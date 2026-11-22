# Drawing for the Weather app (HIRES, 320x240). Everything here reads a plain
# `view` dict built by __init__.py, so layout can change without touching the
# data or input logic.

W, H = 320, 240

BG = color.rgb(13, 17, 23)
PANEL = color.rgb(22, 27, 34)
CELL = color.rgb(52, 63, 80)        # brightened: dark greys merge on the badge LCD
LINE = color.rgb(62, 70, 80)
TEXT = color.rgb(230, 237, 243)
MUTED = color.rgb(165, 173, 183)
DIM = color.rgb(125, 133, 143)
ACCENT = color.rgb(88, 166, 255)
WARN = color.rgb(255, 166, 87)
SHADE = color.rgb(0, 0, 0, 170)

TONES = {
    "sun": color.rgb(255, 172, 40),   # warmer: pure yellow reads green-ish on the LCD
    "moon": color.rgb(225, 222, 180),
    "cloud": color.rgb(190, 200, 214),
    "rain": color.rgb(96, 170, 255),
    "ice": color.rgb(150, 220, 255),
    "snow": color.rgb(215, 238, 255),
    "storm": color.rgb(255, 150, 50),
    "fog": color.rgb(160, 168, 178),
}

_fonts = {}


def init(icons, sans, small):
    _fonts["icons"] = icons
    _fonts["sans"] = sans
    _fonts["small"] = small


def tone(key, is_day=True):
    if key == "sun" and is_day is not None and not is_day:
        key = "moon"
    return TONES.get(key, TONES["cloud"])


# ---- primitives ------------------------------------------------------------------

def icon(char, x, y, size, pen):
    screen.font = _fonts["icons"]
    screen.pen = pen
    screen.text(char, x, y, size)


def sans(text, x, y, size, pen, align="left"):
    screen.font = _fonts["sans"]
    screen.pen = pen
    if align != "left":
        width, _ = screen.measure_text(text, size)
        x = x - width if align == "right" else x - width / 2
    screen.text(text, x, y, size)


def sans_width(text, size):
    screen.font = _fonts["sans"]
    return screen.measure_text(text, size)[0]


def small(text, x, y, pen, align="left"):
    screen.font = _fonts["small"]
    screen.pen = pen
    if align != "left":
        width, _ = screen.measure_text(text)
        x = x - width if align == "right" else x - width / 2
    screen.text(text, x, y)


def small_width(text):
    screen.font = _fonts["small"]
    return screen.measure_text(text)[0]


def box(x, y, w, h, pen, radius=4):
    screen.pen = pen
    screen.shape(shape.rounded_rectangle(x, y, w, h, radius, radius, radius, radius))


def fit(text, size, width):
    """Shorten text with an ellipsis until it fits `width` at MonaSans `size`."""
    if sans_width(text, size) <= width:
        return text
    while len(text) > 1 and sans_width(text + "...", size) > width:
        text = text[:-1]
    return text.rstrip() + "..."


# ---- screens -----------------------------------------------------------------------

def main(view):
    screen.pen = BG
    screen.rectangle(0, 0, W, H)
    _title(view)
    if view.get("slot") is None:
        _empty(view)
    else:
        _hero(view)
        _when(view)
        _strip(view)
    _footer(view)


def _title(view):
    x = 10
    if view["here"]:
        icon("p", x, 7, 15, ACCENT)
        x += 19
    name = fit(view["name"], 18, 228 - x)
    sans(name, x, 2, 18, TEXT)
    # position among locations, with up/down hints
    text = "%d/%d" % (view["index"] + 1, view["total"])
    right = W - 10
    small(text, right - 12, 9, MUTED, "right")
    screen.pen = MUTED if view["total"] > 1 else DIM
    screen.shape(shape.custom([vec2(right - 8, 10), vec2(right, 10), vec2(right - 4, 5)]))
    screen.shape(shape.custom([vec2(right - 8, 13), vec2(right, 13), vec2(right - 4, 18)]))
    screen.pen = LINE
    screen.line(0, 26, W, 26)


def _empty(view):
    message = view.get("empty") or "No forecast yet"
    icon("q" if view.get("busy") else "s", W / 2 - 24, 64, 48, DIM)
    sans(message, W / 2, 124, 16, MUTED, "center")
    detail = view.get("empty_detail")
    if detail:
        small(detail, W / 2, 150, DIM, "center")


def _hero(view):
    slot = view["slot"]
    pen = tone(slot["tone"], slot.get("d"))
    icon(slot["icon"], 14, 34, 92, pen)

    x = 122
    if view["mode"] == "day":
        hi, lo = slot["hi"], slot["lo"]
        sans(hi, x, 30, 46, TEXT)
        sans("/ " + lo, x + sans_width(hi, 46) + 6, 48, 22, MUTED)
    else:
        sans(slot["temp"], x, 30, 46, TEXT)
    sans(fit(slot["label"], 17, W - x - 8), x, 82, 17, pen)

    # facts in a fixed two-column grid
    for i, (char, text) in enumerate(slot["facts"][:4]):
        fx = x + (i % 2) * 100
        fy = 108 + (i // 2) * 19
        icon(char, fx, fy + 1, 13, MUTED)
        sans(fit(text, 14, 78), fx + 18, fy, 14, TEXT)


def _when(view):
    y = 152
    screen.pen = LINE
    screen.line(0, y - 4, W, y - 4)
    sans(view["when"], 10, y, 15, TEXT)
    if view.get("rel"):
        sans(view["rel"], 10 + sans_width(view["when"], 15) + 8, y + 1, 13, MUTED)
    tag = "HOURLY" if view["mode"] == "hour" else "DAILY"
    width = small_width(tag) + 10
    # nope glyphs cover rows +3..+10 of the text origin (measured on the badge);
    # the pill spans the MonaSans line (rows 157..166) with even padding.
    box(W - 10 - width, y + 3, width, 13, CELL, 3)
    small(tag, W - 15, y + 3, MUTED, "right")


def _strip(view):
    cells = view["strip"]
    if not cells:
        return
    count = view["strip_slots"]
    cw = (W - 12) // count
    x0 = 6
    top = 172
    for i, cell in enumerate(cells):
        x = x0 + i * cw
        if cell["selected"]:
            box(x + 1, top, cw - 2, 50, CELL, 5)
            # Accent bar on the top edge: the pixel font sits a little lower on
            # the badge than in the simulator, so nothing is drawn under the text.
            screen.pen = tone(cell["tone"], cell.get("d"))
            screen.rectangle(x + 8, top, cw - 16, 2)
        elif cell.get("divider"):
            screen.pen = LINE
            screen.line(x, top + 2, x, top + 48)
        # Rows within the 50 px cell, from glyphs measured on the badge (the
        # nope font draws on rows +2..+10 of its origin, descenders included):
        # label 176-183 | icon from 186 | values below, all inside 172..221.
        label_pen = TEXT if cell["selected"] else (ACCENT if cell.get("divider") else MUTED)
        small(cell["label"], x + cw / 2, top + 1, label_pen, "center")
        mark = cell.get("mark")
        if mark:
            # 12h strip: a line over AM labels, under PM labels (glyphs fill rows 175-183).
            lw = small_width(cell["label"])
            screen.pen = label_pen
            screen.rectangle(int(x + (cw - lw) / 2), top + 2 if mark == "am" else top + 12, int(lw), 1)
        value_pen = TEXT if cell["selected"] else MUTED
        pen = tone(cell["tone"], cell.get("d"))
        if cell.get("value2"):
            icon(cell["icon"], x + (cw - 15) / 2, top + 14, 15, pen)          # 186-200
            small(cell["value"], x + cw / 2, top + 28, value_pen, "center")    # 202-210
            small(cell["value2"], x + cw / 2, top + 38, MUTED if cell["selected"] else DIM, "center")  # 212-220
        else:
            icon(cell["icon"], x + (cw - 19) / 2, top + 14, 19, pen)          # 186-204
            small(cell["value"], x + cw / 2, top + 35, value_pen, "center")    # 209-217
    # arrows when more slots exist off screen
    screen.pen = MUTED
    if view["strip_more_left"]:
        screen.shape(shape.custom([vec2(4, top + 20), vec2(4, top + 30), vec2(0, top + 25)]))
    if view["strip_more_right"]:
        screen.shape(shape.custom([vec2(W - 4, top + 20), vec2(W - 4, top + 30), vec2(W, top + 25)]))


def _footer(view):
    y = 227   # nope glyphs land on rows 229..237 of the 226..239 footer band
    screen.pen = PANEL
    screen.rectangle(0, 226, W, H - 226)
    status = view.get("status")
    if status and status.get("busy"):
        progress = status.get("progress")
        small(status["text"], 8, y, ACCENT)
        bar_x = 8 + small_width(status["text"]) + 8
        bar_w = W - 8 - bar_x
        screen.pen = CELL
        screen.rectangle(bar_x, y + 4, bar_w, 4)
        screen.pen = ACCENT
        if progress is None:
            # indeterminate: a block sliding back and forth
            phase = (badge.ticks % 1600) / 800
            phase = phase if phase <= 1 else 2 - phase
            screen.rectangle(bar_x + int((bar_w - 30) * phase), y + 4, 30, 4)
        else:
            screen.rectangle(bar_x, y + 4, max(2, int(bar_w * progress)), 4)
        return
    left = view.get("updated") or ""
    pen = WARN if view.get("stale") else DIM
    small(left, 8, y, pen)
    if status and status.get("note"):
        small(status["note"], W - 8, y, ACCENT, "right")
    elif status and status.get("error"):
        width = small_width(status["error"])
        icon("s", W - 8 - width - 15, y - 1, 11, WARN)
        small(status["error"], W - 8, y, WARN, "right")
    else:
        small("Open-Meteo.com", W - 8, y, DIM, "right")


MENU_ROWS = 7   # rows shown at once; the list scrolls to keep the selection visible


def menu(items, selected, first=0, title="Settings", back="Back"):
    """Draw a menu panel; returns (y of the selected row, y of the key guide line) for popup()."""
    sel_ry = H // 2
    screen.pen = SHADE
    screen.rectangle(0, 0, W, H)
    rows = min(MENU_ROWS, len(items))
    x, w, row = 40, 240, 22
    guide = 18      # key guide under the list: "< Back" and "Select >"
    h = 34 + row * rows + 6 + guide
    y = (H - h) // 2
    box(x, y, w, h, PANEL, 8)
    icon("r", x + 12, y + 9, 15, MUTED)
    sans(title, x + 34, y + 6, 16, TEXT)
    small("%d/%d" % (selected + 1, len(items)), x + w - 14, y + 11, DIM, "right")
    for i in range(first, min(first + rows, len(items))):
        label, value = items[i][:2]
        arrows = items[i][2] if len(items[i]) > 2 else True   # False: a plain value, not a choice
        ry = y + 34 + (i - first) * row
        if i == selected:
            box(x + 6, ry - 2, w - 12, row - 2, CELL, 4)
            sel_ry = ry
        pen = TEXT if i == selected else MUTED
        sans(label, x + 16, ry, 14, pen)
        # Right arrow on the selected row when Right does something visible:
        # steps a value, or opens another screen (rows without a value).
        if i == selected and arrows:
            screen.pen = ACCENT
            screen.shape(shape.custom([vec2(x + w - 13, ry + 4), vec2(x + w - 13, ry + 14), vec2(x + w - 8, ry + 9)]))
        if value is not None:
            sans(value, x + w - 16, ry, 14, ACCENT if i == selected else TEXT, "right")
    # scroll hints on the panel's right edge
    screen.pen = MUTED
    cx = x + w - 6
    if first > 0:
        top = y + 32
        screen.shape(shape.custom([vec2(cx - 4, top + 5), vec2(cx + 4, top + 5), vec2(cx, top)]))
    if first + rows < len(items):
        bottom = y + h - 6 - guide
        screen.shape(shape.custom([vec2(cx - 4, bottom - 5), vec2(cx + 4, bottom - 5), vec2(cx, bottom)]))
    gy = y + h - guide
    screen.pen = LINE
    screen.line(x + 10, gy, x + w - 10, gy)
    small("< " + back, x + 14, gy + 3, DIM)
    small("Select >", x + w - 14, gy + 3, DIM, "right")
    return sel_ry, gy


def toast(title, detail, failed=False):
    """A centred popup over everything (screenshot result)."""
    w, h = 200, 50
    x, y = (W - w) // 2, (H - h) // 2
    box(x - 1, y - 1, w + 2, h + 2, WARN if failed else ACCENT, 9)
    box(x, y, w, h, PANEL, 8)
    sans(title, W // 2, y + 8, 16, WARN if failed else TEXT, "center")
    small(detail, W // 2, y + 31, DIM, "center")


def popup(items, selected, anchor):
    """A small menu beside the menu row, so the list behind stays visible.
    anchor is menu()'s result: below the row when it fits above the key guide, else above."""
    ry, bottom = anchor
    row = 20
    w, h = 116, 8 + row * len(items)
    x = 40 + 240 - 10 - w
    y = ry + 20 if ry + 20 + h <= bottom - 2 else ry - h - 4
    box(x - 1, y - 1, w + 2, h + 2, LINE, 7)
    box(x, y, w, h, PANEL, 6)
    for i, label in enumerate(items):
        iy = y + 4 + i * row
        if i == selected:
            box(x + 4, iy, w - 8, row - 2, CELL, 4)
        sans(label, x + 12, iy + 1, 14, TEXT if i == selected else MUTED)


def about(lines):
    screen.pen = SHADE
    screen.rectangle(0, 0, W, H)
    box(16, 14, W - 32, H - 28, PANEL, 8)
    sans("About", 30, 20, 16, TEXT)
    y = 46
    for text, muted in lines:
        if text:
            small(text, 30, y, MUTED if muted else TEXT)
        y += 13
    small("< to return", W - 30, H - 30, DIM, "right")
