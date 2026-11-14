"""Writes the analysis page and the per-day game files it loads.

The numbers come from analysis.py and the drawing is done in the browser by
the scripts in analysis_assets/. This file is the seam between them: it puts
the payload, the stylesheet and the scripts into one self-contained HTML
file, the same way the main dashboard is one file.

The stylesheet and scripts are real .css and .js files rather than strings in
here, because the main dashboard's are strings inside a Python f-string and
every brace in them has to be doubled. That is survivable for one page and
was not worth repeating for a second.
"""

import json
from html import escape
from pathlib import Path

from analysis import Analysis

ASSETS = Path(__file__).parent / "analysis_assets"

_BRAND_MARK = ('<svg viewBox="0 0 64 64" width="26" height="26" aria-hidden="true" focusable="false">'
               '<path d="M22 13 H35 V39 H50 V46 L44 52 H22 Z" fill="#fff"/></svg>')


def _json_for_script(obj):
    """JSON that is safe inside a <script> element."""
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render(payload, colours, basic_href, alt_href=None, alt_label="", avatars=None):
    meta = payload["meta"]
    css = (ASSETS / "analysis.css").read_text(encoding="utf-8")
    js = "\n".join(p.read_text(encoding="utf-8") for p in sorted(ASSETS.glob("a*.js")))
    config = {"colors": colours, "basicHref": basic_href}
    stored, season = meta.get("storedGames", 0), meta.get("seasonGames", 0)
    notice = ""
    if stored < season:
        notice = (f'<div class="notice">Built from <b>{stored:,}</b> of this season&#39;s <b>{season:,}</b> games so far. '
                  f'Full game detail is fetched a few hundred games at a time, newest first, so older games '
                  f'join over the next few hours and the figures here firm up as they do.</div>')
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
  </div>
  {notice}
  <main>
    <div class="tabs" id="tabs" role="tablist" aria-label="Analysis sections"></div>
    <div id="view"></div>
  </main>
  <footer>
    Data via the Riot Games API. Not endorsed by Riot Games. "Lobby" means everyone else in the group&#39;s own
    games, compared role for role. Champion classes are kept by hand. Remakes are excluded.
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


def build(data, store_games, colours, out_path, basic_href, alt_href=None, alt_label="", avatars=None):
    """Build one analysis page. Returns the Analysis so the caller can reuse
    it for the main page's borrowed numbers and for the game files."""
    analysis = Analysis(data, store_games)
    Path(out_path).write_text(
        render(analysis.payload(), colours, basic_href, alt_href, alt_label, avatars), encoding="utf-8")
    return analysis
