from PIL import Image
import os

# Load image
im = Image.open("characters_sprites.gif").convert("RGBA")
pixels = im.load()
width, height = im.size

base_folder = "sprites"
super_folder = os.path.join(base_folder, "super_mario")
mario_folder = os.path.join(base_folder, "mario")

os.makedirs(super_folder, exist_ok=True)
os.makedirs(mario_folder, exist_ok=True)


def row_has_pixels(y):
    for x in range(width):
        if pixels[x, y][3] > 0:
            return True
    return False


# ---- Find first row ----
y = 0
while y < height and not row_has_pixels(y):
    y += 1

row1_top = y

while y < height and row_has_pixels(y):
    y += 1

row1_bottom = y

# ---- Skip gap ----
while y < height and not row_has_pixels(y):
    y += 1

# ---- Find second row ----
row2_top = y

while y < height and row_has_pixels(y):
    y += 1

row2_bottom = y


def extract_row(row_top, row_bottom, output_folder):
    sprite_regions = []
    in_sprite = False
    start_x = 0

    # Detect horizontal sprite bounds
    for x in range(width):
        column_has_pixel = False
        for y in range(row_top, row_bottom):
            if pixels[x, y][3] > 0:
                column_has_pixel = True
                break

        if column_has_pixel and not in_sprite:
            in_sprite = True
            start_x = x

        elif not column_has_pixel and in_sprite:
            sprite_regions.append((start_x, x))
            in_sprite = False

    if in_sprite:
        sprite_regions.append((start_x, width))

    # Save sprites
    for i, (start, end) in enumerate(sprite_regions):
        left = max(start - 1, 0)
        right = min(end + 1, width)

        # Clamp padding strictly to row
        top = max(row_top - 1, 0)
        bottom = min(row_bottom + 1, height)

        sprite = im.crop((left, top, right, bottom))
        sprite.save(os.path.join(output_folder, f"frame_{i}.png"))

    print(f"Saved {len(sprite_regions)} sprites to {output_folder}")


# Extract rows
extract_row(row1_top, row1_bottom, super_folder)
extract_row(row2_top, row2_bottom, mario_folder)
