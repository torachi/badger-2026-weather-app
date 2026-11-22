# Weather

See the forecast for where you are and your favourite cities, hour by hour or day by day.

## Requirements

- Wi-Fi details in `secrets.py` (set them in the Settings app or over USB).
- Internet access to `api.open-meteo.com` (forecast) and `free.freeipapi.com`
  (location from your public IP address).
- The October 2026 badge firmware or later.

## Using it

The bottom row of physical buttons is Left, Right and Select (the return arrow);
Up and Down are on the right edge.

| Button | Main screen | Settings menu |
| --- | --- | --- |
| Up / Down | Switch location | Move between items (the list scrolls) |
| Left | Move the time cursor back (hold to scroll) | Go back (closes the settings menu) |
| Right | Move the time cursor forward (hold to scroll) | Select: run the item, open it, or step to the next value |
| Select | Tap: open the settings menu. Hold 1.5 s: screenshot | Tap: same as Right. Hold 1.5 s: screenshot |
| Home | Return to the badge menu | - |

The first location, marked with a pin, is **Here**: the app estimates it from
your public IP address. That estimate is usually city-level at best, and a VPN,
phone tethering or a venue proxy can place you somewhere else entirely. When
the location cannot be found, the app opens on the city you last chose instead.

The settings menu changes the time step (hourly for 48 hours, or daily for 7
days), the **Units** of temperature (°C/°F), wind speed (m/s, km/h, mph,
knots) and rain (mm/in), and the clock (24h/12h). Units are converted on the badge, so changing them
needs no download. **Cities** edits the city list and holds **Location**,
which switches the IP lookup for **Here** off (and deletes the stored
estimate); see below. **Refresh now** fetches immediately; **About** shows the data
sources, the current location estimate and the last error. Each menu shows its
keys at the bottom (Left: back, Right: select). Holding Select for 1.5 s saves
the screen to `/weather_screen.raw` (RGB565, 320x240).

## Cities

Add, remove and reorder the cities after **Here** (up to 7) in
**Settings > Cities**. **+ Add city** offers the cities in `catalog.py` by
region. The list is saved to `/state/weather_cities.json`; `cities.py` is only
the starting list.

To offer another city, add it to `catalog.py` with a plain ASCII name (the badge
fonts have no Japanese glyphs). Find coordinates with the
[Open-Meteo geocoding API](https://open-meteo.com/en/docs/geocoding-api), for
example `https://geocoding-api.open-meteo.com/v1/search?name=Kyoto&count=1`.

## Privacy and security

Your public IP address is sent to freeipapi.com (only while Location is on)
and to Open-Meteo, together with the coordinates of the locations shown.
"Here" is rounded to about 1 km. The badge does not verify TLS certificates, so
every response is size-capped and validated before use. See the repository's
README and SECURITY.md for details.

## How it works

- All locations come from one Open-Meteo request (about 20 KB, 3 to 4 seconds
  on the badge). The body is read in small pieces between frames, so the
  buttons keep working and the footer shows progress.
- The forecast refreshes every 30 minutes and at the top of every hour, but an automatic refresh waits until
  the buttons have been idle for 8 seconds. The location is re-estimated every
  6 hours. Failures retry after 1, 2 and then 5 minutes.
- The last forecast and your settings are kept in `/state`, so the app shows
  something immediately, even offline, with the time of the last update.
- The badge clock is set over NTP before it is trusted.

## Credits

- Weather data by [Open-Meteo.com](https://open-meteo.com/),
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); values rounded and
  converted. Open-Meteo's free API is for non-commercial use.
- IP location by [freeipapi.com](https://freeipapi.com/).
- Weather icons from [Font Awesome Free](https://fontawesome.com/) 7.3.1
  SVGs (CC BY 4.0), converted by `tools/build_weather_icons.py`; see
  `ICONS_LICENSE.txt`.
