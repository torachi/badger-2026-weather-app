#!/usr/bin/env python3
"""Build the weather app's Font Awesome icon font and menu icon.

Downloads a pinned Font Awesome Free release from the npm registry, reads the
solid SVG icons listed in GLYPHS, assigns each one a printable ASCII character,
and encodes their outlines as an Alright Font (.af) that the badge's vector
text renderer loads with font.load(). It also rasterises the menu icon
(icon.png).

Licensing: Font Awesome Free licenses its SVG icons under CC BY 4.0 but its
web/desktop font files under SIL OFL 1.1 (Reserved Font Name "Font Awesome").
This tool deliberately reads only the SVG files, never the font files, so the
output is an adaptation of CC BY 4.0 icons. ICONS_LICENSE.txt carries the
attribution and lists the changes made.

The badge renderer scales glyph coordinates by font_size / 128 and places
y = 0 on the baseline, font_size pixels below the text origin. Every icon is
therefore centred in a 127-unit square sitting on the baseline (x 0..127,
y -127..0, y pointing down) with an advance of 128, so
screen.text(icon, x, y, size) fills a size x size square whose top-left corner
is (x, y), and screen.measure_text() reports (size, size). The header sets
flag 1 (16-bit path point counts), matching the fonts in badge/assets/fonts.


Usage:  python3 tools/build_weather_icons.py [--preview preview.png]
Requires: fonttools, brotli, Pillow.
"""

import argparse
import hashlib
import math
import io
import json
import struct
import tarfile
from pathlib import Path
from urllib.request import urlopen

import xml.etree.ElementTree as ET

from fontTools.pens.basePen import BasePen
from fontTools.svgLib.path import parse_path
from PIL import Image, ImageDraw

FA_VERSION = "7.3.1"
FA_TARBALL = f"https://registry.npmjs.org/@fortawesome/fontawesome-free/-/fontawesome-free-{FA_VERSION}.tgz"
FA_SHA256 = "ca4e32843bd81711894385c2466fb19c55cfd32ef3c58830b2d1df7bd42e6571"
FA_SVG_DIR = "package/svgs/solid/"

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "weather"

# ASCII character -> Font Awesome icon name. Keep in sync with icons.py.
GLYPHS = {
    "a": "sun",
    "b": "moon",
    "c": "cloud",
    "d": "cloud-sun",
    "e": "cloud-moon",
    "f": "cloud-rain",
    "g": "cloud-showers-heavy",
    "h": "cloud-sun-rain",
    "i": "cloud-moon-rain",
    "j": "cloud-bolt",
    "k": "snowflake",
    "l": "smog",
    "m": "wind",
    "n": "droplet",
    "o": "umbrella",
    "p": "location-dot",
    "q": "arrows-rotate",
    "r": "gear",
    "s": "triangle-exclamation",
    "t": "wifi",
    "u": "temperature-half",
}

BOX = 127.0          # icon square, in font units (128 units = font_size)
FLATNESS = 0.4       # max curve deviation in font units
ICON_PNG_GLYPH = "d" # cloud-sun for the launcher tile
ICON_PNG_SIZE = 24


class FlattenPen(BasePen):
    """Collects contours as polylines, flattening curves adaptively."""

    def __init__(self, glyphset, tolerance):
        super().__init__(glyphset)
        self.tolerance = tolerance
        self.contours = []
        self.current = None

    def _moveTo(self, pt):
        self.current = [pt]

    def _lineTo(self, pt):
        self.current.append(pt)

    def _segments(self, degree, second_difference):
        # Wang's formula: segments needed so the chord stays within tolerance.
        n = math.sqrt(degree * (degree - 1) / 8 * second_difference / self.tolerance)
        return max(1, min(32, math.ceil(n)))

    def _curveToOne(self, p1, p2, p3):
        p0 = self.current[-1]
        dd = max(_norm(p0, p1, p2), _norm(p1, p2, p3))
        n = self._segments(3, dd)
        for i in range(1, n + 1):
            t = i / n
            mt = 1 - t
            x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
            y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
            self.current.append((x, y))

    def _qCurveToOne(self, p1, p2):
        p0 = self.current[-1]
        n = self._segments(2, _norm(p0, p1, p2))
        for i in range(1, n + 1):
            t = i / n
            mt = 1 - t
            x = mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0]
            y = mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]
            self.current.append((x, y))

    def _closePath(self):
        if self.current and len(self.current) > 2:
            if self.current[0] == self.current[-1]:
                self.current.pop()
            self.contours.append(self.current)
        self.current = None

    _endPath = _closePath


def _norm(a, b, c):
    """Magnitude of the second difference a - 2b + c."""
    return math.hypot(a[0] - 2 * b[0] + c[0], a[1] - 2 * b[1] + c[1])


def _drop_collinear(points):
    """Remove points that lie exactly on the line between their neighbours."""
    i = 0
    while len(points) > 3 and i < len(points):
        a, p, b = points[i - 1], points[i], points[(i + 1) % len(points)]
        if (p[0] - a[0]) * (b[1] - a[1]) == (p[1] - a[1]) * (b[0] - a[0]):
            del points[i]
            i = max(0, i - 1)
        else:
            i += 1
    return points


def _dedupe(points):
    out = []
    for p in points:
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def download_svgs(names):
    """{icon name: SVG text} for the requested solid icons, plus metadata and licence."""
    with urlopen(FA_TARBALL, timeout=60) as response:
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if FA_SHA256 and digest != FA_SHA256:
        raise SystemExit(f"Font Awesome tarball checksum mismatch: {digest}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        svgs = {name: tar.extractfile(FA_SVG_DIR + name + ".svg").read().decode("utf-8") for name in names}
        meta = json.load(tar.extractfile("package/metadata/icon-families.json"))
        license_text = tar.extractfile("package/LICENSE.txt").read().decode("utf-8")
    return svgs, meta, license_text, digest


def _svg_paths(svg_text):
    root = ET.fromstring(svg_text)
    paths = [el.get("d") for el in root.iter() if el.tag.endswith("path") and el.get("d")]
    if not paths:
        raise SystemExit("SVG has no path data")
    return paths


def _draw(paths, pen):
    for d in paths:
        parse_path(d, pen)


def glyph_polylines(svg_text):
    """Contours of one SVG icon, centred in the icon square on the baseline.

    SVG coordinates already point down, matching the badge renderer.
    """
    paths = _svg_paths(svg_text)
    probe = FlattenPen(None, 4.0)
    _draw(paths, probe)
    xs = [p[0] for contour in probe.contours for p in contour]
    ys = [p[1] for contour in probe.contours for p in contour]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    scale = (BOX - 1) / max(width, height)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

    pen = FlattenPen(None, FLATNESS / scale)
    _draw(paths, pen)
    contours = []
    for contour in pen.contours:
        points = _drop_collinear(_dedupe([
            (round((x - cx) * scale + BOX / 2), round((y - cy) * scale - BOX / 2)) for x, y in contour]))
        if len(points) > 2:
            contours.append(points)
    return contours


def encode_af(glyphs):
    """glyphs: list of (codepoint, contours) -> Alright Font bytes."""
    glyphs = sorted(glyphs, key=lambda g: g[0])
    paths = sum(len(c) for _, c in glyphs)
    points = sum(len(p) for _, c in glyphs for p in c)
    if points > 65535 or paths > 65535:
        raise SystemExit("Icon font too large for the .af header")
    out = bytearray(b"af!?")
    out += struct.pack(">HHHH", 1, len(glyphs), paths, points)
    for codepoint, contours in glyphs:
        out += struct.pack(">HbbBBBB", codepoint, 0, 0, int(BOX), int(BOX), 128, len(contours))
    for _, contours in glyphs:
        for contour in contours:
            out += struct.pack(">H", len(contour))
    for _, contours in glyphs:
        for contour in contours:
            for x, y in contour:
                out += struct.pack(">bb", max(0, min(127, x)), max(-127, min(0, y)))
    return bytes(out)


def rasterise(contours, size, fill=(255, 255, 255, 255), supersample=8):
    from PIL import ImageChops

    big = size * supersample
    mask = Image.new("1", (big, big), 0)
    # Even-odd (XOR) fill reproduces holes such as the cutouts in sun and gear.
    for contour in contours:
        layer = Image.new("1", (big, big), 0)
        ImageDraw.Draw(layer).polygon(
            [(x / BOX * big, (y + BOX) / BOX * big) for x, y in contour], fill=1)
        mask = ImageChops.logical_xor(mask, layer)
    mask = mask.convert("L").resize((size, size), Image.LANCZOS)
    img = Image.new("RGBA", (size, size), fill)
    img.putalpha(mask)
    return img


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preview", help="write a contact sheet PNG of every glyph")
    parser.add_argument("--print-sha", action="store_true", help="print the tarball SHA-256 and exit")
    args = parser.parse_args()

    svgs, meta, license_text, digest = download_svgs(GLYPHS.values())
    if args.print_sha:
        print(digest)
        return

    glyphs = []
    rendered = {}
    for char, name in GLYPHS.items():
        info = meta.get(name)
        free = info and any(s["style"] == "solid" for s in info.get("familyStylesByLicense", {}).get("free", []))
        if not free:
            raise SystemExit(f"{name} is not a Font Awesome Free solid icon")
        contours = glyph_polylines(svgs[name])
        glyphs.append((ord(char), contours))
        rendered[char] = contours

    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = encode_af(glyphs)
    (OUTPUT / "weather-icons.af").write_bytes(data)

    icon = rasterise(rendered[ICON_PNG_GLYPH], ICON_PNG_SIZE, fill=(255, 210, 90, 255))
    icon.save(OUTPUT / "icon.png")

    (OUTPUT / "ICONS_LICENSE.txt").write_text(
        "Icons in weather-icons.af and icon.png\n"
        "======================================\n\n"
        f"Source: Font Awesome Free {FA_VERSION} by Fonticons, Inc. - https://fontawesome.com\n"
        "Licence: Creative Commons Attribution 4.0 International (CC BY 4.0)\n"
        "         https://creativecommons.org/licenses/by/4.0/\n"
        "Icons used (solid style, SVG files only): " + ", ".join(GLYPHS.values()) + ".\n\n"
        "Changes made by tools/build_weather_icons.py: the SVG outlines were\n"
        "flattened into polylines, scaled into a 127-unit square, remapped to ASCII\n"
        "characters and encoded in the Alright Font (.af) format; icon.png is the\n"
        "cloud-sun icon rasterised at 24x24 and coloured. No Font Awesome font file\n"
        "(SIL OFL 1.1) was used, and these files are not Font Awesome fonts.\n"
        "Font Awesome does not endorse this project.\n\n"
        f"Source tarball: {FA_TARBALL}\n"
        f"SHA-256: {digest}\n\n"
        "The upstream licence notice from that release follows for reference; of it,\n"
        "the \"Icons: CC BY 4.0\" section applies to these files.\n\n"
        f"{license_text}",
        encoding="utf-8")

    points = sum(len(p) for _, c in glyphs for p in c)
    print(f"weather-icons.af: {len(data)} bytes, {len(glyphs)} glyphs, {points} points")

    if args.preview:
        cell = 64
        sheet = Image.new("RGBA", (cell * 8, cell * ((len(rendered) + 7) // 8)), (16, 20, 26, 255))
        for i, (char, contours) in enumerate(rendered.items()):
            img = rasterise(contours, cell - 8)
            sheet.alpha_composite(img, ((i % 8) * cell + 4, (i // 8) * cell + 4))
            ImageDraw.Draw(sheet).text(((i % 8) * cell + 2, (i // 8) * cell + 1), char, fill=(255, 120, 120, 255))
        sheet.save(args.preview)
        print("preview:", args.preview)


if __name__ == "__main__":
    main()
