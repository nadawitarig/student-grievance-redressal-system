# Security Policy

This repository is an academic prototype and is not configured for production use by default.

## Reporting a vulnerability

Please avoid opening a public issue that reveals an exploitable vulnerability. Contact the maintainer privately through the professional profile linked in the README and include reproduction steps without real student data.

## Deployment checklist

- Replace the development secret key with a long random environment value.
- Serve the application behind HTTPS and set `COOKIE_SECURE=1`.
- Use a production WSGI server and a supported production database.
- Restrict administrator creation and protect operational backups.
- Complete institutional privacy, retention and access-control reviews.
