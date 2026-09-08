import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pygame

from mario import Mario
from level_loader import Level
from sprite_manager import SpriteManager
from mario_ai import (
    FULL_JUMP_HOLD,
    LOOK,
    OBS_SIZE,
    SHORT_JUMP_HOLD,
    MarioSenses,
)

SCALE = 3
BASE_WIDTH, BASE_HEIGHT = 256, 240
SCREEN_WIDTH = BASE_WIDTH * SCALE
SCREEN_HEIGHT = BASE_HEIGHT * SCALE

# SHORT_JUMP_HOLD / FULL_JUMP_HOLD / LOOK / the observation layout all live
# in mario_ai.py, which the browser build imports too -- so what the policy
# sees here during training is literally the same code that runs in Pyodide.


class MarioEnv(gym.Env):
    def __init__(self, render_mode=False):
        pygame.init()
        pygame.display.set_mode((1, 1))
        super().__init__()

        self.render_mode = render_mode
        self.level = Level("levels/1-1.json", "tileset.json")
        self.mario = Mario(x=100, y=0, scale=SCALE)
        self.sprites = SpriteManager("sprites", SCALE)

        self.camera_x = 0
        self.prev_x = self.mario.x

        # Feature extraction + jump-hold state, shared with the web build.
        self.senses = MarioSenses()

        # Tracks the far edge of a pit Mario is currently airborne over,
        # so we can reward a successful crossing when he lands past it.
        self._crossing_end = None

        # Episode step counter — used to truncate runaway episodes.
        self._steps = 0
        self.max_steps = 3000

        # 0: idle  1: walk right  2: walk left
        # 3: short jump+right (~6 frames)
        # 4: full jump+right  (~18 frames, clears wide gaps)
        # 5: full jump only   (no horizontal)
        self.action_space = spaces.Discrete(6)

        # Observation layout is documented on MarioSenses.observe().
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0,
            shape=(OBS_SIZE,), dtype=np.float32
        )

        if self.render_mode:
            self.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
            self.clock = pygame.time.Clock()

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.level = Level("levels/1-1.json", "tileset.json")
        self.mario = Mario(x=100, y=0, scale=SCALE)
        self.camera_x = 0
        self.prev_x = self.mario.x
        self.senses.reset()
        self._crossing_end = None
        self._steps = 0
        return self._get_state(), {}

    def step(self, action):
        dt = 1 / 60
        terminated = False
        truncated = False
        reward = 0.0
        self._steps += 1

        was_on_ground = self.mario.on_ground
        x_before = self.mario.x

        self._apply_action(action, was_on_ground)

        self.mario.update(dt, self.camera_x, self.level.solid_at)
        self._update_camera()

        delta_x = self.mario.x - self.prev_x
        over_pit = self._over_pit()

        # ── 1. Forward progress (the main driver) ─────────────────────
        # Reward moving right whether on the ground or in the air, so
        # committing to a jump across a gap is never punished.
        reward += np.clip(delta_x, -8, 8) * 0.10
        if delta_x < 0:
            reward -= 0.05

        # ── 2. Gap crossing — learned, not scripted ───────────────────
        # We never tell Mario *when* to jump. We only make the outcome of
        # a successful crossing valuable and falling in a pit costly, and
        # let PPO discover that a max jump near the edge is how you earn it.
        if not self.mario.on_ground and over_pit:
            # Airborne out over the void — small per-frame bonus for
            # committing, so the arc that clears the gap gets credit early.
            reward += 0.05
            if self._crossing_end is None:
                self._crossing_end = self._pit_end_ahead()

        if self.mario.on_ground and self._crossing_end is not None:
            if self.mario.x >= self._crossing_end:
                reward += 2.0        # landed safely on the far side
            self._crossing_end = None    # crossing resolved either way

        # ── 3. Gentle grounded stability bonus ────────────────────────
        if self.mario.on_ground:
            reward += 0.01

        # ── 4. Discourage button spam (small, so it can still explore) ─
        if action in [3, 4, 5] and not was_on_ground:
            reward -= 0.05   # can't actually jump mid-air
        if action in [1, 3, 4] and delta_x < 1.0 and self.mario.on_ground:
            reward -= 0.05   # walking into a wall, going nowhere

        # ── 5. Death / completion ─────────────────────────────────────
        floor_y = self.level.height * self.level.tile_size * SCALE
        if self.mario.y >= floor_y:
            reward -= 50           # fell in a pit
            terminated = True

        level_pixel_width = self.level.width * self.level.tile_size * SCALE
        if self.mario.x >= level_pixel_width - 50:
            reward += 300          # reached the flag
            terminated = True

        reward -= 0.005  # tiny living penalty — nudges toward finishing

        # End (truncate) episodes that drag on so PPO keeps seeing fresh starts.
        if self._steps >= self.max_steps:
            truncated = True

        self.prev_x = self.mario.x
        return self._get_state(), reward, terminated, truncated, {}

    # ── policy-facing surface ─────────────────────────────────────────
    # These all forward to mario_ai.MarioSenses. Keeping the bodies in one
    # place is what guarantees the browser build and this env agree; the
    # thin wrappers stay because step()'s reward shaping reads them.

    def _apply_action(self, action, was_on_ground):
        self.senses.apply_action(self.mario, self.level, action, was_on_ground)

    def _over_pit(self):
        return self.senses.over_pit(self.mario, self.level)

    def _pit_end_ahead(self):
        return self.senses.pit_end_ahead(self.mario, self.level)

    def _get_state(self):
        return np.array(
            self.senses.observe(self.mario, self.level), dtype=np.float32
        )


    def _update_camera(self):
        if self.mario.x - self.camera_x > SCREEN_WIDTH // 2:
            self.camera_x = self.mario.x - SCREEN_WIDTH // 2
        level_pixel_width = self.level.width * self.level.tile_size * SCALE
        if self.camera_x > level_pixel_width - SCREEN_WIDTH:
            self.camera_x = level_pixel_width - SCREEN_WIDTH

    def render(self):
        if not self.render_mode:
            return
        # Real per-frame dt so sprite/tile animations actually advance.
        # (Passing 0 froze Mario on the first walk frame, frame_17.)
        dt = self.clock.tick(60) / 1000.0
        self.screen.fill((92, 148, 252))
        self.level.draw(self.screen, dt, self.camera_x, SCALE)
        self.mario.draw(self.screen, self.sprites, self.camera_x, dt)
        pygame.display.flip()