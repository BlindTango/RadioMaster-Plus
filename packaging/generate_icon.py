"""One-off script that draws RadioMaster+'s app icon with PIL and saves it
to resources/icon.ico (multi-resolution) and resources/icon.png (used by
the splash screen). Not part of the runtime app -- run manually whenever
the icon design needs to change:

    python packaging/generate_icon.py

Design: a circular badge combining the three things the app actually
does -- broadcast (antenna + radio waves), playback (a play triangle),
and downloading (a tray with a down arrow) -- rather than a generic
music-note icon that could be any media player.
"""

import math
import os

from PIL import Image, ImageDraw

SIZE = 512
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "resources")

BG_TOP = (30, 64, 128)      # deep blue
BG_BOTTOM = (12, 28, 56)    # near-black navy
ACCENT = (64, 176, 255)     # bright cyan-blue (waves, arrow)
PLAY_COLOR = (255, 255, 255)


def _radial_background(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size / 2, size / 2
    radius = size / 2 - size * 0.02
    for y in range(size):
        for x in range(size):
            dx, dy = x - cx, y - cy
            if dx * dx + dy * dy <= radius * radius:
                t = (y / size)
                r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
                g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
                b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
                img.putpixel((x, y), (r, g, b, 255))
    return img


def _draw_broadcast_waves(draw: ImageDraw.ImageDraw, cx: float, cy: float) -> None:
    # Three concentric arcs above the antenna tip, like a "on air" signal.
    for i, radius in enumerate((70, 100, 130)):
        width = max(4, 10 - i * 2)
        alpha = 255 - i * 40
        draw.arc(
            [cx - radius, cy - radius - 40, cx + radius, cy + radius - 40],
            start=210, end=330, fill=ACCENT + (alpha,) if len(ACCENT) == 3 else ACCENT,
            width=width,
        )


def _draw_antenna(draw: ImageDraw.ImageDraw, cx: float, cy: float) -> None:
    tip_y = cy - 150
    base_y = cy - 40
    draw.line([(cx, tip_y), (cx, base_y)], fill=PLAY_COLOR, width=8)
    draw.line([(cx, tip_y), (cx - 26, base_y)], fill=PLAY_COLOR, width=6)
    draw.line([(cx, tip_y), (cx + 26, base_y)], fill=PLAY_COLOR, width=6)
    draw.ellipse([cx - 8, tip_y - 8, cx + 8, tip_y + 8], fill=ACCENT)


def _draw_play_triangle(draw: ImageDraw.ImageDraw, cx: float, cy: float) -> None:
    r = 60
    points = [
        (cx - r * 0.6, cy - r),
        (cx - r * 0.6, cy + r),
        (cx + r * 0.9, cy),
    ]
    draw.polygon(points, fill=PLAY_COLOR)


def _draw_download_arrow(draw: ImageDraw.ImageDraw, cx: float, cy: float) -> None:
    top = cy + 90
    bottom = cy + 150
    draw.line([(cx, top), (cx, bottom)], fill=ACCENT, width=14)
    arrow_r = 22
    draw.polygon(
        [
            (cx - arrow_r, bottom - arrow_r),
            (cx + arrow_r, bottom - arrow_r),
            (cx, bottom + 6),
        ],
        fill=ACCENT,
    )
    # Tray under the arrow.
    draw.line([(cx - 50, bottom + 22), (cx + 50, bottom + 22)], fill=ACCENT, width=10)


def build() -> Image.Image:
    img = _radial_background(SIZE)
    draw = ImageDraw.Draw(img)
    cx, cy = SIZE / 2, SIZE / 2 + 10

    _draw_broadcast_waves(draw, cx, cy)
    _draw_antenna(draw, cx, cy)
    _draw_play_triangle(draw, cx, cy)
    _draw_download_arrow(draw, cx, cy)

    return img


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    img = build()

    png_path = os.path.join(OUT_DIR, "icon.png")
    img.save(png_path)

    ico_path = os.path.join(OUT_DIR, "icon.ico")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(ico_path, format="ICO", sizes=sizes)

    print(f"Wrote {png_path}")
    print(f"Wrote {ico_path}")


if __name__ == "__main__":
    main()
