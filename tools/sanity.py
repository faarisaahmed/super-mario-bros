"""Assertions about the environment, so a broken one fails here.

Training is slow and its failures are quiet -- a reward that never fires or
an action that does not do what its name says costs hours before anyone
notices. Each check below is a claim the reward function or the action space
depends on, exercised against the real physics.

    python3 tools/sanity.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mario_ai as M  # noqa: E402
import smb_physics as smb  # noqa: E402
from goomba import Goomba  # noqa: E402
from mario_env import SCALE, MarioEnv, TILE_PX  # noqa: E402

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    mark = "ok  " if condition else "FAIL"
    print(f"  {mark}  {name}" + (f"   [{detail}]" if detail else ""))


def surface_row(env, col):
    for row in range(env.level.height):
        if env.level.solid_at(col, row):
            return row
    raise ValueError(f"column {col} is a pit, nothing to stand on")


def spawn_at(env, col, row_offset=3):
    """Put Mario on the surface of a column and settle him onto it."""
    surface = surface_row(env, col)
    env.reset()
    env.mario.x = col * TILE_PX
    env.mario.y = (surface - row_offset) * TILE_PX
    env.start_x = env.mario.x
    env.prev_x = env.mario.x
    env.max_x = env.mario.x
    env.par_steps = max(env.finish_x - env.mario.x, 1.0) / 4.5
    for _ in range(60):
        if env.mario.on_ground:
            break
        env.step(0)
    return env


def main():
    print("action space")
    env = MarioEnv(seed=0)
    env.reset()
    senses = M.MarioSenses()
    for index, name in enumerate(M.ACTION_NAMES):
        senses.reset()
        senses.apply_action(env.mario, env.level, index, True)
        dx, hold, run = M._ACTIONS[index]
        m = env.mario
        check(f"{name}: buttons match the table",
              m.btn_right == (dx > 0) and m.btn_left == (dx < 0)
              and m.btn_b == run and m.btn_a == (hold is not None))
    act_names = {k: v for k, v in vars(M.ACT).items() if not k.startswith("_")}
    check("ACT names cover every action exactly once",
          sorted(act_names.values()) == list(range(M.ACTION_SIZE)),
          f"{len(act_names)} names, {M.ACTION_SIZE} actions")
    check("ACT names match ACTION_NAMES",
          all(M.ACTION_NAMES[v].replace(" ", "_").replace("-", "_").upper() == k
              for k, v in act_names.items()))
    check("some action holds B with a full jump",
          any(hold == M.FULL_JUMP_HOLD and run for _, hold, run in M._ACTIONS),
          "a run-jump is expressible")

    print("\njump holds")
    check("FULL_JUMP_HOLD is past the point where height saturates",
          M.FULL_JUMP_HOLD >= 30, f"hold={M.FULL_JUMP_HOLD}")
    check("SHORT is genuinely shorter", M.SHORT_JUMP_HOLD < M.FULL_JUMP_HOLD)

    # B stays down for the whole arc of a jump that started as a run-jump.
    env.reset()
    senses.reset()
    senses.apply_action(env.mario, env.level, 7, True)      # run-jump
    held = []
    for _ in range(M.FULL_JUMP_HOLD):
        senses.apply_action(env.mario, env.level, 0, False)  # policy picks idle
        held.append(env.mario.btn_b)
    check("B is latched through a run-jump even if the policy stops asking",
          all(held), f"{sum(held)}/{len(held)} frames")

    print("\nreward: goombas")

    def lone_goomba(env, col=195):
        """One stationary goomba on open ground, and nothing else.

        Picking one out of the level keeps producing fixtures that test the
        level rather than the reward: 1-1's first goomba stands under the
        brick row, and the next is flush against a pipe so it turns round on
        frame one and walks away. Building the situation is the only way to
        be sure what is being measured.
        """
        surface = surface_row(env, col)
        g = Goomba(col, surface - 1, env.level.tile_size, SCALE)
        g.x_speed = 0                       # stand still; locomotion is not
        g.active = True                     # what these checks are about
        env.goombas = [g]
        return g

    def place_above(env, goomba, tiles_up):
        """Mario hanging directly over a goomba's centre, so a drop with no
        horizontal input lands on its head."""
        env.mario.x = goomba.x + (goomba.width * goomba.scale
                                  - env.mario.width * env.mario.scale) / 2
        env.mario.y = goomba.y - tiles_up * TILE_PX
        env.camera_x = max(0.0, env.mario.x - 384)
        env.prev_x = env.max_x = env.mario.x

    env = MarioEnv(seed=0)
    env.reset()
    goomba = lone_goomba(env)
    place_above(env, goomba, 4)
    stomp_reward = 0.0
    info = {"stomps": 0}
    for _ in range(120):
        _, r, term, _, info = env.step(0)          # straight down, no steering
        stomp_reward += r
        if info["stomps"] or term:
            break
    check("landing on a goomba stomps it and pays",
          info["stomps"] == 1 and stomp_reward > 5,
          f"stomps={info['stomps']} reward={stomp_reward:.1f}")
    check("the stomped goomba stops being dangerous",
          not goomba.is_dangerous())
    check("a stomp bounces Mario back up",
          env.mario.y_speed < 0, f"y_speed={env.mario.y_speed}")

    env = MarioEnv(seed=0)
    env.reset()
    goomba = lone_goomba(env)
    env.mario.x = goomba.x - 3 * TILE_PX
    env.mario.y = goomba.y
    env.camera_x = max(0.0, env.mario.x - 384)
    env.prev_x = env.max_x = env.mario.x
    walked = 0.0
    term = False
    for _ in range(200):
        _, r, term, _, _ = env.step(1)
        walked += r
        if term:
            break
    check("walking into a goomba ends the episode at a loss",
          term and walked < -50, f"reward={walked:.1f} terminated={term}")

    print("\nreward: pits and the flag")
    env = MarioEnv(seed=0)
    spawn_at(env, 67)                       # the ledge before the pit at 68-69
    fell = 0.0
    for _ in range(200):
        _, r, term, _, _ = env.step(1)      # walk straight off it
        fell += r
        if term:
            break
    check("falling in a pit ends the episode at a loss",
          term and fell < -50, f"reward={fell:.1f}")

    env = MarioEnv(seed=0)
    spawn_at(env, 200)                      # past the flagpole, on the run-in
    total = 0.0
    for _ in range(400):
        _, r, term, _, info = env.step(3)
        total += r
        if term:
            break
    check("reaching the end terminates and pays the completion bonus",
          term and info["finished"] and total > 300,
          f"reward={total:.1f} frames={info['steps']}")

    print("\nfinishing faster is worth more")
    scores = {}
    for label, action in (("walking", 1), ("running", 3)):
        env = MarioEnv(seed=0)
        spawn_at(env, 200)
        total = 0.0
        for _ in range(600):
            _, r, term, _, info = env.step(action)
            total += r
            if term:
                break
        scores[label] = (total, info["steps"], info["finished"])
    check("a running clear scores above a walking one",
          scores["running"][0] > scores["walking"][0],
          f"run {scores['running'][0]:.0f} in {scores['running'][1]}f vs "
          f"walk {scores['walking'][0]:.0f} in {scores['walking'][1]}f")

    print("\nobservations")
    env = MarioEnv(seed=0)
    obs, _ = env.reset()
    check("observation is the advertised width", len(obs) == M.OBS_SIZE,
          f"{len(obs)} == {M.OBS_SIZE}")
    lo = hi = 0.0
    for _ in range(1500):
        obs, _, term, trunc, _ = env.step(env.action_space.sample())
        lo, hi = min(lo, float(obs.min())), max(hi, float(obs.max()))
        if term or trunc:
            env.reset()
    check("observations stay inside the declared Box",
          lo >= -10.0 and hi <= 10.0, f"range [{lo:.2f}, {hi:.2f}]")
    check("observations stay roughly normalised",
          lo >= -3.0 and hi <= 3.0, f"range [{lo:.2f}, {hi:.2f}]")

    print("\na step down is not a pit")
    env = MarioEnv(seed=0)
    spawn_at(env, 46, row_offset=1)         # stood on top of the tall pipe
    obs = env._get_state()
    check("stood on a pipe: a gap is reported ahead",
          obs[M.OBS.GAP_WIDTH] > 0.0, f"gap width {obs[M.OBS.GAP_WIDTH]:.2f}")
    check("stood on a pipe: no bottomless pit is reported",
          obs[M.OBS.PIT_WIDTH] == 0.0, f"pit width {obs[M.OBS.PIT_WIDTH]:.2f}")
    spawn_at(env, 66)                       # flat ground before the real pit
    obs = env._get_state()
    check("approaching the real pit: it is reported",
          obs[M.OBS.PIT_WIDTH] > 0.0, f"pit width {obs[M.OBS.PIT_WIDTH]:.2f}")

    fields = [v for k, v in vars(M.OBS).items() if not k.startswith("_")]
    flat = sorted(i for f in fields for i in (f if isinstance(f, tuple) else (f,)))
    check("OBS names cover every slot exactly once",
          flat == list(range(M.OBS_SIZE)), f"{len(flat)} names, {M.OBS_SIZE} slots")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for name in FAIL:
            print(f"  failed: {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
