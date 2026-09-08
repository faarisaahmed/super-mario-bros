"""
rom_compare_contact.py -- verify stomping and wall collision against the ROM.

The scenarios in rom_compare.py deliberately stay on empty flat ground, so
they never exercise ImpedePlayerMove or a stomp. This one does the opposite:
it runs Mario into the first goomba and the first pipe of 1-1 and checks that
our collision reacts on the same frame, at the same pixel.

To make positions comparable, the level is not ours -- the ROM's own block
buffer is read out of RAM every frame and used as the collision map, so both
sides are colliding against identical geometry.

    python3 tools/rom_compare_contact.py [path-to-rom]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nespy_compat  # noqa: F401

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((8, 8))

from nes_py import NESEnv          # noqa: E402
from mario import Mario            # noqa: E402
from goomba import Goomba          # noqa: E402
import smb_physics as smb          # noqa: E402

DEFAULT_ROM = "~/roms/Super Mario Bros. (Japan, USA).nes"
SCALE = 3
LAG = 1                       # established in rom_compare.py

HW_RIGHT, HW_A, HW_START = 0x01, 0x80, 0x10
NP_RIGHT, NP_A, NP_START = 0x80, 0x01, 0x08

BLOCK_BUFFER_1 = 0x500
BLOCK_BUFFER_2 = 0x5D0
# SMB's block buffer row 0 sits at screen Y $20, i.e. two tiles down, because
# of the status bar. Our grid rows have no such offset.
BUFFER_ROW_OFFSET = 2


def to_nespy(hw):
    out = 0
    if hw & HW_RIGHT: out |= NP_RIGHT
    if hw & HW_A:     out |= NP_A
    if hw & HW_START: out |= NP_START
    return out


def read_state(env):
    r = env.ram
    return {
        "engine": int(r[0x0E]), "state": int(r[0x1D]),
        "x_speed": int(r[0x57]), "x_moveforce": int(r[0x705]),
        "y_speed": int(r[0x9F]), "y_moveforce": int(r[0x433]),
        "world_x": int(r[0x6D]) * 256 + int(r[0x86]),
        "y_position": int(r[0xCE]),
        "moving_dir": int(r[0x45]), "facing_dir": int(r[0x33]),
        "vertical_force": int(r[0x709]), "vert_force_down": int(r[0x70A]),
        "running_timer": int(r[0x783]), "running_speed": int(r[0x703]),
        "ymf_dummy": int(r[0x416]),
        "goomba_id": int(r[0x16]), "goomba_state": int(r[0x1E]),
        "goomba_x": int(r[0x6E]) * 256 + int(r[0x87]),
        "goomba_y": int(r[0xCF]),
        # Both block buffers, so our collision sees the ROM's own geometry.
        "buffer": bytes(r[BLOCK_BUFFER_1:BLOCK_BUFFER_1 + 208])
                  + bytes(r[BLOCK_BUFFER_2:BLOCK_BUFFER_2 + 208]),
    }


def solid_from_buffer(buffer):
    """A solid_at() backed by the ROM's block buffer.

    The foot and side checks in PlayerBGCollision treat *any* non-empty
    metatile as blocking -- only the head check consults
    CheckForSolidMTiles -- so a plain non-zero test is what these scenarios
    need.
    """
    def solid_at(col, row):
        buf_row = row - BUFFER_ROW_OFFSET
        if buf_row < 0 or buf_row >= 13 or col < 0:
            return False
        which = (col >> 4) & 1
        offset = which * 208 + (col & 0x0F) + buf_row * 16
        return buffer[offset] != 0
    return solid_at


def boot(env):
    env.reset()
    for _ in range(40):
        env.step(0)
    for _ in range(8):
        env.step(to_nespy(HW_START))
    for _ in range(250):
        env.step(0)
    return read_state(env)


def seed(mario, s):
    mario.gx = s["world_x"] + smb.HITBOX_ORIGIN_DX
    mario.gy = s["y_position"] + smb.HITBOX_ORIGIN_DY
    mario.x_speed = smb.signed_byte(s["x_speed"])
    mario.x_moveforce = s["x_moveforce"]
    mario.x_position_frac = 0
    mario.y_speed = smb.signed_byte(s["y_speed"])
    mario.y_moveforce = s["y_moveforce"]
    mario.ymf_dummy = s["ymf_dummy"]
    mario.vertical_force = s["vertical_force"]
    mario.vertical_force_down = s["vert_force_down"]
    mario.running_timer = s["running_timer"]
    mario.running_speed = s["running_speed"]
    mario.moving_dir = s["moving_dir"]
    mario.facing_dir = s["facing_dir"]
    mario.state = s["state"]
    mario.prev_btn_a = False


def script_for(jump_at, hold, total):
    return [HW_RIGHT | (HW_A if jump_at <= i < jump_at + hold else 0)
            for i in range(total)]


def run(rom_path, name, jump_at, hold, total, watch_stomp):
    env = NESEnv(rom_path)
    try:
        start = boot(env)
        frames = []
        for buttons in script_for(jump_at, hold, total):
            env.step(to_nespy(buttons))
            frames.append(read_state(env))
    finally:
        env.close()

    mario = Mario(x=0, y=0, scale=SCALE)
    seed(mario, start)
    goomba = Goomba(0, 0, 16, SCALE) if watch_stomp else None

    script = script_for(jump_at, hold, total)
    rom_stomp = our_stomp = None
    matched = 0

    for i, buttons in enumerate(script):
        if i + LAG >= len(frames):
            break
        rom = frames[i + LAG]
        if rom["engine"] != 0x08:
            print(f"  {name}: ROM left player control at frame {i} "
                  f"(${rom['engine']:02x}); {matched} frames matched")
            break

        # Collide against the ROM's own geometry for this frame.
        solid_at = solid_from_buffer(frames[min(i + LAG, len(frames) - 1)]["buffer"])
        mario.set_buttons(right=bool(buttons & HW_RIGHT), a=bool(buttons & HW_A))
        mario.update(smb.FRAME_TIME, 0, solid_at)

        if watch_stomp:
            # Put our goomba exactly where the ROM's is and let our own
            # contact rule decide, so the trigger frame is under test too.
            # Enemy_Y_Position sits 8px above the goomba's sprite top (its
            # box is Enemy_Y+14..+20 and our offset into the sprite is 6).
            goomba.x = float(rom["goomba_x"] * SCALE)
            goomba.y = float((rom["goomba_y"] + 8) * SCALE)
            if rom["goomba_state"] == 0x04 and rom_stomp is None:
                rom_stomp = i
            if (our_stomp is None and goomba.is_dangerous()
                    and mario.rect().colliderect(goomba.hitbox())
                    and mario.is_descending()):
                our_stomp = i
                goomba.squash()
                mario.stomp()

        checks = [
            ("x_speed", mario.x_speed & 0xFF, rom["x_speed"]),
            ("x_moveforce", mario.x_moveforce, rom["x_moveforce"]),
            ("y_speed", mario.y_speed & 0xFF, rom["y_speed"]),
            ("y_moveforce", mario.y_moveforce, rom["y_moveforce"]),
            ("world_x", mario.smb_x, rom["world_x"]),
            ("y_position", mario.smb_y & 0xFF, rom["y_position"]),
        ]
        bad = [(k, a, b) for k, a, b in checks if a != b]
        if bad:
            print(f"  {name}: DIVERGED at frame {i} ({matched} matched)")
            for k, a, b in bad:
                print(f"      {k:12s} ours {a:5d} (${a & 0xff:02x})   rom {b:5d} (${b & 0xff:02x})")
            return matched, False, rom_stomp, our_stomp
        matched += 1

    return matched, True, rom_stomp, our_stomp


def main():
    rom_path = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROM)
    if not os.path.exists(rom_path):
        sys.exit(f"ROM not found: {rom_path}")
    print(f"ROM: {rom_path}\n")
    ok = True

    # Runs into the first pipe of 1-1 -- exercises ImpedePlayerMove.
    m, good, _, _ = run(rom_path, "run into the first pipe", 165, 20, 300, False)
    print(f"  {'OK  ' if good else 'FAIL'} run into the first pipe: {m} frames identical\n")
    ok &= good

    # Lands on the first goomba -- exercises the stomp trigger and bounce.
    m, good, rs, os_ = run(rom_path, "stomp the first goomba", 165, 6, 260, True)
    print(f"  {'OK  ' if good else 'FAIL'} stomp the first goomba: {m} frames identical")
    print(f"       ROM stomped on frame {rs}; we stomped on frame {os_}")
    ok &= good and rs is not None and rs == os_

    print("\n" + "=" * 58)
    print("CONTACT SCENARIOS MATCH" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
