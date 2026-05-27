"""Generate a circular Solace favicon from the wordmark logo.

Takes the boxed-"S" mark from frontend/public/solace-logo.png, recolors it white,
and centers it on a brand-slate circle (color sampled from the mark itself).
Emits favicon.ico + PNG sizes + apple-touch-icon into frontend/public/.

Reproducible — re-run if the logo changes.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "frontend" / "public"
LOGO = PUB / "solace-logo.png"
# If a pre-isolated, background-removed S-mark is dropped here, use it directly
# instead of cropping the mark out of the full wordmark. Its alpha defines the
# shape; the mark is recolored white regardless of its source color.
MARK = PUB / "solace-mark.png"

SS = 4          # supersample factor for a crisp anti-aliased circle
SIZE = 512      # master icon size
MARK_FRAC = 0.60  # mark diameter as a fraction of the circle


def main() -> None:
    if MARK.exists():
        # Use the pre-isolated, background-removed mark as-is.
        mark = Image.open(MARK).convert("RGBA")
        print(f"  source: {MARK.name} (pre-isolated)")
    else:
        # Fallback: crop the S-mark out of the left ~25% of the wordmark.
        logo = Image.open(LOGO).convert("RGBA")
        w, h = logo.size
        mark = logo.crop((0, 0, int(w * 0.25), h))
        print(f"  source: {LOGO.name} (cropped wordmark)")
    bbox = mark.getbbox()
    if bbox:
        mark = mark.crop(bbox)

    # Sample the mark's solid color (average of opaque pixels) for the circle.
    opaque = [(r, g, b) for (r, g, b, a) in mark.getdata() if a > 200]
    if opaque:
        circle_rgb = tuple(sum(ch) // len(opaque) for ch in zip(*opaque))
    else:
        circle_rgb = (42, 71, 78)  # brand slate fallback (#2A474E)
    circle_color = (*circle_rgb, 255)

    big = SIZE * SS
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).ellipse((0, 0, big - 1, big - 1), fill=circle_color)

    # Recolor the mark to white using its own alpha as the shape mask.
    white = Image.new("RGBA", mark.size, (255, 255, 255, 255))
    white.putalpha(mark.split()[3])

    # Scale the mark to MARK_FRAC of the circle, preserving aspect ratio.
    target = int(big * MARK_FRAC)
    mw, mh = mark.size
    scale = target / max(mw, mh)
    nw, nh = max(1, int(mw * scale)), max(1, int(mh * scale))
    white = white.resize((nw, nh), Image.LANCZOS)
    canvas.alpha_composite(white, ((big - nw) // 2, (big - nh) // 2))

    icon = canvas.resize((SIZE, SIZE), Image.LANCZOS)

    icon.save(PUB / "favicon-512.png")
    icon.resize((180, 180), Image.LANCZOS).save(PUB / "apple-touch-icon.png")
    icon.resize((32, 32), Image.LANCZOS).save(PUB / "favicon-32.png")
    icon.save(PUB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    print(f"  circle color: #{circle_rgb[0]:02x}{circle_rgb[1]:02x}{circle_rgb[2]:02x}")
    print("  wrote: favicon.ico, favicon-512.png, favicon-32.png, apple-touch-icon.png")


if __name__ == "__main__":
    main()
