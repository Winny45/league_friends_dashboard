# -*- coding: utf-8 -*-
"""Assemble config.json for an unattended run.

The friends list, platform and season start live in the private state repo
alongside rank_history.json, because they carry riot IDs and this repo is
public. The API key does not live there: it rotates, and a key sitting in a
file is a key somebody eventually pastes somewhere. It comes from the
RIOT_API_KEY secret and is written only into the runner's working copy.

Nothing here prints the key, including on failure.
"""
import json
import os
import pathlib
import sys

src = pathlib.Path(".state/config.json")
if not src.exists():
    sys.exit("No config.json in the state repo. Copy your local one there once, "
             "with the api_key field left as an empty string.")

key = os.environ.get("RIOT_API_KEY", "").strip()
if not key:
    sys.exit("RIOT_API_KEY is empty. Set it in the repository secrets.")

config = json.loads(src.read_text(encoding="utf-8"))
config["api_key"] = key

friends = config.get("friends") or []
if not friends:
    sys.exit("The state repo's config.json lists no friends.")

pathlib.Path("config.json").write_text(
    json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"config.json written for {len(friends)} friend(s) on {config.get('platform', '?')}, "
      f"key ending {key[-4:]}")
