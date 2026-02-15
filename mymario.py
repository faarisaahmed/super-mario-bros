import os
import pygame
from sprite_manager import SpriteManager
from level_loader import Level

direction = "right"

pygame.init()
pygame.mixer.init()

SCALE = 3
BASE_WIDTH, BASE_HEIGHT = 256, 240
screen_width, screen_height = BASE_WIDTH * SCALE, BASE_HEIGHT * SCALE
screen = pygame.display.set_mode((screen_width, screen_height))
clock = pygame.time.Clock()

# --- Load and play music ---
music_path = os.path.join("music", "overworld1_mario.mp3")
pygame.mixer.music.load(music_path)
pygame.mixer.music.set_volume(0.5)
pygame.mixer.music.play(-1)

sprites = SpriteManager("sprites", SCALE)

# --- Load Level ---
level = Level("levels/1-1.json", "tileset.json")

# --- Mario ---
x, y = 100, 457
current_animation = "idle"

# --- Jump physics ---
jump_max_height = 64
jump_up_frames = 30
hang_frames_default = 5
fall_frames = 18
FPS = 60

velocity_y = 0
on_ground = True
GROUND_Y = 457
jump_pressed_frames = 0
hang_frames = hang_frames_default

# Movement
horizontal_speed = 200
jump_up_velocity = -jump_max_height / (jump_up_frames / FPS) * 4
gravity_down = 4 * jump_max_height / ((fall_frames / FPS) ** 2)

# Camera
camera_x = 0

running = True
while running:
    dt = clock.tick(FPS) / 1000

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    keys = pygame.key.get_pressed()

    # --- Jump input ---
    if keys[pygame.K_z] and on_ground:
        on_ground = False
        jump_pressed_frames = 0
        velocity_y = jump_up_velocity

    # --- Horizontal movement ---
    if keys[pygame.K_RIGHT]:
        x += horizontal_speed * dt
        direction = "right"
    elif keys[pygame.K_LEFT]:
        x -= horizontal_speed * dt
        direction = "left"

    # --- Invisible wall at left edge of camera ---
    if x < camera_x:
        x = camera_x

    # --- Jump logic ---
    if not on_ground:
        if keys[pygame.K_z] and jump_pressed_frames < jump_up_frames:
            velocity_y = jump_up_velocity
            jump_pressed_frames += 1
        else:
            if hang_frames > 0:
                velocity_y = 0
                hang_frames -= 1
            else:
                velocity_y += gravity_down * dt

        y += velocity_y * dt

        if y >= GROUND_Y:
            y = GROUND_Y
            velocity_y = 0
            on_ground = True
            hang_frames = hang_frames_default

    # --- Choose animation ---
    if not on_ground:
        current_animation = "jump"
    else:
        if keys[pygame.K_RIGHT]:
            current_animation = "walk right"
        elif keys[pygame.K_LEFT]:
            current_animation = "walk left"
        else:
            if direction == "right":
                current_animation = "idle right"
            elif direction == "left":
                current_animation = "idle left"

    # --- Camera logic (only moves forward) ---
    if x - camera_x > screen_width // 2:
        camera_x = x - screen_width // 2

        level_pixel_width = level.width * level.tile_size
        if camera_x > level_pixel_width - screen_width:
            camera_x = level_pixel_width - screen_width

    # --- Draw ---
    screen.fill((92, 148, 252))  # NES sky blue

    level.draw(screen, camera_x, SCALE)
    solid_tiles = level.get_solid_tiles(SCALE)

    frame = sprites.get_frame(current_animation, dt)
    screen.blit(frame, (x - camera_x, y))

    pygame.display.flip()

pygame.quit()
