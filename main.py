"""Super Mario Bros — desktop and browser entry point.

The loop is `async` because that is what pygbag needs: in WebAssembly there is
no way to block the main thread, so every frame has to yield back to the
browser event loop via `await asyncio.sleep(0)`. On desktop `asyncio.run`
costs nothing, so one file serves both.

Two modes, chosen from the title screen:

  PLAY      keyboard/touch control, goombas active — the normal game.
  WATCH AI  the PPO policy from `ai/policy.json` drives Mario.

AI mode deliberately runs the level without goombas. The policy's 16 inputs
(see mario_ai.MarioSenses.observe) describe terrain only — it was never shown
an enemy and has no way to perceive one — so putting goombas in front of it
would be showing off a handicap rather than the model.
"""

import asyncio
import os
import sys

import pygame

import goomba as goomba_mod
from goomba import Goomba
from level_loader import Level
from mario import Mario
from mario_ai import ACTION_NAMES, MarioSenses, Policy
from sprite_manager import SpriteManager

WEB = sys.platform == "emscripten"

pygame.init()
try:
    pygame.mixer.init()
except pygame.error:
    pass
pygame.joystick.init()

controller = None
if pygame.joystick.get_count() > 0:
    controller = pygame.joystick.Joystick(0)
    controller.init()
    print("Controller connected:", controller.get_name())

SCALE = 3
BASE_WIDTH, BASE_HEIGHT = 256, 240
screen_width, screen_height = BASE_WIDTH * SCALE, BASE_HEIGHT * SCALE
screen = pygame.display.set_mode((screen_width, screen_height))
pygame.display.set_caption("Super Mario Bros — AI")
clock = pygame.time.Clock()
FPS = 60

# The AI was trained on a fixed 1/60 timestep. Feeding it wall-clock dt would
# put it in states the policy never saw, so AI mode steps at exactly the rate
# the env did and only the human mode uses real elapsed time.
AI_DT = 1 / 60

sprites = SpriteManager("sprites", SCALE)
level = Level("levels/1-1.json", "tileset.json")
LEVEL_PIXEL_WIDTH = level.width * level.tile_size * SCALE
FLOOR_Y = level.height * level.tile_size * SCALE

font_big = pygame.font.Font(None, 64)
font = pygame.font.Font(None, 30)
font_small = pygame.font.Font(None, 22)

SKY = (92, 148, 252)
HITBOX_COLOR = (126, 239, 72)
SOLID_BOX_COLOR = (150, 150, 150)
HITBOX_LINE = max(1, SCALE // 2)


# ── audio ─────────────────────────────────────────────────────────────
# Browsers refuse to start audio until the page has been interacted with, so
# the music can only begin once the player has picked a mode. Every call is
# guarded: no-audio is a fine way to play, a traceback is not.
def start_music():
    try:
        pygame.mixer.music.load(os.path.join("music", "overworld1_mario.ogg"))
        pygame.mixer.music.set_volume(0.5)
        pygame.mixer.music.play(-1)
    except pygame.error:
        pass


def stop_music():
    try:
        pygame.mixer.music.stop()
    except pygame.error:
        pass


# ── the trained policy ────────────────────────────────────────────────
def load_policy():
    """None if there is no exported model; AI mode then says so rather than
    disappearing from the menu."""
    try:
        return Policy.load()
    except (OSError, ValueError) as exc:
        print("Could not load ai/policy.json:", exc)
        return None


policy = load_policy()
senses = MarioSenses()


# ── world ─────────────────────────────────────────────────────────────
class World:
    """One attempt at the level. `with_goombas` is what separates a human
    run from the enemy-free conditions the policy was trained under."""

    def __init__(self, with_goombas):
        self.with_goombas = with_goombas
        self.reset()

    def reset(self):
        self.mario = Mario(x=100, y=0, scale=SCALE)
        self.goombas = (
            [Goomba(gx, gy, level.tile_size, SCALE) for gx, gy in level.goombas]
            if self.with_goombas
            else []
        )
        self.camera_x = 0
        self.won = False
        senses.reset()

    def update_camera(self):
        if self.mario.x - self.camera_x > screen_width // 2:
            self.camera_x = self.mario.x - screen_width // 2
            if self.camera_x > LEVEL_PIXEL_WIDTH - screen_width:
                self.camera_x = LEVEL_PIXEL_WIDTH - screen_width

    def resolve_goombas(self, dt):
        goomba_mod.tick_interval_timers(dt)
        solid_tiles = level.get_solid_tiles(SCALE)
        for goomba in self.goombas:
            goomba.update(dt, solid_tiles, self.camera_x, screen_width)

        # Coming down on an enemy's contact box stomps it; touching it any
        # other way is fatal.
        if self.mario.dying:
            return
        mario_box = self.mario.rect()
        for goomba in self.goombas:
            if not goomba.is_dangerous():
                continue
            if not mario_box.colliderect(goomba.hitbox()):
                continue
            if self.mario.is_descending():
                goomba.squash()
                self.mario.stomp()
            else:
                self.mario.die()
            break

    def fell_out(self):
        return self.mario.y >= FLOOR_Y

    def reached_flag(self):
        return self.mario.x >= LEVEL_PIXEL_WIDTH - 50

    def draw(self, dt, show_hitboxes):
        screen.fill(SKY)
        level.draw(screen, dt, self.camera_x, SCALE)
        for goomba in self.goombas:
            if goomba.alive:
                goomba.draw(screen, self.camera_x)
        self.mario.draw(screen, sprites, self.camera_x, dt)

        if show_hitboxes:
            # Boxes are in world space; shift them by the camera to get
            # screen space. A squashed goomba can't hurt anyone, so it gets
            # no contact box.
            threats = [g for g in self.goombas if g.is_dangerous()]
            for box in [g.rect() for g in self.goombas if g.alive]:
                pygame.draw.rect(screen, SOLID_BOX_COLOR,
                                 box.move(-self.camera_x, 0), HITBOX_LINE)
            for box in [self.mario.rect()] + [g.hitbox() for g in threats]:
                pygame.draw.rect(screen, HITBOX_COLOR,
                                 box.move(-self.camera_x, 0), HITBOX_LINE)


# ── touch controls ────────────────────────────────────────────────────
# Only drawn on the web build, where there may be no keyboard at all. They
# feed set_buttons() directly, the same entry point the keyboard and the
# training env use, so they cannot drift from the real controls.
PAD = 14
BTN = 96


def touch_zones():
    y = screen_height - BTN - PAD
    return {
        "left": pygame.Rect(PAD, y, BTN, BTN),
        "right": pygame.Rect(PAD * 2 + BTN, y, BTN, BTN),
        "b": pygame.Rect(screen_width - PAD * 2 - BTN * 2, y, BTN, BTN),
        "a": pygame.Rect(screen_width - PAD - BTN, y, BTN, BTN),
    }


TOUCH_LABELS = {"left": "<", "right": ">", "b": "B", "a": "A"}


def draw_touch_controls(held):
    overlay = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
    for name, rect in touch_zones().items():
        down = name in held
        pygame.draw.rect(overlay, (255, 255, 255, 110 if down else 55),
                         rect, border_radius=16)
        pygame.draw.rect(overlay, (0, 0, 0, 140), rect, 3, border_radius=16)
        label = font.render(TOUCH_LABELS[name], True, (0, 0, 0))
        overlay.blit(label, label.get_rect(center=rect.center))
    screen.blit(overlay, (0, 0))


class Pointers:
    """Which mouse/finger contacts are currently down, and where.

    Tracked from the event stream rather than polled. pygame's multi-touch
    query API (get_num_touch_devices / touch_get_finger) hangs outright in
    pygbag's WebAssembly SDL -- it never returns, so the whole game loop
    stops on the first frame that calls it. Events work fine.
    """

    def __init__(self):
        self.down = {}       # id -> (x, y) in screen space
        self.pressed = []    # positions that went down this frame

    def begin_frame(self):
        self.pressed = []

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.down["mouse"] = event.pos
            self.pressed.append(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP:
            self.down.pop("mouse", None)
        elif event.type == pygame.MOUSEMOTION:
            if "mouse" in self.down:
                self.down["mouse"] = event.pos
        elif event.type == pygame.FINGERDOWN:
            pos = (event.x * screen_width, event.y * screen_height)
            self.down[event.finger_id] = pos
            self.pressed.append(pos)
        elif event.type == pygame.FINGERMOTION:
            if event.finger_id in self.down:
                self.down[event.finger_id] = (event.x * screen_width,
                                              event.y * screen_height)
        elif event.type == pygame.FINGERUP:
            self.down.pop(event.finger_id, None)

    def held_buttons(self):
        """Which on-screen buttons currently have a contact inside them."""
        points = list(self.down.values())
        if not points:
            return set()
        return {name for name, rect in touch_zones().items()
                if any(rect.collidepoint(p) for p in points)}


# ── HUD / screens ─────────────────────────────────────────────────────
def shadowed(surface, text, f, color, pos, center=False):
    shadow = f.render(text, True, (0, 0, 0))
    body = f.render(text, True, color)
    rect = body.get_rect(center=pos) if center else body.get_rect(topleft=pos)
    surface.blit(shadow, rect.move(2, 2))
    surface.blit(body, rect)
    return rect


TITLE_PLAY = pygame.Rect(0, 0, 420, 66)
TITLE_AI = pygame.Rect(0, 0, 420, 66)
TITLE_PLAY.center = (screen_width // 2, 360)
TITLE_AI.center = (screen_width // 2, 446)


def draw_title():
    screen.fill(SKY)
    shadowed(screen, "SUPER MARIO BROS", font_big, (255, 255, 255),
             (screen_width // 2, 200), center=True)
    shadowed(screen, "with a PPO agent that learned 1-1", font, (255, 240, 160),
             (screen_width // 2, 254), center=True)

    for rect, label, sub, enabled in (
        (TITLE_PLAY, "1  ·  PLAY", "arrows move · Z jump · X run", True),
        (TITLE_AI, "2  ·  WATCH AI",
         "the trained model plays it" if policy else "ai/policy.json missing",
         policy is not None),
    ):
        fill = (0, 0, 0, 90) if enabled else (0, 0, 0, 40)
        box = pygame.Surface(rect.size, pygame.SRCALPHA)
        box.fill(fill)
        screen.blit(box, rect.topleft)
        pygame.draw.rect(screen, (255, 255, 255) if enabled else (150, 150, 150),
                         rect, 3)
        color = (255, 255, 255) if enabled else (170, 170, 170)
        shadowed(screen, label, font, color, (rect.centerx, rect.centery - 10),
                 center=True)
        shadowed(screen, sub, font_small, (220, 220, 220) if enabled else (150, 150, 150),
                 (rect.centerx, rect.centery + 16), center=True)

    shadowed(screen, "R restart · H hitboxes · TAB swap mode · ESC menu",
             font_small, (255, 255, 255), (screen_width // 2, screen_height - 40),
             center=True)


def draw_hud(mode, world, action, attempts, best_x):
    if mode == "ai":
        lines = [
            "WATCHING THE TRAINED MODEL",
            "action: %s" % ACTION_NAMES[action],
            "run %d · x %d · best %d" % (attempts, int(world.mario.x), int(best_x)),
            "no goombas: the policy sees terrain only",
        ]
        color = (255, 240, 160)
    else:
        lines = ["YOU"]
        color = (255, 255, 255)

    panel = pygame.Surface((360, 22 * len(lines) + 12), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 110))
    screen.blit(panel, (10, 10))
    for i, line in enumerate(lines):
        shadowed(screen, line, font_small, color if i == 0 else (235, 235, 235),
                 (20, 18 + i * 22))


def draw_banner(text):
    surf = pygame.Surface((screen_width, 90), pygame.SRCALPHA)
    surf.fill((0, 0, 0, 150))
    screen.blit(surf, (0, screen_height // 2 - 45))
    shadowed(screen, text, font_big, (255, 240, 160),
             (screen_width // 2, screen_height // 2), center=True)


# ── main loop ─────────────────────────────────────────────────────────
async def main():
    global policy

    mode = "title"          # "title" | "play" | "ai"
    world = None
    show_hitboxes = False
    held_touch = set()
    last_action = 0
    attempts = 1
    best_x = 0
    win_timer = 0.0
    music_started = False

    def enter(new_mode):
        nonlocal mode, world, attempts, best_x, win_timer, last_action, music_started
        mode = new_mode
        if new_mode == "title":
            stop_music()
            music_started = False
            world = None
            return
        world = World(with_goombas=(new_mode == "play"))
        attempts = 1
        best_x = 0
        win_timer = 0.0
        last_action = 0
        if not music_started:
            start_music()
            music_started = True

    pointers = Pointers()

    running = True
    while running:
        dt = clock.tick(FPS) / 1000
        # A tab-out or a slow first frame can hand us a huge dt, which would
        # tunnel Mario through the floor. Cap it at a few frames' worth.
        dt = min(dt, 0.05)

        pointers.begin_frame()
        for event in pygame.event.get():
            pointers.handle(event)
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    enter("title")
                elif mode == "title":
                    if event.key in (pygame.K_1, pygame.K_p, pygame.K_RETURN):
                        enter("play")
                    elif event.key in (pygame.K_2, pygame.K_a) and policy:
                        enter("ai")
                elif event.key == pygame.K_h:
                    show_hitboxes = not show_hitboxes
                elif event.key == pygame.K_r:
                    world.reset()
                    win_timer = 0.0
                elif event.key == pygame.K_TAB:
                    if mode == "play" and policy:
                        enter("ai")
                    elif mode == "ai":
                        enter("play")

        if mode == "title":
            for pos in pointers.pressed:
                if TITLE_PLAY.collidepoint(pos):
                    enter("play")
                elif TITLE_AI.collidepoint(pos) and policy:
                    enter("ai")
            draw_title()
            pygame.display.flip()
            await asyncio.sleep(0)
            continue

        held_touch = pointers.held_buttons() if WEB else set()

        if mode == "ai":
            # Exactly the env's step order: read on_ground, choose, apply,
            # advance physics, move the camera, then observe.
            was_on_ground = world.mario.on_ground
            obs = senses.observe(world.mario, level)
            last_action = policy.act(obs)
            senses.apply_action(world.mario, level, last_action, was_on_ground)
            world.mario.update(AI_DT, world.camera_x, level.solid_at)
            world.update_camera()

            best_x = max(best_x, world.mario.x)
            if world.reached_flag():
                world.won = True
            if world.fell_out() or world.won:
                win_timer += dt
                if win_timer > (2.0 if world.won else 0.6):
                    world.reset()
                    attempts += 1
                    win_timer = 0.0
        else:
            keys = pygame.key.get_pressed()
            world.mario.handle_input(keys, controller)
            if held_touch and not world.mario.dying:
                # OR the on-screen pad over whatever the keyboard said.
                world.mario.set_buttons(
                    left=world.mario.btn_left or "left" in held_touch,
                    right=world.mario.btn_right or "right" in held_touch,
                    a=world.mario.btn_a or "a" in held_touch,
                    b=world.mario.btn_b or "b" in held_touch,
                )
            world.mario.update(dt, world.camera_x, level.solid_at)
            world.resolve_goombas(dt)
            world.update_camera()

            if world.reached_flag():
                world.won = True
            if world.fell_out():
                world.reset()

        world.draw(dt, show_hitboxes)
        draw_hud(mode, world, last_action, attempts, best_x)
        if world.won:
            draw_banner("COURSE CLEAR")
        if WEB and mode == "play":
            draw_touch_controls(held_touch)

        pygame.display.flip()
        await asyncio.sleep(0)

    pygame.quit()


asyncio.run(main())
