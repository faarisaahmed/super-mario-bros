# Super Mario Bros — from scratch, with a PPO agent

Super Mario Bros for the NES, rebuilt from scratch in Python, plus a
reinforcement-learning agent trained to play World 1-1.

**▶ Play it in the browser: https://faarisaahmed.github.io/super-mario-bros-rl-model/**

No install, no window — the whole game runs in the page, compiled to
WebAssembly by [pygbag](https://pygame-web.github.io/). Two modes from the
title screen:

| | |
| --- | --- |
| **1 · PLAY** | You play. Arrows move, `Z` jumps, `X` runs. On-screen buttons appear on touch devices. |
| **2 · WATCH AI** | The trained PPO policy plays it. |

`R` restarts, `H` draws hitboxes, `TAB` swaps mode, `ESC` returns to the menu.

## The physics is the point

`smb_physics.py` holds the original game's integer tables — jump forces,
friction, gravity — and `mario.py` steps them the way `smbdis.asm` does, byte
for byte. Jump height comes from how long A is held, not from a tuned
constant. `tools/rom_compare.py` diffs the result against the real ROM.

`docs/physics.md` and `docs/hitboxes.md` cover what was matched and how.

## How the AI works

PPO (Stable-Baselines3) over a 16-value observation — velocity, ground and
wall sensors at fixed distances ahead, and gap geometry including a
"would a full jump clear this?" feature computed by running the real physics
forward. Six discrete actions: idle, left, right, hop-right, jump-right, jump.
It sees terrain only, never enemies.

```sh
python3 train_ai.py            # train (MARIO_TIMESTEPS=500000 to shorten)
python3 watch_ai.py            # watch the checkpoint play, natively
python3 tools/export_policy.py # re-export ai/policy.json for the web build
```

### How far it actually gets

**The agent clears about 21% of 1-1 and then stalls.** It walks and jumps its
way to x≈2175, reaches the four-tile-tall pipe there, and stops. Both
checkpoints do exactly this, and the browser build reproduces it frame for
frame.

That pipe is clearable — but barely. Sweeping every grounded launch position
in front of it:

| jump hold | launch positions that clear the pipe |
| --- | --- |
| 18 frames (`FULL_JUMP_HOLD`, the longest the action space offers) | 26 |
| 20 frames | 264 |
| 24 frames | 764 |

So the agent's biggest jump does clear it, from a window roughly a tile and a
half wide. PPO never found that window. Widening `FULL_JUMP_HOLD` to ~24 in
`mario_ai.py` and retraining would turn a needle-threading exploration
problem into an easy one — at the cost of invalidating the current weights.

## torch does not run in a browser

The web build cannot call `PPO.load(...).predict(...)`: neither torch nor
gymnasium has a WebAssembly build. The actor is small enough not to need one —
16→64→64→6 with tanh — so `tools/export_policy.py` lifts the weights into
`ai/policy.json` and `mario_ai.Policy` replays the forward pass in plain
Python, about 5.5k multiply-adds per frame.

The export refuses to write a file whose actions disagree with torch's, over
4000 sampled observations. That check is what makes "the model you trained" an
accurate description of what the page runs.

`mario_ai.py` also holds the observation builder and the action-to-joypad
mapping, and `mario_env.py` imports both — so the numbers the policy sees in
training are produced by the same code that feeds it in the browser.

## Building the web version

```sh
./tools/build_web.sh          # -> build/web/
./tools/build_web.sh --serve  # build and serve on :8000
```

It stages only what the browser needs before invoking pygbag: pygbag bundles
everything under the app directory, and the training-only files (checkpoints,
tensorboard logs, `mario_env.py`) would otherwise ride along as dead weight.

Pushing to `main` runs the same script in CI and publishes `build/web` to
Pages — see `.github/workflows/pages.yml`.

## Running natively

```sh
pip install -r requirements.txt
python3 main.py
```

`level_editor.py` edits `levels/1-1.json`; `server.py` is a small local
launcher for the desktop build.
