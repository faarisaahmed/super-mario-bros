import pygame
import os

class SpriteManager:
    def __init__(self, base_folder, scale=1):
        self.frames = {}
        self.scale = scale

        # Load ONLY mario folder
        mario_path = os.path.join(base_folder, "mario")
        self.frames["mario"] = []
        files = [f for f in os.listdir(mario_path) if f.endswith(".png")]

        # Sort numerically by the number in frame_#.png
        files.sort(key=lambda x: int(x.split("_")[1].split(".")[0]))

        for file in files:
            image = pygame.image.load(
                os.path.join(mario_path, file)
            ).convert_alpha()

            # Scale using the SAME scale as background
            width = int(image.get_width() * self.scale)
            height = int(image.get_height() * self.scale)

            image = pygame.transform.scale(image, (width, height))
            self.frames["mario"].append(image)

        # ---- Animations ----
        self.animations = {
            "idle left": [("mario", 13)],
            "idle right": [("mario", 16)],
            "walk right": [("mario", 17), ("mario", 18), ("mario", 19)],
            "walk left": [("mario", 10), ("mario", 11), ("mario", 12)],
            "jump": [("mario", 21)],
        }

        self.frame_index = 0
        self.animation_speed = 1 / 10  # 10 frames per second
        self.timer = 0
        self.current_animation = None

    def get_frame(self, animation_type, dt):
        if animation_type != self.current_animation:
            self.frame_index = 0
            self.timer = 0
            self.current_animation = animation_type

        animation = self.animations[animation_type]

        self.timer += dt
        if self.timer >= self.animation_speed:
            self.timer = 0
            self.frame_index += 1

        self.frame_index %= len(animation)

        folder, frame_number = animation[self.frame_index]
        return self.frames[folder][frame_number]
