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

        self.animation_timer = 0

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

    def draw(self, surface, dt, camera_x=0, scale=1):
        self.animation_timer += dt

        # --- 1. Draw Standard Tiles ---
        for row in range(self.height):
            for col in range(self.width):
                tile_id = self.grid[row][col]
                # Skip air (0) and any tile marked as an object (like ID 10-14)
                tile_info = self.tileset.get(str(tile_id))
                is_obj = tile_info.get("is_object", False) if tile_info else False

                if tile_id != 0 and not is_obj and tile_id in self.tile_images:
                    img_list = self.tile_images[tile_id]
                    if len(img_list) > 1:
                        frame_idx = self.get_animated_frame_index(tile_id)
                        base_image = img_list[min(frame_idx, len(img_list) - 1)]
                    else:
                        base_image = img_list[0]

                    x = col * self.tile_size * scale - camera_x
                    y = row * self.tile_size * scale

                    tile_image = pygame.transform.scale(
                        base_image,
                        (int(self.tile_size * scale), int(self.tile_size * scale))
                    )
                    surface.blit(tile_image, (x, y))

        # --- 2. Draw Objects (Flagpoles, Bushes, Clouds) ---
        for obj in self.flagpoles:
            # Handle both legacy format [x] and new format [x, id]
            if isinstance(obj, list):
                fx, obj_id = obj[0], obj[1]
            else:
                fx, obj_id = obj, 10 # Default to flagpole ID
            
            str_id = str(obj_id)
            if obj_id in self.tile_images and len(self.tile_images[obj_id]) > 0:
                obj_img = self.tile_images[obj_id][0]
                
                # Metadata from the tileset
                info = self.tileset[str_id]
                w = info["width"] * scale
                h = info["height"] * scale
                
                scaled_img = pygame.transform.scale(obj_img, (int(w), int(h)))
                
                # CENTER LOGIC: (column * size) + (half tile) - (half sprite width)
                draw_x = (fx * self.tile_size * scale) - camera_x + (self.tile_size // 2 * scale) - (w // 2)
                
                # Y POSITION:
                if "cloud" in info["name"]:
                    # Clouds float high (adjust -12 as needed)
                    draw_y = (self.height - 12) * self.tile_size * scale
                else:
                    # Ground level for Flagpole and Bushes (above floor tiles at height - 2)
                    draw_y = (self.height - 2) * self.tile_size * scale - h
                
                surface.blit(scaled_img, (draw_x, draw_y))

    def get_solid_tiles(self, scale=1):
        solids = []
        for row in range(self.height):
            for col in range(self.width):
                tile_id = self.grid[row][col]
                tile_info = self.tileset.get(str(tile_id))
                if tile_info and tile_info.get("solid"):
                    rect = pygame.Rect(
                        col * self.tile_size * scale,
                        row * self.tile_size * scale,
                        self.tile_size * scale,
                        self.tile_size * scale
                    )
                    solids.append(rect)
        return solids