"""Writes the analysis page and the per-day game files it loads.

The numbers come from analysis.py and the drawing is done in the browser by
the scripts in analysis_assets/. This file is the seam between them: it puts
the payload, the stylesheet, the map and the scripts into one self-contained
HTML file, the same way the main dashboard is one file.

The stylesheet and scripts are real .css and .js files rather than strings in
here, because the main dashboard's are strings inside a Python f-string and
every brace in them has to be doubled. That is survivable for one page and
was not worth repeating for a second.
"""

import json
import re
from html import escape
from pathlib import Path

from analysis import Analysis

ASSETS = Path(__file__).parent / "analysis_assets"

_BRAND_MARK = ('<svg viewBox="0 0 64 64" width="26" height="26" aria-hidden="true" focusable="false">'
               '<path d="M22 13 H35 V39 H50 V46 L44 52 H22 Z" fill="#fff"/></svg>')

# How each shape of the map drawing is coloured. Lanes, river and jungle take
# their colour from the stylesheet so one drawing can be shown two ways; the
# bases keep the colours the file gives them.
_ZONE_CLASS = {
    "toplane": "rz", "botlane": "rz", "midlane": "rz", "basepath": "rz",
    "topriver": "rz rz-river", "botriver": "rz rz-river",
    "bluejungle": "rz rz-jungle", "redjungle": "rz rz-jungle",
    "river": "rz-flow",
}


def _json_for_script(obj):
    """JSON that is safe inside a <script> element."""
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def rift_defs():
    """The map, once, for every map on the page to <use>.

    Read from the vector copy of the minimap in analysis_assets/map. Each area
    is its own path; the ids are dropped (nothing addresses them, and an id
    like "river" is too likely to collide) in favour of classes.
    """
    svg = (ASSETS / "map" / "rift-site-theme.svg").read_text(encoding="utf-8")
    gradient = re.search(r"<linearGradient.*?</linearGradient>", svg, re.S)
    parts = []
    for tag in re.findall(r"<path\b[^>]*>", svg):
        pid = re.search(r'\bid="([^"]+)"', tag)
        d = re.search(r'\sd="([^"]+)"', tag)
        if not pid or not d:
            continue
        cls = _ZONE_CLASS.get(pid.group(1))
        if cls:
            parts.append(f'<path class="{cls}" fill-rule="evenodd" d="{d.group(1)}"/>')
        else:
            fill = re.search(r'\bfill="([^"]+)"', tag)
            colour = fill.group(1) if fill else "#2b3550"
            parts.append(f'<path fill="{colour}" stroke="{colour}" stroke-width="1.2" fill-rule="evenodd" d="{d.group(1)}"/>')
    return ('<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false"><defs>'
            + (gradient.group(0) if gradient else "") + '<g id="rift">' + "".join(parts) + "</g></defs></svg>")


def _notices(meta):
    """What is still being collected, said once at the top of the page."""
    stored, season = meta.get("storedGames", 0), meta.get("seasonGames", 0)
    out = []
    if stored < season:
        out.append(f'Built from <b>{stored:,}</b> of this season&#39;s <b>{season:,}</b> games so far. Full game detail is '
                   f'fetched a few hundred games at a time, newest first, so the figures firm up as older games join.')
    ranked, detail = meta.get("rankedGames", 0), meta.get("detailGames", 0)
    if stored and ranked < stored:
        out.append(f'Ranks have been read for the players in <b>{ranked:,}</b> of <b>{stored:,}</b> games. Riot only gives a '
                   f'player&#39;s rank as it is today, so games from before ranks were collected use today&#39;s rank, and '
                   f'until a game is reached everyone in it is placed at the rank of the friend who played it.')
    if stored and detail < stored:
        out.append(f'<b>{detail:,}</b> of <b>{stored:,}</b> games have the newer detail (turret damage, skillshots, level '
                   f'times, scuttles). The rest are scored on the metrics they have until they are fetched again.')
    return "".join(f'<div class="notice">{text}</div>' for text in out)


def render(payload, colours, basic_href, alt_href=None, alt_label="", avatars=None):
    meta = payload["meta"]
    css = (ASSETS / "analysis.css").read_text(encoding="utf-8")
    js = "\n".join(p.read_text(encoding="utf-8") for p in sorted(ASSETS.glob("a*.js")))
    config = {"colors": colours, "basicHref": basic_href}
    stored = meta.get("storedGames", 0)
    alt = (f'<a class="hbtn" href="{escape(alt_href)}" title="{escape(alt_label)}">⇄ {escape(alt_label)}</a>'
           if alt_href else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>League Friends Dashboard · Data analysis</title>
<meta name="robots" content="noindex">
<meta name="theme-color" content="#0a0c12">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="apple-touch-icon" href="icon-180.png">
<style>
{css}
</style>
</head>
<body>
{rift_defs()}
<div class="wrap">
  <header class="top">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true">{_BRAND_MARK}</div>
      <h1>League Friends Dashboard</h1>
      <nav class="mode" aria-label="Dashboard mode">
        <a href="{escape(basic_href)}">Basic</a>
        <a class="on" href="#" aria-current="page">Data analysis</a>
      </nav>
    </div>
    <div class="header-actions">{alt}</div>
  </header>
  <div class="status-strip">
    <span>{escape(str(meta.get("platform") or ""))}</span>
    <span data-generated-ms="{int(meta.get("generatedAtMs") or 0)}">updated <b>{escape(str(meta.get("generatedAt") or ""))}</b></span>
    <span>season from <b>{escape(str(meta.get("seasonStart") or ""))}</b></span>
    <span><b>{stored:,}</b> games analysed</span>
    <span>scores recalculated every update</span>
  </div>
  {_notices(meta)}
  <main>
    <div class="tabs" id="tabs" role="tablist" aria-label="Analysis sections"></div>
    <div id="view"></div>
  </main>
  <footer>
    Data via the Riot Games API. Not endorsed by Riot Games. Champion classes and tags are from the
    <a href="https://wiki.leagueoflegends.com/en-us/" rel="noopener">League of Legends Wiki</a>. Objective and role
    icons are Riot&#39;s, served by Community Dragon. "Lobby" means everyone else in the group&#39;s own games,
    compared role for role. Remakes are excluded. Times are UK time.
  </footer>
</div>
<script type="application/json" id="analysis-data">{_json_for_script(payload)}</script>
<script type="application/json" id="analysis-config">{_json_for_script(config)}</script>
<script type="application/json" id="avatar-config">{_json_for_script(avatars or {"version": "", "defaults": {}, "played": {}, "champs": []})}</script>
<script>
{js}
</script>
</body>
</html>
"""


def redirect_page(target):
    """A page that only sends its visitor somewhere else, for an address that
    used to be a page of its own and may still be bookmarked."""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0; url={escape(target)}"><title>Moved</title>'
            f'<script>location.replace({json.dumps(target)} + location.hash)</script></head>'
            f'<body><a href="{escape(target)}">This page has moved.</a></body></html>')


def write_game_files(analysis, out_dir):
    """deploy/g/2026-11-12.json for every day with a stored game in it.

    Rewritten whole on each build, into a directory that is empty at the start
    of a CI run. The content of a finished day never changes, so the host's
    content-addressed upload sends only the days that are new.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    days = analysis.game_files()
    for day, games in days.items():
        ordered = {gid: games[gid] for gid in sorted(games)}
        (out_dir / f"{day}.json").write_text(
            json.dumps(ordered, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return len(days), sum(len(g) for g in days.values())


def load_store_games(root="games"):
    """Every stored game, or an empty list when the store is not there yet."""
    try:
        import game_store
        return list(game_store.GameStore(root).load().games())
    except Exception as e:
        print(f"  ! game store not readable ({e}); analysis pages will be empty")
        return []


def merge_second_accounts(data):
    """The same data with each person's second account folded into their first.

    A second account is one marked "second" in config.json whose label is the
    owner's label followed by "2nd". Its games become the owner's games, and
    its puuid one more of theirs, so the analysis sees one player with two
    logins instead of two half-players. An account whose owner is not on the
    list is left as it is.
    """
    friends = data.get("friends", [])
    by_label = {f["label"]: f for f in friends}
    owner_of = {}
    for f in friends:
        base = f["label"][:-3] if f["label"].endswith("2nd") else None
        if f.get("second") and base in by_label and not by_label[base].get("second"):
            owner_of[f["label"]] = base
    if not owner_of:
        return None
    merged = []
    for f in friends:
        if f["label"] in owner_of:
            continue
        mine = [g for g in friends if owner_of.get(g["label"]) == f["label"]]
        if not mine:
            merged.append(f)
            continue
        person = dict(f)
        person["puuids"] = [a.get("puuid") for a in [f] + mine if a.get("puuid")]
        person["accounts"] = [a["label"] for a in [f] + mine]
        for key in ("seasonMatches", "recentMatches"):
            rows = [m for a in [f] + mine for m in a.get(key, [])]
            person[key] = sorted(rows, key=lambda m: m.get("gameStartMs") or 0, reverse=True)
        merged.append(person)
    out = dict(data)
    out["friends"] = merged
    out["mergedAccounts"] = True
    return out


def build(data, store_games, colours, out_path, basic_href, alt_href=None, alt_label="", avatars=None,
          highlights=None):
    """Build one analysis page. Returns the Analysis so the caller can reuse
    it for the main page's borrowed numbers and for the game files."""
    analysis = Analysis(data, store_games, highlights=highlights)
    Path(out_path).write_text(
        render(analysis.payload(), colours, basic_href, alt_href, alt_label, avatars), encoding="utf-8")
    return analysis
