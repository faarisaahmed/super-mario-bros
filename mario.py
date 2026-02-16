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
        # --- Horizontal Movement ---
        self.x += self.velocity_x * dt
        mario_rect = self.rect()
        for tile in solid_tiles:
            if mario_rect.colliderect(tile):
                if self.velocity_x > 0:
                    self.x = float(tile.left - mario_rect.width)
                elif self.velocity_x < 0:
                    self.x = float(tile.right)
                mario_rect = self.rect()

        # --- Vertical Movement ---
        # 1. Apply gravity
        self.velocity_y += self.gravity * dt
        self.y += self.velocity_y * dt
        
        # 2. Assume we are in the air until proven otherwise
        self.on_ground = False 
        mario_rect = self.rect()

        for tile in solid_tiles:
            if mario_rect.colliderect(tile):
                # Falling Down (Landing)
                if self.velocity_y > 0: 
                    self.y = float(tile.top - mario_rect.height)
                    self.velocity_y = 0
                    self.on_ground = True # Confirmed on floor
                
                # Jumping Up (Hitting ceiling)
                elif self.velocity_y < 0:
                    self.y = float(tile.bottom)
                    self.velocity_y = 0
                
                mario_rect = self.rect()

        # --- Animation State Logic ---
        # We only show the jump frame if he is actually in the air 
        # AND has a significant vertical velocity (to avoid micro-flicker)
        if not self.on_ground and abs(self.velocity_y) > 50:
            self.current_animation = "jump"
        elif self.velocity_x != 0:
            self.current_animation = "walk " + self.direction
        else:
            self.current_animation = "idle " + self.direction

    def draw(self, screen, sprites, camera_x, dt):
        # We pass the calculated state to the manager
        frame = sprites.get_frame(self.current_animation, dt)
        
        diff_x = (frame.get_width() - (self.width * self.scale)) // 2
        img_height = frame.get_height()
        hitbox_bottom = self.y + (self.height * self.scale)
        
        draw_x = int(self.x - camera_x - diff_x)
        draw_y = int(hitbox_bottom - img_height) + 1 * self.scale
        
        screen.blit(frame, (draw_x, draw_y))