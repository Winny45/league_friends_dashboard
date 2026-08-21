#!/usr/bin/env python3
"""
generate_dashboard.py — reads data.json (produced by fetch_data.py, or the
bundled demo data) and renders a single self-contained dashboard.html you
can open in any browser.

Usage:
    python3 generate_dashboard.py [data.json] [dashboard.html]
"""
import html
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

TIER_ORDER = [
    "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
    "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
]
RANK_SCORE = {"IV": 0, "III": 1, "II": 2, "I": 3}
APEX_TIERS = {"MASTER", "GRANDMASTER", "CHALLENGER"}

# Each tier gets a light-mode and dark-mode hex so text stays readable (and
# distinguishable from its neighbors) on both surfaces. Values are exposed as
# CSS custom properties (--tier-xxx) so the dark-mode toggle swaps them in
# one place rather than needing separate markup per theme.
TIER_COLOR = {
    "IRON":        {"light": "#5b5850", "dark": "#a6a399"},
    "BRONZE":      {"light": "#8a5a3c", "dark": "#cf9163"},
    "SILVER":      {"light": "#5f6570", "dark": "#b7bcc2"},
    "GOLD":        {"light": "#a66f00", "dark": "#eda100"},
    "PLATINUM":    {"light": "#1baf7a", "dark": "#199e70"},
    "EMERALD":     {"light": "#147a3d", "dark": "#0d7530"},
    "DIAMOND":     {"light": "#2a78d6", "dark": "#3987e5"},
    "MASTER":      {"light": "#6a3fc9", "dark": "#a78bfa"},
    "GRANDMASTER": {"light": "#d0362f", "dark": "#e66767"},
    "CHALLENGER":  {"light": "#b8860b", "dark": "#f4c95d"},
}
DEFAULT_TIER_COLOR = {"light": "#898781", "dark": "#898781"}

# Separate from TIER_COLOR: this is a per-*friend* identity palette for the
# rank-progress chart, where each line needs its own distinguishable color
# regardless of what rank that friend happens to be. Fixed order, validated
# categorical hues — never reassign/cycle these per-render.
FRIEND_PALETTE = [
    {"light": "#2a78d6", "dark": "#3987e5"},  # blue
    {"light": "#eb6834", "dark": "#d95926"},  # orange
    {"light": "#1baf7a", "dark": "#199e70"},  # aqua
    {"light": "#eda100", "dark": "#c98500"},  # yellow
    {"light": "#e87ba4", "dark": "#d55181"},  # magenta
    {"light": "#008300", "dark": "#008300"},  # green
    {"light": "#4a3aa7", "dark": "#9085e9"},  # violet
    {"light": "#e34948", "dark": "#e66767"},  # red
]


def tier_var(tier):
    """CSS custom property name for a tier, e.g. 'DIAMOND' -> '--tier-diamond'."""
    return f"--tier-{(tier or 'unranked').lower()}"


def _rank_snapshot_key(h):
    return (h.get("tier"), h.get("rank"))


def snapshot_change_label(prev, curr):
    """What changed between two consecutive rank snapshots. Raw League
    Points only mean the same thing when tier and division haven't moved —
    a promotion resets LP, so a naive point-to-point subtraction across a
    promotion would misreport a huge LP swing that didn't really happen.
    So: same tier+division -> real LP delta; otherwise -> promoted/demoted."""
    if prev is None:
        return None
    if _rank_snapshot_key(prev) == _rank_snapshot_key(curr):
        delta = (curr.get("leaguePoints") or 0) - (prev.get("leaguePoints") or 0)
        if delta == 0:
            return None
        return f"{'+' if delta >= 0 else ''}{delta} LP"
    prev_score = tier_score(prev)
    curr_score = tier_score(curr)
    if curr_score > prev_score:
        return f"promoted to {rank_label(curr)}".replace("&middot;", "·")
    if curr_score < prev_score:
        return f"demoted to {rank_label(curr)}".replace("&middot;", "·")
    return None


def net_change_label(first, last):
    """Net movement across the whole visible window, for the small label
    under each line's end point. Same tier+division at both ends -> a plain
    net LP number; otherwise a compact 'was -> now' since raw LP isn't
    comparable across a promotion/demotion."""
    first_score, last_score = tier_score(first), tier_score(last)
    direction = 1 if last_score > first_score else (-1 if last_score < first_score else 0)
    if _rank_snapshot_key(first) == _rank_snapshot_key(last):
        delta = (last.get("leaguePoints") or 0) - (first.get("leaguePoints") or 0)
        if delta == 0:
            return None
        return {"text": f"{'+' if delta >= 0 else ''}{delta} LP (30d)", "direction": direction}
    first_short = rank_label(first).split(" &middot;")[0]
    last_short = rank_label(last).split(" &middot;")[0]
    return {"text": f"{first_short} → {last_short}", "direction": direction}


def tier_score(ranked_entry):
    if not ranked_entry or not ranked_entry.get("tier"):
        return -1
    tier = ranked_entry["tier"]
    ti = TIER_ORDER.index(tier) if tier in TIER_ORDER else -1
    if tier in APEX_TIERS:
        rank_component = 4
    else:
        rank_component = RANK_SCORE.get(ranked_entry.get("rank"), 0)
    lp = ranked_entry.get("leaguePoints", 0) or 0
    return ti * 1000 + rank_component * 200 + lp


def rank_label(ranked_entry):
    if not ranked_entry or not ranked_entry.get("tier"):
        return "Unranked"
    tier = ranked_entry["tier"].capitalize()
    if ranked_entry["tier"] in APEX_TIERS:
        return f"{tier} &middot; {ranked_entry.get('leaguePoints', 0)} LP"
    return f"{tier} {ranked_entry.get('rank', '')} &middot; {ranked_entry.get('leaguePoints', 0)} LP"


def esc(s):
    return html.escape(str(s)) if s is not None else ""


# Set once per render by build_html() so every render_* helper below can
# look up an icon without threading version/map through every function
# signature. A little global state, but scoped to a single render pass.
_ICON_CTX = {"version": None, "map": {}}


def set_icon_context(version, icon_map):
    _ICON_CTX["version"] = version
    _ICON_CTX["map"] = icon_map or {}


def champion_icon_url(champion_name):
    """Data Dragon champion square icon URL, or None if we don't have a
    patch version / slug for this champion (e.g. very old cached data from
    before icons were added, or a brand-new champion Data Dragon hasn't
    indexed under this name yet)."""
    version = _ICON_CTX["version"]
    if not version or not champion_name:
        return None
    slug = _ICON_CTX["map"].get(champion_name)
    if not slug:
        return None
    return f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{slug}.png"


def render_champion_icon(champion_name, size=20):
    """An <img> for a champion icon that quietly goes invisible (rather
    than showing a broken-image glyph) if the URL 404s or the browser has
    no internet — the champion name text next to it already carries the
    meaning on its own. Uses visibility:hidden rather than display:none so
    the icon's box keeps its space; a table of champion rows where only
    some icons load stays aligned instead of each failed row's text
    creeping left to fill the gap."""
    url = champion_icon_url(champion_name)
    if not url:
        return f'<span class="champ-icon champ-icon-ph" style="width:{size}px;height:{size}px;"></span>'
    return (
        f'<img src="{esc(url)}" alt="" class="champ-icon" width="{size}" height="{size}" '
        f'loading="lazy" onerror="this.style.visibility=\'hidden\'">'
    )


# Rank tier emblems aren't part of Riot's official Data Dragon CDN (that's
# champion/item/etc art only) — these come from Community Dragon, a
# well-established community-run mirror of League's game assets. Unlike
# the champion icon map, there's no per-account API data needed to resolve
# these (tier names map straight to file names), so no fetch_data.py
# involvement is needed — generate_dashboard.py builds the URL directly.
# Community-run means the path could change on Riot's end without notice;
# same graceful degradation as champion icons handles that (blank, not
# broken) if it ever does.
RANK_ICON_BASE = "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-emblems-latest/emblem-{tier}.png"


def rank_icon_url(tier):
    if not tier:
        return None
    return RANK_ICON_BASE.format(tier=tier.lower())


def render_rank_icon(tier, size=20):
    url = rank_icon_url(tier)
    if not url:
        return f'<span class="rank-icon rank-icon-ph" style="width:{size}px;height:{size}px;"></span>'
    return (
        f'<img src="{esc(url)}" alt="" class="rank-icon" width="{size}" height="{size}" '
        f'loading="lazy" onerror="this.style.visibility=\'hidden\'">'
    )


def parse_match_dt(m):
    raw = m.get("gameStart")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def format_match_when(m):
    dt = parse_match_dt(m)
    if not dt:
        return "—"
    hour12 = dt.strftime("%I").lstrip("0") or "12"
    return f'{dt.strftime("%b %d")}, {hour12}{dt.strftime(":%M %p")}'


def format_minutes(total_min):
    total_min = round(total_min)
    h, m = divmod(total_min, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


def format_day_label(date_key):
    try:
        dt = datetime.strptime(date_key, "%Y-%m-%d")
    except (ValueError, TypeError):
        return date_key or "—"
    return dt.strftime("%a, %b %d")


def weekly_playtime(matches, now):
    """Minutes played and game count in the trailing 7 days from `now`."""
    cutoff = now - timedelta(days=7)
    total_min, count = 0.0, 0
    for m in matches:
        dt = parse_match_dt(m)
        if dt and dt >= cutoff:
            total_min += m.get("durationMin", 0)
            count += 1
    return total_min, count


def busiest_day(matches):
    """(dateKey, count) for the day with the most games this season."""
    counts = {}
    for m in matches:
        key = m.get("dateKey")
        if key:
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None, 0
    best_date = max(counts, key=counts.get)
    return best_date, counts[best_date]


POSITION_LABELS = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "Bottom", "UTILITY": "Support"}


def champion_breakdown(season_matches):
    """Per-champion games/wins/winrate for one friend's season, most-played first."""
    stats = {}
    for m in season_matches:
        s = stats.setdefault(m["champion"], {"games": 0, "wins": 0})
        s["games"] += 1
        if m["win"]:
            s["wins"] += 1
    rows = [
        {"champion": c, "games": s["games"], "wins": s["wins"], "winrate": round(100 * s["wins"] / s["games"], 1)}
        for c, s in stats.items()
    ]
    rows.sort(key=lambda r: (-r["games"], -r["winrate"]))
    return rows


def nemesis_champion(season_matches):
    """The enemy champion (same role, opposing team) a friend has lost to
    most often this season. Needs at least 2 losses to the same champion to
    surface — otherwise it's just noise from a single bad game."""
    losses_vs = {}
    for m in season_matches:
        opp = m.get("opponentChampion")
        if not opp or m["win"]:
            continue
        losses_vs[opp] = losses_vs.get(opp, 0) + 1
    if not losses_vs:
        return None
    champ, count = max(losses_vs.items(), key=lambda kv: kv[1])
    if count < 2:
        return None
    return {"champion": champ, "losses": count}


def role_breakdown(season_matches):
    """Per-role games/wins/winrate for one friend's season, most-played first."""
    stats = {}
    for m in season_matches:
        pos = m.get("position")
        if not pos:
            continue
        label = POSITION_LABELS.get(pos, pos.title())
        s = stats.setdefault(label, {"games": 0, "wins": 0})
        s["games"] += 1
        if m["win"]:
            s["wins"] += 1
    rows = [
        {"role": r, "games": s["games"], "wins": s["wins"], "winrate": round(100 * s["wins"] / s["games"], 1)}
        for r, s in stats.items()
    ]
    rows.sort(key=lambda r: -r["games"])
    return rows


def compute_duo_synergy(friends):
    """For every pair of friends who were teammates in the same ranked
    game at least twice this season, their combined winrate playing
    together. Detected purely from matchId + teamId overlap across
    friends' own season match lists — no extra API calls needed."""
    by_match = {}
    for f in friends:
        for m in f.get("seasonMatches", []):
            by_match.setdefault(m["matchId"], []).append((f, m))

    pair_stats = {}
    for entries in by_match.values():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                fa, ma = entries[i]
                fb, mb = entries[j]
                if ma.get("teamId") is None or ma.get("teamId") != mb.get("teamId"):
                    continue  # same lobby, opposite teams — not a duo
                key = tuple(sorted([fa["label"], fb["label"]]))
                stats = pair_stats.setdefault(key, {"wins": 0, "games": 0})
                stats["games"] += 1
                if ma["win"]:
                    stats["wins"] += 1

    rows = []
    for (a, b), s in pair_stats.items():
        if s["games"] < 2:
            continue
        rows.append({
            "a": a, "b": b, "games": s["games"], "wins": s["wins"],
            "losses": s["games"] - s["wins"],
            "winrate": round(100 * s["wins"] / s["games"], 1),
        })
    rows.sort(key=lambda r: (-r["games"], -r["winrate"]))
    return rows


def weekly_trend_for(rank_history, label, now):
    """Same net-change logic as weekly_rank_leader, scoped to one friend —
    powers the ▲/▼ trend arrow on each leaderboard row."""
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    pts = sorted(
        (h for h in rank_history if h.get("queue") == "solo" and h["label"] == label),
        key=lambda h: h["date"],
    )
    window = [h for h in pts if h["date"] >= cutoff]
    if len(window) < 2:
        return None
    return net_change_label(window[0], window[-1])


def weekly_rank_leader(rank_history, now):
    """Whoever climbed the most in Ranked Solo/Duo over the trailing 7
    days, for the 'This week at a glance' panel. Returns None if nobody
    has at least two snapshots inside the window."""
    by_label = {}
    for h in rank_history:
        if h.get("queue") != "solo":
            continue
        by_label.setdefault(h["label"], []).append(h)

    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    best = None
    for label, pts in by_label.items():
        pts.sort(key=lambda h: h["date"])
        window = [h for h in pts if h["date"] >= cutoff]
        if len(window) < 2:
            continue
        delta = tier_score(window[-1]) - tier_score(window[0])
        if delta <= 0:
            continue
        if best is None or delta > best["delta"]:
            net = net_change_label(window[0], window[-1])
            best = {"label": label, "delta": delta, "text": net["text"] if net else None}
    return best


def winrate_bar(pct, color):
    pct = max(0, min(100, pct or 0))
    # Gradient fades the bar toward transparent at its leading edge so the
    # fill reads as a level rather than a flat block of colour.
    fill = f"linear-gradient(90deg, color-mix(in srgb, {color} 65%, transparent), {color})"
    return f'''<div class="wr-track"><div class="wr-fill" style="width:{pct}%;background:{fill};"></div></div>'''


def render_match_dot(m):
    cls = "win" if m["win"] else "loss"
    when = format_match_when(m)
    title = f"{when} — {m['champion']} — {'Win' if m['win'] else 'Loss'} — {m['kills']}/{m['deaths']}/{m['assists']} KDA {m['kda']}"
    return f'<span class="dot {cls}" title="{esc(title)}"></span>'


def render_mastery_chip(m):
    return f'''<div class="chip">
      {render_champion_icon(m["championName"], size=28)}
      <div>
        <span class="chip-name">{esc(m["championName"])}</span>
        <span class="chip-level">M{esc(m["level"])}</span>
        <span class="chip-points">{esc(f"{m['points']:,}")} pts</span>
      </div>
    </div>'''


def render_match_row(m):
    cls = "win" if m["win"] else "loss"
    label = "WIN" if m["win"] else "LOSS"
    return f'''<tr>
      <td class="muted small">{esc(format_match_when(m))}</td>
      <td><span class="tag {cls}">{label}</span></td>
      <td class="champ-cell">{render_champion_icon(m["champion"])}{esc(m["champion"])}</td>
      <td class="num">{esc(m["kills"])}/{esc(m["deaths"])}/{esc(m["assists"])}</td>
      <td class="num">{esc(m["kda"])}</td>
      <td class="num">{esc(m["csPerMin"])}</td>
      <td class="muted">{esc(m.get("queue", ""))}</td>
      <td class="num muted">{esc(m.get("durationMin", ""))}m</td>
    </tr>'''


def render_peak_badge(current, peak):
    """Small 'Peak: X' note next to a rank row when the season peak is
    strictly better than the current rank — omitted otherwise (current
    rank already tells the whole story if it's the season high)."""
    if not peak or not peak.get("tier"):
        return ""
    if tier_score(peak) <= tier_score(current):
        return ""
    return f'<span class="muted small" style="margin-left:8px;">Peak: {rank_label(peak).replace("&middot;", "·")}</span>'


def render_fresh_badge(entry):
    """Flags a friend sitting at low LP in their current division — likely
    just landed there (promoted/demoted recently or on a fresh climb),
    worth a quick visual note. Not the same as the old 'promo series'
    concept, which modern ranked no longer has below Master."""
    if not entry or not entry.get("tier") or entry.get("leaguePoints") is None:
        return ""
    if entry["tier"] in APEX_TIERS:
        return ""
    if entry["leaguePoints"] <= 20:
        return '<span class="badge-fresh" title="Low LP in this division — recently promoted, demoted, or just starting the climb">Fresh</span>'
    return ""


def render_champion_breakdown(rows):
    if not rows:
        return '<div class="muted small">No ranked games this season.</div>'
    body = "".join(
        f'<tr><td class="champ-cell">{render_champion_icon(r["champion"])}{esc(r["champion"])}</td><td class="num">{r["games"]}</td>'
        f'<td class="num">{r["wins"]}W {r["games"] - r["wins"]}L</td>'
        f'<td class="num">{r["winrate"]}%</td></tr>'
        for r in rows
    )
    return f'''<table class="matches-table">
      <thead><tr><th>Champion</th><th class="num">Games</th><th class="num">Record</th><th class="num">Winrate</th></tr></thead>
      <tbody>{body}</tbody>
    </table>'''


def render_role_breakdown(rows):
    if not rows:
        return '<div class="muted small">No role data available for this season\'s games.</div>'
    body = "".join(
        f'<tr><td>{esc(r["role"])}</td><td class="num">{r["games"]}</td>'
        f'<td class="num">{r["wins"]}W {r["games"] - r["wins"]}L</td>'
        f'<td class="num">{r["winrate"]}%</td></tr>'
        for r in rows
    )
    return f'''<table class="matches-table">
      <thead><tr><th>Role</th><th class="num">Games</th><th class="num">Record</th><th class="num">Winrate</th></tr></thead>
      <tbody>{body}</tbody>
    </table>'''


def render_friend_card(f, rank_position, now):
    solo = f["ranked"].get("solo")
    flex = f["ranked"].get("flex")
    solo_var = tier_var((solo or {}).get("tier"))
    flex_var = tier_var((flex or {}).get("tier"))
    matches = f.get("recentMatches", [])
    season_matches = f.get("seasonMatches", matches)
    wins = sum(1 for m in matches if m["win"])
    losses = len(matches) - wins
    dots = "".join(render_match_dot(m) for m in matches) or '<span class="muted">No recent games</span>'
    mastery_html = "".join(render_mastery_chip(m) for m in f.get("mastery", [])) or '<span class="muted">No mastery data</span>'
    match_rows = "".join(render_match_row(m) for m in matches)
    solo_wr = (solo or {}).get("winrate")
    flex_wr = (flex or {}).get("winrate")

    weekly_min, weekly_games = weekly_playtime(season_matches, now)
    busiest_date, busiest_count = busiest_day(season_matches)
    busiest_label = format_day_label(busiest_date) if busiest_date else "—"
    season_games = len(season_matches)
    season_hours = format_minutes(sum(m.get("durationMin", 0) for m in season_matches))

    peak_rank = f.get("peakRank", {})
    solo_peak_badge = render_peak_badge(solo, peak_rank.get("solo"))
    flex_peak_badge = render_peak_badge(flex, peak_rank.get("flex"))
    solo_fresh_badge = render_fresh_badge(solo)

    champ_rows = champion_breakdown(season_matches)
    champion_pool = len(champ_rows)
    role_rows = role_breakdown(season_matches)
    nemesis = nemesis_champion(season_matches)
    nemesis_note = (
        f'<div class="muted small nemesis-row" style="margin-top:6px;">😤 Nemesis: {render_champion_icon(nemesis["champion"], size=18)}'
        f'<strong>{esc(nemesis["champion"])}</strong> '
        f'has beaten {esc(f["label"])} {nemesis["losses"]} times this season.</div>'
        if nemesis else ""
    )

    return f'''
    <section class="card" id="friend-{f["label"].lower()}">
      <header class="card-head">
        <div class="rank-badge">#{rank_position}</div>
        <div>
          <h2>{esc(f["label"])}</h2>
          <div class="muted small">{esc(f["riotId"])} &middot; Level {esc(f.get("summonerLevel", "?"))}</div>
        </div>
        {'<div class="hot">🔥 Hot streak</div>' if (solo or {}).get("hotStreak") else ""}
      </header>

      <div class="rank-rows">
        <div class="rank-row">
          <span class="rank-label rank-cell" style="color:var({solo_var})">{render_rank_icon((solo or {}).get("tier"), size=22)}{rank_label(solo)}</span>
          <span class="muted small">Solo/Duo</span>
          {winrate_bar(solo_wr, "var(--series-1)")}
          <span class="wr-text">{esc(solo_wr) + '%' if solo_wr is not None else '—'} ({esc((solo or {}).get('wins', 0))}W {esc((solo or {}).get('losses', 0))}L)</span>
        </div>
        <div class="rank-row">
          <span class="rank-label rank-cell" style="color:var({flex_var})">{render_rank_icon((flex or {}).get("tier"), size=22)}{rank_label(flex)}</span>
          <span class="muted small">Flex</span>
          {winrate_bar(flex_wr, "var(--series-2)")}
          <span class="wr-text">{esc(flex_wr) + '%' if flex_wr is not None else '—'} ({esc((flex or {}).get('wins', 0))}W {esc((flex or {}).get('losses', 0))}L)</span>
        </div>
        {f'<div class="muted small">{solo_fresh_badge}{solo_peak_badge}{flex_peak_badge}</div>' if (solo_fresh_badge or solo_peak_badge or flex_peak_badge) else ""}
      </div>

      <div class="section-label">Form (last {len(matches)} games, {wins}W {losses}L)</div>
      <div class="dots">{dots}</div>
      {nemesis_note}

      <div class="season-stats">
        <div class="stat-tile">
          <div class="stat-value">{format_minutes(weekly_min)}</div>
          <div class="stat-label">Played this week ({weekly_games} games)</div>
        </div>
        <div class="stat-tile">
          <div class="stat-value">{busiest_count if busiest_date else "—"}</div>
          <div class="stat-label">Busiest day{f" — {busiest_label}" if busiest_date else ""}</div>
        </div>
        <div class="stat-tile">
          <div class="stat-value">{season_games}</div>
          <div class="stat-label">Games this season ({season_hours})</div>
        </div>
        <div class="stat-tile">
          <div class="stat-value">{champion_pool}</div>
          <div class="stat-label">Champion pool this season</div>
        </div>
      </div>

      <div class="section-label">Top champions</div>
      <div class="chips">{mastery_html}</div>

      <details class="matches-details">
        <summary>Recent match detail ({len(matches)} games)</summary>
        <table class="matches-table">
          <thead><tr><th>When</th><th>Result</th><th>Champion</th><th>K/D/A</th><th>KDA</th><th>CS/min</th><th>Queue</th><th>Length</th></tr></thead>
          <tbody>{match_rows}</tbody>
        </table>
      </details>

      <details class="matches-details">
        <summary>Champion breakdown this season ({len(champ_rows)} champions)</summary>
        {render_champion_breakdown(champ_rows)}
      </details>

      <details class="matches-details">
        <summary>Role breakdown this season</summary>
        {render_role_breakdown(role_rows)}
      </details>
    </section>'''


def render_trend_arrow(trend):
    """▲/▼/— since 7 days ago, for the leaderboard. `trend` is a
    net_change_label()-style dict (direction + text) or None if there's
    not enough history yet to compare."""
    if not trend:
        return '<span class="muted small">—</span>'
    if trend["direction"] > 0:
        return f'<span class="small" style="color:var(--good);">▲ {esc(trend["text"])}</span>'
    if trend["direction"] < 0:
        return f'<span class="small" style="color:var(--critical);">▼ {esc(trend["text"])}</span>'
    return '<span class="muted small">—</span>'


def render_leaderboard_row(f, i, trend=None):
    solo = f["ranked"].get("solo")
    var = tier_var((solo or {}).get("tier"))
    wr = (solo or {}).get("winrate")
    # Top three get a tinted medal chip; everyone else a neutral one.
    pos_cls = f"pos pos-{i}" if i <= 3 else "pos"
    return f'''<tr>
      <td class="num"><span class="{pos_cls}">{i}</span></td>
      <td><a href="#friend-{f["label"].lower()}" data-friend-link="{f["label"].lower()}">{esc(f["label"])}</a></td>
      <td class="rank-cell" style="color:var({var});font-weight:600;">{render_rank_icon((solo or {}).get("tier"))}{rank_label(solo)}</td>
      <td class="num">{esc(wr) + '%' if wr is not None else '—'}</td>
      <td class="num muted">{esc((solo or {}).get('wins', 0))}W / {esc((solo or {}).get('losses', 0))}L</td>
      <td class="num">{render_trend_arrow(trend)}</td>
    </tr>'''


# ---------------------------------------------------------------------------
# Rank progress chart — a 30-day line chart of each friend's ranked
# Solo/Duo standing. Riot's API has no historical-rank endpoint, so this is
# built from local snapshots fetch_data.py records on every run; it starts
# empty and fills in as the tool gets run over time (ideally daily).
# ---------------------------------------------------------------------------

def friend_var(index):
    return f"--series-f{index}"


def end_label_groups(label_entries, prefix):
    """Decluttering pass for the end-of-line name labels shared by both rank
    charts: with few data points (or several friends sitting at a similar
    rank), the labels land on top of each other. Sort top-to-bottom and push
    any label down just enough to clear the one above it, drawing a short
    leader line back to the real point whenever a label had to move."""
    label_groups = []
    MIN_LABEL_GAP = 20
    ICON_SIZE = 14
    label_entries.sort(key=lambda e: e["ly"])
    for idx, e in enumerate(label_entries):
        e["draw_y"] = e["ly"] if idx == 0 else max(e["ly"], label_entries[idx - 1]["draw_y"] + MIN_LABEL_GAP)
    for e in label_entries:
        var, lx, ly, draw_y = e["var"], e["lx"], e["ly"], e["draw_y"]
        parts = []
        if abs(draw_y - ly) > 3:
            parts.append(
                f'<line x1="{lx + 4:.1f}" y1="{ly:.1f}" x2="{lx + 8:.1f}" y2="{draw_y:.1f}" '
                f'stroke="var({var})" stroke-width="1" stroke-dasharray="2,2" opacity="0.5" />'
            )
        icon_url = rank_icon_url(e.get("tier"))
        text_x = lx + 8
        if icon_url:
            parts.append(
                f'<image href="{esc(icon_url)}" x="{lx + 8:.1f}" y="{draw_y - ICON_SIZE / 2:.1f}" '
                f'width="{ICON_SIZE}" height="{ICON_SIZE}" onerror="this.style.visibility=\'hidden\'" />'
            )
            text_x = lx + 8 + ICON_SIZE + 3
        parts.append(
            f'<text x="{text_x:.1f}" y="{draw_y + 4:.1f}" font-size="11" font-weight="700" fill="var({var})">{esc(e["label"])}</text>'
        )
        if e["net"]:
            net_color = "var(--good)" if e["net"]["direction"] > 0 else ("var(--critical)" if e["net"]["direction"] < 0 else "var(--muted)")
            parts.append(
                f'<text x="{text_x:.1f}" y="{draw_y + 16:.1f}" font-size="10" fill="{net_color}">{esc(e["net"]["text"])}</text>'
            )
        label_groups.append(f'<g id="{prefix}-label-{e["idx"]}">{"".join(parts)}</g>')
    return label_groups


# ---------------------------------------------------------------------------
# Per-game LP chart.
#
# IMPORTANT: Riot's Match-V5 API does not return the LP change for a game —
# there is no endpoint that does. What *is* known exactly is each friend's LP
# at every daily snapshot fetch_data.py has recorded, plus the full ordered
# list of ranked Solo/Duo games played between those snapshots.
#
# So the per-game steps below are a reconstruction, not measured data: the
# snapshots are real anchor points and the shape between them is inferred by
# splitting the known net LP change across the games that produced it. Every
# point where a snapshot exists is exact; the intermediate points are an
# estimate, and the UI says so.
# ---------------------------------------------------------------------------

NOMINAL_LP = 20  # typical LP swing per ranked game, used as the prior


# tier_score() is an ordering key, not a distance: it spends 200 units on a
# division that only holds 100 LP and 1000 on a tier that only holds 4
# divisions, leaving dead zones. Splitting an LP change across that scale
# inflates every step, so this chart works in a linear ladder-LP space where
# one division is exactly 100 LP and one tier is 400.
LP_PER_DIVISION = 100
DIVISIONS_PER_TIER = 4


def ladder_lp(entry):
    """Absolute ladder position of a rank snapshot, measured in real LP."""
    tier = entry.get("tier")
    if not tier:
        return 0
    ti = TIER_ORDER.index(tier) if tier in TIER_ORDER else 0
    lp = entry.get("leaguePoints", 0) or 0
    if tier in APEX_TIERS:
        return ti * DIVISIONS_PER_TIER * LP_PER_DIVISION + lp
    division = RANK_SCORE.get(entry.get("rank"), 0)
    return (ti * DIVISIONS_PER_TIER + division) * LP_PER_DIVISION + lp


def ladder_decompose(value):
    """Inverse of ladder_lp(): (tier index, division, LP)."""
    value = max(0, int(round(value)))
    steps = value // LP_PER_DIVISION
    lp = value - steps * LP_PER_DIVISION
    ti = min(steps // DIVISIONS_PER_TIER, len(TIER_ORDER) - 1)
    division = steps - ti * DIVISIONS_PER_TIER
    return ti, min(division, DIVISIONS_PER_TIER - 1), lp


def score_to_rank_label(value):
    ti, division, lp = ladder_decompose(value)
    tier = TIER_ORDER[ti]
    if tier in APEX_TIERS:
        return f"{tier.capitalize()} &middot; {lp} LP"
    rank_by_score = {v: k for k, v in RANK_SCORE.items()}
    return f"{tier.capitalize()} {rank_by_score.get(division, 'IV')} &middot; {lp} LP"


def lp_step_label(prev_value, value, delta, exact):
    """How to describe one game's move. Within a division the step really is
    an LP change; across one it includes the promotion/demotion reset, so
    printing it as an LP number would overstate it."""
    if ladder_decompose(prev_value)[:2] != ladder_decompose(value)[:2]:
        return "promoted" if delta >= 0 else "demoted"
    return f"{'+' if delta >= 0 else '−'}{abs(delta):.0f} LP{'' if exact else ' (est.)'}"


def segment_deltas(wins, net):
    """Split a known net LP change across the games in one snapshot-to-snapshot
    segment. Solves for the win/loss step sizes closest to a nominal 20 LP that
    still land exactly on the next real snapshot: minimise (g-20)^2 + (d-20)^2
    subject to W*g - L*d = net. `wins` is the ordered list of win booleans."""
    if not wins:
        return []
    W = sum(1 for w in wins if w)
    L = len(wins) - W
    lam = (net - NOMINAL_LP * (W - L)) / (W * W + L * L)
    gain = NOMINAL_LP + lam * W
    loss = NOMINAL_LP - lam * L
    # A win must never cost LP and a loss must never gain it, so clamp the
    # solve, then spread whatever that clamping left over evenly — the line
    # still has to land on the real snapshot.
    gain, loss = max(gain, 1.0), max(loss, 1.0)
    deltas = [gain if w else -loss for w in wins]
    residual = net - sum(deltas)
    if abs(residual) > 1e-9:
        share = residual / len(deltas)
        deltas = [d + share for d in deltas]
    return deltas


def build_lp_timeline(solo_pts, solo_matches):
    """Per-game LP path for one friend, anchored on their real daily snapshots.

    Games played *before* the first snapshot are skipped — there's no known LP
    to place them against. Returns [{idx, score, delta, match, exact}] where
    idx 0 is the first snapshot itself."""
    if len(solo_pts) < 2:
        return []
    by_date = {}
    for m in solo_matches:
        by_date.setdefault(m.get("dateKey"), []).append(m)
    for lst in by_date.values():
        lst.sort(key=lambda m: m.get("gameStartMs", 0))

    points = [{"idx": 0, "score": ladder_lp(solo_pts[0]), "delta": None,
               "match": None, "exact": True}]
    idx = 0
    for prev, cur in zip(solo_pts, solo_pts[1:]):
        # A snapshot taken on day D reflects LP at whatever time the fetch ran
        # that day, so attribute games by date: everything after the previous
        # snapshot's day up to and including this one produced this change.
        seg = [m for d in sorted(by_date) if prev["date"] < d <= cur["date"] for m in by_date[d]]
        if not seg:
            continue
        start, end = ladder_lp(prev), ladder_lp(cur)
        run = start
        for m, delta in zip(seg, segment_deltas([m["win"] for m in seg], end - start)):
            run += delta
            idx += 1
            points.append({"idx": idx, "score": run, "delta": delta, "match": m, "exact": False})
        # Land exactly on the measured snapshot rather than on accumulated float.
        points[-1]["score"] = end
        points[-1]["exact"] = True
    return points


def render_lp_chart(friends_sorted, rank_history, now, tracking_since):
    """Game-by-game LP chart. Returns None when nobody has enough games inside
    the tracked window yet, so the caller can fall back to the daily chart."""
    solo_history_by_label = {}
    for h in rank_history:
        if h.get("queue") != "solo":
            continue
        solo_history_by_label.setdefault(h["label"], []).append(h)
    for pts in solo_history_by_label.values():
        pts.sort(key=lambda h: h["date"])

    timelines = {}
    for f in friends_sorted:
        pts = solo_history_by_label.get(f["label"])
        if not pts:
            continue
        solo_matches = [m for m in f.get("seasonMatches", []) if m.get("queue") == "Ranked Solo/Duo"]
        tl = build_lp_timeline(pts, solo_matches)
        if len(tl) >= 2:
            timelines[f["label"]] = tl

    chart_friends = [f for f in friends_sorted if f["label"] in timelines]
    if not chart_friends:
        return None

    omitted = []
    if len(chart_friends) > len(FRIEND_PALETTE):
        omitted = [f["label"] for f in chart_friends[len(FRIEND_PALETTE):]]
        chart_friends = chart_friends[:len(FRIEND_PALETTE)]

    max_games = max(len(timelines[f["label"]]) - 1 for f in chart_friends)
    all_scores = [p["score"] for f in chart_friends for p in timelines[f["label"]]]
    y_min, y_max = min(all_scores), max(all_scores)
    pad = max(40, (y_max - y_min) * 0.16)
    y_min, y_max = y_min - pad, y_max + pad
    if y_max <= y_min:
        y_max = y_min + 200

    # The chart is rendered twice: a wide desktop version, and a compact one
    # for phones. A single SVG can't serve both — squeezing the 900-unit
    # viewBox into a ~320px screen scaled its 11px labels down to under 4px,
    # which is unreadable. The compact build drops the end-of-line labels
    # (they alone cost 175 units of width) and thins the ticks out instead.
    legend_items, standings = [], []
    rank_by_score = {v: k for k, v in RANK_SCORE.items()}

    def build_svg(compact):
        prefix = "lpm" if compact else "lp"
        if compact:
            W = 360
            H = max(240, min(420, 20 * len(chart_friends) + 190))
            PAD_L, PAD_R, PAD_T, PAD_B = 38, 10, 12, 28
        else:
            W = 900
            H = max(300, min(660, 34 * len(chart_friends) + 140))
            PAD_L, PAD_R, PAD_T, PAD_B = 64, 175, 16, 34
        plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B

        def xy(game_idx, score):
            x = PAD_L + (game_idx / max_games if max_games else 0) * plot_w
            y = PAD_T + (1 - (score - y_min) / (y_max - y_min)) * plot_h
            return x, y

        # Gridlines on every division inside the visible range, named by tier
        # at the tier boundary so a tall chart doesn't turn into a wall of
        # labels. On a phone only the tier lines are labelled.
        tier_span = DIVISIONS_PER_TIER * LP_PER_DIVISION
        y_ticks = []
        first_div = int(y_min // LP_PER_DIVISION)
        last_div = int(y_max // LP_PER_DIVISION)
        show_divisions = (last_div - first_div) <= 12 and not compact
        for steps in range(max(first_div, 0), last_div + 1):
            tick = steps * LP_PER_DIVISION
            if not (y_min <= tick <= y_max):
                continue
            ti, division, _ = ladder_decompose(tick)
            if ti >= len(TIER_ORDER):
                continue
            if tick % tier_span == 0:
                y_ticks.append((xy(0, tick)[1], TIER_ORDER[ti].capitalize()))
            elif show_divisions:
                y_ticks.append((xy(0, tick)[1], rank_by_score.get(division, "")))

        step = max(1, round(max_games / (3 if compact else 6)))
        tick_idxs = list(range(0, max_games + 1, step))
        # Always end on the final game, but drop the tick before it if the two
        # would sit close enough to overlap.
        if tick_idxs[-1] != max_games:
            if max_games - tick_idxs[-1] < step * 0.6:
                tick_idxs.pop()
            tick_idxs.append(max_games)
        x_ticks = [(xy(gi, y_min)[0], "Start" if gi == 0 else (str(gi) if compact else f"Game {gi}"))
                   for gi in tick_idxs]

        series_groups, label_entries = [], []
        for i, f in enumerate(chart_friends):
            var = friend_var(i)
            tl = timelines[f["label"]]
            coords = [xy(p["idx"], p["score"]) for p in tl]
            parts = []
            path_d = " ".join(f"{'M' if n == 0 else 'L'}{x:.1f},{y:.1f}" for n, (x, y) in enumerate(coords))
            parts.append(
                f'<path d="{path_d}" fill="none" stroke="var({var})" stroke-width="2" '
                f'stroke-linecap="round" stroke-linejoin="round" />'
            )
            for n, ((x, y), p) in enumerate(zip(coords, tl)):
                m = p["match"]
                if m:
                    move = lp_step_label(tl[n - 1]["score"], p["score"], p["delta"], p["exact"])
                    title = (f"{f['label']} — game {p['idx']} — {'Win' if m['win'] else 'Loss'} on {m['champion']} — "
                             f"{move} → {score_to_rank_label(p['score'])}").replace("&middot;", "·")
                    fill = "var(--good)" if m["win"] else "var(--critical)"
                    r = 3 if compact else 3.5
                else:
                    title = (f"{f['label']} — tracking started — "
                             f"{score_to_rank_label(p['score'])}").replace("&middot;", "·")
                    fill = f"var({var})"
                    r = 3.5 if compact else 4
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" '
                    f'stroke="var(--surface-1)" stroke-width="1.5"><title>{esc(title)}</title></circle>'
                )
            series_groups.append(f'<g id="{prefix}-series-{i}">{"".join(parts)}</g>')

            if not compact:
                lx, ly = coords[-1]
                label_entries.append({"idx": i, "var": var, "label": f["label"], "lx": lx, "ly": ly,
                                      "net": net_labels[i], "tier": tiers[i]})

        label_groups = [] if compact else end_label_groups(label_entries, prefix)

        grid_svg = "".join(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" class="chart-grid" />'
            f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end" class="chart-tick">{esc(label)}</text>'
            for y, label in y_ticks
        )
        xticks_svg = "".join(
            f'<text x="{x:.1f}" y="{H - PAD_B + (16 if compact else 20)}" text-anchor="middle" class="chart-tick">{esc(label)}</text>'
            for x, label in x_ticks
        )
        cls = "rank-chart chart-compact" if compact else "rank-chart chart-wide"
        return (f'<svg viewBox="0 0 {W} {H}" class="{cls}" role="img" '
                f'aria-label="Ranked Solo/Duo LP game by game">'
                f'{grid_svg}{xticks_svg}{"".join(series_groups)}{"".join(label_groups)}</svg>')

    # Per-friend summary text, computed once and shared by both renders.
    net_labels, tiers = [], []
    for i, f in enumerate(chart_friends):
        tl = timelines[f["label"]]
        net_lp = tl[-1]["score"] - tl[0]["score"]
        games = len(tl) - 1
        wins = sum(1 for p in tl[1:] if p["match"] and p["match"]["win"])
        # Raw LP only means the same thing while tier and division hold still —
        # a promotion resets LP, so across one the ladder distance isn't an LP
        # number worth printing. Same rule the daily chart already uses.
        hist = solo_history_by_label[f["label"]]
        first_h, last_h = hist[0], hist[-1]
        record = f"{wins}W {games - wins}L"
        if _rank_snapshot_key(first_h) == _rank_snapshot_key(last_h):
            lp = (last_h.get("leaguePoints") or 0) - (first_h.get("leaguePoints") or 0)
            net_text = f"{'+' if lp >= 0 else '−'}{abs(lp)} LP · {record}"
        else:
            net_text = (f'{rank_label(first_h).split(" &middot;")[0]} → '
                        f'{rank_label(last_h).split(" &middot;")[0]} · {record}')
        net_labels.append({"text": net_text, "direction": 1 if net_lp > 0 else (-1 if net_lp < 0 else 0)})
        tiers.append(hist[-1].get("tier"))
        standings.append({"var": friend_var(i), "label": f["label"], "tier": hist[-1].get("tier"),
                          "rankLabel": rank_label(hist[-1]), "games": games,
                          "net": net_text})
        legend_items.append(
            f'<span class="legend-item" data-chart="lp lpm" data-idx="{i}">'
            f'<span class="sw" style="background:var({friend_var(i)})"></span>{esc(f["label"])}</span>'
        )

    charts_svg = build_svg(False) + build_svg(True)

    omitted_note = ""
    if omitted:
        omitted_note = (f'<div class="muted small" style="margin-top:8px;">Not shown: {esc(", ".join(omitted))} '
                        f'(chart shows up to {len(FRIEND_PALETTE)} friends at once).</div>')

    # The compact chart has no end-of-line labels, so the per-friend net LP
    # moves into the standings chip where a phone can still read it.
    standings_html = "".join(
        f'<div class="standing-chip" style="border-color:var({s["var"]});">'
        f'{render_rank_icon(s["tier"], size=22)}'
        f'<span class="name" style="color:var({s["var"]});">{esc(s["label"])}</span>'
        f'<span class="rank">{s["rankLabel"]}</span>'
        f'<span class="rank muted">· {s["games"]}g</span>'
        f'<span class="rank muted chip-net">· {esc(s["net"])}</span></div>'
        for s in standings
    )

    table_rows = "".join(
        f'<tr><td class="muted small">{esc(p["idx"])}</td><td>{esc(f["label"])}</td>'
        f'<td><span class="tag {"win" if p["match"]["win"] else "loss"}">{"W" if p["match"]["win"] else "L"}</span></td>'
        f'<td class="champ-cell">{render_champion_icon(p["match"]["champion"], size=18)}{esc(p["match"]["champion"])}</td>'
        f'<td class="num">{esc(lp_step_label(tl[n - 1]["score"], p["score"], p["delta"], p["exact"]))}</td>'
        f'<td class="num">{score_to_rank_label(p["score"])}</td>'
        f'<td class="muted small">{esc(p["match"].get("gameStart", ""))}</td></tr>'
        for f in chart_friends
        for tl in [timelines[f["label"]]]
        for n, p in enumerate(tl)
        if p["match"]
    )

    return f'''
    <div class="panel">
      <h2 style="margin-bottom:4px;">LP per game</h2>
      <div class="muted small" style="margin-bottom:12px;">Ranked Solo/Duo &middot; every game since rank tracking began on {esc(tracking_since)}</div>
      <div class="banner" style="margin-bottom:14px;">
        <strong>How this is built:</strong> Riot's API doesn't expose the LP change for an individual
        game, so only the daily snapshots are measured values. The steps in between reconstruct the
        known net LP change across the games that produced it, which means the shape of each run is an
        estimate even though every snapshot it passes through is exact.
      </div>
      <div class="muted small" style="margin-bottom:6px;">Current standings</div>
      <div class="standings">{standings_html}</div>
      {charts_svg}
      <div class="legend" style="justify-content:flex-start;">{"".join(legend_items)}</div>
      <div class="muted small" style="margin-top:2px;">Tap a name above to show/hide that friend's line. Tap any point for the game behind it.</div>
      {omitted_note}
      <details class="matches-details" style="margin-top:10px;">
        <summary>View as table</summary>
        <table class="matches-table">
          <thead><tr><th>Game</th><th>Friend</th><th>Result</th><th>Champion</th><th class="num">LP</th><th class="num">Rank after</th><th>When</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
      </details>
    </div>'''


def render_rank_chart(friends_sorted, rank_history, now, tracking_since):
    solo_history_by_label = {}
    for h in rank_history:
        if h.get("queue") != "solo":
            continue
        solo_history_by_label.setdefault(h["label"], []).append(h)
    for pts in solo_history_by_label.values():
        pts.sort(key=lambda h: h["date"])

    chart_friends = [f for f in friends_sorted if f["label"] in solo_history_by_label]
    if not chart_friends:
        return f'''
    <div class="panel">
      <h2 style="margin-bottom:8px;">Rank progress</h2>
      <div class="muted small">No rank history yet — Riot's API doesn't expose past ranks, so this
      builds up from snapshots taken each time you run <code>fetch_data.py</code>. Run it again
      tomorrow (and keep running it, ideally daily) to start seeing a trend line here.</div>
    </div>'''

    omitted = []
    if len(chart_friends) > len(FRIEND_PALETTE):
        omitted = [f["label"] for f in chart_friends[len(FRIEND_PALETTE):]]
        chart_friends = chart_friends[:len(FRIEND_PALETTE)]

    end_date = now.date()
    earliest_date = min(
        datetime.strptime(h["date"], "%Y-%m-%d").date()
        for f in chart_friends for h in solo_history_by_label[f["label"]]
    )
    # Anchor the axis to the first real snapshot instead of always spanning a
    # full 30 days — with only a few days of tracking history, a fixed
    # 30-day window left most of the chart empty. Still capped at 30 days
    # back so the axis doesn't keep growing forever once history piles up.
    start_date = max(earliest_date, end_date - timedelta(days=29))
    span_days = max((end_date - start_date).days, 1)

    def x_frac(date_key):
        d = datetime.strptime(date_key, "%Y-%m-%d").date()
        return max(0.0, min(1.0, (d - start_date).days / span_days))

    all_scores = [
        tier_score({"tier": h["tier"], "rank": h.get("rank"), "leaguePoints": h.get("leaguePoints")})
        for f in chart_friends for h in solo_history_by_label[f["label"]]
    ]
    y_min, y_max = min(all_scores), max(all_scores)
    pad = max(250, (y_max - y_min) * 0.2)
    y_min -= pad
    y_max += pad
    if y_max <= y_min:
        y_max = y_min + 400

    # Chart height scales with how many friends are on it — with a fixed
    # height, a crowded group (several friends at similar rank) forces the
    # label-decluttering pass to compress everything into too little
    # vertical room, which is what actually made a big group feel
    # cluttered rather than the line chart itself. Capped so a huge group
    # doesn't produce an absurdly tall panel.
    W = 900
    H = max(280, min(640, 34 * len(chart_friends) + 120))
    PAD_L, PAD_R, PAD_T, PAD_B = 64, 170, 16, 30
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def xy(date_key, score):
        x = PAD_L + x_frac(date_key) * plot_w
        y = PAD_T + (1 - (score - y_min) / (y_max - y_min)) * plot_h
        return x, y

    # Y gridlines at whole-tier boundaries within the visible score range.
    lo_ti, hi_ti = int(y_min // 1000), int(y_max // 1000) + 1
    y_ticks = []
    for ti in range(max(lo_ti, 0), min(hi_ti + 1, len(TIER_ORDER))):
        tick_score = ti * 1000
        if y_min <= tick_score <= y_max:
            _, y = xy(start_date.strftime("%Y-%m-%d"), tick_score)
            y_ticks.append((y, TIER_ORDER[ti].capitalize()))

    # X ticks roughly weekly, plus today — drop the last weekly tick if it'd
    # land close enough to "Today" for the labels to overlap.
    x_ticks = []
    for i in range(0, span_days, 7):
        if span_days - i < 4:
            continue
        d = start_date + timedelta(days=i)
        x, _ = xy(d.strftime("%Y-%m-%d"), y_min)
        x_ticks.append((x, d.strftime("%b %d")))
    x_today, _ = xy(end_date.strftime("%Y-%m-%d"), y_min)
    x_ticks.append((x_today, "Today"))

    series_groups, legend_items, standings = [], [], []
    label_entries = []  # end-of-line labels, positioned after a declutter pass below
    for i, f in enumerate(chart_friends):
        var = friend_var(i)
        pts = solo_history_by_label[f["label"]]
        coords = [
            xy(h["date"], tier_score({"tier": h["tier"], "rank": h.get("rank"), "leaguePoints": h.get("leaguePoints")}))
            for h in pts
        ]
        series_parts = []
        if len(coords) >= 2:
            path_d = " ".join(f"{'M' if idx == 0 else 'L'}{x:.1f},{y:.1f}" for idx, (x, y) in enumerate(coords))
            series_parts.append(
                f'<path d="{path_d}" fill="none" stroke="var({var})" stroke-width="2" '
                f'stroke-linecap="round" stroke-linejoin="round" />'
            )
        for idx, ((x, y), h) in enumerate(zip(coords, pts)):
            change = snapshot_change_label(pts[idx - 1] if idx > 0 else None, h)
            title = f"{f['label']} — {h['date']} — {rank_label(h)}".replace("&middot;", "·")
            if change:
                title += f" ({change})"
            series_parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="var({var})" '
                f'stroke="var(--surface-1)" stroke-width="1.5"><title>{esc(title)}</title></circle>'
            )
        series_groups.append(f'<g id="daily-series-{i}">{"".join(series_parts)}</g>')
        if coords:
            lx, ly = coords[-1]
            net = net_change_label(pts[0], pts[-1]) if len(pts) >= 2 else None
            label_entries.append({"idx": i, "var": var, "label": f["label"], "lx": lx, "ly": ly, "net": net, "tier": pts[-1].get("tier")})
            standings.append({"var": var, "label": f["label"], "tier": pts[-1].get("tier"), "rankLabel": rank_label(pts[-1])})
        legend_items.append(
            f'<span class="legend-item" data-chart="daily" data-idx="{i}"><span class="sw" style="background:var({var})"></span>{esc(f["label"])}</span>'
        )

    label_groups = end_label_groups(label_entries, "daily")

    grid_svg = "".join(
        f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" class="chart-grid" />'
        f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" class="chart-tick">{esc(label)}</text>'
        for y, label in y_ticks
    )
    xticks_svg = "".join(
        f'<text x="{x:.1f}" y="{H - PAD_B + 18}" text-anchor="middle" class="chart-tick">{esc(label)}</text>'
        for x, label in x_ticks
    )

    omitted_note = ""
    if omitted:
        omitted_note = f'<div class="muted small" style="margin-top:8px;">Not shown: {esc(", ".join(omitted))} (chart shows up to {len(FRIEND_PALETTE)} friends at once).</div>'

    table_rows = "".join(
        f'<tr><td class="muted small">{esc(h["date"])}</td><td>{esc(f["label"])}</td><td>{rank_label(h)}</td>'
        f'<td class="muted small">{esc(snapshot_change_label(pts[idx - 1] if idx > 0 else None, h) or "—")}</td></tr>'
        for f in chart_friends
        for pts in [solo_history_by_label[f["label"]]]
        for idx, h in enumerate(pts)
    )

    distinct_dates = {h["date"] for f in chart_friends for h in solo_history_by_label[f["label"]]}
    sparse_note = ""
    if len(distinct_dates) < 2:
        sparse_note = (f'<div class="banner" style="margin-top:12px;">Rank tracking only started '
                        f'{esc(tracking_since)}, so there\'s just one snapshot so far — the trend line '
                        f'will build in as you keep running <code>fetch_data.py</code> (ideally daily).</div>')

    standings_html = "".join(
        f'<div class="standing-chip" style="border-color:var({s["var"]});">'
        f'{render_rank_icon(s["tier"], size=22)}'
        f'<span class="name" style="color:var({s["var"]});">{esc(s["label"])}</span>'
        f'<span class="rank">{s["rankLabel"]}</span></div>'
        for s in standings
    )

    header_days = span_days + 1
    return f'''
    <div class="panel">
      <h2 style="margin-bottom:4px;">Rank progress (last {header_days} day{"s" if header_days != 1 else ""})</h2>
      <div class="muted small" style="margin-bottom:14px;">Ranked Solo/Duo &middot; tracking since {esc(tracking_since)}</div>
      <div class="muted small" style="margin-bottom:6px;">Current standings</div>
      <div class="standings">{standings_html}</div>
      <svg viewBox="0 0 {W} {H}" class="rank-chart chart-wide" role="img" aria-label="Ranked Solo/Duo standing over the last {header_days} days">
        {grid_svg}
        {xticks_svg}
        {"".join(series_groups)}
        {"".join(label_groups)}
      </svg>
      <div class="legend" style="justify-content:flex-start;">{"".join(legend_items)}</div>
      <div class="muted small" style="margin-top:2px;">Click a name above to show/hide that friend's line.</div>
      {omitted_note}
      {sparse_note}
      <details class="matches-details" style="margin-top:10px;">
        <summary>View as table</summary>
        <table class="matches-table">
          <thead><tr><th>Date</th><th>Friend</th><th>Rank</th><th>Change</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
      </details>
    </div>'''


# ---------------------------------------------------------------------------
# Highlights / "awards" — fun, derived call-outs computed across everyone's
# recent games. Purely for entertainment; thresholds are tuned to only fire
# when there's something notable, so the section can come up short (that's
# fine — better than manufacturing a "worst" for someone who's been fine).
# ---------------------------------------------------------------------------

def collect_all_matches(friends):
    rows = []
    for f in friends:
        for m in f.get("recentMatches", []):
            rows.append((f, m))
    return rows


def kda_score(m):
    return (m["kills"] + m["assists"]) / max(m["deaths"], 1)


def current_streak(matches, want_win):
    """Matches are assumed most-recent-first (as Riot returns them)."""
    streak = 0
    for m in matches:
        if m["win"] == want_win:
            streak += 1
        else:
            break
    return streak


def compute_awards(friends, now):
    awards = []
    pairs = collect_all_matches(friends)
    if not pairs:
        return awards

    # MVP performance — best single-game KDA ratio across everyone.
    f, m = max(pairs, key=lambda p: kda_score(p[1]))
    if kda_score(m) >= 3:
        awards.append({
            "icon": "🏆", "title": "MVP performance",
            "text": f"{esc(f['label'])} popped off on {esc(m['champion'])} — "
                    f"{m['kills']}/{m['deaths']}/{m['assists']} (KDA {kda_score(m):.1f}).",
        })

    # Untouchable — a win with zero deaths and a meaningful kill/assist total.
    flawless = [p for p in pairs if p[1]["win"] and p[1]["deaths"] == 0 and (p[1]["kills"] + p[1]["assists"]) >= 8]
    if flawless:
        f, m = max(flawless, key=lambda p: p[1]["kills"] + p[1]["assists"])
        awards.append({
            "icon": "🛡️", "title": "Untouchable",
            "text": f"{esc(f['label'])} didn't die once on {esc(m['champion'])} — {m['kills']}/{m['deaths']}/{m['assists']}.",
        })

    # Int alert — a rough loss with a lot of deaths.
    rough_losses = [p for p in pairs if not p[1]["win"] and p[1]["deaths"] >= 6]
    if rough_losses:
        f, m = max(rough_losses, key=lambda p: p[1]["deaths"])
        awards.append({
            "icon": "💀", "title": "Int alert",
            "text": f"{esc(f['label'])} went {m['kills']}/{m['deaths']}/{m['assists']} on {esc(m['champion'])} in a loss. Rough one.",
        })

    # Farm god — highest CS/min in a single game.
    farmable = [p for p in pairs if p[1].get("csPerMin", 0) > 0]
    if farmable:
        f, m = max(farmable, key=lambda p: p[1]["csPerMin"])
        awards.append({
            "icon": "🌾", "title": "Farm god",
            "text": f"{esc(f['label'])} hit {m['csPerMin']} CS/min on {esc(m['champion'])}.",
        })

    # On a heater — longest current win streak (min 3), across friends.
    best_streak = None
    for f in friends:
        s = current_streak(f.get("recentMatches", []), True)
        if s >= 3 and (best_streak is None or s > best_streak[1]):
            best_streak = (f, s)
    if best_streak:
        f, s = best_streak
        awards.append({
            "icon": "🔥", "title": "On a heater",
            "text": f"{esc(f['label'])} is on a {s}-game win streak.",
        })

    # Tilt patrol — longest current loss streak (min 3), across friends.
    worst_streak = None
    for f in friends:
        s = current_streak(f.get("recentMatches", []), False)
        if s >= 3 and (worst_streak is None or s > worst_streak[1]):
            worst_streak = (f, s)
    if worst_streak:
        f, s = worst_streak
        awards.append({
            "icon": "📉", "title": "Tilt patrol",
            "text": f"{esc(f['label'])} has dropped {s} in a row. Might be time for a break.",
        })

    # Support life — most assists in a single game.
    f, m = max(pairs, key=lambda p: p[1]["assists"])
    if m["assists"] >= 12:
        awards.append({
            "icon": "🎯", "title": "Playmaker",
            "text": f"{esc(f['label'])} racked up {m['assists']} assists on {esc(m['champion'])}.",
        })

    # Most active this week — highest playtime in the trailing 7 days.
    best_week = None
    for f in friends:
        season_matches = f.get("seasonMatches", f.get("recentMatches", []))
        mins, games = weekly_playtime(season_matches, now)
        if games and (best_week is None or mins > best_week[1]):
            best_week = (f, mins, games)
    if best_week:
        f, mins, games = best_week
        awards.append({
            "icon": "⏱️", "title": "Most active this week",
            "text": f"{esc(f['label'])} played {format_minutes(mins)} across {games} games in the last 7 days.",
        })

    # Marathon day — the single busiest day this season, across everyone.
    best_day = None
    for f in friends:
        season_matches = f.get("seasonMatches", f.get("recentMatches", []))
        date_key, count = busiest_day(season_matches)
        if date_key and (best_day is None or count > best_day[2]):
            best_day = (f, date_key, count)
    if best_day and best_day[2] >= 3:
        f, date_key, count = best_day
        awards.append({
            "icon": "📅", "title": "Marathon day",
            "text": f"{esc(f['label'])} played {count} games on {format_day_label(date_key)} — the busiest single day this season.",
        })

    # Damage dealer — highest single-game damage to champions.
    damaging = [p for p in pairs if p[1].get("damageDealt", 0) > 0]
    if damaging:
        f, m = max(damaging, key=lambda p: p[1]["damageDealt"])
        if m["damageDealt"] >= 20000:
            awards.append({
                "icon": "💥", "title": "Damage dealer",
                "text": f"{esc(f['label'])} dealt {m['damageDealt']:,} damage to champions on {esc(m['champion'])}.",
            })

    # Speed run — fastest ranked win.
    quick_wins = [p for p in pairs if p[1]["win"] and p[1].get("durationMin", 0) > 0]
    if quick_wins:
        f, m = min(quick_wins, key=lambda p: p[1]["durationMin"])
        if m["durationMin"] <= 22:
            awards.append({
                "icon": "⚡", "title": "Speed run",
                "text": f"{esc(f['label'])} closed one out in just {format_minutes(m['durationMin'])} on {esc(m['champion'])}.",
            })

    # The long game — longest ranked match of the season.
    if pairs:
        f, m = max(pairs, key=lambda p: p[1].get("durationMin", 0))
        if m.get("durationMin", 0) >= 45:
            result = "won" if m["win"] else "lost"
            awards.append({
                "icon": "⏳", "title": "The long game",
                "text": f"{esc(f['label'])} slugged through a {format_minutes(m['durationMin'])} game on {esc(m['champion'])} and {result} it.",
            })

    # Season grinder — most ranked games played this season, across everyone.
    most_games = None
    for f in friends:
        season_matches = f.get("seasonMatches", f.get("recentMatches", []))
        count = len(season_matches)
        if count and (most_games is None or count > most_games[1]):
            most_games = (f, count)
    if most_games and most_games[1] >= 20:
        f, count = most_games
        awards.append({
            "icon": "🎮", "title": "Season grinder",
            "text": f"{esc(f['label'])} has racked up {count} ranked games this season — more than anyone else in the group.",
        })

    # Comeback kid — a win despite the roughest KDA of anyone's winning games.
    scrappy_wins = [p for p in pairs if p[1]["win"] and p[1]["deaths"] >= 5 and kda_score(p[1]) < 2]
    if scrappy_wins:
        f, m = max(scrappy_wins, key=lambda p: p[1]["deaths"])
        awards.append({
            "icon": "🩹", "title": "Comeback kid",
            "text": f"{esc(f['label'])} still won going {m['kills']}/{m['deaths']}/{m['assists']} on {esc(m['champion'])}. Grit over stats.",
        })

    return awards[:12]


def render_award(a):
    return f'''<div class="award">
      <div class="award-icon">{a["icon"]}</div>
      <div>
        <div class="award-title">{esc(a["title"])}</div>
        <div class="award-text">{a["text"]}</div>
      </div>
    </div>'''


def render_duo_synergy_panel(friends):
    rows = compute_duo_synergy(friends)
    if not rows:
        return ""
    body = "".join(
        f'<tr><td>{esc(r["a"])} &amp; {esc(r["b"])}</td><td class="num">{r["games"]}</td>'
        f'<td class="num">{r["wins"]}W {r["losses"]}L</td><td class="num">{r["winrate"]}%</td></tr>'
        for r in rows
    )
    return f'''
    <div class="panel">
      <h2 style="margin-bottom:4px;">Duo synergy</h2>
      <div class="muted small" style="margin-bottom:14px;">Winrate when two friends were teammates in the same ranked game (2+ games together, this season).</div>
      <table>
        <thead><tr><th>Pair</th><th class="num">Games together</th><th class="num">Record</th><th class="num">Winrate</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>'''


def render_week_glance_panel(friends_sorted, awards, rank_history, now):
    tiles = []
    if awards:
        top = awards[0]
        tiles.append((top["icon"], top["title"], top["text"]))

    best_week = None
    for f in friends_sorted:
        season_matches = f.get("seasonMatches", f.get("recentMatches", []))
        mins, games = weekly_playtime(season_matches, now)
        if games and (best_week is None or mins > best_week[1]):
            best_week = (f, mins, games)
    if best_week:
        f, mins, games = best_week
        tiles.append(("⏱️", "Most active", f"{esc(f['label'])} played {format_minutes(mins)} across {games} games this week."))

    climber = weekly_rank_leader(rank_history, now)
    if climber and climber.get("text"):
        tiles.append(("📈", "Biggest climber", f"{esc(climber['label'])} — {esc(climber['text'])} this week."))

    if not tiles:
        return ""

    tiles_html = "".join(
        f'<div class="award"><div class="award-icon">{icon}</div><div>'
        f'<div class="award-title">{esc(title)}</div><div class="award-text">{text}</div></div></div>'
        for icon, title, text in tiles
    )
    return f'''
    <div class="panel">
      <h2 style="margin-bottom:14px;">This week at a glance</h2>
      <div class="awards">{tiles_html}</div>
    </div>'''


def build_html(data):
    friends = data.get("friends", [])
    friends_sorted = sorted(friends, key=lambda f: tier_score(f["ranked"].get("solo")), reverse=True)
    now = datetime.now()
    rank_history = data.get("rankHistory", [])
    set_icon_context(data.get("ddragonVersion"), data.get("championIconMap", {}))

    leaderboard_rows = "".join(
        render_leaderboard_row(f, i + 1, weekly_trend_for(rank_history, f["label"], now))
        for i, f in enumerate(friends_sorted)
    )
    cards = "".join(render_friend_card(f, i + 1, now) for i, f in enumerate(friends_sorted))
    friend_pills = "".join(
        f'<button class="pill{" active" if i == 0 else ""}" type="button" data-friend="{f["label"].lower()}">{esc(f["label"])}</button>'
        for i, f in enumerate(friends_sorted)
    )

    awards = compute_awards(friends_sorted, now)
    awards_panel = ""
    if awards:
        awards_html = "".join(render_award(a) for a in awards)
        awards_panel = f'''
    <div class="panel">
      <h2 style="margin-bottom:14px;">Highlights</h2>
      <div class="awards">{awards_html}</div>
    </div>'''

    week_glance_panel = render_week_glance_panel(friends_sorted, awards, rank_history, now)
    duo_synergy_panel = render_duo_synergy_panel(friends_sorted)

    tracking_since = data.get("rankTrackingSince", "recently")
    # Per-game LP is the primary view; it needs at least one snapshot-to-
    # snapshot interval with games in it, so fall back to the daily-snapshot
    # chart alone until that exists.
    lp_chart_panel = render_lp_chart(friends_sorted, rank_history, now, tracking_since)
    daily_chart_panel = render_rank_chart(friends_sorted, rank_history, now, tracking_since)
    if lp_chart_panel:
        # The 30-day chart has no phone-sized build, and on a small screen it
        # says less than the per-game chart directly above it. Hide it there
        # rather than render one that can't be read.
        daily_chart_panel = f'<div class="wide-screen-only">{daily_chart_panel}</div>'
    rank_chart_panel = (lp_chart_panel or "") + daily_chart_panel

    # Flat export of every friend's season matches, embedded once as JSON so
    # the "Export CSV" button can build a CSV client-side with no server and
    # no re-fetching — just a browser-side Blob download.
    season_export = [
        {**m, "friend": f["label"]}
        for f in friends_sorted
        for m in f.get("seasonMatches", [])
    ]
    season_export_json = json.dumps(season_export, ensure_ascii=False)

    demo_banner = ""
    if data.get("demo"):
        demo_banner = '''<div class="banner">This is sample data so you can preview the dashboard. Run
        <code>python3 fetch_data.py</code> after adding your Riot API key and friends to
        <code>config.json</code> to replace it with real stats.</div>'''

    # Build the tier CSS variable blocks (light default, dark override via
    # both the OS media query and the manual toggle) from TIER_COLOR so the
    # markup only ever references var(--tier-xxx).
    tier_vars_light = "\n    ".join(f"{tier_var(t)}: {c['light']};" for t, c in TIER_COLOR.items())
    tier_vars_light += f"\n    {tier_var(None)}: {DEFAULT_TIER_COLOR['light']};"
    tier_vars_dark = "\n      ".join(f"{tier_var(t)}: {c['dark']};" for t, c in TIER_COLOR.items())
    tier_vars_dark += f"\n      {tier_var(None)}: {DEFAULT_TIER_COLOR['dark']};"

    friend_vars_light = "\n    ".join(f"{friend_var(i)}: {c['light']};" for i, c in enumerate(FRIEND_PALETTE))
    friend_vars_dark = "\n      ".join(f"{friend_var(i)}: {c['dark']};" for i, c in enumerate(FRIEND_PALETTE))

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>League Friends Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    color-scheme: light;
    --surface-1: #ffffff;
    --surface-2: #f3f5f9;
    --page: #eceff5;
    --text-primary: #0d1117;
    --text-secondary: #4c5566;
    --muted: #8a93a4;
    --gridline: #e3e7ee;
    --border: rgba(13,17,23,0.10);
    --accent: #2f6feb;
    --accent-2: #00b3a4;
    --gold: #c9971f;
    --silver: #7f8b9e;
    --bronze: #b0713f;
    --series-1: #2a78d6;
    --series-2: #eb6834;
    --good: #10a152;
    --critical: #d03b3b;
    --shadow-sm: 0 1px 2px rgba(13,17,23,0.05), 0 1px 3px rgba(13,17,23,0.04);
    --shadow-md: 0 4px 14px rgba(13,17,23,0.07);
    --shadow-lg: 0 14px 36px rgba(13,17,23,0.11);
    --radius: 14px;
    --radius-sm: 10px;
    --halo: rgba(47,111,235,0.10);
    {tier_vars_light}
    {friend_vars_light}
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
      --surface-1: #14161d;
      --surface-2: #1b1f28;
      --page: #090a0e;
      --text-primary: #f1f3f7;
      --text-secondary: #b4bbc9;
      --muted: #7c8698;
      --gridline: #262b35;
      --border: rgba(255,255,255,0.09);
      --accent: #4c8dff;
      --accent-2: #17d3c1;
      --gold: #e6c15c;
      --silver: #a7b1c1;
      --bronze: #cc8a5b;
      --series-1: #4c8dff;
      --series-2: #ff7a45;
      --good: #2ecc71;
      --critical: #ff5f5f;
      --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
      --shadow-md: 0 6px 18px rgba(0,0,0,0.45);
      --shadow-lg: 0 18px 44px rgba(0,0,0,0.55);
      --halo: rgba(76,141,255,0.16);
      {tier_vars_dark}
      {friend_vars_dark}
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --surface-1: #14161d;
    --surface-2: #1b1f28;
    --page: #090a0e;
    --text-primary: #f1f3f7;
    --text-secondary: #b4bbc9;
    --muted: #7c8698;
    --gridline: #262b35;
    --border: rgba(255,255,255,0.09);
    --accent: #4c8dff;
    --accent-2: #17d3c1;
    --gold: #e6c15c;
    --silver: #a7b1c1;
    --bronze: #cc8a5b;
    --series-1: #4c8dff;
    --series-2: #ff7a45;
    --good: #2ecc71;
    --critical: #ff5f5f;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
    --shadow-md: 0 6px 18px rgba(0,0,0,0.45);
    --shadow-lg: 0 18px 44px rgba(0,0,0,0.55);
    --halo: rgba(76,141,255,0.16);
    {tier_vars_dark}
    {friend_vars_dark}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page);
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
    background-image:
      radial-gradient(900px 500px at 12% -8%, var(--halo), transparent 70%),
      radial-gradient(760px 420px at 96% 0%, rgba(0,179,164,0.09), transparent 68%);
    background-attachment: fixed;
  }}
  h1, h2, h3, .stat-value, .brand-mark {{ font-family: "Outfit", "Inter", system-ui, sans-serif; }}
  .wrap {{ max-width: 1060px; margin: 0 auto; padding: 30px 20px 80px; }}

  /* ---- Header ------------------------------------------------------- */
  header.top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 22px; gap: 16px; flex-wrap: wrap; }}
  .brand {{ display: flex; align-items: center; gap: 14px; min-width: 0; }}
  .brand-mark {{
    width: 46px; height: 46px; border-radius: 13px; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center; font-size: 22px;
    background: linear-gradient(140deg, var(--accent), var(--accent-2));
    box-shadow: 0 6px 18px var(--halo);
  }}
  header.top h1 {{
    margin: 0 0 5px; font-size: 27px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.1;
  }}
  .meta-row {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .meta-chip {{
    font-size: 11px; font-weight: 500; color: var(--text-secondary);
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 999px; padding: 3px 10px; white-space: nowrap;
  }}
  .meta-chip b {{ font-weight: 700; color: var(--text-primary); }}
  .header-actions {{ display: flex; gap: 8px; flex-shrink: 0; }}
  #theme-toggle, #export-csv {{
    flex-shrink: 0; height: 40px; border-radius: 11px;
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
    font-family: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
    display: flex; align-items: center; justify-content: center; gap: 7px;
    box-shadow: var(--shadow-sm); transition: transform .16s ease, box-shadow .16s ease, background .16s ease;
  }}
  #theme-toggle {{ width: 40px; font-size: 17px; padding: 0; }}
  #export-csv {{ padding: 0 15px; }}
  #theme-toggle:hover, #export-csv:hover {{ transform: translateY(-1px); box-shadow: var(--shadow-md); background: var(--surface-2); }}
  #theme-toggle:active, #export-csv:active {{ transform: translateY(0); }}
  :focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 8px; }}

  .badge-fresh {{
    display: inline-block; font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 40%, transparent);
    border-radius: 999px; padding: 2px 8px; margin-right: 8px;
  }}
  .banner {{
    background: color-mix(in srgb, var(--accent) 8%, var(--surface-1));
    border: 1px solid color-mix(in srgb, var(--accent) 26%, transparent);
    border-radius: var(--radius-sm);
    padding: 12px 16px; margin-bottom: 20px; font-size: 13px; color: var(--text-secondary);
  }}
  .banner code {{ background: rgba(128,128,128,0.16); padding: 1px 5px; border-radius: 4px; }}

  /* ---- Panels ------------------------------------------------------- */
  .panel {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 22px; margin-bottom: 20px; box-shadow: var(--shadow-sm);
  }}
  h2 {{ font-size: 18px; margin: 0; font-weight: 700; letter-spacing: -0.01em; }}
  .panel > h2:first-child {{ display: flex; align-items: center; gap: 9px; }}
  .panel > h2:first-child::before {{
    content: ""; width: 3px; height: 17px; border-radius: 2px; flex-shrink: 0;
    background: linear-gradient(var(--accent), var(--accent-2));
  }}

  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{ text-align: left; color: var(--muted); font-weight: 600; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.05em; padding: 8px; border-bottom: 1px solid var(--gridline); }}
  td {{ padding: 10px 8px; border-bottom: 1px solid var(--gridline); }}
  tbody tr {{ transition: background .14s ease; }}
  tbody tr:hover {{ background: var(--surface-2); }}
  tbody tr:last-child td {{ border-bottom: none; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .muted {{ color: var(--muted); }}
  .small {{ font-size: 12px; }}
  a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
  a:hover {{ text-decoration: underline; }}

  /* Leaderboard: the table is much wider than its content, and auto layout
     parked all that slack in the middle (Rank), leaving a dead gap before
     Winrate. Fixed widths park it in the name column instead, so the row
     reads as "medal + name" then a tight block of stats on the right.
     Reverts to auto on small screens so the columns can shrink naturally. */
  /* Below the fixed-layout breakpoint the trend text ("Emerald III → Emerald
     IV") forces a min-width wider than a phone panel, so let it scroll in
     place rather than spill past the panel's rounded edge. */
  .table-scroll {{ overflow-x: auto; }}
  .leaderboard {{ table-layout: fixed; min-width: 100%; }}
  .leaderboard th:nth-child(1), .leaderboard td:nth-child(1) {{ width: 5%; text-align: center; }}
  .leaderboard th:nth-child(2), .leaderboard td:nth-child(2) {{ width: 24%; }}
  .leaderboard th:nth-child(3), .leaderboard td:nth-child(3) {{ width: 17%; }}
  .leaderboard th:nth-child(4), .leaderboard td:nth-child(4) {{ width: 11%; }}
  .leaderboard th:nth-child(5), .leaderboard td:nth-child(5) {{ width: 16%; }}
  .leaderboard th:nth-child(6), .leaderboard td:nth-child(6) {{ width: 27%; }}
  @media (max-width: 720px) {{ .leaderboard {{ table-layout: auto; }} }}

  /* Leaderboard position medals */
  .pos {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 24px; height: 24px; border-radius: 8px; font-size: 12px; font-weight: 700;
    background: var(--surface-2); color: var(--muted); font-variant-numeric: tabular-nums;
  }}
  .pos-1 {{ background: color-mix(in srgb, var(--gold) 20%, transparent); color: var(--gold); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--gold) 45%, transparent); }}
  .pos-2 {{ background: color-mix(in srgb, var(--silver) 20%, transparent); color: var(--silver); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--silver) 45%, transparent); }}
  .pos-3 {{ background: color-mix(in srgb, var(--bronze) 20%, transparent); color: var(--bronze); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--bronze) 45%, transparent); }}

  /* ---- Award / highlight cards -------------------------------------- */
  .awards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(258px, 1fr)); gap: 12px; }}
  .award {{
    display: flex; gap: 12px; align-items: flex-start; background: var(--surface-2);
    border: 1px solid var(--border); border-radius: 12px; padding: 13px 14px;
    position: relative; overflow: hidden;
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
  }}
  .award::before {{
    content: ""; position: absolute; inset: 0 auto 0 0; width: 3px;
    background: linear-gradient(var(--accent), var(--accent-2)); opacity: .75;
  }}
  .award:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-md); border-color: color-mix(in srgb, var(--accent) 32%, var(--border)); }}
  .award-icon {{
    font-size: 19px; line-height: 1; flex-shrink: 0;
    width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
    background: var(--surface-1); border: 1px solid var(--border);
  }}
  .award-title {{ font-weight: 700; font-size: 13px; margin-bottom: 3px; letter-spacing: -0.01em; }}
  .award-text {{ font-size: 12px; color: var(--text-secondary); line-height: 1.45; }}

  /* ---- Friend cards -------------------------------------------------- */
  .card {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 22px; margin-bottom: 20px; box-shadow: var(--shadow-sm);
  }}
  .card-head {{ display: flex; align-items: center; gap: 13px; margin-bottom: 18px; flex-wrap: wrap; }}
  .rank-badge {{
    width: 38px; height: 38px; border-radius: 12px; background: var(--surface-2);
    border: 1px solid var(--border); display: flex; align-items: center; justify-content: center;
    font-family: "Outfit", sans-serif; font-weight: 700; font-size: 14px; color: var(--text-secondary); flex-shrink: 0;
  }}
  .card-head h2 {{ margin: 0; font-size: 19px; }}
  .hot {{
    margin-left: auto; font-size: 11px; font-weight: 700; color: #d1740b;
    background: rgba(235,104,52,0.14); border: 1px solid rgba(235,104,52,0.35);
    border-radius: 999px; padding: 4px 11px;
  }}

  .rank-rows {{ display: flex; flex-direction: column; gap: 11px; margin-bottom: 16px; }}
  .rank-row {{ display: grid; grid-template-columns: 150px 70px 1fr 152px; align-items: center; gap: 10px; font-size: 13px; }}
  .rank-label {{ font-weight: 700; }}
  .wr-track {{ height: 8px; border-radius: 999px; background: var(--gridline); overflow: hidden; }}
  .wr-fill {{ height: 100%; border-radius: 999px; transition: width .5s cubic-bezier(.4,0,.2,1); }}
  .wr-text {{ font-variant-numeric: tabular-nums; color: var(--text-secondary); text-align: right; }}

  .section-label {{
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--muted); font-weight: 600; margin: 18px 0 9px;
  }}
  .dots {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  .dot {{
    width: 15px; height: 15px; border-radius: 5px; display: inline-block;
    transition: transform .12s ease; cursor: default;
  }}
  .dot:hover {{ transform: scale(1.25); }}
  .dot.win {{ background: var(--good); box-shadow: 0 1px 4px color-mix(in srgb, var(--good) 40%, transparent); }}
  .dot.loss {{ background: var(--critical); box-shadow: 0 1px 4px color-mix(in srgb, var(--critical) 35%, transparent); }}

  .season-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(152px, 1fr)); gap: 10px; margin-top: 14px; }}
  .stat-tile {{
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 11px; padding: 12px 14px;
    transition: transform .16s ease, border-color .16s ease;
  }}
  .stat-tile:hover {{ transform: translateY(-2px); border-color: color-mix(in srgb, var(--accent) 30%, var(--border)); }}
  .stat-value {{ font-size: 23px; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; line-height: 1.15; }}
  .stat-label {{ font-size: 11px; color: var(--muted); margin-top: 3px; line-height: 1.35; }}

  /* ---- Rank chart ---------------------------------------------------- */
  .rank-chart {{ width: 100%; height: auto; overflow: visible; }}
  .chart-grid {{ stroke: var(--gridline); stroke-width: 1; }}
  .chart-tick {{ fill: var(--muted); font-size: 11px; font-family: "Inter", system-ui, sans-serif; }}
  .rank-chart circle {{ transition: r .12s ease; }}
  .rank-chart circle:hover {{ r: 6; }}

  .chips {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .chip {{
    display: flex; align-items: center; gap: 9px; background: var(--surface-2);
    border: 1px solid var(--border); border-radius: 11px; padding: 7px 12px 7px 8px; min-width: 116px;
    transition: transform .16s ease, border-color .16s ease;
  }}
  .chip:hover {{ transform: translateY(-2px); border-color: color-mix(in srgb, var(--accent) 30%, var(--border)); }}
  .chip > div {{ display: flex; flex-direction: column; gap: 1px; }}
  .chip-name {{ font-weight: 600; font-size: 13px; }}
  .chip-level {{ font-size: 11px; color: var(--accent); font-weight: 700; }}
  .chip-points {{ font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; }}

  .champ-icon {{ border-radius: 6px; vertical-align: middle; flex-shrink: 0; object-fit: cover; }}
  .champ-icon-ph {{ display: inline-block; }}
  .champ-cell {{ display: flex; align-items: center; gap: 8px; }}
  .nemesis-row {{ display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }}

  .rank-icon {{ vertical-align: middle; flex-shrink: 0; object-fit: contain; }}
  .rank-icon-ph {{ display: inline-block; }}
  .rank-cell {{ display: flex; align-items: center; gap: 7px; }}
  /* On a <td> the flex display would take the cell out of the table's column
     layout (it stops being a table-cell), so it ignores the column width and
     spills. Keep table semantics there and space the icon with a margin. */
  td.rank-cell {{ display: table-cell; }}
  td.rank-cell .rank-icon, td.rank-cell .rank-icon-ph {{ margin-right: 7px; }}
  .standings {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }}
  .standing-chip {{
    display: flex; align-items: center; gap: 7px; background: var(--surface-2);
    border: 1px solid var(--border); border-left-width: 3px;
    border-radius: 999px; padding: 5px 13px 5px 6px; font-size: 12px;
    transition: transform .16s ease;
  }}
  .standing-chip:hover {{ transform: translateY(-2px); }}
  .standing-chip .name {{ font-weight: 700; }}
  .standing-chip .rank {{ color: var(--text-secondary); font-variant-numeric: tabular-nums; }}

  details.matches-details {{
    margin-top: 12px; border: 1px solid var(--border); border-radius: 11px;
    padding: 2px 14px; background: var(--surface-2);
    /* The match/champion tables are wider than a phone viewport — scroll
       them inside their own box so they never push the page sideways. */
    overflow-x: auto;
  }}
  details.matches-details[open] {{ padding-bottom: 12px; }}
  summary {{ cursor: pointer; font-size: 13px; font-weight: 600; color: var(--text-secondary); padding: 10px 0; }}
  summary:hover {{ color: var(--text-primary); }}
  .tag {{ font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 999px; }}
  .tag.win {{ background: color-mix(in srgb, var(--good) 16%, transparent); color: var(--good); }}
  .tag.loss {{ background: color-mix(in srgb, var(--critical) 16%, transparent); color: var(--critical); }}
  .matches-table th, .matches-table td {{ font-size: 12px; }}
  .matches-details table {{ margin-bottom: 4px; }}

  .legend {{ display: flex; gap: 14px; font-size: 12px; color: var(--text-secondary); margin-top: 10px; justify-content: center; flex-wrap: wrap; }}
  .legend span.sw {{ display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }}
  .legend-item {{
    cursor: pointer; user-select: none; transition: opacity .15s, background .15s;
    padding: 3px 9px; border-radius: 999px; background: var(--surface-2); font-weight: 600;
  }}
  .legend-item:hover {{ background: var(--gridline); }}
  footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 28px; line-height: 1.6; }}

  /* ---- Tabs ---------------------------------------------------------- */
  .tabs {{
    display: flex; gap: 4px; margin-bottom: 20px; overflow-x: auto;
    background: var(--surface-1); border: 1px solid var(--border);
    border-radius: 12px; padding: 5px; box-shadow: var(--shadow-sm);
    scrollbar-width: none;
  }}
  .tabs::-webkit-scrollbar {{ display: none; }}
  .tab-btn {{
    appearance: none; background: none; border: none; cursor: pointer;
    padding: 9px 17px; font-size: 13.5px; font-weight: 600; color: var(--muted);
    border-radius: 8px; white-space: nowrap; font-family: inherit;
    /* Deliberately not transitioning `color`: it resolves from a theme
       token, and Chromium leaves a transitioned colour stuck on the old
       value when the toggle swaps the token underneath it. */
    transition: background .16s ease;
  }}
  .tab-btn:hover {{ color: var(--text-primary); background: var(--surface-2); }}
  .tab-btn.active {{
    color: #fff; background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 62%, var(--accent-2)));
    box-shadow: 0 2px 10px var(--halo);
  }}

  .friend-pills {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }}
  .pill {{
    appearance: none; cursor: pointer; font-family: inherit; font-size: 13px; font-weight: 600;
    padding: 7px 15px; border-radius: 999px; border: 1px solid var(--border);
    background: var(--surface-1); color: var(--text-secondary);
    transition: transform .16s ease, background .16s ease, border-color .16s ease;
  }}
  .pill:hover {{ background: var(--surface-2); color: var(--text-primary); transform: translateY(-1px); }}
  .pill.active {{
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 62%, var(--accent-2)));
    border-color: transparent; color: #fff; box-shadow: 0 2px 10px var(--halo);
  }}

  /* ---- Hosted controls: refresh + API key ---------------------------- */
  #refresh-data[hidden], #set-key[hidden] {{ display: none; }}
  #refresh-data:disabled, #set-key:disabled {{ opacity: .55; cursor: not-allowed; }}
  .refresh-status {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 14px 18px; margin-bottom: 18px; box-shadow: var(--shadow-sm);
  }}
  .refresh-status[hidden] {{ display: none; }}
  .refresh-bar {{ height: 7px; border-radius: 999px; background: var(--gridline); overflow: hidden; }}
  .refresh-bar-fill {{
    height: 100%; width: 0%; border-radius: 999px;
    background: linear-gradient(90deg, var(--accent), var(--accent-2));
    transition: width .35s cubic-bezier(.4,0,.2,1);
  }}
  .refresh-text {{ font-size: 12.5px; color: var(--text-secondary); margin-top: 9px; }}
  .refresh-text.error {{ color: var(--critical); }}
  .refresh-text.done {{ color: var(--good); }}

  .modal-backdrop {{
    position: fixed; inset: 0; background: rgba(0,0,0,0.55); backdrop-filter: blur(3px);
    display: flex; align-items: center; justify-content: center; padding: 20px; z-index: 50;
  }}
  .modal-backdrop[hidden] {{ display: none; }}
  .modal {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 22px; width: 100%; max-width: 420px; box-shadow: var(--shadow-lg);
  }}
  .modal h3 {{ margin: 0 0 6px; font-size: 17px; }}
  .modal .field {{ display: block; margin-top: 14px; }}
  .modal .field span {{ display: block; font-size: 12px; color: var(--muted); margin-bottom: 5px; font-weight: 600; }}
  .modal input {{
    width: 100%; font-family: inherit; font-size: 13px; padding: 9px 11px;
    border-radius: 9px; border: 1px solid var(--border);
    background: var(--surface-2); color: var(--text-primary);
  }}
  .modal input:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  .modal-msg {{ font-size: 12px; margin-top: 12px; min-height: 16px; color: var(--critical); }}
  .modal-msg.ok {{ color: var(--good); }}
  .modal-actions {{ display: flex; justify-content: flex-end; gap: 9px; margin-top: 16px; }}
  .btn-primary, .btn-ghost {{
    font-family: inherit; font-size: 13px; font-weight: 600; padding: 9px 16px;
    border-radius: 9px; cursor: pointer; border: 1px solid var(--border);
  }}
  .btn-ghost {{ background: var(--surface-2); color: var(--text-secondary); }}
  .btn-ghost:hover {{ background: var(--gridline); }}
  .btn-primary {{
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 62%, var(--accent-2)));
    border-color: transparent; color: #fff;
  }}
  .btn-primary:disabled {{ opacity: .6; cursor: not-allowed; }}

  /* ---- Entrance animation -------------------------------------------- */
  @keyframes rise {{ from {{ opacity: 0; transform: translateY(9px); }} to {{ opacity: 1; transform: none; }} }}
  .tab-panel > .panel, .tab-panel > .card {{ animation: rise .32s ease both; }}
  .tab-panel > *:nth-child(2) {{ animation-delay: .05s; }}
  .tab-panel > *:nth-child(3) {{ animation-delay: .1s; }}

  /* ---- Chart variants -------------------------------------------------- */
  /* Two renders of the same chart: a wide one, and a phone-sized one whose
     labels stay legible instead of being scaled down to ~4px. */
  .chart-compact {{ display: none; }}
  .chip-net {{ display: none; }}

  /* ---- Responsive ----------------------------------------------------- */
  @media (max-width: 720px) {{
    .wrap {{ padding: 14px 12px 56px; }}
    header.top {{ margin-bottom: 16px; gap: 10px; }}
    header.top h1 {{ font-size: 19px; margin-bottom: 3px; }}
    .brand {{ gap: 10px; }}
    .brand-mark {{ width: 38px; height: 38px; border-radius: 11px; font-size: 18px; }}
    /* Meta chips collapse to one line of plain text — three pill rows pushed
       the actual content most of a screen down. */
    .meta-row {{ gap: 4px; }}
    .meta-chip {{ border: none; background: none; padding: 0; font-size: 11px; }}
    .meta-chip::after {{ content: "·"; margin-left: 4px; opacity: .5; }}
    .meta-chip:last-child::after {{ content: ""; }}

    .panel, .card {{ padding: 15px 13px; border-radius: 12px; }}
    h2 {{ font-size: 16px; }}

    /* Touch targets: 34px tabs and 21px legend chips were well under the
       ~44px a fingertip needs. */
    .tabs {{ padding: 4px; gap: 2px; }}
    .tab-btn {{ padding: 12px 14px; font-size: 13px; min-height: 44px; }}
    .legend {{ gap: 8px; }}
    .legend-item {{ padding: 9px 12px; min-height: 38px; display: inline-flex; align-items: center; }}
    .pill {{ padding: 10px 16px; min-height: 40px; }}
    #export-csv, #theme-toggle, #refresh-data, #set-key {{ height: 42px; }}
    #export-csv, #refresh-data, #set-key {{ padding: 0 12px; font-size: 12.5px; }}
    summary {{ padding: 13px 0; }}

    .chart-wide {{ display: none; }}
    .chart-compact {{ display: block; }}
    .chip-net {{ display: inline; }}
    .wide-screen-only {{ display: none; }}

    .rank-row {{ grid-template-columns: 1fr auto; gap: 6px 10px; }}
    .rank-row .wr-track {{ grid-column: 1 / -1; }}
    .rank-row .wr-text {{ grid-column: 1 / -1; text-align: left; }}
    .season-stats {{ grid-template-columns: repeat(2, 1fr); gap: 8px; }}
    .stat-value {{ font-size: 19px; }}
    .stat-tile {{ padding: 10px 11px; }}
    .awards {{ grid-template-columns: 1fr; }}
    table {{ font-size: 13px; }}
    td, th {{ padding: 8px 6px; }}
    .modal {{ padding: 18px; }}
    .refresh-status {{ padding: 12px 14px; }}
  }}

  /* Very narrow phones */
  @media (max-width: 380px) {{
    .season-stats {{ grid-template-columns: 1fr; }}
    header.top h1 {{ font-size: 17px; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    * {{ animation: none !important; transition: none !important; }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <header class="top">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">⚔️</div>
        <div>
          <h1>League Friends Dashboard</h1>
          <div class="meta-row">
            <span class="meta-chip">Platform <b>{esc(data.get("platform", "?"))}</b></span>
            <span class="meta-chip">Updated <b>{esc(data.get("generatedAt", ""))}</b></span>
            {f'<span class="meta-chip">Season since <b>{esc(data.get("seasonStart"))}</b></span>' if data.get("seasonStart") else ""}
          </div>
        </div>
      </div>
      <div class="header-actions">
        <!-- Hosted-only controls: revealed by JS once /api/status answers, so
             a locally generated dashboard doesn't show buttons that can't work. -->
        <button id="refresh-data" class="hosted-only" type="button" hidden title="Re-fetch everyone's games from the Riot API">⟳ Refresh data</button>
        <button id="set-key" class="hosted-only" type="button" hidden title="Update the Riot API key (dev keys expire every 24h)">🔑 API key</button>
        <button id="export-csv" type="button" title="Download this season's match data as a CSV">⬇ Export CSV</button>
        <button id="theme-toggle" type="button" aria-label="Toggle dark mode" title="Toggle dark mode">🌙</button>
      </div>
    </header>

    <div id="refresh-status" class="refresh-status" hidden>
      <div class="refresh-bar"><div class="refresh-bar-fill" id="refresh-bar-fill"></div></div>
      <div class="refresh-text" id="refresh-text">Starting…</div>
    </div>

    <div class="modal-backdrop" id="modal" hidden>
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <h3 id="modal-title">Admin</h3>
        <p class="muted small" id="modal-blurb"></p>
        <label class="field"><span>Admin password</span>
          <input type="password" id="modal-pass" autocomplete="current-password"></label>
        <label class="field" id="modal-key-field"><span>Riot API key</span>
          <input type="text" id="modal-key" placeholder="RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" autocomplete="off" spellcheck="false"></label>
        <div class="modal-msg" id="modal-msg"></div>
        <div class="modal-actions">
          <button type="button" class="btn-ghost" id="modal-cancel">Cancel</button>
          <button type="button" class="btn-primary" id="modal-ok">Confirm</button>
        </div>
      </div>
    </div>

    {demo_banner}

    <nav class="tabs">
      <button class="tab-btn active" type="button" data-tab="overview">Overview</button>
      <button class="tab-btn" type="button" data-tab="rank">Rank progress</button>
      {'<button class="tab-btn" type="button" data-tab="duo">Duo synergy</button>' if duo_synergy_panel else ""}
      <button class="tab-btn" type="button" data-tab="friends">Friends</button>
    </nav>

    <section class="tab-panel" data-tab-panel="overview">
      {awards_panel}
      {week_glance_panel}

      <div class="panel">
        <h2 style="margin-bottom:14px;">Ranked Solo/Duo leaderboard</h2>
        <div class="table-scroll">
          <table class="leaderboard">
            <thead><tr><th class="num">#</th><th>Friend</th><th>Rank</th><th class="num">Winrate</th><th class="num">Record</th><th class="num">7-day trend</th></tr></thead>
            <tbody>{leaderboard_rows}</tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="tab-panel" data-tab-panel="rank" style="display:none;">
      {rank_chart_panel}
    </section>

    {f'<section class="tab-panel" data-tab-panel="duo" style="display:none;">{duo_synergy_panel}</section>' if duo_synergy_panel else ""}

    <section class="tab-panel" data-tab-panel="friends" style="display:none;">
      <div class="friend-pills">{friend_pills}</div>
      {cards}
    </section>

    <footer>
      Data via the Riot Games API. Not endorsed by Riot Games. Remake games (early
      surrender with no stat impact) are automatically excluded from every stat here.
      <div class="legend">
        <span><span class="sw" style="background:var(--good)"></span>Win</span>
        <span><span class="sw" style="background:var(--critical)"></span>Loss</span>
      </div>
    </footer>
  </div>

  <script type="application/json" id="season-export-data">{season_export_json}</script>

  <script>
    (function () {{
      var root = document.documentElement;
      var btn = document.getElementById('theme-toggle');
      function isDarkNow() {{
        var explicit = root.getAttribute('data-theme');
        if (explicit === 'dark') return true;
        if (explicit === 'light') return false;
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      }}
      function sync() {{ btn.textContent = isDarkNow() ? '☀️' : '🌙'; }}
      btn.addEventListener('click', function () {{
        root.setAttribute('data-theme', isDarkNow() ? 'light' : 'dark');
        sync();
      }});
      sync();
    }})();
  </script>

  <script>
    (function () {{
      var btn = document.getElementById('export-csv');
      if (!btn) return;
      btn.addEventListener('click', function () {{
        var raw = document.getElementById('season-export-data');
        var rows = raw ? JSON.parse(raw.textContent) : [];
        var cols = ['friend', 'gameStart', 'champion', 'win', 'kills', 'deaths', 'assists',
                     'kda', 'csPerMin', 'damageDealt', 'queue', 'durationMin', 'position', 'opponentChampion'];
        var lines = [cols.join(',')];
        rows.forEach(function (row) {{
          lines.push(cols.map(function (c) {{
            var v = row[c];
            if (v === undefined || v === null) v = '';
            v = String(v).replace(/"/g, '""');
            if (/[",\\n]/.test(v)) v = '"' + v + '"';
            return v;
          }}).join(','));
        }});
        var blob = new Blob([lines.join('\\n')], {{ type: 'text/csv' }});
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'league_friends_season_data.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
      }});
    }})();
  </script>

  <script>
    (function () {{
      document.querySelectorAll('.legend-item[data-idx]').forEach(function (el) {{
        el.addEventListener('click', function () {{
          var idx = el.getAttribute('data-idx');
          // One legend drives both the wide and compact renders of the chart.
          var charts = (el.getAttribute('data-chart') || 'daily').split(' ');
          var first = document.getElementById(charts[0] + '-series-' + idx);
          var willHide = !(first && first.style.display === 'none');
          charts.forEach(function (c) {{
            var series = document.getElementById(c + '-series-' + idx);
            var label = document.getElementById(c + '-label-' + idx);
            if (series) series.style.display = willHide ? 'none' : '';
            if (label) label.style.display = willHide ? 'none' : '';
          }});
          el.style.opacity = willHide ? '0.35' : '1';
        }});
      }});
    }})();
  </script>

  <script>
    // Hosted controls. These only do anything when the dashboard is served by
    // the Vercel app (which provides /api/*); a locally generated file just
    // leaves the buttons hidden.
    (function () {{
      var refreshBtn = document.getElementById('refresh-data');
      var keyBtn = document.getElementById('set-key');
      var statusBox = document.getElementById('refresh-status');
      var barFill = document.getElementById('refresh-bar-fill');
      var statusText = document.getElementById('refresh-text');
      var modal = document.getElementById('modal');
      var modalTitle = document.getElementById('modal-title');
      var modalBlurb = document.getElementById('modal-blurb');
      var modalPass = document.getElementById('modal-pass');
      var modalKey = document.getElementById('modal-key');
      var modalKeyField = document.getElementById('modal-key-field');
      var modalMsg = document.getElementById('modal-msg');
      var modalOk = document.getElementById('modal-ok');
      var modalCancel = document.getElementById('modal-cancel');
      var state = null;

      function setStatus(msg, cls, pct) {{
        statusBox.hidden = false;
        statusText.textContent = msg;
        statusText.className = 'refresh-text' + (cls ? ' ' + cls : '');
        if (typeof pct === 'number') barFill.style.width = Math.max(0, Math.min(100, pct)) + '%';
      }}

      fetch('api/status').then(function (r) {{
        if (!r.ok) throw new Error('no api');
        return r.json();
      }}).then(function (s) {{
        state = s;
        refreshBtn.hidden = false;
        keyBtn.hidden = false;
        if (!s.hasKey) setStatus('No Riot API key stored yet — use the 🔑 API key button before refreshing.', 'error', 0);
        else if (s.keyAgeHours !== null && s.keyAgeHours >= 24)
          setStatus('The stored Riot API key is ' + Math.floor(s.keyAgeHours) + 'h old — dev keys expire after 24h, so it probably needs replacing.', 'error', 0);
      }}).catch(function () {{ /* not hosted — leave the buttons hidden */ }});

      var onConfirm = null;
      function openModal(opts) {{
        modalTitle.textContent = opts.title;
        modalBlurb.textContent = opts.blurb;
        modalKeyField.style.display = opts.needsKey ? '' : 'none';
        // Replacing an expired key needs no password; spending Riot quota does.
        modalPass.parentElement.style.display = opts.needsPass ? '' : 'none';
        modalMsg.textContent = '';
        modalMsg.className = 'modal-msg';
        modalPass.value = '';
        modalKey.value = '';
        modal.hidden = false;
        onConfirm = opts.onConfirm;
        setTimeout(function () {{ (opts.needsPass ? modalPass : modalKey).focus(); }}, 30);
      }}
      function closeModal() {{ modal.hidden = true; onConfirm = null; }}
      modalCancel.addEventListener('click', closeModal);
      modal.addEventListener('click', function (e) {{ if (e.target === modal) closeModal(); }});
      document.addEventListener('keydown', function (e) {{
        if (e.key === 'Escape' && !modal.hidden) closeModal();
        if (e.key === 'Enter' && !modal.hidden) modalOk.click();
      }});
      modalOk.addEventListener('click', function () {{ if (onConfirm) onConfirm(); }});

      function post(path, body) {{
        return fetch('api/' + path, {{
          method: 'POST',
          headers: {{ 'content-type': 'application/json' }},
          body: JSON.stringify(body || {{}})
        }}).then(function (r) {{
          return r.json().catch(function () {{ return {{ error: 'Bad response from server (HTTP ' + r.status + ')' }}; }})
            .then(function (j) {{ if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status)); return j; }});
        }});
      }}

      keyBtn.addEventListener('click', function () {{
        openModal({{
          title: 'Update Riot API key',
          blurb: 'Riot development keys expire every 24 hours. Grab a fresh one from developer.riotgames.com and paste it here.',
          needsKey: true, needsPass: false,
          onConfirm: function () {{
            var key = modalKey.value.trim();
            if (!/^RGAPI-/.test(key)) {{ modalMsg.textContent = 'That does not look like a Riot key (should start with RGAPI-).'; return; }}
            modalOk.disabled = true;
            modalMsg.className = 'modal-msg';
            modalMsg.textContent = 'Checking the key against Riot…';
            post('set_key', {{ key: key }}).then(function () {{
              modalMsg.className = 'modal-msg ok';
              modalMsg.textContent = 'Key accepted and stored.';
              setStatus('Riot API key updated. You can refresh now.', 'done', 0);
              setTimeout(closeModal, 900);
            }}).catch(function (e) {{
              modalMsg.className = 'modal-msg';
              modalMsg.textContent = e.message;
            }}).finally(function () {{ modalOk.disabled = false; }});
          }}
        }});
      }});

      refreshBtn.addEventListener('click', function () {{
        openModal({{
          title: 'Refresh everyone\\'s data',
          blurb: 'Re-fetches new ranked games for every friend from the Riot API, then rebuilds the dashboard. Takes a minute or two.',
          needsKey: false, needsPass: false,
          onConfirm: function () {{ closeModal(); runRefresh(); }}
        }});
      }});

      function runRefresh() {{
        refreshBtn.disabled = true;
        keyBtn.disabled = true;
        var names = (state && state.friends) || [];
        var total = names.length + 1; // +1 for the rebuild step
        var newGames = 0;
        setStatus('Starting refresh…', null, 2);

        // One friend per request: each Riot fetch is well within a serverless
        // timeout on its own, but all of them together would not be.
        function step(i) {{
          if (i >= names.length) {{
            setStatus('Rebuilding the dashboard…', null, (total - 0.5) / total * 100);
            return post('finalize', {{}}).then(function (res) {{
              setStatus('Done — refreshed ' + res.friends + ' friends, ' + newGames +
                        ' new game' + (newGames === 1 ? '' : 's') + '. Reloading…', 'done', 100);
              setTimeout(function () {{ location.reload(); }}, 1400);
            }});
          }}
          setStatus('Fetching ' + names[i] + '… (' + (i + 1) + ' of ' + names.length + ')', null, (i / total) * 100);
          return post('refresh', {{ index: i }}).then(function (res) {{
            newGames += (res && res.newMatches) || 0;
            return step(i + 1);
          }});
        }}

        step(0).catch(function (e) {{
          setStatus('Refresh failed: ' + e.message, 'error');
          refreshBtn.disabled = false;
          keyBtn.disabled = false;
        }});
      }}
    }})();
  </script>

  <script>
    (function () {{
      var tabBtns = document.querySelectorAll('.tab-btn');
      var tabPanels = document.querySelectorAll('.tab-panel');

      function showTab(name) {{
        tabBtns.forEach(function (b) {{ b.classList.toggle('active', b.getAttribute('data-tab') === name); }});
        tabPanels.forEach(function (p) {{ p.style.display = (p.getAttribute('data-tab-panel') === name) ? '' : 'none'; }});
      }}
      tabBtns.forEach(function (btn) {{
        btn.addEventListener('click', function () {{ showTab(btn.getAttribute('data-tab')); }});
      }});

      var pills = document.querySelectorAll('.pill[data-friend]');
      var friendCards = document.querySelectorAll('.card[id^="friend-"]');
      function showFriend(label) {{
        friendCards.forEach(function (c) {{ c.style.display = (c.id === 'friend-' + label) ? '' : 'none'; }});
        pills.forEach(function (p) {{ p.classList.toggle('active', p.getAttribute('data-friend') === label); }});
      }}
      pills.forEach(function (p) {{
        p.addEventListener('click', function () {{ showFriend(p.getAttribute('data-friend')); }});
      }});
      if (pills.length) showFriend(pills[0].getAttribute('data-friend'));

      // Leaderboard "Friend" links jump to the Friends tab and select that
      // friend's card, instead of just anchor-scrolling to a hidden panel.
      document.querySelectorAll('a[data-friend-link]').forEach(function (a) {{
        a.addEventListener('click', function (e) {{
          e.preventDefault();
          var label = a.getAttribute('data-friend-link');
          showTab('friends');
          showFriend(label);
        }});
      }});
    }})();
  </script>
</body>
</html>'''


def main():
    data_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data.json")
    out_path = Path(sys.argv[2] if len(sys.argv) > 2 else "dashboard.html")
    if not data_path.exists():
        print(f"Data file not found: {data_path}. Run fetch_data.py first (or use the bundled demo data.json).")
        sys.exit(1)
    data = json.loads(data_path.read_text(encoding="utf-8"))
    out_path.write_text(build_html(data), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
