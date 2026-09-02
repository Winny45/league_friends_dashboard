# -*- coding: utf-8 -*-
"""Put a Riot key into config.json and prove Riot accepts it.

    python set_key.py RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

Editing the JSON by hand works too, but a key pasted on top of an old one
gives "RGAPI-<old>RGAPI-<new>", which still starts with RGAPI-, still looks
right, and comes back from Riot as a 401 that reads like the new key is bad.
So this checks the shape, writes it, and then actually calls Riot: either it
says the key works or it says exactly what is wrong, and you find out now
rather than at the top of the next hour.

The key is never printed in full.
"""
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

KEY_RE = re.compile(r"^RGAPI-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

if len(sys.argv) != 2:
    sys.exit("Usage: python set_key.py RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")

key = sys.argv[1].strip().strip('"').strip("'")

if not KEY_RE.match(key):
    if not key.startswith("RGAPI-"):
        sys.exit("That does not start with RGAPI-, so it is not a Riot key.")
    if key.count("RGAPI-") > 1:
        sys.exit("That looks like two keys joined together. Copy just the new one.")
    sys.exit(f"Expected RGAPI- followed by 36 characters; got {len(key) - 6}.")

cfg_path = pathlib.Path(__file__).with_name("config.json")
config = json.loads(cfg_path.read_text(encoding="utf-8"))
platform = config.get("platform", "euw1")

print(f"Checking the key against {platform}...")
# The same headers fetch_data.py sends. Riot's API is behind Cloudflare,
# which answers a bare urllib request with a 403 "error code: 1010" page
# regardless of the key. Checking with default headers made a working key
# look revoked.
req = urllib.request.Request(
    f"https://{platform}.api.riotgames.com/lol/status/v4/platform-data",
    headers={
        "X-Riot-Token": key,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://developer.riotgames.com",
    },
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp.read(1)
except urllib.error.HTTPError as e:
    if e.code == 401:
        sys.exit("Riot rejected it (401 Unknown apikey). A development key expires\n"
                 "24 hours after it is issued; get a fresh one, or apply for a\n"
                 "Personal API Key, which does not expire.")
    if e.code == 403:
        # What an expired development key actually returns here, so lead with
        # that rather than with revocation.
        sys.exit("Riot returned 403 Forbidden, which is what an expired development\n"
                 "key gives. They last 24 hours. Get a fresh one at\n"
                 "developer.riotgames.com, or apply there for a Personal API Key,\n"
                 "which does not expire and is what makes the hourly job worth having.")
    sys.exit(f"Riot returned {e.code} {e.reason}. Nothing has been written.")
except Exception as e:
    sys.exit(f"Could not reach Riot ({e}). Nothing has been written.")

config["api_key"] = key
cfg_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Riot accepts it. Written to config.json (ends {key[-4:]}).")
print("\nThe hourly task will pick it up on its own at the top of the hour.")
print(r"To publish right now instead:  .\update_and_publish.ps1")
