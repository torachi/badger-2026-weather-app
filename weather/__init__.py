import os
import sys

APP_DIR = "/system/apps/weather"
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

from badgeware import State

import clock
import forecast
import geo
import net
import ui
import units
import wmo
from cities import CITIES

badge.mode(HIRES | VSYNC)
screen.antialias = image.X2

ui.init(
    font.load(APP_DIR + "/weather-icons.af"),
    font.load("/system/assets/fonts/MonaSans-Medium.af"),
    font.nope,
)

# ---- configuration -----------------------------------------------------------------

MAX_CITIES = 7
REFRESH_EVERY_S = 30 * 60      # forecast age that triggers an automatic refresh
GEO_EVERY_S = 6 * 60 * 60      # how often to re-estimate "Here"
IDLE_BEFORE_AUTO_MS = 8000     # auto refreshes wait for the buttons to be idle
RETRY_MS = (60_000, 120_000, 300_000)
REPEAT_DELAY_MS = 380          # left/right auto-repeat when held
REPEAT_EVERY_MS = 110
SAVE_DELAY_MS = 3000           # write the selected city after this much quiet
HOUR_SLOTS = 8
DAY_SLOTS = 7

CITY_LIST = [{"key": name, "name": name, "lat": lat, "lon": lon, "here": False}
             for name, lat, lon in CITIES[:MAX_CITIES]]

DEFAULTS = {"step": "hour", "temp": "C", "wind": "m/s", "rain": "mm", "clock": "24h",
            "location": "on", "last_city": None}
CHOICES = {"step": ("hour", "day"), "temp": units.TEMP_UNITS, "wind": units.WIND_UNITS,
           "rain": units.RAIN_UNITS, "clock": units.CLOCKS, "location": ("on", "off")}

settings = dict(DEFAULTS)
State.load("weather", settings)
# A damaged or hand-edited state file must not stop the app from starting.
for _key, _allowed in CHOICES.items():
    if settings.get(_key) not in _allowed:
        settings[_key] = DEFAULTS[_key]
if not isinstance(settings.get("last_city"), (str, type(None))):
    settings["last_city"] = None

# Last successful forecast, keyed by location so edits to cities.py keep
# whatever still matches. "at" is the Unix time of the fetch (0 if unknown).
CACHE_EMPTY = {"at": 0, "geo": None, "geo_at": 0, "size": 0, "data": {}}
cache = dict(CACHE_EMPTY)
State.load("weather_cache", cache)


def _cache_ok(c):
    g = c.get("geo")
    geo_ok = g is None or (isinstance(g, dict) and isinstance(g.get("city"), str) and isinstance(g.get("cc"), str)
                           and isinstance(g.get("lat"), (int, float)) and isinstance(g.get("lon"), (int, float)))
    return (isinstance(c.get("data"), dict) and all(isinstance(r, dict) and "h" in r and "dl" in r and "off" in r
                                                     for r in c["data"].values())
            and isinstance(c.get("at"), (int, float)) and isinstance(c.get("geo_at"), (int, float)) and geo_ok)


if not _cache_ok(cache):
    cache = dict(CACHE_EMPTY)
if cache.get("geo"):
    # Older versions kept 4 decimals; keep only about 1 km, as geo.parse now does.
    cache["geo"]["lat"] = round(cache["geo"]["lat"], 2)
    cache["geo"]["lon"] = round(cache["geo"]["lon"], 2)


def forget_here():
    """Drop the IP-based location and its forecast (whose key encodes the coordinates)."""
    g = cache.get("geo")
    if g:
        key = "%.3f,%.3f" % (g["lat"], g["lon"])
        if key not in {"%.3f,%.3f" % (c[1], c[2]) for c in CITIES}:
            cache["data"].pop(key, None)
    cache["geo"] = None
    cache["geo_at"] = 0


if settings["location"] == "off":
    forget_here()

# ---- runtime state -----------------------------------------------------------------

job = None
last_error = None
last_detail = None
retry_at = 0
failures = 0
last_input = 0
selection = None          # key of the shown location ("here" or a city name)
user_moved = False
save_due = 0
offset = 0                # cursor: hours (hour mode) or days (day mode) from now
strip_first = 0
held_since = None
next_repeat = 0
overlay = None            # None, "menu" or "about"
menu_index = 0
menu_first = 0            # first visible menu row (the list scrolls)
shot_since = None         # Settings > Screenshot, or holding the Back touch pad, saves the screen
shot_pending = False
shot_note_until = 0
SHOT_HOLD_MS = 1500
# The framebuffer as-is: RGB565 little-endian on the badge (RGBA8888 in the
# simulator). tools/screenshot_to_png.py converts either.
SHOT_PATH = "/weather_screen.raw"
DEBUG_FPS = False         # print the frame rate over USB serial every FPS_EVERY_MS
frames = 0
fps_since = 0
FPS_EVERY_MS = 10_000


def locations():
    out = []
    if cache.get("geo") and settings["location"] == "on":
        g = cache["geo"]
        out.append({"key": "here", "name": g["city"], "lat": g["lat"], "lon": g["lon"], "here": True})
    return out + CITY_LIST


def coord_key(loc):
    return "%.3f,%.3f" % (loc["lat"], loc["lon"])


def record_for(loc):
    return cache["data"].get(coord_key(loc))


def choose_initial():
    keys = [loc["key"] for loc in locations()]
    if "here" in keys and cache.get("geo_at") and fresh_geo():
        return "here"
    if settings.get("last_city") in keys:
        return settings["last_city"]
    return keys[0] if keys else None


def fresh_geo():
    now = clock.now(badge.ticks)
    return now is not None and now - cache.get("geo_at", 0) < GEO_EVERY_S


def current_location():
    locs = locations()
    for i, loc in enumerate(locs):
        if loc["key"] == selection:
            return i, loc, locs
    return 0, (locs[0] if locs else None), locs


# ---- refresh -----------------------------------------------------------------------

GEO_FORGET_S = 24 * 60 * 60   # drop an old "Here" when it cannot be re-estimated


def forecast_url_for(found_geo):
    now = clock.now(badge.ticks)
    if found_geo and settings["location"] == "on":
        cache["geo"] = found_geo
        cache["geo_at"] = now or 0
    elif cache.get("geo") and now and now - cache.get("geo_at", 0) > GEO_FORGET_S:
        cache["geo"] = None
    points = [(loc["lat"], loc["lon"]) for loc in locations()]
    return forecast.build_url(points), len(points)


def cache_fresh():
    now = clock.now(badge.ticks)
    return (now is not None and bool(cache["data"]) and cache.get("at")
            and 0 <= now - cache["at"] < REFRESH_EVERY_S)


def start_refresh(reason, want_geo=None):
    """reason: "manual" always fetches; "auto" first syncs the clock and skips
    the download when the cached forecast (and location) are still fresh."""
    global job
    if job is not None:
        return
    if want_geo is None:
        want_geo = not cache.get("geo") or not fresh_geo()
    want_geo = want_geo and settings["location"] == "on"
    needed = None
    if reason != "manual":
        needed = lambda: not cache_fresh() or (want_geo and not fresh_geo())
    job = net.Refresh(want_geo, geo.URL, forecast_url_for, cache.get("size"), badge.ticks, needed)


def finish_refresh():
    global job, last_error, last_detail, retry_at, failures, selection, user_moved
    done = job
    job = None
    if done.geo_error and not cache.get("geo"):
        print("[weather] no location; using registered cities")
    if done.state == net.DONE and done.skipped:
        last_error = None
        failures = 0
        if fresh_geo() and not user_moved and cache.get("geo"):
            selection = "here"
        return
    if done.state == net.DONE:
        try:
            records = forecast.parse(done.payload, done.count)
        except Exception as e:  # noqa: BLE001 - untrusted data must never reboot the badge
            done.error = "Bad response"
            done.detail = "Unexpected forecast data: %s" % e
            records = None
        done.payload = None
        if records is not None:
            data = {}
            for loc, record in zip(locations(), records):
                data[coord_key(loc)] = record
            cache["data"] = data
            cache["at"] = clock.now(badge.ticks) or 0
            cache["size"] = done.received
            State.save("weather_cache", cache)
            last_error = last_detail = None
            failures = 0
            if done.geo and not user_moved:
                selection = "here"
            return
    last_error = done.error or "Refresh failed"
    last_detail = done.detail or last_error
    retry_at = badge.ticks + RETRY_MS[min(failures, len(RETRY_MS) - 1)]
    failures += 1


def refresh_due():
    if job is not None or badge.ticks < retry_at:
        return False
    if not cache["data"]:
        return True
    now = clock.now(badge.ticks)
    if now is None or not cache.get("at"):
        return True
    stale = now - cache["at"] >= REFRESH_EVERY_S
    return stale and badge.ticks - last_input >= IDLE_BEFORE_AUTO_MS


# ---- input -------------------------------------------------------------------------

def any_input():
    for button in (BUTTON_UP, BUTTON_DOWN, BUTTON_LEFT, BUTTON_RIGHT, BUTTON_SELECT, BUTTON_BACK, BUTTON_MENU):
        if badge.pressed(button) or badge.held(button):
            return True
    return False


def repeat(button):
    """True on press, then repeatedly while held."""
    global held_since, next_repeat
    if badge.pressed(button):
        held_since = (button, badge.ticks)
        next_repeat = badge.ticks + REPEAT_DELAY_MS
        return True
    if held_since and held_since[0] == button and badge.held(button) and badge.ticks >= next_repeat:
        next_repeat = badge.ticks + REPEAT_EVERY_MS
        return True
    return False


def move_city(step):
    global selection, user_moved, save_due
    index, _, locs = current_location()
    if not locs:
        return
    loc = locs[(index + step) % len(locs)]
    selection = loc["key"]
    user_moved = True
    if not loc["here"]:
        settings["last_city"] = loc["key"]
        save_due = badge.ticks + SAVE_DELAY_MS


def move_time(step):
    global offset
    _, loc, _ = current_location()
    record = record_for(loc) if loc else None
    if record is None:
        return
    limit = forecast.max_offset(record, settings["step"], clock.now(badge.ticks))
    offset = max(0, min(limit, offset + step))


MENU = (
    ("Step", "step", ("hour", "day"), ("Hourly", "Daily")),
    ("Temperature", "temp", units.TEMP_UNITS, ("°C", "°F")),
    ("Wind", "wind", units.WIND_UNITS, units.WIND_UNITS),
    ("Rain", "rain", units.RAIN_UNITS, units.RAIN_UNITS),
    ("Clock", "clock", units.CLOCKS, units.CLOCKS),
    ("Location", "location", ("on", "off"), ("On", "Off")),
    ("Refresh now", None, None, None),
    ("Screenshot", None, None, None),
    ("About", None, None, None),
    ("Close", None, None, None),
)


def cycle(entry, step):
    global offset, strip_first
    _, key, values, _ = entry
    index = values.index(settings[key]) if settings[key] in values else 0
    settings[key] = values[(index + step) % len(values)]
    if key == "step":
        offset = 0
        strip_first = 0
    elif key == "location":
        set_location(settings["location"] == "on")


def handle_menu():
    global overlay, menu_index, shot_pending
    entry = MENU[menu_index]
    if badge.pressed(BUTTON_UP):
        menu_index = (menu_index - 1) % len(MENU)
        scroll_menu()
    elif badge.pressed(BUTTON_DOWN):
        menu_index = (menu_index + 1) % len(MENU)
        scroll_menu()
    elif entry[1] and badge.pressed(BUTTON_LEFT):
        cycle(entry, -1)
    elif entry[1] and (badge.pressed(BUTTON_RIGHT) or badge.pressed(BUTTON_SELECT)):
        cycle(entry, 1)
    elif badge.pressed(BUTTON_SELECT):
        label = entry[0]
        if label == "Refresh now":
            close_menu()
            start_refresh("manual", want_geo=True)
        elif label == "Screenshot":
            close_menu()            # this frame is drawn without the menu, then saved
            shot_pending = True
        elif label == "About":
            overlay = "about"
        else:
            close_menu()
    elif badge.pressed(BUTTON_BACK) or badge.pressed(BUTTON_MENU):
        close_menu()


def scroll_menu():
    """Keep the selected row inside the visible window of ui.MENU_ROWS rows."""
    global menu_first
    rows = min(ui.MENU_ROWS, len(MENU))
    if menu_index < menu_first:
        menu_first = menu_index
    elif menu_index >= menu_first + rows:
        menu_first = menu_index - rows + 1
    menu_first = max(0, min(menu_first, len(MENU) - rows))


def set_location(on):
    """Settings > Location. Off forgets the estimate and stops the IP lookup."""
    global selection
    if on:
        start_refresh("manual", want_geo=True)
    else:
        forget_here()
        State.save("weather_cache", cache)
        if selection == "here":
            selection = settings.get("last_city") or (CITY_LIST[0]["key"] if CITY_LIST else None)


def close_menu():
    global overlay
    overlay = None
    State.save("weather", settings)


def handle_input():
    global overlay, last_input, menu_index
    if any_input():
        last_input = badge.ticks
    if overlay == "about":
        if badge.pressed(BUTTON_BACK) or badge.pressed(BUTTON_SELECT):
            overlay = "menu"
        return
    if overlay == "menu":
        handle_menu()
        return
    if badge.pressed(BUTTON_SELECT) or badge.pressed(BUTTON_MENU):
        overlay = "menu"
        menu_index = 0
        scroll_menu()
        return
    watch_screenshot_hold()
    if badge.pressed(BUTTON_UP):
        move_city(-1)
    elif badge.pressed(BUTTON_DOWN):
        move_city(1)
    if repeat(BUTTON_LEFT):
        move_time(-1)
    elif repeat(BUTTON_RIGHT):
        move_time(1)


def watch_screenshot_hold():
    global shot_since, shot_pending
    if badge.held(BUTTON_BACK):
        if shot_since is None:
            shot_since = badge.ticks
        elif shot_since and badge.ticks - shot_since >= SHOT_HOLD_MS:
            shot_pending = True
            shot_since = 0          # once per hold
    else:
        shot_since = None


def save_screenshot():
    """Write the frame just drawn (screen.raw) to SHOT_PATH."""
    global shot_note_until
    try:
        with open(SHOT_PATH, "wb") as f:
            f.write(screen.raw)
        print("[weather] screenshot saved to %s (%dx%d)" % (SHOT_PATH, screen.width, screen.height))
        shot_note_until = badge.ticks + 2000
    except OSError as e:
        print("[weather] screenshot failed:", e)


# ---- view model ----------------------------------------------------------------------

def fmt_local(epoch, off, with_day=True):
    y, m, d, hh, mm, wd = clock.civil(epoch, off)
    text = units.fmt_clock(hh, mm, settings["clock"])
    return (clock.WEEKDAYS[wd] + " " + text) if with_day else text


def build_slot(record, now):
    mode = settings["step"]
    raw = forecast.day_slot(record, now, offset) if mode == "day" else forecast.hour_slot(record, now, offset)
    if raw is None:
        return None
    char, label, key = wmo.lookup(raw.get("c"), raw.get("d"))
    slot = {"icon": char, "label": label, "tone": key, "d": raw.get("d"), "time": raw["time"]}
    t, w, r = settings["temp"], settings["wind"], settings["rain"]
    if mode == "day":
        slot["hi"] = units.fmt_temp(raw.get("hi"), t)
        slot["lo"] = units.fmt_temp(raw.get("lo"), t)
        slot["facts"] = [
            (wmo.UMBRELLA, units.fmt_percent(raw.get("pp"))),
            (wmo.DROPLET, units.fmt_rain(raw.get("p"), r)),
            (wmo.WIND, units.fmt_wind(raw.get("w"), w)),
        ]
    else:
        slot["temp"] = units.fmt_temp(raw.get("t"), t, with_unit=True)
        facts = [(wmo.UMBRELLA, units.fmt_percent(raw.get("pp"))), (wmo.WIND, units.fmt_wind(raw.get("w"), w))]
        if raw.get("live"):
            facts.append((wmo.THERMOMETER, "Feels " + units.fmt_temp(raw.get("f"), t)))
            facts.append((wmo.DROPLET, units.fmt_percent(raw.get("rh")) + " RH"))
        slot["facts"] = facts
        slot["live"] = raw.get("live")
    return slot


def build_strip(record, now):
    global strip_first
    mode = settings["step"]
    count = DAY_SLOTS if mode == "day" else HOUR_SLOTS
    last = forecast.max_offset(record, mode, now)
    if offset < strip_first:
        strip_first = offset
    elif offset >= strip_first + count:
        strip_first = offset - count + 1
    strip_first = max(0, min(strip_first, max(0, last - count + 1)))
    cells = []
    for off, raw in forecast.strip(record, now, mode, strip_first, count):
        if raw is None:
            continue
        char, _, key = wmo.lookup(raw.get("c"), raw.get("d"))
        y, m, d, hh, mm, wd = clock.civil(raw["time"], record["off"])
        cell = {"icon": char, "tone": key, "d": raw.get("d"), "selected": off == offset}
        if mode == "day":
            cell["label"] = "Today" if off == 0 else clock.WEEKDAYS[wd]
            cell["value"] = units.fmt_temp(raw.get("hi"), settings["temp"])
            cell["value2"] = units.fmt_temp(raw.get("lo"), settings["temp"])
        else:
            if off == 0:
                cell["label"] = "Now"
            elif hh == 0:
                cell["label"] = clock.WEEKDAYS[wd]
                cell["divider"] = True
            else:
                cell["label"] = units.fmt_hour(hh, settings["clock"])
            cell["value"] = units.fmt_temp(raw.get("t"), settings["temp"])
        cells.append(cell)
    return cells, count, strip_first > 0, strip_first + count <= last


def local_offset():
    """UTC offset for times about the badge itself: Here's zone, else the first city's."""
    for loc in locations():
        record = record_for(loc)
        if record is not None:
            return record["off"]
    return 0


def build_view():
    global offset
    index, loc, locs = current_location()
    now = clock.now(badge.ticks)
    view = {
        "name": loc["name"] if loc else "Weather",
        "here": bool(loc and loc["here"]),
        "index": index, "total": max(1, len(locs)),
        "mode": settings["step"], "slot": None,
        "busy": job is not None,
    }
    record = record_for(loc) if loc else None
    if record is not None:
        offset = min(offset, forecast.max_offset(record, settings["step"], now))
        slot = build_slot(record, now)
        view["slot"] = slot
        if slot:
            if settings["step"] == "day":
                y, m, d, hh, mm, wd = clock.civil(slot["time"], record["off"])
                view["when"] = "%s %d %s" % (clock.WEEKDAYS[wd], d, clock.MONTHS[m - 1])
                view["rel"] = "Today" if offset == 0 else ("Tomorrow" if offset == 1 else "+%dd" % offset)
            else:
                stamp = now if (slot.get("live") and now) else slot["time"]
                view["when"] = ("Now  " if offset == 0 else "") + fmt_local(stamp, record["off"])
                view["rel"] = "" if offset == 0 else "+%dh" % offset
            cells, count, more_left, more_right = build_strip(record, now)
            view.update(strip=cells, strip_slots=count, strip_more_left=more_left, strip_more_right=more_right)
    else:
        view["empty"] = "Fetching forecast..." if job else "No forecast yet"
        if last_error and not job:
            view["empty_detail"] = (last_detail or last_error)[:44]

    if cache.get("at"):
        off = local_offset()
        age = (now - cache["at"]) if now else None
        view["updated"] = "Updated " + fmt_local(cache["at"], off, with_day=age is not None and age > 20 * 3600)
        view["stale"] = age is not None and age > 3 * REFRESH_EVERY_S
    if badge.ticks < shot_note_until:
        view["status"] = {"note": "Screenshot saved"}
    elif job is not None:
        view["status"] = {"busy": True, "text": job.label() or "Updating", "progress": job.progress()}
    elif last_error:
        view["status"] = {"error": last_error}
    return view


def about_lines():
    g = cache.get("geo")
    return [
        ("Weather data: Open-Meteo.com (CC BY 4.0)", False),
        ("Location: freeipapi.com (from public IP)", False),
        ("Icons: Font Awesome Free (CC BY 4.0)", False),
        ("", False),
        (("Here: %s, %s (from IP, approximate)" % (g["city"], g["cc"])) if g and settings["location"] == "on"
         else "Here: off" if settings["location"] == "off" else "Here: unavailable", True),
        ("Turn it off in Settings > Location.", True),
        ("TLS certificates are not verified.", True),
        ("", False),
        ("Cities: edit cities.py on the badge.", True),
        ("Clock: %s" % ("NTP synced" if clock.trusted() else "not synced"), True),
        ("Last error: %s" % (last_detail or "none")[:38], True),
    ]


# ---- main loop ------------------------------------------------------------------------

def update():
    global save_due, frames, fps_since, shot_pending
    if DEBUG_FPS:
        frames += 1
        if badge.ticks - fps_since >= FPS_EVERY_MS:
            if fps_since:
                print("[weather] %.1f fps" % (frames * 1000 / (badge.ticks - fps_since)))
            frames, fps_since = 0, badge.ticks
    handle_input()

    if job is not None:
        job.step(badge.ticks)
        if job.done():
            finish_refresh()
    elif refresh_due():
        start_refresh("auto")

    if save_due and badge.ticks >= save_due:
        save_due = 0
        State.save("weather", settings)

    ui.main(build_view())
    if overlay == "menu":
        items = []
        for label, key, values, names in MENU:
            value = names[values.index(settings[key])] if key else None
            items.append((label, value))
        ui.menu(items, menu_index, menu_first)
    elif overlay == "about":
        ui.about(about_lines())

    if shot_pending:
        shot_pending = False
        save_screenshot()


def on_exit():
    if job is not None:
        job.cancel()
    State.save("weather", settings)


selection = choose_initial()
run(update)
