import pygame
import json
import os

pygame.init()

# --- Constants ---
TILE_SIZE = 16
GRID_WIDTH = 211
GRID_HEIGHT = 15

VISIBLE_TILES_X = 60
SCREEN_WIDTH = VISIBLE_TILES_X * TILE_SIZE
SCREEN_HEIGHT = GRID_HEIGHT * TILE_SIZE

LEVEL_PATH = os.path.join("levels", "1-1.json")

FLOOR_TILE_ID = 4
DOUBLE_TAP_TIME = 300  # ms

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Level Editor")

clock = pygame.time.Clock()
FONT = pygame.font.SysFont(None, 20)

# --- Camera ---
camera_x = 0

# --- Load tileset ---
with open("tileset.json", "r") as f:
    tileset = json.load(f)

tiles = tileset["tiles"]

tile_images = {}
for tile_id, tile_data in tiles.items():
    frames = tile_data["frames"]
    if frames:
        image_path = os.path.join("sprites", "tiles", frames[0])
        image = pygame.image.load(image_path).convert_alpha()
        tile_images[int(tile_id)] = image

# --- Load or create level ---
if os.path.exists(LEVEL_PATH):
    with open(LEVEL_PATH, "r") as f:
        level_data = json.load(f)
        loaded_level = level_data["tiles"]

    level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]

    for y in range(min(GRID_HEIGHT, len(loaded_level))):
        for x in range(min(GRID_WIDTH, len(loaded_level[y]))):
            level[y][x] = loaded_level[y][x]

else:
    level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]

# Always enforce 2 bottom floor rows
for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
    for col in range(GRID_WIDTH):
        level[row][col] = FLOOR_TILE_ID

current_tile_id = FLOOR_TILE_ID
last_c_press = 0

# --- Main Loop ---
running = True
while running:
    clock.tick(60)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:

            # Tile selection
            if event.key == pygame.K_0:
                current_tile_id = 0
            elif event.key == pygame.K_1:
                current_tile_id = 1
            elif event.key == pygame.K_2:
                current_tile_id = 2
            elif event.key == pygame.K_3:
                current_tile_id = 3
            elif event.key == pygame.K_4:
                current_tile_id = 4
            elif event.key == pygame.K_5:
                current_tile_id = 5
            elif event.key == pygame.K_6:
                current_tile_id = 6
            elif event.key == pygame.K_7:
                current_tile_id = 7
            elif event.key == pygame.K_8:
                current_tile_id = 8
            elif event.key == pygame.K_9:
                current_tile_id = 9

            # Save
            elif event.key == pygame.K_s:
                os.makedirs("levels", exist_ok=True)
                with open(LEVEL_PATH, "w") as f:
                    json.dump(
                        {
                            "width": GRID_WIDTH,
                            "height": GRID_HEIGHT,
                            "tiles": level
                        },
                        f,
                        indent=4
                    )
                print("Level saved")

            # Double-tap C to clear level (keep floor)
            elif event.key == pygame.K_c:
                now = pygame.time.get_ticks()

                if now - last_c_press <= DOUBLE_TAP_TIME:
                    level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]

                    for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
                        for col in range(GRID_WIDTH):
                            level[row][col] = FLOOR_TILE_ID

                    print("Level cleared (floor preserved)")

                last_c_press = now

    # --- Camera movement ---
    keys = pygame.key.get_pressed()
    if keys[pygame.K_RIGHT]:
        camera_x += 10
    if keys[pygame.K_LEFT]:
        camera_x -= 10

    max_camera = (GRID_WIDTH * TILE_SIZE) - SCREEN_WIDTH
    camera_x = max(0, min(camera_x, max_camera))

    # --- Mouse placement ---
    mouse_buttons = pygame.mouse.get_pressed()
    mouse_x, mouse_y = pygame.mouse.get_pos()

    world_x = mouse_x + camera_x
    grid_x = world_x // TILE_SIZE
    grid_y = mouse_y // TILE_SIZE

    if 0 <= grid_x < GRID_WIDTH and 0 <= grid_y < GRID_HEIGHT:
        if mouse_buttons[0]:
            level[grid_y][grid_x] = current_tile_id
        elif mouse_buttons[2]:
            level[grid_y][grid_x] = 0

    # --- Draw ---
    screen.fill((30, 30, 30))

    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            tile_id = level[y][x]
            if tile_id in tile_images:
                draw_x = (x * TILE_SIZE) - camera_x
                if -TILE_SIZE < draw_x < SCREEN_WIDTH:
                    screen.blit(tile_images[tile_id], (draw_x, y * TILE_SIZE))

    # Grid lines
    for x in range(GRID_WIDTH):
        draw_x = (x * TILE_SIZE) - camera_x
        if -TILE_SIZE < draw_x < SCREEN_WIDTH:
            pygame.draw.line(screen, (60, 60, 60),
                             (draw_x, 0), (draw_x, SCREEN_HEIGHT))

    for y in range(GRID_HEIGHT):
        pygame.draw.line(screen, (60, 60, 60),
                         (0, y * TILE_SIZE),
                         (SCREEN_WIDTH, y * TILE_SIZE))

    # UI
    text = FONT.render(f"Selected Tile: {current_tile_id}", True, (255, 255, 255))
    screen.blit(text, (5, 5))

    pygame.display.flip()

pygame.quit()
