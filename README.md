# Super Mario Bros — from scratch, with a PPO agent

Super Mario Bros for the NES, rebuilt from scratch in Python, plus a
reinforcement-learning agent trained to play World 1-1 quickly.

**▶ Play it in the browser: https://faarisaahmed.github.io/super-mario-bros-rl-model/**

No install, no window — the whole game runs in the page, compiled to
WebAssembly by [pygbag](https://pygame-web.github.io/). Two modes from the
title screen:

| | |
| --- | --- |
| **1 · PLAY** | You play. Arrows move, `Z` jumps, `X` runs. On-screen buttons appear on touch devices. |
| **2 · WATCH AI** | The trained PPO policy plays it — same level, same goombas. |

`R` restarts, `H` draws hitboxes, `TAB` swaps mode, `ESC` returns to the menu.

## The physics is the point

`smb_physics.py` holds the original game's integer tables — jump forces,
friction, gravity — and `mario.py` steps them the way `smbdis.asm` does, byte
for byte. Jump height comes from how long A is held, not from a tuned
constant. `tools/rom_compare.py` diffs the result against the real ROM.

`docs/physics.md` and `docs/hitboxes.md` cover what was matched and how.

## The pipe that wasn't a hard exploration problem

The previous agent stopped at the four-tile pipe at x=2208 and cleared about
21% of the level. That looked like an exploration failure — a narrow launch
window PPO never found — and this README used to say so.

It was not. `tools/jump_sweep.py` walks Mario up to an obstacle, snapshots
every frame he is grounded on the approach, and re-runs the jump from each of
those snapshots, so it counts real reachable states rather than points on a
grid. Against that pipe, out of 73 walking and 54 running launch positions:

| hold | walking: past / on top | running: past / on top |
| --- | --- | --- |
| 18 frames (the old `FULL_JUMP_HOLD`) | 0 / 0 | 0 / 10 |
| 22 | 0 / 3 | 2 / 19 |
| 26 | 0 / 9 | 5 / 21 |
| **32** (now) | 0 / 18 | **10 / 16** |

At an 18-frame hold with no run button — all the old six-action space could
express — **the answer is zero**. Not a window it kept missing: there is no
launch position on the level that clears that pipe, so no amount of training
would ever have got past it. Launching from on top of the previous pipe is
worse, not better: only two tiles of runway, so he never reaches running
speed and never gets past.

Two things fix it, and both are in the action space rather than the
algorithm. Height saturates at a 32-frame hold (34 is identical), so that is
what `FULL_JUMP_HOLD` is now. And B is a button the agent is allowed to press.

```sh
python3 tools/jump_sweep.py --list        # obstacles in the level
python3 tools/jump_sweep.py --col 46      # sweep the tall pipe
python3 tools/jump_sweep.py --profile     # apex and travel per hold
```

## How the AI works

PPO (Stable-Baselines3) over a **26-value observation** and **eight discrete
actions**.

**Actions.** Each one is a direction, a jump-hold length and the B button:

| | | | |
| --- | --- | --- | --- |
| 0 idle | 1 walk right | 2 walk left | 3 run right |
| 4 hop right | 5 jump right | 6 run-hop right | 7 **run-jump right** |

Action 7 is the one that matters and the one the old space could not express.
B is latched for the duration of a jump it started: airborne, `X_Physics`
only grants running speed once absolute speed already reaches
`AIR_RUN_SPEED`, so a jump taken at walking pace stays at walking pace for
its whole arc whatever the policy presses next. Latching makes a run-jump one
decision instead of a thirty-frame commitment the policy has to remember to
renew every frame.

**Observation.** All relative to Mario and normalised, so the policy never
reasons about absolute world coordinates:

- velocity, on-ground, and whether running physics are currently active (4)
- ground sensors at 16/32/64/96/128px ahead (5)
- wall sensors at 16/32/48/64px ahead (4)
- **how tall the wall ahead is**, in tiles (1)
- the next step down, and separately the next *bottomless pit* (4)
- would a full jump clear that pit, computed by running the real integer
  physics forward — occupying two slots that necessarily hold the same
  number (2, see below)
- over-a-pit right now (1)
- the nearest two goombas: distance, height, whether one is closing, and
  whether a stomp would land right now (5)

Three of those are new and each fixes a specific failure:

*Wall height* — without it a two-tile pipe and the four-tile pipe are the
same observation, and only one of them needs a run-jump, so whichever answer
the policy settles on is wrong half the time.

*Step down vs. bottomless pit* — the old gap sensor probes at foot level, so
standing on a pipe it reports the drop off the end as a gap. A step down costs
nothing; a pit ends the run. A hand-written policy that cannot tell them apart
takes a full run-jump off a pipe and sails ten tiles into the real pit, which
is exactly what happened while building this.

*Goombas* — the old policy had no way to perceive an enemy, which is why AI
mode used to run the level empty.

One slot is dead weight, and knowingly so. Slots 18 and 19 were meant to be
the walking and running answers to "would a jump clear this pit". They cannot
differ: `X_Physics`' airborne branch selects the running row on speed alone
and never reads the B button, so a jump's arc is set by the speed it launched
at and nothing else. The `run=False` prediction used to gate on B as well and
so landed 3.6 tiles short whenever Mario was actually running — exactly when
the feature gets consulted. Both slots now carry the corrected number.
Deleting the duplicate would change `OBS_SIZE` and invalidate every trained
checkpoint, and the shipped policy turns out to be measurably indifferent to
that slot — correcting it changes its play not at all, frame for frame, over
20 runs — so the duplicate stays until the next retrain collapses it.

## Reward: finishing is not the same as finishing fast

Forward progress is the main driver, but its integral over the level is the
level's length however long you take — so progress alone cannot prefer fast.
Being alive therefore costs `0.05` a frame, and anything above walking speed
pays up to `0.05` a frame, which together make a frame spent running worth
about twice a frame spent walking *locally*, where PPO can see it. Finishing
pays `300` plus up to `700` more, scaled by how far under a flat-out walk the
clear came in and priced off the distance actually travelled, so a curriculum
episode that starts near the flag cannot farm it.

A stomp pays `10`; a hit or a pit costs `100` and ends the episode. An episode
that stops making progress for 240 frames is truncated — without that, sitting
against a wall is a viable way to spend three thousand rollout steps.

`tools/sanity.py` asserts all of it against the real physics, because a reward
branch that never fires costs hours before anyone notices.

## Training

```sh
python3 train_ai.py                        # the full run
MARIO_TIMESTEPS=500000 python3 train_ai.py # a short one
python3 tools/sanity.py                    # 25 checks on the environment
python3 tools/baseline.py                  # a hand-written reference policy
python3 tools/evaluate.py --episodes 20 --jitter 60
python3 watch_ai.py                        # watch it, natively
python3 tools/export_policy.py             # re-export ai/policy.json
```

Three things do the work the previous run was missing.

**Parallel rollouts.** Eight environments in worker processes rather than one
in-process. PPO is on-policy, so wall-clock is almost entirely rollout
collection.

**A random-start curriculum.** On-policy learning only improves on states it
visits. If every rollout ends at the same obstacle then nothing past it is
ever in a batch, and the tail of the level is not hard to learn — it is
absent. Early episodes start at a random point along 1-1; that fraction is
annealed to zero by 60% of the way through, so the end of training is spent
on the real task.

**Schedules.** Learning rate and entropy both decay. High entropy early is
what finds the run-jump; keeping it high is what stops the timing ever
getting sharp.

Two smaller things that turned out to matter: goombas scan every solid tile
in the level twice a frame each, which is fine for a browser with three on
screen and fatal for training, so `mario_env.TileIndex` buckets them by
column; and `VecNormalize`'s default `clip_reward=10` clips the completion
bonus, which deletes exactly the signal saying a faster clear is better.

Fine-tuning an existing policy for speed, rather than retraining:

```sh
MARIO_RESUME=best_model/best_model.zip MARIO_SPEED_BONUS=0.15 \
MARIO_TIME_COST=0.12 MARIO_TIMESTEPS=2000000 python3 train_ai.py
```

## How far it actually gets

Measured over 20 runs with the start jittered by up to 60px, so these
describe a policy rather than one memorised keypress sequence
(`tools/evaluate.py --episodes 20 --jitter 60`):

| | old agent* | scripted baseline | **this agent** |
| --- | --- | --- | --- |
| clears 1-1 | never | never | **20 / 20** |
| furthest it gets | x=2175 (21%) | x=2043 (20%) | x=10078 (100%) |
| frames to clear | — | — | best 1692, mean 1724 |
| at 60fps | — | — | **28.7 s** |
| vs a flat-out walk (2206 frames) | — | — | 1.28x faster |
| vs the physical floor (1354 frames) | — | — | 1.27x |
| goombas stomped | not simulated | 0 of 16 | 8.3 of 16 |

\* The old agent's figures are the ones this README previously reported. They
are not re-measured, and cannot be: its observation was 16 values wide and
its action space six, so it does not load into this environment at all. The
checkpoint itself is still recoverable —
`git show HEAD:best_model/best_model.zip`.

The floor is what holding right and B gets you across an empty level of the
same length. Nothing can beat it and it is not quite reachable, since some
jumps have to be taken at less than full speed — but it is the honest
denominator for "fast", where a walking par is only the reward's yardstick.

### What it worked out

The action mix is not what I expected:

| hop right | run right | run-jump right | run-hop right | walk right |
| --- | --- | --- | --- | --- |
| 55% | 36% | 6% | 2% | 1% |

It builds speed on the ground with `run right`, and then **chains short hops**
— which hold no B at all. That looks wrong until you read `X_Physics`: the
airborne branch takes the running row whenever absolute speed is already at
`AIR_RUN_SPEED`, and it never consults the B button. So once you are at speed,
hopping keeps it. On flat ground over 600 frames, in scaled px per frame:

```
hold run right            7.215      run right, then hop      7.215
hold walk right           4.345      hop right from a stop    4.345
```

Identical — so hopping costs nothing. What it buys is that a goomba's contact
box sits at body height: being airborne most of the time means most of them
cannot reach you, and the ones you come down on get stomped instead. The
trade is control, since a hop is committed once it starts, which is presumably
why the 6% of run-jumps are still there for the tall pipes. It found a
bunny-hop, and it found it because the physics is the real physics.

### What is still wrong

**PPO's last policy is not its best one, and not by a little.** The final
checkpoint of the fine-tune scores **0/20** — three quarters of those runs end
at the first goomba — while the best-evaluated checkpoint from the same run
scores 20/20. Evaluation
reward oscillates between a full clear (~1400) and an early death (~70)
throughout training. `EvalCallback` keeping the best checkpoint is not a nicety
here, it is the only reason there is a model at all, which is why every tool
prefers `best_model_speed/` over `mario_model.zip`.

**The cold run peaked early and then went nowhere.** Six million steps were
budgeted; it hit its best at about 700k and 3M further steps produced no
improvement, so it was stopped. The cause looks like `clip_reward=10` — see
Training. What ships is a 2.5M-step fine-tune of that peak with the clipping
fixed and the speed weights raised, which took the clear rate from 18/20 to
20/20 and the mean time from 1786 frames to 1724.

**One-tile pits are the thin ice.** The pre-fine-tune model's only two
failures in 20 were both at the single-tile pit at x=4176, the narrowest in
the level. The shipped model clears it in all 20, but that is the spot to
watch.

Total training: about 25 minutes on eight cores.

## torch does not run in a browser

The web build cannot call `PPO.load(...).predict(...)`: neither torch nor
gymnasium has a WebAssembly build. The actor is small enough not to need one —
26→64→64→8 with tanh — so `tools/export_policy.py` lifts the weights into
`ai/policy.json` and `mario_ai.Policy` replays the forward pass in plain
Python, about 6.3k multiply-adds per frame. The hidden layers stay at 64 for
that reason: 128 would be 20k a frame, which measures fine in CPython and is
a gamble in Pyodide.

The export refuses to write a file whose actions disagree with torch's, over
4000 sampled observations. That check is what makes "the model you trained" an
accurate description of what the page runs, and
`python3 tools/evaluate.py --both` scores the two side by side.

`mario_ai.py` also holds the observation builder and the action-to-joypad
mapping, and `mario_env.py` imports both — so the numbers the policy sees in
training are produced by the same code that feeds it in the browser. It
imports no pygame, so the sensors work outside a display context too.

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
