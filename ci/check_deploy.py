# -*- coding: utf-8 -*-
"""Last look at the page before it goes to a public URL.

Cheap, and it runs on every hourly publish. The one that matters is the key:
config.json is read at build time for site_url, so a bug that widened that
read would put a live Riot key on a public page and nothing would say so.
"""
import pathlib
import re
import sys

page = pathlib.Path("deploy/index.html")
if not page.exists():
    sys.exit("deploy/index.html is missing; the build did not produce a page.")

html = page.read_text(encoding="utf-8")
problems = []

# A development key is RGAPI- plus a UUID. The page legitimately contains the
# literal "RGAPI-" in placeholder text and in its own key-validation regex, so
# match the real shape rather than the prefix.
if re.search(r"RGAPI-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", html):
    problems.append("a live-looking Riot API key is in the page")

if len(html) < 500_000:
    problems.append(f"the page is only {len(html)} bytes, far below a real build")

if "<title>" not in html:
    problems.append("no <title>, so the build probably failed part way")

# vercel.json decides caching and clean URLs, so its absence is a real
# problem. The share images are decoration: say so and carry on.
if not pathlib.Path("deploy", "vercel.json").exists():
    problems.append("deploy/vercel.json is missing")
for asset in ("og.png", "icon-180.png"):
    if not pathlib.Path("deploy", asset).exists():
        print(f"note: deploy/{asset} was not built, so the link preview will be plain.")

if problems:
    for p in problems:
        print(f"! {p}")
    sys.exit("Refusing to publish.")

# The primary-accounts-only companion, when the config names any second
# account. Same checks: it is published to the same public URL space and a
# key leaking onto it would leak just as far.
companion = pathlib.Path("deploy/main.html")
if companion.exists():
    alt = companion.read_text(encoding="utf-8")
    if re.search(r"RGAPI-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", alt):
        sys.exit("! a live-looking Riot API key is in deploy/main.html. Refusing to publish.")
    if len(alt) < 500_000:
        sys.exit(f"! deploy/main.html is only {len(alt)} bytes. Refusing to publish.")
    print(f"deploy/main.html looks publishable: {len(alt)} bytes, no key.")
else:
    print("note: no deploy/main.html, so no second accounts are configured.")

# The analysis pages and the game files they load. Built only once the game
# store has something in it, so their absence is a note and not a failure.
# What they must never do is carry the key, or reach the public site as a
# husk: a page that parsed its data and found nothing still has a title.
KEY = r"RGAPI-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# analysis.html has second accounts merged into their owners and
# analysis-split.html shows every account; analysis-main.html is a few lines
# that send an old address on, so it is checked for a key and nothing else.
moved = pathlib.Path("deploy", "analysis-main.html")
if moved.exists() and re.search(KEY, moved.read_text(encoding="utf-8")):
    sys.exit("! a live-looking Riot API key is in deploy/analysis-main.html. Refusing to publish.")
for name in ("analysis.html", "analysis-split.html"):
    extra = pathlib.Path("deploy", name)
    if not extra.exists():
        print(f"note: no deploy/{name} this build.")
        continue
    text = extra.read_text(encoding="utf-8")
    if re.search(KEY, text):
        sys.exit(f"! a live-looking Riot API key is in deploy/{name}. Refusing to publish.")
    if 'id="analysis-data"' not in text or len(text) < 100_000:
        sys.exit(f"! deploy/{name} is {len(text)} bytes and looks incomplete. Refusing to publish.")
    print(f"deploy/{name} looks publishable: {len(text)} bytes, no key.")

games = sorted(pathlib.Path("deploy", "g").glob("*.json")) if pathlib.Path("deploy", "g").is_dir() else []
if games:
    # A puuid is 78 characters of base64url. The public game files are meant
    # to hold names and numbers only, so one turning up means the stripping
    # in analysis.public_game was bypassed.
    sample = games[-1].read_text(encoding="utf-8")
    if re.search(KEY, sample):
        sys.exit(f"! a live-looking Riot API key is in {games[-1]}. Refusing to publish.")
    if '"pu"' in sample or re.search(r'"[A-Za-z0-9_-]{78}"', sample):
        sys.exit(f"! {games[-1]} contains what looks like a puuid. Refusing to publish.")
    print(f"deploy/g holds {len(games)} day files; newest checked, no key, no puuids.")

print(f"deploy/index.html looks publishable: {len(html)} bytes, no key, assets present.")
