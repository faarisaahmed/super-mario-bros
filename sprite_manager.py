import pygame
import os

class SpriteManager:
    def __init__(self, base_folder, scale=1):
        self.frames = {}
        self.scale = scale
        self.mario_path = os.path.join(base_folder, "mario")
        self.frames["mario"] = []

        # load all frames
        if os.path.exists(self.mario_path):
            files = [f for f in os.listdir(self.mario_path) if f.endswith(".png")]
            files.sort(key=lambda x: int(x.split("_")[1].split(".")[0]))  # ensure order

            for file in files:
                image = pygame.image.load(os.path.join(self.mario_path, file)).convert_alpha()
                w, h = image.get_size()
                image = pygame.transform.scale(image, (w * self.scale, h * self.scale))
                self.frames["mario"].append(image)

        # define animations using the **indices of the loaded frames**
        self.animations = {
            "idle left": [13],
            "idle right": [16],
            "walk right": [17, 18, 19],
            "walk left": [10, 11, 12],
            "jump right": [21],
            "jump left": [8],
            "fall right": [18],
            "fall left": [11]
        }

        self.current_animation = None
        self.frame_index = 0
        self.timer = 0
        self.animation_speed = 0.1

    def get_frame(self, animation_type, dt):
        # change animation type
        if animation_type != self.current_animation:
            self.current_animation = animation_type
            self.frame_index = 0
            self.timer = 0

        frames = self.animations.get(animation_type, self.animations["idle right"])
        self.timer += dt
        if self.timer >= self.animation_speed:
            self.timer = 0
            self.frame_index = (self.frame_index + 1) % len(frames)

        # frames list only has indices for self.frames["mario"]
        idx = frames[self.frame_index]
        return self.frames["mario"][idx]
