"""Everything the trained policy needs, with no torch and no gymnasium.

`mario_env.py` (training) and `main.py` (the browser build) both drive the
policy through this module, so the numbers the network sees in Pyodide are
bit-for-bit the ones it saw during training. Nothing here imports anything
that is unavailable in WebAssembly -- the forward pass is plain Python floats,
because torch cannot be compiled into a pygbag bundle. It does not import
pygame either, so the sensor code stays usable outside a display context.
"""

import json
import math
import os

import smb_physics as smb

SCALE = 3

# How long the jump actions hold A. In SMB height comes purely from hold
# length -- there is no separate "jump force" -- so these two numbers decide
# which obstacles are reachable at all.
#
# FULL_JUMP_HOLD was 18 and that was the single biggest thing wrong with the
# old agent. `tools/jump_sweep.py --col 46` sweeps every grounded launch
# position on the approach to 1-1's four-tile pipe and asks how many of them
# get past it or on top of it:
#
#     hold |  walking past / on top  |  running past / on top
#       18 |        0    /    0      |       0    /   10
#       32 |        0    /   21      |      10    /   16
#
# At 18 while walking -- which is all the old action space could express --
# the answer is zero. Not a narrow window the search kept missing: no launch
# position on the level clears that pipe, so no amount of training would ever
# have got past it. Hold saturates around 32 frames (34 is identical), which
# is where FULL sits now, and the run button supplies the rest.
SHORT_JUMP_HOLD = 6
FULL_JUMP_HOLD = 32

# How far ahead (px) the gap/landing/threat features look. Used to normalise.
LOOK = 250.0

# Tallest obstacle worth distinguishing, in tiles -- used to normalise the
# obstacle-height sensor. 1-1's tallest jumpable wall is the 4-tile pipe.
MAX_OBSTACLE_TILES = 5.0

OBS_SIZE = 26
ACTION_SIZE = 8


class OBS:
    """Named offsets into the observation vector.

    Everything that reads an observation -- the scripted baseline, the
    environment checks -- used to do it by number, which is a bug waiting for
    the next feature: inserting one value silently shifts every index after
    it and the reader carries on reading a plausible wrong thing. The order
    here is the order observe() emits, and OBS_SIZE is asserted against it.
    """

    VELOCITY_X = 0
    VELOCITY_Y = 1
    ON_GROUND = 2
    RUNNING = 3
    GROUND_AHEAD = (4, 5, 6, 7, 8)          # 16, 32, 64, 96, 128 px
    WALL_AHEAD = (9, 10, 11, 12)            # 16, 32, 48, 64 px
    OBSTACLE_HEIGHT = 13                    # tiles / MAX_OBSTACLE_TILES
    GAP_DIST = 14                           # next step down
    GAP_WIDTH = 15
    PIT_DIST = 16                           # next bottomless pit
    PIT_WIDTH = 17
    WALK_CLEARS_PIT = 18                    # both hold the same value:
    RUN_CLEARS_PIT = 19                     # airborne physics ignore B
    OVER_PIT = 20
    THREAT_DX = 21
    THREAT_DY = 22
    THREAT_CLOSING = 23
    THREAT2_DX = 24
    STOMPABLE = 25

# Every action holds a direction, a jump-hold length, and the B button. The
# split that matters is that B is available *with* a full jump (action 7):
# a run-jump is the only thing in 1-1 that clears the tall pipe, and the old
# six-action space had no way to express one.
class ACT:
    """Named action indices, matching ACTION_NAMES and _ACTIONS below."""

    IDLE = 0
    WALK_RIGHT = 1
    WALK_LEFT = 2
    RUN_RIGHT = 3
    HOP_RIGHT = 4
    JUMP_RIGHT = 5
    RUN_HOP_RIGHT = 6
    RUN_JUMP_RIGHT = 7


ACTION_NAMES = [
    "idle",
    "walk right",
    "walk left",
    "run right",
    "hop right",
    "jump right",
    "run-hop right",
    "run-jump right",
]

# Per action: (dx, jump hold or None, run)
_ACTIONS = [
    (0, None, False),                 # 0 idle
    (1, None, False),                 # 1 walk right
    (-1, None, False),                # 2 walk left
    (1, None, True),                  # 3 run right
    (1, SHORT_JUMP_HOLD, False),      # 4 hop right
    (1, FULL_JUMP_HOLD, False),       # 5 jump right
    (1, SHORT_JUMP_HOLD, True),       # 6 run-hop right
    (1, FULL_JUMP_HOLD, True),        # 7 run-jump right
]


def _clamp(value, low, high):
    return low if value < low else (high if value > high else value)


class MarioSenses:
    """Turns the live game world into the observation vector, and turns an
    action index back into joypad state.

    Holds the jump-hold countdown and whether that jump was a running one,
    which is the only state the policy's side of the loop carries between
    frames.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._jump_frames_left = 0
        self._jump_run = False

    # -- action -> joypad --------------------------------------------------
    def apply_action(self, mario, level, action, was_on_ground):
        """Turn the discrete action into joypad state.

        Jump height is not something we set: in SMB it comes entirely from
        how many frames A stays down, so the jump actions latch a hold length
        and we keep the button pressed for that long.

        B is latched the same way. Airborne, X_Physics only grants running
        speed once Player_XSpeedAbsolute is already at or above AIR_RUN_SPEED
        -- so a jump taken at walking pace is stuck at walking pace for its
        whole arc no matter what the policy presses next. Holding B for the
        agent through the jump it started as a run-jump means "run-jump" is
        one decision rather than a thirty-frame commitment the policy has to
        remember to renew every single frame.
        """
        dx, hold, run = _ACTIONS[action]

        jump = False
        in_jump = self._jump_frames_left > 0
        if in_jump:
            self._jump_frames_left -= 1
            jump = True

        if hold is not None and was_on_ground:
            # A fresh jump takes its run bit from the action that started it,
            # never from the one still counting down -- otherwise a plain
            # jump launched the frame after a clipped run-jump inherits B.
            self._jump_frames_left = hold
            self._jump_run = run
            jump = True
            in_jump = True

        held_b = run or (self._jump_run if in_jump else False)
        if self._jump_frames_left <= 0:
            self._jump_run = False

        mario.set_buttons(left=dx < 0, right=dx > 0, a=jump, b=held_b)

    # -- world sensors -----------------------------------------------------
    def _solid(self, level, col, row):
        if not (0 <= row < level.height and 0 <= col < level.width):
            return False
        tile = level.tileset.get(str(level.grid[row][col]))
        return tile is not None and tile.get("solid", False)

    def ground_ahead(self, mario, level, pixels_ahead):
        check_x = mario.x + pixels_ahead
        check_y = mario.y + (mario.height * mario.scale) + 5
        tile_px = level.tile_size * SCALE
        return self._solid(level, int(check_x // tile_px), int(check_y // tile_px))

    def wall_ahead(self, mario, level, pixels_ahead):
        """A solid tile at torso height ahead of Mario. This is what
        distinguishes a wall (jump over it) from a gap (jump across it)."""
        check_x = mario.x + (mario.width * mario.scale) + pixels_ahead
        check_y = mario.y + (mario.height * mario.scale) * 0.5
        tile_px = level.tile_size * SCALE
        return self._solid(level, int(check_x // tile_px), int(check_y // tile_px))

    def obstacle_height_ahead(self, mario, level, max_look=96):
        """How many tiles the nearest wall in front of Mario stands above his
        feet, 0 if there is nothing to climb.

        The wall sensors say *that* something is there; this says how much of
        it there is. Without it a two-tile pipe and the four-tile pipe are the
        same observation, and the four-tile one needs a run-jump while the
        other does not -- so the policy has no way to tell the two apart, and
        whichever answer it settles on is wrong half the time.
        """
        tile_px = level.tile_size * SCALE
        feet_row = int((mario.y + mario.height * mario.scale + 4) // tile_px)
        front = mario.x + mario.width * mario.scale
        for offset in range(4, int(max_look), int(tile_px // 2)):
            col = int((front + offset) // tile_px)
            if not self._solid(level, col, feet_row - 1):
                continue
            height = 0
            row = feet_row - 1
            while row >= 0 and self._solid(level, col, row):
                height += 1
                row -= 1
            return height
        return 0

    def ground_at_world_x(self, mario, level, world_x):
        check_y = mario.y + (mario.height * mario.scale) + 5
        tile_px = level.tile_size * SCALE
        return self._solid(level, int(world_x // tile_px), int(check_y // tile_px))

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

    def find_pit_ahead(self, mario, level, max_look=LOOK):
        """The next *bottomless* gap ahead -- a run of columns with nothing
        solid anywhere below Mario's feet, all the way down.

        This is a different question from find_gap_ahead(), which probes at
        foot level and so reports the drop off the end of a pipe as a gap. A
        step down costs nothing; a pit ends the episode. Standing on the tall
        pipe those two look identical to the foot-level sensor, and an agent
        that cannot tell them apart either freezes on every ledge or takes a
        full run-jump off one and overshoots the landing into the real pit
        ten tiles later -- which is exactly what a hand-written policy does
        here when this feature is missing.
        """
        tile_px = level.tile_size * SCALE
        start = end = None
        x = mario.x
        limit = x + max_look
        while x < limit:
            if not self.column_has_ground(mario, level, x):
                if start is None:
                    start = x
            elif start is not None:
                end = x
                break
            x += tile_px
        if start is not None and end is None:
            end = limit
        return start, end

    def column_has_ground(self, mario, level, world_x):
        """True if any solid tile sits in the column at world_x (from a bit
        below Mario's feet down to the bottom of the level)."""
        tile_px = level.tile_size * SCALE
        col = int(world_x // tile_px)
        if not (0 <= col < level.width):
            return False
        feet_row = int((mario.y + mario.height * mario.scale) // tile_px)
        for row in range(max(feet_row, 0), level.height):
            if self._solid(level, col, row):
                return True
        return False

    def over_pit(self, mario, level):
        """True when there is nothing solid anywhere below Mario -- i.e. he
        is currently out over a bottomless gap."""
        center_x = mario.x + (mario.width * mario.scale) * 0.5
        return not self.column_has_ground(mario, level, center_x)

    def pit_end_ahead(self, mario, level):
        """World x where solid ground resumes ahead of Mario (the far edge of
        the pit he is currently over)."""
        tile_px = level.tile_size * SCALE
        x = mario.x
        for _ in range(80):                      # safety cap
            if self.column_has_ground(mario, level, x):
                return x
            x += tile_px
        return x

    def estimate_landing_x(self, mario, level, hold=FULL_JUMP_HOLD, run=False):
        """Predict landing x for a jump of this hold length by stepping the
        same integer routines mario.py does, so the feature the policy sees
        agrees with the physics it actually gets.

        `run` is accepted for symmetry with the action space and is
        deliberately ignored. X_Physics' airborne branch picks the running
        row on `x_speed_absolute >= AIR_RUN_SPEED` alone and never reads the
        B button, so a jump's arc is decided by the speed it launched at and
        nothing else. Gating this on B as well used to make the run=False
        prediction land 3.6 tiles short of the truth whenever Mario was
        actually running -- which is precisely when the feature is consulted.
        Both callers now get the same, correct number; see observe().
        """
        if not mario.on_ground:
            return None

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

        for frame in range(120):                 # airtime tops out near 60
            rising = y_speed < 0
            force = jump_force if (rising and frame < hold) else fall_force

            # --- vertical, ImposeGravity ------------------------------
            total = ymf_dummy + y_moveforce
            ymf_dummy = total & 0xff
            y_px += y_speed + (1 if total > 0xff else 0)

            total = y_moveforce + force
            y_moveforce = total & 0xff
            y_speed = smb.signed_byte(y_speed + (1 if total > 0xff else 0))
            if y_speed >= smb.MAX_FALL_SPEED and y_moveforce >= 0x80:
                y_speed = smb.MAX_FALL_SPEED
                y_moveforce = 0

            # --- horizontal, holding right the whole way --------------
            # X_Physics airborne branch: the running row applies once
            # absolute speed is at AIR_RUN_SPEED, whatever B is doing.
            if abs(x_speed) >= smb.AIR_RUN_SPEED:
                adder = smb.FRICTION[0]
                cap = smb.MAX_RIGHT_X_SPEED[0]
            else:
                adder = smb.FRICTION[
                    2 if abs(x_speed) >= smb.FAST_FRICTION_SPEED else 1]
                cap = smb.MAX_RIGHT_X_SPEED[1]

            velocity = ((x_speed << 8) | x_moveforce) + adder
            x_moveforce = velocity & 0xff
            x_speed = min(smb.signed_byte(velocity >> 8), cap)

            sixteenths = (x_speed << 4) & 0xff
            total = x_moveforce + sixteenths
            x_moveforce = total & 0xff
            x_px += (x_speed >> 4) + (1 if total > 0xff else 0)

            if frame > 5 and y_px >= 0:          # back at launch height
                break

        return mario.x + x_px * SCALE

    # -- threats -----------------------------------------------------------
    @staticmethod
    def _threat_span(threat):
        """(left, right, top, bottom) of a goomba in world pixels, without
        importing pygame -- this module has to stay display-free."""
        s = threat.scale
        left = threat.x + threat.HITBOX_OFFSET_X * s
        top = threat.y + threat.HITBOX_OFFSET_Y * s
        return (left, left + threat.HITBOX_WIDTH * s,
                top, top + threat.HITBOX_HEIGHT * s)

    def nearest_threats(self, mario, threats, count=2):
        """The `count` closest live goombas ahead of or on top of Mario,
        nearest first, as (dx, dy, closing) in world pixels."""
        mx = mario.x + (mario.width * mario.scale) * 0.5
        my = mario.y + (mario.height * mario.scale) * 0.5
        found = []
        for threat in threats:
            if not threat.is_dangerous():
                continue
            left, right, top, bottom = self._threat_span(threat)
            cx = (left + right) * 0.5
            cy = (top + bottom) * 0.5
            dx = cx - mx
            if dx < -48 or dx > LOOK:            # behind him, or too far off
                continue
            closing = 1.0 if (threat.x_speed > 0) == (dx < 0) else 0.0
            found.append((dx, cy - my, closing))
        found.sort(key=lambda t: abs(t[0]))
        return found[:count]

    def stompable_now(self, mario, threats):
        """Descending with a goomba directly underneath -- the state where
        holding course lands a stomp instead of taking a hit."""
        if not mario.is_descending():
            return False
        m_left = mario.x
        m_right = mario.x + mario.width * mario.scale
        m_bottom = mario.y + mario.height * mario.scale
        for threat in threats:
            if not threat.is_dangerous():
                continue
            left, right, top, _ = self._threat_span(threat)
            if right > m_left and left < m_right and top >= m_bottom - 24:
                return True
        return False

    # -- the observation the policy is trained on --------------------------
    def observe(self, mario, level, threats=()):
        """The 26 values, in the order train_ai.py feeds them to PPO.

        All RELATIVE to Mario and normalised to roughly [-1, 1] so the policy
        never has to reason about absolute world coordinates.

           0:     velocity_x / top *running* speed  (1.0 = flat out)
           1:     velocity_y / terminal velocity
           2:     on_ground
           3:     running physics active right now  (0/1)
           4-8:   ground sensors at 16,32,64,96,128 px ahead  (0/1)
           9-12:  wall sensors at 16,32,48,64 px ahead        (0/1)
          13:     height of the wall ahead, in tiles / 5
          14:     distance to the next step down ahead / LOOK (1 = none near)
          15:     width of that step-down / LOOK              (0 = none)
          16:     distance to the next bottomless pit / LOOK  (1 = none near)
          17:     width of that pit / LOOK                    (0 = none)
          18:     (full-jump landing - pit far edge) / tiles, clamped
          19:     the same number again -- see the note below
          20:     over_pit -- nothing solid below Mario right now (0/1)
          21-22:  nearest goomba dx / LOOK, dy / 3 tiles  (1, 0 = none)
          23:     that goomba is walking towards him       (0/1)
          24:     second goomba dx / LOOK                  (1 = none)
          25:     stompable right now                      (0/1)
        """
        tile_px = level.tile_size * SCALE
        span = tile_px * 3

        gap_start, gap_end = self.find_gap_ahead(mario, level, max_look=LOOK)
        if gap_start is not None:
            dist_to_gap = _clamp((gap_start - mario.x) / LOOK, -1.0, 1.0)
            gap_width = _clamp((gap_end - gap_start) / LOOK, 0.0, 1.0)
        else:
            dist_to_gap, gap_width = 1.0, 0.0    # no step down within reach

        pit_start, pit_end = self.find_pit_ahead(mario, level, max_look=LOOK)
        if pit_start is not None:
            dist_to_pit = _clamp((pit_start - mario.x) / LOOK, -1.0, 1.0)
            pit_width = _clamp((pit_end - pit_start) / LOOK, 0.0, 1.0)
            # Would a full jump taken right now land past the far side?
            #
            # Slots 18 and 19 were meant to be "walking" and "running"
            # answers. They cannot differ: the airborne physics read speed,
            # not the B button, so there is one answer and this is it. The
            # duplicated slot is left in place because removing it changes
            # OBS_SIZE and so invalidates every trained checkpoint, and the
            # shipped policy is measurably indifferent to it -- correcting
            # slot 18 changes its play not at all, frame for frame. Collapse
            # the two at the next retrain.
            land = self.estimate_landing_x(mario, level, FULL_JUMP_HOLD)
            clears = (_clamp((land - pit_end) / span, -1.0, 1.0)
                      if land is not None else 0.0)
            walk_clears = run_clears = clears
        else:
            dist_to_pit, pit_width = 1.0, 0.0
            walk_clears = run_clears = 0.0

        # Running physics, as X_Physics decides it: B held with the grace
        # timer still up, or simply going fast enough for the airborne branch.
        running = float(bool(mario.running_timer)
                        or mario.x_speed_absolute >= smb.AIR_RUN_SPEED)

        near = self.nearest_threats(mario, threats, count=2)
        if near:
            t_dx = _clamp(near[0][0] / LOOK, -1.0, 1.0)
            t_dy = _clamp(near[0][1] / (tile_px * 3), -1.0, 1.0)
            t_closing = near[0][2]
        else:
            t_dx, t_dy, t_closing = 1.0, 0.0, 0.0
        second_dx = _clamp(near[1][0] / LOOK, -1.0, 1.0) if len(near) > 1 else 1.0

        return [
            mario.velocity_x / mario.running_speed_max,
            mario.velocity_y / mario.terminal_velocity,
            float(mario.on_ground),
            running,
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
            _clamp(self.obstacle_height_ahead(mario, level) / MAX_OBSTACLE_TILES,
                   0.0, 1.0),
            # Terrain ahead: a step down, then a pit that actually kills
            float(dist_to_gap),
            float(gap_width),
            float(dist_to_pit),
            float(pit_width),
            float(walk_clears),
            float(run_clears),
            float(self.over_pit(mario, level)),
            # Threats
            float(t_dx),
            float(t_dy),
            float(t_closing),
            float(second_dx),
            float(self.stompable_now(mario, threats)),
        ]


class Policy:
    """The trained PPO actor, as a plain-Python forward pass.

    Stable-Baselines3's MlpPolicy is a 26-64-64 tanh trunk followed by a
    linear head over the 8 actions. That is ~6.3k multiply-adds per frame,
    cheap enough to run in the interpreter at 60fps and worth it to avoid
    shipping torch (which has no WebAssembly build) to the browser. The
    hidden layers stay at 64 for that reason: 128 would be 20k MACs a frame,
    which measures fine in CPython and is a gamble in Pyodide.

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
