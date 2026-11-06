"""Generate the Studio Lights app icon (PNG + multi-size ICO).

Usage:  python tools/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


def rounded_background(size: int, radius: int) -> Image.Image:
    top = (16, 25, 38)
    bottom = (5, 8, 13)
    image = Image.new("RGB", (size, size), bottom)
    draw = ImageDraw.Draw(image)
    for y in range(size):
        factor = y / (size - 1)
        color = tuple(round(top[i] * (1 - factor) + bottom[i] * factor) for i in range(3))
        draw.line((0, y, size, y), fill=color)

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=255
    )
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(image, (0, 0), mask)
    return result


def add_glow(base: Image.Image, center: tuple[int, int], radius: int, color: tuple[int, int, int]) -> None:
    glow = Image.new("RGB", base.size, (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse(
        (
            center[0] - radius * 2,
            center[1] - radius * 2,
            center[0] + radius * 2,
            center[1] + radius * 2,
        ),
        fill=color,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius * 0.85))
    base.alpha_composite(glow.convert("RGBA"))


def main() -> None:
    size = 512
    scale = size / 512
    base = rounded_background(size, int(112 * scale))

    # Ambient glow behind the three "studio" lights.
    add_glow(base, (int(170 * scale), int(180 * scale)), int(74 * scale), (48, 198, 186))
    add_glow(base, (int(345 * scale), int(180 * scale)), int(74 * scale), (150, 110, 255))
    add_glow(base, (int(258 * scale), int(352 * scale)), int(64 * scale), (255, 190, 130))

    draw = ImageDraw.Draw(base)
    lights = [
        ((170, 180), 58, (79, 209, 197)),
        ((345, 180), 58, (176, 140, 255)),
        ((258, 352), 48, (255, 216, 168)),
    ]
    for (cx, cy), radius, color in lights:
        cx, cy, radius = int(cx * scale), int(cy * scale), int(radius * scale)
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=color,
            outline=(255, 255, 255, 90),
            width=max(1, int(2 * scale)),
        )

    # Thin rounded ring around the composition.
    draw.rounded_rectangle(
        (int(30 * scale), int(30 * scale), int(482 * scale), int(482 * scale)),
        radius=int(96 * scale),
        outline=(58, 78, 100, 160),
        width=max(1, int(3 * scale)),
    )

    ASSETS.mkdir(parents=True, exist_ok=True)
    png_path = ASSETS / "icon.png"
    ico_path = ASSETS / "icon.ico"
    base.save(png_path)
    base.save(
        ico_path,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Creato {png_path}")
    print(f"Creato {ico_path}")


if __name__ == "__main__":
    main()
