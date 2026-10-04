# /// script
# requires-python = ">=3.12"
# dependencies = ["pillow"]
# ///
"""Draw the PNG icons that Android needs to install the site as an app.

    uv run scripts/make_icons.py

Writes icon-192.png, icon-512.png and icon-maskable-512.png next to icon.svg,
with the same shape. The maskable one fills the square and keeps the line in
the middle, as Android cuts it to a circle or another shape. Run it again when
icon.svg changes; the results are committed.
"""

from pathlib import Path

from PIL import Image, ImageDraw

STATIC = Path(__file__).parent.parent / "src" / "garmin_analyzer" / "web" / "static"

# From icon.svg, on its grid of 32 by 32.
GRID = 32
BLUE = "#1f6feb"
CORNER = 7
LINE = [(4, 17), (10, 17), (13, 9), (18, 23), (21, 17), (28, 17)]
LINE_WIDTH = 2.5

# Drawn larger and scaled down, which smooths the edges.
OVERSAMPLE = 4


def draw(size: int, maskable: bool) -> Image.Image:
    side = size * OVERSAMPLE
    unit = side / GRID
    image = Image.new("RGBA", (side, side), BLUE if maskable else (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    if not maskable:
        pen.rounded_rectangle((0, 0, side - 1, side - 1), radius=CORNER * unit, fill=BLUE)

    # Android shows only the middle of a maskable icon for certain.
    shrink = 0.8 if maskable else 1.0
    middle = GRID / 2
    points = [
        ((middle + (x - middle) * shrink) * unit, (middle + (y - middle) * shrink) * unit)
        for x, y in LINE
    ]
    width = round(LINE_WIDTH * shrink * unit)
    pen.line(points, fill="white", width=width, joint="curve")
    for x, y in points:
        pen.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill="white")
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    for name, size, maskable in [
        ("icon-192.png", 192, False),
        ("icon-512.png", 512, False),
        ("icon-maskable-512.png", 512, True),
    ]:
        draw(size, maskable).save(STATIC / name, optimize=True)
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
