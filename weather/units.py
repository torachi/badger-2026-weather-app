# Unit conversion and formatting. Forecasts are always fetched in metric
# (degrees C, km/h, mm) and converted here, so changing a unit needs no refetch.

TEMP_UNITS = ("C", "F")
WIND_UNITS = ("m/s", "km/h", "mph", "kn")
RAIN_UNITS = ("mm", "in")
CLOCKS = ("24h", "12h")

DEGREE = "°"
DASH = "--"

_WIND_DIVISOR = {"m/s": 3.6, "km/h": 1.0, "mph": 1.609344, "kn": 1.852}


def temperature(celsius, unit):
    if celsius is None:
        return None
    return celsius * 9 / 5 + 32 if unit == "F" else celsius


def wind(kmh, unit):
    if kmh is None:
        return None
    return kmh / _WIND_DIVISOR.get(unit, 1.0)


def rain(mm, unit):
    if mm is None:
        return None
    return mm / 25.4 if unit == "in" else mm


def _round_half_away(value):
    # round() in MicroPython and CPython rounds halves to even; -0.5 -> -1
    # and 0.5 -> 1 reads better for temperatures.
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def fmt_temp(celsius, unit, with_unit=False):
    value = temperature(celsius, unit)
    if value is None:
        return DASH
    text = "%d%s" % (_round_half_away(value), DEGREE)
    return text + unit if with_unit else text


def fmt_wind(kmh, unit):
    value = wind(kmh, unit)
    if value is None:
        return DASH
    if value < 10 and unit in ("m/s", "kn"):
        return "%.1f %s" % (value, unit)
    return "%d %s" % (_round_half_away(value), unit)


def fmt_rain(mm, unit):
    value = rain(mm, unit)
    if value is None:
        return DASH
    if unit == "in":
        return "%.2f in" % value
    return ("%.1f mm" % value) if value < 10 else ("%d mm" % _round_half_away(value))


def fmt_percent(value):
    return DASH if value is None else "%d%%" % _round_half_away(value)


def fmt_clock(hour, minute, clock):
    if clock == "12h":
        suffix = "am" if hour < 12 else "pm"
        return "%d:%02d%s" % (hour % 12 or 12, minute, suffix)
    return "%02d:%02d" % (hour, minute)


def fmt_hour(hour, minute, clock):
    """Timeline strip label: "13:00" (24h) or "1:00" (12h; the strip marks AM/PM with a line)."""
    if clock == "12h":
        return "%d:%02d" % (hour % 12 or 12, minute)
    return "%02d:%02d" % (hour, minute)
