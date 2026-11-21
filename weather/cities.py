# Registered cities for the Weather app.
#
# Each entry is (display name, latitude, longitude). Names must be plain ASCII
# (the badge fonts have no Japanese glyphs) and short enough to fit the title
# bar, about 18 characters. Up and Down cycle through these after "Here", the
# location estimated from the badge's public IP address.
#
# At most 7 entries are used: together with "Here" that makes 8 locations,
# which the app fetches from Open-Meteo in a single request.
# Coordinates from the Open-Meteo geocoding API (geocoding-api.open-meteo.com).

CITIES = [
    ("Tokyo", 35.6895, 139.69171),
    ("Osaka", 34.69379, 135.50107),
    ("Sapporo", 43.06667, 141.35),
    ("Fukuoka", 33.6, 130.41667),
    ("Naha", 26.213, 127.67851),
    ("San Francisco", 37.77493, -122.41942),
]
