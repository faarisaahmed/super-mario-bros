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
flagpoles = [] # Stores X-coordinates (in tile units)
input_active = False
input_text = ""
last_f_press = 0  # To track double-tap for removal

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
        if os.path.exists(image_path):
            image = pygame.image.load(image_path).convert_alpha()
            tile_images[int(tile_id)] = image

# --- Load or create level ---
if os.path.exists(LEVEL_PATH):
    with open(LEVEL_PATH, "r") as f:
        data = json.load(f)
        loaded_tiles = data["tiles"] if "tiles" in data else data
        flagpoles = data.get("objects", {}).get("flagpoles", [])
    
    level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]
    for y in range(min(GRID_HEIGHT, len(loaded_tiles))):
        for x in range(min(GRID_WIDTH, len(loaded_tiles[y]))):
            level[y][x] = loaded_tiles[y][x]
else:
    level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]

# Enforce floor
for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
    for col in range(GRID_WIDTH):
        level[row][col] = FLOOR_TILE_ID

current_tile_id = FLOOR_TILE_ID
last_c_press = 0

running = True
while running:
    clock.tick(60)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        # --- Flagpole Input Handling ---
        if input_active:
            if event.type == pygame.KEYDOWN:
                # We handle the 'F' key within input_active to catch the double-tap
                if event.key == pygame.K_f:
                    now = pygame.time.get_ticks()
                    if now - last_f_press <= DOUBLE_TAP_TIME:
                        # Double tap detected: Remove nearest flagpole
                        center_tile_x = (camera_x + SCREEN_WIDTH // 2) // TILE_SIZE
                        if flagpoles:
                            closest_flag = min(flagpoles, key=lambda fx: abs(fx - center_tile_x))
                            # Only remove if it's within current screen view
                            if abs(closest_flag - center_tile_x) < (VISIBLE_TILES_X // 2):
                                flagpoles.remove(closest_flag)
                                print(f"Removed flagpole at tile {closest_flag}")
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
            if event.key == pygame.K_f:
                now = pygame.time.get_ticks()
                # If they tap F while input is NOT active (very first tap)
                input_active = True
                last_f_press = now
            
            elif event.key >= pygame.K_0 and event.key <= pygame.K_9:
                current_tile_id = int(event.unicode)

            elif event.key == pygame.K_s:
                os.makedirs("levels", exist_ok=True)
                with open(LEVEL_PATH, "w") as f:
                    json.dump({
                        "width": GRID_WIDTH,
                        "height": GRID_HEIGHT,
                        "tiles": level,
                        "objects": {"flagpoles": flagpoles}
                    }, f, indent=4)
                print("Level saved with Flagpoles")

            elif event.key == pygame.K_c:
                now = pygame.time.get_ticks()
                if now - last_c_press <= DOUBLE_TAP_TIME:
                    level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]
                    flagpoles = []
                    for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
                        for col in range(GRID_WIDTH):
                            level[row][col] = FLOOR_TILE_ID
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

    # Tiles
    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            tile_id = level[y][x]
            if tile_id in tile_images:
                draw_x = (x * TILE_SIZE) - camera_x
                if -TILE_SIZE < draw_x < SCREEN_WIDTH:
                    screen.blit(tile_images[tile_id], (draw_x, y * TILE_SIZE))

    # --- Inside the Draw section for Flagpoles ---
    for fx in flagpoles:
        # 1. Shift the X-position half a block (8px) to the right
        # (fx * TILE_SIZE) is the start of the tile, + 8 centers the 16px visual pole 
        # on the tile boundary or shifts the 32px pole half-way.
        draw_x = (fx * TILE_SIZE) - camera_x + (TILE_SIZE // 2)
        
        # 1 block above floor (GRID_HEIGHT-3)
        draw_y = (GRID_HEIGHT - 3) * TILE_SIZE - 152
        
        if -32 < draw_x < SCREEN_WIDTH:
            # 2. Cut the box in half vertically for the editor (32px -> 16px)
            # We show only the "right half" of the original footprint
            # If the full pole is 32px, showing the right 16px:
            visual_width = 16 
            
            # Draw the 16px wide rectangle
            pygame.draw.rect(screen, (0, 255, 0), (draw_x + 16, draw_y, visual_width, 152), 2)
            
            lbl = FONT.render("FLAG (R-Half)", True, (0, 255, 0))
            screen.blit(lbl, (draw_x + 16, draw_y - 20))
            
    # Grid lines
    for x in range(0, SCREEN_WIDTH + TILE_SIZE, TILE_SIZE):
        offset = camera_x % TILE_SIZE
        pygame.draw.line(screen, (60, 60, 60), (x - offset, 0), (x - offset, SCREEN_HEIGHT))
    for y in range(0, SCREEN_HEIGHT, TILE_SIZE):
        pygame.draw.line(screen, (60, 60, 60), (0, y), (SCREEN_WIDTH, y))

    # UI
    info_text = f"Selected Tile: {current_tile_id} | F: Add/Remove Flag"
    if input_active:
        info_text = f"ADD AT X: {input_text}_ (Double-F to Remove Closest)"
    
    ui_surface = FONT.render(info_text, True, (255, 255, 0) if input_active else (255, 255, 255))
    screen.blit(ui_surface, (10, 10))

    pygame.display.flip()

pygame.quit()