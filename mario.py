import pygame

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

        # Movement tuning
        self.horizontal_speed = 200
        self.jump_force = -600
        self.gravity = 2000

    def rect(self):
        # Convert to int for Pygame's Rect to handle pixel collisions
        return pygame.Rect(int(self.x), int(self.y), 
                           self.width * self.scale, 
                           self.height * self.scale)

    def handle_input(self, keys):
        self.velocity_x = 0
        if keys[pygame.K_RIGHT]:
            self.velocity_x = self.horizontal_speed
            self.direction = "right"
        elif keys[pygame.K_LEFT]:
            self.velocity_x = -self.horizontal_speed
            self.direction = "left"

        if keys[pygame.K_z] and self.on_ground:
            self.velocity_y = self.jump_force
            self.on_ground = False

    def update(self, dt, camera_x, solid_tiles):
        # --- 1. Horizontal Movement ---
        self.x += self.velocity_x * dt
        mario_rect = self.rect()
        for tile in solid_tiles:
            if mario_rect.colliderect(tile):
                if self.velocity_x > 0:
                    self.x = float(tile.left - mario_rect.width)
                elif self.velocity_x < 0:
                    self.x = float(tile.right)
                self.velocity_x = 0 # Kill velocity on wall hit
                mario_rect = self.rect()

        # --- 2. Vertical Movement ---
        # Apply gravity
        self.velocity_y += self.gravity * dt
        self.y += self.velocity_y * dt
        
        # Reset on_ground and check collisions
        self.on_ground = False 
        mario_rect = self.rect()

        for tile in solid_tiles:
            if mario_rect.colliderect(tile):
                if self.velocity_y > 0: # Landing / Falling onto floor
                    self.y = float(tile.top - mario_rect.height)
                    self.velocity_y = 0
                    self.on_ground = True 
                elif self.velocity_y < 0: # Hitting ceiling
                    self.y = float(tile.bottom)
                    self.velocity_y = 0
                mario_rect = self.rect()

        # --- 3. Jitter-Free Animation State Logic ---
        # We only use 'jump' if he is NOT on the ground 
        # AND his velocity is substantial (prevents flicker from gravity math)
        if not self.on_ground and abs(self.velocity_y) > 50:
            self.current_animation = f"jump {self.direction}"
        elif self.velocity_x != 0:
            self.current_animation = f"walk {self.direction}"
        else:
            self.current_animation = f"idle {self.direction}"

    def draw(self, screen, sprites, camera_x, dt):
        frame = sprites.get_frame(self.current_animation, dt)
        
        # Centering logic
        diff_x = (frame.get_width() - (self.width * self.scale)) // 2
        img_height = frame.get_height()
        hitbox_bottom = self.y + (self.height * self.scale)
        
        # Draw at exact integer positions to prevent pixel-bleeding jitter
        draw_x = int(self.x - camera_x - diff_x)
        draw_y = int(hitbox_bottom - img_height)
        
        screen.blit(frame, (draw_x, draw_y))