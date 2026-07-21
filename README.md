# Parks Canada campsite monitor

Checks selected campsite numbers at Mkwesaqtuk/Cap-Rouge through a saved Parks Canada reservation-results URL.

## Monitored stay

- Arrival: 2026-09-04
- Departure: 2026-09-07
- Party: 2 people
- Equipment: one small tent
- Sites: 17, 22, 23, 24, 25, 26, 27, 28, 29

## Required GitHub Actions secrets

Repository → Settings → Secrets and variables → Actions:

- `PARKS_SEARCH_URL`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `ALERT_EMAIL`
- `ALERT_FROM`

For personal Gmail:

- `SMTP_HOST`: `smtp.gmail.com`
- `SMTP_PORT`: `465`
- `SMTP_USERNAME`: complete Gmail address
- `SMTP_PASSWORD`: Google App Password, not the normal account password
- `ALERT_FROM`: same Gmail address

## Run manually

Repository → Actions → Parks Canada campsite monitor → Run workflow.

Each run uploads:

- `initial.png`, `initial.html`, `initial.txt`
- `latest.png`, `latest.html`, `latest.txt`
- `result.json`

The script does not bypass CAPTCHA or access controls. If Parks Canada blocks the browser, the job fails and the diagnostic artifact preserves the returned page.
