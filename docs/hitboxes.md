# Hitboxes

Reference art and the numbers taken off it. All sizes are **unscaled game
pixels** — multiply by `SCALE` for screen pixels.

- `mario-hitbox-reference.png` — Mario, standing and mid-jump.
- `enemy-hitbox-reference.png` — a sheet of enemies, every hitbox filled solid
  green. Drawn at 3x, so every box in it is a multiple of 3 screen pixels.

## Two different boxes

Enemies need two, and conflating them causes bugs:

| box | used for | size |
|---|---|---|
| collision box | tiles: floors, pipes, walls | the full sprite cell (16x16) |
| contact box | Mario touching / stomping the enemy | the small green box in the reference |

The green boxes in the reference sheet are **contact** boxes. Several of them
float clear of the ground (the goomba's sits 4px above its feet), so using one
for tile collision would sink the enemy into the floor.

Mario is the exception: his green box is flush with his feet, so a single box
serves both jobs. That is why `Mario` has one `rect()` and `Goomba` has both
`rect()` and `hitbox()`.

## Measured values

Both boxes are anchored to the **bottom** of the sprite and stay a fixed size
across every pose — the reference draws the identical rectangle on a standing
and a mid-jump Mario, so flung-out arms and a raised knee fall outside it.

| entity | box | size | offset into the 16-wide cell | where |
|---|---|---|---|---|
| Mario (small) | contact + collision | 11 x 13 | x +0.5, bottom-flush | `Mario.HITBOX_WIDTH` / `HITBOX_HEIGHT` |
| Goomba | collision | 16 x 16 | 0, 0 | `Goomba.width` / `height` |
| Goomba | contact | 11 x 7 | x +3, y +5 | `Goomba.HITBOX_*` |

Mario's 11 x 13 was cross-checked two ways: measured off the standing and
jumping figures in `mario-hitbox-reference.png`, and read pixel-exact off the
small underground Mario in the enemy sheet (bottom row, left of centre), which
gives 11 x 13 with the top edge 3px below the cap and the bottom flush with
the ground.

## Not yet implemented

The enemy sheet covers more than we have sprites for. Sizes below are measured
straight from the sheet; the **names are unverified guesses** except where
noted, since the green fill hides most of the sprite. Re-check the identity
against the image before wiring any of these up.

| size | count in sheet | plausibly |
|---|---|---|
| 11 x 7 | 8 | goomba (confirmed, 2 of them), plus flat/wide swimmers — cheep cheep, blooper |
| 13 x 13 | 6 | koopa troopa / paratroopa / beetle-shaped enemies |
| 11 x 13 | 1 | Mario (confirmed) |
| 13 x 25 | 1 | a tall enemy — hammer bro or similar |
| 9 x 25 | 1 | piranha plant (tall, emerges from a pipe) |
| 9 x 9 | 1 | small projectile or the axe |
| 5 x 5 | 1 | fireball |
| two overlapping | 1 | a multi-box enemy |

## How to re-measure

The sheet's background is flat NES palette, so boxes and sprites separate
cleanly by colour:

- hitbox green: `(32, 248, 40)`
- backgrounds: sky `(92, 148, 252)`, underwater `(32, 56, 236)`, underground
  `(0, 0, 0)`

Find connected runs of the green, divide the bounding box by 3 for game
pixels, then align the sprite cell by IoU-matching a sprite from
`sprites/` against the non-background mask — that is how the goomba and Mario
entries above were pinned down rather than guessed.

## Seeing them in game

Press **H** while playing (`main.py`) to toggle the outlines. Green is the
contact box, grey is the tile-collision box where it differs.
