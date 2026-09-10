"""Train the PPO agent on 1-1.

    python3 train_ai.py
    MARIO_TIMESTEPS=500000 python3 train_ai.py      # a short run
    MARIO_ENVS=4 python3 train_ai.py                # fewer workers

Three things here are doing the work that the previous run was missing.

**Parallel rollouts.** Eight environments in worker processes instead of one
in-process. PPO is on-policy, so wall-clock is almost entirely rollout
collection, and the batch that comes back is decorrelated instead of being
one long trajectory.

**A random-start curriculum.** On-policy learning only ever improves on
states it visits. If every rollout ends at the same obstacle then nothing
past it is ever in a batch and no amount of extra timesteps helps -- the tail
of the level is not hard to learn, it is *absent*. So early episodes start at
a random point along 1-1 and that fraction is annealed to zero, which means
the last of training is spent on the real task while the middle of it has
already seen the end of the level.

**Schedules.** Learning rate and entropy both decay. High entropy early is
what finds the run-jump at all; keeping it high is what stops the timing from
ever getting sharp.
"""

import os

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, EvalCallback
from stable_baselines3.common.vec_env import (
    SubprocVecEnv,
    VecMonitor,
    VecNormalize,
)

from mario_env import MarioEnv

TIMESTEPS = int(os.environ.get("MARIO_TIMESTEPS", 6_000_000))
N_ENVS = int(os.environ.get("MARIO_ENVS", 8))

# Continue from an existing checkpoint instead of starting cold. Getting the
# agent round the level at all and then getting it round quickly are two
# different problems, and the second one is a fine-tune of the first rather
# than a fresh six million steps.
#   MARIO_RESUME=best_model/best_model.zip MARIO_SPEED_BONUS=0.15 \
#   MARIO_TIME_COST=0.12 MARIO_TIMESTEPS=2000000 python3 train_ai.py
RESUME = os.environ.get("MARIO_RESUME", "")
# Reward statistics to restore when resuming, and where this run writes its
# own. A fine-tune writes beside its own checkpoints for the same reason it
# does not share best_model/: everything it produces is conditional on a
# reward it was given on the command line, and dropping that on top of the
# cold run's artifacts would silently restore the wrong normaliser -- and
# the wrong final checkpoint -- to the next run that resumes.
STATS_IN = os.environ.get("MARIO_STATS", "logs/vecnormalize.pkl")
# Where EvalCallback keeps the best checkpoint. A fine-tune writes somewhere
# else by default so a run that trades away reliability for speed cannot
# overwrite the policy it started from.
BEST_DIR = os.environ.get(
    "MARIO_BEST_DIR", "./best_model_speed/" if RESUME else "./best_model/")
STATS_OUT = (os.path.join(BEST_DIR, "vecnormalize.pkl") if RESUME
             else "logs/vecnormalize.pkl")
FINAL_OUT = (os.path.join(BEST_DIR, "final_model") if RESUME
             else "mario_model")
SPEED_BONUS = float(os.environ.get("MARIO_SPEED_BONUS", 0.05))
TIME_COST = float(os.environ.get("MARIO_TIME_COST", 0.05))

# Fraction of training over which random starts are annealed away, and the
# fraction of episodes that start somewhere other than the beginning at the
# very start of training.
CURRICULUM_FRACTION = 0.6
START_RANDOM_PROB = 0.5


# A resumed run skips the curriculum entirely, and it has to be off from the
# very first transition. Curriculum only reaches its first
# set_random_start_prob() after 2048 callback calls, which across eight envs
# is 16k timesteps -- four whole rollouts of the batch dilution the fine-tune
# exists to avoid.
COLD_START_PROB = 0.0 if RESUME else START_RANDOM_PROB


def make_env(rank, random_start_prob=None, start_jitter=0):
    prob = COLD_START_PROB if random_start_prob is None else random_start_prob

    def _init():
        return MarioEnv(random_start_prob=prob,
                        start_jitter=start_jitter,
                        speed_bonus=SPEED_BONUS, time_cost=TIME_COST,
                        seed=1000 + rank)
    return _init


def linear(start, end):
    """SB3 passes progress_remaining: 1.0 at the start, 0.0 at the end."""
    def schedule(progress_remaining):
        return end + (start - end) * progress_remaining
    return schedule


class Curriculum(BaseCallback):
    """Anneal the random-start probability to zero, and decay entropy.

    Entropy is not a schedulable hyperparameter in SB3 the way the learning
    rate is, so it gets set on the model directly.
    """

    def __init__(self, total_timesteps, start_prob=START_RANDOM_PROB,
                 ent_start=0.02, ent_end=0.003, verbose=0):
        super().__init__(verbose)
        self.total = total_timesteps
        self.start_prob = start_prob
        self.ent_start = ent_start
        self.ent_end = ent_end

    def _on_step(self):
        progress = min(self.num_timesteps / self.total, 1.0)

        share = max(0.0, 1.0 - progress / CURRICULUM_FRACTION)
        prob = self.start_prob * share
        if self.n_calls % 2048 == 0:
            self.training_env.env_method("set_random_start_prob", prob)
            self.logger.record("curriculum/random_start_prob", prob)

        self.model.ent_coef = (self.ent_end
                               + (self.ent_start - self.ent_end) * (1 - progress))
        self.logger.record("curriculum/ent_coef", self.model.ent_coef)
        return True


class ProgressLog(BaseCallback):
    """Log what the run is actually judged on.

    Episode reward is a proxy and a moving one -- the reward function changes
    what it pays for as the agent gets further. How much of the level it
    covers, how often it finishes and how long that takes are the numbers
    that mean the same thing on day one and at the end.
    """

    def __init__(self, window=100, verbose=0):
        super().__init__(verbose)
        self.window = window
        self.progress = []
        self.finished = []
        self.times = []
        self.stomps = []
        self.best_progress = 0.0

    def _on_step(self):
        for info, done in zip(self.locals["infos"], self.locals["dones"]):
            if not done or "progress" not in info:
                continue
            self.progress.append(info["progress"])
            self.stomps.append(info["stomps"])
            # Only episodes that began at the start of the level say anything
            # about clearing it; a curriculum episode can spawn past the last
            # obstacle and walk to the flag.
            if info.get("from_start"):
                self.finished.append(1.0 if info["finished"] else 0.0)
                if info["finished"]:
                    self.times.append(info["steps"])
            self.best_progress = max(self.best_progress, info["progress"])
            for series in (self.progress, self.finished, self.stomps, self.times):
                del series[:-self.window]

        if self.progress:
            self.logger.record("mario/progress_mean", float(np.mean(self.progress)))
            self.logger.record("mario/progress_best", self.best_progress)
            self.logger.record("mario/stomps_mean", float(np.mean(self.stomps)))
        if self.finished:
            self.logger.record("mario/finish_rate", float(np.mean(self.finished)))
        if self.times:
            self.logger.record("mario/finish_frames", float(np.mean(self.times)))
        return True


def main():
    venv = VecMonitor(SubprocVecEnv([make_env(i) for i in range(N_ENVS)]))

    # Observations are already relative and normalised by hand in
    # mario_ai.observe, and they have to stay that way: the browser build
    # runs that function and no normaliser, so any running-mean shift applied
    # here would not exist in Pyodide and the exported policy would be fed
    # different numbers from the ones it trained on. Rewards do get
    # normalised, and clip_reward is raised because the default of 10 clips
    # the completion bonus -- finishing pays 300-1000 depending on the time,
    # and once both ends of that range normalise above the clip they arrive
    # as the same number, which deletes exactly the signal saying that
    # finishing sooner is better.
    if RESUME and os.path.exists(STATS_IN):
        # Resuming with a fresh normaliser means the first few thousand
        # steps are scaled by statistics that have not converged, which
        # arrives as enormous advantages and walks the policy away from the
        # one being resumed before it has learnt anything.
        print(f"restoring reward statistics from {STATS_IN}")
        env = VecNormalize.load(STATS_IN, venv)
        env.training = True
    else:
        env = VecNormalize(venv, norm_obs=False, norm_reward=True,
                           gamma=0.995)
    env.norm_obs = False
    env.clip_reward = 50.0

    # Evaluation always starts at the beginning -- the curriculum is a
    # training aid, and a score measured from a random midpoint is not
    # comparable to anything.
    # ...and it jitters the start. The level is deterministic and a greedy
    # policy is deterministic, so without a nudge all five eval episodes are
    # the same episode, and "best model" gets picked off a single trajectory
    # that may just have been lucky.
    eval_env = VecNormalize(
        VecMonitor(SubprocVecEnv([
            make_env(500, random_start_prob=0.0, start_jitter=60)])),
        norm_obs=False,
        norm_reward=False,
        training=False,
        gamma=0.995,
    )

    hyper = dict(
        learning_rate=linear(3e-4, 5e-5),
        n_steps=512,                 # x8 envs = 4096 transitions a rollout
        batch_size=256,
        n_epochs=10,
        # A clear takes 1400-2200 frames and the completion bonus is paid at
        # the very end of it. At gamma=0.99 the effective horizon is about a
        # hundred steps, so that bonus is invisible from anywhere that
        # matters; 0.995 doubles the horizon without destabilising the value
        # function the way 0.999 does on episodes this long.
        gamma=0.995,
        gae_lambda=0.95,
        ent_coef=0.02,               # overwritten each step by Curriculum
        vf_coef=0.5,
        clip_range=0.2,
        max_grad_norm=0.5,
    )

    if RESUME:
        # Fine-tuning: keep the policy, lower the learning rate and the
        # exploration, and skip the curriculum -- it already knows the whole
        # level, so random starts would only dilute the batch.
        print(f"resuming from {RESUME}")
        model = PPO.load(RESUME.removesuffix(".zip"), env=env, device="cpu",
                         **{**hyper,
                            "learning_rate": linear(1e-4, 1e-5),
                            "ent_coef": 0.004,
                            "tensorboard_log": "./logs/"})
        curriculum = Curriculum(TIMESTEPS, start_prob=0.0,
                                ent_start=0.004, ent_end=0.001)
    else:
        model = PPO(
            "MlpPolicy",
            env,
            verbose=1,
            policy_kwargs=dict(net_arch=[64, 64]),   # see mario_ai.Policy
            tensorboard_log="./logs/",
            **hyper,
        )
        curriculum = Curriculum(TIMESTEPS)

    callbacks = [
        curriculum,
        ProgressLog(),
        EvalCallback(
            eval_env,
            best_model_save_path=BEST_DIR,
            log_path="./logs/eval/",
            eval_freq=max(25_000 // N_ENVS, 1),
            n_eval_episodes=5,
            deterministic=True,
            render=False,
        ),
    ]

    model.learn(total_timesteps=TIMESTEPS, callback=callbacks)

    os.makedirs(os.path.dirname(FINAL_OUT) or ".", exist_ok=True)
    model.save(FINAL_OUT)
    env.save(STATS_OUT)

    # Guarantee best_model exists even if eval never triggered (short runs).
    if not os.path.exists(os.path.join(BEST_DIR, "best_model.zip")):
        os.makedirs(BEST_DIR, exist_ok=True)
        model.save(os.path.join(BEST_DIR, "best_model"))

    env.close()
    eval_env.close()
    print("TRAINING_COMPLETE")


if __name__ == "__main__":
    main()
