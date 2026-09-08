import json
import os
import pygame

class Level:
    def __init__(self, level_path, tileset_path):
        # 1. Load level layout data
        with open(level_path, "r") as f:
            level_data = json.load(f)

        self.width = level_data["width"]
        self.height = level_data["height"]
        
        self.grid = level_data["tiles"] if isinstance(level_data.get("tiles"), list) else level_data
        self.flagpoles = level_data.get("objects", {}).get("flagpoles", [])
        # Goomba spawn points, each stored as [grid_x, grid_y].
        self.goombas = level_data.get("objects", {}).get("goombas", [])

        # 2. Load tileset configuration
        with open(tileset_path, "r") as f:
            tileset_config = json.load(f)

        self.tile_size = tileset_config["tile_size"]
        self.tileset = tileset_config["tiles"]

        # 3. Load tile images
        self.tile_images = {}
        for tile_id, tile_data in self.tileset.items():
            frames = tile_data.get("frames", [])
            self.tile_images[int(tile_id)] = []
            for f_name in frames:
                img_path = os.path.join("sprites", "tiles", f_name)
                if os.path.exists(img_path):
                    image = pygame.image.load(img_path).convert_alpha()
                    self.tile_images[int(tile_id)].append(image)
                else:
                    print(f"Warning: Missing tile image {img_path}")

        # Tiles are blitted every frame, so the scale is done once here and
        # cached rather than per tile per frame. On the WebAssembly build the
        # old way spent more of the frame budget rescaling 3165 tiles than on
        # everything else combined.
        self._scaled = {}
        self._solid_rects = {}

        self.animation_timer = 0

    def _scaled_frames(self, tile_id, size):
        key = (tile_id, size)
        frames = self._scaled.get(key)
        if frames is None:
            frames = [pygame.transform.scale(img, (size, size))
                      for img in self.tile_images.get(tile_id, [])]
            self._scaled[key] = frames
        return frames

    def _scaled_object(self, obj_id, size):
        key = ("obj", obj_id, size)
        img = self._scaled.get(key)
        if img is None:
            img = pygame.transform.scale(self.tile_images[obj_id][0], size)
            self._scaled[key] = img
        return img

    def get_animated_frame_index(self, tile_id):
        tile_info = self.tileset.get(str(tile_id))
        durations = tile_info.get("frame_durations")
        
        if not durations:
            return 0
            
        total_frames = sum(durations)
        total_time = total_frames / 60.0
        current_time = self.animation_timer % total_time
        
        elapsed = 0
        for i, d in enumerate(durations):
            elapsed += (d / 60.0)
            if current_time < elapsed:
                return i
        return 0

    def solid_at(self, col, row):
        """Whether the tile at a grid cell is solid.

        This is what the original's collision needs: it samples individual
        pixels and asks what metatile is there, rather than intersecting
        rectangles. Anything off the grid is empty, except below the bottom,
        which stays empty so falling out of the level keeps working.
        """
        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return False
        tile_info = self.tileset.get(str(self.grid[row][col]))
        return bool(tile_info and tile_info.get("solid", False))

    def draw(self, surface, dt, camera_x=0, scale=1):
        self.animation_timer += dt

        # --- 1. Draw Standard Tiles ---
        # Only the columns the camera can actually see: 1-1 is 211 columns
        # wide and about 17 of them fit on screen.
        size = int(self.tile_size * scale)
        first_col = max(0, int(camera_x // size))
        last_col = min(self.width, int((camera_x + surface.get_width()) // size) + 2)

        # One animation lookup per tile *type* per frame, not per tile.
        frame_for = {}

        for row in range(self.height):
            grid_row = self.grid[row]
            y = row * size
            for col in range(first_col, last_col):
                tile_id = grid_row[col]
                if tile_id == 0:
                    continue
                # Skip any tile marked as an object (like ID 10-14)
                tile_info = self.tileset.get(str(tile_id))
                if tile_info is not None and tile_info.get("is_object", False):
                    continue

                frames = self._scaled_frames(tile_id, size)
                if not frames:
                    continue
                if len(frames) > 1:
                    idx = frame_for.get(tile_id)
                    if idx is None:
                        idx = frame_for[tile_id] = self.get_animated_frame_index(tile_id)
                    tile_image = frames[min(idx, len(frames) - 1)]
                else:
                    tile_image = frames[0]

                surface.blit(tile_image, (col * size - camera_x, y))

        # --- 2. Draw Objects (Flagpoles, Bushes, Clouds) ---
        for obj in self.flagpoles:
            # Handle both legacy format [x] and new format [x, id]
            if isinstance(obj, list):
                fx, obj_id = obj[0], obj[1]
            else:
                fx, obj_id = obj, 10 # Default to flagpole ID
            
            str_id = str(obj_id)
            if obj_id in self.tile_images and len(self.tile_images[obj_id]) > 0:
                # Metadata from the tileset
                info = self.tileset[str_id]
                w = info["width"] * scale
                h = info["height"] * scale
                
                scaled_img = self._scaled_object(obj_id, (int(w), int(h)))
                
                # CENTER LOGIC: (column * size) + (half tile) - (half sprite width)
                draw_x = (fx * self.tile_size * scale) - camera_x + (self.tile_size // 2 * scale) - (w // 2)
                
                # Y POSITION:
                if "cloud" in info["name"]:
                    # Clouds float high (adjust -12 as needed)
                    draw_y = (self.height - 12) * self.tile_size * scale
                elif "hill" in info["name"]:
                    # Ground level for Flagpole and Bushes (above floor tiles at height - 2)
                    draw_y = (self.height - 2) * self.tile_size * scale - h
                else:
                    draw_y = (self.height - 2) * self.tile_size * scale - h
                surface.blit(scaled_img, (draw_x, draw_y))

    def get_solid_tiles(self, scale=1):
        """Every solid tile as a Rect, in world space.

        The grid never changes once loaded, so this is built once per scale
        and handed back. It used to allocate 3165 Rects on every frame of
        every goomba update; callers treat the list as read-only.
        """
        cached = self._solid_rects.get(scale)
        if cached is not None:
            return cached

        size = int(self.tile_size * scale)
        solids = []
        for row in range(self.height):
            for col in range(self.width):
                tile_id = self.grid[row][col]
                tile_info = self.tileset.get(str(tile_id))
                if tile_info and tile_info.get("solid"):
                    solids.append(pygame.Rect(col * size, row * size, size, size))
        self._solid_rects[scale] = solids
        return solids