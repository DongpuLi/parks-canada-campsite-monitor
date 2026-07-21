from __future__ import annotations

import json
import os
import re
import smtplib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable

from playwright.sync_api import Browser, Locator, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

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


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config.example.json to config.json and edit it."
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def site_patterns(site: int) -> list[re.Pattern[str]]:
    return [
        re.compile(rf"\bsite\s*#?\s*0*{site}\b", re.IGNORECASE),
        re.compile(rf"\bcampsite\s*#?\s*0*{site}\b", re.IGNORECASE),
        re.compile(rf"\bemplacement\s*#?\s*0*{site}\b", re.IGNORECASE),
        re.compile(rf"^\s*#?\s*0*{site}\s*$", re.IGNORECASE),
    ]


def click_cookie_banner(page: Page, selectors: Iterable[str]) -> None:
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=800):
                button.click(timeout=1500)
                return
        except Exception:
            continue


def candidate_cards(page: Page, site: int, explicit_selector: str) -> list[Locator]:
    candidates: list[Locator] = []

    if explicit_selector:
        for card in page.locator(explicit_selector).all():
            try:
                text = card.inner_text(timeout=1000)
            except Exception:
                continue
            if any(p.search(text) for p in site_patterns(site)):
                candidates.append(card)
        return candidates

    # Find exact or labelled occurrences, then climb ancestors to a likely card/container.
    text_locators = [
        page.get_by_text(
            re.compile(
                rf"^\s*(?:site|campsite|emplacement)?\s*#?\s*0*{site}\s*$",
                re.IGNORECASE,
            )
        ),
        page.get_by_text(
            re.compile(
                rf"\b(?:site|campsite|emplacement)\s*#?\s*0*{site}\b",
                re.IGNORECASE,
            )
        ),
    ]

    seen: set[str] = set()
    for locator in text_locators:
        count = min(locator.count(), 20)
        for i in range(count):
            node = locator.nth(i)
            for levels in range(1, 7):
                ancestor = node.locator("xpath=" + "/.." * levels)
                try:
                    text = ancestor.inner_text(timeout=800)
                except Exception:
                    continue
                text_n = normalize(text)
                if len(text_n) < 8 or len(text_n) > 2500:
                    continue
                key = text_n[:500]
                if key not in seen:
                    seen.add(key)
                    candidates.append(ancestor)
                # A card with a button/link is usually the right scope.
                try:
                    if ancestor.locator("button, a, [role='button']").count() > 0:
                        break
                except Exception:
                    pass
    return candidates


def classify_card(card: Locator, available_words: list[str], unavailable_words: list[str]) -> tuple[bool, str]:
    try:
        raw = card.inner_text(timeout=1500)
    except Exception:
        return False, "Could not read candidate card"

    text = normalize(raw)
    has_unavailable = any(word.lower() in text for word in unavailable_words)
    has_available = any(word.lower() in text for word in available_words)

    actionable = False
    try:
        controls = card.locator("button, a, [role='button']")
        for i in range(min(controls.count(), 20)):
            control = controls.nth(i)
            label = normalize(
                " ".join(
                    filter(
                        None,
                        [
                            control.inner_text(timeout=500) if control.is_visible() else "",
                            control.get_attribute("aria-label") or "",
                            control.get_attribute("title") or "",
                        ],
                    )
                )
            )
            disabled = control.get_attribute("disabled") is not None or control.get_attribute("aria-disabled") == "true"
            if not disabled and any(word.lower() in label for word in available_words):
                actionable = True
                break
    except Exception:
        pass

    available = (has_available or actionable) and not has_unavailable
    evidence = re.sub(r"\s+", " ", raw).strip()[:700]
    return available, evidence


def inspect_site(page: Page, site: int, config: dict) -> Result:
    cards = candidate_cards(page, site, config.get("site_card_selector", "").strip())
    if not cards:
        return Result(site, False, "Site number not found in rendered page")

    evidence_parts: list[str] = []
    for card in cards[:12]:
        available, evidence = classify_card(
            card,
            config["available_keywords"],
            config["unavailable_keywords"],
        )
        evidence_parts.append(evidence)
        if available:
            return Result(site, True, evidence)

    return Result(site, False, " | ".join(evidence_parts)[:1200])


def send_email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    recipient = os.getenv("ALERT_EMAIL", "").strip()
    sender = os.getenv("ALERT_FROM", username).strip()

    if not all([username, password, recipient, sender]):
        print("Email secrets are incomplete; printing alert instead.", file=sys.stderr)
        print(subject)
        print(body)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)

    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(msg)


def save_debug(page: Page, name: str) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(ARTIFACTS / f"{name}.png"), full_page=True)
    except Exception:
        pass
    try:
        (ARTIFACTS / f"{name}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass


def run(browser: Browser, config: dict) -> list[Result]:
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
    page.set_default_timeout(12000)

    response = page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60000)
    if response and response.status >= 400:
        raise RuntimeError(f"Reservation page returned HTTP {response.status}")

    click_cookie_banner(page, config.get("cookie_accept_selectors", []))
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(3000)

    title = page.title()
    body_text = normalize(page.locator("body").inner_text(timeout=10000))
    if any(token in body_text for token in ["access denied", "forbidden", "captcha", "verify you are human"]):
        save_debug(page, "blocked")
        raise RuntimeError(f"Reservation site blocked automation or requested verification. Page title: {title}")

    results = [inspect_site(page, int(site), config) for site in config["sites"]]
    save_debug(page, "latest")
    context.close()
    return results


def main() -> int:
    if not SEARCH_URL:
        print("PARKS_SEARCH_URL is required. Save the fully configured reservation results URL as a GitHub secret.", file=sys.stderr)
        return 2

    config = load_config()
    now = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        try:
            results = run(browser, config)
        except Exception as exc:
            message = f"Campsite monitor failed at {now}\n\n{type(exc).__name__}: {exc}\n\nSee the GitHub Actions artifacts for screenshot and HTML."
            send_email("Parks Canada monitor needs attention", message)
            print(message, file=sys.stderr)
            return 1
        finally:
            browser.close()

    available = [r for r in results if r.available]
    report = {
        "checked_at_utc": now,
        "campground": config["campground"],
        "arrival": config["arrival"],
        "departure": config["departure"],
        "results": [r.__dict__ for r in results],
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if available:
        sites = ", ".join(str(r.site) for r in available)
        evidence = "\n\n".join(f"Site {r.site}: {r.evidence}" for r in available)
        body = (
            f"Available campsite(s): {sites}\n"
            f"Campground: {config['campground']}\n"
            f"Stay: {config['arrival']} to {config['departure']}\n"
            f"Party: {config['party_size']} people, {config['equipment']}\n\n"
            f"Open the booking page immediately:\n{SEARCH_URL}\n\n"
            f"Evidence:\n{evidence}"
        )
        send_email(f"Campsite available: {sites} at {config['campground']}", body)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
