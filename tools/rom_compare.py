"""
rom_compare.py -- diff this engine's physics against the real cartridge, frame
by frame, with no emulator install and no manual play.

nes-py runs the ROM in-process, so we can drive it with a scripted button
sequence, read SMB's own physics variables straight out of RAM each frame, and
push the identical sequence through this project's Mario.

    python3 tools/rom_compare.py [path-to-rom]

What is compared are SMB's state bytes -- Player_X_Speed, Player_X_MoveForce,
Player_Y_Speed, Player_Y_MoveForce -- not screen positions. Those four *are*
the physics: if they agree every frame under identical input, the port is
exact. Positions additionally depend on the collision model, which this
project deliberately does not reproduce (docs/physics.md).

Scenarios therefore keep Mario clear of scenery: jumps happen on the spot, and
horizontal runs are short enough to stay on the flat opening of 1-1.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nespy_compat  # noqa: F401  (patches nes-py for NumPy 2)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((8, 8))

from nes_py import NESEnv          # noqa: E402
from mario import Mario            # noqa: E402
import smb_physics as smb          # noqa: E402

DEFAULT_ROM = "~/roms/Super Mario Bros. (Japan, USA).nes"
SCALE = 3

# Our scripts use the hardware bit order the disassembly documents
# (smbdis.asm:645-652); nes-py reverses it, so translate on the way in.
HW_RIGHT, HW_LEFT, HW_A, HW_B, HW_START = 0x01, 0x02, 0x80, 0x40, 0x10
NP_RIGHT, NP_LEFT, NP_A, NP_B, NP_START = 0x80, 0x40, 0x01, 0x02, 0x08


def to_nespy(hw):
    out = 0
    if hw & HW_RIGHT: out |= NP_RIGHT
    if hw & HW_LEFT:  out |= NP_LEFT
    if hw & HW_A:     out |= NP_A
    if hw & HW_B:     out |= NP_B
    if hw & HW_START: out |= NP_START
    return out


# RAM addresses, from the disassembly's defines (smbdis.asm:50-391).
RAM = {
    "game_engine_sub": 0x0E, "player_state": 0x1D, "facing_dir": 0x33,
    "moving_dir": 0x45, "x_speed": 0x57, "y_speed": 0x9F,
    "x_speed_abs": 0x700, "running_speed": 0x703, "x_moveforce": 0x705,
    "vertical_force": 0x709, "vert_force_down": 0x70A, "running_timer": 0x783,
    "y_moveforce": 0x433, "ymf_dummy": 0x416, "x_position": 0x86,
    "y_position": 0xCE,
}

# The four bytes that constitute "the physics", plus the vertical position --
# now that collision is the original's, Player_Y_Position is comparable too on
# flat ground, which tests landing and the LandPlyr snap end to end.
COMPARED = ["x_speed", "x_moveforce", "y_speed", "y_moveforce"]
COMPARED_POS = COMPARED + ["y_position"]


# Past roughly here, 1-1 stops being flat and empty: blocks and pipes start
# clipping Mario, which zeroes his speed for reasons our bare test floor
# cannot reproduce. Comparison stops before that rather than blaming physics
# for a collision difference we already document as out of scope.
SAFE_WORLD_X = 220


def sample(env):
    ram = env.ram
    row = {name: int(ram[addr]) for name, addr in RAM.items()}
    row["world_x"] = int(ram[0x6D]) * 256 + int(ram[0x86])
    return row


def boot(env):
    """Reset, press Start, and settle into 1-1 with Mario standing still."""
    env.reset()
    for _ in range(40):
        env.step(0)
    for _ in range(8):
        env.step(to_nespy(HW_START))
    for _ in range(250):
        env.step(0)
    return sample(env)


def run_rom(env, script):
    """Play `script` (one hardware button byte per frame) and return the state
    after each frame."""
    frames = []
    for buttons in script:
        env.step(to_nespy(buttons))
        frames.append(sample(env))
    return frames


# 1-1's floor: Mario rests at Player_Y_Position $b0, so his feet are at
# $b0 + 32 = 208 and the floor's top row is 208 // 16 = 13.
FLOOR_ROW = 13


def flat_ground(col, row):
    return row >= FLOOR_ROW


def run_ours(script, start):
    """Push the same script through our Mario, seeded from the ROM's state."""
    tiles = flat_ground
    mario = Mario(x=300, y=0, scale=SCALE)
    for _ in range(240):                      # let him settle on the floor
        mario.update(smb.FRAME_TIME, 0, tiles)

    mario.x_speed = smb.signed_byte(start["x_speed"])
    mario.x_moveforce = start["x_moveforce"]
    mario.y_speed = smb.signed_byte(start["y_speed"])
    mario.y_moveforce = start["y_moveforce"]
    mario.ymf_dummy = start["ymf_dummy"]
    mario.vertical_force = start["vertical_force"]
    mario.vertical_force_down = start["vert_force_down"]
    mario.running_timer = start["running_timer"]
    mario.running_speed = start["running_speed"]
    # Seed faithfully -- do not coerce a zero moving_dir to "right". At rest
    # the ROM leaves it 0, and X_Physics compares it against the held
    # direction to decide whether the running row applies, so forcing it to 1
    # silently selects the wrong friction.
    mario.moving_dir = start["moving_dir"]
    mario.facing_dir = start["facing_dir"]
    mario.prev_btn_a = False

    frames = []
    for buttons in script:
        mario.set_buttons(left=bool(buttons & HW_LEFT),
                          right=bool(buttons & HW_RIGHT),
                          a=bool(buttons & HW_A),
                          b=bool(buttons & HW_B))
        mario.update(smb.FRAME_TIME, 0, tiles)
        frames.append({
            "x_speed": mario.x_speed & 0xFF,
            "x_moveforce": mario.x_moveforce,
            "y_speed": mario.y_speed & 0xFF,
            "y_moveforce": mario.y_moveforce,
            "y_position": mario.smb_y & 0xFF,
            "player_state": mario.state,
        })
    return frames


# nes-py's post-step RAM snapshot is taken before that frame's game logic has
# run, so the ROM's state trails ours by exactly one frame. Verified across
# walking, running, jumping and running-jump inputs: lag 1 gives 59/59 frames
# in every case, lag 0 and lag 2 give essentially nothing.
LAG = 1


def compare(name, rom_frames, our_frames, compare_position=False):
    matched = 0
    rom_frames = rom_frames[LAG:]
    for i, (rom, ours) in enumerate(zip(rom_frames, our_frames)):
        if rom["game_engine_sub"] != 0x08:
            print(f"  {name}: ROM left player control at frame {i} "
                  f"(${rom['game_engine_sub']:02x}) -- stopping, {matched} matched")
            return matched, True
        if rom["world_x"] > SAFE_WORLD_X:
            print(f"  {name:34s} OK   {matched} frames identical "
                  f"(stopped at x={rom['world_x']}, entering scenery)")
            return matched, True
        fields = COMPARED_POS if compare_position else COMPARED
        bad = [(k, ours[k], rom[k]) for k in fields if ours[k] != rom[k]]
        if bad:
            print(f"  {name}: DIVERGED at frame {i} ({matched} frames matched)")
            for k, o, r in bad:
                print(f"      {k:14s} ours ${o:02x}   rom ${r:02x}")
            print(f"      rom state=${rom['player_state']:02x} "
                  f"vforce=${rom['vertical_force']:02x} "
                  f"vdown=${rom['vert_force_down']:02x} "
                  f"abs=${rom['x_speed_abs']:02x} "
                  f"runtimer=${rom['running_timer']:02x}")
            return matched, False
        matched += 1
    return matched, True


def hold(buttons, frames):
    return [buttons] * frames


SCENARIOS = [
    # Vertical physics in isolation -- he never leaves the spot, so nothing
    # can collide and only gravity and the jump tables are under test.
    ("stand still", hold(0, 60)),
    ("jump in place, 1-frame tap", [HW_A] + hold(0, 90)),
    ("jump in place, 6-frame hold", hold(HW_A, 6) + hold(0, 90)),
    ("jump in place, hold A fully", hold(HW_A, 40) + hold(0, 70)),
    ("two jumps in place", hold(HW_A, 30) + hold(0, 60) + hold(HW_A, 30) + hold(0, 60)),

    # Horizontal: acceleration, top speed, friction, skid. Kept short so he
    # stays on the flat opening stretch.
    ("walk right, then release", hold(HW_RIGHT, 60) + hold(0, 60)),
    ("run right with B, then release B", hold(HW_RIGHT | HW_B, 80) + hold(HW_RIGHT, 60)),
    ("run right then skid left", hold(HW_RIGHT | HW_B, 70) + hold(HW_LEFT, 50)),
    ("tap B on and off", (hold(HW_RIGHT | HW_B, 10) + hold(HW_RIGHT, 10)) * 6),

    # Combined: running jumps pick a different row of the jump tables.
    ("running jump, hold A", hold(HW_RIGHT | HW_B, 60) + hold(HW_RIGHT | HW_B | HW_A, 30)
                             + hold(HW_RIGHT | HW_B, 40)),
    ("walking jump, hold A", hold(HW_RIGHT, 50) + hold(HW_RIGHT | HW_A, 30)
                             + hold(HW_RIGHT, 40)),
]


def main():
    rom_path = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROM)
    if not os.path.exists(rom_path):
        sys.exit(f"ROM not found: {rom_path}")
    print(f"ROM: {rom_path}\n")

    total_matched = 0
    failures = 0
    for name, script in SCENARIOS:
        env = NESEnv(rom_path)
        try:
            start = boot(env)
            rom_frames = run_rom(env, script)
        finally:
            env.close()
        our_frames = run_ours(script, start)
        vertical_only = 'place' in name or 'stand' in name
        matched, ok = compare(name, rom_frames, our_frames, vertical_only)
        total_matched += matched
        if ok and matched >= len(script) - LAG:
            print(f"  {name:34s} OK   {matched} frames identical")
        elif not ok:
            failures += 1
        print()

    print("=" * 62)
    print(f"{total_matched} frames of physics compared against the cartridge")
    print("ALL SCENARIOS MATCH" if failures == 0 else f"{failures} scenario(s) diverged")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
