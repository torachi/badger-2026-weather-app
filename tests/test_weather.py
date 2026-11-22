"""Weather app: units, calendar maths, API parsing and the time cursor.

Fixtures in tests/fixtures/weather were captured on a Universe 2026 badge on
2026-11-21 (identifying fields of the IP-location response replaced).
open_meteo_7.json answers one request in the app's order, Here first and then
the six cities of cities.py (Tokyo ... San Francisco); open_meteo_6.json is the
same without Here.
"""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "weather"
FIXTURES = Path(__file__).resolve().parent / "fixtures/weather"
sys.path.insert(0, str(APP))

import cities  # noqa: E402
import clock  # noqa: E402
import forecast  # noqa: E402
import geo  # noqa: E402
import net  # noqa: E402
import units  # noqa: E402
import wmo  # noqa: E402


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


OM7 = load("open_meteo_7.json")
# The badge fetched at 22:39:56 JST (13:39:56 UTC) on 2026-11-21.
FETCHED = 1795268396


class UnitTests(unittest.TestCase):
    def test_temperature(self):
        self.assertEqual(units.fmt_temp(7.9, "C"), "8°")
        self.assertEqual(units.fmt_temp(7.9, "C", with_unit=True), "8°C")
        self.assertEqual(units.fmt_temp(0, "F"), "32°")
        self.assertEqual(units.fmt_temp(-40, "F"), "-40°")
        self.assertEqual(units.fmt_temp(-0.5, "C"), "-1°")
        self.assertEqual(units.fmt_temp(0.5, "C"), "1°")
        self.assertEqual(units.fmt_temp(None, "C"), "--")

    def test_wind(self):
        self.assertEqual(units.fmt_wind(3.6, "m/s"), "1.0 m/s")
        self.assertEqual(units.fmt_wind(36, "m/s"), "10 m/s")
        self.assertEqual(units.fmt_wind(10, "km/h"), "10 km/h")
        self.assertEqual(units.fmt_wind(16.09344, "mph"), "10 mph")
        self.assertEqual(units.fmt_wind(1.852 * 5, "kn"), "5.0 kn")
        self.assertEqual(units.fmt_wind(None, "kn"), "--")

    def test_rain_percent_and_clock(self):
        self.assertEqual(units.fmt_rain(4.8, "mm"), "4.8 mm")
        self.assertEqual(units.fmt_rain(25.4, "in"), "1.00 in")
        self.assertEqual(units.fmt_percent(88), "88%")
        self.assertEqual(units.fmt_clock(0, 5, "24h"), "00:05")
        self.assertEqual(units.fmt_clock(0, 5, "12h"), "12:05am")
        self.assertEqual(units.fmt_clock(13, 0, "12h"), "1:00pm")
        self.assertEqual(units.fmt_hour(0, 0, "12h"), "12:00")
        self.assertEqual(units.fmt_hour(13, 22, "12h"), "1:22")
        self.assertEqual(units.fmt_hour(1, 22, "24h"), "01:22")
        self.assertEqual(units.fmt_hour(23, 0, "24h"), "23:00")


class ClockTests(unittest.TestCase):
    def test_civil_matches_datetime(self):
        for epoch in (0, 951782400, 1795268396, 1795186800, 4102444800, 1709164800):
            for offset in (0, 32400, -28800, 19800):
                dt = datetime.fromtimestamp(epoch, timezone.utc) + timedelta(seconds=offset)
                self.assertEqual(clock.civil(epoch, offset),
                                 (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.weekday()), (epoch, offset))

    def test_untrusted_rtc_is_ignored_until_synced(self):
        # A badge that has not synced kept 2025-05-08 in November 2026.
        with patch.object(clock, "_synced", False), patch.object(clock, "_anchor_epoch", None), \
                patch.object(clock.time, "time", return_value=1746672776):
            self.assertIsNone(clock.now(1000))
        with patch.object(clock, "_synced", False), patch.object(clock, "_anchor_epoch", None):
            clock.anchor(FETCHED, 5000)
            self.assertEqual(clock.now(65000), FETCHED + 60)
        with patch.object(clock, "_synced", True), patch.object(clock.time, "time", return_value=FETCHED):
            self.assertEqual(clock.now(0), FETCHED)


class GeoTests(unittest.TestCase):
    def test_parse_fixture(self):
        found = geo.parse(load("freeipapi.json"))
        # Coordinates are kept to 2 decimals (about 1 km) before storing or sending.
        self.assertEqual(found, {"lat": 35.69, "lon": 139.75, "city": "Chiyoda", "cc": "JP"})

    def test_rejects_bad_payloads(self):
        self.assertIsNone(geo.parse({"latitude": float("nan"), "longitude": 1}))
        self.assertIsNone(geo.parse({"latitude": float("inf"), "longitude": 1}))
        self.assertIsNone(geo.parse({"latitude": "1e999", "longitude": 1}))
        self.assertIsNone(geo.parse({"latitude": 0, "longitude": 0}))
        self.assertIsNone(geo.parse({"latitude": "x", "longitude": 1}))
        self.assertIsNone(geo.parse({"latitude": 95, "longitude": 1}))
        self.assertIsNone(geo.parse([]))

    def test_non_ascii_names_are_made_printable(self):
        found = geo.parse({"latitude": 48.2, "longitude": 16.4, "cityName": "Wién", "countryCode": "at"})
        self.assertEqual(found["city"], "Wi?n")
        self.assertEqual(found["cc"], "AT")


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.records = forecast.parse(OM7, 7)
        self.tokyo = self.records[1]

    def test_url_covers_every_location_once(self):
        url = forecast.build_url([(35.69, 139.75)] + [(c[1], c[2]) for c in cities.CITIES])
        self.assertIn("latitude=35.69,35.6895,34.6938,43.0667,33.6,26.213,37.7749&", url)
        self.assertIn("longitude=139.75,139.6917,135.5011,141.35,130.4167,127.6785,-122.4194&", url)
        self.assertIn("timezone=auto&timeformat=unixtime", url)
        self.assertIn("forecast_hours=48&forecast_days=7", url)

    def test_parse_shapes(self):
        self.assertEqual(len(self.records), 7)
        self.assertEqual(self.tokyo["off"], 32400)
        self.assertEqual([r["off"] for r in self.records], [32400] * 6 + [-28800])
        self.assertEqual(len(self.tokyo["h"]["time"]), 48)
        self.assertEqual(len(self.tokyo["dl"]["time"]), 7)
        self.assertIsInstance(self.tokyo["h"]["c"][0], int)
        self.assertEqual(self.tokyo["now"]["t"], 7.9)
        self.assertEqual(self.records[6]["off"], -28800)

    def test_six_city_fixture_matches_cities_order(self):
        records = forecast.parse(load("open_meteo_6.json"), len(cities.CITIES))
        self.assertEqual(records[-1]["off"], -28800)  # San Francisco is last

    def test_single_location_object_and_errors(self):
        self.assertEqual(len(forecast.parse(OM7[0], 1)), 1)
        with self.assertRaises(ValueError):
            forecast.parse(OM7, 6)
        with self.assertRaises(ValueError):
            forecast.parse({"error": True, "reason": "Invalid"}, 1)

    def test_hostile_values_are_dropped_not_crashing(self):
        entry = json.loads(json.dumps(OM7[0]))
        entry["hourly"]["temperature_2m"][:4] = [float("inf"), float("nan"), 1e300, "hot"]
        entry["hourly"]["weather_code"][0] = True
        entry["current"]["temperature_2m"] = float("-inf")
        record = forecast.parse(entry, 1)[0]
        self.assertEqual(record["h"]["t"][:4], [None, None, None, None])
        self.assertIsNone(record["h"]["c"][0])
        self.assertIsNone(record["now"]["t"])
        self.assertEqual(units.fmt_temp(record["h"]["t"][0], "C"), "--")

    def test_hostile_structure_raises_value_error(self):
        for mutate in (
            lambda e: e["hourly"]["time"].__setitem__(0, float("inf")),
            lambda e: e["hourly"]["time"].__setitem__(0, -5),
            lambda e: e.__setitem__("utc_offset_seconds", 10 ** 9),
            lambda e: e.__setitem__("utc_offset_seconds", "32400"),
            lambda e: e.__setitem__("hourly", []),
        ):
            entry = json.loads(json.dumps(OM7[0]))
            mutate(entry)
            with self.assertRaises(ValueError):
                forecast.parse(entry, 1)

    def test_missing_series_values_become_none(self):
        entry = json.loads(json.dumps(OM7[0]))
        del entry["hourly"]["precipitation_probability"]
        record = forecast.parse(entry, 1)[0]
        self.assertEqual(record["h"]["pp"], [None] * 48)

    def test_cursor_bases(self):
        self.assertEqual(forecast.hour_base(self.tokyo, FETCHED), 0)
        self.assertEqual(forecast.hour_base(self.tokyo, FETCHED + 3 * 3600), 3)
        self.assertEqual(forecast.hour_base(self.tokyo, None), 0)
        self.assertEqual(forecast.max_offset(self.tokyo, "hour", FETCHED), 47)
        self.assertEqual(forecast.max_offset(self.tokyo, "hour", FETCHED + 10 * 3600), 37)
        # 22:39 JST is still the first local day; 01:00 JST next day is the second.
        self.assertEqual(forecast.day_base(self.tokyo, FETCHED), 0)
        self.assertEqual(forecast.day_base(self.tokyo, FETCHED + 3 * 3600), 1)
        self.assertEqual(forecast.max_offset(self.tokyo, "day", FETCHED), 6)

    def test_hour_slot_prefers_current_conditions_now(self):
        live = forecast.hour_slot(self.tokyo, FETCHED, 0)
        self.assertTrue(live["live"])
        self.assertEqual(live["t"], self.tokyo["now"]["t"])
        self.assertEqual(live["rh"], self.tokyo["now"]["rh"])
        later = forecast.hour_slot(self.tokyo, FETCHED, 3)
        self.assertFalse(later["live"])
        self.assertEqual(later["time"], self.tokyo["h"]["time"][3])
        self.assertNotIn("rh", later)
        # Current conditions older than 90 minutes are not shown as "now".
        stale = forecast.hour_slot(self.tokyo, FETCHED + 2 * 3600, 0)
        self.assertFalse(stale["live"])

    def test_hour_strip_shows_forecast_not_current_conditions(self):
        _, first = forecast.strip(self.tokyo, FETCHED, "hour", 0, 7)[0]
        base = forecast.hour_base(self.tokyo, FETCHED)
        self.assertFalse(first["live"])
        self.assertEqual(first["time"], self.tokyo["h"]["time"][base])
        self.assertEqual(first["t"], self.tokyo["h"]["t"][base])

    def test_strip_is_clamped_to_available_data(self):
        cells = forecast.strip(self.tokyo, FETCHED, "hour", 44, 8)
        self.assertEqual([offset for offset, _ in cells], [44, 45, 46, 47])
        days = forecast.strip(self.tokyo, FETCHED, "day", 0, 7)
        self.assertEqual(len(days), 7)
        self.assertIn("hi", days[0][1])


class WmoTests(unittest.TestCase):
    def test_every_code_in_fixture_is_known(self):
        codes = set()
        for entry in OM7:
            codes.update(entry["hourly"]["weather_code"])
            codes.update(entry["daily"]["weather_code"])
            codes.add(entry["current"]["weather_code"])
        for code in codes:
            self.assertNotEqual(wmo.lookup(code)[1], "--", code)

    def test_day_night_and_unknown(self):
        self.assertEqual(wmo.lookup(0, 1)[0], wmo.SUN)
        self.assertEqual(wmo.lookup(0, 0)[0], wmo.MOON)
        self.assertEqual(wmo.lookup(2, 0)[0], wmo.CLOUD_MOON)
        self.assertEqual(wmo.lookup(None)[1], "--")
        self.assertEqual(wmo.lookup(42)[1], "--")


class _Raw:
    def __init__(self, data):
        self.data = data

    def read(self, n):
        chunk, self.data = self.data[:n], self.data[n:]
        return chunk


class _Response:
    def __init__(self, data, raw=True):
        self.raw = _Raw(data) if raw else None
        self.content = data


class NetTests(unittest.TestCase):
    def test_read_limited_caps_untrusted_bodies(self):
        self.assertEqual(net.read_limited(_Response(b"x" * 1000), 4096), b"x" * 1000)
        with self.assertRaises(ValueError):
            net.read_limited(_Response(b"x" * 5000), 4096)
        with self.assertRaises(ValueError):
            net.read_limited(_Response(b"x" * 5000, raw=False), 4096)
        self.assertEqual(net.short_error(ValueError("response larger than 4096 bytes")), "Too large")

    def test_real_forecast_fits_the_cap_with_room_for_eight_locations(self):
        size = len((FIXTURES / "open_meteo_7.json").read_bytes())
        self.assertLess(size * 8 / 7, net.MAX_FORECAST_BYTES / 2)

    def test_short_errors_fit_the_footer(self):
        self.assertEqual(net.short_error(OSError("HTTP 503")), "Server error 503")
        self.assertEqual(net.short_error(ValueError("bad json")), "Bad response")
        self.assertEqual(net.short_error(OSError(110)), "Timed out")
        self.assertEqual(net.short_error(OSError(-2)), "Network error")


class AssetTests(unittest.TestCase):
    def test_icon_font_header_and_glyphs(self):
        data = (APP / "weather-icons.af").read_bytes()
        self.assertEqual(data[:4], b"af!?")
        flags, glyphs, paths, points = struct.unpack(">HHHH", data[4:12])
        self.assertEqual(flags, 1)
        codepoints = [struct.unpack(">H", data[12 + 8 * i:14 + 8 * i])[0] for i in range(glyphs)]
        self.assertEqual(codepoints, sorted(codepoints))
        used = {getattr(wmo, name) for name in dir(wmo) if name.isupper() and len(getattr(wmo, name)) == 1}
        self.assertTrue({ord(ch) for ch in used} <= set(codepoints))
        self.assertEqual(len(data), 12 + 8 * glyphs + 2 * paths + 2 * points)

    def test_cities_are_ascii_and_within_limit(self):
        self.assertLessEqual(len(cities.CITIES), 7)
        for name, lat, lon in cities.CITIES:
            self.assertTrue(name.isascii() and 0 < len(name) <= 18, name)
            self.assertTrue(-90 <= lat <= 90 and -180 <= lon <= 180)


if __name__ == "__main__":
    unittest.main()
