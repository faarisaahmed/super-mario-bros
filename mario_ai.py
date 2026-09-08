"""Everything the trained policy needs, with no torch and no gymnasium.

`mario_env.py` (training) and `main.py` (the browser build) both drive the
policy through this module, so the 16 numbers the network sees in Pyodide are
bit-for-bit the ones it saw during training. Nothing here imports anything
that is unavailable in WebAssembly -- the forward pass is plain Python floats,
because torch cannot be compiled into a pygbag bundle.
"""

import json
import math
import os

import smb_physics as smb

SCALE = 3

# How long actions 3 and 4 hold the jump button. In SMB height comes purely
# from hold length, so these two numbers are what separate a hop from a full
# jump -- there is no separate "jump force" to set.
SHORT_JUMP_HOLD = 6
FULL_JUMP_HOLD = 18

# How far ahead (px) the gap/landing features look. Used to normalise.
LOOK = 250.0

OBS_SIZE = 16
ACTION_SIZE = 6

ACTION_NAMES = [
    "idle",
    "right",
    "left",
    "hop right",
    "jump right",
    "jump",
]


def _clamp(value, low, high):
    return low if value < low else (high if value > high else value)


class MarioSenses:
    """Turns the live game world into the observation vector, and turns an
    action index back into joypad state.

    Holds the jump-hold countdown, which is the only state the policy's side
    of the loop carries between frames.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._jump_frames_left = 0
        self._jump_holding = False

    # ── action -> joypad ──────────────────────────────────────────────
    def apply_action(self, mario, level, action, was_on_ground):
        """Turn the discrete action into joypad state.

        Jump height is not something we set -- in SMB it comes entirely from
        how many frames A stays down, so 3/4/5 latch a hold length and we
        keep the button pressed for that long. Everything else is the same
        physics the keyboard drives.
        """
        left = right = jump = run = False

        # Keep A down for the rest of an in-progress hold.
        if self._jump_frames_left > 0:
            self._jump_frames_left -= 1
            jump = True
        self._jump_holding = self._jump_frames_left > 0

        if action == 1:
            right = True
        elif action == 2:
            left = True
        elif action == 3:
            right = True
            if was_on_ground:
                self._jump_frames_left = SHORT_JUMP_HOLD
                jump = True
        elif action == 4:
            right = True
            if was_on_ground:
                self._jump_frames_left = FULL_JUMP_HOLD
                jump = True
        elif action == 5:
            if was_on_ground:
                self._jump_frames_left = FULL_JUMP_HOLD
                jump = True

        mario.set_buttons(left=left, right=right, a=jump, b=run)

    # ── world sensors ─────────────────────────────────────────────────
    def ground_ahead(self, mario, level, pixels_ahead):
        check_x = mario.x + pixels_ahead
        check_y = mario.y + (mario.height * mario.scale) + 5
        col = int(check_x // (level.tile_size * SCALE))
        row = int(check_y // (level.tile_size * SCALE))
        if not (0 <= row < level.height and 0 <= col < level.width):
            return False
        tile_id = level.grid[row][col]
        tile_info = level.tileset.get(str(tile_id))
        return tile_info is not None and tile_info.get("solid", False)

    def wall_ahead(self, mario, level, pixels_ahead):
        """
        Check for a solid tile at torso height ahead of Mario.
        This distinguishes walls (jump over them) from gaps (jump across).
        """
        check_x = mario.x + (mario.width * mario.scale) + pixels_ahead
        # Check at mid-body height
        check_y = mario.y + (mario.height * mario.scale) * 0.5
        col = int(check_x // (level.tile_size * SCALE))
        row = int(check_y // (level.tile_size * SCALE))
        if not (0 <= row < level.height and 0 <= col < level.width):
            return False
        tile_id = level.grid[row][col]
        tile_info = level.tileset.get(str(tile_id))
        return tile_info is not None and tile_info.get("solid", False)

    def ground_at_world_x(self, mario, level, world_x):
        check_y = mario.y + (mario.height * mario.scale) + 5
        col = int(world_x // (level.tile_size * SCALE))
        row = int(check_y // (level.tile_size * SCALE))
        if not (0 <= row < level.height and 0 <= col < level.width):
            return False
        tile_id = level.grid[row][col]
        tile_info = level.tileset.get(str(tile_id))
        return tile_info is not None and tile_info.get("solid", False)

    def find_gap_ahead(self, mario, level, max_look=LOOK):
        tile_px = level.tile_size * SCALE
        gap_start = None
        gap_end = None
        x = mario.x
        end_x = x + max_look
        while x < end_x:
            if not self.ground_at_world_x(mario, level, x):
                if gap_start is None:
                    gap_start = x
            else:
                if gap_start is not None:
                    gap_end = x
                    break
            x += tile_px
        if gap_start is not None and gap_end is None:
            gap_end = end_x
        return gap_start, gap_end

    def column_has_ground(self, mario, level, world_x):
        """True if any solid tile sits in the column at world_x
        (from a bit below Mario's feet down to the bottom of the level)."""
        tile_px = level.tile_size * SCALE
        col = int(world_x // tile_px)
        if not (0 <= col < level.width):
            return False
        feet_row = int((mario.y + mario.height * mario.scale) // tile_px)
        for row in range(max(feet_row, 0), level.height):
            tile_id = level.grid[row][col]
            tile_info = level.tileset.get(str(tile_id))
            if tile_info is not None and tile_info.get("solid", False):
                return True
        return False

    def over_pit(self, mario, level):
        """True when there is nothing solid anywhere below Mario -- i.e. he
        is currently out over a bottomless gap."""
        center_x = mario.x + (mario.width * mario.scale) * 0.5
        return not self.column_has_ground(mario, level, center_x)

    def pit_end_ahead(self, mario, level):
        """World x where solid ground resumes ahead of Mario (the far edge
        of the pit he is currently over)."""
        tile_px = level.tile_size * SCALE
        x = mario.x
        for _ in range(80):  # safety cap
            if self.column_has_ground(mario, level, x):
                return x
            x += tile_px
        return x

    def estimate_landing_x(self, mario, level, action=4):
        """Predict landing x for the given action's hold length by stepping
        the same integer routines mario.py uses, so the feature the policy
        sees agrees with the physics it actually gets."""
        if not mario.on_ground:
            return None

        hold_frames = SHORT_JUMP_HOLD if action == 3 else FULL_JUMP_HOLD
        index = smb.jump_index(mario.x_speed_absolute)
        jump_force = smb.JUMP_M_FORCE[index]
        fall_force = smb.FALL_M_FORCE[index]
        y_speed = smb.PLAYER_Y_SPEED[index]
        y_moveforce = smb.INIT_M_FORCE[index]
        ymf_dummy = 0

        x_speed = mario.x_speed
        x_moveforce = mario.x_moveforce
        y_px = 0
        x_px = 0

        for frame in range(500):                       # safety limit
            rising = y_speed < 0
            force = jump_force if (rising and frame < hold_frames) else fall_force

            # --- vertical, ImposeGravity -----------------------------------
            total = ymf_dummy + y_moveforce
            ymf_dummy = total & 0xff
            y_px += y_speed + (1 if total > 0xff else 0)

            total = y_moveforce + force
            y_moveforce = total & 0xff
            y_speed = smb.signed_byte(y_speed + (1 if total > 0xff else 0))
            if y_speed >= smb.MAX_FALL_SPEED and y_moveforce >= 0x80:
                y_speed = smb.MAX_FALL_SPEED
                y_moveforce = 0

            # --- horizontal, holding right the whole way -------------------
            adder = smb.FRICTION[2 if x_speed >= smb.FAST_FRICTION_SPEED else 1]
            velocity = ((x_speed << 8) | x_moveforce) + adder
            x_moveforce = velocity & 0xff
            x_speed = min(smb.signed_byte(velocity >> 8), smb.MAX_RIGHT_X_SPEED[1])

            sixteenths = (x_speed << 4) & 0xff
            total = x_moveforce + sixteenths
            x_moveforce = total & 0xff
            x_px += (x_speed >> 4) + (1 if total > 0xff else 0)

            if frame > 5 and y_px >= 0:                # back at launch height
                break

        return mario.x + x_px * SCALE

    # ── the observation the policy was trained on ─────────────────────
    def observe(self, mario, level):
        """The 16 values, in the order train_ai.py fed them to PPO.

        All RELATIVE to Mario and normalised to roughly [-1, 1] so the policy
        never has to reason about absolute world coordinates (which range
        into the thousands).

          0:     velocity_x / max_speed
          1:     velocity_y / terminal_velocity
          2:     on_ground
          3-7:   ground sensors at 16,32,64,96,128 px ahead (0/1)
          8-11:  wall sensors at 16,32,48,64 px ahead        (0/1)
          12:    distance to next gap edge ahead   / LOOK   (1 = none near)
          13:    width of that gap                 / LOOK   (0 = none)
          14:    (full-jump landing - gap far edge) / tiles, clamped
                 i.e. "would a max jump clear the gap right now?"
          15:    over_pit -- nothing solid below Mario right now (0/1)
        """
        tile_px = level.tile_size * SCALE
        gap_start, gap_end = self.find_gap_ahead(mario, level, max_look=LOOK)
        landing_x = self.estimate_landing_x(mario, level, action=4)

        max_vx = mario.horizontal_speed
        max_vy = mario.terminal_velocity

        if gap_start is not None:
            dist_to_gap = _clamp((gap_start - mario.x) / LOOK, -1.0, 1.0)
            gap_width = _clamp((gap_end - gap_start) / LOOK, 0.0, 1.0)
            # Would a max jump right now overshoot the far edge? (>0 = clears)
            if landing_x is not None:
                clears = _clamp((landing_x - gap_end) / (tile_px * 3), -1.0, 1.0)
            else:
                clears = 0.0
        else:
            dist_to_gap = 1.0   # no gap within look-ahead
            gap_width = 0.0
            clears = 0.0

        return [
            mario.velocity_x / max_vx,
            mario.velocity_y / max_vy,
            float(mario.on_ground),
            # Ground sensors ahead (are the tiles under the path solid?)
            float(self.ground_ahead(mario, level, 16)),
            float(self.ground_ahead(mario, level, 32)),
            float(self.ground_ahead(mario, level, 64)),
            float(self.ground_ahead(mario, level, 96)),
            float(self.ground_ahead(mario, level, 128)),
            # Wall sensors ahead (something to jump *over*?)
            float(self.wall_ahead(mario, level, 16)),
            float(self.wall_ahead(mario, level, 32)),
            float(self.wall_ahead(mario, level, 48)),
            float(self.wall_ahead(mario, level, 64)),
            # Gap / trajectory features, all relative + normalised
            float(dist_to_gap),
            float(gap_width),
            float(clears),
            float(self.over_pit(mario, level)),
        ]


class Policy:
    """The trained PPO actor, as a plain-Python forward pass.

    Stable-Baselines3's MlpPolicy is a 16-64-64 tanh trunk followed by a
    linear head over the 6 actions. That is ~5.5k multiply-adds per frame,
    cheap enough to run in the interpreter at 60fps and worth it to avoid
    shipping torch (which has no WebAssembly build) to the browser.

    Only the actor is exported. The critic is training-time scaffolding and
    never runs here.
    """

    def __init__(self, layers):
        # layers: list of (weight_rows, bias) applied in order; tanh between,
        # nothing after the last one (argmax over logits is unaffected).
        self.layers = layers

    @classmethod
    def load(cls, path=None):
        path = path or os.path.join("ai", "policy.json")
        with open(path, "r") as f:
            data = json.load(f)
        if data.get("obs_size") != OBS_SIZE or data.get("action_size") != ACTION_SIZE:
            raise ValueError(
                f"{path} has shape {data.get('obs_size')}->{data.get('action_size')}, "
                f"expected {OBS_SIZE}->{ACTION_SIZE}"
            )
        return cls([(l["w"], l["b"]) for l in data["layers"]])

    def act(self, obs):
        """Greedy action, matching `model.predict(obs, deterministic=True)`."""
        x = obs
        last = len(self.layers) - 1
        for i, (w, b) in enumerate(self.layers):
            # w is stored row-major as [out][in], so each row is one neuron.
            out = [sum(wi * xi for wi, xi in zip(row, x)) + bi
                   for row, bi in zip(w, b)]
            x = out if i == last else [math.tanh(v) for v in out]
        best = 0
        for i in range(1, len(x)):
            if x[i] > x[best]:
                best = i
        return best
