import os

import pygame

import smb_physics as smb

# The original drives every enemy's interval timer off one shared counter that
# only fires every 21 frames (DecTimers, smbdis.asm:789). Keeping it shared and
# free-running is what makes a stomped goomba linger for a variable 22-42
# frames rather than a fixed count. main.py ticks this once per frame.
_interval_clock = {"countdown": smb.INTERVAL_TIMER_PERIOD, "fired": False}


def tick_interval_timers(dt):
    """Advance the shared interval clock. Call once per rendered frame."""
    _interval_clock["fired"] = False
    _interval_clock["countdown"] -= 1
    if _interval_clock["countdown"] < 0:
        _interval_clock["countdown"] = smb.INTERVAL_TIMER_PERIOD
        _interval_clock["fired"] = True


def interval_timer_fired():
    return _interval_clock["fired"]

# Caches of scaled sprites, keyed by scale, so every Goomba on screen shares
# one set of surfaces instead of reloading the PNGs.
_frame_cache = {}
_squashed_cache = {}


def _scaled(name, scale):
    img = pygame.image.load(
        os.path.join("sprites", "enemies", "goomba", name)
    ).convert_alpha()
    w, h = img.get_size()
    return pygame.transform.scale(img, (w * scale, h * scale))


def _load_frames(scale):
    if scale not in _frame_cache:
        # the two walking sprites
        _frame_cache[scale] = [_scaled("goomba1.png", scale),
                               _scaled("goomba2.png", scale)]
    return _frame_cache[scale]


def _load_squashed(scale):
    """The flattened sprite. Its art sits in the bottom half of the 16x16
    cell, so it draws at the goomba's normal position and reads as squashed
    flat against the floor."""
    if scale not in _squashed_cache:
        _squashed_cache[scale] = _scaled("goomba3.png", scale)
    return _squashed_cache[scale]


class Goomba:
    # NormalXSpdData $f8 -- half a pixel a frame, a third of Mario's walk.
    WALK_X_SPEED = smb.ENEMY_WALK_X_SPEED[0]
    # The two frames swap about every 8 game frames (~0.13s) in the real game.
    ANIM_SPEED = 0.13

    # A goomba has two boxes, and they are not the same thing:
    #
    #   rect()    - the full 16x16 cell, used against tiles. It has to stay
    #               sprite-sized or the goomba sinks into the floor and stops
    #               bouncing off pipes at the right spot.
    #   hitbox()  - the smaller box that decides Mario-vs-goomba contact. It
    #               sits in the middle of the cell, well clear of the floor,
    #               so a near-miss over the head or past the feet isn't a hit.
    #
    # Offsets are unscaled game pixels into the 16x16 cell; see
    # docs/hitboxes.md for where these numbers come from.
    # BoundBoxCtrlData row $09 (SmallBBox, smbdis.asm), $03,$0e,$0d,$14: the
    # box runs Enemy_X+3..+13 and Enemy_Y+14..+20. Read against a goomba
    # standing on 1-1's floor -- Enemy_Y $b8, so rows 198..204 with the
    # sprite at 192..207 -- that puts the top 6 pixels down the sprite, not
    # the 5 originally measured off the reference art.
    HITBOX_OFFSET_X = 3
    HITBOX_OFFSET_Y = 6
    HITBOX_WIDTH = 11
    HITBOX_HEIGHT = 7

    # How long the flattened sprite lingers. The original doesn't count
    # frames: it sets EnemyIntervalTimer to $10 and erases the goomba when
    # that timer reads $0e, and interval timers only tick every 21 frames.
    # Two ticks, so the sprite lasts 22-42 frames depending on where the
    # shared interval clock happened to be. See smb_physics.py.
    SQUASH_TIMER_SET = smb.SQUASH_TIMER_SET
    SQUASH_TIMER_KILL = smb.SQUASH_TIMER_KILL

    def __init__(self, grid_x, grid_y, tile_size, scale):
        self.scale = scale
        self.width = 16
        self.height = 16

        self.x = float(grid_x * tile_size * scale)
        self.y = float(grid_y * tile_size * scale)

        # Same fixed-point state as the player: 4.4 horizontal speed with an
        # 8-bit fraction, whole-pixel vertical speed with its own fraction.
        # Heads left the instant the level starts.
        self.x_speed = self.WALK_X_SPEED
        self.x_moveforce = 0
        self.y_speed = 0
        self.y_moveforce = 0
        self.ymf_dummy = 0
        self._accumulator = 0.0

        self.frames = _load_frames(scale)
        self.squashed_frame = _load_squashed(scale)
        self.frame_index = 0
        self.anim_timer = 0.0

        self.squashed = False
        self.squash_timer = 0

        self.alive = True
        # Like the NES original, a goomba is dormant until the camera reveals
        # it — it only starts walking once it scrolls into view.
        self.active = False

    def rect(self):
        """Collision box against tiles — the whole 16x16 cell."""
        return pygame.Rect(
            int(self.x), int(self.y),
            int(self.width * self.scale), int(self.height * self.scale)
        )

    def is_dangerous(self):
        """Whether Mario can still be hurt by — or stomp — this one. A goomba
        already flattened underfoot is inert for the rest of its 20 frames."""
        return self.alive and not self.squashed

    def squash(self):
        """Stomped: stops dead, flattens, and vanishes 20 frames later."""
        if not self.is_dangerous():
            return
        self.squashed = True
        self.squash_timer = self.SQUASH_TIMER_SET
        self.x_speed = 0
        self.x_moveforce = 0
        self.y_speed = 0
        self.y_moveforce = 0

    def hitbox(self):
        """Contact box against Mario — inset from the sprite on every side."""
        s = self.scale
        return pygame.Rect(
            int(self.x + self.HITBOX_OFFSET_X * s),
            int(self.y + self.HITBOX_OFFSET_Y * s),
            int(self.HITBOX_WIDTH * s),
            int(self.HITBOX_HEIGHT * s),
        )

    def update(self, dt, solid_tiles, camera_x=0, screen_width=0):
        # Squashed goombas don't walk or fall — they just count down.
        if self.squashed:
            if interval_timer_fired() and self.squash_timer > 0:
                self.squash_timer -= 1
            if self.squash_timer <= self.SQUASH_TIMER_KILL:
                self.alive = False
            return

        # Stay frozen until the viewport reaches this goomba; once woken it
        # keeps moving even after walking back off-screen.
        if not self.active:
            if self.x <= camera_x + screen_width:
                self.active = True
            else:
                return

        # Physics steps at a fixed 60Hz, same as the player, because every
        # constant involved is per frame rather than per second.
        self._accumulator += dt
        if self._accumulator > 0.25:
            self._accumulator = 0.25
        while self._accumulator >= smb.FRAME_TIME:
            self._accumulator -= smb.FRAME_TIME
            self._step_frame(solid_tiles)

        # --- Walk animation -------------------------------------------
        self.anim_timer += dt
        if self.anim_timer >= self.ANIM_SPEED:
            self.anim_timer = 0.0
            self.frame_index = (self.frame_index + 1) % len(self.frames)

    def _step_frame(self, solid_tiles):
        # --- Horizontal move + wall/pipe/block bounce -----------------
        speed = self.x_speed & 0xff
        sixteenths = (speed << 4) & 0xff
        whole = speed >> 4
        if whole >= 8:
            whole |= 0xf0
        total = self.x_moveforce + sixteenths
        self.x_moveforce = total & 0xff
        moved = smb.signed_byte(whole) + (1 if total > 0xff else 0)

        if moved:
            self.x += moved * self.scale
            box = self.rect()
            for tile in solid_tiles:
                if box.colliderect(tile):
                    if moved > 0:
                        self.x = float(tile.left - box.width)
                    else:
                        self.x = float(tile.right)
                    self.x_speed = -self.x_speed      # turn around
                    box = self.rect()

        # Also flip at the very start of the level.
        if self.x < 0:
            self.x = 0.0
            self.x_speed = abs(self.x_speed)

        # --- Gravity + landing ----------------------------------------
        # MoveD_EnemyVertically -> SetHiMax: enemies use their own force and
        # top out at 3 px/frame rather than the player's 4.
        total = self.ymf_dummy + self.y_moveforce
        self.ymf_dummy = total & 0xff
        moved = self.y_speed + (1 if total > 0xff else 0)

        total = self.y_moveforce + smb.ENEMY_GRAVITY
        self.y_moveforce = total & 0xff
        self.y_speed = smb.signed_byte(self.y_speed + (1 if total > 0xff else 0))
        if self.y_speed >= smb.ENEMY_MAX_FALL_SPEED and self.y_moveforce >= 0x80:
            self.y_speed = smb.ENEMY_MAX_FALL_SPEED
            self.y_moveforce = 0

        if moved:
            self.y += moved * self.scale
            box = self.rect()
            for tile in solid_tiles:
                if box.colliderect(tile):
                    if moved > 0:
                        self.y = float(tile.top - box.height)
                    else:
                        self.y = float(tile.bottom)
                    self.y_speed = 0
                    self.y_moveforce = 0
                    self.ymf_dummy = 0
                    box = self.rect()

    def draw(self, screen, camera_x):
        img = self.squashed_frame if self.squashed else self.frames[self.frame_index]
        screen.blit(img, (int(self.x - camera_x), int(self.y)))
