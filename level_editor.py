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
DOUBLE_TAP_TIME = 300 

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Level Editor - Press F to add Flagpole, Double-F to remove")

clock = pygame.time.Clock()
FONT = pygame.font.SysFont(None, 24)

# --- Flagpole Object Data ---
flagpoles = [] 
input_active = False
input_text = ""
last_f_press = 0  
last_c_press = 0

# --- Camera ---
camera_x = 0

# --- Load tileset ---
# (Assumes tileset.json and sprites/tiles/ exist as per your original setup)
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
        # Handle both old list-style and new dict-style saves
        loaded_tiles = data["tiles"] if isinstance(data, dict) and "tiles" in data else data
        if isinstance(data, dict):
            flagpoles = data.get("objects", {}).get("flagpoles", [])
    
    # Fill existing level data
    for y in range(min(GRID_HEIGHT, len(loaded_tiles))):
        for x in range(min(GRID_WIDTH, len(loaded_tiles[y]))):
            level[y][x] = loaded_tiles[y][x]
else:
    # FIRST TIME RUN: Generate default floor
    for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
        for col in range(GRID_WIDTH):
            level[row][col] = FLOOR_TILE_ID

current_tile_id = FLOOR_TILE_ID

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
                        # Double tap: Remove nearest
                        center_tile_x = (camera_x + SCREEN_WIDTH // 2) // TILE_SIZE
                        if flagpoles:
                            closest_flag = min(flagpoles, key=lambda fx: abs(fx - center_tile_x))
                            if abs(closest_flag - center_tile_x) < (VISIBLE_TILES_X // 2):
                                flagpoles.remove(closest_flag)
                        input_active = False
                        input_text = ""
                        last_f_press = now
                        continue
                    last_f_press = now

                if event.key == pygame.K_RETURN:
                    if input_text.isdigit():
                        fx = int(input_text)
                        if 0 <= fx < GRID_WIDTH:
                            if fx not in flagpoles: flagpoles.append(fx)
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
            # Add Flagpole toggle
            if event.key == pygame.K_f:
                now = pygame.time.get_ticks()
                input_active = True
                last_f_press = now
            
            # Select Tile
            elif pygame.K_0 <= event.key <= pygame.K_9:
                current_tile_id = int(event.unicode)

            # Save Level
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

            # CLEAR LEVEL (Adds floor back)
            elif event.key == pygame.K_c:
                now = pygame.time.get_ticks()
                if now - last_c_press <= DOUBLE_TAP_TIME:
                    level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]
                    flagpoles = []
                    # Re-add floor on clear
                    for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
                        for col in range(GRID_WIDTH):
                            level[row][col] = FLOOR_TILE_ID
                    print("Level cleared to default floor.")
                last_c_press = now

    # --- Camera movement ---
    keys = pygame.key.get_pressed()
    if not input_active:
        if keys[pygame.K_RIGHT]: camera_x += 10
        if keys[pygame.K_LEFT]: camera_x -= 10
    camera_x = max(0, min(camera_x, (GRID_WIDTH * TILE_SIZE) - SCREEN_WIDTH))

    # --- Mouse placement ---
    if not input_active:
        mouse_buttons = pygame.mouse.get_pressed()
        mouse_x, mouse_y = pygame.mouse.get_pos()
        world_x = mouse_x + camera_x
        grid_x, grid_y = world_x // TILE_SIZE, mouse_y // TILE_SIZE

        if 0 <= grid_x < GRID_WIDTH and 0 <= grid_y < GRID_HEIGHT:
            if mouse_buttons[0]: level[grid_y][grid_x] = current_tile_id
            elif mouse_buttons[2]: level[grid_y][grid_x] = 0

    # --- Draw ---
    screen.fill((30, 30, 30))

    # Draw Tiles
    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            tile_id = level[y][x]
            if tile_id in tile_images:
                draw_x = (x * TILE_SIZE) - camera_x
                if -TILE_SIZE < draw_x < SCREEN_WIDTH:
                    screen.blit(tile_images[tile_id], (draw_x, y * TILE_SIZE))

    # Draw Flagpoles
    for fx in flagpoles:
        draw_x = (fx * TILE_SIZE) - camera_x + (TILE_SIZE // 2)
        draw_y = (GRID_HEIGHT - 3) * TILE_SIZE - 152
        if -32 < draw_x < SCREEN_WIDTH:
            pygame.draw.rect(screen, (0, 255, 0), (draw_x + 16, draw_y, 16, 152), 2)
            lbl = FONT.render("FLAG", True, (0, 255, 0))
            screen.blit(lbl, (draw_x + 16, draw_y - 20))
            
    # Grid lines
    offset = camera_x % TILE_SIZE
    for x in range(0, SCREEN_WIDTH + TILE_SIZE, TILE_SIZE):
        pygame.draw.line(screen, (60, 60, 60), (x - offset, 0), (x - offset, SCREEN_HEIGHT))
    for y in range(0, SCREEN_HEIGHT, TILE_SIZE):
        pygame.draw.line(screen, (60, 60, 60), (0, y), (SCREEN_WIDTH, y))

    # UI
    info_text = f"Tile: {current_tile_id} | S: Save | Double-C: Clear | F: Flag"
    if input_active:
        info_text = f"ADD FLAG AT X: {input_text}_"
    
    ui_surface = FONT.render(info_text, True, (255, 255, 0) if input_active else (255, 255, 255))
    screen.blit(ui_surface, (10, 10))

    pygame.display.flip()

pygame.quit()