"""Measure what a jump can actually clear, by driving the real physics.

In SMB height comes purely from how long A is held, so the hold lengths the
action space offers are what decide which obstacles the agent can reach at
all. Rather than guess them, this walks Mario up to an obstacle, snapshots
every frame he is grounded on the approach, and re-runs the jump from each of
those snapshots -- so "launch positions that clear it" counts real, reachable
states rather than points on a grid.

    python3 tools/jump_sweep.py              # sweep the tall pipe
    python3 tools/jump_sweep.py --profile    # apex/travel per hold, flat ground
    python3 tools/jump_sweep.py --list       # obstacles in the level

It drives mario.Mario against levels/1-1.json, so what it reports includes
collision and is what the agent would actually get.
"""

import argparse
import copy
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((1, 1))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from level_loader import Level  # noqa: E402
from mario import Mario  # noqa: E402
import smb_physics as smb  # noqa: E402

SCALE = 3
TILE = 16 * SCALE
DT = smb.FRAME_TIME
FLOOR_ROWS = 2          # 1-1's ground is two tiles deep


def load_level():
    return Level("levels/1-1.json", "tileset.json")


def flat_level(width=80):
    """A featureless floor, for measuring a jump with nothing to hit."""
    level = load_level()
    level.width = width
    level.grid = [[0] * width for _ in range(level.height)]
    for row in range(level.height - FLOOR_ROWS, level.height):
        level.grid[row] = [4] * width
    return level


def settle(level, x):
    """Mario standing still on the ground at world x."""
    mario = Mario(x=x, y=0, scale=SCALE)
    for _ in range(240):
        mario.set_buttons()
        mario.update(DT, 0, level.solid_at)
        if mario.on_ground:
            break
    return mario


def approach(level, start_x, stop_x, run, from_mario=None):
    """Walk/run right from start_x, snapshotting every grounded frame between
    the two x values. Those snapshots are the launch positions."""
    mario = copy.deepcopy(from_mario) if from_mario is not None else settle(level, start_x)
    shots = []
    stalled = 0
    last_x = mario.x
    for _ in range(2000):
        mario.set_buttons(right=True, b=run)
        mario.update(DT, 0, level.solid_at)
        if mario.y > level.height * TILE:
            break
        if mario.on_ground and start_x <= mario.x <= stop_x:
            shots.append(copy.deepcopy(mario))
        if mario.x > stop_x:
            break
        # He has walked into something and is going nowhere; stop piling up
        # identical snapshots against it.
        stalled = stalled + 1 if mario.x <= last_x else 0
        if stalled > 20:
            break
        last_x = max(last_x, mario.x)
    return shots


def jump_from(level, mario, hold, run, limit=400):
    """Jump from this exact state, A held `hold` frames, right (and B) held
    throughout.

    Returns where he came down as (x, y), or None if he fell out of the
    level. The y matters: landing on top of a pipe is a perfectly good
    outcome -- you walk off the far side -- and counting only landings past
    it would call a successful jump a failure.
    """
    mario = copy.deepcopy(mario)
    for frame in range(limit):
        mario.set_buttons(right=True, a=frame < hold, b=run)
        mario.update(DT, 0, level.solid_at)
        if mario.y > level.height * TILE:
            return None
        if frame > 4 and mario.on_ground:
            return mario.x, mario.y
    return mario.x, mario.y


def column_height(level, col):
    n = 0
    for row in range(level.height - 1, -1, -1):
        if level.solid_at(col, row):
            n += 1
        elif n:
            break
    return n


def obstacles(level, min_above=2):
    """Runs of columns standing at least `min_above` tiles proud of the floor."""
    out = []
    col = 0
    while col < level.width:
        if column_height(level, col) - FLOOR_ROWS >= min_above:
            start = col
            while (col < level.width
                   and column_height(level, col) - FLOOR_ROWS >= min_above):
                col += 1
            tallest = max(column_height(level, c) for c in range(start, col))
            out.append((start, col - 1, tallest - FLOOR_ROWS))
        else:
            col += 1
    return out


def runway(level, start_col, found):
    """Ground the agent can actually build speed on before this obstacle:
    from just past the previous obstacle up to the wall itself."""
    previous = [o for o in found if o[1] < start_col]
    first_col = (previous[-1][1] + 1) if previous else 1
    return first_col * TILE, start_col * TILE - TILE


def launch_pads(level, start_col, found):
    """Every surface a jump at this obstacle can start from: the ground on
    the runway, and the top of the previous obstacle if he can stand on it.
    A pipe you can land on is a launch platform three tiles up, which is a
    different jump from the same one taken off the floor."""
    pads = [("ground", *runway(level, start_col, found))]
    previous = [o for o in found if o[1] < start_col]
    if previous:
        prev_start, prev_end, height = previous[-1]
        if height >= 2:
            pads.append((f"atop cols {prev_start}-{prev_end}",
                         prev_start * TILE, prev_end * TILE + TILE - 1))
    return pads


def approach_from_pad(level, pad, run, level_height_px):
    """Snapshots along one launch pad. For a raised pad he is dropped onto
    it first, because he cannot walk there from the floor."""
    kind, start_x, stop_x = pad
    if kind == "ground":
        return approach(level, start_x, stop_x, run)
    mario = Mario(x=start_x, y=0, scale=SCALE)
    for _ in range(240):
        mario.set_buttons()
        mario.update(DT, 0, level.solid_at)
        if mario.on_ground:
            break
    if not mario.on_ground or mario.y > level_height_px:
        return []
    return approach(level, start_x, stop_x, run, from_mario=mario)


def sweep(level, start_col, end_col, holds, found):
    right_edge = (end_col + 1) * TILE
    top_y = (level.height - column_height(level, start_col)) * TILE
    start_x, stop_x = runway(level, start_col, found)

    print(f"obstacle: cols {start_col}-{end_col}, "
          f"{column_height(level, start_col) - FLOOR_ROWS} tiles above the floor")
    print(f"runway:   x {int(start_x)} -> {int(stop_x)}  "
          f"({(stop_x - start_x) / TILE:.0f} clear tiles between the previous "
          f"obstacle and this one)")
    print(f"cleared:  landing x > {int(right_edge)}, "
          f"or on top (y <= {int(top_y)})")
    print()

    level_px = level.height * TILE
    for pad in launch_pads(level, start_col, found):
        shots = {run: approach_from_pad(level, pad, run, level_px)
                 for run in (False, True)}
        if not shots[False] and not shots[True]:
            continue

        print(f"launching from {pad[0]}:")
        for run in (False, True):
            top = max((s.x_speed_absolute for s in shots[run]), default=0)
            label = "run " if run else "walk"
            print(f"  {label}: {len(shots[run]):>4} grounded launch positions, "
                  f"top speed reached {top / 16:.2f} px/frame "
                  f"(max {smb.MAX_RIGHT_X_SPEED[0 if run else 1] / 16:.2f})")
        print()

        print(f"{'hold':>5} | {'walking':^28} | {'running':^28}")
        print(f"{'':>5} | {'past':>7} {'ontop':>7} {'of':>5} {'furthest':>7} "
              f"| {'past':>7} {'ontop':>7} {'of':>5} {'furthest':>7}")
        print("-" * 72)

        for hold in holds:
            cells = []
            for run in (False, True):
                past = ontop = furthest = 0
                for shot in shots[run]:
                    landed = jump_from(level, shot, hold, run)
                    if landed is None:
                        continue
                    x, y = landed
                    furthest = max(furthest, x)
                    if x > right_edge:
                        past += 1
                    elif y <= top_y + 1 and x >= start_col * TILE:
                        ontop += 1
                cells.append((past, ontop, len(shots[run]), int(furthest)))
            line = " | ".join(f"{p:>7} {t:>7} {n:>5} {f:>7}" for p, t, n, f in cells)
            print(f"{hold:>5} | {line}")
        print()


def profile(level, holds):
    print("On flat ground with nothing overhead. Apex and travel in tiles.\n")
    print(f"{'hold':>5} | {'walking':^26} | {'running':^26}")
    print(f"{'':>5} | {'apex':>8} {'travel':>8} {'air':>7} "
          f"| {'apex':>8} {'travel':>8} {'air':>7}")
    print("-" * 66)
    launch_x = 20 * TILE
    approaches = {run: approach(level, 4 * TILE, launch_x, run)[-1]
                  for run in (False, True)}
    for hold in holds:
        cells = []
        for run in (False, True):
            mario = copy.deepcopy(approaches[run])
            y0, x0 = mario.y, mario.x
            apex = y0
            frames = 0
            for frame in range(400):
                mario.set_buttons(right=True, a=frame < hold, b=run)
                mario.update(DT, 0, level.solid_at)
                frames += 1
                apex = min(apex, mario.y)
                if frame > 4 and mario.on_ground:
                    break
            cells.append(((y0 - apex) / TILE, (mario.x - x0) / TILE, frames))
        line = " | ".join(f"{a:>8.2f} {d:>8.2f} {f:>7}" for a, d, f in cells)
        print(f"{hold:>5} | {line}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--holds", type=int, nargs="+",
                    default=[6, 10, 14, 18, 22, 26, 30, 34])
    ap.add_argument("--col", type=int, default=None,
                    help="obstacle column to sweep (default: the tallest)")
    args = ap.parse_args()

    if args.profile:
        profile(flat_level(), args.holds)
        return

    level = load_level()
    found = obstacles(level)
    if args.list:
        print(f"{'cols':>10} {'tiles above floor':>18} {'x':>8}")
        for a, b, h in found:
            print(f"{a:>4}-{b:<5} {h:>18} {a * TILE:>8}")
        return

    if args.col is not None:
        target = min(found, key=lambda o: abs(o[0] - args.col))
    else:
        target = max(found, key=lambda o: o[2])
    sweep(level, target[0], target[1], args.holds, found)


if __name__ == "__main__":
    main()
