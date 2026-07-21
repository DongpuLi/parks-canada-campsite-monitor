# Parks Canada campsite monitor

Checks the Parks Canada reservation results page once per hour for these exact Mkwesaqtuk/Cap-Rouge sites:

`17, 22, 23, 24, 25, 26, 27, 28, 29`

Stay: **September 4–7, 2026**, two people, one small tent.

## Important limitation

The Parks Canada reservation application is dynamic and may reject automated traffic or change its HTML. This project therefore:

- uses a real headless Chromium browser;
- receives the fully configured reservation-results URL through a GitHub Secret;
- checks only the requested site numbers;
- uploads a screenshot, HTML, and JSON result after each run;
- sends an error email if the site blocks the browser or the page can no longer be interpreted.

It does not reserve a site automatically. It only alerts you.

## 1. Create the repository

Create a private GitHub repository and upload all files in this folder. Private is preferable because the repository concerns your travel dates, although secrets remain encrypted either way.

## 2. Obtain `PARKS_SEARCH_URL`

1. Open the Parks Canada Reservation Service in your normal browser.
2. Search for Mkwesaqtuk/Cap-Rouge.
3. Set arrival to **2026-09-04**, departure to **2026-09-07**, two people, and tent equipment.
4. Continue until the page displays the campsite map/list and individual site numbers.
5. Copy the complete URL from the address bar.
6. In GitHub, open **Settings → Secrets and variables → Actions → New repository secret**.
7. Create a secret named `PARKS_SEARCH_URL` and paste the URL.

If the copied URL does not preserve the search after reopening it in an incognito window, the site stores the search in browser session state. In that case, run the workflow manually once and inspect the uploaded `latest.png`/`latest.html`; the navigation portion of `monitor.py` will need to be adapted to the current form. This cannot be reliably hard-coded without observing the live form.

## 3. Configure Gmail notification

For Gmail, enable two-step verification and create a Google App Password. Do not use your normal Gmail password.

Create these GitHub Actions secrets:

| Secret | Value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USERNAME` | your Gmail address |
| `SMTP_PASSWORD` | the 16-character Google App Password |
| `ALERT_EMAIL` | address that should receive alerts |
| `ALERT_FROM` | usually the same Gmail address |

The workflow still runs without email secrets, but alerts will only appear in the Actions log.

## 4. Run once manually

Open **Actions → Parks Canada campsite monitor → Run workflow**.

Then open the completed run and download the diagnostic artifact. Verify:

- `result.json` lists all nine site numbers;
- `latest.png` shows the correct campground and dates;
- no site is falsely classified as available.

If `result.json` says `Site number not found in rendered page`, inspect `latest.html`. Find the repeating HTML element that contains one complete campsite card and set `site_card_selector` in `config.json`, for example:

```json
"site_card_selector": "[data-testid='campsite-card']"
```

The actual selector must come from the current Parks Canada page; it is intentionally not invented here.

## 5. Hourly scheduling

The workflow runs at minute 17 of every hour. GitHub scheduled workflows may start later during periods of high load, so “hourly” is not guaranteed to run at the exact minute.

You can also run it at any time with **workflow_dispatch**.

## Files

- `monitor.py` — browser automation, site classification, email notification.
- `config.json` — campground, dates, site numbers, and text rules.
- `.github/workflows/monitor.yml` — hourly GitHub Actions workflow.
- `artifacts/` — screenshots, HTML, and JSON generated during a run.

## Responsible use

Keep the hourly interval. Do not increase the frequency aggressively. Respect Parks Canada’s terms, access controls, and any CAPTCHA or rate-limit response. If the service blocks automation, use the official availability notification instead of trying to bypass the block.
