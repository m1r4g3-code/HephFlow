"""Generate HephFlow tray icons into assets/. Run once: `python generate_icons.py`.

Produces:
  assets/icon_idle.png / .ico  - grey microphone (idle)
  assets/icon_recording.png    - red microphone (recording)
  assets/icon_error.png        - yellow warning triangle (error)

Kept out of the shipped build; assets/ is bundled instead.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

ASSETS = "assets"
GREY = (140, 140, 140, 255)
RED = (220, 50, 50, 255)
YELLOW = (255, 200, 0, 255)
BLACK = (0, 0, 0, 255)


def _draw_mic(draw: ImageDraw.ImageDraw, size: int, color) -> None:
    """Draw a simple microphone centered in a size x size box."""
    cx = size / 2
    line_w = max(1, round(size * 0.06))

    # Capsule body.
    bw = size * 0.34
    bh = size * 0.46
    bx0 = cx - bw / 2
    by0 = size * 0.10
    bx1 = cx + bw / 2
    by1 = by0 + bh
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=bw / 2, fill=color)

    # Cradle arc under the body.
    r = size * 0.30
    cyc = by0 + bh * 0.55
    draw.arc([cx - r, cyc - r, cx + r, cyc + r], start=20, end=160,
             fill=color, width=line_w)

    # Stem + base.
    stem_top = cyc + r
    base_y = size * 0.92
    draw.line([cx, stem_top, cx, base_y], fill=color, width=line_w)
    base_half = size * 0.18
    draw.line([cx - base_half, base_y, cx + base_half, base_y],
              fill=color, width=line_w)


def _mic_image(size: int, color) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _draw_mic(ImageDraw.Draw(img), size, color)
    return img


def _warning_image(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = size * 0.08
    d.polygon([(size / 2, m), (size - m, size - m), (m, size - m)],
              fill=YELLOW)
    # Exclamation mark drawn as a bar + dot (text is illegible at 16px).
    bar_w = max(1, round(size * 0.08))
    top = size * 0.34
    bot = size * 0.66
    cx = size / 2
    d.line([cx, top, cx, bot], fill=BLACK, width=bar_w)
    dot_r = max(1, round(size * 0.05))
    dy = size * 0.78
    d.ellipse([cx - dot_r, dy - dot_r, cx + dot_r, dy + dot_r], fill=BLACK)
    return img


def main() -> None:
    os.makedirs(ASSETS, exist_ok=True)

    # Idle mic: PNG (256) + multi-size ICO for the exe / tray.
    idle_256 = _mic_image(256, GREY)
    idle_256.save(os.path.join(ASSETS, "icon_idle.png"))
    ico_sizes = [16, 32, 48, 64, 128, 256]
    ico_imgs = [
        idle_256.resize((s, s), Image.Resampling.LANCZOS) for s in ico_sizes
    ]
    ico_imgs[0].save(
        os.path.join(ASSETS, "icon_idle.ico"),
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=ico_imgs[1:],
    )

    # Recording + error states (PNG; tray scales as needed).
    _mic_image(256, RED).save(os.path.join(ASSETS, "icon_recording.png"))
    _warning_image(256).save(os.path.join(ASSETS, "icon_error.png"))

    print(f"Icons written to {os.path.abspath(ASSETS)}")


if __name__ == "__main__":
    main()
