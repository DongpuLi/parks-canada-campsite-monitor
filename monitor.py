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
    source: str


def log(message: str) -> None:
    print(message, flush=True)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config.example.json to config.json and edit it."
        )

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    required = [
        "campground",
        "arrival",
        "departure",
        "party_size",
        "equipment",
        "sites",
        "available_keywords",
        "unavailable_keywords",
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
        log("Email secrets are incomplete. Alert content follows:")
        log(subject)
        log(body)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)

    log(f"Sending email to {recipient} through {host}:{port}")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(username, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(msg)

    log("Email sent")


def save_debug(page: Page, name: str) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    png = ARTIFACTS / f"{name}.png"
    html = ARTIFACTS / f"{name}.html"
    text = ARTIFACTS / f"{name}.txt"

    try:
        page.screenshot(path=str(png), full_page=True)
        log(f"Saved screenshot: {png}")
    except Exception as exc:
        log(f"Could not save screenshot: {exc}")

    try:
        html.write_text(page.content(), encoding="utf-8")
        log(f"Saved HTML: {html}")
    except Exception as exc:
        log(f"Could not save HTML: {exc}")

    try:
        body = page.locator("body").inner_text(timeout=10_000)
        text.write_text(body, encoding="utf-8")
        log(f"Saved rendered text: {text}")
    except Exception as exc:
        log(f"Could not save rendered text: {exc}")


def click_cookie_banner(page: Page, selectors: list[str]) -> None:
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=700):
                log(f"Clicking cookie/consent element: {selector}")
                button.click(timeout=2_000)
                return
        except Exception:
            continue


def detect_blocked_page(page: Page) -> None:
    title = page.title()
    body = normalize(page.locator("body").inner_text(timeout=10_000))
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
            f"Reservation website blocked automation or requested verification. "
            f"Page title: {title}"
        )


def collect_candidate_cards(page: Page, sites: list[int], explicit_selector: str) -> list[dict[str, Any]]:
    """
    Extract possible campsite cards in one browser-side pass.

    This avoids the old implementation's repeated locator.count(),
    ancestor traversal, and inner_text() calls for every site.
    """
    log("Scanning rendered page for campsite cards")

    script = r"""
    ({ sites, explicitSelector }) => {
      const wanted = new Set(sites.map(String));
      const clean = value => (value || "").replace(/\s+/g, " ").trim();

      function siteNumbers(text) {
        const out = new Set();
        const patterns = [
          /\b(?:site|campsite|emplacement)\s*#?\s*0*(\d{1,4})\b/gi,
          /^\s*#?\s*0*(\d{1,4})\s*$/gim
        ];
        for (const pattern of patterns) {
          let match;
          while ((match = pattern.exec(text)) !== null) {
            out.add(String(Number(match[1])));
          }
        }
        return [...out].filter(number => wanted.has(number));
      }

      function scoreElement(el) {
        let score = 0;
        const tag = el.tagName.toLowerCase();
        const role = (el.getAttribute("role") || "").toLowerCase();
        const cls = (el.className || "").toString().toLowerCase();

        if (["article", "li"].includes(tag)) score += 3;
        if (role === "listitem") score += 3;
        if (/(card|site|campsite|result|inventory|availability|unit)/.test(cls)) score += 3;
        if (el.querySelector("button, a, [role='button']")) score += 2;

        const textLength = clean(el.innerText).length;
        if (textLength >= 15 && textLength <= 1600) score += 2;
        if (textLength > 3000) score -= 5;

        return score;
      }

      function nearestCard(start) {
        let current = start;
        let best = start;
        let bestScore = scoreElement(start);

        for (let depth = 0; current && depth < 7; depth += 1, current = current.parentElement) {
          const score = scoreElement(current);
          if (score > bestScore) {
            best = current;
            bestScore = score;
          }
          if (score >= 7) break;
        }
        return best;
      }

      let elements = [];
      if (explicitSelector) {
        try {
          elements = [...document.querySelectorAll(explicitSelector)];
        } catch (error) {
          return { selectorError: String(error), cards: [] };
        }
      } else {
        elements = [...document.querySelectorAll(
          "article, li, [role='listitem'], [class*='card'], [class*='site'], " +
          "[class*='result'], [class*='inventory'], [class*='availability'], " +
          "button, a, span, div"
        )];
      }

      const cards = [];
      const seen = new Set();

      for (const element of elements) {
        const ownText = clean(element.innerText);
        if (!ownText || ownText.length > 5000) continue;

        const numbers = siteNumbers(ownText);
        if (!numbers.length) continue;

        const card = explicitSelector ? element : nearestCard(element);
        const text = clean(card.innerText);
        if (!text || text.length > 5000) continue;

        const key = text.slice(0, 1000);
        if (seen.has(key)) continue;
        seen.add(key);

        const controls = [...card.querySelectorAll("button, a, [role='button']")].slice(0, 30).map(control => ({
          text: clean(control.innerText),
          ariaLabel: clean(control.getAttribute("aria-label")),
          title: clean(control.getAttribute("title")),
          disabled:
            control.hasAttribute("disabled") ||
            control.getAttribute("aria-disabled") === "true"
        }));

        cards.push({
          sites: siteNumbers(text),
          text,
          controls,
          tag: card.tagName,
          className: (card.className || "").toString().slice(0, 500)
        });
      }

      return { selectorError: null, cards: cards.slice(0, 200) };
    }
    """

    payload = page.evaluate(
        script,
        {
            "sites": sites,
            "explicitSelector": explicit_selector,
        },
    )

    if payload.get("selectorError"):
        raise ValueError(
            f"Invalid site_card_selector: {payload['selectorError']}"
        )

    cards = payload.get("cards", [])
    log(f"Found {len(cards)} candidate card(s)")
    return cards


def classify_card(
    card: dict[str, Any],
    available_words: list[str],
    unavailable_words: list[str],
) -> tuple[bool, str]:
    text = normalize(card.get("text", ""))
    available_words_n = [normalize(word) for word in available_words]
    unavailable_words_n = [normalize(word) for word in unavailable_words]

    has_unavailable = any(word and word in text for word in unavailable_words_n)
    has_available = any(word and word in text for word in available_words_n)

    actionable = False
    for control in card.get("controls", []):
        label = normalize(
            " ".join(
                [
                    control.get("text", ""),
                    control.get("ariaLabel", ""),
                    control.get("title", ""),
                ]
            )
        )
        if not control.get("disabled", False) and any(
            word and word in label for word in available_words_n
        ):
            actionable = True
            break

    available = (has_available or actionable) and not has_unavailable
    evidence = re.sub(r"\s+", " ", card.get("text", "")).strip()[:1000]
    return available, evidence


def inspect_sites(
    cards: list[dict[str, Any]],
    sites: list[int],
    config: dict[str, Any],
) -> list[Result]:
    results: list[Result] = []

    for site in sites:
        log(f"[Site {site}] evaluating")

        matching = [
            card
            for card in cards
            if str(site) in {str(number) for number in card.get("sites", [])}
        ]

        if not matching:
            log(f"[Site {site}] number not found")
            results.append(
                Result(
                    site=site,
                    available=False,
                    evidence="Site number not found in rendered page",
                    source="not-found",
                )
            )
            continue

        evidence_parts: list[str] = []
        site_available = False

        for card in matching[:20]:
            available, evidence = classify_card(
                card,
                config["available_keywords"],
                config["unavailable_keywords"],
            )
            evidence_parts.append(evidence)

            if available:
                site_available = True
                log(f"[Site {site}] AVAILABLE")
                results.append(
                    Result(
                        site=site,
                        available=True,
                        evidence=evidence,
                        source="rendered-card",
                    )
                )
                break

        if not site_available:
            log(f"[Site {site}] not classified as available")
            results.append(
                Result(
                    site=site,
                    available=False,
                    evidence=" | ".join(evidence_parts)[:1600],
                    source="rendered-card",
                )
            )

    return results


def run(browser: Browser, config: dict[str, Any]) -> list[Result]:
    log("Creating browser context")
    context = browser.new_context(
        locale="en-CA",
        timezone_id="America/Halifax",
        viewport={"width": 1440, "height": 1200},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    )

    page = context.new_page()
    page.set_default_timeout(12_000)

    try:
        log("Opening Parks Canada reservation URL")
        response = page.goto(
            SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        if response is not None:
            log(f"Initial HTTP status: {response.status}")
            if response.status >= 400:
                raise RuntimeError(
                    f"Reservation page returned HTTP {response.status}"
                )

        log(f"Loaded page title: {page.title()}")

        click_cookie_banner(
            page,
            config.get("cookie_accept_selectors", []),
        )

        log("Allowing client-side content to render")
        page.wait_for_timeout(
            int(config.get("render_wait_ms", 5_000))
        )

        save_debug(page, "initial")
        detect_blocked_page(page)

        cards = collect_candidate_cards(
            page,
            config["sites"],
            config.get("site_card_selector", "").strip(),
        )

        results = inspect_sites(cards, config["sites"], config)
        save_debug(page, "latest")
        return results

    finally:
        context.close()


def write_result(
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
    log(f"Saved result: {path}")


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    if not SEARCH_URL:
        log(
            "PARKS_SEARCH_URL is required. Save the fully configured "
            "reservation-results URL as a GitHub Actions secret."
        )
        return 2

    checked_at = datetime.now(timezone.utc).isoformat()
    config = load_config()

    log("Starting Parks Canada campsite monitor")
    log(f"Campground: {config['campground']}")
    log(f"Stay: {config['arrival']} to {config['departure']}")
    log(f"Sites: {config['sites']}")
    log(f"HEADLESS: {HEADLESS}")

    try:
        with sync_playwright() as playwright:
            log("Launching Chromium")
            browser = playwright.chromium.launch(headless=HEADLESS)
            try:
                results = run(browser, config)
            finally:
                log("Closing Chromium")
                browser.close()

        write_result(config, results, checked_at)

    except Exception as exc:
        message = (
            f"Campsite monitor failed at {checked_at}\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            "Download the GitHub Actions diagnostic artifact for the "
            "screenshot, HTML, and rendered page text."
        )
        log(message)

        try:
            send_email(
                "Parks Canada monitor needs attention",
                message,
            )
        except Exception as email_exc:
            log(
                "Could not send failure email: "
                f"{type(email_exc).__name__}: {email_exc}"
            )

        return 1

    available = [result for result in results if result.available]

    if available:
        sites = ", ".join(str(result.site) for result in available)
        evidence = "\n\n".join(
            f"Site {result.site}: {result.evidence}"
            for result in available
        )
        body = (
            f"Available campsite(s): {sites}\n"
            f"Campground: {config['campground']}\n"
            f"Stay: {config['arrival']} to {config['departure']}\n"
            f"Party: {config['party_size']} people, "
            f"{config['equipment']}\n\n"
            f"Open the booking page immediately:\n{SEARCH_URL}\n\n"
            f"Evidence:\n{evidence}"
        )

        try:
            send_email(
                f"Campsite available: {sites} at "
                f"{config['campground']}",
                body,
            )
        except Exception as exc:
            log(
                "Availability was detected, but the notification email "
                f"failed: {type(exc).__name__}: {exc}"
            )
            return 1
    else:
        log("No configured campsite was classified as available")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
