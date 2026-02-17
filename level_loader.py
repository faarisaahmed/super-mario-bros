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
        self.grid = level_data["tiles"]

        # 2. Load tileset configuration
        with open(tileset_path, "r") as f:
            tileset_config = json.load(f)

        self.tile_size = tileset_config["tile_size"]
        self.tileset = tileset_config["tiles"]  # Key fix: defining self.tileset

        # 3. Load tile images (handling animations)
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

        # Animation tracking
        self.animation_timer = 0

    def get_animated_frame_index(self, tile_id):
        tile_info = self.tileset.get(str(tile_id))
        durations = tile_info.get("frame_durations") # e.g., [24, 7, 8, 7]
        
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

        for row in range(self.height):
            for col in range(self.width):
                tile_id = self.grid[row][col]
                if tile_id != 0 and tile_id in self.tile_images:
                    
                    img_list = self.tile_images[tile_id]
                    if len(img_list) > 1:
                        frame_idx = self.get_animated_frame_index(tile_id)
                        # Safety check if indices match frame count
                        frame_idx = min(frame_idx, len(img_list) - 1)
                        base_image = img_list[frame_idx]
                    else:
                        base_image = img_list[0]

                    x = col * self.tile_size * scale - camera_x
                    y = row * self.tile_size * scale

                    tile_image = pygame.transform.scale(
                        base_image,
                        (int(self.tile_size * scale), int(self.tile_size * scale))
                    )
                    surface.blit(tile_image, (x, y))

    def get_solid_tiles(self, scale=1):
        """Used by Mario's physics to check for collisions."""
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