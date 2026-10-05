#!/usr/bin/env python3
"""
T&P portal change monitor.

Logs in (optional), reads the notices list, compares it with the last saved
state (state.json) and sends a Telegram and/or email alert for every NEW item.
All configuration comes from environment variables (GitHub Actions secrets).
"""
import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

STATE_FILE = Path(__file__).parent / "state.json"
MAX_STORED = 500


def env(name, default=""):
    return os.environ.get(name) or default


LOGIN_URL = env("PORTAL_LOGIN_URL")
NOTICES_URL = env("PORTAL_NOTICES_URL")
USER = env("PORTAL_USER")
PASSWORD = env("PORTAL_PASS")
USER_FIELD = env("PORTAL_USER_FIELD", "username")
PASS_FIELD = env("PORTAL_PASS_FIELD", "password")
EXTRA_FIELDS = env("PORTAL_EXTRA_FIELDS", "{}")  # JSON, e.g. {"role": "student"}
NOTICE_SELECTOR = env("NOTICE_SELECTOR", "table tr")  # CSS selector, one match per notice
UPDATE_SELECTOR = env("UPDATE_SELECTOR", "#newseventsx1 tbody tr")  # dashboard NOTIFICATION panel rows
UPDATE_PREFIX = "[Update] "
LOGIN_REQUIRED = env("LOGIN_REQUIRED", "true").lower() != "false"

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


# ---------------------------------------------------------------- notifications
def notify(text, subject="T&P Portal: new update"):
    text = text[:3800]
    sent = False

    token, chat = env("TG_BOT_TOKEN"), env("TG_CHAT_ID")
    if token and chat:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": text, "disable_web_page_preview": "true"},
            timeout=30,
        )
        r.raise_for_status()
        sent = True

    mail, app_pw = env("NOTIFY_EMAIL"), env("GMAIL_APP_PASSWORD")
    if mail and app_pw:
        msg = MIMEText(text)
        msg["Subject"] = subject
        msg["From"] = mail
        msg["To"] = env("NOTIFY_TO", mail)  # optional: send alerts to a different address
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(mail, app_pw)
            s.send_message(msg)
        sent = True

    if not sent:
        sys.exit("No notification channel configured (set TG_BOT_TOKEN + TG_CHAT_ID, or NOTIFY_EMAIL + GMAIL_APP_PASSWORD).")


# ---------------------------------------------------------------- portal access
def login(session):
    global USER_FIELD
    r = session.get(LOGIN_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Pick the form that contains the password box
    form = next((f for f in soup.find_all("form") if f.find("input", {"type": "password"})), None)
    payload, action = {}, LOGIN_URL
    if form:
        for inp in form.find_all("input"):
            n = inp.get("name")
            if n and inp.get("type") in ("hidden", "submit"):
                payload[n] = inp.get("value", "")

        all_input_names = [i.get("name") for i in form.find_all("input") if i.get("name")]
        if USER_FIELD not in all_input_names:
            if "identity" in all_input_names:
                USER_FIELD = "identity"
            elif "email" in all_input_names:
                USER_FIELD = "email"

        action = urljoin(r.url, form.get("action") or r.url)

    payload.update(json.loads(EXTRA_FIELDS))
    payload[USER_FIELD] = USER
    payload[PASS_FIELD] = PASSWORD

    resp = session.post(action, data=payload, timeout=30)
    resp.raise_for_status()


def fetch_notices_html():
    s = requests.Session()
    s.headers.update(HEADERS)
    if LOGIN_REQUIRED:
        login(s)
    r = s.get(NOTICES_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    if LOGIN_REQUIRED and soup.find("input", {"type": "password"}):
        sys.exit("Login seems to have failed (password box still on the page). Check credentials / field names.")
    return r.text


def extract_items(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for el in soup.select(NOTICE_SELECTOR):
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if not text:
            continue
        a = el.find("a", href=True)
        link = urljoin(NOTICES_URL, a["href"]) if a else ""
        items.append(f"{text} | {link}" if link else text)
    return list(dict.fromkeys(items))  # de-duplicate, keep order


def extract_updates(html):
    """Rows of the dashboard NOTIFICATION panel (interviews, shortlists, results...)."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for el in soup.select(UPDATE_SELECTOR):
        cell = el.find("td") or el  # first cell only; later cells are hidden sort keys
        text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True))
        if not text:
            continue
        a = cell.find("a", href=True)
        link = urljoin(NOTICES_URL, a["href"]) if a else ""
        items.append(f"{UPDATE_PREFIX}{text} | {link}" if link else f"{UPDATE_PREFIX}{text}")
    return list(dict.fromkeys(items))


# ---------------------------------------------------------------- state
def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"initialized": False, "items": []}


def save_state(current, previous):
    merged = list(dict.fromkeys(current + previous))[:MAX_STORED]
    STATE_FILE.write_text(json.dumps({"initialized": True, "items": merged}, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- main
def main():
    if env("TEST_NOTIFY") == "1":
        notify("✅ Test notification from your T&P portal monitor. Alerts are working.", "T&P Monitor: test email")
        print("Test notification sent.")
        return

    if not NOTICES_URL:
        sys.exit("PORTAL_NOTICES_URL is not set.")
    if LOGIN_REQUIRED and not (LOGIN_URL and USER and PASSWORD):
        sys.exit("PORTAL_LOGIN_URL, PORTAL_USER and PORTAL_PASS are required (or set LOGIN_REQUIRED=false).")

    html = fetch_notices_html()
    items = extract_items(html)
    if not items:
        sys.exit(f"No notices matched selector '{NOTICE_SELECTOR}'. Fix NOTICE_SELECTOR.")
    updates = extract_updates(html)
    if not updates:
        print(f"WARNING: no rows matched UPDATE_SELECTOR '{UPDATE_SELECTOR}'; notification panel not monitored.")

    state = load_state()
    previous = state.get("items", [])

    # First run with update tracking: store current updates as baseline without alerting.
    if state.get("initialized") and updates and not any(p.startswith(UPDATE_PREFIX) for p in previous):
        previous = previous + updates
        print(f"Update baseline saved ({len(updates)} items).")

    items = updates + items

    if not state.get("initialized"):
        save_state(items, [])
        notify(f"✅ T&P monitor is live. Tracking {len(items)} existing notices; you'll be alerted about new ones.", "T&P Monitor: now live")
        print(f"Baseline saved ({len(items)} items).")
        return

    known = set(previous)
    new = [i for i in items if i not in known]
    if new:
        lines = [f"🔔 {len(new)} new update(s) on the T&P portal:", ""]
        lines += [f"• {n}" for n in new[:15]]
        if len(new) > 15:
            lines.append(f"…and {len(new) - 15} more")
        lines += ["", NOTICES_URL]
        notify("\n".join(lines), f"🔔 {len(new)} new T&P notice(s)")
        print(f"{len(new)} new item(s) — notification sent.")
    else:
        print("No changes.")

    save_state(items, previous)


if __name__ == "__main__":
    main()
