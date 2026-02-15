import json
import os
import pygame


class Level:
    def __init__(self, level_path, tileset_path):
        # Load level data
        with open(level_path, "r") as f:
            level_data = json.load(f)

        self.width = level_data["width"]
        self.height = level_data["height"]
        self.grid = level_data["tiles"]

        # Load tileset
        with open(tileset_path, "r") as f:
            tileset = json.load(f)

        self.tile_size = tileset["tile_size"]
        self.tileset = tileset["tiles"]

        # Load tile images
        self.tile_images = {}
        for tile_id, tile_data in self.tileset.items():
            frames = tile_data["frames"]
            if frames:
                image_path = os.path.join("sprites", "tiles", frames[0])
                image = pygame.image.load(image_path).convert_alpha()
                self.tile_images[int(tile_id)] = image

    def draw(self, surface, camera_x=0, scale=1):
        """
        Draw all tiles relative to the camera, with optional scaling.
        """
        for row in range(self.height):
            for col in range(self.width):
                tile_id = self.grid[row][col]
                if tile_id != 0 and tile_id in self.tile_images:
                    x = col * self.tile_size * scale - camera_x
                    y = row * self.tile_size * scale

                    # Scale tile if needed
                    if scale != 1:
                        tile_image = pygame.transform.scale(
                            self.tile_images[tile_id],
                            (self.tile_size * scale, self.tile_size * scale)
                        )
                    else:
                        tile_image = self.tile_images[tile_id]

                    surface.blit(tile_image, (x, y))

    def get_solid_tiles(self, scale=1):
        """
        Returns a list of solid tile rects, scaled if needed.
        """
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
