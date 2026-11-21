#!/usr/bin/env python3
"""Convert a Weather app screenshot (/weather_screen.raw) to PNG.

On the badge, Settings > Screenshot writes the framebuffer as-is: 320x240
RGB565, little-endian (153,600 bytes). The badge simulator writes RGBA8888
(307,200 bytes). Both are detected by size.

Copy the file off the badge first:
    mpremote connect <port> fs cp :/weather_screen.raw .
Then:
    python3 tools/screenshot_to_png.py weather_screen.raw screen.png [--scale 2]

Uses only the standard library.
"""

import argparse
import struct
import zlib

WIDTH, HEIGHT = 320, 240


def decode(data):
    """Raw framebuffer bytes -> RGB rows (bytes of length WIDTH*3 each)."""
    if len(data) == WIDTH * HEIGHT * 2:
        values = struct.unpack("<%dH" % (WIDTH * HEIGHT), data)
        rows = []
        for y in range(HEIGHT):
            row = bytearray()
            for v in values[y * WIDTH:(y + 1) * WIDTH]:
                row += bytes((((v >> 11) & 31) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31))
            rows.append(bytes(row))
        return rows
    if len(data) == WIDTH * HEIGHT * 4:
        rows = []
        for y in range(HEIGHT):
            rgba = data[y * WIDTH * 4:(y + 1) * WIDTH * 4]
            rows.append(bytes(b for i, b in enumerate(rgba) if i % 4 != 3))
        return rows
    raise SystemExit("unexpected size %d bytes (want %d for RGB565 or %d for RGBA)"
                     % (len(data), WIDTH * HEIGHT * 2, WIDTH * HEIGHT * 4))


def scale_rows(rows, factor):
    out = []
    for row in rows:
        wide = b"".join(row[i:i + 3] * factor for i in range(0, len(row), 3))
        out.extend([wide] * factor)
    return out


def write_png(path, rows):
    height, width = len(rows), len(rows[0]) // 3

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + row for row in rows)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        f.write(chunk(b"IEND", b""))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw")
    parser.add_argument("png")
    parser.add_argument("--scale", type=int, default=1, choices=(1, 2, 3, 4))
    args = parser.parse_args()
    with open(args.raw, "rb") as f:
        rows = decode(f.read())
    write_png(args.png, scale_rows(rows, args.scale) if args.scale > 1 else rows)
    print("wrote", args.png)


if __name__ == "__main__":
    main()
