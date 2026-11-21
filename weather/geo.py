# Location estimate from the badge's public IP address (freeipapi.com).
# Can be switched off in Settings > Location (then no request is made).
# Free tier: HTTPS, no key, 60 requests/minute. The app asks at most once
# every few hours. Accuracy is usually city-level at best; VPNs, tethering and
# corporate or venue proxies can place the badge far from where it really is.

URL = "https://free.freeipapi.com/api/v1/json/"
SOURCE = "freeipapi.com"


def _ascii(text, limit=18):
    text = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(text or "")).strip()
    return text[:limit].rstrip()


def parse(payload):
    """Validated {lat, lon, city, cc} from a freeipapi response, or None."""
    if not isinstance(payload, dict):
        return None
    try:
        lat = float(payload["latitude"])
        lon = float(payload["longitude"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    # nan fails every comparison below, inf fails the range check
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    city = _ascii(payload.get("cityName")) or _ascii(payload.get("regionName")) or _ascii(payload.get("countryName"))
    # Keep about 1 km of precision (2 decimals): enough for a forecast grid
    # cell, and no more than needs to be stored on the badge or sent onwards.
    return {
        "lat": round(lat, 2),
        "lon": round(lon, 2),
        "city": city or "Unknown",
        "cc": _ascii(payload.get("countryCode"), 2).upper(),
    }
