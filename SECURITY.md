# Security

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub's private vulnerability reporting](https://github.com/torachi/badger-2026-weather-app/security/advisories/new)
rather than in a public issue.

## Threat model

The app runs on a conference badge and talks to two public HTTPS APIs
(api.open-meteo.com and free.freeipapi.com). It holds no secrets of its own;
the badge's Wi-Fi credentials are managed by the firmware and never read by
the app.

**TLS certificates are not verified.** MicroPython's `requests` module
([micropython-lib](https://github.com/micropython/micropython-lib/blob/master/python-ecosys/requests/requests/__init__.py))
opens HTTPS connections with `verify_mode = CERT_NONE`, and the app uses the
copy built into the badge firmware. Verified on a badge (firmware 2026-10-13,
MicroPython 1.29.0-preview): a request to `https://self-signed.badssl.com/`,
whose certificate is self-signed, succeeded with HTTP 200. On a hostile network (for example a shared
conference Wi-Fi), someone who can intercept traffic could read the
coordinates being requested and return forged forecasts or locations. The app
therefore treats every response as untrusted:

- response bodies are capped (64 KB for forecasts, 4 KB for the location);
- every number is checked to be finite and within a plausible range, and
  timestamps and UTC offsets are range-checked;
- any parsing failure is reported on screen and retried later instead of
  raising, because an uncaught exception reboots the badge;
- settings and cached data loaded from `/state` are validated, so a damaged
  file cannot stop the app from starting.

The worst a forged response can do is show wrong weather or a wrong "Here"
city. You can switch the IP lookup off in **Settings > Location**.

## CI

The workflow runs with read-only repository permissions, does not persist
credentials, pins its actions to commit SHAs (updated by Dependabot), and
verifies the Font Awesome download against a SHA-256 checksum.
