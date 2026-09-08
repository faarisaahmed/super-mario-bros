# Physics

Every constant in `smb_physics.py` is copied from the Super Mario Bros. 6502
disassembly rather than measured off a recording. Line numbers below refer to
`smbdis.asm` (doppelganger's disassembly; the copy in
[MitchellSternke/SuperMarioBros-C](https://github.com/MitchellSternke/SuperMarioBros-C/blob/master/docs/smbdis.asm)).

## Fixed point

Two different formats, and confusing them is the easy mistake:

| quantity | format | example |
|---|---|---|
| X speed | signed byte, 4.4 — whole px in the high nybble, sixteenths in the low | `$18` = 1.5 px/frame |
| X move force | 8-bit fraction of an X-speed unit | 1 unit = 1/4096 px/frame |
| Y speed | signed byte, **whole** px/frame | `$fc` = −4 px/frame |
| Y move force | 8-bit fraction of a pixel | 1 unit = 1/256 px |
| gravity ("movement force") | added to Y move force each frame | `$20` = 0.125 px/frame² |

There is no `dt` anywhere in the original — every value is per frame at 60 Hz.
`Mario.update()` therefore accumulates real time and steps a fixed 60 Hz
simulation, which is what keeps these numbers meaningful.

## Horizontal (`smbdis.asm:6026-6033`, `6146-6190`, `6227`)

```
MaxLeftXSpdData:   $d8, $e8, $f0          -> -2.5, -1.5, -1.0 px/frame
MaxRightXSpdData:  $28, $18, $10, $0c     ->  2.5,  1.5,  1.0, 0.75 px/frame
FrictionData:      $e4, $98, $d0          ->  228, 152, 208  (1/4096 px/frame²)
```

Index 0 is running, 1 walking, 2 swimming (not implemented), 3 the pipe intro.
One accelerator serves both speeding up and slowing down — releasing the d-pad
uses the same value against the direction of travel. It **doubles while
skidding** (facing direction ≠ moving direction), which is why turning around
at speed is so much sharper than accelerating.

Holding B latches `RunningTimer` for 10 frames, so briefly releasing it doesn't
drop you out of the running row.

Below `$0b` of speed while skidding, horizontal speed snaps to zero and the
moving direction flips (`GetPlayerAnimSpeed`, `smbdis.asm:6216`).

Measured from this port: **walk `$18` = 1.50 px/frame, run `$28` = 2.50
px/frame**, reached in 36 and 47 frames from a standstill.

## Jumping (`smbdis.asm:6014-6024`, `6081-6127`, `5922-5936`)

The row is chosen by `Player_XSpeedAbsolute` **at the instant of the jump**, so
a running jump both launches harder and falls slower:

| X speed at launch | launch | gravity, A held | gravity, A released |
|---|---|---|---|
| < `$09` | −4 | `$20` = 0.1250 | `$70` = 0.4375 |
| `$09`–`$0f` | −4 | `$20` = 0.1250 | `$70` = 0.4375 |
| `$10`–`$18` | −4 | `$1e` = 0.1172 | `$60` = 0.3750 |
| `$19`–`$1b` | −5 | `$28` = 0.1563 | `$90` = 0.5625 |
| ≥ `$1c` | −5 | `$28` = 0.1563 | `$90` = 0.5625 |

**Variable jump height is not a velocity cut.** Releasing A does not touch the
speed — it swaps gravity from the small value to the large one, and the arc
does the rest (`JumpSwimSub`). `DiffToHaltJump` = 1 means releasing A before
rising a single pixel doesn't cut the jump, so a one-frame tap still leaves the
ground.

Terminal velocity is 4 px/frame (`MovePlayerVertically`, `smbdis.asm:7592`).

Resulting apex heights in this port, above the launch point:

| | px | blocks |
|---|---|---|
| standing, 1-frame tap | 24 | 1.50 |
| standing, hold A | 66 | 4.12 |
| walking, hold A | 71 | 4.44 |
| running, hold A | 83 | 5.19 |

The ~4-block standing jump and ~5-block running jump are the two figures the
original is best known for.

## Stomping (`smbdis.asm:11480-11512`)

A goomba (ID `$06`) is under `$09`, so it takes `ChkForDemoteKoopa` →
`HandleStompedShellE` → `SBnce`, which does exactly one thing to the player:

```
SBnce: lda #$fc          ; -4 px/frame
       sta Player_Y_Speed
```

Nothing else is touched — not the state, not the gravity. So the bounce is
governed by whatever `VerticalForce` already held, and that is always the
*falling* gravity: the weak jump gravity is written in exactly one place,
`GetYPhy` (`smbdis.asm:6117`), reached only when a jump is initiated. Every
other write dumps `VerticalForceDown`. To be falling onto a goomba at all you
must have passed your apex, which already overwrote it.

**Holding A therefore does not bounce you higher.** `ProcSwim` only skips the
overwrite; by then there is nothing left to preserve. The bounce is a flat
4 px/frame against the fall gravity of your last jump:

| last jump was | fall gravity | bounce |
|---|---|---|
| standing / slow | `$70` = 0.4375 | 21 px (1.31 blocks) |
| walking | `$60` = 0.3750 | 24 px (1.50 blocks) |
| running | `$90` = 0.5625 | 17 px (1.06 blocks) |

Roughly a block, and *lower* after a running jump — the faster you were going,
the harder your gravity, so the less you rebound.

The flattened goomba is not on a frame counter. `HandleStompedShellE` sets
`EnemyIntervalTimer` to `$10`, and `ChkKillGoomba` (`smbdis.asm:9360`) erases it
once that timer reads `$0e` — two decrements. Interval timers only tick when
`IntervalTimerControl` wraps, every 21 frames (`DecTimers`, `smbdis.asm:789`).
So the sprite lasts **23–43 frames depending on the phase of a shared clock**,
averaging 33. `goomba.tick_interval_timers()` reproduces that shared clock;
`main.py` ticks it once per frame.

## Death (`smbdis.asm:11427`, `5766`, `7546`)

```
KillPlayer:  Player_X_Speed = 0
             Player_Y_Speed = $fc        ; -4 px/frame
             GameEngineSubroutine = $0b
             TimerControl = $ff
```

`PlayerDeath` refuses to run until `TimerControl` drops below `$f0`, and it
ticks once a frame — so he hangs **motionless for 16 frames** before moving.

The arc's gravity is not from the jump tables. `LRAir` contains:

```
lda GameEngineSubroutine
cmp #$0b
bne ExitMov1
lda #$28
sta VerticalForce
```

While the death routine is active, gravity is pinned at `$28` = 0.15625
px/frame² every frame. That gives an apex of v²/2g = 51.2 px, reached ~25
frames after the freeze ends, then he falls through the floor. Measured here:
**16 frames frozen, apex 54 px at frame 41.**

## Enemies (`smbdis.asm:8163`, `7599-7644`)

```
NormalXSpdData: $f8, $f4      -> -0.5, -0.75 px/frame (normal, hard mode)
MoveD_EnemyVertically: $3d    -> gravity 0.238 px/frame²
SetHiMax:              $03    -> terminal 3 px/frame
```

Enemies fall harder than Mario but top out slower — 3 px/frame against his 4.
A goomba walks at half a pixel a frame, a third of Mario's walking speed.

## Bounding boxes (`BoundBoxCtrlData`, `smbdis.asm:12766`)

Each row is `[left, top, right, bottom]` added to the object's position, so the
box spans corner to corner **inclusive** — a row of `$03 … $0d` covers columns
3 through 13, which is 11 pixels wide, not 10.

| row | object | box |
|---|---|---|
| 1 | small Mario | `$03, $14, $0d, $20` → **11 x 13** |
| 9 | goomba | `$03, $0e, $0d, $14` → **11 x 7** |

These match the hitboxes already measured off the reference art in
`docs/hitboxes.md` exactly, including the left inset of 3. Two independent
sources agreeing is a good sign both are right.

## Verification

Two levels of checking, both reproducible.

**Constants, against the cartridge.** SMB is NROM, so CPU `$8000` is file
offset 16 and every table can be read straight out of a `.nes` dump. All 19
constants used here were confirmed byte-for-byte that way, and independently
against [McFadden's disassembly](https://6502disassembly.com/nes-smb/), which
prints the ROM bytes alongside each line.

**Behaviour, against the running game.** `tools/rom_compare.py` uses `nes-py`
to run the real ROM in-process, drives it with scripted button sequences, and
diffs SMB's own state bytes — `Player_X_Speed`, `Player_X_MoveForce`,
`Player_Y_Speed`, `Player_Y_MoveForce` — against this engine frame by frame.
Those four *are* the physics. Since the collision system is now the
original's, `Player_Y_Position` is compared too on the in-place scenarios,
which tests the whole vertical arc end to end — rise, apex, fall, landing and
the `LandPlyr` snap. Our Mario settles at `Player_Y_Position` `$b0`, the same
value the ROM reports.

```
$ python3 tools/rom_compare.py
  stand still                        OK   59 frames identical
  jump in place, 1-frame tap         OK   90 frames identical
  jump in place, 6-frame hold        OK   95 frames identical
  jump in place, hold A fully        OK  109 frames identical
  two jumps in place                 OK  179 frames identical
  walk right, then release           OK  119 frames identical
  run right with B, then release B   OK   98 frames identical
  run right then skid left           OK  119 frames identical
  tap B on and off                   OK  108 frames identical
  running jump, hold A               OK   94 frames identical
  walking jump, hold A               OK  119 frames identical
  1189 frames of physics compared against the cartridge
  ALL SCENARIOS MATCH
```

`tools/rom_compare_contact.py` covers what those scenarios deliberately avoid
— actual contact. It runs Mario into the first goomba and the first pipe of
1-1, and to make positions comparable it reads the **ROM's own block buffer**
out of RAM each frame and uses that as the collision map, so both sides
collide against identical geometry.

```
$ python3 tools/rom_compare_contact.py
  OK   run into the first pipe: 299 frames identical
  OK   stomp the first goomba: 259 frames identical
       ROM stomped on frame 192; we stomped on frame 192
  CONTACT SCENARIOS MATCH
```

Both compare `world_x` and `Player_Y_Position` alongside the speed bytes, and
the stomp scenario mirrors the ROM's goomba position each frame and lets our
own contact rule decide, so the trigger frame is under test too, not just the
bounce.

Two notes on reading that output. nes-py's post-step RAM snapshot precedes
that frame's game logic, so the ROM trails by exactly one frame (`LAG = 1`,
established empirically: lag 1 matches 59/59 across every input type, lag 0
and 2 match essentially nothing). And scenarios stop once Mario passes
`world_x` 220, where 1-1 stops being flat — beyond that the ROM starts
clipping blocks and its speed changes for collision reasons the bare test
floor cannot reproduce.

This is what caught the `x_moveforce` bug: `Player_X_MoveForce` ($0705, the
fraction of *speed*, used by friction) and `SprObject_X_MoveForce` ($0400, the
fraction of *position*, used by the movement routine) are different variables.
Collapsing them into one made acceleration drift — the ROM adds a flat 152 per
frame, the buggy port added 152, 168, 184, 200... Reading the tables correctly
was not enough; only running the ROM exposed it.

## Collision and ground detection (`smbdis.asm:11902`, `12318`, `13053`)

The original does **not** intersect rectangles. `PlayerBGCollision` samples
seven single pixels around the player and asks what metatile sits under each:

| point | offset from `Player_X/Y_Position` | from our hitbox |
|---|---|---|
| head | `+$08, +$12` | `x+5, y-2` |
| foot left | `+$03, +$20` | `x+0, y+12` |
| foot right | `+$0c, +$20` | `x+9, y+12` |
| left side x2 | `+$02, +$18` | `x-1, y+4` |
| right side x2 | `+$0d, +$18` | `x+10, y+4` |

Offsets come from `BlockBuffer_X_Adder` / `BlockBuffer_Y_Adder` at base `$0e`,
the row `BlockBufferAdderData` selects for small Mario. `Player_X/Y_Position`
is not the hitbox corner — the hitbox is inset `+3, +20` from it, exactly as
`BoundBoxCtrlData` row 1 says.

Three behaviours fall out of this that a rectangle sweep does not give:

- **Ground detection is "assume falling, prove grounded."** `PlayerBGCollision`
  sets the state to falling at the top of every frame, and only the foot check
  puts it back. There is no ground sensor anywhere in the ROM; the sensor rect
  this project used before was invented and is gone.
- **Landing snaps.** `LandPlyr` does `Player_Y_Position &= $f0` — he is pulled
  down to the tile boundary, not placed at the exact contact point.
- **Walls nudge, they don't clamp.** `ImpedePlayerMove` zeroes horizontal
  speed and moves him **one pixel**, then leaves it. It does not align him to
  the tile edge, so he re-enters and gets nudged again while you hold into a
  wall.

There is also a depth test: a foot hit whose `Player_Y_Position & $0f` is `>= 5`
is too deep to stand on and is treated as a wall instead, and a head hit under
`4` is ignored outright.

And one mechanism that is easy to miss but very visible in play:
`ImpedePlayerMove` clears a bit in **`Player_CollisionBits`**, and
`ImposeFriction` opens with `and Player_CollisionBits`. So on the frame after
a wall hit, the direction you are holding reads as *not held* and no
acceleration happens at all. Running into a wall therefore stalls for a frame
before speed starts rebuilding, rather than grinding against it at full
acceleration. `PlayerBGCollision` resets the byte to `$ff` every frame.

Collision runs **after** movement, at the end of `PlayerCtrlRoutine`, which is
why `mario.py` moves first and collides second.

## Known deviations

- **Water/swimming is not implemented.** The `AreaType` branch in `X_Physics`
  always takes the land path, and jump table rows 5–6 are unused.
- **Only small Mario.** The adder tables have rows for big and crouching; only
  base `$0e` is wired up.
- **Metatile semantics are reduced to solid/not-solid.** The original also
  branches on coins, climbable tiles, jumpsprings, the axe, hidden blocks and
  pipe entry inside the same routine; none of those exist here.
- **Goombas still use a rect sweep.** Only the player got the block-collision
  treatment.
- **`Player_XSpeedAbsolute` is recomputed every frame** here, where the
  original only refreshes it at the end of `ImposeFriction`. The two agree in
  every case reachable on land, since nothing else changes `x_speed`.
- **Stomp chains are absent.** `StompTimer` also lets the original count a
  contact as a stomp while rising; without it, rising into an enemy is always
  fatal here.
- **Enemies never revive.** `HandleStompedShellE` sets a revival timer used by
  koopa shells; only the goomba's erase path off that timer is implemented.
- **Death ignores horizontal input.** The original leaves `Left_Right_Buttons`
  frozen at whatever was held when you died, which can make the corpse drift.
  Here `x_speed` is zeroed and stays zeroed.
- **Score, stomp chains, and the 1-up ladder are absent**, as are sounds beyond
  jump and death.
- The NES ran at 60.0988 Hz; this uses a flat 60.

## Controls

Arrows move, **Z** jumps (A), **X** runs (B), **H** toggles hitboxes, **R**
resets. On a controller: d-pad/stick, button 0 = A, button 2 = B.
