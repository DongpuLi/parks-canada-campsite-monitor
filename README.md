# Parks Canada campsite monitor — List view

This version opens the saved reservation-results URL, switches from Map to List,
enables "Show available sites only", extracts the displayed site numbers, and
checks whether any target site is present.

## Target sites

17, 22, 23, 24, 25, 26, 27, 28, 29

## Stay

- Arrival: 2026-09-04
- Departure: 2026-09-07
- Two people
- One small tent

## GitHub Actions secrets

- PARKS_SEARCH_URL
- SMTP_HOST
- SMTP_PORT
- SMTP_USERNAME
- SMTP_PASSWORD
- ALERT_EMAIL
- ALERT_FROM

For Gmail:

- SMTP_HOST = smtp.gmail.com
- SMTP_PORT = 465
- SMTP_USERNAME = full Gmail address
- SMTP_PASSWORD = Google App Password
- ALERT_FROM = same Gmail address

Each run uploads map-view and list-view screenshots, HTML, text, and result.json.
