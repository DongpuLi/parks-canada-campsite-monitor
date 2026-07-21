# Parks Canada campsite monitor v4

The code remains fixed. Routine changes are made through GitHub repository
variables rather than editing Python or JSON files.

## Repository variables

Go to:

`Settings → Secrets and variables → Actions → Variables`

Create:

- `MONITOR_ENABLED`: `true` to run hourly, `false` to pause scheduled checks
- `PARKS_SEARCH_URL`: the complete Parks Canada reservation-results URL
- `TARGET_SITES`: comma-separated site numbers, for example `17,22,23,24`
- `MONITOR_LABEL`: optional descriptive name, for example
  `Mkwesaqtuk/Cap-Rouge Sep 4–7`

## Email secrets

Under the adjacent `Secrets` tab:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `ALERT_EMAIL`
- `ALERT_FROM`

## Manual test

Open `Actions → Parks Canada campsite monitor → Run workflow`.

The three input fields are optional:

- Leave them blank to test the saved repository variables.
- Enter a temporary URL/sites/label to test another campground without changing
  the saved hourly monitor.

Manual runs work even when `MONITOR_ENABLED=false`.
Scheduled hourly runs only occur when `MONITOR_ENABLED=true`.

## Changing the monitored trip

No code edits are needed:

1. Replace `PARKS_SEARCH_URL`.
2. Replace `TARGET_SITES`.
3. Optionally update `MONITOR_LABEL`.
4. Set `MONITOR_ENABLED=true`.

The URL controls the park, campground, dates, stay length, party size, equipment,
and other search settings.
