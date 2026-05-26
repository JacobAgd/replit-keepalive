import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 10


def load_apps():
    # If APPS_JSON env var is set (GitHub secret), use it — keeps URLs out of the repo
    raw = os.environ.get("APPS_JSON")
    if raw:
        return json.loads(raw)
    path = os.path.join(os.path.dirname(__file__), "apps.json")
    with open(path) as f:
        return json.load(f)


def ping(app: dict) -> tuple[bool, int | None, float | None]:
    url = app["url"]
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT_SECONDS, allow_redirects=True)
            elapsed = resp.elapsed.total_seconds()
            if resp.status_code < 500:
                # Treat anything below 500 as alive (redirects, auth pages, etc. are fine)
                print(f"  OK  {app['name']} — HTTP {resp.status_code} in {elapsed:.2f}s")
                return True, resp.status_code, elapsed
            print(
                f"  ERR {app['name']} — HTTP {resp.status_code} "
                f"(attempt {attempt}/{MAX_RETRIES})"
            )
        except requests.exceptions.Timeout:
            print(
                f"  ERR {app['name']} — timed out after {TIMEOUT_SECONDS}s "
                f"(attempt {attempt}/{MAX_RETRIES})"
            )
        except requests.exceptions.RequestException as exc:
            print(
                f"  ERR {app['name']} — {exc} "
                f"(attempt {attempt}/{MAX_RETRIES})"
            )

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY_SECONDS)

    return False, None, None


def send_slack_alert(app: dict, status_code: int | None) -> None:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("  WARN SLACK_WEBHOOK_URL not set — skipping alert")
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    status_text = f"HTTP {status_code}" if status_code else "No response / timeout"

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": ":red_circle: App Down", "emoji": True},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*App*\n{app['name']}"},
                    {"type": "mrkdwn", "text": f"*Status*\n{status_text}"},
                    {"type": "mrkdwn", "text": f"*URL*\n{app['url']}"},
                    {"type": "mrkdwn", "text": f"*Detected at*\n{ts}"},
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Replit Keep-Alive Monitor · Check the app on Replit for logs.",
                    }
                ],
            },
        ]
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"  SENT Slack alert for {app['name']}")
        else:
            print(f"  WARN Slack alert failed — HTTP {resp.status_code}: {resp.text}")
    except Exception as exc:
        print(f"  WARN Slack alert error — {exc}")


def main() -> int:
    apps = load_apps()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"Keep-alive check — {ts}")
    print(f"Checking {len(apps)} app(s) (timeout={TIMEOUT_SECONDS}s, retries={MAX_RETRIES})...\n")

    failed: list[tuple[dict, int | None]] = []

    for app in apps:
        ok, status_code, _ = ping(app)
        if not ok:
            failed.append((app, status_code))

    print()
    if failed:
        print(f"{len(failed)}/{len(apps)} app(s) DOWN — sending alerts")
        for app, status_code in failed:
            send_slack_alert(app, status_code)
        return 1

    print(f"All {len(apps)} app(s) healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
