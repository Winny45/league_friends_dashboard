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

print(f"deploy/index.html looks publishable: {len(html)} bytes, no key, assets present.")
