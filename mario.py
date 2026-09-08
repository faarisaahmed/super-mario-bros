import os

import pygame

import smb_physics as smb

pygame.mixer.init()
pygame.mixer.set_num_channels(16)

jump_sound = pygame.mixer.Sound(os.path.join("sfx", "jump_effect.ogg"))
jump_sound.set_volume(0.1)

death_sound = pygame.mixer.Sound(os.path.join("music", "deathsound.mp3"))
death_sound.set_volume(0.5)

# Player_State values, same meaning as the original (JumpEngine dispatch,
# smbdis.asm:5511). Climbing is not implemented here.
STATE_GROUND = 0
STATE_JUMPING = 1
STATE_FALLING = 2

# Player_MovingDir / PlayerFacingDir use the joypad's own bit values, which is
# what lets X_Physics compare the two directly.
DIR_RIGHT = 1
DIR_LEFT = 2


class Mario:
    # Collision box in unscaled game pixels. Deliberately smaller than the
    # 12x16 sprite: it hugs the body core, so the cap's top row and the arms
    # that swing out during a jump don't count as Mario. The box is a fixed
    # size for every pose and is anchored to the bottom of the sprite (his
    # feet), which is why a jump frame's flung-out limbs poke outside it.
    # See docs/hitboxes.md for how these were measured off the reference art.
    HITBOX_WIDTH = 11
    HITBOX_HEIGHT = 13

    def __init__(self, x, y, scale):
        self.scale = scale
        # Position is kept in whole game pixels, because the original's
        # collision samples individual pixels and a fractional position would
        # make those lookups meaningless. Sub-pixel motion lives in the move
        # force accumulators instead, exactly as it does on the NES.
        self.gx = int(round(x / scale))
        self.gy = int(round(y / scale))

        self.width = self.HITBOX_WIDTH
        self.height = self.HITBOX_HEIGHT

        self.direction = "right"
        self.current_animation = "idle right"

        # --- SMB physics state ------------------------------------------
        # Horizontal speed in 4.4 fixed point (1/16 px per frame) plus an
        # 8-bit fraction of that; vertical speed in whole px per frame plus
        # its own 8-bit fraction, and a separate subpixel accumulator for
        # position. This mirrors Player_X_Speed / Player_X_MoveForce /
        # Player_Y_Speed / Player_Y_MoveForce / Player_YMF_Dummy.
        self.x_speed = 0
        # Two *different* horizontal fractions in the original, and conflating
        # them silently corrupts acceleration:
        #   Player_X_MoveForce    ($0705) - fraction of SPEED, used by friction
        #   SprObject_X_MoveForce ($0400) - fraction of POSITION, used by the
        #                                   movement routine
        # Vertically there is no such split: SprObject_Y_MoveForce and
        # Player_Y_MoveForce are both $0433, so one variable is correct there.
        self.x_moveforce = 0
        self.x_position_frac = 0
        self.y_speed = 0
        self.y_moveforce = 0
        self.ymf_dummy = 0

        self.vertical_force = smb.FALL_M_FORCE[0]
        self.vertical_force_down = smb.FALL_M_FORCE[0]
        self.jump_origin_y = float(y)

        self.state = STATE_FALLING
        self.moving_dir = DIR_RIGHT
        self.facing_dir = DIR_RIGHT
        self.running_timer = 0
        self.running_speed = 0

        # Per-frame max speeds and accelerator, recomputed by _x_physics.
        self.max_left_speed = smb.MAX_LEFT_X_SPEED[1]
        self.max_right_speed = smb.MAX_RIGHT_X_SPEED[1]
        self.friction_adder = smb.FRICTION[1]

        # Buttons, latched once per physics frame like the real joypad read.
        self.btn_left = False
        self.btn_right = False
        self.btn_a = False
        self.btn_b = False
        self.prev_btn_a = False

        # Player_CollisionBits. PlayerBGCollision resets this to $ff every
        # frame and ImpedePlayerMove clears the bit for whichever direction
        # just hit something. ImposeFriction masks the held buttons through
        # it, so the frame after a wall hit you get no acceleration at all --
        # that one-frame stall is why running into a wall doesn't instantly
        # rebuild speed.
        self.collision_bits = 0xFF

        self.on_ground = False
        self.dying = False
        self.death_freeze_left = 0

        # Physics runs on a fixed 60Hz step; dt only decides how many steps.
        self._accumulator = 0.0

    # -- position -----------------------------------------------------------
    # x/y stay readable and writable in scaled screen pixels so the rest of
    # the project (rendering, camera, the training env) is unaffected.

    @property
    def x(self):
        return float(self.gx * self.scale)

    @x.setter
    def x(self, value):
        self.gx = int(round(value / self.scale))

    @property
    def y(self):
        return float(self.gy * self.scale)

    @y.setter
    def y(self, value):
        self.gy = int(round(value / self.scale))

    @property
    def smb_x(self):
        """Player_X_Position -- the hitbox is inset from it by 3 pixels."""
        return self.gx - smb.HITBOX_ORIGIN_DX

    @property
    def smb_y(self):
        """Player_Y_Position -- the hitbox starts 20 pixels below it."""
        return self.gy - smb.HITBOX_ORIGIN_DY

    # -- speeds the outside world asks about --------------------------------

    @property
    def x_speed_absolute(self):
        """Player_XSpeedAbsolute — magnitude of x_speed, in 1/16 px/frame."""
        return abs(self.x_speed)

    @property
    def velocity_x(self):
        """Horizontal speed in scaled pixels per second."""
        return (self.x_speed / 16.0) * 60.0 * self.scale

    @property
    def velocity_y(self):
        """Vertical speed in scaled pixels per second."""
        return (self.y_speed + self.y_moveforce / 256.0) * 60.0 * self.scale

    @property
    def horizontal_speed(self):
        """Top walking speed, scaled px/s — 1.5 px/frame in the original."""
        return (smb.MAX_RIGHT_X_SPEED[1] / 16.0) * 60.0 * self.scale

    @property
    def running_speed_max(self):
        """Top running speed, scaled px/s — 2.5 px/frame in the original."""
        return (smb.MAX_RIGHT_X_SPEED[0] / 16.0) * 60.0 * self.scale

    @property
    def terminal_velocity(self):
        """Maximum fall speed, scaled px/s — 4 px/frame in the original."""
        return smb.MAX_FALL_SPEED * 60.0 * self.scale

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y),
                           int(self.width * self.scale),
                           int(self.height * self.scale))

    def is_descending(self):
        """Whether a collision counts as a stomp instead of a death.

        ChkForPlayerInjury (smbdis.asm:11376) branches to the stomp only when
        vertical speed is *strictly* positive: moving up is an injury, and so
        is a speed of exactly zero. That zero case is the important one --
        standing or running along the ground leaves y_speed at 0, so walking
        into a goomba has to be fatal, not a free kill.
        """
        return self.y_speed > 0

    # -- input --------------------------------------------------------------

    def set_buttons(self, left=False, right=False, a=False, b=False):
        """Set the joypad state directly. Both the keyboard path and the
        training environment go through here, so both drive identical
        physics."""
        self.btn_left = left
        self.btn_right = right
        self.btn_a = a
        self.btn_b = b

    def handle_input(self, keys, controller=None):
        if self.dying:
            return          # the death arc plays out on its own

        left = bool(keys[pygame.K_LEFT])
        right = bool(keys[pygame.K_RIGHT])
        jump = bool(keys[pygame.K_z])
        run = bool(keys[pygame.K_x])

        if controller:
            if controller.get_button(13):        # D-pad left
                left = True
            if controller.get_button(14):        # D-pad right
                right = True
            if controller.get_numaxes() > 0:
                axis_x = controller.get_axis(0)
                if axis_x < -0.5:
                    left = True
                if axis_x > 0.5:
                    right = True
            if controller.get_button(0):         # A
                jump = True
            if controller.get_button(2):         # X / square, used as B
                run = True

        self.set_buttons(left=left, right=right, a=jump, b=run)

    def _pressed_dir(self):
        """Left_Right_Buttons — the raw joypad bits, which double as a
        direction value comparable against moving/facing direction."""
        return (DIR_LEFT if self.btn_left else 0) | (DIR_RIGHT if self.btn_right else 0)

    # -- events -------------------------------------------------------------

    def start_jump(self):
        """ProcJumping, smbdis.asm:6081. Which row of the jump tables applies
        is decided by how fast he is already moving, so running jumps launch
        harder *and* fall slower."""
        index = smb.jump_index(self.x_speed_absolute)
        self.jump_origin_y = self.y
        self.vertical_force = smb.JUMP_M_FORCE[index]
        self.vertical_force_down = smb.FALL_M_FORCE[index]
        self.y_moveforce = smb.INIT_M_FORCE[index]
        self.y_speed = smb.PLAYER_Y_SPEED[index]
        self.state = STATE_JUMPING
        self.on_ground = False
        jump_sound.play()

    def stomp(self):
        """SBnce, smbdis.asm:11512. Sets vertical speed and nothing else.

        The gravity the bounce runs against is therefore whatever is already
        loaded, which is always the *falling* value -- the weak jump gravity
        is only ever written when a jump starts (GetYPhy, smbdis.asm:6117),
        and passing the apex to fall onto the goomba has long since dumped it.
        Holding A does not raise the bounce; it lands around one block either
        way, and slightly less after a running jump because that jump carries
        harder fall gravity.
        """
        if self.dying:
            return
        # Only the speed byte. SBnce leaves Player_Y_MoveForce and the
        # subpixel accumulator untouched, so the fraction carried in from the
        # fall survives into the bounce.
        self.y_speed = smb.STOMP_BOUNCE_Y_SPEED
        self.state = STATE_JUMPING
        self.on_ground = False

    def die(self):
        """KillPlayer, smbdis.asm:11427. Horizontal speed is halted, he is
        launched at 4 px/frame, and the whole thing freezes for 16 frames
        before the arc starts."""
        if self.dying:
            return
        self.dying = True
        self.death_freeze_left = smb.DEATH_FREEZE_FRAMES
        self.x_speed = 0
        self.x_moveforce = 0
        self.y_speed = smb.DEATH_Y_SPEED
        self.y_moveforce = 0
        self.ymf_dummy = 0
        self.vertical_force = smb.DEATH_VERTICAL_FORCE
        self.state = STATE_JUMPING
        self.on_ground = False
        self.current_animation = "death"

        # The overworld track cuts out the instant he is hit, leaving the
        # death jingle alone.
        pygame.mixer.music.stop()
        death_sound.play()

    # -- physics ------------------------------------------------------------

    def _x_physics(self):
        """X_Physics, smbdis.asm:6146. Picks the max-speed row and the
        accelerator for this frame. Water areas are not implemented, so the
        AreaType branch always takes the land path."""
        speed_index = 0
        friction_index = 0
        pressed = self._pressed_dir()

        if self.state != STATE_GROUND:
            if self.x_speed_absolute >= smb.AIR_RUN_SPEED:
                speed_index, friction_index = 0, 0
            else:
                speed_index, friction_index = self._chk_r_fast()
        elif pressed and pressed == self.moving_dir and self.btn_b:
            self.running_timer = smb.RUNNING_TIMER_SET
            speed_index, friction_index = 0, 0
        elif pressed and pressed == self.moving_dir and self.running_timer:
            speed_index, friction_index = 0, 0
        else:
            speed_index, friction_index = self._chk_r_fast()

        self.max_left_speed = smb.MAX_LEFT_X_SPEED[speed_index]
        self.max_right_speed = smb.MAX_RIGHT_X_SPEED[speed_index]

        adder = smb.FRICTION[friction_index]
        if self.facing_dir != self.moving_dir:
            adder <<= 1          # skidding turns you around twice as fast
        self.friction_adder = adder

    def _chk_r_fast(self):
        """ChkRFast, smbdis.asm:6160. Every path that lands here on dry land
        arrives with the speed index at 0, so this yields the walking row;
        only the water branch (not implemented) arrives with it at 1."""
        speed_index = 1
        friction_index = 1
        if self.running_speed or self.x_speed_absolute >= smb.FAST_FRICTION_SPEED:
            friction_index += 1
        return speed_index, friction_index

    def _impose_friction(self):
        """ImposeFriction, smbdis.asm:6227. One accelerator serves for both
        speeding up and slowing down; which side it is applied to depends on
        the buttons, or on the direction of travel when nothing is held."""
        # ImposeFriction opens with `and Player_CollisionBits`, so a direction
        # you just collided in counts as not held for one frame.
        pressed = self._pressed_dir() & self.collision_bits
        if pressed & DIR_RIGHT:
            accelerate_right = True
        elif pressed & DIR_LEFT:
            accelerate_right = False
        elif self.x_speed == 0:
            return
        else:
            # Nothing held: push against whichever way he is drifting.
            accelerate_right = self.x_speed < 0

        velocity = (self.x_speed << 8) | self.x_moveforce
        if accelerate_right:
            velocity += self.friction_adder
        else:
            velocity -= self.friction_adder

        self.x_moveforce = velocity & 0xff
        self.x_speed = smb.signed_byte(velocity >> 8)

        if accelerate_right:
            if self.x_speed >= self.max_right_speed:
                self.x_speed = self.max_right_speed
        else:
            if self.x_speed < self.max_left_speed:
                self.x_speed = self.max_left_speed

    def _move_horizontally(self):
        """MoveObjectHorizontally, smbdis.asm:7541. Splits the 4.4 speed byte
        into whole pixels and sixteenths, banks the sixteenths in the move
        force, and returns the whole pixels to travel this frame."""
        speed = self.x_speed & 0xff
        sixteenths = (speed << 4) & 0xff
        whole = speed >> 4
        if whole >= 8:                       # sign-extend a negative speed
            whole |= 0xf0
        whole = smb.signed_byte(whole)

        total = self.x_position_frac + sixteenths
        self.x_position_frac = total & 0xff
        return whole + (1 if total > 0xff else 0)

    def _impose_gravity(self):
        """ImposeGravity, smbdis.asm:7704, with the upward-force argument
        zero as ImposeGravitySprObj passes it for the player. Returns whole
        pixels moved this frame."""
        total = self.ymf_dummy + self.y_moveforce
        self.ymf_dummy = total & 0xff
        moved = self.y_speed + (1 if total > 0xff else 0)

        total = self.y_moveforce + self.vertical_force
        self.y_moveforce = total & 0xff
        self.y_speed = smb.signed_byte(self.y_speed + (1 if total > 0xff else 0))

        if self.y_speed >= smb.MAX_FALL_SPEED and self.y_moveforce >= 0x80:
            self.y_speed = smb.MAX_FALL_SPEED
            self.y_moveforce = 0

        return moved

    def _get_player_anim_speed(self):
        """The half of GetPlayerAnimSpeed (smbdis.asm:6198) that affects
        physics: it latches RunningSpeed, and snaps a slow skid around."""
        absolute = self.x_speed_absolute
        pressed = self._pressed_dir()

        if absolute >= smb.RUN_SPEED_THRESHOLD:
            self.running_speed = absolute
            return
        if pressed == 0:
            return
        if pressed == self.moving_dir:
            self.running_speed = 0
            return
        # Skidding. Below a threshold he stops dead and faces the new way.
        if absolute < smb.SKID_TURNAROUND_SPEED:
            self.moving_dir = self.facing_dir
            self.x_speed = 0
            self.x_moveforce = 0

    def _apply_horizontal(self, camera_x):
        """Move only. Collision is a separate pass afterwards, as it is in the
        original -- PlayerBGCollision runs at the end of PlayerCtrlRoutine,
        after everything has already moved."""
        moved = self._move_horizontally()
        if moved:
            self.gx += moved
        left_limit = int(camera_x // self.scale)
        if self.gx < left_limit:
            self.gx = left_limit
            self.x_speed = 0
            self.x_moveforce = 0

    def _apply_vertical(self):
        self.gy += self._impose_gravity()

    # -- background collision (PlayerBGCollision, smbdis.asm:11902) ----------

    def _block_at(self, solid_at, adder_index):
        """Sample the single pixel this adder points at and report whether the
        metatile there is solid. BlockBufferCollision, smbdis.asm:13053."""
        px = self.smb_x + smb.BLOCK_X_ADDER[adder_index]
        py = self.smb_y + smb.BLOCK_Y_ADDER[adder_index]
        return solid_at(px // 16, py // 16)

    def _impede_player_move(self, side):
        """ImpedePlayerMove, smbdis.asm:12318. `side` is 1 to stop rightward
        travel and 2 to stop leftward. Nudges him one pixel clear and kills
        his horizontal speed -- it does not snap him to the tile edge."""
        # The collision bit is cleared whether or not he actually gets moved,
        # because the original falls through to ExIPM either way.
        if side == 1:
            self.collision_bits &= ~DIR_RIGHT & 0xFF
            if self.x_speed < 0:
                return
            adder = -1
        else:
            self.collision_bits &= ~DIR_LEFT & 0xFF
            if self.x_speed >= 1:
                return
            adder = 1
        # Only the speed is nullified. The original leaves Player_X_MoveForce
        # alone here, so the sub-pixel remainder survives the collision and
        # feeds straight back into the next frame's acceleration.
        self.x_speed = 0
        self.gx += adder

    def _player_bg_collision(self, solid_at):
        base = smb.BLOCK_ADDER_BASE_SMALL
        self.collision_bits = 0xFF

        # Assume falling; only the foot check below can put him back on the
        # ground. This *is* the original's ground detection -- there is no
        # separate sensor anywhere in the ROM.
        if self.state == STATE_GROUND:
            self.state = STATE_FALLING
        self.on_ground = False

        # --- head ---------------------------------------------------------
        if self.smb_y >= smb.PLAYER_BG_UPPER_EXTENT_SMALL:
            if self._block_at(solid_at, base):
                low = self.smb_y & 0x0F
                if self.y_speed < 0 and low >= smb.HEAD_LOW_NYBBLE_MIN:
                    # NYSpd: cancel the rest of the jump, but keep him rising
                    # by a single pixel this frame like the original does.
                    self.y_speed = 1
                    self.y_moveforce = 0

        # --- feet ---------------------------------------------------------
        foot_left = self._block_at(solid_at, base + 1)
        foot_right = self._block_at(solid_at, base + 2)
        if (foot_left or foot_right) and self.y_speed >= 0:
            low = self.smb_y & 0x0F
            if low >= smb.FOOT_LOW_NYBBLE_MAX:
                # Too deep into the block to stand on it, so it counts as a
                # wall in whichever direction he was travelling.
                self._impede_player_move(self.moving_dir)
            else:
                # LandPlyr: snap down to the tile boundary and stop.
                self.gy = ((self.smb_y & 0xF0) + smb.HITBOX_ORIGIN_DY)
                self.y_speed = 0
                self.y_moveforce = 0
                self.ymf_dummy = 0
                self.state = STATE_GROUND
                self.on_ground = True

        # --- sides --------------------------------------------------------
        # Two points down the left side, then two down the right. The counter
        # in $00 doubles as the direction handed to ImpedePlayerMove: 2 while
        # checking the left side, 1 while checking the right.
        index = base + 2
        for side in (2, 1):
            hit = False
            for _ in range(2):
                index += 1
                if self._block_at(solid_at, index):
                    hit = True
                    break
            if hit:
                self._impede_player_move(side)
                return

    def _step_death(self):
        """PlayerDeath, smbdis.asm:5766. Nothing moves until the master timer
        drops below $f0; after that he rises and falls through the floor,
        with VerticalForce pinned at $28 by LRAir."""
        if self.death_freeze_left > 0:
            self.death_freeze_left -= 1
            return
        self.vertical_force = smb.DEATH_VERTICAL_FORCE
        self.gy += self._impose_gravity()

    def _step_frame(self, camera_x, solid_at):
        if self.dying:
            self._step_death()
            return

        # RunningTimer lives in the frame-timer block the original ticks down
        # once a frame (DecTimers, smbdis.asm:787). Without this the 10-frame
        # grace never expires and one tap of B leaves you running forever.
        if self.running_timer > 0:
            self.running_timer -= 1

        # PlayerPhysicsSub: a fresh press of A off the ground starts a jump.
        if self.btn_a and not self.prev_btn_a and self.state == STATE_GROUND:
            self.start_jump()
        self._x_physics()

        if self.state == STATE_GROUND:
            self._get_player_anim_speed()
            if self._pressed_dir():
                self.facing_dir = self._pressed_dir()
            self._impose_friction()
            self._apply_horizontal(camera_x)
        else:
            # JumpSwimSub / FallingSub: while rising with A still held the
            # weak jump gravity stays in effect; the frame he lets go, the
            # much stronger falling gravity takes over. That, and nothing
            # else, is what makes the jump variable-height.
            rising = self.y_speed < 0
            holding = self.btn_a and self.prev_btn_a
            # The original compares JumpOrigin - Y as an unsigned byte, so
            # being *below* the origin wraps to a large number and counts as
            # "not just started" rather than as a tiny rise. Hence the >= 0.
            risen = (self.jump_origin_y - self.y) / self.scale
            just_started = 0 <= risen < smb.DIFF_TO_HALT_JUMP
            if not rising or not (holding or just_started):
                self.vertical_force = self.vertical_force_down

            if self._pressed_dir():
                self._impose_friction()
            self._apply_horizontal(camera_x)
            self._apply_vertical()

        # ChkMoveDir: moving direction follows the sign of horizontal speed.
        if self.x_speed > 0:
            self.moving_dir = DIR_RIGHT
        elif self.x_speed < 0:
            self.moving_dir = DIR_LEFT

        # PlayerBGCollision comes last, after everything has moved.
        self._player_bg_collision(solid_at)
        self.prev_btn_a = self.btn_a

    def update(self, dt, camera_x, solid_at):
        """Advance the fixed 60Hz simulation by however many whole frames dt
        covers. The original had no dt — every constant above is per frame,
        so stepping at a fixed rate is what keeps them meaningful.

        `solid_at(col, row)` reports whether the metatile at a grid cell is
        solid; the original's collision samples points, not rectangles, so a
        grid lookup is what it needs rather than a list of rects.
        """
        self._accumulator += dt
        # Don't let a long stall (window drag, first frame) spiral.
        if self._accumulator > 0.25:
            self._accumulator = 0.25
        while self._accumulator >= smb.FRAME_TIME:
            self._accumulator -= smb.FRAME_TIME
            self._step_frame(camera_x, solid_at)

        self.direction = "right" if self.facing_dir == DIR_RIGHT else "left"
        if not self.dying:
            self._set_animation()

    def _set_animation(self):
        if self.state != STATE_GROUND:
            self.current_animation = f"jump {self.direction}"
        elif self.x_speed != 0:
            self.current_animation = f"walk {self.direction}"
        else:
            self.current_animation = f"idle {self.direction}"

    def draw(self, screen, sprites, camera_x, dt):
        frame = sprites.get_frame(self.current_animation, dt)
        diff_x = (frame.get_width() - (self.width * self.scale)) // 2
        img_height = frame.get_height()
        hitbox_bottom = self.y + (self.height * self.scale)

        draw_x = int(self.x - camera_x - diff_x)
        draw_y = int(hitbox_bottom - img_height) + 1 * self.scale
        screen.blit(frame, (draw_x, draw_y))
