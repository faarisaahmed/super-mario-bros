import pygame
import json
import os

pygame.init()

# --- World / grid constants ---
TILE_SIZE = 16
GRID_WIDTH = 211
GRID_HEIGHT = 15
FLOOR_TILE_ID = 4
LEVEL_PATH = os.path.join("levels", "1-1.json")
DOUBLE_TAP_TIME = 300

# --- View: the play area is drawn at 2x so tiles are legible ---
ZOOM = 2
VIEW_W = 960                       # play-area width in screen px
PLAY_H = GRID_HEIGHT * TILE_SIZE * ZOOM   # 480 — shows the full level height
PANEL_H = 150                      # bottom toolbar
SCREEN_WIDTH = VIEW_W
SCREEN_HEIGHT = PLAY_H + PANEL_H

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Level Editor")
clock = pygame.time.Clock()

FONT_BIG = pygame.font.SysFont("menlo,consolas,monospace", 22, bold=True)
FONT = pygame.font.SysFont("menlo,consolas,monospace", 15)
FONT_SMALL = pygame.font.SysFont("menlo,consolas,monospace", 12, bold=True)

# --- Colours ---
SKY = (99, 148, 240)
PANEL_BG = (22, 24, 32)
PANEL_LINE = (48, 52, 68)
SWATCH_BG = (40, 44, 58)
SELECT = (255, 208, 0)
TEXT = (236, 238, 245)
MUTED = (150, 156, 174)
GRID_COL = (255, 255, 255)
GROUND_COL = (255, 236, 140)

# --- Brush state (kept as three vars so placement logic stays simple) ---
current_tile_id = FLOOR_TILE_ID
current_object_id = None
goomba_mode = False

# --- Level data ---
flagpoles = []
goombas = []

camera_x = 0            # leftmost visible WORLD pixel (unscaled)
input_active = False
input_text = ""
last_f_press = 0
last_c_press = 0
toast = ""
toast_until = 0

# --- Load tileset + images ---
tileset = {}
tiles = {}
tile_images = {}       # native-resolution surfaces, keyed by int id
try:
    with open("tileset.json", "r") as f:
        tileset = json.load(f)
    tiles = tileset["tiles"]
    for tid, tdata in tiles.items():
        frames = tdata.get("frames", [])
        if frames:
            path = os.path.join("sprites", "tiles", frames[0])
            if os.path.exists(path):
                tile_images[int(tid)] = pygame.image.load(path).convert_alpha()
except FileNotFoundError:
    print("Warning: tileset.json not found.")

goomba_img = None
_gpath = os.path.join("sprites", "enemies", "goomba", "goomba1.png")
if os.path.exists(_gpath):
    goomba_img = pygame.image.load(_gpath).convert_alpha()

# Scaled caches so we don't rescale every frame.
_scaled_tiles = {}
def scaled_tile(tid):
    if tid not in _scaled_tiles and tid in tile_images:
        s = TILE_SIZE * ZOOM
        _scaled_tiles[tid] = pygame.transform.scale(tile_images[tid], (s, s))
    return _scaled_tiles.get(tid)

_scaled_objs = {}
def scaled_object(obj_id):
    if obj_id not in _scaled_objs and obj_id in tile_images and str(obj_id) in tiles:
        info = tiles[str(obj_id)]
        w = int(info.get("width", 16) * ZOOM)
        h = int(info.get("height", 16) * ZOOM)
        _scaled_objs[obj_id] = pygame.transform.scale(tile_images[obj_id], (w, h))
    return _scaled_objs.get(obj_id)

def fit_icon(surface, box):
    """Scale a surface to fit inside a box, preserving aspect ratio."""
    w, h = surface.get_size()
    s = min(box / w, box / h)
    return pygame.transform.scale(surface, (max(1, int(w * s)), max(1, int(h * s))))

# --- Load or create the level ---
level = [[0 for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]
if os.path.exists(LEVEL_PATH):
    with open(LEVEL_PATH, "r") as f:
        data = json.load(f)
    loaded = data["tiles"] if isinstance(data, dict) and "tiles" in data else data
    if isinstance(data, dict):
        flagpoles = data.get("objects", {}).get("flagpoles", [])
        goombas = data.get("objects", {}).get("goombas", [])
    for y in range(min(GRID_HEIGHT, len(loaded))):
        for x in range(min(GRID_WIDTH, len(loaded[y]))):
            level[y][x] = loaded[y][x]
else:
    for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
        for col in range(GRID_WIDTH):
            level[row][col] = FLOOR_TILE_ID


# --- Palette definition (order shown in the toolbar) ---
# Each entry: (type, id, key-hint, short label)
PALETTE = [
    ("tile", 1, "1", "brick"),
    ("tile", 2, "2", "used"),
    ("tile", 3, "3", "?block"),
    ("tile", 4, "4", "floor"),
    ("tile", 5, "5", "block"),
    ("tile", 6, "6", "pipeTL"),
    ("tile", 7, "7", "pipeTR"),
    ("tile", 8, "8", "pipeL"),
    ("tile", 9, "9", "pipeR"),
    ("tile", 0, "0", "eraser"),
    ("object", 11, "Z", "bushS"),
    ("object", 12, "X", "bushL"),
    ("object", 13, "V", "cloudS"),
    ("object", 14, "B", "cloudL"),
    ("object", 15, "K", "hillS"),
    ("object", 16, "L", "hillL"),
    ("object", 10, "F", "flag"),
    ("goomba", None, "G", "goomba"),
]

SWATCH = 40
SW_GAP = 6
SW_X0 = 14
SW_Y = PLAY_H + 44


def swatch_rect(i):
    return pygame.Rect(SW_X0 + i * (SWATCH + SW_GAP), SW_Y, SWATCH, SWATCH)


def brush_name():
    if goomba_mode:
        return "Goomba"
    if current_object_id is not None:
        return tiles.get(str(current_object_id), {}).get("name", "object")
    if current_tile_id == 0:
        return "Eraser"
    return tiles.get(str(current_tile_id), {}).get("name", "tile")


def is_selected(kind, oid):
    if goomba_mode:
        return kind == "goomba"
    if kind == "tile":
        return current_object_id is None and current_tile_id == oid
    if kind == "object":
        return current_object_id == oid
    return False


def select_brush(kind, oid):
    global current_tile_id, current_object_id, goomba_mode
    current_tile_id = None
    current_object_id = None
    goomba_mode = False
    if kind == "tile":
        current_tile_id = oid
    elif kind == "object":
        current_object_id = oid
    elif kind == "goomba":
        goomba_mode = True


def brush_icon(kind, oid, box=SWATCH - 8):
    if kind == "goomba" and goomba_img:
        return fit_icon(goomba_img, box)
    if kind == "tile" and oid == 0:
        return None  # eraser: drawn as an outline
    if oid in tile_images:
        return fit_icon(tile_images[oid], box)
    return None


def notify(msg):
    global toast, toast_until
    toast = msg
    toast_until = pygame.time.get_ticks() + 1500


# --- World <-> screen helpers ---
def screen_to_grid(mx, my):
    wx = mx / ZOOM + camera_x
    wy = my / ZOOM
    return int(wx // TILE_SIZE), int(wy // TILE_SIZE)


def world_to_screen_x(wx):
    return int((wx - camera_x) * ZOOM)


def draw_object(fx, obj_id):
    img = scaled_object(obj_id)
    info = tiles.get(str(obj_id))
    if img is None or info is None:
        return
    w, h = img.get_size()
    center_world = fx * TILE_SIZE + TILE_SIZE // 2
    dx = world_to_screen_x(center_world) - w // 2
    if "cloud" in info["name"]:
        dy = (GRID_HEIGHT - 12) * TILE_SIZE * ZOOM
    else:
        dy = (GRID_HEIGHT - 2) * TILE_SIZE * ZOOM - h
    screen.blit(img, (dx, dy))


running = True
while running:
    clock.tick(60)
    now = pygame.time.get_ticks()
    mouse_x, mouse_y = pygame.mouse.get_pos()
    in_play = mouse_y < PLAY_H

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        # --- Flag column input overlay ---
        if input_active:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_f:
                    if now - last_f_press <= DOUBLE_TAP_TIME:
                        center_tile = (camera_x + (VIEW_W / ZOOM) / 2) // TILE_SIZE
                        if flagpoles:
                            closest = min(flagpoles, key=lambda o: abs(
                                (o[0] if isinstance(o, list) else o) - center_tile))
                            flagpoles.remove(closest)
                            notify("Flag removed")
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
                            notify(f"Flag placed at column {fx}")
                    input_active = False
                    input_text = ""
                elif event.key == pygame.K_BACKSPACE:
                    input_text = input_text[:-1]
                elif event.key == pygame.K_ESCAPE:
                    input_active = False
                    input_text = ""
                elif event.unicode.isdigit():
                    input_text += event.unicode
            continue

        if event.type == pygame.KEYDOWN:
            prop_map = {
                pygame.K_z: 11, pygame.K_x: 12,
                pygame.K_v: 13, pygame.K_b: 14,
                pygame.K_n: 11, pygame.K_m: 12,
                pygame.K_k: 15, pygame.K_l: 16,
            }
            if event.key in prop_map:
                select_brush("object", prop_map[event.key])
            elif event.key == pygame.K_g:
                select_brush("goomba", None)
            elif pygame.K_0 <= event.key <= pygame.K_9:
                select_brush("tile", int(event.unicode))
            elif event.key == pygame.K_f:
                input_active = True
                input_text = ""
                last_f_press = now
            elif event.key == pygame.K_s:
                os.makedirs("levels", exist_ok=True)
                with open(LEVEL_PATH, "w") as f:
                    json.dump({
                        "width": GRID_WIDTH,
                        "height": GRID_HEIGHT,
                        "tiles": level,
                        "objects": {"flagpoles": flagpoles, "goombas": goombas},
                    }, f, indent=4)
                notify("Level saved")
                print("Level saved.")
            elif event.key == pygame.K_c:
                if now - last_c_press <= DOUBLE_TAP_TIME:
                    level = [[0] * GRID_WIDTH for _ in range(GRID_HEIGHT)]
                    flagpoles = []
                    goombas = []
                    for row in range(GRID_HEIGHT - 2, GRID_HEIGHT):
                        for col in range(GRID_WIDTH):
                            level[row][col] = FLOOR_TILE_ID
                    notify("Level cleared")
                last_c_press = now

        # --- Palette clicks (in the bottom panel) ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not in_play:
            for i, (kind, oid, _key, _label) in enumerate(PALETTE):
                if swatch_rect(i).collidepoint(mouse_x, mouse_y):
                    select_brush(kind, oid)
                    break

    # --- Camera scroll ---
    keys = pygame.key.get_pressed()
    if not input_active:
        if keys[pygame.K_RIGHT]:
            camera_x += 8
        if keys[pygame.K_LEFT]:
            camera_x -= 8
    max_cam = GRID_WIDTH * TILE_SIZE - VIEW_W / ZOOM
    camera_x = max(0, min(camera_x, max_cam))

    # --- Painting in the play area ---
    hover_grid = None
    if in_play and not input_active:
        gx, gy = screen_to_grid(mouse_x, mouse_y)
        if 0 <= gx < GRID_WIDTH and 0 <= gy < GRID_HEIGHT:
            hover_grid = (gx, gy)
            buttons = pygame.mouse.get_pressed()
            if buttons[0]:      # left click = place
                if goomba_mode:
                    if [gx, gy] not in goombas:
                        goombas.append([gx, gy])
                elif current_object_id is not None:
                    if not any(isinstance(o, list) and o[0] == gx and o[1] == current_object_id
                               for o in flagpoles):
                        flagpoles.append([gx, current_object_id])
                elif current_tile_id is not None:
                    level[gy][gx] = current_tile_id
            elif buttons[2]:    # right click = erase
                # A goomba under the cursor is always removable, whatever the
                # current brush — so you never get stuck unable to delete one.
                if any(g[0] == gx and g[1] == gy for g in goombas):
                    goombas = [g for g in goombas if not (g[0] == gx and g[1] == gy)]
                elif goomba_mode:
                    pass  # goomba brush and nothing here to erase
                elif current_object_id is not None:
                    flagpoles = [o for o in flagpoles
                                 if (o[0] if isinstance(o, list) else o) != gx]
                else:
                    level[gy][gx] = 0

    # ============================ DRAW ============================
    screen.fill(SKY, (0, 0, VIEW_W, PLAY_H))

    ts = TILE_SIZE * ZOOM
    first_col = int(camera_x // TILE_SIZE)
    last_col = int((camera_x + VIEW_W / ZOOM) // TILE_SIZE) + 1

    # Tiles
    for y in range(GRID_HEIGHT):
        for x in range(max(0, first_col), min(GRID_WIDTH, last_col)):
            tid = level[y][x]
            if tid == 0:
                continue
            info = tiles.get(str(tid))
            if info and info.get("is_object"):
                continue  # objects are drawn separately
            img = scaled_tile(tid)
            if img:
                screen.blit(img, (world_to_screen_x(x * TILE_SIZE), y * ts))

    # Objects (flag, bushes, clouds, hills) using their real sprites
    for obj in flagpoles:
        fx, oid = (obj[0], obj[1]) if isinstance(obj, list) else (obj, 10)
        draw_object(fx, oid)

    # Goombas
    if goomba_img:
        gimg = pygame.transform.scale(goomba_img, (ts, ts))
        for gx, gy in goombas:
            screen.blit(gimg, (world_to_screen_x(gx * TILE_SIZE), gy * ts))

    # Grid lines (subtle) + ground reference line
    grid_surf = pygame.Surface((VIEW_W, PLAY_H), pygame.SRCALPHA)
    offset = int((camera_x % TILE_SIZE) * ZOOM)
    for sx in range(-offset, VIEW_W, ts):
        pygame.draw.line(grid_surf, (*GRID_COL, 28), (sx, 0), (sx, PLAY_H))
    for row in range(GRID_HEIGHT + 1):
        pygame.draw.line(grid_surf, (*GRID_COL, 28), (0, row * ts), (VIEW_W, row * ts))
    pygame.draw.line(grid_surf, (*GROUND_COL, 120),
                     (0, (GRID_HEIGHT - 2) * ts), (VIEW_W, (GRID_HEIGHT - 2) * ts), 2)
    screen.blit(grid_surf, (0, 0))

    # Hover cell + ghost preview
    if hover_grid:
        gx, gy = hover_grid
        cell = pygame.Rect(world_to_screen_x(gx * TILE_SIZE), gy * ts, ts, ts)
        if goomba_mode and goomba_img:
            ghost = pygame.transform.scale(goomba_img, (ts, ts)).copy()
            ghost.set_alpha(140)
            screen.blit(ghost, cell.topleft)
        elif current_tile_id not in (None, 0) and scaled_tile(current_tile_id):
            ghost = scaled_tile(current_tile_id).copy()
            ghost.set_alpha(140)
            screen.blit(ghost, cell.topleft)
        elif current_tile_id == 0:
            pygame.draw.line(screen, (255, 80, 80), cell.topleft, cell.bottomright, 2)
            pygame.draw.line(screen, (255, 80, 80), cell.topright, cell.bottomleft, 2)
        pygame.draw.rect(screen, SELECT, cell, 2)

    # ---------------------------- PANEL ----------------------------
    screen.fill(PANEL_BG, (0, PLAY_H, VIEW_W, PANEL_H))
    pygame.draw.line(screen, PANEL_LINE, (0, PLAY_H), (VIEW_W, PLAY_H), 2)

    # Current-brush heading
    screen.blit(FONT_BIG.render(f"Brush: {brush_name()}", True, SELECT), (16, PLAY_H + 12))

    # Right-aligned save toast
    if toast and now < toast_until:
        t = FONT.render(toast, True, (120, 230, 140))
        screen.blit(t, (VIEW_W - t.get_width() - 16, PLAY_H + 15))

    # Palette swatches
    for i, (kind, oid, key, label) in enumerate(PALETTE):
        r = swatch_rect(i)
        sel = is_selected(kind, oid)
        pygame.draw.rect(screen, SWATCH_BG, r, border_radius=4)
        icon = brush_icon(kind, oid)
        if icon:
            screen.blit(icon, (r.centerx - icon.get_width() // 2,
                               r.centery - icon.get_height() // 2))
        elif kind == "tile" and oid == 0:
            pygame.draw.line(screen, (255, 90, 90), (r.left + 8, r.top + 8),
                             (r.right - 8, r.bottom - 8), 3)
            pygame.draw.line(screen, (255, 90, 90), (r.right - 8, r.top + 8),
                             (r.left + 8, r.bottom - 8), 3)
        pygame.draw.rect(screen, SELECT if sel else PANEL_LINE, r, 3 if sel else 1,
                         border_radius=4)
        # key badge in the top-left corner
        badge = pygame.Rect(r.left, r.top, 15, 15)
        pygame.draw.rect(screen, (0, 0, 0), badge, border_radius=3)
        pygame.draw.rect(screen, SELECT if sel else PANEL_LINE, badge, 1, border_radius=3)
        k = FONT_SMALL.render(key, True, SELECT if sel else TEXT)
        screen.blit(k, (badge.centerx - k.get_width() // 2,
                        badge.centery - k.get_height() // 2))
        # name below
        n = FONT_SMALL.render(label, True, TEXT if sel else MUTED)
        screen.blit(n, (r.centerx - n.get_width() // 2, r.bottom + 4))

    # Bottom help line
    help_text = ("L-click place  ·  R-click erase  ·  arrows scroll  ·  "
                 "S save  ·  CC clear  ·  F flag-by-column")
    screen.blit(FONT.render(help_text, True, MUTED), (16, PLAY_H + PANEL_H - 24))

    # Flag input overlay
    if input_active:
        box = pygame.Rect(VIEW_W // 2 - 170, PLAY_H // 2 - 40, 340, 80)
        pygame.draw.rect(screen, (0, 0, 0), box)
        pygame.draw.rect(screen, SELECT, box, 2)
        screen.blit(FONT.render("Flag column (Enter to place, Esc to cancel):",
                                True, TEXT), (box.x + 14, box.y + 12))
        screen.blit(FONT_BIG.render(input_text + "_", True, SELECT),
                    (box.x + 14, box.y + 40))

    pygame.display.flip()

pygame.quit()
