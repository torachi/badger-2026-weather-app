# One refresh = Wi-Fi -> clock sync -> IP location (when due) -> forecast.
#
# The job advances one bounded step per frame so the screen keeps drawing and
# the buttons keep working. The forecast body (about 20 KB for 7 locations,
# roughly 3-4 s at the badge's TLS throughput) is read in small chunks across
# frames when the response exposes its socket, with a progress fraction for the
# footer; otherwise it falls back to reading it in one go.

import json
import gc

import clock

CHUNK = 512          # about 80 ms of data at the badge's ~6.5 KB/s TLS rate
REQUEST_TIMEOUT = 15
# Responses are untrusted: MicroPython's requests does not verify TLS
# certificates, so on a hostile network anyone can answer. Cap their size so a
# huge body cannot exhaust memory. A real 8-location forecast is about 22 KB
# and a location lookup about 0.4 KB.
MAX_FORECAST_BYTES = 64 * 1024
MAX_GEO_BYTES = 4 * 1024
WIFI_TIMEOUT_MS = 30000

IDLE, WIFI, SYNC, GEO, CONNECT, READ, DONE, FAILED = range(8)
LABELS = {
    WIFI: "Connecting Wi-Fi",
    SYNC: "Syncing clock",
    GEO: "Finding location",
    CONNECT: "Contacting Open-Meteo",
    READ: "Downloading",
}

try:
    import wifi
    import requests
except ImportError:  # desktop tests
    wifi = None
    requests = None

_ntp_done = False


def _sync_clock():
    """Set the RTC from NTP once per session; True when the RTC can be trusted."""
    global _ntp_done
    if _ntp_done:
        return True
    try:
        import ntptime
        ntptime.settime()
        _ntp_done = True
        clock.mark_synced()
    except Exception as e:  # noqa: BLE001 - any failure just means no NTP
        print("[weather] ntp failed:", e)
    return _ntp_done


def read_limited(response, limit):
    """The whole body, but never more than `limit` bytes (ValueError if longer)."""
    raw = getattr(response, "raw", None)
    if raw is None or not hasattr(raw, "read"):
        body = response.content
        if len(body) > limit:
            raise ValueError("response larger than %d bytes" % limit)
        return body
    chunks = []
    size = 0
    while True:
        chunk = raw.read(CHUNK)
        if not chunk:
            return b"".join(chunks)
        size += len(chunk)
        if size > limit:
            raise ValueError("response larger than %d bytes" % limit)
        chunks.append(chunk)


def short_error(e):
    """A footer-sized description of a refresh failure."""
    text = str(e)
    if text.startswith("HTTP "):
        return "Server error " + text[5:]
    if isinstance(e, ValueError):
        return "Too large" if "larger than" in text else "Bad response"
    if "timed out" in text.lower() or "ETIMEDOUT" in text or text == "110":
        return "Timed out"
    if isinstance(e, MemoryError):
        return "Out of memory"
    return "Network error"


class Refresh:
    """A single refresh run. Call step(ticks) once per frame until done()."""

    def __init__(self, want_geo, geo_url, forecast_url_for, expected_bytes, ticks, needed=None):
        self.state = WIFI
        self.want_geo = want_geo
        self.needed = needed  # fn() -> bool, asked once the clock is known; None = always fetch
        self.skipped = False
        self.geo_url = geo_url
        self.forecast_url_for = forecast_url_for  # fn(geo or None) -> (url, location count)
        self.expected = max(1, expected_bytes or 20000)
        self.started = ticks
        self.geo = None
        self.geo_error = None
        self.payload = None
        self.count = 0
        self.error = None
        self.detail = None
        self.received = 0
        self._response = None
        self._raw = None
        self._chunks = []
        self._ticks = ticks

    # -- status for the UI ------------------------------------------------------
    def done(self):
        return self.state in (DONE, FAILED)

    def label(self):
        return LABELS.get(self.state, "")

    def progress(self):
        if self.state == READ:
            return min(0.99, self.received / self.expected)
        return None

    # -- the steps -------------------------------------------------------------
    def step(self, ticks):
        self._ticks = ticks
        try:
            if self.state == WIFI:
                self._step_wifi(ticks)
            elif self.state == SYNC:
                _sync_clock()
                if self.needed is not None and not self.needed():
                    self.skipped = True
                    self.state = DONE
                else:
                    self.state = GEO if self.want_geo else CONNECT
            elif self.state == GEO:
                self._step_geo()
                self.state = CONNECT
            elif self.state == CONNECT:
                self._step_connect()
            elif self.state == READ:
                self._step_read()
        except Exception as e:  # noqa: BLE001 - reported on screen, retried later
            self._fail(short_error(e), "%s: %s" % (type(e).__name__, e))

    def _step_wifi(self, ticks):
        if wifi is None:
            raise OSError("no wifi module")
        if wifi.connect():
            self.state = SYNC
            return
        code, _ = wifi.status()
        if code is not None and code < 0 or ticks - self.started > WIFI_TIMEOUT_MS:
            self._fail("No Wi-Fi", "Wi-Fi did not connect: %s" % (wifi.status(),))

    def _get(self, url):
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            response.close()
            raise OSError("HTTP %d" % response.status_code)
        return response

    def _step_geo(self):
        import geo as geo_mod
        try:
            response = self._get(self.geo_url)
            try:
                self.geo = geo_mod.parse(json.loads(read_limited(response, MAX_GEO_BYTES)))
            finally:
                response.close()
            if self.geo is None:
                self.geo_error = "bad location data"
        except Exception as e:  # noqa: BLE001 - location is optional
            self.geo_error = "%s: %s" % (type(e).__name__, e)
            print("[weather] location failed:", self.geo_error)

    def _step_connect(self):
        url, self.count = self.forecast_url_for(self.geo)
        gc.collect()
        self._response = self._get(url)
        self._raw = getattr(self._response, "raw", None)
        if self._raw is None or not hasattr(self._raw, "read"):
            self._finish(read_limited(self._response, MAX_FORECAST_BYTES))
        else:
            self.state = READ

    def _step_read(self):
        chunk = self._raw.read(CHUNK)
        if chunk:
            self._chunks.append(chunk)
            self.received += len(chunk)
            if self.received > MAX_FORECAST_BYTES:
                self._chunks = []
                raise ValueError("response larger than %d bytes" % MAX_FORECAST_BYTES)
            return
        body = b"".join(self._chunks)
        self._chunks = []
        self._finish(body)

    def _finish(self, body):
        self._close()
        self.received = len(body)
        self.payload = json.loads(body)
        del body
        anchor = None
        first = self.payload[0] if isinstance(self.payload, list) and self.payload else self.payload
        if isinstance(first, dict) and isinstance(first.get("current"), dict):
            anchor = first["current"].get("time")
        if anchor:
            # current.time is the start of a 15-minute slot; aim for its middle.
            clock.anchor(int(anchor) + 450, self._ticks)
        self.state = DONE

    def _fail(self, message, detail=None):
        self._close()
        self.error = message
        self.detail = detail or message
        self.state = FAILED
        print("[weather] refresh failed:", self.detail)

    def _close(self):
        if self._response is not None:
            try:
                self._response.close()
            except Exception:  # noqa: BLE001
                pass
        self._response = None
        self._raw = None

    def cancel(self):
        self._close()
        self.state = FAILED
        self.error = "cancelled"
