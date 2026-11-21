# Calendar arithmetic on Unix epoch seconds, independent of the badge RTC's
# epoch and time zone. Forecast times arrive as UTC epoch seconds plus each
# location's utc_offset_seconds, so local fields are computed here directly.

import time

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

PLAUSIBLE = 1735689600   # 2025-01-01T00:00Z; earlier means the RTC is unset

# Seconds between the Unix epoch and the RTC's epoch (0 when it is 1970,
# 946684800 on ports that count from 2000).
_RTC_EPOCH = 0 if time.gmtime(0)[0] == 1970 else 946684800

_anchor_epoch = None     # Unix seconds reported by a server...
_anchor_ticks = 0        # ...and the badge ticks (ms) when it was received
_synced = False          # True once NTP has set the RTC in this session


def civil(epoch, offset=0):
    """(year, month, day, hour, minute, weekday Mon=0) for epoch + offset seconds."""
    seconds = int(epoch) + int(offset)
    days, rem = divmod(seconds, 86400)
    hour, rem = divmod(rem, 3600)
    minute = rem // 60
    weekday = (days + 3) % 7  # 1970-01-01 was a Thursday
    # Howard Hinnant's civil_from_days
    z = days + 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return (y + (1 if m <= 2 else 0), m, d, hour, minute, weekday)


def anchor(epoch, ticks):
    """Remember a trusted server time so now() works without a set RTC."""
    global _anchor_epoch, _anchor_ticks
    if epoch and epoch > PLAUSIBLE:
        _anchor_epoch = int(epoch)
        _anchor_ticks = ticks


def mark_synced():
    global _synced
    _synced = True


def rtc_now():
    value = int(time.time()) + _RTC_EPOCH
    return value if value > PLAUSIBLE else None


def now(ticks):
    """Best estimate of Unix time.

    The RTC is only trusted after NTP set it this session: a badge that has not
    synced can keep a stale but plausible-looking date (one test badge read
    2025-05-08 in November 2026). Otherwise use the last server anchor, or
    None when there is neither.
    """
    if _synced:
        return rtc_now()
    if _anchor_epoch is not None:
        return _anchor_epoch + (ticks - _anchor_ticks) // 1000
    return None


def trusted():
    return _synced or _anchor_epoch is not None
