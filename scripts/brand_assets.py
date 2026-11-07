#!/usr/bin/env python3
"""Every LAZIS logo variant, generated from the owner's one source image.

    python3 scripts/brand_assets.py        # needs Pillow; macOS iconutil for the .icns

Source: assets/brand/lazis-logo-source.png (the owner's logo: the neural sphere and "LAZIS").
Writes:
  apps/desktop/src-tauri/icons/        app icon in every size Tauri uses (macOS rounded square)
  apps/desktop/src-tauri/icons/tray-template.rgba
                                       menu bar icon: the logo's shape as a 44x44 template
                                       (black + alpha), so macOS tints it for light and dark bars
  apps/desktop/ui/src/assets/brand/    in-app logo (full, with the name) and emblem (sphere
                                       only, for small places), black turned into transparency
  apps/desktop/ui/public/favicon.png   the emblem for the browser tab in development
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets/brand/lazis-logo-source.png"
ICONS = ROOT / "apps/desktop/src-tauri/icons"
UI = ROOT / "apps/desktop/ui/src/assets/brand"
PUBLIC = ROOT / "apps/desktop/ui/public"

# Measured on the source (1254 x 1254): sphere and rings y 109-829, x 135-1150; name below.
EMBLEM_BOX = (120, 95, 1165, 845)
TRAY = 44  # 22 pt @2x, as before


def black_to_alpha(img: Image.Image, floor: int = 14) -> Image.Image:
    """Light on black -> the same light on transparency (un-premultiplied), for any background."""
    rgb = img.convert("RGB")
    r, g, b = rgb.split()
    m = ImageChops.lighter(ImageChops.lighter(r, g), b)
    alpha = m.point(lambda v: 0 if v <= floor else min(255, round((v - floor) * 255 / (255 - floor))))
    out = Image.new("RGBA", rgb.size)
    src, a = rgb.load(), alpha.load()
    dst = out.load()
    for y in range(rgb.height):
        for x in range(rgb.width):
            av = a[x, y]
            if av == 0:
                dst[x, y] = (0, 0, 0, 0)
                continue
            pr, pg, pb = src[x, y]
            k = 255 / max(av, 1)
            dst[x, y] = (min(255, round(pr * k)), min(255, round(pg * k)), min(255, round(pb * k)), av)
    return out


def square(img: Image.Image, fill: tuple[int, ...]) -> Image.Image:
    side = max(img.size)
    canvas = Image.new(img.mode, (side, side), fill)
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def app_icon(src: Image.Image) -> Image.Image:
    """macOS app icon: the logo in a rounded square (824 of 1024, radius 185, Apple's grid)."""
    size, body, radius = 1024, 824, 185
    off = (size - body) // 2
    logo = src.convert("RGB").resize((body, body), Image.Resampling.LANCZOS)
    mask = Image.new("L", (body * 4, body * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, body * 4 - 1, body * 4 - 1), radius * 4, fill=255)
    mask = mask.resize((body, body), Image.Resampling.LANCZOS)
    shadow = Image.new("L", (size, size), 0)
    shadow.paste(mask.point(lambda v: v * 0.45), (off, off + 10))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.putalpha(shadow)
    icon.paste(logo, (off, off), mask)
    return icon


def tray_template() -> bytes:
    """The logo as a menu bar pictogram: the sphere, its ring crossing in front, and a few
    connected nodes inside, in the logo's proportions. The network texture of the full logo
    turns to noise at 22 pt, so the shape is drawn in clean lines. Black + alpha (a template
    image): macOS colours it to fit light and dark menu bars."""
    k = 8  # drawn 8x larger, then reduced (smooth edges)
    n = TRAY * k
    c = n / 2
    r = n * 0.3
    w = round(n * 0.045)

    def ring(width: int) -> Image.Image:
        layer = Image.new("L", (n, n), 0)
        ImageDraw.Draw(layer).ellipse((c - n * 0.47, c - n * 0.11, c + n * 0.47, c + n * 0.11), outline=255, width=width)
        return layer.rotate(13, resample=Image.Resampling.BICUBIC, center=(c, c))

    sphere = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(sphere)
    d.ellipse((c - r, c - r, c + r, c + r), outline=255, width=w)
    # A small network above the ring's front arc: a bright hub (the logo's centre) joined to
    # three nodes that are also joined to each other. Asymmetric, so it never reads as a face.
    hub = (c - n * 0.01, c - n * 0.02)
    others = [(c - n * 0.16, c - n * 0.09), (c + n * 0.05, c - n * 0.19), (c + n * 0.17, c - n * 0.05)]
    for p in others:
        d.line((hub, p), fill=255, width=round(w * 0.5))
    for a, b in [(0, 1), (1, 2)]:
        d.line((others[a], others[b]), fill=255, width=round(w * 0.5))
    for x, y in others:
        d.ellipse((x - w * 0.75, y - w * 0.75, x + w * 0.75, y + w * 0.75), fill=255)
    d.ellipse((hub[0] - w * 1.25, hub[1] - w * 1.25, hub[0] + w * 1.25, hub[1] + w * 1.25), fill=255)
    # The ring passes in front of the lower half and behind the upper half of the sphere.
    disc = Image.new("L", (n, n), 0)
    ImageDraw.Draw(disc).ellipse((c - r + w, c - r + w, c + r - w, c + r - w), fill=255)
    upper = Image.new("L", (n, n), 0)
    ImageDraw.Draw(upper).rectangle((0, 0, n, c), fill=255)
    behind = ImageChops.multiply(disc, upper)
    front = ring(w)
    front = ImageChops.subtract(front, behind)
    gap = ImageChops.subtract(ring(w * 3), upper)
    sphere = ImageChops.subtract(sphere, gap)
    art = ImageChops.lighter(sphere, front)
    alpha = art.resize((TRAY, TRAY), Image.Resampling.LANCZOS)
    out = bytearray()
    for v in alpha.getdata():
        out += bytes((0, 0, 0, v))
    return bytes(out)


def main() -> None:
    src = Image.open(SOURCE)
    assert src.size == (1254, 1254), src.size

    # App icon set (same files and sizes as before).
    icon = app_icon(src)
    icon.save(ICONS / "source.png")
    for name, px in [("32x32.png", 32), ("64x64.png", 64), ("128x128.png", 128), ("128x128@2x.png", 256), ("icon.png", 512)]:
        icon.resize((px, px), Image.Resampling.LANCZOS).save(ICONS / name)
    icon.save(ICONS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for px in (16, 32, 128, 256, 512):
            icon.resize((px, px), Image.Resampling.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
            icon.resize((px * 2, px * 2), Image.Resampling.LANCZOS).save(iconset / f"icon_{px}x{px}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ICONS / "icon.icns")], check=True)

    # Menu bar template.
    emblem_src = square(src.convert("RGB").crop(EMBLEM_BOX), (0, 4, 9))
    (ICONS / "tray-template.rgba").write_bytes(tray_template())

    # In-app logo and emblem, transparent.
    UI.mkdir(parents=True, exist_ok=True)
    full = black_to_alpha(src.resize((560, 560), Image.Resampling.LANCZOS))
    full.save(UI / "lazis-logo.png", optimize=True)
    emblem = black_to_alpha(emblem_src.resize((192, 192), Image.Resampling.LANCZOS))
    emblem.save(UI / "lazis-emblem.png", optimize=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    emblem.resize((64, 64), Image.Resampling.LANCZOS).save(PUBLIC / "favicon.png", optimize=True)
    print("written:", *(p.relative_to(ROOT) for p in sorted([*ICONS.iterdir(), *UI.iterdir(), PUBLIC / "favicon.png"])), sep="\n  ")


if __name__ == "__main__":
    shutil.which("iconutil") or exit("iconutil (macOS) is needed for icon.icns")
    main()
