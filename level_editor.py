import pygame
import random
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
DOUBLE_TAP_TIME = 300 

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Level Editor - Z/X/V/B/N/M for Brushes")

clock = pygame.time.Clock()
FONT = pygame.font.SysFont(None, 24)

# --- Object & Brush Data ---
flagpoles = [] 
current_tile_id = FLOOR_TILE_ID
current_object_id = None  # When this is set, we are in "Object Mode"

input_active = False
input_text = ""
last_f_press = 0  
last_c_press = 0

# --- Camera ---
camera_x = 0

# --- Load tileset ---
tile_images = {}
try:
    with open("tileset.json", "r") as f:
        tileset = json.load(f)
    tiles = tileset["tiles"]
    for tile_id, tile_data in tiles.items():
        frames = tile_data["frames"]
        if frames:
            image_path = os.path.join("sprites", "tiles", frames[0])
            if os.path.exists(image_path):
                image = pygame.image.load(image_path).convert_alpha()
                tile_images[int(tile_id)] = image
except FileNotFoundError:
    print("Warning: tileset.json not found.")

# --- Load or create level ---
level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]

if os.path.exists(LEVEL_PATH):
    with open(LEVEL_PATH, "r") as f:
        data = json.load(f)
        loaded_tiles = data["tiles"] if isinstance(data, dict) and "tiles" in data else data
        if isinstance(data, dict):
            flagpoles = data.get("objects", {}).get("flagpoles", [])
    
    for y in range(min(GRID_HEIGHT, len(loaded_tiles))):
        for x in range(min(GRID_WIDTH, len(loaded_tiles[y]))):
            level[y][x] = loaded_tiles[y][x]
else:
    for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
        for col in range(GRID_WIDTH):
            level[row][col] = FLOOR_TILE_ID

running = True
while running:
    clock.tick(60)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        # --- Flagpole Input Handling ---
        if input_active:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f:
                    now = pygame.time.get_ticks()
                    if now - last_f_press <= DOUBLE_TAP_TIME:
                        center_tile_x = (camera_x + SCREEN_WIDTH // 2) // TILE_SIZE
                        if flagpoles:
                            closest = min(flagpoles, key=lambda obj: abs((obj[0] if isinstance(obj, list) else obj) - center_tile_x))
                            flagpoles.remove(closest)
                        input_active = False
                        input_text = ""
                        last_f_press = now
                        continue
                    last_f_press = now

                if event.key == pygame.K_RETURN:
                    if input_text.isdigit():
                        fx = int(input_text)
                        if 0 <= fx < GRID_WIDTH:
                            flagpoles.append([fx, 10])
                    input_active = False
                    input_text = ""
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                elif event.key == pygame.K_ESCAPE:
                    input_active = False
                elif event.unicode.isdigit():
                    input_text += event.unicode
            continue 

        if event.type == pygame.KEYDOWN:
            # --- ZXVBNM Mapping (Switches to Object Brush) ---
            prop_map = {
                pygame.K_z: 11, pygame.K_x: 12, 
                pygame.K_v: 13, pygame.K_b: 14,
                pygame.K_n: 11, pygame.K_m: 12
            }

            if event.key in prop_map:
                current_object_id = prop_map[event.key]
                current_tile_id = None # Disable tile brush
            
            # --- Tile Selection (Switches to Tile Brush) ---
            elif pygame.K_0 <= event.key <= pygame.K_9:
                current_tile_id = int(event.unicode)
                current_object_id = None # Disable object brush

            elif event.key == pygame.K_f:
                now = pygame.time.get_ticks()
                input_active = True
                last_f_press = now

            elif event.key == pygame.K_s:
                os.makedirs("levels", exist_ok=True)
                with open(LEVEL_PATH, "w") as f:
                    json.dump({
                        "width": GRID_WIDTH,
                        "height": GRID_HEIGHT,
                        "tiles": level,
                        "objects": {"flagpoles": flagpoles}
                    }, f, indent=4)
                print("Level saved.")

            elif event.key == pygame.K_c:
                now = pygame.time.get_ticks()
                if now - last_c_press <= DOUBLE_TAP_TIME:
                    level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]
                    flagpoles = []
                    for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
                        for col in range(GRID_WIDTH):
                            level[row][col] = FLOOR_TILE_ID
                last_c_press = now

    # --- Camera ---
    keys = pygame.key.get_pressed()
    if not input_active:
        if keys[pygame.K_RIGHT]: camera_x += 10
        if keys[pygame.K_LEFT]: camera_x -= 10
    camera_x = max(0, min(camera_x, (GRID_WIDTH * TILE_SIZE) - SCREEN_WIDTH))

    # --- Mouse Placement ---
    if not input_active:
        mouse_buttons = pygame.mouse.get_pressed()
        mouse_x, mouse_y = pygame.mouse.get_pos()
        world_x = mouse_x + camera_x
        grid_x, grid_y = world_x // TILE_SIZE, mouse_y // TILE_SIZE

        if 0 <= grid_x < GRID_WIDTH and 0 <= grid_y < GRID_HEIGHT:
            if mouse_buttons[0]: # Left Click
                if current_object_id is not None:
                    # Place Object (only once per click suggested, but this follows tile logic)
                    if not any(obj[0] == grid_x and obj[1] == current_object_id for obj in flagpoles if isinstance(obj, list)):
                        flagpoles.append([grid_x, current_object_id])
                elif current_tile_id is not None:
                    # Place Tile
                    level[grid_y][grid_x] = current_tile_id
            
            elif mouse_buttons[2]: # Right Click to Clear
                if current_object_id is not None:
                    # Remove object at this column
                    flagpoles = [obj for obj in flagpoles if (obj[0] if isinstance(obj, list) else obj) != grid_x]
                else:
                    level[grid_y][grid_x] = 0

    # --- Draw ---
    screen.fill((30, 30, 30))

    # Tiles
    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            tile_id = level[y][x]
            if tile_id in tile_images:
                draw_x = (x * TILE_SIZE) - camera_x
                if -TILE_SIZE < draw_x < SCREEN_WIDTH:
                    screen.blit(tile_images[tile_id], (draw_x, y * TILE_SIZE))

    # Flagpoles and Props
    for obj in flagpoles:
        fx, obj_id = (obj[0], obj[1]) if isinstance(obj, list) else (obj, 10)
        draw_x = (fx * TILE_SIZE) - camera_x + (TILE_SIZE // 2)
        if -64 < draw_x < SCREEN_WIDTH:
            if obj_id == 10:
                draw_y = (GRID_HEIGHT - 3) * TILE_SIZE - 152
                pygame.draw.rect(screen, (0, 255, 0), (draw_x + 16, draw_y, 16, 152), 2)
            elif obj_id in [11, 12]:
                pygame.draw.circle(screen, (0, 255, 0), (draw_x, SCREEN_HEIGHT - 40), 10, 2)
            elif obj_id in [13, 14]:
                pygame.draw.ellipse(screen, (255, 255, 255), (draw_x - 15, 40, 30, 20), 2)
            
    # Grid lines
    offset = camera_x % TILE_SIZE
    for x in range(0, SCREEN_WIDTH + TILE_SIZE, TILE_SIZE):
        pygame.draw.line(screen, (60, 60, 60), (x - offset, 0), (x - offset, SCREEN_HEIGHT))
    for y in range(0, SCREEN_HEIGHT, TILE_SIZE):
        pygame.draw.line(screen, (60, 60, 60), (0, y), (SCREEN_WIDTH, y))

    # UI
    mode = f"Object: {current_object_id}" if current_object_id else f"Tile: {current_tile_id}"
    info_text = f"Mode: {mode} | S: Save | F: Flag"
    ui_surface = FONT.render(info_text, True, (255, 255, 255))
    screen.blit(ui_surface, (10, 10))

    pygame.display.flip()

pygame.quit()