import os
import pygame
from sprite_manager import SpriteManager
from level_loader import Level
from mario import Mario

pygame.init()
pygame.mixer.init()

SCALE = 3
BASE_WIDTH, BASE_HEIGHT = 256, 240
screen_width, screen_height = BASE_WIDTH * SCALE, BASE_HEIGHT * SCALE
screen = pygame.display.set_mode((screen_width, screen_height))
clock = pygame.time.Clock()
FPS = 60

# music
music_path = os.path.join("music", "overworld1_mario.ogg")
pygame.mixer.music.load(music_path)
pygame.mixer.music.set_volume(0.5)
pygame.mixer.music.play(-1)

# sprites & level
sprites = SpriteManager("sprites", SCALE)
level = Level("levels/1-1.json", "tileset.json")

# mario
mario = Mario(x=100, y=0, scale=SCALE)

camera_x = 0

running = True
while running:
    # dt is the time passed since the last frame in seconds
    dt = clock.tick(FPS) / 1000

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    keys = pygame.key.get_pressed()

    mario.handle_input(keys)
    solid_tiles = level.get_solid_tiles(SCALE)
    mario.update(dt, camera_x, solid_tiles)

    # camera logic
    if mario.x - camera_x > screen_width // 2:
        camera_x = mario.x - screen_width // 2
        level_pixel_width = level.width * level.tile_size * SCALE
        if camera_x > level_pixel_width - screen_width:
            camera_x = level_pixel_width - screen_width

    # draw
    screen.fill((192, 148, 252))
    
    # --- UPDATED LINE ---
    # We pass 'dt' so the tiles can update their animation frames
    level.draw(screen, dt, camera_x, SCALE)
    
    mario.draw(screen, sprites, camera_x, dt)

    pygame.display.flip()

pygame.quit()