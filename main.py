import os
import pygame
from sprite_manager import SpriteManager
from level_loader import Level
from mario import Mario
from goomba import Goomba
import goomba as goomba_mod

pygame.init()
pygame.mixer.init()
pygame.joystick.init()

controller = None
if pygame.joystick.get_count() > 0:
    controller = pygame.joystick.Joystick(0)
    controller.init()
    print("Controller connected:", controller.get_name())

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

# sprites & level
sprites = SpriteManager("sprites", SCALE)
level = Level("levels/1-1.json", "tileset.json")


def reset():
    """Back to the start of the level: fresh Mario, goombas respawned, camera
    home and the music from the top. Bound to R so deaths are quick to retry."""
    pygame.mixer.music.play(-1)
    return (
        Mario(x=100, y=0, scale=SCALE),
        # one goomba per point placed in the editor; each heads left at start
        [Goomba(gx, gy, level.tile_size, SCALE) for gx, gy in level.goombas],
        0,
    )


mario, goombas, camera_x = reset()

# Press H to outline the boxes, so they can be eyeballed against the sprites
# without guessing. Green is the contact box (what the reference art shows);
# grey is the tile-collision box, drawn only where it differs from it.
HITBOX_COLOR = (126, 239, 72)
SOLID_BOX_COLOR = (150, 150, 150)
HITBOX_LINE = max(1, SCALE // 2)
show_hitboxes = False

running = True
while running:
    dt = clock.tick(FPS) / 1000

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_h:
                show_hitboxes = not show_hitboxes
            elif event.key == pygame.K_r:
                mario, goombas, camera_x = reset()

    keys = pygame.key.get_pressed()

    mario.handle_input(keys, controller)
    solid_tiles = level.get_solid_tiles(SCALE)
    # Mario collides the way the original does, by sampling grid cells;
    # goombas still use the rect sweep.
    mario.update(dt, camera_x, level.solid_at)

    goomba_mod.tick_interval_timers(dt)
    for goomba in goombas:
        goomba.update(dt, solid_tiles, camera_x, screen_width)

    # Coming down on an enemy's contact box stomps it; touching it any other
    # way is fatal.
    if not mario.dying:
        mario_box = mario.rect()
        for goomba in goombas:
            if not goomba.is_dangerous():
                continue
            if not mario_box.colliderect(goomba.hitbox()):
                continue
            if mario.is_descending():
                goomba.squash()
                mario.stomp()
            else:
                mario.die()
            break

    # camera logic
    if mario.x - camera_x > screen_width // 2:
        camera_x = mario.x - screen_width // 2
        level_pixel_width = level.width * level.tile_size * SCALE
        if camera_x > level_pixel_width - screen_width:
            camera_x = level_pixel_width - screen_width

    # draw
    screen.fill((92, 148, 252))
    
    level.draw(screen, dt, camera_x, SCALE)
    for goomba in goombas:
        if goomba.alive:
            goomba.draw(screen, camera_x)
    mario.draw(screen, sprites, camera_x, dt)

    if show_hitboxes:
        # Boxes are in world space; shift them by the camera to get screen space.
        # a squashed goomba can't hurt anyone, so it gets no contact box
        threats = [g for g in goombas if g.is_dangerous()]
        for box in [g.rect() for g in goombas if g.alive]:
            pygame.draw.rect(screen, SOLID_BOX_COLOR,
                             box.move(-camera_x, 0), HITBOX_LINE)
        for box in [mario.rect()] + [g.hitbox() for g in threats]:
            pygame.draw.rect(screen, HITBOX_COLOR,
                             box.move(-camera_x, 0), HITBOX_LINE)

    pygame.display.flip()

pygame.quit()