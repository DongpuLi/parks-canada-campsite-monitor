from __future__ import annotations

import json
import os
import re
import smtplib
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright


ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
CONFIG_PATH = Path(os.getenv("MONITOR_CONFIG", ROOT / "config.json"))
SEARCH_URL = os.getenv("PARKS_SEARCH_URL", "").strip()
HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"


@dataclass(frozen=True)
class Result:
    site: int
    available: bool
    evidence: str


def log(message: str) -> None:
    print(message, flush=True)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing configuration file: {CONFIG_PATH}")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    required = [
        "campground",
        "arrival",
        "departure",
        "party_size",
        "equipment",
        "sites",
    ]
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing config key(s): {', '.join(missing)}")

    config["sites"] = [int(site) for site in config["sites"]]
    return config


def send_email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "465"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").replace(" ", "").strip()
    recipient = os.getenv("ALERT_EMAIL", "").strip()
    sender = os.getenv("ALERT_FROM", username).strip()

    if not all([username, password, recipient, sender]):
        log("Email settings are incomplete. Printing alert instead.")
        log(subject)
        log(body)
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    log(f"Sending email through {host}:{port}")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)

    log("Email sent")


def save_debug(page: Page, name: str) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    try:
        page.screenshot(
            path=str(ARTIFACTS / f"{name}.png"),
            full_page=True,
        )
        log(f"Saved screenshot: {name}.png")
    except Exception as exc:
        log(f"Could not save screenshot: {exc}")

    try:
        (ARTIFACTS / f"{name}.html").write_text(
            page.content(),
            encoding="utf-8",
        )
        log(f"Saved HTML: {name}.html")
    except Exception as exc:
        log(f"Could not save HTML: {exc}")

    try:
        body_text = page.locator("body").inner_text(timeout=10_000)
        (ARTIFACTS / f"{name}.txt").write_text(
            body_text,
            encoding="utf-8",
        )
        log(f"Saved text: {name}.txt")
    except Exception as exc:
        log(f"Could not save text: {exc}")


def click_consent(page: Page) -> None:
    selectors = [
        "button:has-text('I Consent')",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "button:has-text('Accepter')",
    ]

    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=800):
                log(f"Clicking consent button: {selector}")
                button.click(timeout=3_000)
                page.wait_for_timeout(800)
                return
        except Exception:
            continue


def switch_to_list_view(page: Page) -> None:
    log("Switching to List view")

    candidates = [
        page.get_by_role("button", name=re.compile(r"^list$", re.IGNORECASE)),
        page.get_by_role("tab", name=re.compile(r"^list$", re.IGNORECASE)),
        page.get_by_text(re.compile(r"^list$", re.IGNORECASE)),
    ]

    for locator in candidates:
        try:
            if locator.count() > 0:
                target = locator.first
                if target.is_visible(timeout=1_500):
                    target.click(timeout=5_000)
                    page.wait_for_timeout(2_000)
                    log("List view selected")
                    return
        except Exception:
            continue

    raise RuntimeError("Could not locate or click the List view control")


def ensure_available_filter(page: Page) -> None:
    """
    The screenshot shows a checkbox labelled 'Show available sites only'.
    When it is present, ensure it is checked.
    """
    try:
        checkbox = page.get_by_role(
            "checkbox",
            name=re.compile(
                r"show available sites only",
                re.IGNORECASE,
            ),
        ).first

        if checkbox.count() > 0 and checkbox.is_visible(timeout=1_500):
            if not checkbox.is_checked():
                log("Enabling 'Show available sites only'")
                checkbox.check(timeout=5_000)
                page.wait_for_timeout(1_500)
            else:
                log("'Show available sites only' is already enabled")
            return
    except Exception as exc:
        log(f"Could not verify available-only checkbox: {exc}")


def wait_for_list_content(page: Page) -> None:
    """
    Wait until List view contains at least one visible 'Available' label
    or an explicit no-results message.
    """
    log("Waiting for List results")

    available = page.get_by_text(
        re.compile(r"^available$", re.IGNORECASE),
        exact=True,
    )
    no_results = page.get_by_text(
        re.compile(
            r"(no sites|no results|no campsites|none available)",
            re.IGNORECASE,
        ),
    )

    for _ in range(20):
        try:
            if available.count() > 0:
                log(f"List results loaded with {available.count()} available row label(s)")
                return
            if no_results.count() > 0:
                log("List view reports no available results")
                return
        except Exception:
            pass
        page.wait_for_timeout(500)

    log("No explicit result marker found; continuing with DOM extraction")


def extract_available_sites(page: Page) -> list[int]:
    """
    Extract site numbers from rows/cards that contain an exact Available label.

    The browser-side code walks from each Available element to the nearest
    row-like container and extracts a standalone numeric site identifier.
    """
    log("Extracting available site numbers from List view")

    script = r"""
    () => {
      const clean = value => (value || "").replace(/\s+/g, " ").trim();

      const availableNodes = [...document.querySelectorAll("body *")]
        .filter(el => clean(el.textContent).toLowerCase() === "available");

      const output = [];
      const seen = new Set();

      function rowScore(el) {
        const text = clean(el.innerText);
        if (!text || text.length > 2500) return -100;

        let score = 0;
        const tag = el.tagName.toLowerCase();
        const role = (el.getAttribute("role") || "").toLowerCase();
        const cls = (el.className || "").toString().toLowerCase();

        if (["article", "li", "tr"].includes(tag)) score += 4;
        if (["row", "listitem"].includes(role)) score += 4;
        if (/(card|row|result|resource|site|inventory|list-item)/.test(cls)) score += 3;
        if (el.querySelector("img")) score += 1;
        if (el.querySelector("button, a, [role='button']")) score += 1;
        if (/\bavailable\b/i.test(text)) score += 2;
        if (text.length >= 10 && text.length <= 800) score += 2;

        return score;
      }

      function nearestRow(start) {
        let current = start;
        let best = start;
        let bestScore = rowScore(start);

        for (let depth = 0; current && depth < 8; depth += 1) {
          const score = rowScore(current);
          if (score > bestScore) {
            best = current;
            bestScore = score;
          }
          if (score >= 9) break;
          current = current.parentElement;
        }
        return best;
      }

      function extractNumber(row) {
        const text = clean(row.innerText);

        const labelled = text.match(
          /\b(?:site|campsite|emplacement)\s*#?\s*0*(\d{1,3})\b/i
        );
        if (labelled) return Number(labelled[1]);

        const elements = [...row.querySelectorAll("*")];
        for (const el of elements) {
          const value = clean(el.innerText);
          if (/^\d{1,3}$/.test(value)) {
            return Number(value);
          }
        }

        const leading = text.match(/^\s*0*(\d{1,3})\b/);
        if (leading) return Number(leading[1]);

        return null;
      }

      for (const node of availableNodes) {
        const row = nearestRow(node);
        const site = extractNumber(row);
        if (site === null || seen.has(site)) continue;

        seen.add(site);
        output.push({
          site,
          evidence: clean(row.innerText).slice(0, 1000),
          tag: row.tagName,
          className: (row.className || "").toString().slice(0, 500)
        });
      }

      return output;
    }
    """

    rows = page.evaluate(script)

    log(f"Extracted {len(rows)} available site row(s)")
    for row in rows:
        log(f"Available site detected: {row['site']}")

    return sorted(
        {
            int(row["site"])
            for row in rows
            if isinstance(row.get("site"), int)
        }
    )


def inspect_target_sites(
    available_sites: list[int],
    target_sites: list[int],
) -> list[Result]:
    available_set = set(available_sites)
    results: list[Result] = []

    for site in target_sites:
        if site in available_set:
            results.append(
                Result(
                    site=site,
                    available=True,
                    evidence=f"Site {site} is listed in the available-only List view",
                )
            )
            log(f"[Target site {site}] AVAILABLE")
        else:
            results.append(
                Result(
                    site=site,
                    available=False,
                    evidence=f"Site {site} is not listed in the available-only List view",
                )
            )
            log(f"[Target site {site}] not listed")

    return results


def detect_wrong_page(page: Page, config: dict[str, Any]) -> None:
    body = normalize(page.locator("body").inner_text(timeout=10_000)).lower()
    title = page.title()

    blocked_tokens = [
        "access denied",
        "forbidden",
        "captcha",
        "verify you are human",
        "unusual traffic",
        "request blocked",
    ]
    if any(token in body for token in blocked_tokens):
        raise RuntimeError(
            f"Reservation site blocked automation. Page title: {title}"
        )

    campground = config["campground"].lower()
    if campground not in body:
        raise RuntimeError(
            f"Expected campground '{config['campground']}' was not found "
            f"on the loaded page. Page title: {title}"
        )


def run(browser: Browser, config: dict[str, Any]) -> list[Result]:
    log("Creating browser context")
    context = browser.new_context(
        locale="en-CA",
        timezone_id="America/Halifax",
        viewport={"width": 1600, "height": 1200},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.set_default_timeout(12_000)

    try:
        log("Opening Parks Canada reservation page")
        response = page.goto(
            SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        if response is not None:
            log(f"HTTP status: {response.status}")
            if response.status >= 400:
                raise RuntimeError(
                    f"Reservation page returned HTTP {response.status}"
                )

        log(f"Page title: {page.title()}")
        page.wait_for_timeout(4_000)

        click_consent(page)
        detect_wrong_page(page, config)
        save_debug(page, "map-view")

        switch_to_list_view(page)
        ensure_available_filter(page)
        wait_for_list_content(page)
        save_debug(page, "list-view")

        available_sites = extract_available_sites(page)

        if not available_sites:
            body = normalize(page.locator("body").inner_text(timeout=10_000))
            if "available" in body.lower():
                raise RuntimeError(
                    "The List view contains Available labels, but no site "
                    "numbers could be extracted. Inspect list-view.html."
                )

        return inspect_target_sites(
            available_sites,
            config["sites"],
        )

    finally:
        context.close()


def write_report(
    config: dict[str, Any],
    results: list[Result],
    checked_at: str,
) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    report = {
        "checked_at_utc": checked_at,
        "campground": config["campground"],
        "arrival": config["arrival"],
        "departure": config["departure"],
        "party_size": config["party_size"],
        "equipment": config["equipment"],
        "results": [asdict(result) for result in results],
    }

    path = ARTIFACTS / "result.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    if not SEARCH_URL:
        log("PARKS_SEARCH_URL is missing")
        return 2

    checked_at = datetime.now(timezone.utc).isoformat()
    config = load_config()

    log("Starting Parks Canada campsite monitor")
    log(f"Campground: {config['campground']}")
    log(f"Stay: {config['arrival']} to {config['departure']}")
    log(f"Target sites: {config['sites']}")

    try:
        with sync_playwright() as playwright:
            log("Launching Chromium")
            browser = playwright.chromium.launch(headless=HEADLESS)
            try:
                results = run(browser, config)
            finally:
                log("Closing Chromium")
                browser.close()

        write_report(config, results, checked_at)

    except Exception as exc:
        message = (
            f"Campsite monitor failed at {checked_at}\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            "Download the GitHub Actions artifact and inspect "
            "map-view.png, list-view.png, and list-view.html."
        )
        log(message)

        try:
            send_email(
                "Parks Canada monitor needs attention",
                message,
            )
        except Exception as email_exc:
            log(
                "Failure email could not be sent: "
                f"{type(email_exc).__name__}: {email_exc}"
            )

        return 1

    available = [result for result in results if result.available]

    if available:
        sites = ", ".join(str(result.site) for result in available)
        body = (
            f"Available campsite(s): {sites}\n"
            f"Campground: {config['campground']}\n"
            f"Stay: {config['arrival']} to {config['departure']}\n"
            f"Party: {config['party_size']} people, "
            f"{config['equipment']}\n\n"
            f"Booking page:\n{SEARCH_URL}"
        )

        try:
            send_email(
                f"Campsite available: {sites} at "
                f"{config['campground']}",
                body,
            )
        except Exception as exc:
            log(
                "Availability was detected, but email failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return 1
    else:
        log("None of the target sites appears in the available-only List view")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
