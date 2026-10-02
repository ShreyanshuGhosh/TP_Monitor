# T&P Portal Monitor

Checks your college Training & Placement portal every 15 minutes (GitHub Actions) and sends a
Telegram and/or email alert when a new notice appears.

## Files
- `check_portal.py` – login, scrape, diff, notify
- `.github/workflows/monitor.yml` – scheduler (cron + manual run)
- `state.json` – last seen notices (auto-updated by the workflow)
- `requirements.txt`

## Secrets (Repo -> Settings -> Secrets and variables -> Actions)
| Secret | Required | Notes |
|---|---|---|
| PORTAL_NOTICES_URL | yes | Page that lists notices |
| PORTAL_LOGIN_URL | if login needed | Page containing the login form |
| PORTAL_USER / PORTAL_PASS | if login needed | Your portal credentials |
| PORTAL_USER_FIELD / PORTAL_PASS_FIELD | optional | `name` attributes of the login inputs (default `username` / `password`) |
| PORTAL_EXTRA_FIELDS | optional | JSON of extra login fields, e.g. `{"role":"student"}` |
| NOTICE_SELECTOR | recommended | CSS selector matching ONE notice (default `table tr`) |
| LOGIN_REQUIRED | optional | `false` for public pages |
| TG_BOT_TOKEN / TG_CHAT_ID | one channel needed | Telegram alerts |
| NOTIFY_EMAIL / GMAIL_APP_PASSWORD | one channel needed | Gmail address + App Password for sending |
| NOTIFY_TO | optional | Different inbox to receive alerts (defaults to NOTIFY_EMAIL) |

## Local test
    pip install -r requirements.txt
    export PORTAL_NOTICES_URL=... PORTAL_LOGIN_URL=... PORTAL_USER=... PORTAL_PASS=... TG_BOT_TOKEN=... TG_CHAT_ID=...
    python check_portal.py
