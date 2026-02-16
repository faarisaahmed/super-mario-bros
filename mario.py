import pygame
import math

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
        
        # Max Height (64 pixels)
        target_max_height = 64 * self.scale
        self.jump_force = -math.sqrt(2 * self.gravity * target_max_height)
        
        # Min Height (24 pixels) - The velocity required to reach exactly 24px
        target_min_height = 24 * self.scale
        self.min_jump_velocity = -math.sqrt(2 * self.gravity * target_min_height)

        self.terminal_velocity = 400 * self.scale 
        self.horizontal_speed = 90 * self.scale

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), 
                           int(self.width * self.scale), 
                           int(self.height * self.scale))

    def handle_input(self, keys):
        # Horizontal Movement
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
                # Start the full jump
                self.velocity_y = self.jump_force
                self.on_ground = False
                self.y -= 2 
            self.z_was_pressed = True
        else:
            # SHORT JUMP LOGIC:
            # If the button is released, and Mario is rising faster than the 24px velocity limit,
            # we instantly cap his upward speed to that limit.
            if self.velocity_y < self.min_jump_velocity:
                self.velocity_y = self.min_jump_velocity
            self.z_was_pressed = False

    def update(self, dt, camera_x, solid_tiles):
        # 1. Horizontal Movement & Collision
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

        # 2. Vertical Movement
        self.velocity_y += self.gravity * dt
        if self.velocity_y > self.terminal_velocity:
            self.velocity_y = self.terminal_velocity
        self.y += self.velocity_y * dt
        
        # 3. Collision Resolution
        mario_rect = self.rect()
        for tile in solid_tiles:
            if mario_rect.colliderect(tile):
                if self.velocity_y > 0: # Falling/Landing
                    self.y = float(tile.top - mario_rect.height)
                    self.velocity_y = 0
                elif self.velocity_y < 0: # Hitting ceiling
                    self.y = float(tile.bottom)
                    self.velocity_y = 0
                mario_rect = self.rect()

        # 4. GROUNDED CHECK
        ground_sensor = pygame.Rect(int(self.x), int(self.y + 1), 
                                   int(self.width * self.scale), 
                                   int(self.height * self.scale))
        
        self.on_ground = False
        for tile in solid_tiles:
            if ground_sensor.colliderect(tile):
                self.on_ground = True
                break

        # 5. Animation State
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