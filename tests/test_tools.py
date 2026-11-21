"""tools/screenshot_to_png.py: both framebuffer layouts decode to the same RGB."""

from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import screenshot_to_png as shot  # noqa: E402

W, H = shot.WIDTH, shot.HEIGHT


def rgb565(r, g, b):
    return (r >> 3) << 11 | (g >> 2) << 5 | b >> 3


class ScreenshotTests(unittest.TestCase):
    def test_rgb565_little_endian(self):
        # The badge background (13, 17, 23) as the badge stores it.
        data = struct.pack("<H", rgb565(13, 17, 23)) * (W * H)
        rows = shot.decode(data)
        self.assertEqual(len(rows), H)
        self.assertEqual(rows[0][:3], bytes((8, 16, 16)))
        self.assertEqual(len(rows[0]), W * 3)

    def test_rgba_from_simulator(self):
        data = bytes((13, 17, 23, 255)) * (W * H)
        self.assertEqual(shot.decode(data)[-1][-3:], bytes((13, 17, 23)))

    def test_rejects_other_sizes(self):
        with self.assertRaises(SystemExit):
            shot.decode(b"\x00" * 100)

    def test_png_round_trip(self):
        rows = shot.scale_rows(shot.decode(bytes((255, 0, 0, 255)) * (W * H)), 2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.png"
            shot.write_png(str(path), rows)
            data = path.read_bytes()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (W * 2, H * 2))
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        self.assertEqual(zlib.decompress(idat)[1:4], bytes((255, 0, 0)))


if __name__ == "__main__":
    unittest.main()
