"""The training environment: 1-1, goombas and all.

What the policy sees and how an action becomes joypad state both live in
mario_ai.py, which the browser build imports too -- so the observations here
during training are produced by literally the same code that runs in Pyodide.
This file owns only the things training needs and the game does not: the
reward, the episode boundaries, and where Mario starts.
"""

import os
import random

import gymnasium as gym
import numpy as np
import pygame
from gymnasium import spaces

import goomba as goomba_mod
import smb_physics as smb
from goomba import Goomba
from level_loader import Level
from mario import Mario
from mario_ai import ACTION_SIZE, OBS_SIZE, MarioSenses
from sprite_manager import SpriteManager

SCALE = 3
BASE_WIDTH, BASE_HEIGHT = 256, 240
SCREEN_WIDTH = BASE_WIDTH * SCALE
SCREEN_HEIGHT = BASE_HEIGHT * SCALE
TILE_PX = 16 * SCALE
DT = smb.FRAME_TIME

# Top walking and running speeds in scaled px/frame, used to normalise the
# speed bonus and to price a "par" time for the level.
WALK_PX_PER_FRAME = (smb.MAX_RIGHT_X_SPEED[1] / 16.0) * SCALE
RUN_PX_PER_FRAME = (smb.MAX_RIGHT_X_SPEED[0] / 16.0) * SCALE

# Goombas only matter near the camera, and stepping the ones a screen and a
# half away is pure cost. They are dormant until the camera reaches them
# anyway, and one that has walked off to the left is never coming back.
GOOMBA_ACTIVE_MARGIN = 400


class TileIndex:
    """Solid tiles bucketed by column.

    Goomba._step_frame walks the whole list it is handed, twice a frame. The
    level has 3165 solid tiles and up to sixteen goombas, which is a hundred
    thousand rectangle tests per frame and makes training crawl. A goomba can
    only ever touch tiles it overlaps, so handing it the three columns around
    itself is the same answer for a thousandth of the work.
    """

    def __init__(self, level, scale=SCALE):
        self.size = int(level.tile_size * scale)
        self.columns = {}
        for rect in level.get_solid_tiles(scale):
            self.columns.setdefault(rect.x // self.size, []).append(rect)

    def near(self, x, width):
        first = int(x) // self.size - 1
        last = (int(x) + int(width)) // self.size + 1
        out = []
        for col in range(first, last + 1):
            bucket = self.columns.get(col)
            if bucket:
                out.extend(bucket)
        return out


class MarioEnv(gym.Env):
    """Super Mario Bros 1-1 as a gymnasium environment.

    The reward is built to produce a *fast* clear rather than merely a clear.
    Forward progress is the main driver, but a per-frame cost of being alive
    plus a bonus that only pays above walking speed mean dawdling loses
    ground every frame, and finishing well under a walking pace is worth
    several hundred points on its own.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(self, render_mode=False, random_start_prob=0.0,
                 start_jitter=0, speed_bonus=0.05, time_cost=0.05, seed=None):
        # Headless only when nobody wants to look at it. This has to happen
        # before pygame picks a video driver, and it must NOT be done at
        # import time: watch_ai.py and server.py import this module and then
        # ask for render_mode=True, and a module-level dummy driver would
        # leave them drawing into nothing -- with no window there is also no
        # QUIT event, so the watcher would never even exit.
        if not render_mode:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((1, 1))
        super().__init__()

        self.render_mode = render_mode
        self.level = Level("levels/1-1.json", "tileset.json")
        self.tiles = TileIndex(self.level)
        self.sprites = SpriteManager("sprites", SCALE) if render_mode else None

        self.level_pixel_width = self.level.width * self.level.tile_size * SCALE
        self.finish_x = self.level_pixel_width - 50

        # Feature extraction + jump-hold state, shared with the web build.
        self.senses = MarioSenses()

        # Curriculum: how often an episode starts somewhere other than the
        # beginning. See set_random_start_prob().
        self.random_start_prob = random_start_prob
        # The level is deterministic and so is a greedy policy, so without
        # this every evaluation episode is the same episode and running
        # twenty of them measures nothing. Nudging the start by a few pixels
        # is the cheapest honest test of whether the agent has a policy or a
        # memorised keypress sequence.
        self.start_jitter = int(start_jitter)
        self._spawns = self._find_spawns()
        self._rng = random.Random(seed)

        # An episode that stops getting anywhere is over. Without this the
        # agent can sit against a wall collecting the living penalty for
        # three thousand frames, and every one of those frames is a rollout
        # step that taught nothing.
        self.max_steps = 3000
        self.stall_limit = 240

        # The two weights that decide how much the agent cares about being
        # fast, exposed so a finished policy can be fine-tuned for speed
        # without retraining it from nothing. See step().
        self.speed_bonus = float(speed_bonus)
        self.time_cost = float(time_cost)

        self.action_space = spaces.Discrete(ACTION_SIZE)
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(OBS_SIZE,), dtype=np.float32
        )

        self.mario = None
        self.goombas = []
        self.camera_x = 0

        if self.render_mode:
            self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
            self.clock = pygame.time.Clock()

        self.reset()

    # -- setup -------------------------------------------------------------
    def _find_spawns(self):
        """Every column Mario can be dropped into: walkable ground with three
        clear tiles of headroom above it.

        "Walkable ground" means the top of the stack that rises from the
        bottom of the level -- floor, pipe or stair -- not simply the highest
        solid tile in the column. Taking the highest one put two fifths of
        1-1's spawn points on top of the floating brick and question-block
        rows, which is not a state a run from the start can reach, and it
        also made the headroom test below vacuous: the topmost solid tile has
        nothing above it by definition, so the check rejected nothing.
        """
        spawns = []
        floor_row = self.level.height - 1
        for col in range(2, self.level.width - 12):
            if not self.level.solid_at(col, floor_row):
                continue                        # a pit
            surface = floor_row
            while surface > 0 and self.level.solid_at(col, surface - 1):
                surface -= 1
            if surface < 3:
                continue
            if any(self.level.solid_at(col, surface - k) for k in (1, 2, 3)):
                continue                        # something overhead
            spawns.append((col * TILE_PX, (surface - 3) * TILE_PX))
        return spawns

    def set_random_start_prob(self, prob):
        """Curriculum hook, called through VecEnv.env_method during training.

        Starting some episodes partway into the level is what stops the tail
        of 1-1 from being unreachable to the search: on-policy PPO only ever
        learns about states it visits, and if the tall pipe at x=2208 stops
        every rollout then nothing past it is ever in a batch.
        """
        self.random_start_prob = float(prob)

    # -- gym API -----------------------------------------------------------
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self._rng.seed(seed)

        start_x, start_y = 100, 0
        if self._spawns and self._rng.random() < self.random_start_prob:
            start_x, start_y = self._rng.choice(self._spawns)
        elif self.start_jitter:
            start_x += self._rng.randint(0, self.start_jitter)

        self.mario = Mario(x=start_x, y=start_y, scale=SCALE)
        self.goombas = [
            Goomba(gx, gy, self.level.tile_size, SCALE)
            for gx, gy in self.level.goombas
        ]
        self.senses.reset()

        self.camera_x = 0
        self._update_camera()
        self.start_x = float(start_x)
        self.prev_x = self.mario.x
        self.max_x = self.mario.x
        self._crossing_end = None
        self._steps = 0
        self._since_progress = 0
        self._stomps = 0
        self._outcome = "running"

        # A walking clear of the distance left is "par". Beating it is what
        # the finishing bonus pays for, and pricing it off the distance
        # actually travelled keeps a random start from being worth more than
        # a run from the beginning.
        remaining = max(self.finish_x - self.mario.x, 1.0)
        self.par_steps = remaining / WALK_PX_PER_FRAME

        return self._get_state(), {}

    def step(self, action):
        terminated = truncated = False
        reward = 0.0
        self._steps += 1

        was_on_ground = self.mario.on_ground
        self.senses.apply_action(self.mario, self.level, action, was_on_ground)
        self.mario.update(DT, self.camera_x, self.level.solid_at)
        # Move the goombas and settle contact before the camera moves, which
        # is the order main.py's loop uses. Both read camera_x to decide
        # which goombas are live, so doing it the other way round would make
        # training and the browser disagree by one frame of camera travel.
        self._update_goombas()
        stomped, hit = self._resolve_goombas()
        self._update_camera()

        delta_x = self.mario.x - self.prev_x
        over_pit = self.senses.over_pit(self.mario, self.level)

        # -- 1. Forward progress, the main driver --------------------------
        # Paid in the air as well as on the ground, so committing to a jump
        # across a gap is never punished on the way over.
        reward += np.clip(delta_x, -8, 8) * 0.10
        if delta_x < 0:
            reward -= 0.05

        # -- 2. Speed ------------------------------------------------------
        # Progress alone cannot prefer fast: its integral over the level is
        # the level's length however long you take. So being alive costs, and
        # anything above a walk pays -- together those make a frame spent
        # running worth about twice a frame spent walking, locally, where PPO
        # can actually see it.
        reward -= self.time_cost
        # Absolute speed, so this has to be gated on actually going forwards
        # -- otherwise sprinting left collects the same bonus as sprinting
        # right. The progress term outweighs it today, but the documented
        # fine-tune workflow raises MARIO_SPEED_BONUS, and at that point
        # paying for fast backwards motion would start to bite.
        over_walk = self.mario.x_speed_absolute - smb.MAX_RIGHT_X_SPEED[1]
        if over_walk > 0 and delta_x > 0:
            span = smb.MAX_RIGHT_X_SPEED[0] - smb.MAX_RIGHT_X_SPEED[1]
            reward += self.speed_bonus * (over_walk / span)

        # -- 3. Gap crossing -- learned, not scripted ----------------------
        # We never say *when* to jump. We make the outcome of a crossing
        # valuable and falling in costly, and let PPO find the launch.
        if not self.mario.on_ground and over_pit:
            reward += 0.05
            if self._crossing_end is None:
                self._crossing_end = self.senses.pit_end_ahead(
                    self.mario, self.level)

        if self.mario.on_ground and self._crossing_end is not None:
            if self.mario.x >= self._crossing_end:
                reward += 2.0
            self._crossing_end = None

        # -- 4. Goombas ----------------------------------------------------
        reward += 10.0 * stomped
        self._stomps += stomped
        if hit:
            reward -= 100.0
            terminated = True
            self._outcome = "goomba"

        # -- 5. Death / completion -----------------------------------------
        floor_y = self.level.height * self.level.tile_size * SCALE
        if self.mario.y >= floor_y:
            reward -= 100.0
            terminated = True
            self._outcome = "pit"

        if self.mario.x >= self.finish_x:
            ahead_of_par = np.clip(1.0 - self._steps / self.par_steps, 0.0, 1.0)
            reward += 300.0 + 700.0 * float(ahead_of_par)
            terminated = True
            self._outcome = "flag"

        # -- 6. Episode limits ---------------------------------------------
        if self.mario.x > self.max_x:
            self.max_x = self.mario.x
            self._since_progress = 0
        else:
            self._since_progress += 1

        if not terminated:
            if self._since_progress >= self.stall_limit:
                truncated = True
                self._outcome = "stalled"
            elif self._steps >= self.max_steps:
                truncated = True
                self._outcome = "timeout"

        self.prev_x = self.mario.x
        info = {
            "x": float(self.mario.x),
            "max_x": float(self.max_x),
            "progress": float((self.max_x - self.start_x)
                              / max(self.finish_x - self.start_x, 1.0)),
            "steps": self._steps,
            "stomps": self._stomps,
            "finished": bool(self.mario.x >= self.finish_x),
            # Curriculum episodes start partway in. A "finish" from three
            # tiles before the flag is not the same event as a clear, so
            # anything reported as a completion rate has to filter on this.
            "from_start": bool(self.start_x <= 100.0 + self.start_jitter),
            "outcome": self._outcome,
        }
        return self._get_state(), float(reward), terminated, truncated, info

    # -- world -------------------------------------------------------------
    def _live_goombas(self):
        low = self.camera_x - GOOMBA_ACTIVE_MARGIN
        high = self.camera_x + SCREEN_WIDTH + GOOMBA_ACTIVE_MARGIN
        return [g for g in self.goombas if g.alive and low <= g.x <= high]

    def _update_goombas(self):
        goomba_mod.tick_interval_timers(DT)
        for g in self._live_goombas():
            g.update(DT, self.tiles.near(g.x, g.width * SCALE),
                     self.camera_x, SCREEN_WIDTH)

    def _resolve_goombas(self):
        """Coming down on a goomba's contact box stomps it; touching it any
        other way is fatal. Same rule main.py plays by."""
        if self.mario.dying:
            return 0, False
        box = self.mario.rect()
        for g in self._live_goombas():
            if not g.is_dangerous() or not box.colliderect(g.hitbox()):
                continue
            if self.mario.is_descending():
                g.squash()
                self.mario.stomp()
                return 1, False
            return 0, True
        return 0, False

    def _threats(self):
        return [g for g in self._live_goombas() if g.is_dangerous()]

    def _get_state(self):
        return np.array(
            self.senses.observe(self.mario, self.level, self._threats()),
            dtype=np.float32,
        )

    def _update_camera(self):
        if self.mario.x - self.camera_x > SCREEN_WIDTH // 2:
            self.camera_x = self.mario.x - SCREEN_WIDTH // 2
        if self.camera_x > self.level_pixel_width - SCREEN_WIDTH:
            self.camera_x = self.level_pixel_width - SCREEN_WIDTH
        if self.camera_x < 0:
            self.camera_x = 0

    def render(self):
        if not self.render_mode:
            return
        # Real per-frame dt so sprite/tile animations actually advance.
        dt = self.clock.tick(60) / 1000.0
        self.screen.fill((92, 148, 252))
        self.level.draw(self.screen, dt, self.camera_x, SCALE)
        for g in self.goombas:
            if g.alive:
                g.draw(self.screen, self.camera_x)
        self.mario.draw(self.screen, self.sprites, self.camera_x, dt)
        pygame.display.flip()
