import pygame
import math
import os

pygame.mixer.init()
pygame.mixer.set_num_channels(16)

jump_sound = pygame.mixer.Sound(os.path.join("sfx", "jump_effect.ogg"))
jump_sound.set_volume(0.1)

class Mario:
    def __init__(self, x, y, scale):
        self.x = float(x)
        self.y = float(y)
        self.scale = scale

        self.width = 12    
        self.height = 16   

        self.direction = "right"
        self.current_animation = "idle right"

        self.velocity_x = 0
        self.velocity_y = 0
        self.on_ground = False
        self.z_was_pressed = False 

        self.gravity = 800 * self.scale  
        
        target_max_height = 70 * self.scale
        self.jump_force = -math.sqrt(2 * self.gravity * target_max_height)
        
        target_min_height = 24 * self.scale
        self.min_jump_velocity = -math.sqrt(2 * self.gravity * target_min_height)

        self.terminal_velocity = 400 * self.scale 
        self.horizontal_speed = 90 * self.scale

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), 
                           int(self.width * self.scale), 
                           int(self.height * self.scale))

    def handle_input(self, keys, controller=None):
        self.velocity_x = 0

        move_left = False
        move_right = False
        jump_pressed = False

        # --- KEYBOARD ---
        if keys[pygame.K_RIGHT]:
            move_right = True
        if keys[pygame.K_LEFT]:
            move_left = True
        if keys[pygame.K_z]:
            jump_pressed = True

        # --- CONTROLLER ---
        if controller:
            # D-Pad (mapped as buttons on your system)
            if controller.get_button(13):  # D-pad left
                move_left = True
            if controller.get_button(14):  # D-pad right
                move_right = True

            # Left joystick
            if controller.get_numaxes() > 0:
                axis_x = controller.get_axis(0)
                if axis_x < -0.5:
                    move_left = True
                if axis_x > 0.5:
                    move_right = True

            # A button only
            if controller.get_button(0):  # A
                jump_pressed = True

        # --- APPLY MOVEMENT ---
        if move_right:
            self.velocity_x = self.horizontal_speed
            self.direction = "right"
        elif move_left:
            self.velocity_x = -self.horizontal_speed
            self.direction = "left"

        # --- JUMP LOGIC ---
        if jump_pressed:
            if not self.z_was_pressed and self.on_ground:
                self.velocity_y = self.jump_force
                self.on_ground = False
                self.y -= 2 
                jump_sound.play()
                
            self.z_was_pressed = True
        else:
            if self.velocity_y < self.min_jump_velocity:
                self.velocity_y = self.min_jump_velocity
            self.z_was_pressed = False

    def update(self, dt, camera_x, solid_tiles):
        self.x += self.velocity_x * dt

        if self.x < camera_x:
            self.x = float(camera_x)

        mario_rect = self.rect()
        for tile in solid_tiles:
            if mario_rect.colliderect(tile):
                if self.velocity_x > 0:
                    self.x = float(tile.left - mario_rect.width)
                elif self.velocity_x < 0:
                    self.x = float(tile.right)
                self.velocity_x = 0
                mario_rect = self.rect()

        self.velocity_y += self.gravity * dt
        if self.velocity_y > self.terminal_velocity:
            self.velocity_y = self.terminal_velocity
        self.y += self.velocity_y * dt
        
        mario_rect = self.rect()
        for tile in solid_tiles:
            if mario_rect.colliderect(tile):
                if self.velocity_y > 0: 
                    self.y = float(tile.top - mario_rect.height)
                    self.velocity_y = 0
                elif self.velocity_y < 0: 
                    self.y = float(tile.bottom)
                    self.velocity_y = 0
                mario_rect = self.rect()

        ground_sensor = pygame.Rect(int(self.x), int(self.y + 1), 
                                   int(self.width * self.scale), 
                                   int(self.height * self.scale))
        
        self.on_ground = False
        for tile in solid_tiles:
            if ground_sensor.colliderect(tile):
                self.on_ground = True
                break

        if not self.on_ground:
            self.current_animation = f"jump {self.direction}"
        elif self.velocity_x != 0:
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