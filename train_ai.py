import os

from stable_baselines3 import PPO
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.callbacks import EvalCallback

from mario_env import MarioEnv

# How long to train. Overridable so the launcher / CLI can shorten it:
#   MARIO_TIMESTEPS=500000 python3 train_ai.py
TIMESTEPS = int(os.environ.get("MARIO_TIMESTEPS", 2_000_000))

# Separate env instances for training and periodic evaluation.
env = Monitor(MarioEnv(render_mode=False))
eval_env = Monitor(MarioEnv(render_mode=False))

# EvalCallback rolls out the current policy every eval_freq steps and keeps a
# copy of whichever one scored best -> ./best_model/best_model.zip. That is the
# "best model" the watcher shows after training, not just the last checkpoint.
eval_callback = EvalCallback(
    eval_env,
    best_model_save_path="./best_model/",
    log_path="./logs/eval/",
    eval_freq=25_000,
    n_eval_episodes=5,
    deterministic=True,
    render=False,
)

model = PPO(
    "MlpPolicy",
    env,
    verbose=1,
    learning_rate=0.0003,
    n_steps=4096,
    batch_size=128,
    gamma=0.99,
    ent_coef=0.02,
    vf_coef=0.5,
    clip_range=0.2,
    tensorboard_log="./logs/",
)

model.learn(total_timesteps=TIMESTEPS, callback=eval_callback)

# Keep the final policy too, for backwards compatibility.
model.save("mario_model")

# Guarantee best_model exists even if eval never triggered (very short runs).
if not os.path.exists("best_model/best_model.zip"):
    os.makedirs("best_model", exist_ok=True)
    model.save("best_model/best_model")

print("TRAINING_COMPLETE")
