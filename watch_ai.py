"""Watch the trained agent play, in a real window.

    python3 watch_ai.py                # the torch checkpoint
    python3 watch_ai.py --policy       # the exported ai/policy.json instead

Use `--policy` to check what the browser will actually run: it drives the
same plain-Python forward pass the web build uses, so a discrepancy between
the two shows up here rather than after a deploy. For numbers rather than a
window, see tools/evaluate.py.
"""

import argparse
import os

import pygame

from mario_env import MarioEnv


def load_actor(use_policy_json):
    if use_policy_json:
        from mario_ai import Policy
        policy = Policy.load()
        print("driving with ai/policy.json (the browser's forward pass)")
        return lambda obs: policy.act([float(v) for v in obs])

    from stable_baselines3 import PPO
    # best_model is updated throughout training, so it is the best-so-far
    # even if training was stopped early.
    for path in ("best_model_speed/best_model.zip",
                 "best_model/best_model.zip", "mario_model.zip"):
        if os.path.exists(path):
            model = PPO.load(path[: -len(".zip")])
            print(f"driving with {path}")
            return lambda obs: model.predict(obs, deterministic=True)[0]
    raise SystemExit("No trained model found. Run train_ai.py first.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", action="store_true")
    args = ap.parse_args()

    act = load_actor(args.policy)
    env = MarioEnv(render_mode=True)
    obs, _ = env.reset()
    run = 0

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return

        obs, _, terminated, truncated, info = env.step(act(obs))
        env.render()

        if terminated or truncated:
            run += 1
            print(f"run {run:>3}  {info['outcome']:<8} "
                  f"x={info['max_x']:>6.0f} ({info['progress']:>5.1%})  "
                  f"{info['steps']:>4} frames  {info['stomps']} stomps")
            obs, _ = env.reset()


if __name__ == "__main__":
    main()
