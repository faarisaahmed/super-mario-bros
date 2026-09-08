import os
import pygame
from stable_baselines3 import PPO
from mario_env import MarioEnv

# Prefer the best model saved during training; fall back to the final one.
# (best_model is updated throughout training, so it's the best-so-far even if
# training was stopped early.)
if os.path.exists("best_model/best_model.zip"):
    MODEL_PATH = "best_model/best_model"
elif os.path.exists("mario_model.zip"):
    MODEL_PATH = "mario_model"
else:
    print("No trained model found. Run Train first.")
    raise SystemExit(0)

env = MarioEnv(render_mode=True)
model = PPO.load(MODEL_PATH)

obs, _ = env.reset()

while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            exit()

    action, _ = model.predict(obs, deterministic=True)
    obs, reward, terminated, truncated, _ = env.step(action)

    env.render()

    if terminated or truncated:
        obs, _ = env.reset()
