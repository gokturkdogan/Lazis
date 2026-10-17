"""Generate the LAZIS source icon (1024x1024 PNG) without third-party dependencies.

A dark rounded square with a glowing blue core and two rings — the Phase 1 identity mark.
Usage: python3 scripts/make_icon.py <output.png>
"""

from __future__ import annotations

import math
import struct
import sys
import zlib

SIZE = 1024


def _png(width: int, height: int, rows: list[bytes]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    raw = b"".join(b"\x00" + row for row in rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _pixel(x: int, y: int) -> tuple[int, int, int, int]:
    nx, ny = (x + 0.5) / SIZE * 2 - 1, (y + 0.5) / SIZE * 2 - 1
    # Rounded-square mask (superellipse), with a soft edge.
    se = (abs(nx) ** 5 + abs(ny) ** 5) ** (1 / 5)
    alpha = max(0.0, min(1.0, (0.92 - se) * 60))
    if alpha <= 0:
        return (0, 0, 0, 0)
    r = math.hypot(nx, ny)
    # Background: deep navy with a slight vignette.
    base = (6 + 10 * (1 - r), 10 + 16 * (1 - r), 22 + 30 * (1 - r))
    glow = 0.0
    glow += math.exp(-((r - 0.62) ** 2) / 0.00045) * 0.9  # outer ring
    glow += math.exp(-((r - 0.46) ** 2) / 0.00030) * 0.55  # inner ring
    glow += math.exp(-(r**2) / 0.035) * 1.25  # core
    glow += math.exp(-(r**2) / 0.18) * 0.25  # halo
    core_white = math.exp(-(r**2) / 0.004)
    red = base[0] + glow * 58 + core_white * 200
    green = base[1] + glow * 160 + core_white * 200
    blue = base[2] + glow * 255 + core_white * 200
    return (min(255, int(red)), min(255, int(green)), min(255, int(blue)), int(alpha * 255))


def main() -> None:
    rows = [b"".join(struct.pack("BBBB", *_pixel(x, y)) for x in range(SIZE)) for y in range(SIZE)]
    with open(sys.argv[1], "wb") as handle:
        handle.write(_png(SIZE, SIZE, rows))


if __name__ == "__main__":
    main()
