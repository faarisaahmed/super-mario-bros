import pygame
import math
import os

# --- 1. INITIALIZE MIXER AND LOAD SOUND ---
pygame.mixer.init()
# Increasing channels prevents sounds from cutting each other off
pygame.mixer.set_num_channels(16)

jump_sound = pygame.mixer.Sound(os.path.join("sfx", "jump_effect.mp3"))

# --- VOLUME CONTROL ---
# 0.0 is silent, 1.0 is full blast. 0.2 is usually the "sweet spot" for SFX.
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

        # Physics
        self.velocity_x = 0
        self.velocity_y = 0
        self.on_ground = False
        self.z_was_pressed = False 

        # --- TUNING ---
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

    def handle_input(self, keys):
        self.velocity_x = 0
        if keys[pygame.K_RIGHT]:
            self.velocity_x = self.horizontal_speed
            self.direction = "right"
        elif keys[pygame.K_LEFT]:
            self.velocity_x = -self.horizontal_speed
            self.direction = "left"

        # Jump Input
        if keys[pygame.K_z]:
            if not self.z_was_pressed and self.on_ground:
                self.velocity_y = self.jump_force
                self.on_ground = False
                self.y -= 2 
                
                # Triggers the quieter sound
                jump_sound.play()
                
            self.z_was_pressed = True
        else:
            if self.velocity_y < self.min_jump_velocity:
                self.velocity_y = self.min_jump_velocity
            self.z_was_pressed = False

    def update(self, dt, camera_x, solid_tiles):
        # Horizontal Movement & Collision
        self.x += self.velocity_x * dt
        mario_rect = self.rect()
        for tile in solid_tiles:
            if mario_rect.colliderect(tile):
                if self.velocity_x > 0:
                    self.x = float(tile.left - mario_rect.width)
                elif self.velocity_x < 0:
                    self.x = float(tile.right)
                self.velocity_x = 0
                mario_rect = self.rect()

        # Vertical Movement
        self.velocity_y += self.gravity * dt
        if self.velocity_y > self.terminal_velocity:
            self.velocity_y = self.terminal_velocity
        self.y += self.velocity_y * dt
        
        # Collision Resolution
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

        # GROUNDED CHECK
        ground_sensor = pygame.Rect(int(self.x), int(self.y + 1), 
                                   int(self.width * self.scale), 
                                   int(self.height * self.scale))
        
        self.on_ground = False
        for tile in solid_tiles:
            if ground_sensor.colliderect(tile):
                self.on_ground = True
                break

        # Animation State
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