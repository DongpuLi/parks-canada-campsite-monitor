# Parks Canada campsite monitor v5

The code remains fixed. Routine changes are made through GitHub repository
variables rather than editing Python or JSON files.

## Repository variables

Go to:

`Settings → Secrets and variables → Actions → Variables`

Create the existing Monitor 1 variables (their names are unchanged):

- `MONITOR_ENABLED`: `true` to run hourly, `false` to pause scheduled checks
- `PARKS_SEARCH_URL`: the complete Parks Canada reservation-results URL
  ⚠️ **Important:** Enter the **list view** URL, not the map view. The monitor
  extracts availability from the list view.
- `TARGET_SITES`: comma-separated site numbers, for example `17,22,23,24`
- `MONITOR_LABEL`: optional descriptive name, for example
  `Mkwesaqtuk/Cap-Rouge Sep 4–7`

Create these additional Monitor 2 variables:

- `PARKS_SEARCH_URL_2`: the second complete Parks Canada list-view results URL
- `TARGET_SITES_2`: comma-separated site numbers for Monitor 2
- `MONITOR_LABEL_2`: optional descriptive name for Monitor 2

Both monitors run independently in the same scheduled workflow. A failure in
one does not prevent the other from running. If either fails, its own diagnostic
artifact is uploaded and the workflow is marked failed after both checks finish.
Failures do not send email. Email alerts are sent only when a configured target
site is detected as available.

## Email secrets

Under the adjacent `Secrets` tab:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `ALERT_EMAIL`
- `ALERT_FROM`

## Configuration priority

The `monitor.py` script loads configuration in this priority order:

1. **GitHub Actions environment variables** (highest priority)
   - Monitor 1: `PARKS_SEARCH_URL`, `TARGET_SITES`, `MONITOR_LABEL`
   - Monitor 2 is mapped to the same script variables from
     `PARKS_SEARCH_URL_2`, `TARGET_SITES_2`, `MONITOR_LABEL_2`
   - Set via repository variables or workflow dispatch inputs
2. **config.json** (fallback values only)
   - `sites`: fallback site numbers if `TARGET_SITES` is not set
   - `party_size`, `equipment`, `campground`: informational fields
3. **Derived from URL** (highest priority for dates)
   - `arrival`, `departure`, `nights` extracted from `PARKS_SEARCH_URL`

**Keep `config.json` empty or minimal** — it exists only as an optional fallback.
All critical settings must be configured via GitHub Actions variables.

## Manual test

Open `Actions → Parks Canada campsite monitor → Run workflow`.

All six input fields are optional (URL, sites, and label for each monitor):

- Leave them blank to test the saved repository variables.
- Enter temporary values for either or both monitors without changing the saved
  hourly configuration. Any blank field falls back to its repository variable.

Manual runs work even when `MONITOR_ENABLED=false`.
Scheduled hourly runs only occur when `MONITOR_ENABLED=true`.

## Changing either monitored trip

No code edits are needed:

1. Replace that monitor's `PARKS_SEARCH_URL` or `PARKS_SEARCH_URL_2`.
2. Replace its `TARGET_SITES` or `TARGET_SITES_2`.
3. Optionally update its `MONITOR_LABEL` or `MONITOR_LABEL_2`.
4. Set `MONITOR_ENABLED=true`.

The URL controls the park, campground, dates, stay length, party size, equipment,
and other search settings.
