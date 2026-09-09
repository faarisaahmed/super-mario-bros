"""Score a trained agent over many runs, and say where it goes wrong.

    python3 tools/evaluate.py                    # the torch checkpoint
    python3 tools/evaluate.py --policy           # the exported policy.json
    python3 tools/evaluate.py --both             # and check they agree
    python3 tools/evaluate.py --episodes 50

A single watched run tells you almost nothing: the level has three pits and
sixteen goombas, and whether a given attempt dies at the second one is mostly
which frame the policy happened to jump on. What matters is the finish rate
over a batch, the time when it does finish, and -- when it does not -- the
distribution of where it stopped and what stopped it.
"""

import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mario_ai as M  # noqa: E402
from mario_env import MarioEnv  # noqa: E402

# Newest first: a speed fine-tune writes to best_model_speed/ so it cannot
# clobber the policy it started from.
CHECKPOINTS = ["best_model_speed/best_model.zip",
               "best_model/best_model.zip", "mario_model.zip"]


def flat_out_frames(env):
    """The floor: how many frames it takes to cover the level's length
    holding right and B on open ground.

    A walking par is the reward's yardstick, but it is a soft one -- what
    "fast" is actually bounded by is running acceleration and top speed. It
    is not quite reachable, since a few jumps have to be taken at less than
    full speed, but nothing can beat it, so a clear can be quoted honestly as
    a multiple of it.
    """
    import pygame
    from mario import Mario
    import smb_physics as smb

    level = env.level
    width = level.width
    grid, real = level.grid, level.grid
    flat = [[0] * width for _ in range(level.height)]
    for row in range(level.height - 2, level.height):
        flat[row] = [4] * width
    level.grid = flat
    try:
        mario = Mario(x=100, y=0, scale=3)
        for _ in range(240):
            mario.set_buttons()
            mario.update(smb.FRAME_TIME, 0, level.solid_at)
            if mario.on_ground:
                break
        frames = 0
        while mario.x < env.finish_x and frames < 10000:
            mario.set_buttons(right=True, b=True)
            mario.update(smb.FRAME_TIME, 0, level.solid_at)
            frames += 1
        return frames
    finally:
        level.grid = real


def torch_actor(path=None):
    from stable_baselines3 import PPO
    src = path or next((p for p in CHECKPOINTS if os.path.exists(p)), None)
    if src is None:
        raise SystemExit(f"no checkpoint found (looked for {CHECKPOINTS})")
    model = PPO.load(src[: -len(".zip")], device="cpu")
    print(f"loaded {src}")
    return lambda obs: int(model.predict(obs, deterministic=True)[0])


def json_actor(path=None):
    policy = M.Policy.load(path)
    print(f"loaded {path or os.path.join('ai', 'policy.json')}")
    return lambda obs: policy.act([float(v) for v in obs])


def evaluate(act, episodes, seed=0, jitter=0):
    env = MarioEnv(seed=seed, start_jitter=jitter)
    outcomes = collections.Counter()
    actions = collections.Counter()
    times, progress, stomps, stops = [], [], [], []

    for episode in range(episodes):
        obs, _ = env.reset(seed=seed + episode)
        done = False
        info = {}
        while not done:
            action = act(obs)
            actions[action] += 1
            obs, _, terminated, truncated, info = env.step(action)
            done = terminated or truncated
        outcomes[info["outcome"]] += 1
        progress.append(info["progress"])
        stomps.append(info["stomps"])
        if info["finished"]:
            times.append(info["steps"])
        else:
            stops.append(info["max_x"])

    return {
        "flat_out": flat_out_frames(env),
        "episodes": episodes,
        "outcomes": outcomes,
        "actions": actions,
        "times": times,
        "progress": progress,
        "stomps": stomps,
        "stops": stops,
        "finish_x": env.finish_x,
        "par": env.par_steps,
        "jitter": jitter,
    }


def report(name, r):
    n = r["episodes"]
    finished = len(r["times"])
    suffix = f", start jittered by up to {r['jitter']}px" if r["jitter"] else ""
    print(f"\n=== {name} — {n} episodes{suffix} ===")
    print(f"finished      : {finished}/{n}  ({finished / n:.0%})")
    if r["times"]:
        best = min(r["times"])
        mean = sum(r["times"]) / len(r["times"])
        worst = max(r["times"])
        print(f"frames        : best {best} ({best / 60:.2f}s), "
              f"mean {mean:.0f} ({mean / 60:.2f}s), worst {worst}")
        print(f"walking par   : {r['par']:.0f} frames ({r['par'] / 60:.2f}s)"
              f"  ->  {r['par'] / mean:.2f}x faster")
        print(f"flat-out floor: {r['flat_out']} frames "
              f"({r['flat_out'] / 60:.2f}s), unreachable but nothing beats it"
              f"  ->  {mean / r['flat_out']:.2f}x the floor")
    print(f"progress      : mean {sum(r['progress']) / n:.1%}, "
          f"best {max(r['progress']):.1%}")
    print(f"stomps        : mean {sum(r['stomps']) / n:.1f} of 16 goombas")
    print("outcomes      : " + ", ".join(
        f"{k} {v}" for k, v in r["outcomes"].most_common()))
    if r["stops"]:
        buckets = collections.Counter(int(x // 480) for x in r["stops"])
        print("stopped near  : " + ", ".join(
            f"x~{b * 480}-{b * 480 + 479}: {c}"
            for b, c in sorted(buckets.items())))
    total = sum(r["actions"].values())
    print("action mix    : " + ", ".join(
        f"{M.ACTION_NAMES[a]} {c / total:.0%}"
        for a, c in r["actions"].most_common(5)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--model", default=None,
                    help="a specific checkpoint, instead of the newest")
    ap.add_argument("--policy", action="store_true",
                    help="score ai/policy.json instead of the checkpoint")
    ap.add_argument("--both", action="store_true",
                    help="score both and check the exported one matches")
    ap.add_argument("--jitter", type=int, default=0,
                    help="vary the start x by up to N pixels, to tell a "
                         "policy apart from a memorised keypress sequence")
    args = ap.parse_args()

    kwargs = dict(episodes=args.episodes, jitter=args.jitter)

    if args.both:
        a = evaluate(torch_actor(args.model), **kwargs)
        b = evaluate(json_actor(), **kwargs)
        report("torch checkpoint", a)
        report("exported policy.json", b)
        same = (len(a["times"]) == len(b["times"])
                and a["outcomes"] == b["outcomes"])
        print(f"\nexport agrees with torch: {same}")
        return 0 if same else 1

    act = json_actor() if args.policy else torch_actor(args.model)
    report("policy.json" if args.policy else "checkpoint",
           evaluate(act, **kwargs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
