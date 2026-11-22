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
REFRESH_EVERY_S = 30 * 60      # forecast age that triggers an automatic refresh (also at every local :00)
GEO_EVERY_S = 6 * 60 * 60      # how often to re-estimate "Here"
IDLE_BEFORE_AUTO_MS = 8000     # auto refreshes wait for the buttons to be idle
RETRY_MS = (60_000, 120_000, 300_000)
REPEAT_DELAY_MS = 380          # left/right auto-repeat when held
REPEAT_EVERY_MS = 110
SAVE_DELAY_MS = 3000           # write the selected city after this much quiet
HOUR_SLOTS = 7             # "13:00" labels need ~44 px cells
DAY_SLOTS = 7



def _city(name, lat, lon):
    return {"key": name, "name": name, "lat": lat, "lon": lon, "here": False}


def _load_cities():
    """The registered cities from /state (Settings > Cities), else the defaults in cities.py."""
    data = {"list": None}
    State.load("weather_cities", data)
    out, seen = [], set()
    entries = data.get("list")
    for entry in entries if isinstance(entries, list) else ():
        # A damaged or hand-edited file must not stop the app: skip anything odd.
        if (isinstance(entry, (list, tuple)) and len(entry) == 3 and isinstance(entry[0], str)
                and 0 < len(entry[0]) <= 24 and entry[0] not in seen and entry[0] != "here"
                and all(isinstance(v, (int, float)) for v in entry[1:])
                and -90 <= entry[1] <= 90 and -180 <= entry[2] <= 180):
            seen.add(entry[0])
            out.append(_city(*entry))
    return out[:MAX_CITIES] if out else [_city(*c) for c in CITIES[:MAX_CITIES]]


def save_cities():
    State.save("weather_cities", {"list": [[c["name"], c["lat"], c["lon"]] for c in CITY_LIST]})


CITY_LIST = _load_cities()

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
        if key not in {"%.3f,%.3f" % (c["lat"], c["lon"]) for c in CITY_LIST}:
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
overlay = None            # None, "menu", "about" or a Cities screen (see CITY_SCREENS)
menu_index = 0
menu_first = 0            # first visible menu row (the list scrolls)
# Holding Select for SHOT_HOLD_MS saves the screen.
# Select acts on release (see TapHold) so that a hold never also acts.
TAP_GRACE_MS = 120        # a press lasts at least this long, in case held() lags pressed()
shot_pending = False
shot_note_until = 0
shot_note = None          # (title, detail, failed) shown in a popup after a screenshot
SHOT_NOTE_MS = 2000
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


def is_stale(now):
    """True when the forecast is REFRESH_EVERY_S old or a local :00 has passed since it was fetched."""
    at = cache.get("at")
    if now is None or not at or now < at:
        return True
    off = local_offset()
    return now - at >= REFRESH_EVERY_S or (now + off) // 3600 != (at + off) // 3600


def cache_fresh():
    now = clock.now(badge.ticks)
    return bool(cache["data"]) and not is_stale(now)


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
    return is_stale(now) and badge.ticks - last_input >= IDLE_BEFORE_AUTO_MS


# ---- input -------------------------------------------------------------------------

def any_input():
    for button in (BUTTON_UP, BUTTON_DOWN, BUTTON_LEFT, BUTTON_RIGHT, BUTTON_SELECT):
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
    ("Units", None, None, None),
    ("Clock", "clock", units.CLOCKS, units.CLOCKS),
    ("Cities", None, None, None),
    ("Refresh now", None, None, None),
    ("About", None, None, None),
)

# Settings > Units, a submenu of value rows (same shape as MENU entries).
UNITS_MENU = (
    ("Temperature", "temp", units.TEMP_UNITS, ("°C", "°F")),
    ("Wind", "wind", units.WIND_UNITS, units.WIND_UNITS),
    ("Rain", "rain", units.RAIN_UNITS, units.RAIN_UNITS),
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
    """Menu keys (all screens): Up/Down move, Left goes back, Right (or Select) selects.
    On a value row, selecting steps to the next value."""
    global overlay, menu_index, shot_pending
    entry = MENU[menu_index]
    if badge.pressed(BUTTON_UP):
        menu_index = (menu_index - 1) % len(MENU)
        scroll_menu()
    elif badge.pressed(BUTTON_DOWN):
        menu_index = (menu_index + 1) % len(MENU)
        scroll_menu()
    elif badge.pressed(BUTTON_LEFT):
        close_menu()
    elif entry[1] and (badge.pressed(BUTTON_RIGHT) or SELECT_KEY.tapped):
        cycle(entry, 1)
    elif badge.pressed(BUTTON_RIGHT) or SELECT_KEY.tapped:
        label = entry[0]
        if label == "Refresh now":
            close_menu()
            start_refresh("manual", want_geo=True)
        elif label == "About":
            overlay = "about"
        elif label == "Units":
            open_screen("units", 0)
        elif label == "Cities":
            open_cities(0)


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
            selection = settings.get("last_city") or CITY_LIST[0]["key"]


def close_menu():
    global overlay, cities_dirty
    overlay = None
    State.save("weather", settings)
    if cities_dirty:
        cities_dirty = False
        start_refresh("manual", want_geo=False)


# ---- Settings > Cities ---------------------------------------------------------------
#
# "units"   Temperature / Wind / Rain (Settings > Units, not a Cities screen,
#           but it shares the list handling)
# "cities"  Location (the IP-based "Here" on/off), the registered cities, then
#           "+ Add city" (while fewer than MAX_CITIES)
# "city"    Move up / Move down / Remove for one registered city
# "regions" catalog regions;  "catalog"  the cities of one region (Select adds)

CITY_SCREENS = ("units", "cities", "city", "regions", "catalog")
sub_index = 0
sub_first = 0
editing = 0               # index in CITY_LIST on the "city" screen
region = 0                # index in catalog.REGIONS on the "catalog" screen
cities_dirty = False      # list changed: refetch when the menu closes
city_first = 0            # scroll of the Cities list drawn behind the city popup


def open_cities(city):
    """Open the Cities list with registered city `city` (len(CITY_LIST) = "+ Add city") selected."""
    open_screen("cities", city + 1)


def toggle_location():
    settings["location"] = "off" if settings["location"] == "on" else "on"
    set_location(settings["location"] == "on")


def open_screen(name, index):
    global overlay, sub_index, sub_first
    overlay = name
    sub_index = index
    sub_first = 0
    scroll_sub()


def sub_items():
    """(title, [(label, value, arrows), ...]) for the open Cities screen."""
    if overlay == "units":
        return "Units", [(label, names[values.index(settings[key])], True)
                         for label, key, values, names in UNITS_MENU]
    if overlay == "cities":
        return cities_items()
    if overlay == "city":
        items = [("Move up", None, False), ("Move down", None, False)]
        if len(CITY_LIST) > 1:
            items.append(("Remove", None, False))
        return CITY_LIST[editing]["name"], items
    import catalog
    if overlay == "regions":
        return "Add city", [(r[0], None, True) for r in catalog.REGIONS]
    names = {c["name"] for c in CITY_LIST}
    title, entries = catalog.REGIONS[region]
    return title, [(e[0], "Added" if e[0] in names else None, False) for e in entries]


def cities_items():
    """(title, items) of the Cities list, also drawn behind the city popup."""
    items = [("Location", "On" if settings["location"] == "on" else "Off", True)]
    items += [(c["name"], None, True) for c in CITY_LIST]
    if len(CITY_LIST) < MAX_CITIES:
        items.append(("+ Add city", None, True))
    return "Cities %d/%d" % (len(CITY_LIST), MAX_CITIES), items


def list_first(index, first, count):
    """Scroll offset keeping row `index` of `count` inside ui.MENU_ROWS rows."""
    rows = min(ui.MENU_ROWS, count)
    if index < first:
        first = index
    elif index >= first + rows:
        first = index - rows + 1
    return max(0, min(first, count - rows))


def scroll_sub():
    global sub_first
    sub_first = list_first(sub_index, sub_first, len(sub_items()[1]))


def cities_changed():
    """Save the list, and stop a download whose URL no longer matches it."""
    global job, selection, cities_dirty
    save_cities()
    cities_dirty = True
    if job is not None:
        job.cancel()
        job = None
    keys = [c["key"] for c in CITY_LIST]
    if settings.get("last_city") not in keys:
        settings["last_city"] = keys[0]
    if selection != "here" and selection not in keys:
        selection = settings["last_city"]


def sub_back():
    if overlay == "units":
        open_menu_at("Units")
    elif overlay == "cities":
        open_menu_at("Cities")
    elif overlay == "city":
        open_cities(editing)
    elif overlay == "regions":
        open_cities(len(CITY_LIST))
    else:
        open_screen("regions", region)


def open_menu_at(label):
    global overlay, menu_index
    overlay = "menu"
    menu_index = [m[0] for m in MENU].index(label)
    scroll_menu()


def sub_select():
    global editing, region, city_first
    _, items = sub_items()
    label = items[sub_index][0]
    if overlay == "units":
        cycle(UNITS_MENU[sub_index], 1)
    elif overlay == "cities":
        if label == "Location":
            toggle_location()
        elif label == "+ Add city":
            open_screen("regions", 0)
        else:
            editing = sub_index - 1
            city_first = sub_first
            open_screen("city", 0)
    elif overlay == "city":
        if label == "Remove":
            CITY_LIST.pop(editing)
            cities_changed()
            open_cities(min(editing, len(CITY_LIST) - 1))
            return
        to = editing - 1 if label == "Move up" else editing + 1
        if 0 <= to < len(CITY_LIST):
            CITY_LIST[editing], CITY_LIST[to] = CITY_LIST[to], CITY_LIST[editing]
            editing = to
            cities_changed()
    elif overlay == "regions":
        region = sub_index
        open_screen("catalog", 0)
    else:
        import catalog
        name, lat, lon = catalog.REGIONS[region][1][sub_index]
        if any(c["name"] == name for c in CITY_LIST):
            return
        if len(CITY_LIST) < MAX_CITIES:
            CITY_LIST.append(_city(name, lat, lon))
            cities_changed()
            open_cities(len(CITY_LIST) - 1)


def handle_cities():
    global sub_index
    count = len(sub_items()[1])
    if badge.pressed(BUTTON_UP):
        sub_index = (sub_index - 1) % count
        scroll_sub()
    elif badge.pressed(BUTTON_DOWN):
        sub_index = (sub_index + 1) % count
        scroll_sub()
    elif SELECT_KEY.tapped or badge.pressed(BUTTON_RIGHT):
        sub_select()
    elif badge.pressed(BUTTON_LEFT):
        sub_back()


def handle_input():
    global overlay, last_input, menu_index
    if any_input():
        last_input = badge.ticks
    # Holding Select saves a screenshot on every screen, so it acts on release
    # (TapHold.tapped) rather than on press.
    watch_screenshot_hold()
    if overlay == "about":
        if badge.pressed(BUTTON_LEFT) or badge.pressed(BUTTON_RIGHT) or SELECT_KEY.tapped:
            overlay = "menu"
        return
    if overlay == "menu":
        handle_menu()
        return
    if overlay in CITY_SCREENS:
        handle_cities()
        return
    if SELECT_KEY.tapped:
        overlay = "menu"
        menu_index = 0
        scroll_menu()
        return
    if badge.pressed(BUTTON_UP):
        move_city(-1)
    elif badge.pressed(BUTTON_DOWN):
        move_city(1)
    if repeat(BUTTON_LEFT):
        move_time(-1)
    elif repeat(BUTTON_RIGHT):
        move_time(1)


class TapHold:
    """One action per press: a tap (.tapped, on release) or, held for SHOT_HOLD_MS,
    a screenshot. Only the press edge starts a press, so it can never count twice
    even if held() lags pressed() by a frame."""

    def __init__(self, button):
        self.button = button
        self.since = None       # ticks of the press, None when up
        self.shot = False       # this press already saved a screenshot
        self.tapped = False

    def update(self):
        global shot_pending
        self.tapped = False
        if badge.pressed(self.button):
            self.since = badge.ticks
            self.shot = False
        if self.since is None:
            return
        if badge.held(self.button) or badge.pressed(self.button) or badge.ticks - self.since < TAP_GRACE_MS:
            if not self.shot and badge.ticks - self.since >= SHOT_HOLD_MS:
                shot_pending = True
                self.shot = True
        else:
            self.tapped = not self.shot
            self.since = None


SELECT_KEY = TapHold(BUTTON_SELECT)


def watch_screenshot_hold():
    SELECT_KEY.update()


def save_screenshot():
    """Write the frame just drawn (screen.raw) to SHOT_PATH, then show the result
    in a popup for SHOT_NOTE_MS (drawn from the next frame, so it is not in the file)."""
    global shot_note_until, shot_note
    try:
        with open(SHOT_PATH, "wb") as f:
            f.write(screen.raw)
        print("[weather] screenshot saved to %s (%dx%d)" % (SHOT_PATH, screen.width, screen.height))
        shot_note = ("Screenshot saved", SHOT_PATH, False)
    except OSError as e:
        print("[weather] screenshot failed:", e)
        shot_note = ("Screenshot failed", str(e)[:30], True)
    # Writing 150 KB to flash can take longer than SHOT_NOTE_MS, and badge.ticks
    # is read per frame, so the timer starts on the first frame that shows it.
    shot_note_until = None


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
            cell["divider"] = hh == 0 and mm == 0 and off != 0
            cell["label"] = units.fmt_hour(hh, mm, settings["clock"])
            if settings["clock"] == "12h":
                cell["mark"] = "am" if hh < 12 else "pm"   # overline / underline
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
                # The hour of the selected strip cell, not the clock or the current-conditions slot.
                stamp = forecast.hour_slot(record, now, offset, live=False)["time"]
                view["when"] = fmt_local(stamp, record["off"])
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
    if job is not None:
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
        ("Turn it off in Settings > Cities > Location.", True),
        ("TLS certificates are not verified.", True),
        ("", False),
        ("Cities: Settings > Cities (saved in /state).", True),
        ("Clock: %s" % ("NTP synced" if clock.trusted() else "not synced"), True),
        ("Last error: %s" % (last_detail or "none")[:38], True),
    ]


# ---- main loop ------------------------------------------------------------------------

def update():
    global save_due, frames, fps_since, shot_pending, city_first, shot_note, shot_note_until
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
            if label == "Cities":
                items.append((label, "%d/%d" % (len(CITY_LIST), MAX_CITIES), True))
                continue
            # value rows step on Right; Units and About open another screen
            items.append((label, value, key is not None or label in ("Units", "About")))
        ui.menu(items, menu_index, menu_first, back="Close")
    elif overlay == "city":
        # The Cities list stays behind a small popup, so Move up/down shows at once.
        title, items = cities_items()
        city_first = list_first(editing + 1, city_first, len(items))
        anchor = ui.menu(items, editing + 1, city_first, title)
        ui.popup([label for label, _, _ in sub_items()[1]], sub_index, anchor)
    elif overlay in CITY_SCREENS:
        title, items = sub_items()
        ui.menu(items, sub_index, sub_first, title)
    elif overlay == "about":
        ui.about(about_lines())

    if shot_pending:
        shot_pending = False
        save_screenshot()
    elif shot_note:
        if shot_note_until is None:
            shot_note_until = badge.ticks + SHOT_NOTE_MS
        if badge.ticks < shot_note_until:
            ui.toast(*shot_note)
        else:
            shot_note = None


def on_exit():
    if job is not None:
        job.cancel()
    State.save("weather", settings)


selection = choose_initial()
run(update)
