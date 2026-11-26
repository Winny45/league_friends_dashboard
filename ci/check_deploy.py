# -*- coding: utf-8 -*-
"""Last look at the pages before they go to a public URL.

Cheap, and it runs on every hourly publish. The one that matters is the key:
config.json is read at build time for site_url, and data.json carries the key
too, so a bug that copied the wrong field would put a live Riot key on a
public page and nothing would say so.

The site, since the overhaul:
    index.html     the site, second accounts merged (or the classic page
                   standing in for it, if the new pages failed to build)
    split.html     the site, every account on its own
    classic.html   the old single page
    main.html, analysis.html, analysis-split.html, analysis-main.html
                   a few lines each that send an old address on
    g/, c/         per-day game files and per-champion files
    m/             the multisearch lookup, keyed by hashed Riot ID
"""
import pathlib
import re
import sys

KEY = r"RGAPI-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PUUID = r'"[A-Za-z0-9_-]{78}"'
problems = []


def read(name):
    path = pathlib.Path("deploy", name)
    return path.read_text(encoding="utf-8") if path.exists() else None


page = read("index.html")
if page is None:
    sys.exit("deploy/index.html is missing; the build did not produce a page.")
if re.search(KEY, page):
    problems.append("a live-looking Riot API key is in index.html")
if "<title>" not in page:
    problems.append("index.html has no <title>, so the build probably failed part way")
site = 'id="analysis-data"' in page
if site and len(page) < 300_000:
    problems.append(f"index.html is the site but only {len(page)} bytes, far below a real build")
if not site and len(page) < 500_000:
    problems.append(f"index.html is the classic page standing in, but only {len(page)} bytes")
if not site:
    print("note: index.html is the classic page this build; the new pages did not build.")

# vercel.json decides caching and clean URLs, so its absence is a real
# problem. The share images are decoration: say so and carry on.
if not pathlib.Path("deploy", "vercel.json").exists():
    problems.append("deploy/vercel.json is missing")
for asset in ("og.png", "icon-180.png"):
    if not pathlib.Path("deploy", asset).exists():
        print(f"note: deploy/{asset} was not built, so the link preview will be plain.")

if site:
    split = read("split.html")
    if split is not None:
        if re.search(KEY, split):
            problems.append("a live-looking Riot API key is in split.html")
        if 'id="analysis-data"' not in split and "http-equiv=\"refresh\"" not in split:
            problems.append("split.html is neither the site nor a redirect")
    classic = read("classic.html")
    if classic is None:
        problems.append("classic.html is missing")
    else:
        if re.search(KEY, classic):
            problems.append("a live-looking Riot API key is in classic.html")
        if len(classic) < 500_000:
            problems.append(f"classic.html is only {len(classic)} bytes")
    # The analysis payload carries lobby names by design (everyone in a game
    # is on its scoreboard), but never an account id.
    if re.search(PUUID, page):
        problems.append("index.html contains what looks like a puuid")

# The live lookup reads the key from Vercel's environment; the file itself
# must never hold one.
lookup = pathlib.Path("deploy", "api", "lookup.js")
if lookup.exists():
    src = lookup.read_text(encoding="utf-8")
    if re.search(KEY, src) or "RGAPI-" in src:
        problems.append("deploy/api/lookup.js contains a Riot key; it must read process.env.RIOT_API_KEY")

for name in ("main.html", "analysis.html", "analysis-split.html", "analysis-main.html"):
    text = read(name)
    if text is not None and re.search(KEY, text):
        problems.append(f"a live-looking Riot API key is in {name}")

if problems:
    for p in problems:
        print(f"! {p}")
    sys.exit("Refusing to publish.")


def newest(folder, kind):
    d = pathlib.Path("deploy", folder)
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []
    if not files:
        return
    # A puuid is 78 characters of base64url. These files are meant to hold
    # names and numbers only, so one turning up means the stripping was
    # bypassed.
    for f in (files[-1], files[0]):
        sample = f.read_text(encoding="utf-8")
        if re.search(KEY, sample):
            sys.exit(f"! a live-looking Riot API key is in {f}. Refusing to publish.")
        if '"pu"' in sample or re.search(PUUID, sample):
            sys.exit(f"! {f} contains what looks like a puuid. Refusing to publish.")
    print(f"deploy/{folder} holds {len(files)} {kind} files; newest and oldest checked, no key, no puuids.")


newest("g", "day")
newest("c", "champion")
newest("m", "multisearch")
print(f"deploy/index.html looks publishable: {len(page)} bytes, {'the site' if site else 'the classic page'}, no key.")
