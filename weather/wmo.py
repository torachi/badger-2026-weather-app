# WMO weather interpretation codes (as used by Open-Meteo) -> icon and label.
#
# Icon characters index weather-icons.af (see tools/build_weather_icons.py).
# Each code maps to (day icon, night icon, short label, colour key).

SUN = "a"
MOON = "b"
CLOUD = "c"
CLOUD_SUN = "d"
CLOUD_MOON = "e"
RAIN = "f"
HEAVY_RAIN = "g"
SUN_SHOWER = "h"
MOON_SHOWER = "i"
STORM = "j"
SNOW = "k"
FOG = "l"
WIND = "m"
DROPLET = "n"
UMBRELLA = "o"
PIN = "p"
REFRESH = "q"
GEAR = "r"
WARNING = "s"
WIFI = "t"
THERMOMETER = "u"

_CODES = {
    0: (SUN, MOON, "Clear", "sun"),
    1: (SUN, MOON, "Mainly clear", "sun"),
    2: (CLOUD_SUN, CLOUD_MOON, "Partly cloudy", "cloud"),
    3: (CLOUD, CLOUD, "Overcast", "cloud"),
    45: (FOG, FOG, "Fog", "fog"),
    48: (FOG, FOG, "Rime fog", "fog"),
    51: (RAIN, RAIN, "Light drizzle", "rain"),
    53: (RAIN, RAIN, "Drizzle", "rain"),
    55: (RAIN, RAIN, "Dense drizzle", "rain"),
    56: (RAIN, RAIN, "Freezing drizzle", "ice"),
    57: (RAIN, RAIN, "Freezing drizzle", "ice"),
    61: (RAIN, RAIN, "Light rain", "rain"),
    63: (RAIN, RAIN, "Rain", "rain"),
    65: (HEAVY_RAIN, HEAVY_RAIN, "Heavy rain", "rain"),
    66: (RAIN, RAIN, "Freezing rain", "ice"),
    67: (HEAVY_RAIN, HEAVY_RAIN, "Freezing rain", "ice"),
    71: (SNOW, SNOW, "Light snow", "snow"),
    73: (SNOW, SNOW, "Snow", "snow"),
    75: (SNOW, SNOW, "Heavy snow", "snow"),
    77: (SNOW, SNOW, "Snow grains", "snow"),
    80: (SUN_SHOWER, MOON_SHOWER, "Showers", "rain"),
    81: (SUN_SHOWER, MOON_SHOWER, "Showers", "rain"),
    82: (HEAVY_RAIN, HEAVY_RAIN, "Heavy showers", "rain"),
    85: (SNOW, SNOW, "Snow showers", "snow"),
    86: (SNOW, SNOW, "Snow showers", "snow"),
    95: (STORM, STORM, "Thunderstorm", "storm"),
    96: (STORM, STORM, "Storm, hail", "storm"),
    99: (STORM, STORM, "Storm, hail", "storm"),
}

_UNKNOWN = (CLOUD, CLOUD, "--", "cloud")


def lookup(code, is_day=True):
    """(icon, label, colour key) for a WMO code; unknown or None -> neutral."""
    entry = _CODES.get(code, _UNKNOWN) if code is not None else _UNKNOWN
    return (entry[0] if is_day or is_day is None else entry[1]), entry[2], entry[3]
