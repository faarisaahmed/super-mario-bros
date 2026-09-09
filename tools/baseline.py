"""A hand-written policy, as a reference the trained one has to beat.

Nothing here is learned: it is a dozen if-statements over the same
observation vector PPO gets. It exists for two reasons. It proves the action
space and the environment can actually finish the level, so a failure to
learn is a learning problem rather than an impossible task; and it gives a
number -- time, deaths, stomps -- that "the agent is good" has to mean
something against.

    python3 tools/baseline.py            # one run, summarised
    python3 tools/baseline.py --trace    # every decision
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mario_ai as M  # noqa: E402
from mario_env import MarioEnv  # noqa: E402

TILE = 48.0


def decide(o):
    F = M.OBS
    on_ground = o[F.ON_GROUND] > 0.5
    wall = max(o[i] for i in F.WALL_AHEAD)
    obstacle_tiles = o[F.OBSTACLE_HEIGHT] * M.MAX_OBSTACLE_TILES
    pit_px = o[F.PIT_DIST] * M.LOOK
    run_clears = o[F.RUN_CLEARS_PIT]
    over_pit = o[F.OVER_PIT] > 0.5
    threat_px = o[F.THREAT_DX] * M.LOOK
    threat_dy = o[F.THREAT_DY]

    # Airborne: hold right and B. The jump's hold length was already latched
    # when it started, so there is nothing else to decide until he lands.
    A = M.ACT
    if not on_ground:
        return A.RUN_RIGHT

    # A pit inside two tiles, and a run-jump would land past it.
    if 0.0 <= pit_px < 2.0 * TILE and run_clears > 0.0:
        return A.RUN_JUMP_RIGHT
    if over_pit:
        return A.RUN_JUMP_RIGHT

    # A goomba on the same level, close enough to matter.
    if 0.0 < threat_px < 2.5 * TILE and abs(threat_dy) < 0.35:
        return A.RUN_HOP_RIGHT if threat_px < 1.5 * TILE else A.RUN_JUMP_RIGHT

    # Something to climb. Only the tall pipes need a full run-jump.
    if wall > 0.5:
        return A.RUN_JUMP_RIGHT if obstacle_tiles >= 3.0 else A.HOP_RIGHT

    return A.RUN_RIGHT


def run(trace=False, seed=0):
    env = MarioEnv(seed=seed)
    obs, _ = env.reset(seed=seed)
    done = False
    info = {}
    while not done:
        action = decide(obs)
        if trace and env._steps % 15 == 0:
            F = M.OBS
            print(f"  x={env.mario.x:>6.0f} act={M.ACTION_NAMES[action]:<15} "
                  f"pit={obs[F.PIT_DIST] * M.LOOK:>6.1f} "
                  f"runclr={obs[F.RUN_CLEARS_PIT]:>5.2f} "
                  f"wall={max(obs[i] for i in F.WALL_AHEAD):.0f} "
                  f"h={obs[F.OBSTACLE_HEIGHT] * M.MAX_OBSTACLE_TILES:.1f} "
                  f"threat={obs[F.THREAT_DX] * M.LOOK:>6.1f}")
        obs, _, terminated, truncated, info = env.step(action)
        done = terminated or truncated
    return env, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", action="store_true")
    args = ap.parse_args()

    env, info = run(trace=args.trace)
    print(f"\nfinished : {info['finished']}")
    print(f"progress : {info['progress']:.1%}  (max x {info['max_x']:.0f} "
          f"of {env.finish_x:.0f})")
    print(f"frames   : {info['steps']}  (par, a pure walk, is "
          f"{env.par_steps:.0f})")
    print(f"stomps   : {info['stomps']}")
    if info["finished"]:
        print(f"time     : {info['steps'] / 60.0:.2f}s at 60fps")


if __name__ == "__main__":
    main()
