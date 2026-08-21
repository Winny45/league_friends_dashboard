#!/usr/bin/env python3
"""
post_discord.py — posts a short highlights summary to a Discord webhook.

Called automatically by fetch_data.py at the end of every run *if*
"discord_webhook_url" is set in config.json. Can also be run standalone
against an existing data.json:

    python3 post_discord.py data.json https://discord.com/api/webhooks/...

To get a webhook URL: in Discord, go to the channel you want updates
posted to -> Edit Channel -> Integrations -> Webhooks -> New Webhook ->
Copy Webhook URL. Paste that into config.json's "discord_webhook_url".
"""
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from generate_dashboard import compute_awards, tier_score, rank_label


def build_message(data):
    friends = data.get("friends", [])
    friends_sorted = sorted(friends, key=lambda f: tier_score(f["ranked"].get("solo")), reverse=True)
    now = datetime.now()
    awards = compute_awards(friends_sorted, now)

    lines = ["**League Friends Dashboard — daily update**"]
    if friends_sorted:
        top = friends_sorted[0]
        lines.append(f"👑 Leading Solo/Duo: **{top['label']}** — {rank_label(top['ranked'].get('solo')).replace('&middot;', '·')}")

    if awards:
        lines.append("")
        lines.append("**Highlights:**")
        for a in awards[:5]:
            # a["text"] may contain escaped HTML entities from generate_dashboard's
            # esc() calls (used for the HTML dashboard) — undo the couple that
            # actually show up in award text so Discord doesn't render "&amp;".
            text = a["text"].replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"')
            lines.append(f"{a['icon']} **{a['title']}** — {text}")
    else:
        lines.append("")
        lines.append("No new highlights today.")

    return "\n".join(lines)


def post(webhook_url, data):
    message = build_message(data)
    payload = json.dumps({"content": message[:2000]}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read()


def main():
    data_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data.json")
    webhook_url = sys.argv[2] if len(sys.argv) > 2 else None
    if not webhook_url:
        config_path = Path("config.json")
        if config_path.exists():
            webhook_url = json.loads(config_path.read_text(encoding="utf-8")).get("discord_webhook_url")
    if not webhook_url:
        print("No webhook URL given and none found in config.json's discord_webhook_url.")
        sys.exit(1)
    if not data_path.exists():
        print(f"{data_path} not found — run fetch_data.py first.")
        sys.exit(1)
    data = json.loads(data_path.read_text(encoding="utf-8"))
    try:
        post(webhook_url, data)
        print("Posted to Discord.")
    except urllib.error.HTTPError as e:
        print(f"Discord webhook failed: {e.code} {e.read().decode('utf-8', 'ignore')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
