# Open-Meteo forecast: request building, parsing into compact per-location
# records, and the lookups behind the time cursor.
#
# All locations are fetched in one request (comma-separated coordinates);
# Open-Meteo then answers with a JSON array in request order. A single
# timezone=auto resolves each location's own time zone. Times are requested as
# Unix seconds (timeformat=unixtime) and shown using utc_offset_seconds.
# Data: Open-Meteo.com, CC BY 4.0.

BASE = "https://api.open-meteo.com/v1/forecast"
SOURCE = "Open-Meteo.com"
HOURS = 48
DAYS = 7

CURRENT = ("temperature_2m", "apparent_temperature", "relative_humidity_2m",
           "weather_code", "is_day", "wind_speed_10m", "precipitation")
# Hourly is the bulk of the response (48 values x 7 locations), so it carries
# only what the timeline needs; feels-like and humidity come from "current".
HOURLY = ("temperature_2m", "weather_code", "precipitation_probability",
          "is_day", "wind_speed_10m")
DAILY = ("weather_code", "temperature_2m_max", "temperature_2m_min",
         "precipitation_probability_max", "precipitation_sum", "wind_speed_10m_max")

# Short keys keep the cached JSON and the in-memory lists small.
_SHORT = {
    "temperature_2m": "t", "apparent_temperature": "f", "relative_humidity_2m": "rh",
    "weather_code": "c", "is_day": "d", "wind_speed_10m": "w", "precipitation": "p",
    "precipitation_probability": "pp", "temperature_2m_max": "hi",
    "temperature_2m_min": "lo", "precipitation_probability_max": "pp",
    "precipitation_sum": "p", "wind_speed_10m_max": "w",
}
_INTS = ("c", "d", "rh", "pp")


def _fmt_coord(value):
    text = "%.4f" % value
    return text.rstrip("0").rstrip(".") if "." in text else text


def build_url(points):
    """points: [(lat, lon), ...] -> one forecast URL for all of them."""
    lats = ",".join(_fmt_coord(p[0]) for p in points)
    lons = ",".join(_fmt_coord(p[1]) for p in points)
    return (BASE + "?latitude=" + lats + "&longitude=" + lons +
            "&current=" + ",".join(CURRENT) +
            "&hourly=" + ",".join(HOURLY) +
            "&daily=" + ",".join(DAILY) +
            "&forecast_hours=%d&forecast_days=%d" % (HOURS, DAYS) +
            "&timezone=auto&timeformat=unixtime")


# Responses are untrusted (see net.py): keep only finite values in a range no
# real forecast leaves, so formatting can never fail on inf, nan or 1e300.
_LIMIT = 10000


def _num(value, key):
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value - value != 0 or not -_LIMIT < value < _LIMIT:   # nan or inf, or absurd
        return None
    if key in _INTS:
        return int(value)
    return round(value, 1)


def _time(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value - value != 0:
        raise ValueError("bad time value")
    value = int(value)
    if not 0 < value < 4102444800:   # 1970 .. 2100
        raise ValueError("time out of range")
    return value


def _series(block, names):
    if not isinstance(block, dict) or not isinstance(block.get("time"), list):
        raise ValueError("missing time series")
    times = [_time(t) for t in block["time"]]
    out = {"time": times}
    for name in names:
        values = block.get(name)
        key = _SHORT[name]
        if not isinstance(values, list) or len(values) != len(times):
            values = [None] * len(times)
        out[key] = [_num(v, key) for v in values]
    return out


def _location(entry):
    if not isinstance(entry, dict):
        raise ValueError("location is not an object")
    if "error" in entry and entry.get("error"):
        raise ValueError(str(entry.get("reason", "API error")))
    current = entry.get("current") or {}
    offset = entry.get("utc_offset_seconds")
    if isinstance(offset, bool) or not isinstance(offset, int) or not -50400 <= offset <= 50400:
        raise ValueError("bad utc offset")   # must be whole seconds within UTC-14..+14
    record = {
        "off": offset,
        "h": _series(entry.get("hourly"), HOURLY),
        "dl": _series(entry.get("daily"), DAILY),
        "now": None,
    }
    if not isinstance(current, dict):
        current = {}
    if current.get("time") is not None:
        now = {"time": _time(current["time"])}
        for name in CURRENT:
            key = _SHORT[name]
            now[key] = _num(current.get(name), key)
        record["now"] = now
    return record


def parse(payload, count):
    """Open-Meteo JSON (object for one location, array for several) -> list of records."""
    if isinstance(payload, dict) and payload.get("error"):
        raise ValueError(str(payload.get("reason", "API error")))
    entries = payload if isinstance(payload, list) else [payload]
    if len(entries) != count:
        raise ValueError("expected %d locations, got %d" % (count, len(entries)))
    return [_location(entry) for entry in entries]


# ---- cursor lookups -----------------------------------------------------------

def base_index(times, now, step):
    """Index of the slot containing `now` (clamped), e.g. the current hour."""
    if not times:
        return 0
    if now is None:
        return 0
    index = (now - times[0]) // step
    return max(0, min(len(times) - 1, index))


def hour_base(record, now):
    return base_index(record["h"]["time"], now, 3600)


def day_base(record, now):
    # Daily times are local midnights expressed in UTC; compare in local time.
    times = record["dl"]["time"]
    if not times or now is None:
        return 0
    return base_index(times, now, 86400)


def max_offset(record, mode, now):
    if mode == "day":
        return max(0, len(record["dl"]["time"]) - 1 - day_base(record, now))
    return max(0, len(record["h"]["time"]) - 1 - hour_base(record, now))


def _pick(series, index, keys):
    return {key: series[key][index] for key in keys if key in series}


def hour_slot(record, now, offset):
    """Values for the hour `offset` hours from now; offset 0 prefers current conditions."""
    h = record["h"]
    if not h["time"]:
        return None
    index = min(len(h["time"]) - 1, hour_base(record, now) + offset)
    slot = _pick(h, index, ("time", "t", "c", "pp", "d", "w"))
    slot["live"] = False
    cur = record.get("now")
    if offset == 0 and cur and (now is None or abs(now - cur["time"]) < 5400):
        for key in ("t", "f", "rh", "c", "d", "w", "p"):
            if cur.get(key) is not None:
                slot[key] = cur[key]
        slot["time"] = cur["time"]
        slot["live"] = True
    return slot


def day_slot(record, now, offset):
    dl = record["dl"]
    if not dl["time"]:
        return None
    index = min(len(dl["time"]) - 1, day_base(record, now) + offset)
    slot = _pick(dl, index, ("time", "c", "hi", "lo", "pp", "p", "w"))
    slot["d"] = 1
    return slot


def strip(record, now, mode, first, count):
    """Slots for the timeline strip starting at cursor offset `first`."""
    out = []
    last = max_offset(record, mode, now)
    for offset in range(first, min(first + count, last + 1)):
        out.append((offset, hour_slot(record, now, offset) if mode == "hour" else day_slot(record, now, offset)))
    return out
