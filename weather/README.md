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
| Left / Right | Move the time cursor (hold to scroll) | Change the value |
| Select | Open the settings menu | Change the value or run the item; **Close** leaves the menu |
| Back (touch pad) | Hold 1.5 s to save a screenshot | Close the menu |
| Home | Return to the badge menu | - |

The first location, marked with a pin, is **Here**: the app estimates it from
your public IP address. That estimate is usually city-level at best, and a VPN,
phone tethering or a venue proxy can place you somewhere else entirely. When
the location cannot be found, the app opens on the city you last chose instead.

The settings menu changes the time step (hourly for 48 hours, or daily for 7
days), temperature (°C/°F), wind speed (m/s, km/h, mph, knots), rain (mm/in)
and clock (24h/12h) units. Units are converted on the badge, so changing them
needs no download. **Location** switches the IP lookup for **Here** off (and
deletes the stored estimate). **Refresh now** fetches immediately; **Screenshot** saves the
screen to `/weather_screen.raw` (RGB565, 320x240); **About** shows the data
sources, the current location estimate and the last error.

## Cities

Edit `cities.py` to change the cities after **Here** (up to 7). Use plain ASCII
names: the badge fonts have no Japanese glyphs.

```python
CITIES = [
    ("Tokyo", 35.6895, 139.69171),
    ("San Francisco", 37.77493, -122.41942),
]
```

Find coordinates with the
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
- The forecast refreshes every 30 minutes, but an automatic refresh waits until
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
