# Test fixtures

API responses captured on a GitHub Universe 2026 badge on 2026-11-21.

| File | Source | Licence and changes |
| --- | --- | --- |
| `open_meteo_7.json` | [Open-Meteo.com](https://open-meteo.com/) forecast API, one request for 7 locations | Weather data by Open-Meteo.com, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Values unchanged; the locations were reordered to match the app's request order and `location_id` renumbered. |
| `open_meteo_6.json` | The same response without the first location | As above. |
| `freeipapi.json` | Shape of a [freeipapi.com](https://freeipapi.com/) response | Every identifying field was replaced: the IP address is from the RFC 5737 documentation range, the ASN from the RFC 5398 documentation range, and the city, coordinates and postal code are an arbitrary example (Chiyoda, Tokyo). |
