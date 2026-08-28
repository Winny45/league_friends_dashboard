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
import urllib.parse
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


def net_change_label(first, last, window="30d"):
    """Net movement across the whole visible window, for the small label
    under each line's end point. Same tier+division at both ends -> a plain
    net LP number; otherwise a compact 'was -> now' since raw LP isn't
    comparable across a promotion/demotion.

    `window` only names the period in the text — callers measuring a
    different span must say so, or the label contradicts its own column
    header (the leaderboard's 7-day trend used to read "(30d)")."""
    first_score, last_score = tier_score(first), tier_score(last)
    direction = 1 if last_score > first_score else (-1 if last_score < first_score else 0)
    if _rank_snapshot_key(first) == _rank_snapshot_key(last):
        delta = (last.get("leaguePoints") or 0) - (first.get("leaguePoints") or 0)
        if delta == 0:
            return None
        return {"text": f"{'+' if delta >= 0 else ''}{delta} LP ({window})", "direction": direction}
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


def rank_label_text(ranked_entry):
    """rank_label() without the HTML entity, for contexts that are not HTML:
    the Open Graph raster card and meta attribute values (where escaping the
    entity again would print a literal "&middot;")."""
    return html.unescape(rank_label(ranked_entry))


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


# ---------------------------------------------------------------------------
# Third-party profile links
#
# Every League stats site keys profiles by Riot ID, but they disagree on how to
# name a region: op.gg and League of Graphs take a short slug ("euw"), u.gg
# takes the platform id itself ("euw1"). A platform that is not in the table
# gets no links at all rather than a guessed slug that would 404.
# ---------------------------------------------------------------------------

SHORT_REGION = {
    "euw1": "euw", "eun1": "eune", "na1": "na", "kr": "kr", "jp1": "jp",
    "br1": "br", "la1": "lan", "la2": "las", "oc1": "oce", "ru": "ru",
    "tr1": "tr", "ph2": "ph", "sg2": "sg", "th2": "th", "tw2": "tw",
    "vn2": "vn", "me1": "me",
}

EXTERNAL_SITES = (
    ("op.gg", "https://www.op.gg/summoners/{short}/{name}-{tag}"),
    ("u.gg", "https://u.gg/lol/profile/{platform}/{name}-{tag}/overview"),
    ("League of Graphs", "https://www.leagueofgraphs.com/summoner/{short}/{name}-{tag}"),
)

_PLATFORM = {"id": "euw1"}


def set_platform(platform):
    """Set once per render, so the render_* helpers can build region-specific
    URLs without threading the platform through every signature."""
    _PLATFORM["id"] = (platform or "euw1").lower()


def external_profile_links(riot_id):
    """[(site name, url)] for one "Name#TAG" Riot ID, or [] if it cannot be
    built — an ID with no tag, or a region none of the sites are mapped for."""
    if not riot_id or "#" not in riot_id:
        return []
    name, tag = riot_id.split("#", 1)
    if not name or not tag:
        return []
    short = SHORT_REGION.get(_PLATFORM["id"])
    if not short:
        return []
    parts = {
        "short": short,
        "platform": _PLATFORM["id"],
        # safe="" so a space becomes %20 rather than being left raw, and a
        # name containing / or ? cannot break out of the path.
        "name": urllib.parse.quote(name, safe=""),
        "tag": urllib.parse.quote(tag, safe=""),
    }
    return [(label, tpl.format(**parts)) for label, tpl in EXTERNAL_SITES]


def render_profile_links(riot_id):
    links = external_profile_links(riot_id)
    if not links:
        return ""
    chips = "".join(
        f'<a class="ext-link" href="{esc(url)}" target="_blank" rel="noopener noreferrer" '
        f'title="Open this player on {esc(label)}">{esc(label)}'
        f'<span class="ext" aria-hidden="true">\u2197</span></a>'
        for label, url in links
    )
    return f'<div class="ext-links">{chips}</div>'


def champion_splash_url(champion_name):
    """Data Dragon splash art for a champion, used as the wash behind a
    friend's card. Unlike the square icons this path carries no patch
    version, so it needs nothing but the slug."""
    slug = _ICON_CTX["map"].get(champion_name or "")
    if not slug:
        return None
    return f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{slug}_0.jpg"


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
# Queues the live refresh asks Riot for. Riot filters by queue server-side,
# so a normal game never costs a call. Names must match the strings
# fetch_data.py stores, or a live row would read differently from a built one.
LIVE_RANKED_QUEUES = [420, 440]
LIVE_QUEUE_NAMES = {"420": "Ranked Solo/Duo", "440": "Ranked Flex"}

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
    together. Detected purely from overlap across friends' own season match
    lists — no extra API calls needed.

    Teammates are identified by matchId plus a matching result, not by
    teamId. League has no draws and a match has exactly two teams, so two
    players in the same game share a team if and only if they share an
    outcome — the two tests are equivalent. teamId is only present on records
    summarised after it was added to fetch_data.py, which is about 9% of the
    cache, and requiring it silently hid most of this panel: Brett and Winny
    showed 6 games together out of 130, and ten pairs did not appear at all.
    Checked against every record that does carry teamId: 48 of 48 agree."""
    by_match = {}
    for f in friends:
        for m in f.get("seasonMatches", []):
            if m.get("remake"):
                continue
            by_match.setdefault(m["matchId"], []).append((f, m))

    pair_stats = {}
    for entries in by_match.values():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                fa, ma = entries[i]
                fb, mb = entries[j]
                if ma["win"] != mb["win"]:
                    continue  # same lobby, opposite teams — not a duo
                key = tuple(sorted([fa["label"], fb["label"]]))
                stats = pair_stats.setdefault(key, {"wins": 0, "games": 0, "solo": 0, "flex": 0})
                stats["games"] += 1
                if ma["win"]:
                    stats["wins"] += 1
                if ma.get("queue") == "Ranked Solo/Duo":
                    stats["solo"] += 1
                else:
                    stats["flex"] += 1

    # Each player's own ranked winrate this season, so a pair's number can be
    # read against something. "66.7% together" means nothing until you know
    # whether these two usually win 45% or 60% of their games.
    solo_rate = {}
    order = {}
    for i, f in enumerate(friends):
        order[f["label"]] = i
        played = [m for m in f.get("seasonMatches", []) if not m.get("remake")]
        if played:
            solo_rate[f["label"]] = 100 * sum(1 for m in played if m["win"]) / len(played)

    rows = []
    for (a, b), s in pair_stats.items():
        if s["games"] < 2:
            continue
        winrate = round(100 * s["wins"] / s["games"], 1)
        base = [solo_rate[x] for x in (a, b) if x in solo_rate]
        baseline = sum(base) / len(base) if base else None
        rows.append({
            "a": a, "b": b, "games": s["games"], "wins": s["wins"],
            "losses": s["games"] - s["wins"],
            "winrate": winrate,
            "solo": s["solo"], "flex": s["flex"],
            "baseline": round(baseline, 1) if baseline is not None else None,
            "lift": round(winrate - baseline, 1) if baseline is not None else None,
            "aVar": friend_var(min(order.get(a, 0), len(FRIEND_PALETTE) - 1)),
            "bVar": friend_var(min(order.get(b, 0), len(FRIEND_PALETTE) - 1)),
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
    return net_change_label(window[0], window[-1], window="7d")


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
            net = net_change_label(window[0], window[-1], window="7d")
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

    # A friend's most-played champion, washed out behind the top of their
    # card. Purely decorative, and the whole element removes itself if the
    # image 404s, so a renamed or brand-new champion just means a plain card.
    # Cards other than the visible one are display:none, so the browser never
    # fetches six splashes nobody is looking at.
    signature = (f.get("mastery") or [{}])[0].get("championName")
    splash = champion_splash_url(signature)
    card_art = (
        f'<div class="card-art" aria-hidden="true"><img src="{esc(splash)}" alt="" '
        f'loading="lazy" decoding="async" onerror="this.parentElement.remove()"></div>'
    ) if splash else ""

    return f'''
    <section class="card" id="friend-{f["label"].lower()}" role="tabpanel"
             aria-labelledby="pill-{f["label"].lower()}" tabindex="-1"
             style="--card-tier: var({solo_var});">
      {card_art}
      <header class="card-head">
        <div class="rank-badge">#{rank_position}</div>
        <div>
          <h2>{esc(f["label"])}</h2>
          <div class="muted small">{esc(f["riotId"])} &middot; Level {esc(f.get("summonerLevel", "?"))}</div>
          {render_profile_links(f.get("riotId", ""))}
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

      <div class="section-label" data-form-label>Form (last {len(matches)} games, {wins}W {losses}L)</div>
      <div class="dots" data-dots>{dots}</div>
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
        <summary data-match-summary>Recent match detail ({len(matches)} games)</summary>
        <table class="matches-table">
          <thead><tr><th>When</th><th>Result</th><th>Champion</th><th>K/D/A</th><th>KDA</th><th>CS/min</th><th>Queue</th><th>Length</th></tr></thead>
          <tbody data-match-rows>{match_rows}</tbody>
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
    # data-* hooks let the client-side "live ranks" refresh rewrite these
    # cells in place without re-rendering the page.
    return f'''<tr data-friend-row="{esc(f["label"])}">
      <td class="num"><span class="{pos_cls}">{i}</span></td>
      <td><a href="#friends/{f["label"].lower()}" data-friend-link="{f["label"].lower()}">{esc(f["label"])}</a></td>
      <td class="rank-cell" data-cell="rank" style="color:var({var});font-weight:600;">{render_rank_icon((solo or {}).get("tier"))}{rank_label(solo)}</td>
      <td class="num" data-cell="winrate">{esc(wr) + '%' if wr is not None else '—'}</td>
      <td class="num muted" data-cell="record">{esc((solo or {}).get('wins', 0))}W / {esc((solo or {}).get('losses', 0))}L</td>
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


def end_label_groups(label_entries, prefix, gutter_x=None):
    """Name labels for each line, stacked in a reserved right-hand gutter.

    Anchoring a label to its own line's end point looks tidy only when every
    line ends at the same x. Here they don't — someone with 12 games ends a
    third of the way across — so labels landed in the middle of the plot,
    on top of the lines and each other. Placing them all at a common
    `gutter_x` means the vertical declutter below is sufficient on its own,
    and a leader line keeps each label tied to the point it describes.

    Passing gutter_x=None keeps the old line-end anchoring, which is right
    when every series really does end together.
    """
    label_groups = []
    MIN_LABEL_GAP = 26   # two lines of text (name + net change) plus breathing room
    ICON_SIZE = 14
    label_entries.sort(key=lambda e: e["ly"])
    for idx, e in enumerate(label_entries):
        e["draw_y"] = e["ly"] if idx == 0 else max(e["ly"], label_entries[idx - 1]["draw_y"] + MIN_LABEL_GAP)
    for e in label_entries:
        var, lx, ly, draw_y = e["var"], e["lx"], e["ly"], e["draw_y"]
        anchor_x = gutter_x if gutter_x is not None else lx
        parts = []
        # Leader from the real end point across to the gutter. Drawn whenever
        # the label isn't sitting essentially on top of its point.
        if abs(draw_y - ly) > 3 or (gutter_x is not None and anchor_x - lx > 10):
            parts.append(
                f'<path d="M{lx + 4:.1f},{ly:.1f} L{anchor_x - 4:.1f},{draw_y:.1f}" fill="none" '
                f'stroke="var({var})" stroke-width="1" stroke-dasharray="2,3" opacity="0.45" />'
            )
        icon_url = rank_icon_url(e.get("tier"))
        text_x = anchor_x
        if icon_url:
            parts.append(
                f'<image href="{esc(icon_url)}" x="{anchor_x:.1f}" y="{draw_y - ICON_SIZE / 2:.1f}" '
                f'width="{ICON_SIZE}" height="{ICON_SIZE}" onerror="this.style.visibility=\'hidden\'" />'
            )
            text_x = anchor_x + ICON_SIZE + 3
        parts.append(
            f'<text x="{text_x:.1f}" y="{draw_y + 3:.1f}" font-size="11" font-weight="700" fill="var({var})">{esc(e["label"])}</text>'
        )
        if e["net"]:
            net_color = "var(--good)" if e["net"]["direction"] > 0 else ("var(--critical)" if e["net"]["direction"] < 0 else "var(--muted)")
            parts.append(
                f'<text x="{text_x:.1f}" y="{draw_y + 15:.1f}" font-size="10" fill="{net_color}">{esc(e["net"]["text"])}</text>'
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

    def build_svg(compact, tail=None):
        """One render of the chart.

        `tail` limits each friend to their most recent N games, re-indexed
        from zero — a zoom on the busy right-hand end. It's per friend rather
        than a shared cut of the x-axis because the axis is already each
        person's own game count: slicing by absolute index would simply drop
        anyone who has played fewer games than the cut.
        """
        prefix = ("lpm" if compact else "lp") + ("t" if tail else "")
        view = {}
        for f in chart_friends:
            tl = timelines[f["label"]]
            pts = tl[-(tail + 1):] if tail and len(tl) > tail + 1 else tl
            base = pts[0]["idx"]
            start_i = len(tl) - len(pts)
            # idx drives the x position and is rebased to 0; origIdx keeps the
            # real game number so a tooltip in the zoomed view doesn't call
            # someone's 30th game their 1st. prevScore carries the score of the
            # game before this one *in the full timeline*: the zoomed view's
            # first point has a real predecessor outside the slice, and reading
            # it as tl[n - 1] with n = 0 quietly indexed the last point instead,
            # so that tooltip's LP step was measured against the wrong game.
            view[f["label"]] = [
                dict(p, idx=p["idx"] - base, origIdx=p["idx"],
                     prevScore=(tl[start_i + n - 1]["score"] if start_i + n - 1 >= 0 else p["score"]))
                for n, p in enumerate(pts)
            ]
        max_games = max((len(v) - 1 for v in view.values()), default=0) or 1
        vis_scores = [p["score"] for v in view.values() for p in v]
        y_min, y_max = min(vis_scores), max(vis_scores)
        pad = max(40, (y_max - y_min) * 0.16)
        y_min, y_max = y_min - pad, y_max + pad
        if y_max <= y_min:
            y_max = y_min + 200
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
        # In the zoomed view every friend is rebased to 0, so the axis counts
        # games back from the latest rather than pretending to be an absolute
        # game number that would differ per person.
        def tick_label(gi):
            if tail:
                back = max_games - gi
                return "Latest" if back == 0 else (f"−{back}" if compact else f"{back} ago")
            return "Start" if gi == 0 else (str(gi) if compact else f"Game {gi}")
        x_ticks = [(xy(gi, y_min)[0], tick_label(gi)) for gi in tick_idxs]

        series_groups, label_entries = [], []
        for i, f in enumerate(chart_friends):
            var = friend_var(i)
            tl = view[f["label"]]
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
                    move = lp_step_label(p["prevScore"], p["score"], p["delta"], p["exact"])
                    title = (f"{f['label']} — game {p.get('origIdx', p['idx'])} — {'Win' if m['win'] else 'Loss'} on {m['champion']} — "
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
                if tail and len(tl) > 1:
                    # Ladder LP is linear (100 per division), so a delta across
                    # the visible slice is a true LP count even over a promotion.
                    d = tl[-1]["score"] - tl[0]["score"]
                    net = {"text": f"{'+' if d >= 0 else '−'}{abs(d):.0f} LP · last {len(tl) - 1}",
                           "direction": 1 if d > 0 else (-1 if d < 0 else 0)}
                else:
                    net = net_labels[i]
                label_entries.append({"idx": i, "var": var, "label": f["label"], "lx": lx, "ly": ly,
                                      "net": net, "tier": tiers[i]})

        # Labels sit in the reserved right gutter, not at each line's own end:
        # lines finish at different x (someone with 12 games ends a third of
        # the way across), which put labels on top of the plot and each other.
        label_groups = [] if compact else end_label_groups(
            label_entries, prefix, gutter_x=W - PAD_R + 10)

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
            move_text = f"{'+' if lp >= 0 else '−'}{abs(lp)} LP"
        else:
            move_text = (f'{rank_label(first_h).split(" &middot;")[0]} → '
                         f'{rank_label(last_h).split(" &middot;")[0]}')
        direction = 1 if net_lp > 0 else (-1 if net_lp < 0 else 0)
        # The chart label carries only the movement — appending the W/L record
        # pushed "Emerald II → Emerald III · 24W 31L" past the right edge and
        # it rendered clipped. The record lives in the standings chip instead,
        # where there's room for it.
        net_labels.append({"text": move_text, "direction": direction})
        tiers.append(hist[-1].get("tier"))
        standings.append({"var": friend_var(i), "label": f["label"], "tier": hist[-1].get("tier"),
                          "rankLabel": rank_label(hist[-1]), "games": games,
                          "net": f"{move_text} · {record}"})
        legend_items.append(
            # Names every render this legend drives: wide/compact for both the
            # full and zoomed views. Absent ids are skipped harmlessly, so this
            # stays correct whether or not the zoom variant was built.
            f'<span class="legend-item" data-chart="lp lpm lpt lpmt" data-idx="{i}">'
            f'<span class="sw" style="background:var({friend_var(i)})"></span>{esc(f["label"])}</span>'
        )

    # Two zoom levels, both rendered up front and toggled with CSS — no
    # client-side re-plotting, so the zoom can't get out of step with the
    # data or break if scripting fails.
    TAIL_GAMES = 20
    longest = max((len(timelines[f["label"]]) - 1 for f in chart_friends), default=0)
    show_zoom = longest > TAIL_GAMES + 4   # not worth offering when everyone is short
    charts_svg = (
        f'<div class="chart-view" data-range="all">{build_svg(False)}{build_svg(True)}</div>'
    )
    zoom_toggle = ""
    if show_zoom:
        charts_svg += (
            f'<div class="chart-view" data-range="tail" hidden>'
            f'{build_svg(False, tail=TAIL_GAMES)}{build_svg(True, tail=TAIL_GAMES)}</div>'
        )
        zoom_toggle = (
            '<div class="range-toggle" role="group" aria-label="Chart range">'
            '<button type="button" class="range-btn active" data-range="all">All games</button>'
            f'<button type="button" class="range-btn" data-range="tail">Last {TAIL_GAMES}</button>'
            '</div>'
        )

    omitted_note = ""
    if omitted:
        omitted_note = (f'<div class="muted small" style="margin-top:8px;">Not shown: {esc(", ".join(omitted))} '
                        f'(chart shows up to {len(FRIEND_PALETTE)} friends at once).</div>')

    # Everything the browser needs to rebuild this chart with games played
    # since the publish. Only the solo queue and only the charted friends,
    # since that is all the chart draws.
    lp_chart_json = json.dumps({
        "tierOrder": TIER_ORDER,
        "rankScore": RANK_SCORE,
        "apexTiers": sorted(APEX_TIERS),
        "lpPerDivision": LP_PER_DIVISION,
        "divisionsPerTier": DIVISIONS_PER_TIER,
        "nominalLp": NOMINAL_LP,
        "tailGames": TAIL_GAMES,
        "rankIconBase": RANK_ICON_BASE,
        "friends": [
            {
                "label": f["label"],
                "history": [
                    {"date": h["date"], "tier": h.get("tier"), "rank": h.get("rank"),
                     "leaguePoints": h.get("leaguePoints")}
                    for h in solo_history_by_label[f["label"]]
                ],
                "matches": [
                    {"dateKey": m.get("dateKey"), "gameStartMs": m.get("gameStartMs"),
                     "win": bool(m.get("win")), "champion": m.get("champion")}
                    for m in f.get("seasonMatches", []) if m.get("queue") == "Ranked Solo/Duo"
                ],
            }
            for f in chart_friends
        ],
    }, ensure_ascii=False)

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
      <div class="standings" data-lp-standings>{standings_html}</div>
      {zoom_toggle}
      <div data-lp-charts>{charts_svg}</div>
      <script type="application/json" id="lp-chart-data">{lp_chart_json}</script>
      <div class="legend" style="justify-content:flex-start;">{"".join(legend_items)}</div>
      <div class="muted small" style="margin-top:2px;">Hover or tap a name to highlight that line; click to hide it. Tap any point for the game behind it.</div>
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

    # Everyone who appears in at least one pair, in leaderboard order, for the
    # filter row. Someone with no duos would be a chip that always shows
    # nothing, so they are left out.
    seen = []
    for f in friends:
        if any(f["label"] in (r["a"], r["b"]) for r in rows):
            seen.append(f["label"])
    filter_chips = "".join(
        f'<button type="button" class="duo-chip" data-who="{esc(x)}">{esc(x)}</button>'
        for x in seen
    )

    def lift_html(r):
        if r["lift"] is None:
            return ""
        cls = "up" if r["lift"] > 0 else ("down" if r["lift"] < 0 else "flat")
        sign = "+" if r["lift"] > 0 else ("\u2212" if r["lift"] < 0 else "\u00b1")
        return (f'<div class="duo-lift {cls}">{sign}{abs(r["lift"]):.1f} pts '
                f'<span class="muted">vs their usual {r["baseline"]:.0f}%</span></div>')

    cards = "".join(
        f'<article class="duo-card" data-a="{esc(r["a"])}" data-b="{esc(r["b"])}" '
        f'data-games="{r["games"]}" data-winrate="{r["winrate"]}" '
        f'data-lift="{r["lift"] if r["lift"] is not None else -999}">'
        f'<div class="duo-names">'
        f'<span style="color:var({r["aVar"]});">{esc(r["a"])}</span>'
        f'<span class="duo-amp">&amp;</span>'
        f'<span style="color:var({r["bVar"]});">{esc(r["b"])}</span>'
        f'</div>'
        f'<div class="duo-figure"><span class="duo-wr">{r["winrate"]}%</span>'
        f'<span class="duo-record">{r["wins"]}W {r["losses"]}L</span></div>'
        f'<div class="duo-track"><div class="duo-fill{" good" if r["winrate"] >= 50 else " bad"}" '
        f'style="width:{max(2, min(100, r["winrate"]))}%;"></div></div>'
        f'{lift_html(r)}'
        f'<div class="duo-games">{r["games"]} games together'
        f'{f" &middot; {r["flex"]} flex" if r["flex"] else ""}'
        f'{" <span class='duo-thin'>&middot; small sample</span>" if r["games"] < 5 else ""}</div>'
        f'</article>'
        for r in rows
    )

    body = "".join(
        f'<tr><td>{esc(r["a"])} &amp; {esc(r["b"])}</td><td class="num">{r["games"]}</td>'
        f'<td class="num">{r["wins"]}W {r["losses"]}L</td><td class="num">{r["winrate"]}%</td></tr>'
        for r in rows
    )

    return f'''
    <div class="panel">
      <h2 style="margin-bottom:4px;">Duo synergy</h2>
      <p class="panel-hint" style="margin:6px 0 14px;">Winrate when two friends were on the same team
      in a ranked game this season, and how that compares with how often each of them wins
      otherwise. Two games is a small sample &mdash; the games count is there for a reason.</p>
      <div class="duo-controls">
        <div class="duo-filters" role="group" aria-label="Filter by player">
          <button type="button" class="duo-chip active" data-who="">Everyone</button>{filter_chips}
        </div>
        <div class="range-toggle" role="group" aria-label="Sort pairs">
          <button type="button" class="range-btn active" data-sort="games">Most played</button>
          <button type="button" class="range-btn" data-sort="winrate">Best winrate</button>
          <button type="button" class="range-btn" data-sort="lift">Biggest lift</button>
        </div>
      </div>
      <div class="duo-grid">{cards}</div>
      <div class="duo-empty" hidden>No pairs for that player.</div>
      <details class="matches-details" style="margin-top:12px;">
        <summary>View as table</summary>
        <table class="matches-table">
          <thead><tr><th>Pair</th><th class="num">Games together</th><th class="num">Record</th><th class="num">Winrate</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </details>
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


# ---------------------------------------------------------------------------
# Brand assets
#
# The page had no favicon, no theme colour and no Open Graph tags, which for a
# link whose entire job is to be pasted into a group chat meant a generic globe
# in the tab and a bare unfurled URL in Discord. The mark is a double chevron
# (climbing the ladder) on the same accent gradient the UI already uses.
# ---------------------------------------------------------------------------

BRAND_ACCENT = ("#4c8dff", "#17d3c1")

# Inline so it needs no network request and no extra file next to the HTML.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    f'<stop offset="0" stop-color="{BRAND_ACCENT[0]}"/>'
    f'<stop offset="1" stop-color="{BRAND_ACCENT[1]}"/>'
    '</linearGradient></defs>'
    '<rect width="64" height="64" rx="15" fill="url(#g)"/>'
    '<path d="M18 43.5 32 29.5 46 43.5" fill="none" stroke="#fff" stroke-width="6.5" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M18 30.5 32 16.5 46 30.5" fill="none" stroke="#fff" stroke-width="6.5" '
    'stroke-linecap="round" stroke-linejoin="round" opacity=".5"/>'
    '</svg>'
)

# The same mark for the header, minus its own background — the .brand-mark
# element already paints the gradient tile behind it.
BRAND_MARK_SVG = (
    '<svg viewBox="0 0 64 64" width="26" height="26" aria-hidden="true" focusable="false">'
    '<path d="M18 43.5 32 29.5 46 43.5" fill="none" stroke="#fff" stroke-width="7" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M18 30.5 32 16.5 46 30.5" fill="none" stroke="#fff" stroke-width="7" '
    'stroke-linecap="round" stroke-linejoin="round" opacity=".5"/>'
    '</svg>'
)


def favicon_data_uri():
    return "data:image/svg+xml," + urllib.parse.quote(FAVICON_SVG, safe="")


def _og_font(size, bold=True):
    """A real typeface for the share card, falling back through the usual
    per-platform paths and finally to Pillow's built-in."""
    from PIL import ImageFont
    names = (["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"] if bold
             else ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "Arial.ttf"])
    roots = ["C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/",
             "/System/Library/Fonts/Supplemental/", ""]
    for root in roots:
        for name in names:
            try:
                return ImageFont.truetype(root + name, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size)
    except Exception:
        return ImageFont.load_default()


def _rounded_gradient(size, radius, colors):
    """A rounded tile filled with a diagonal two-stop gradient."""
    from PIL import Image, ImageDraw
    w, h = size
    c0 = tuple(int(colors[0][i:i + 2], 16) for i in (1, 3, 5))
    c1 = tuple(int(colors[1][i:i + 2], 16) for i in (1, 3, 5))
    grad = Image.new("RGB", (w, h))
    px = grad.load()
    for y in range(h):
        for x in range(w):
            t = (x / max(w - 1, 1) + y / max(h - 1, 1)) / 2
            px[x, y] = tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    grad.putalpha(mask)
    return grad


def _og_glow(size, spots):
    """Soft colour blooms behind the card, matching the page background."""
    from PIL import Image, ImageDraw, ImageFilter
    layer = Image.new("RGB", size, (0, 0, 0))
    d = ImageDraw.Draw(layer)
    for (cx, cy, r, colour) in spots:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)
    return layer.filter(ImageFilter.GaussianBlur(radius=160))


def write_share_assets(out_dir, friends_sorted, platform, generated_at):
    """Write og.png (1200x630 Open Graph card) and icon-180.png next to the
    HTML. Returns the names actually written.

    Everything here is best-effort: Pillow is only needed to publish a link
    preview, so a machine without it still renders a perfectly good dashboard.
    """
    try:
        from PIL import Image, ImageDraw, ImageChops
    except Exception:
        return []

    written = []
    try:
        W, H = 1200, 630
        card = Image.new("RGB", (W, H), (11, 13, 18))
        glow = _og_glow((W, H), [
            (110, 0, 250, (30, 58, 122)),
            (1160, 30, 210, (8, 58, 60)),
        ])
        card = ImageChops.add(card, glow)
        d = ImageDraw.Draw(card)

        # Brand tile + chevrons, drawn at 4x and downsampled so the strokes
        # come out smooth without any antialiasing work of our own.
        S = 4
        tile = _rounded_gradient((96 * S, 96 * S), 26 * S, BRAND_ACCENT)
        td = ImageDraw.Draw(tile)
        for pts, width, alpha in (
                ([(27, 65), (48, 44), (69, 65)], 10, 255),
                ([(27, 46), (48, 25), (69, 46)], 10, 130)):
            td.line([(x * S, y * S) for x, y in pts], fill=(255, 255, 255, alpha),
                    width=width * S, joint="curve")
            for (x, y) in (pts[0], pts[-1]):
                r = width * S / 2
                td.ellipse([x * S - r, y * S - r, x * S + r, y * S + r],
                           fill=(255, 255, 255, alpha))
        tile = tile.resize((96, 96), Image.LANCZOS)
        card.paste(tile, (80, 74), tile)

        # The right third is otherwise dead space; an oversized, nearly
        # invisible copy of the mark balances the composition.
        wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        wd = ImageDraw.Draw(wm)
        for pts in ([(880, 500), (1040, 340), (1200, 500)],
                    [(880, 360), (1040, 200), (1200, 360)]):
            wd.line(pts, fill=(255, 255, 255, 12), width=54, joint="curve")
        card = Image.alpha_composite(card.convert("RGBA"), wm).convert("RGB")
        d = ImageDraw.Draw(card)

        d.text((196, 88), "League Friends", font=_og_font(46), fill=(241, 243, 247))
        d.text((196, 138), "Dashboard", font=_og_font(46), fill=(241, 243, 247))

        d.line([(80, 224), (1120, 224)], fill=(38, 43, 53), width=2)
        d.text((80, 244), "LIVE STANDINGS", font=_og_font(17), fill=(110, 120, 138))

        # Live standings, so a shared link previews the current ladder rather
        # than a static poster.
        y = 280
        medal = [(230, 193, 92), (167, 177, 193), (204, 138, 91)]
        for i, f in enumerate(friends_sorted[:5]):
            solo = f["ranked"].get("solo")
            tier = (solo or {}).get("tier")
            colour = TIER_COLOR.get(tier, DEFAULT_TIER_COLOR)["dark"] if tier else \
                DEFAULT_TIER_COLOR["dark"]
            rgb = tuple(int(colour[j:j + 2], 16) for j in (1, 3, 5))
            d.rounded_rectangle([80, y, 118, y + 38], radius=11,
                                fill=(medal[i] if i < 3 else (44, 49, 60)))
            num = str(i + 1)
            nf = _og_font(20)
            nb = d.textbbox((0, 0), num, font=nf)
            d.text((99 - (nb[2] - nb[0]) / 2, y + 19 - (nb[3] - nb[1]) / 2 - nb[1]), num,
                   font=nf, fill=(16, 18, 24) if i < 3 else (180, 187, 201))
            d.text((136, y + 4), f["label"], font=_og_font(27), fill=(241, 243, 247))
            d.text((410, y + 7), rank_label_text(solo), font=_og_font(24, bold=False), fill=rgb)
            y += 50

        foot = f"{len(friends_sorted)} players  ·  {platform.upper()}  ·  updated {generated_at}"
        d.text((80, H - 78), foot, font=_og_font(22, bold=False), fill=(124, 134, 152))

        og = Path(out_dir) / "og.png"
        card.save(og, "PNG", optimize=True)
        written.append(og.name)

        icon = _rounded_gradient((180 * 2, 180 * 2), 40 * 2, BRAND_ACCENT)
        idr = ImageDraw.Draw(icon)
        for pts, alpha in (([(50, 122), (90, 83), (130, 122)], 255),
                           ([(50, 86), (90, 47), (130, 86)], 130)):
            idr.line([(x * 2, y * 2) for x, y in pts], fill=(255, 255, 255, alpha),
                     width=19 * 2, joint="curve")
            for (x, y) in (pts[0], pts[-1]):
                idr.ellipse([x * 2 - 19, y * 2 - 19, x * 2 + 19, y * 2 + 19],
                            fill=(255, 255, 255, alpha))
        icon = icon.resize((180, 180), Image.LANCZOS).convert("RGB")
        ip = Path(out_dir) / "icon-180.png"
        icon.save(ip, "PNG", optimize=True)
        written.append(ip.name)
    except Exception as e:
        print(f"  (skipped share images: {e})")
    return written


# ---------------------------------------------------------------------------
# Patch notes
#
# Content lives in patch_notes.json rather than in here, so adding an entry is
# a small data edit and cannot break the generator. Newest entry first; the
# file is optional, and without it the button simply is not rendered.
# ---------------------------------------------------------------------------

NOTE_KINDS = {
    "added": ("New", "note-new"),
    "fixed": ("Fixed", "note-fix"),
    "improved": ("Better", "note-better"),
}


def load_patch_notes():
    path = Path(__file__).with_name("patch_notes.json")
    if not path.exists():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  (skipped patch notes: {exc})")
        return []
    return entries if isinstance(entries, list) else []


def format_note_date(value):
    """2026-08-28 -> 28 Aug 2026, leaving anything unparseable alone."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")
    except Exception:
        return value


def render_patch_notes(entries):
    """(html, latest date). The date doubles as the "have you read this"
    marker the unread dot compares against."""
    if not entries:
        return "", ""
    blocks = []
    for entry in entries:
        lis = []
        for item in entry.get("items", []):
            word, cls = NOTE_KINDS.get(item.get("type", "added"), NOTE_KINDS["added"])
            lis.append(f'<li><span class="note-tag {cls}">{esc(word)}</span>'
                       f'<span>{esc(item.get("text", ""))}</span></li>')
        blocks.append(
            f'<article class="note">'
            f'<div class="note-date">{esc(format_note_date(entry.get("date", "")))}</div>'
            f'<h4>{esc(entry.get("title", ""))}</h4>'
            f'<ul>{"".join(lis)}</ul>'
            f'</article>')
    return "".join(blocks), str(entries[0].get("date", ""))


# The LP chart renderer, ported to JavaScript. Held as a plain (non-f)
# string so its braces need no doubling when it lands in the page's
# f-string — 400 lines of doubled braces is how escaping bugs happen.
LP_CHART_JS = r'''
// ---------------------------------------------------------------------------
// LP chart, rendered in the browser.
//
// A port of render_lp_chart() and the ladder maths it depends on. It exists so
// a refresh can redraw the chart with games played since the last publish: the
// chart's x-scale, y-range, gridlines and label layout all derive from the
// whole season, so unlike the match lists it cannot be patched in place.
//
// This is a second copy of maths that also lives in generate_dashboard.py.
// The guard against the two drifting apart is that rendering the *unmodified*
// data must reproduce the server's SVG exactly; verifySelf() checks that and
// is what the build test calls.
// ---------------------------------------------------------------------------
window.LpChart = (function () {
  'use strict';

  var D = null;

  function esc(s) {
    // Matches Python's html.escape(quote=True), including &#x27; for an
    // apostrophe, so the two renderers produce identical bytes.
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#x27;');
  }

  function fixed(n, places) {
    // Python's format() rounds half to even; toFixed rounds half away from
    // zero. They only disagree when the double sits exactly on the boundary,
    // which is rarer than it looks: 625.85 as a double is
    // 625.85000000000002, a hair above, and both correctly give 625.9. A true
    // midpoint like 229.25 is exactly representable, and there Python gives
    // 229.2 where toFixed gives 229.3.
    //
    // Detecting it needs the double's real expansion, not its shortest form
    // ("625.85") and not a scaled copy (x10 collapses the near-miss onto the
    // boundary). 18 places is enough to expose the difference.
    var exact = n.toFixed(18), dot = exact.indexOf('.');
    var next = exact.charAt(dot + 1 + places);
    var rest = exact.slice(dot + 2 + places);
    if (next === '5' && !/[1-9]/.test(rest)) {
      var f = Math.pow(10, places);
      return ((2 * Math.round(n * f / 2)) / f).toFixed(places);
    }
    return n.toFixed(places);
  }


  function ladderLp(entry) {
    var tier = entry.tier;
    if (!tier) return 0;
    var ti = D.tierOrder.indexOf(tier);
    if (ti < 0) ti = 0;
    var lp = entry.leaguePoints || 0;
    if (D.apexTiers.indexOf(tier) !== -1) {
      return ti * D.divisionsPerTier * D.lpPerDivision + lp;
    }
    var division = D.rankScore[entry.rank] || 0;
    return (ti * D.divisionsPerTier + division) * D.lpPerDivision + lp;
  }

  function ladderDecompose(value) {
    value = Math.max(0, Math.round(value));
    var steps = Math.floor(value / D.lpPerDivision);
    var lp = value - steps * D.lpPerDivision;
    var ti = Math.min(Math.floor(steps / D.divisionsPerTier), D.tierOrder.length - 1);
    var division = steps - ti * D.divisionsPerTier;
    return [ti, Math.min(division, D.divisionsPerTier - 1), lp];
  }

  function cap(t) { return t.charAt(0) + t.slice(1).toLowerCase(); }

  function rankBySc(division) {
    var keys = Object.keys(D.rankScore);
    for (var i = 0; i < keys.length; i++) {
      if (D.rankScore[keys[i]] === division) return keys[i];
    }
    return 'IV';
  }

  function scoreToRankLabel(value) {
    var d = ladderDecompose(value), tier = D.tierOrder[d[0]];
    if (D.apexTiers.indexOf(tier) !== -1) return cap(tier) + ' &middot; ' + d[2] + ' LP';
    return cap(tier) + ' ' + rankBySc(d[1]) + ' &middot; ' + d[2] + ' LP';
  }

  function lpStepLabel(prevValue, value, delta, exact) {
    var a = ladderDecompose(prevValue), b = ladderDecompose(value);
    if (a[0] !== b[0] || a[1] !== b[1]) return delta >= 0 ? 'promoted' : 'demoted';
    return (delta >= 0 ? '+' : '\u2212') + fixed(Math.abs(delta), 0) + ' LP' +
           (exact ? '' : ' (est.)');
  }

  // Split a known net LP change across the games that produced it: the win and
  // loss steps closest to a nominal 20 LP that still land on the next real
  // snapshot. Riot does not expose per-game LP, so the shape between two
  // snapshots is an estimate while every snapshot itself is measured.
  function segmentDeltas(wins, net) {
    if (!wins.length) return [];
    var W = 0, i;
    for (i = 0; i < wins.length; i++) if (wins[i]) W++;
    var L = wins.length - W;
    var lam = (net - D.nominalLp * (W - L)) / (W * W + L * L);
    var gain = Math.max(D.nominalLp + lam * W, 1.0);
    var loss = Math.max(D.nominalLp - lam * L, 1.0);
    var deltas = wins.map(function (w) { return w ? gain : -loss; });
    var sum = 0;
    for (i = 0; i < deltas.length; i++) sum += deltas[i];
    var residual = net - sum;
    if (Math.abs(residual) > 1e-9) {
      var share = residual / deltas.length;
      deltas = deltas.map(function (d) { return d + share; });
    }
    return deltas;
  }

  function buildLpTimeline(soloPts, soloMatches) {
    if (soloPts.length < 2) return [];
    var byDate = {}, i;
    for (i = 0; i < soloMatches.length; i++) {
      var m = soloMatches[i];
      (byDate[m.dateKey] = byDate[m.dateKey] || []).push(m);
    }
    Object.keys(byDate).forEach(function (d) {
      byDate[d].sort(function (a, b) { return (a.gameStartMs || 0) - (b.gameStartMs || 0); });
    });
    var dates = Object.keys(byDate).sort();

    var points = [{ idx: 0, score: ladderLp(soloPts[0]), delta: null, match: null, exact: true }];
    var idx = 0;
    for (i = 0; i + 1 < soloPts.length; i++) {
      var prev = soloPts[i], cur = soloPts[i + 1];
      var seg = [];
      dates.forEach(function (d) {
        if (prev.date < d && d <= cur.date) seg = seg.concat(byDate[d]);
      });
      if (!seg.length) continue;
      var start = ladderLp(prev), end = ladderLp(cur), run = start;
      var deltas = segmentDeltas(seg.map(function (m) { return !!m.win; }), end - start);
      for (var n = 0; n < seg.length; n++) {
        run += deltas[n];
        idx++;
        points.push({ idx: idx, score: run, delta: deltas[n], match: seg[n], exact: false });
      }
      points[points.length - 1].score = end;
      points[points.length - 1].exact = true;
    }
    return points;
  }

  // Labels stack in the reserved right gutter with a leader back to their real
  // end point: lines finish at different x, so anchoring each label to its own
  // line put them on top of the plot and each other.
  function endLabelGroups(entries, prefix, gutterX) {
    var MIN_LABEL_GAP = 26, ICON_SIZE = 14, out = [];
    entries.sort(function (a, b) { return a.ly - b.ly; });
    entries.forEach(function (e, i) {
      e.drawY = i === 0 ? e.ly : Math.max(e.ly, entries[i - 1].drawY + MIN_LABEL_GAP);
    });
    entries.forEach(function (e) {
      var anchorX = gutterX === null ? e.lx : gutterX;
      var parts = [];
      if (Math.abs(e.drawY - e.ly) > 3 || (gutterX !== null && anchorX - e.lx > 10)) {
        parts.push('<path d="M' + fixed(e.lx + 4, 1) + ',' + fixed(e.ly, 1) + ' L' +
          fixed(anchorX - 4, 1) + ',' + fixed(e.drawY, 1) + '" fill="none" stroke="var(' +
          e.varName + ')" stroke-width="1" stroke-dasharray="2,3" opacity="0.45" />');
      }
      var textX = anchorX;
      if (e.tier) {
        var url = D.rankIconBase.replace('{tier}', e.tier.toLowerCase());
        parts.push('<image href="' + esc(url) + '" x="' + fixed(anchorX, 1) + '" y="' +
          fixed(e.drawY - ICON_SIZE / 2, 1) + '" width="' + ICON_SIZE + '" height="' + ICON_SIZE +
          '" onerror="this.style.visibility=&#x27;hidden&#x27;" />');
        textX = anchorX + ICON_SIZE + 3;
      }
      parts.push('<text x="' + fixed(textX, 1) + '" y="' + fixed(e.drawY + 3, 1) +
        '" font-size="11" font-weight="700" fill="var(' + e.varName + ')">' + esc(e.label) + '</text>');
      if (e.net) {
        var c = e.net.direction > 0 ? 'var(--good)'
              : (e.net.direction < 0 ? 'var(--critical)' : 'var(--muted)');
        parts.push('<text x="' + fixed(textX, 1) + '" y="' + fixed(e.drawY + 15, 1) +
          '" font-size="10" fill="' + c + '">' + esc(e.net.text) + '</text>');
      }
      out.push('<g id="' + prefix + '-label-' + e.idx + '">' + parts.join('') + '</g>');
    });
    return out;
  }

  function buildSvg(state, compact, tail) {
    var friends = state.friends, timelines = state.timelines;
    var prefix = (compact ? 'lpm' : 'lp') + (tail ? 't' : '');
    var view = {}, i;
    friends.forEach(function (f) {
      var tl = timelines[f.label];
      var pts = (tail && tl.length > tail + 1) ? tl.slice(tl.length - (tail + 1)) : tl;
      var base = pts[0].idx, startI = tl.length - pts.length;
      view[f.label] = pts.map(function (p, n) {
        var q = {}; for (var k in p) q[k] = p[k];
        q.origIdx = p.idx;
        q.idx = p.idx - base;
        // The score of the game before this one in the full timeline; the
        // zoomed view's first point has one outside the slice.
        q.prevScore = (startI + n - 1 >= 0) ? tl[startI + n - 1].score : p.score;
        return q;
      });
    });
    var maxGames = 0;
    Object.keys(view).forEach(function (k) { maxGames = Math.max(maxGames, view[k].length - 1); });
    if (!maxGames) maxGames = 1;
    var scores = [];
    Object.keys(view).forEach(function (k) {
      view[k].forEach(function (p) { scores.push(p.score); });
    });
    var yMin = Math.min.apply(null, scores), yMax = Math.max.apply(null, scores);
    var pad = Math.max(40, (yMax - yMin) * 0.16);
    yMin -= pad; yMax += pad;
    if (yMax <= yMin) yMax = yMin + 200;

    var W, H, PAD_L, PAD_R, PAD_T, PAD_B;
    if (compact) {
      W = 360; H = Math.max(240, Math.min(420, 20 * friends.length + 190));
      PAD_L = 38; PAD_R = 10; PAD_T = 12; PAD_B = 28;
    } else {
      W = 900; H = Math.max(300, Math.min(660, 34 * friends.length + 140));
      PAD_L = 64; PAD_R = 175; PAD_T = 16; PAD_B = 34;
    }
    var plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;
    function xy(gi, score) {
      return [PAD_L + (maxGames ? gi / maxGames : 0) * plotW,
              PAD_T + (1 - (score - yMin) / (yMax - yMin)) * plotH];
    }

    var tierSpan = D.divisionsPerTier * D.lpPerDivision;
    var yTicks = [];
    var firstDiv = Math.floor(yMin / D.lpPerDivision);
    var lastDiv = Math.floor(yMax / D.lpPerDivision);
    var showDivisions = (lastDiv - firstDiv) <= 12 && !compact;
    for (var steps = Math.max(firstDiv, 0); steps <= lastDiv; steps++) {
      var tick = steps * D.lpPerDivision;
      if (tick < yMin || tick > yMax) continue;
      var dec = ladderDecompose(tick);
      if (dec[0] >= D.tierOrder.length) continue;
      if (tick % tierSpan === 0) yTicks.push([xy(0, tick)[1], cap(D.tierOrder[dec[0]])]);
      else if (showDivisions) yTicks.push([xy(0, tick)[1], rankBySc(dec[1])]);
    }

    var step = Math.max(1, Math.round(maxGames / (compact ? 3 : 6)));
    var tickIdxs = [];
    for (i = 0; i <= maxGames; i += step) tickIdxs.push(i);
    if (tickIdxs[tickIdxs.length - 1] !== maxGames) {
      if (maxGames - tickIdxs[tickIdxs.length - 1] < step * 0.6) tickIdxs.pop();
      tickIdxs.push(maxGames);
    }
    function tickLabel(gi) {
      if (tail) {
        var back = maxGames - gi;
        return back === 0 ? 'Latest' : (compact ? '\u2212' + back : back + ' ago');
      }
      return gi === 0 ? 'Start' : (compact ? String(gi) : 'Game ' + gi);
    }
    var xTicks = tickIdxs.map(function (gi) { return [xy(gi, yMin)[0], tickLabel(gi)]; });

    var seriesGroups = [], labelEntries = [];
    friends.forEach(function (f, fi) {
      var varName = '--series-f' + fi;
      var tl = view[f.label];
      var coords = tl.map(function (p) { return xy(p.idx, p.score); });
      var parts = [];
      var d = coords.map(function (c, n) {
        return (n === 0 ? 'M' : 'L') + fixed(c[0], 1) + ',' + fixed(c[1], 1);
      }).join(' ');
      parts.push('<path d="' + d + '" fill="none" stroke="var(' + varName +
                 ')" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />');
      tl.forEach(function (p, n) {
        var m = p.match, title, fill, r;
        if (m) {
          var move = lpStepLabel(p.prevScore, p.score, p.delta, p.exact);
          title = (f.label + ' \u2014 game ' + (p.origIdx === undefined ? p.idx : p.origIdx) +
                   ' \u2014 ' + (m.win ? 'Win' : 'Loss') + ' on ' + m.champion + ' \u2014 ' +
                   move + ' \u2192 ' + scoreToRankLabel(p.score)).replace('&middot;', '\u00b7');
          fill = m.win ? 'var(--good)' : 'var(--critical)';
          r = compact ? 3 : 3.5;
        } else {
          title = (f.label + ' \u2014 tracking started \u2014 ' +
                   scoreToRankLabel(p.score)).replace('&middot;', '\u00b7');
          fill = 'var(' + varName + ')';
          r = compact ? 3.5 : 4;
        }
        parts.push('<circle cx="' + fixed(coords[n][0], 1) + '" cy="' + fixed(coords[n][1], 1) +
          '" r="' + r + '" fill="' + fill + '" stroke="var(--surface-1)" stroke-width="1.5">' +
          '<title>' + esc(title) + '</title></circle>');
      });
      seriesGroups.push('<g id="' + prefix + '-series-' + fi + '">' + parts.join('') + '</g>');

      if (!compact) {
        var last = coords[coords.length - 1];
        var net;
        if (tail && tl.length > 1) {
          var dd = tl[tl.length - 1].score - tl[0].score;
          net = { text: (dd >= 0 ? '+' : '\u2212') + fixed(Math.abs(dd), 0) +
                        ' LP \u00b7 last ' + (tl.length - 1),
                  direction: dd > 0 ? 1 : (dd < 0 ? -1 : 0) };
        } else {
          net = state.netLabels[fi];
        }
        labelEntries.push({ idx: fi, varName: varName, label: f.label,
                            lx: last[0], ly: last[1], net: net, tier: state.tiers[fi] });
      }
    });

    var labelGroups = compact ? [] : endLabelGroups(labelEntries, prefix, W - PAD_R + 10);

    var gridSvg = yTicks.map(function (t) {
      return '<line x1="' + PAD_L + '" y1="' + fixed(t[0], 1) + '" x2="' + (W - PAD_R) +
        '" y2="' + fixed(t[0], 1) + '" class="chart-grid" /><text x="' + (PAD_L - 6) +
        '" y="' + fixed(t[0] + 4, 1) + '" text-anchor="end" class="chart-tick">' +
        esc(t[1]) + '</text>';
    }).join('');
    var xticksSvg = xTicks.map(function (t) {
      return '<text x="' + fixed(t[0], 1) + '" y="' + (H - PAD_B + (compact ? 16 : 20)) +
        '" text-anchor="middle" class="chart-tick">' + esc(t[1]) + '</text>';
    }).join('');
    var cls = compact ? 'rank-chart chart-compact' : 'rank-chart chart-wide';
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" class="' + cls + '" role="img" ' +
      'aria-label="Ranked Solo/Duo LP game by game">' + gridSvg + xticksSvg +
      seriesGroups.join('') + labelGroups.join('') + '</svg>';
  }

  // Per-friend summary text, shared by both renders. Mirrors the block at the
  // end of render_lp_chart().
  function summarize(friends, timelines) {
    var netLabels = [], tiers = [], standings = [];
    friends.forEach(function (f, i) {
      var tl = timelines[f.label];
      var netLp = tl[tl.length - 1].score - tl[0].score;
      var games = tl.length - 1, wins = 0;
      for (var n = 1; n < tl.length; n++) if (tl[n].match && tl[n].match.win) wins++;
      var hist = f.history, first = hist[0], last = hist[hist.length - 1];
      var record = wins + 'W ' + (games - wins) + 'L';
      var moveText;
      // Raw LP only means the same thing while tier and division hold still —
      // a promotion resets LP, so across one the ladder distance is not an LP
      // number worth printing.
      if (first.tier === last.tier && first.rank === last.rank) {
        var lp = (last.leaguePoints || 0) - (first.leaguePoints || 0);
        moveText = (lp >= 0 ? '+' : '\u2212') + Math.abs(lp) + ' LP';
      } else {
        moveText = rankName(first) + ' \u2192 ' + rankName(last);
      }
      netLabels.push({ text: moveText, direction: netLp > 0 ? 1 : (netLp < 0 ? -1 : 0) });
      tiers.push(last.tier);
      standings.push({ varName: '--series-f' + i, label: f.label, tier: last.tier,
                       rankLabel: rankLabelOf(last), games: games,
                       net: moveText + ' \u00b7 ' + record });
    });
    return { netLabels: netLabels, tiers: tiers, standings: standings };
  }

  function rankName(h) {
    if (!h.tier) return 'Unranked';
    var t = cap(h.tier);
    return D.apexTiers.indexOf(h.tier) !== -1 ? t : t + ' ' + (h.rank || '');
  }
  function rankLabelOf(h) {
    // rank_label() emits "&middot;" and the chip template interpolates it
    // without escaping, so the entity has to survive here too.
    if (!h.tier) return 'Unranked';
    return rankName(h) + ' &middot; ' + (h.leaguePoints || 0) + ' LP';
  }

  function computeState(friends) {
    var timelines = {}, kept = [];
    friends.forEach(function (f) {
      var tl = buildLpTimeline(f.history, f.matches);
      if (tl.length >= 2) { timelines[f.label] = tl; kept.push(f); }
    });
    if (!kept.length) return null;
    var s = summarize(kept, timelines);
    return { friends: kept, timelines: timelines, netLabels: s.netLabels,
             tiers: s.tiers, standings: s.standings };
  }

  function chartsHtml(state) {
    var longest = 0;
    state.friends.forEach(function (f) {
      longest = Math.max(longest, state.timelines[f.label].length - 1);
    });
    var html = '<div class="chart-view" data-range="all">' +
      buildSvg(state, false, null) + buildSvg(state, true, null) + '</div>';
    if (longest > D.tailGames + 4) {
      html += '<div class="chart-view" data-range="tail" hidden>' +
        buildSvg(state, false, D.tailGames) + buildSvg(state, true, D.tailGames) + '</div>';
    }
    return html;
  }

  function standingsHtml(state) {
    return state.standings.map(function (s) {
      var icon = s.tier
        ? '<img src="' + esc(D.rankIconBase.replace('{tier}', s.tier.toLowerCase())) +
          '" alt="" class="rank-icon" width="22" height="22" loading="lazy" ' +
          'onerror="this.style.visibility=&#x27;hidden&#x27;">'
        : '<span class="rank-icon rank-icon-ph" style="width:22px;height:22px;"></span>';
      return '<div class="standing-chip" style="border-color:var(' + s.varName + ');">' + icon +
        '<span class="name" style="color:var(' + s.varName + ');">' + esc(s.label) + '</span>' +
        '<span class="rank">' + s.rankLabel + '</span>' +
        '<span class="rank muted">\u00b7 ' + s.games + 'g</span>' +
        '<span class="rank muted chip-net">\u00b7 ' + esc(s.net) + '</span></div>';
    }).join('');
  }

  function init() {
    var el = document.getElementById('lp-chart-data');
    if (!el) return false;
    try { D = JSON.parse(el.textContent); } catch (e) { return false; }
    return true;
  }

  // Render the untouched data and compare against what the server produced.
  // Any difference means the two renderers have drifted, which is the one
  // failure mode a second copy of this maths can have.
  function verifySelf() {
    if (!D) return { ok: false, reason: 'no data' };
    var state = computeState(JSON.parse(JSON.stringify(D.friends)));
    if (!state) return { ok: false, reason: 'no timelines' };
    var host = document.querySelector('[data-lp-charts]');
    if (!host) return { ok: false, reason: 'no host' };
    // Both sides must be read back through the DOM: innerHTML rewrites
    // self-closing SVG tags (<line /> becomes <line></line>), so comparing a
    // freshly built string against a parsed one reports differences that are
    // not there.
    var box = document.createElement('div');
    box.innerHTML = chartsHtml(state);
    // Rank emblems come from a community CDN and their onerror handler writes
    // an inline style when one fails to load. That is runtime state on the
    // live page, not a rendering difference, so drop it from both sides.
    function norm(h) { return h.replace(/ style="visibility: hidden;"/g, ''); }
    var mine = norm(box.innerHTML), theirs = norm(host.innerHTML);
    if (mine === theirs) return { ok: true, bytes: mine.length };
    var at = 0;
    while (at < mine.length && at < theirs.length && mine[at] === theirs[at]) at++;
    return { ok: false, at: at, mine: mine.slice(Math.max(0, at - 70), at + 70),
             theirs: theirs.slice(Math.max(0, at - 70), at + 70),
             lens: [mine.length, theirs.length] };
  }

  // Redraw with a live LP reading and any games played since the publish.
  // `live` is { label: {tier, rank, leaguePoints, matches: [...] } }.
  function rerender(live) {
    if (!D) return 0;
    var today = new Date();
    var dateKey = today.getFullYear() + '-' +
                  ('0' + (today.getMonth() + 1)).slice(-2) + '-' +
                  ('0' + today.getDate()).slice(-2);
    var touched = 0;
    var friends = D.friends.map(function (f) {
      var copy = { label: f.label, history: f.history.slice(), matches: f.matches.slice() };
      var l = live[f.label];
      if (!l || !l.tier) return copy;
      var added = (l.matches || []).filter(function (m) {
        return m.queue === 'Ranked Solo/Duo';
      }).map(function (m) {
        return { dateKey: dateKey, gameStartMs: m.gameStartMs, win: !!m.win,
                 champion: m.champion };
      });
      if (!added.length) return copy;
      // The live reading becomes today's snapshot, so the new games are an
      // ordinary segment between two measured points — the same shape every
      // other part of this chart is built from.
      var lastHist = copy.history[copy.history.length - 1];
      var snap = { date: dateKey, tier: l.tier, rank: l.rank, leaguePoints: l.leaguePoints };
      if (lastHist && lastHist.date === dateKey) copy.history[copy.history.length - 1] = snap;
      else copy.history.push(snap);
      copy.matches = copy.matches.concat(added);
      touched += added.length;
      return copy;
    });
    if (!touched) return 0;
    var state = computeState(friends);
    if (!state) return 0;
    var host = document.querySelector('[data-lp-charts]');
    var chips = document.querySelector('[data-lp-standings]');
    if (!host) return 0;

    // Replacing the SVGs throws away two things the viewer chose. The legend
    // and zoom handlers survive (they live outside this element and look
    // groups up by id at click time), but the state they wrote does not.
    var hidden = [];
    host.querySelectorAll('g[id*="-series-"]').forEach(function (g) {
      if (g.style.display === 'none') hidden.push(g.id);
    });
    var activeRange = null;
    var activeBtn = document.querySelector('.range-btn.active');
    if (activeBtn) activeRange = activeBtn.getAttribute('data-range');

    host.innerHTML = chartsHtml(state);
    if (chips) chips.innerHTML = standingsHtml(state);

    hidden.forEach(function (id) {
      var g = document.getElementById(id);
      if (g) g.style.display = 'none';
      var lbl = document.getElementById(id.replace('-series-', '-label-'));
      if (lbl) lbl.style.display = 'none';
    });
    if (activeRange) {
      host.querySelectorAll('.chart-view').forEach(function (v) {
        v.hidden = v.getAttribute('data-range') !== activeRange;
      });
    }
    return touched;
  }

  return { init: init, verifySelf: verifySelf, rerender: rerender };
})();
'''


def build_html(data):
    friends = data.get("friends", [])
    friends_sorted = sorted(friends, key=lambda f: tier_score(f["ranked"].get("solo")), reverse=True)
    now = datetime.now()
    rank_history = data.get("rankHistory", [])
    set_icon_context(data.get("ddragonVersion"), data.get("championIconMap", {}))
    set_platform(data.get("platform"))

    leaderboard_rows = "".join(
        render_leaderboard_row(f, i + 1, weekly_trend_for(rank_history, f["label"], now))
        for i, f in enumerate(friends_sorted)
    )
    cards = "".join(render_friend_card(f, i + 1, now) for i, f in enumerate(friends_sorted))
    # Pills select which friend card is shown, so they are a tablist, not a
    # row of buttons: one tab stop for the group, arrow keys within it.
    friend_pills = "".join(
        f'<button class="pill{" active" if i == 0 else ""}" type="button" role="tab"'
        f' id="pill-{f["label"].lower()}" aria-controls="friend-{f["label"].lower()}"'
        f' aria-selected="{"true" if i == 0 else "false"}" tabindex="{0 if i == 0 else -1}"'
        f' data-friend="{f["label"].lower()}">{esc(f["label"])}</button>'
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

    notes_html, notes_latest = render_patch_notes(load_patch_notes())

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

    # Everything the client-side "live ranks" refresh needs to call Riot with a
    # viewer's own key and rewrite the leaderboard: who to look up, which hosts
    # to use, and how to rebuild a tier's colour and emblem. Deliberately no
    # puuids — those stay out of the public page, so the browser resolves each
    # Riot ID itself.
    # knownMatches lets the browser tell a genuinely new game from one already
    # in the snapshot, so it only spends a call on match detail it does not
    # have. The newest 40 is far more than a refresh could add between builds.
    live_refresh_json = json.dumps({
        "platform": data.get("platform", "euw1"),
        "friends": [{"label": f["label"], "riotId": f.get("riotId", "")} for f in friends_sorted],
        "tierVars": {t: tier_var(t) for t in TIER_ORDER},
        "rankIconBase": RANK_ICON_BASE,
        "apexTiers": sorted(APEX_TIERS),
        # Enough to work out a ladder position in the browser. Rows are sorted
        # server-side at build time, so without this a refresh leaves everyone
        # in their old order while showing their new LP.
        "tierOrder": TIER_ORDER,
        "rankScore": RANK_SCORE,
        "baseScores": {f["label"]: ladder_lp(f["ranked"].get("solo") or {})
                       for f in friends_sorted},
        "ddragonVersion": data.get("ddragonVersion"),
        "championIcons": data.get("championIconMap", {}),
        "rankedQueues": LIVE_RANKED_QUEUES,
        "queueNames": LIVE_QUEUE_NAMES,
        "knownMatches": {
            f["label"]: [m.get("matchId") for m in f.get("seasonMatches", [])[:40] if m.get("matchId")]
            for f in friends_sorted
        },
        # The id diff alone was not enough: knownMatches only holds the newest
        # 40 games, so an older Flex game outside that window looked new and
        # was spliced in among today's. Riot can filter by start time server
        # side, which fixes that and means an inactive friend costs no match
        # calls at all.
        "newestMatchMs": {
            f["label"]: max([m.get("gameStartMs") or 0 for m in f.get("seasonMatches", [])] or [0])
            for f in friends_sorted
        },
    }, ensure_ascii=False)

    # ---- Share metadata -------------------------------------------------
    # A link into a group chat should unfurl with the current ladder, not a
    # bare URL. og:image has to be absolute per the spec (Discord and iMessage
    # both refuse relative ones), so the card is only advertised when
    # config.json supplies site_url.
    leader = friends_sorted[0] if friends_sorted else None
    share_desc = (
        f'Ranked Solo/Duo standings, per-game LP history and season stats for '
        f'{len(friends_sorted)} friends on {esc(str(data.get("platform", "EUW")).upper())}.'
    )
    if leader:
        share_desc += f' {esc(leader["label"])} leads at {esc(rank_label_text(leader["ranked"].get("solo")))}.'
    site_url = (data.get("siteUrl") or "").rstrip("/")
    og_tags = ""
    if site_url:
        og_tags = f"""
<meta property="og:url" content="{esc(site_url)}/">
<meta property="og:image" content="{esc(site_url)}/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{esc(site_url)}/og.png">"""

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
<meta name="description" content="{esc(share_desc)}">
<link rel="icon" href="{favicon_data_uri()}">
<link rel="apple-touch-icon" href="icon-180.png">
<meta name="theme-color" content="#eceff5" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#090a0e" media="(prefers-color-scheme: dark)">
<meta property="og:type" content="website">
<meta property="og:site_name" content="League Friends Dashboard">
<meta property="og:title" content="League Friends Dashboard">
<meta property="og:description" content="{esc(share_desc)}">{og_tags}
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
  html {{ scroll-behavior: smooth; }}
  ::selection {{ background: color-mix(in srgb, var(--accent) 28%, transparent); }}
  /* Themed scrollbars — the default light-grey ones cut straight through the
     dark theme. .tabs and .friend-pills override this back to none. */
  * {{ scrollbar-width: thin; scrollbar-color: var(--gridline) transparent; }}
  ::-webkit-scrollbar {{ width: 11px; height: 11px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{
    background: var(--gridline); border-radius: 999px; border: 3px solid transparent;
    background-clip: content-box;
  }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--muted); background-clip: content-box; }}
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
  .header-actions {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
  /* One class for every header control. These used to be styled by id, and
     three of the five ids were missing from the rule, so Live ranks / Refresh
     data / API key rendered as raw browser buttons beside two styled ones. */
  .hbtn {{
    flex-shrink: 0; height: 40px; border-radius: 11px; padding: 0 15px;
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
    font-family: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
    display: flex; align-items: center; justify-content: center; gap: 7px;
    box-shadow: var(--shadow-sm); transition: transform .16s ease, box-shadow .16s ease, background .16s ease;
  }}
  /* .hbtn sets display:flex, which would otherwise defeat the `hidden`
     attribute the hosted-only buttons rely on. */
  .hbtn[hidden] {{ display: none; }}
  /* Two labels per button: the full one on desktop, a clipped one on phones,
     where four buttons no longer fit across 375px. */
  .btn-short {{ display: none; }}
  .hbtn:disabled {{ opacity: .55; cursor: not-allowed; transform: none; }}
  #theme-toggle {{ width: 40px; font-size: 17px; padding: 0; }}
  .hbtn:hover:not(:disabled) {{ transform: translateY(-1px); box-shadow: var(--shadow-md); background: var(--surface-2); }}
  .hbtn:active:not(:disabled) {{ transform: translateY(0); }}
  /* The header is one real action plus utilities, so only the action is
     coloured. Everything else stays quiet. */
  .hbtn.primary {{
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 62%, var(--accent-2)));
    border-color: transparent; color: #fff; box-shadow: 0 2px 10px var(--halo);
  }}
  .hbtn.primary:hover:not(:disabled) {{
    background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 86%, #000),
                                        color-mix(in srgb, var(--accent) 56%, var(--accent-2)));
  }}
  :focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 8px; }}

  /* Keyboard users shouldn't have to tab through the whole header to reach
     the content. Off-screen until focused. */
  .skip-link {{
    position: absolute; left: 12px; top: -70px; z-index: 60;
    background: var(--surface-1); color: var(--text-primary);
    border: 1px solid var(--border); border-radius: 10px;
    padding: 10px 15px; font-size: 13px; font-weight: 600;
    box-shadow: var(--shadow-md); transition: top .15s ease;
  }}
  .skip-link:focus {{ top: 12px; text-decoration: none; }}

  /* Friend cards and match tables run long; a trip back to the top beats
     scrolling past four of them to reach the tab bar. */
  #to-top {{
    position: fixed; right: 18px; bottom: 18px; z-index: 40;
    width: 44px; height: 44px; border-radius: 50%; cursor: pointer;
    border: 1px solid var(--border); background: var(--surface-1); color: var(--text-primary);
    font-size: 16px; line-height: 1; box-shadow: var(--shadow-md);
    display: flex; align-items: center; justify-content: center;
    opacity: 0; visibility: hidden; transform: translateY(10px);
    transition: opacity .2s ease, transform .2s ease, visibility .2s ease, background .16s ease;
  }}
  #to-top.show {{ opacity: 1; visibility: visible; transform: none; }}
  #to-top:hover {{ background: var(--surface-2); }}

  /* One-line "you can click this" note under a panel heading. */
  .panel-hint {{ font-size: 12.5px; color: var(--muted); margin: -8px 0 13px; }}

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
  /* Rank needs the most room of the text columns — "Platinum III · 91 LP"
     plus an emblem — and previously got 17%, leaving ~3px of slack, so a
     slightly wider glyph combination wrapped one row onto two lines. The
     name column was the one carrying surplus, so the space comes from there. */
  .leaderboard th:nth-child(1), .leaderboard td:nth-child(1) {{ width: 6%; text-align: center; }}
  .leaderboard th:nth-child(2), .leaderboard td:nth-child(2) {{ width: 18%; }}
  .leaderboard th:nth-child(3), .leaderboard td:nth-child(3) {{ width: 22%; }}
  .leaderboard th:nth-child(4), .leaderboard td:nth-child(4) {{ width: 12%; }}
  .leaderboard th:nth-child(5), .leaderboard td:nth-child(5) {{ width: 17%; }}
  .leaderboard th:nth-child(6), .leaderboard td:nth-child(6) {{ width: 25%; }}
  /* Belt and braces: these are all short single-line values, so never wrap
     them even if a future tier name or record runs longer than expected. */
  .leaderboard td:nth-child(3), .leaderboard td:nth-child(4),
  .leaderboard td:nth-child(5), .leaderboard td:nth-child(6),
  .leaderboard th {{ white-space: nowrap; }}
  .leaderboard td:nth-child(4), .leaderboard td:nth-child(5) {{ font-variant-numeric: tabular-nums; }}
  .leaderboard tbody td {{ padding-top: 12px; padding-bottom: 12px; }}
  /* The name is the row's anchor, so it reads as text rather than a link,
     and stops competing with the tier colour next to it. */
  .leaderboard td:nth-child(2) a {{ color: var(--text-primary); font-weight: 700; }}
  .leaderboard td:nth-child(2) a:hover {{ color: var(--accent); text-decoration: none; }}
  .leaderboard tbody tr:hover td:nth-child(2) a {{ color: var(--accent); }}
  /* The whole row opens that player, not just the few characters of their
     name — the row is what people aim at. */
  .leaderboard tbody tr {{ cursor: pointer; }}
  @media (max-width: 720px) {{
    .leaderboard {{ table-layout: auto; }}
    .leaderboard tbody td {{ padding-top: 9px; padding-bottom: 9px; }}
  }}

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
    position: relative; overflow: hidden;
  }}
  /* A tier-coloured hairline ties the card to the same colour the player's
     rank uses everywhere else on the page. */
  .card::before {{
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 3px; z-index: 2;
    background: linear-gradient(90deg, var(--card-tier, var(--accent)), transparent 62%);
  }}
  /* The player's signature champion, behind the top-right of the card.
     Positioned children paint above static ones, so the art would otherwise
     cover the header — everything except the art is lifted above it.
     The fade is three veils painted in the card's own surface colour rather
     than a mask, so it needs no mask-image support and degrades to a plain
     card if any of it is unsupported. */
  .card-art {{
    position: absolute; top: 0; right: 0; width: 66%; height: 215px;
    pointer-events: none; user-select: none;
  }}
  .card > *:not(.card-art) {{ position: relative; z-index: 1; }}
  .card-art img {{
    width: 100%; height: 100%; display: block;
    object-fit: cover; object-position: 56% 26%;
    /* Held well back. The veils below only reach ~55% opacity where the rank
       rows sit, so the art itself has to be faint for text to stay crisp —
       especially in the light theme, where the veil is white over dark art. */
    opacity: .4;
  }}
  .card-art::after {{
    content: ""; position: absolute; inset: 0;
    background:
      linear-gradient(to right, var(--surface-1) 3%,
                                color-mix(in srgb, var(--surface-1) 60%, transparent) 46%,
                                color-mix(in srgb, var(--surface-1) 38%, transparent) 100%),
      linear-gradient(to top, var(--surface-1) 8%,
                              color-mix(in srgb, var(--surface-1) 48%, transparent) 58%,
                              color-mix(in srgb, var(--surface-1) 18%, transparent) 100%),
      linear-gradient(115deg, transparent 42%,
                              color-mix(in srgb, var(--card-tier, var(--accent)) 30%, transparent) 100%);
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
    /* Sits over the champion art, so it needs an opaque backing of its own
       rather than a translucent tint. */
    background: color-mix(in srgb, #eb6834 14%, var(--surface-1));
    border: 1px solid rgba(235,104,52,0.35);
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
  /* Games pulled in by the live refresh, ringed so it is obvious something
     actually arrived rather than leaving you to guess. */
  .dot-new {{ box-shadow: 0 0 0 2px var(--surface-1), 0 0 0 3px var(--accent); }}
  tr.row-new td {{ background: color-mix(in srgb, var(--accent) 9%, transparent); }}

  .season-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(152px, 1fr)); gap: 10px; margin-top: 14px; }}
  .stat-tile {{
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 11px; padding: 12px 14px;
    transition: transform .16s ease, border-color .16s ease;
  }}
  .stat-tile:hover {{ transform: translateY(-2px); border-color: color-mix(in srgb, var(--accent) 30%, var(--border)); }}
  .stat-value {{ font-size: 23px; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; line-height: 1.15; }}
  .stat-label {{ font-size: 11px; color: var(--muted); margin-top: 3px; line-height: 1.35; }}

  /* ---- Rank chart ---------------------------------------------------- */
  .range-toggle {{
    display: inline-flex; gap: 3px; padding: 3px; margin-bottom: 10px;
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 9px;
  }}
  .range-btn {{
    appearance: none; border: none; background: none; cursor: pointer;
    font-family: inherit; font-size: 12px; font-weight: 600; color: var(--muted);
    padding: 6px 13px; border-radius: 7px;
  }}
  .range-btn:hover {{ color: var(--text-primary); }}
  .range-btn.active {{ background: var(--surface-1); color: var(--text-primary); box-shadow: var(--shadow-sm); }}
  .chart-view[hidden] {{ display: none; }}

  .rank-chart {{ width: 100%; height: auto; overflow: visible; }}
  .chart-grid {{ stroke: var(--gridline); stroke-width: 1; }}
  .chart-tick {{ fill: var(--muted); font-size: 11px; font-family: "Inter", system-ui, sans-serif; }}
  .rank-chart circle {{ transition: r .12s ease; }}
  .rank-chart circle:hover {{ r: 6; }}
  /* Hovering a legend name fades the other lines back, which is the quickest
     way to follow one person through seven overlapping series. */
  .rank-chart g[id*="-series-"], .rank-chart g[id*="-label-"] {{ transition: opacity .15s ease; }}
  .rank-chart.has-focus g[id*="-series-"]:not(.focus-on),
  .rank-chart.has-focus g[id*="-label-"]:not(.focus-on) {{ opacity: 0.12; }}
  .legend-item {{ position: relative; }}

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

  /* ---- Duo synergy ---------------------------------------------------- */
  .duo-controls {{
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    justify-content: space-between; margin-bottom: 14px;
  }}
  .duo-filters {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .duo-chip {{
    appearance: none; cursor: pointer; font-family: inherit; font-size: 12px; font-weight: 600;
    padding: 6px 12px; border-radius: 999px; border: 1px solid var(--border);
    background: var(--surface-1); color: var(--text-secondary);
    transition: background .14s ease, border-color .14s ease, color .14s ease;
  }}
  .duo-chip:hover {{ background: var(--surface-2); color: var(--text-primary); }}
  .duo-chip.active {{
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 62%, var(--accent-2)));
    border-color: transparent; color: #fff;
  }}
  .duo-grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(238px, 1fr)); gap: 12px;
  }}
  .duo-card {{
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px;
    padding: 14px 15px; transition: transform .16s ease, border-color .16s ease;
  }}
  .duo-card[hidden] {{ display: none; }}
  .duo-card:hover {{ transform: translateY(-2px); border-color: color-mix(in srgb, var(--accent) 30%, var(--border)); }}
  .duo-names {{ display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 14px; flex-wrap: wrap; }}
  .duo-amp {{ color: var(--muted); font-weight: 500; }}
  /* The winrate is the headline; the record sits on its baseline so the two
     read as one figure rather than competing. */
  .duo-figure {{ display: flex; align-items: baseline; gap: 8px; margin: 9px 0 7px; }}
  .duo-wr {{
    font-family: "Outfit", "Inter", sans-serif; font-size: 24px; font-weight: 700;
    letter-spacing: -0.02em; font-variant-numeric: tabular-nums; line-height: 1;
  }}
  .duo-record {{ font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .duo-track {{ height: 7px; border-radius: 999px; background: var(--gridline); overflow: hidden; }}
  .duo-fill {{ height: 100%; border-radius: 999px; }}
  .duo-fill.good {{ background: linear-gradient(90deg, color-mix(in srgb, var(--good) 70%, transparent), var(--good)); }}
  .duo-fill.bad {{ background: linear-gradient(90deg, color-mix(in srgb, var(--critical) 70%, transparent), var(--critical)); }}
  .duo-lift {{ font-size: 11.5px; font-weight: 600; margin-top: 9px; }}
  .duo-lift.up {{ color: var(--good); }}
  .duo-lift.down {{ color: var(--critical); }}
  .duo-lift.flat {{ color: var(--muted); }}
  .duo-lift .muted {{ font-weight: 500; }}
  .duo-games {{ font-size: 11.5px; color: var(--muted); margin-top: 4px; }}
  /* Under five games a winrate swings on a single result; say so rather than
     letting a sort by lift imply the pair is genuinely better. */
  .duo-thin {{ color: var(--critical); opacity: .75; font-weight: 600; }}
  .duo-empty {{ font-size: 13px; color: var(--muted); padding: 18px 0; }}
  .duo-empty[hidden] {{ display: none; }}

  /* ---- Patch notes ---------------------------------------------------- */
  #patch-notes {{ width: 40px; padding: 0; font-size: 16px; position: relative; }}
  /* Unread marker. Sits on the button rather than beside it so the header
     keeps its shape whether or not there is anything new. */
  .note-dot {{
    position: absolute; top: 6px; right: 6px; width: 8px; height: 8px;
    border-radius: 50%; background: var(--critical);
    box-shadow: 0 0 0 2px var(--surface-1);
  }}
  .note-dot[hidden] {{ display: none; }}
  /* Both are single-class selectors and this block is declared before
     .modal, so it needs the extra class to win on specificity. */
  .modal.notes-modal {{ max-width: 570px; }}
  .notes-body {{
    margin-top: 18px; max-height: min(58vh, 470px); overflow-y: auto; padding-right: 8px;
  }}
  .note {{ padding-bottom: 16px; margin-bottom: 16px; border-bottom: 1px solid var(--gridline); }}
  .note:last-child {{ padding-bottom: 0; margin-bottom: 0; border-bottom: none; }}
  .note-date {{
    font-size: 10.5px; font-weight: 700; letter-spacing: 0.06em;
    text-transform: uppercase; color: var(--muted);
  }}
  .note h4 {{
    margin: 4px 0 10px; font-size: 15px; letter-spacing: -0.01em;
    font-family: "Outfit", "Inter", system-ui, sans-serif;
  }}
  .note ul {{ margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 9px; }}
  .note li {{
    display: flex; gap: 9px; align-items: flex-start;
    font-size: 13px; line-height: 1.5; color: var(--text-secondary);
  }}
  .note-tag {{
    flex-shrink: 0; min-width: 54px; text-align: center; margin-top: 1px;
    font-size: 9.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em;
    border-radius: 999px; padding: 3px 7px;
  }}
  .note-new {{
    color: var(--accent); background: color-mix(in srgb, var(--accent) 13%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 34%, transparent);
  }}
  .note-fix {{
    color: var(--good); background: color-mix(in srgb, var(--good) 13%, transparent);
    border: 1px solid color-mix(in srgb, var(--good) 34%, transparent);
  }}
  .note-better {{
    color: var(--accent-2); background: color-mix(in srgb, var(--accent-2) 13%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent-2) 34%, transparent);
  }}

  /* ---- External profile links ---------------------------------------- */
  /* Opaque chips rather than plain links: they sit over the champion art on
     a phone, where the veils are thinnest. */
  .ext-links {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .ext-link {{
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 11.5px; font-weight: 600; color: var(--text-secondary);
    background: var(--surface-2); border: 1px solid var(--border);
    border-radius: 999px; padding: 4px 11px; white-space: nowrap;
    transition: color .14s ease, border-color .14s ease, background .14s ease;
  }}
  .ext-link:hover {{
    color: var(--accent); text-decoration: none;
    border-color: color-mix(in srgb, var(--accent) 42%, var(--border));
    background: color-mix(in srgb, var(--accent) 9%, var(--surface-2));
  }}
  .ext-link .ext {{ font-size: 9.5px; opacity: .65; }}

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
  footer {{
    text-align: center; color: var(--muted); font-size: 12px; line-height: 1.6;
    margin-top: 34px; padding-top: 22px; border-top: 1px solid var(--border);
  }}
  .footer-mark {{
    width: 26px; height: 26px; border-radius: 8px; margin: 0 auto 10px;
    display: flex; align-items: center; justify-content: center;
    background: linear-gradient(140deg, var(--accent), var(--accent-2));
    opacity: .8;
  }}
  .footer-mark svg {{ width: 16px; height: 16px; }}

  /* ---- Tabs ---------------------------------------------------------- */
  .tabs {{
    display: flex; gap: 4px; margin-bottom: 20px; overflow-x: auto;
    background: color-mix(in srgb, var(--surface-1) 86%, transparent);
    -webkit-backdrop-filter: saturate(180%) blur(14px);
    backdrop-filter: saturate(180%) blur(14px);
    border: 1px solid var(--border);
    border-radius: 12px; padding: 5px; box-shadow: var(--shadow-sm);
    scrollbar-width: none;
    /* Sticky so switching view never means scrolling back up past a long
       friend card. Content passes under the blur rather than behind a solid
       bar, so you keep your place. */
    position: sticky; top: 10px; z-index: 30;
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
  .card[hidden], .tab-panel[hidden] {{ display: none; }}
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

  /* Rows updated by the client-side live-ranks refresh, so it's obvious
     which figures are live and which came from the published snapshot. */
  .row-live td {{ background: color-mix(in srgb, var(--accent) 7%, transparent); }}
  .row-live [data-cell="rank"] {{ font-weight: 700; }}

  /* ---- Hosted controls: refresh + API key ---------------------------- */
  /* Visibility and disabled styling for these now come from .hbtn above. */
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
    position: fixed; inset: 0; background: rgba(6,8,12,0.62);
    -webkit-backdrop-filter: blur(5px); backdrop-filter: blur(5px);
    display: flex; align-items: center; justify-content: center; padding: 20px; z-index: 50;
  }}
  .modal-backdrop[hidden] {{ display: none; }}
  .modal {{
    background: var(--surface-1); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 24px; width: 100%; max-width: 448px; box-shadow: var(--shadow-lg);
    animation: modal-in .18s cubic-bezier(.2,.8,.3,1) both;
  }}
  @keyframes modal-in {{
    from {{ opacity: 0; transform: translateY(10px) scale(.985); }}
    to {{ opacity: 1; transform: none; }}
  }}
  /* Title block: the same gradient tile as the page's brand mark, so the
     dialog reads as part of the site rather than a browser prompt. */
  .modal-head {{ display: flex; gap: 13px; align-items: flex-start; }}
  .modal-icon {{
    width: 38px; height: 38px; border-radius: 11px; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; color: #fff;
    background: linear-gradient(140deg, var(--accent), var(--accent-2));
    box-shadow: 0 4px 14px var(--halo);
  }}
  .modal h3 {{ margin: 1px 0 5px; font-size: 17px; letter-spacing: -0.01em; }}
  .modal-head p {{ margin: 0; line-height: 1.5; }}
  .modal .field {{ display: block; margin-top: 16px; }}
  .modal .field span {{ display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; font-weight: 600; }}
  .modal input[type="text"], .modal input[type="password"] {{
    width: 100%; font-family: inherit; font-size: 13px; padding: 11px 12px;
    border-radius: 10px; border: 1px solid var(--border);
    background: var(--surface-2); color: var(--text-primary);
    transition: border-color .14s ease, box-shadow .14s ease;
  }}
  /* An API key is a token, not prose — monospace makes a mistyped character
     findable instead of hiding it in proportional text. */
  #modal-key {{ font-family: ui-monospace, SFMono-Regular, "Cascadia Mono", Consolas, monospace; font-size: 12.5px; }}
  .modal input:focus {{
    outline: none; border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent);
  }}
  .modal-link {{
    display: inline-flex; align-items: center; gap: 6px; margin-top: 8px;
    padding: 5px 0; font-size: 12.5px; font-weight: 600; color: var(--accent);
  }}
  .modal-link[hidden] {{ display: none; }}
  .modal-link .ext {{ font-size: 11px; opacity: .8; }}
  /* Its own row, not a line of the message slot: writing an error message
     used to replace this checkbox outright, silently clearing the choice. */
  .checkrow {{
    display: flex; align-items: center; gap: 10px; margin-top: 16px;
    padding: 11px 13px; border-radius: 10px; cursor: pointer;
    background: var(--surface-2); border: 1px solid var(--border);
    font-size: 12.5px; color: var(--text-secondary); user-select: none;
    transition: border-color .14s ease, background .14s ease;
  }}
  .checkrow[hidden] {{ display: none; }}
  .checkrow:hover {{ border-color: color-mix(in srgb, var(--accent) 34%, var(--border)); }}
  .checkrow input {{
    width: 17px; height: 17px; flex-shrink: 0; margin: 0;
    accent-color: var(--accent); cursor: pointer;
  }}
  .modal-msg {{
    font-size: 12.5px; margin-top: 14px; line-height: 1.45;
    padding: 10px 12px; border-radius: 9px;
    color: var(--critical);
    background: color-mix(in srgb, var(--critical) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--critical) 26%, transparent);
  }}
  /* No permanent blank gap when there is nothing to say — collapsed rather
     than display:none, which would drop the live region out of the
     accessibility tree and stop screen readers announcing errors. */
  .modal-msg:empty {{ margin: 0; padding: 0; border: none; background: none; }}
  .modal-msg.ok {{
    color: var(--good);
    background: color-mix(in srgb, var(--good) 10%, transparent);
    border-color: color-mix(in srgb, var(--good) 26%, transparent);
  }}
  .modal-actions {{ display: flex; align-items: center; justify-content: flex-end; gap: 9px; margin-top: 20px; }}
  /* Quiet, left-aligned: clearing a saved key is a real need on a shared
     computer, but it is never the action someone opened the dialog for. */
  .btn-link {{
    appearance: none; background: none; border: none; cursor: pointer;
    font-family: inherit; font-size: 12.5px; font-weight: 600;
    color: var(--muted); padding: 6px 2px; margin-right: auto;
  }}
  .btn-link:hover {{ color: var(--critical); text-decoration: underline; }}
  .btn-link[hidden] {{ display: none; }}
  .btn-primary, .btn-ghost {{
    font-family: inherit; font-size: 13px; font-weight: 600;
    height: 40px; padding: 0 20px; border-radius: 10px; cursor: pointer;
    border: 1px solid var(--border);
    display: inline-flex; align-items: center; justify-content: center;
    transition: transform .14s ease, box-shadow .14s ease, background .14s ease;
  }}
  .btn-ghost {{ background: var(--surface-2); color: var(--text-secondary); }}
  .btn-ghost:hover {{ background: var(--gridline); }}
  .btn-primary {{
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 62%, var(--accent-2)));
    border-color: transparent; color: #fff; box-shadow: 0 2px 10px var(--halo);
  }}
  .btn-primary:hover:not(:disabled) {{ transform: translateY(-1px); box-shadow: var(--shadow-md); }}
  .btn-primary:disabled {{ opacity: .6; cursor: not-allowed; transform: none; }}

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
    /* Narrower column means the horizontal veil has less room to fade, so
       the art gets shorter and sits further back. */
    .ext-link {{ min-height: 38px; padding: 8px 13px; font-size: 12px; }}
    .duo-grid {{ grid-template-columns: 1fr; }}
    .duo-chip {{ min-height: 38px; padding: 9px 14px; }}
    .duo-controls {{ gap: 12px; }}
    /* Three sort labels at the shared .range-btn padding wrapped onto a second
       row inside the pill, which reads as broken rather than as a toggle. */
    .duo-controls .range-toggle {{ width: 100%; }}
    .duo-controls .range-btn {{ flex: 1; padding: 11px 6px; font-size: 12px; }}
    .card-art {{ width: 100%; height: 148px; }}
    .card-art img {{ object-position: 56% 22%; }}
    h2 {{ font-size: 16px; }}

    /* Touch targets: 34px tabs and 21px legend chips were well under the
       ~44px a fingertip needs. */
    .tabs {{ padding: 4px; gap: 2px; }}
    .tab-btn {{ padding: 12px 14px; font-size: 13px; min-height: 44px; }}
    .legend {{ gap: 8px; }}
    .legend-item {{ padding: 9px 12px; min-height: 38px; display: inline-flex; align-items: center; }}
    .range-btn {{ padding: 11px 18px; min-height: 40px; font-size: 13px; }}
    .pill {{ padding: 10px 16px; min-height: 40px; }}
    .hbtn {{ height: 42px; padding: 0 11px; font-size: 12.5px; }}
    #theme-toggle, #patch-notes {{ padding: 0; }}
    .btn-long {{ display: none; }}
    .btn-short {{ display: inline; }}
    /* "Forget saved key" beside two half-width buttons overflowed the row,
       so it takes a line of its own above them. */
    .modal-actions {{ flex-wrap: wrap; }}
    .btn-link {{ width: 100%; margin: 0 0 4px; text-align: left; order: -1; padding: 8px 2px; }}
    /* Seven friends wrapped into three rows of pills and pushed the card
       itself most of a screen down. One scrollable row instead, bled to the
       screen edges so it reads as scrollable. */
    .friend-pills {{
      flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none;
      margin-left: -12px; margin-right: -12px; padding: 2px 12px;
    }}
    .friend-pills::-webkit-scrollbar {{ display: none; }}
    .pill {{ flex-shrink: 0; }}
    #to-top {{ right: 12px; bottom: 12px; }}
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
    .checkrow {{ min-height: 46px; }}
    /* A 15px-tall link is not a tap target. */
    .modal-link {{ min-height: 40px; padding: 10px 0; }}
    .btn-primary, .btn-ghost {{ height: 44px; flex: 1; }}
    .refresh-status {{ padding: 12px 14px; }}
  }}

  /* Very narrow phones */
  @media (max-width: 380px) {{
    .season-stats {{ grid-template-columns: 1fr; }}
    header.top h1 {{ font-size: 17px; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    * {{ animation: none !important; transition: none !important; }}
    html {{ scroll-behavior: auto !important; }}
  }}
</style>
</head>
<body>
  <a class="skip-link" href="#main">Skip to dashboard</a>
  <div class="wrap">
    <header class="top">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">{BRAND_MARK_SVG}</div>
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
        <button id="live-ranks" class="hbtn primary" type="button" title="Update everyone's rank and LP right now, using the key saved in this browser">⟳ <span class="btn-long">Refresh ranks</span><span class="btn-short">Refresh</span></button>
        <button id="live-key" class="hbtn" type="button" title="Enter or replace your Riot API key (development keys expire every 24h)">🔑 <span class="btn-long">API key</span><span class="btn-short">Key</span></button>
        <button id="refresh-data" class="hbtn hosted-only" type="button" hidden title="Re-fetch everyone's games from the Riot API">⟳ Refresh data</button>
        <button id="set-key" class="hbtn hosted-only" type="button" hidden title="Update the Riot API key stored on the server, used by Refresh data">🔑 Server key</button>
        <button id="export-csv" class="hbtn" type="button" title="Download this season's match data as a CSV">⬇ <span class="btn-long">Export CSV</span><span class="btn-short">CSV</span></button>
        {'<button id="patch-notes" class="hbtn" type="button" title="What&#39;s new on this dashboard" aria-label="What&#39;s new on this dashboard">✨<span class="note-dot" id="note-dot" hidden></span></button>' if notes_html else ""}
        <button id="theme-toggle" class="hbtn" type="button" aria-label="Toggle dark mode" title="Toggle dark mode">🌙</button>
      </div>
    </header>

    <div id="refresh-status" class="refresh-status" hidden>
      <div class="refresh-bar"><div class="refresh-bar-fill" id="refresh-bar-fill"></div></div>
      <div class="refresh-text" id="refresh-text">Starting…</div>
    </div>

    <div class="modal-backdrop" id="modal" hidden>
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <div class="modal-head">
          <div class="modal-icon" id="modal-icon" aria-hidden="true">⚡</div>
          <div>
            <h3 id="modal-title">Admin</h3>
            <p class="muted small" id="modal-blurb"></p>
          </div>
        </div>
        <label class="field" id="modal-pass-field"><span>Admin password</span>
          <input type="password" id="modal-pass" autocomplete="current-password"></label>
        <label class="field" id="modal-key-field"><span>Riot API key</span>
          <input type="text" id="modal-key" placeholder="RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" autocomplete="off" spellcheck="false"></label>
        <a class="modal-link" id="modal-getkey" href="https://developer.riotgames.com/"
           target="_blank" rel="noopener noreferrer" hidden>Get a free key at developer.riotgames.com<span class="ext" aria-hidden="true">↗</span></a>
        <label class="checkrow" id="modal-remember-row" hidden>
          <input type="checkbox" id="remember-key">
          <span>Remember this key in this browser</span>
        </label>
        <div class="modal-msg" id="modal-msg" role="status" aria-live="polite"></div>
        <div class="modal-actions">
          <button type="button" class="btn-link" id="modal-forget" hidden>Forget saved key</button>
          <button type="button" class="btn-ghost" id="modal-cancel">Cancel</button>
          <button type="button" class="btn-primary" id="modal-ok">Confirm</button>
        </div>
      </div>
    </div>

    {f'''<div class="modal-backdrop" id="notes-modal" data-latest="{esc(notes_latest)}" hidden>
      <div class="modal notes-modal" role="dialog" aria-modal="true" aria-labelledby="notes-title">
        <div class="modal-head">
          <div class="modal-icon" aria-hidden="true">✨</div>
          <div>
            <h3 id="notes-title">What&#39;s new</h3>
            <p class="muted small">Recent changes to this dashboard.</p>
          </div>
        </div>
        <div class="notes-body" tabindex="0">{notes_html}</div>
        <div class="modal-actions">
          <button type="button" class="btn-primary" id="notes-close">Close</button>
        </div>
      </div>
    </div>''' if notes_html else ""}

    {demo_banner}

    <main id="main" tabindex="-1">
    <div class="tabs" role="tablist" aria-label="Dashboard sections">
      <button class="tab-btn active" type="button" role="tab" id="tab-overview" aria-controls="panel-overview" aria-selected="true" tabindex="0" data-tab="overview">Overview</button>
      <button class="tab-btn" type="button" role="tab" id="tab-rank" aria-controls="panel-rank" aria-selected="false" tabindex="-1" data-tab="rank">Rank progress</button>
      {'<button class="tab-btn" type="button" role="tab" id="tab-duo" aria-controls="panel-duo" aria-selected="false" tabindex="-1" data-tab="duo">Duo synergy</button>' if duo_synergy_panel else ""}
      <button class="tab-btn" type="button" role="tab" id="tab-friends" aria-controls="panel-friends" aria-selected="false" tabindex="-1" data-tab="friends">Friends</button>
    </div>

    <section class="tab-panel" id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" tabindex="-1" data-tab-panel="overview">
      {awards_panel}
      {week_glance_panel}

      <div class="panel">
        <h2 style="margin-bottom:14px;">Ranked Solo/Duo leaderboard</h2>
        <p class="panel-hint">Click any row to open that player&rsquo;s full season.</p>
        <div class="table-scroll">
          <table class="leaderboard">
            <thead><tr><th class="num">#</th><th>Friend</th><th>Rank</th><th class="num">Winrate</th><th class="num">Record</th><th class="num">7-day trend</th></tr></thead>
            <tbody>{leaderboard_rows}</tbody>
          </table>
        </div>
      </div>
    </section>

    <section class="tab-panel" id="panel-rank" role="tabpanel" aria-labelledby="tab-rank" tabindex="-1" data-tab-panel="rank" hidden>
      {rank_chart_panel}
    </section>

    {f'<section class="tab-panel" id="panel-duo" role="tabpanel" aria-labelledby="tab-duo" tabindex="-1" data-tab-panel="duo" hidden>{duo_synergy_panel}</section>' if duo_synergy_panel else ""}

    <section class="tab-panel" id="panel-friends" role="tabpanel" aria-labelledby="tab-friends" tabindex="-1" data-tab-panel="friends" hidden>
      <div class="friend-pills" role="tablist" aria-label="Choose a player">{friend_pills}</div>
      {cards}
    </section>
    </main>

    <footer>
      <div class="footer-mark" aria-hidden="true">{BRAND_MARK_SVG}</div>
      Data via the Riot Games API. Not endorsed by Riot Games. Remake games (early
      surrender with no stat impact) are automatically excluded from every stat here.
      <div class="legend">
        <span><span class="sw" style="background:var(--good)"></span>Win</span>
        <span><span class="sw" style="background:var(--critical)"></span>Loss</span>
      </div>
    </footer>
  </div>

  <button id="to-top" type="button" title="Back to top" aria-label="Back to top">↑</button>

  <script type="application/json" id="season-export-data">{season_export_json}</script>
  <script type="application/json" id="live-refresh-data">{live_refresh_json}</script>

  <script>{LP_CHART_JS}</script>

  <script>
    // Riot key validation, shared by both dialog flows below.
    //
    // Checking only the RGAPI- prefix accepted a doubled paste: pasting a new
    // key into a box that still held the old one gives
    // "RGAPI-<old>RGAPI-<new>", which starts with RGAPI-, sails through, and
    // comes back from Riot as a 401 that reads like the new key was rejected.
    // A development key is RGAPI- plus a UUID, so check the whole shape and
    // say specifically what is wrong.
    window.RiotKey = {{
      RE: /^RGAPI-[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$/i,
      LEN: 42,
      // Keys arrive pasted out of a browser tab or a chat message, so strip
      // stray whitespace and wrapping quotes rather than failing on them.
      // A key is hex and hyphens, so dropping everything outside printable
      // ASCII cannot lose anything legitimate.
      clean: function (v) {{
        return String(v == null ? '' : v)
          .replace(/[^!-~]+/g, '')      // spaces, newlines, smart quotes
          .replace(/^["']+|["']+$/g, '');  // quotes wrapped round a pasted value
      }},
      problem: function (k) {{
        if (!k) return 'Paste your Riot API key first.';
        if (this.RE.test(k)) return null;
        if (k.indexOf('RGAPI-') !== 0) return 'A Riot key starts with RGAPI- — that one does not.';
        if (k.length > this.LEN) return 'That looks like two keys run together (' + k.length +
          ' characters, expected ' + this.LEN + '). Clear the box, then paste just the new key.';
        if (k.length < this.LEN) return 'That key is incomplete — ' + k.length +
          ' characters, expected ' + this.LEN + '. Copy the whole key from developer.riotgames.com.';
        return 'That is not a valid Riot key — expected RGAPI- followed by 36 characters.';
      }}
    }};
  </script>

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
    // Duo synergy: filter by player and re-order the cards. Everything is
    // already in the DOM, so this only hides and reorders.
    (function () {{
      var grid = document.querySelector('.duo-grid');
      if (!grid) return;
      var cards = [].slice.call(grid.querySelectorAll('.duo-card'));
      var empty = document.querySelector('.duo-empty');
      var who = '', sortBy = 'games';

      function num(card, key) {{ return parseFloat(card.getAttribute('data-' + key)) || 0; }}

      function apply() {{
        var shown = 0;
        cards.forEach(function (c) {{
          var match = !who || c.getAttribute('data-a') === who || c.getAttribute('data-b') === who;
          c.hidden = !match;
          if (match) shown++;
        }});
        var sorted = cards.slice().sort(function (a, b) {{
          // Ties break on games played, so the more trustworthy number wins
          // when two pairs share a winrate.
          var d = num(b, sortBy) - num(a, sortBy);
          return d !== 0 ? d : num(b, 'games') - num(a, 'games');
        }});
        sorted.forEach(function (c) {{ grid.appendChild(c); }});
        if (empty) empty.hidden = shown > 0;
      }}

      document.querySelectorAll('.duo-chip').forEach(function (b) {{
        b.addEventListener('click', function () {{
          who = b.getAttribute('data-who') || '';
          document.querySelectorAll('.duo-chip').forEach(function (o) {{
            o.classList.toggle('active', o === b);
          }});
          apply();
        }});
      }});

      document.querySelectorAll('.range-btn[data-sort]').forEach(function (b) {{
        b.addEventListener('click', function () {{
          sortBy = b.getAttribute('data-sort');
          document.querySelectorAll('.range-btn[data-sort]').forEach(function (o) {{
            o.classList.toggle('active', o === b);
          }});
          apply();
        }});
      }});
    }})();
  </script>

  <script>
    (function () {{
      // Zoom toggle: both ranges are already in the DOM, so this only swaps
      // which one is shown.
      // data-range only: the duo panel reuses .range-btn for its sort control.
      document.querySelectorAll('.range-btn[data-range]').forEach(function (b) {{
        b.addEventListener('click', function () {{
          var want = b.getAttribute('data-range');
          var panel = b.closest('.panel');
          panel.querySelectorAll('.range-btn').forEach(function (o) {{
            o.classList.toggle('active', o === b);
          }});
          panel.querySelectorAll('.chart-view').forEach(function (v) {{
            v.hidden = v.getAttribute('data-range') !== want;
          }});
        }});
      }});

      // Hover a legend name to bring that line forward and fade the rest.
      // Pure presentation — it changes no state, so it can't get out of sync
      // with the click-to-hide toggle below.
      document.querySelectorAll('.legend-item[data-idx]').forEach(function (el) {{
        var charts = (el.getAttribute('data-chart') || 'daily').split(' ');
        var idx = el.getAttribute('data-idx');
        function focus(on) {{
          charts.forEach(function (c) {{
            ['series', 'label'].forEach(function (kind) {{
              var g = document.getElementById(c + '-' + kind + '-' + idx);
              if (g) g.classList.toggle('focus-on', on);
            }});
            var svg = document.querySelector('svg.rank-chart g[id^="' + c + '-series-"]');
            svg = svg && svg.closest('svg');
            if (svg) svg.classList.toggle('has-focus', on);
          }});
        }}
        el.addEventListener('mouseenter', function () {{ focus(true); }});
        el.addEventListener('mouseleave', function () {{ focus(false); }});
      }});

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
    // ---- Live ranks -------------------------------------------------------
    // Updates everyone's rank/LP/record straight from Riot, in the viewer's
    // own browser, using a key they supply themselves. Riot's API permits
    // cross-origin calls, so this needs no server at all — which means it
    // works on the plain static build with no storage and no functions.
    //
    // The key never leaves this browser except to Riot: it is not sent to
    // this site's origin, not embedded in the page, and only kept in
    // localStorage if the viewer ticks the box. Everyone using their own key
    // also means the rate limit is spread across people rather than pooled
    // onto one.
    //
    // Only rank data is refreshed. Match history, highlights and the LP chart
    // come from the published snapshot, since rebuilding those needs the full
    // per-match fetch the generator does.
    (function () {{
      var cfgEl = document.getElementById('live-refresh-data');
      if (!cfgEl) return;
      if (window.LpChart) LpChart.init();
      var CFG = JSON.parse(cfgEl.textContent);
      var btn = document.getElementById('live-ranks');
      var keyBtn = document.getElementById('live-key');
      var modalForget = document.getElementById('modal-forget');
      function closeModal() {{
        modal.hidden = true;
        modalOk.onclick = null;
        modalGetKey.hidden = true;
        modalRememberRow.hidden = true;
        modalForget.hidden = true;
        modalOk.disabled = false;
        modalOk.textContent = 'Confirm';
        var opener = modal._opener;
        modal._opener = null;
        if (opener && opener.focus) {{ try {{ opener.focus(); }} catch (e) {{}} }}
      }}
      var statusBox = document.getElementById('refresh-status');
      var barFill = document.getElementById('refresh-bar-fill');
      var statusText = document.getElementById('refresh-text');
      var modal = document.getElementById('modal');
      var modalTitle = document.getElementById('modal-title');
      var modalBlurb = document.getElementById('modal-blurb');
      var modalPass = document.getElementById('modal-pass');
      var modalKey = document.getElementById('modal-key');
      var modalKeyField = document.getElementById('modal-key-field');
      var modalPassField = document.getElementById('modal-pass-field');
      var modalIcon = document.getElementById('modal-icon');
      var modalGetKey = document.getElementById('modal-getkey');
      var modalRememberRow = document.getElementById('modal-remember-row');
      var modalRemember = document.getElementById('remember-key');
      var modalMsg = document.getElementById('modal-msg');
      var modalOk = document.getElementById('modal-ok');
      var modalCancel = document.getElementById('modal-cancel');
      var KEY_STORE = 'league-dashboard/riot-key';

      // Riot's regional routing host, derived from the platform id.
      var ROUTING = {{
        euw1: 'europe', eun1: 'europe', tr1: 'europe', ru: 'europe', me1: 'europe',
        na1: 'americas', br1: 'americas', la1: 'americas', la2: 'americas',
        kr: 'asia', jp1: 'asia',
        oc1: 'sea', ph2: 'sea', sg2: 'sea', th2: 'sea', tw2: 'sea', vn2: 'sea'
      }};
      var platform = CFG.platform || 'euw1';
      var routing = ROUTING[platform] || 'europe';

      function say(msg, cls, pct) {{
        statusBox.hidden = false;
        statusText.textContent = msg;
        statusText.className = 'refresh-text' + (cls ? ' ' + cls : '');
        if (typeof pct === 'number') barFill.style.width = Math.max(0, Math.min(100, pct)) + '%';
      }}

      function riot(host, path, key) {{
        return fetch('https://' + host + '.api.riotgames.com' + path, {{
          headers: {{ 'X-Riot-Token': key }}
        }}).then(function (r) {{
          if (r.status === 401 || r.status === 403) {{
            var e = new Error('Riot rejected the key (' + r.status + ') — development keys expire ' +
                              'after 24 hours. Use the 🔑 API key button to paste a fresh one.');
            e.fatal = true; e.rejected = true; throw e;
          }}
          if (r.status === 429) {{
            var e2 = new Error('Riot rate limit reached. Wait a minute and try again.');
            e2.fatal = true; throw e2;
          }}
          if (r.status === 0) throw new Error('Could not reach Riot — check your connection.');
          if (r.status === 404) return null;
          if (!r.ok) throw new Error('Riot returned HTTP ' + r.status);
          return r.json();
        }});
      }}

      function rankText(e) {{
        if (!e || !e.tier) return 'Unranked';
        var tier = e.tier.charAt(0) + e.tier.slice(1).toLowerCase();
        if (CFG.apexTiers.indexOf(e.tier) !== -1) return tier + ' · ' + (e.leaguePoints || 0) + ' LP';
        return tier + ' ' + (e.rank || '') + ' · ' + (e.leaguePoints || 0) + ' LP';
      }}

      // ---- New games -----------------------------------------------------
      // Refreshing used to update ranks only, so the leaderboard moved while
      // the form dots and match list sat on the published snapshot. The
      // browser can fetch match detail itself; what it cannot do is rebuild
      // season totals or the LP chart, which need the whole season.
      // The card shows a 10-game window, so there is nothing to gain from
      // fetching more than 10 per player. The shared budget is what keeps a
      // seven-player refresh inside a development key's 100-calls-per-2-minutes:
      // worst case is 7x(1 account + 1 league + 2 id lists) + 45 = 73.
      var IDS_PER_QUEUE = 10;      // newest N ranked ids asked for, per queue
      var MAX_NEW_PER_FRIEND = 10; // one player cannot exceed the window anyway
      var matchBudget = 40;        // match-detail calls for the whole refresh
      var budgetSpent = false;

      function escapeHtml(v) {{
        return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {{
          return {{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[c];
        }});
      }}

      // "Aug 22, 11:09 PM" — the same shape the built page uses, so a live
      // row and a snapshot row are indistinguishable.
      var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      function whenText(m) {{
        if (!m.gameStartMs) return '\u2014';
        var d = new Date(m.gameStartMs);
        var h = d.getHours(), h12 = h % 12 || 12;
        return MONTHS[d.getMonth()] + ' ' + ('0' + d.getDate()).slice(-2) + ', ' +
               h12 + ':' + ('0' + d.getMinutes()).slice(-2) + ' ' + (h >= 12 ? 'PM' : 'AM');
      }}

      function championIcon(name) {{
        // The map is keyed by display name, but match-v5 already returns the
        // Data Dragon key, so fall through to the raw name.
        var slug = (CFG.championIcons || {{}})[name] || name;
        if (!CFG.ddragonVersion || !slug) {{
          return '<span class="champ-icon champ-icon-ph" style="width:20px;height:20px;"></span>';
        }}
        // &#39; rather than an escaped quote: this string passes through an
        // f-string and then a JS single-quoted literal, and one backslash
        // too few closes the literal early on 'hidden'. The entity needs none.
        return '<img src="https://ddragon.leagueoflegends.com/cdn/' + CFG.ddragonVersion +
               '/img/champion/' + encodeURIComponent(slug) + '.png" alt="" class="champ-icon" ' +
               'width="20" height="20" loading="lazy" onerror="this.style.visibility=&#39;hidden&#39;">';
      }}

      // Mirrors summarize_match() in fetch_data.py. Any drift here shows up as
      // a live row that disagrees with the same game after the next build.
      function summarizeMatch(match, puuid) {{
        var info = match && match.info;
        if (!info || !info.participants) return null;
        var me = null, i;
        for (i = 0; i < info.participants.length; i++) {{
          if (info.participants[i].puuid === puuid) {{ me = info.participants[i]; break; }}
        }}
        if (!me) return null;
        var deaths = me.deaths || 0;
        var cs = (me.totalMinionsKilled || 0) + (me.neutralMinionsKilled || 0);
        var mins = Math.max((info.gameDuration || 0) / 60, 1);
        var start = info.gameStartTimestamp || info.gameCreation || 0;
        var pos = me.teamPosition || null;
        var foe = null;
        if (pos) {{
          for (i = 0; i < info.participants.length; i++) {{
            var q = info.participants[i];
            if (q.teamPosition === pos && q.teamId !== me.teamId) {{ foe = q.championName; break; }}
          }}
        }}
        return {{
          matchId: match.metadata && match.metadata.matchId,
          // Riot ends a game early with no stat impact when someone fails to
          // connect; those must never count as a win, a loss or a game played.
          remake: !!me.gameEndedInEarlySurrender,
          champion: me.championName || 'Unknown',
          win: !!me.win,
          kills: me.kills || 0,
          deaths: deaths,
          assists: me.assists || 0,
          kda: Math.round(((me.kills || 0) + (me.assists || 0)) / Math.max(deaths, 1) * 100) / 100,
          csPerMin: Math.round(cs / mins * 10) / 10,
          queue: (CFG.queueNames || {{}})[String(info.queueId)] || ('Queue ' + info.queueId),
          gameStartMs: start,
          durationMin: Math.round(mins * 10) / 10
        }};
      }}

      function dotHtml(m) {{
        var title = whenText(m) + ' \u2014 ' + m.champion + ' \u2014 ' + (m.win ? 'Win' : 'Loss') +
                    ' \u2014 ' + m.kills + '/' + m.deaths + '/' + m.assists + ' KDA ' + m.kda;
        return '<span class="dot ' + (m.win ? 'win' : 'loss') + ' dot-new" title="' +
               escapeHtml(title) + '"></span>';
      }}

      function rowHtml(m) {{
        return '<tr class="row-new">' +
          '<td class="muted small">' + escapeHtml(whenText(m)) + '</td>' +
          '<td><span class="tag ' + (m.win ? 'win' : 'loss') + '">' +
            (m.win ? 'WIN' : 'LOSS') + '</span></td>' +
          '<td class="champ-cell">' + championIcon(m.champion) + escapeHtml(m.champion) + '</td>' +
          '<td class="num">' + m.kills + '/' + m.deaths + '/' + m.assists + '</td>' +
          '<td class="num">' + m.kda + '</td>' +
          '<td class="num">' + m.csPerMin + '</td>' +
          '<td class="muted">' + escapeHtml(m.queue) + '</td>' +
          '<td class="num muted">' + m.durationMin + 'm</td></tr>';
      }}

      function trim(container, selector, limit) {{
        if (!container) return;
        var kids = container.querySelectorAll(selector);
        for (var i = limit; i < kids.length; i++) kids[i].remove();
      }}

      function applyMatches(label, matches) {{
        var card = document.getElementById('friend-' + label.toLowerCase());
        if (!card || !matches.length) return 0;
        var dots = card.querySelector('[data-dots]');
        var rows = card.querySelector('[data-match-rows]');
        // Keep the window the snapshot used, so the card does not quietly grow
        // a longer form line every time somebody refreshes.
        var limit = Math.max(dots ? dots.querySelectorAll('.dot').length : 0, matches.length);
        if (dots && !dots.querySelector('.dot')) dots.innerHTML = '';  // drops "No recent games"
        // Oldest first at the front, so the newest ends up leftmost.
        matches.slice().reverse().forEach(function (m) {{
          if (dots) dots.insertAdjacentHTML('afterbegin', dotHtml(m));
          if (rows) rows.insertAdjacentHTML('afterbegin', rowHtml(m));
        }});
        trim(dots, '.dot', limit);
        trim(rows, 'tr', limit);
        // Counted back off the DOM rather than tracked in a variable, so the
        // label can never disagree with the dots it describes.
        var total = dots ? dots.querySelectorAll('.dot').length : 0;
        var wins = dots ? dots.querySelectorAll('.dot.win').length : 0;
        var lbl = card.querySelector('[data-form-label]');
        if (lbl) lbl.textContent = 'Form (last ' + total + ' games, ' + wins + 'W ' +
                                   (total - wins) + 'L)';
        var sum = card.querySelector('[data-match-summary]');
        if (sum && rows) sum.textContent = 'Recent match detail (' +
                                           rows.querySelectorAll('tr').length + ' games)';
        return matches.length;
      }}

      function refreshGames(f, puuid, key) {{
        var known = (CFG.knownMatches || {{}})[f.label] || [];
        var newestMs = (CFG.newestMatchMs || {{}})[f.label] || 0;
        // Riot's startTime is in whole seconds; +1 so the newest known game is
        // itself excluded rather than fetched again every refresh.
        var after = newestMs ? Math.floor(newestMs / 1000) + 1 : 0;
        var queues = CFG.rankedQueues || [420, 440];
        var ids = [];

        function nextQueue(qi) {{
          if (qi >= queues.length) return Promise.resolve();
          return riot(routing, '/lol/match/v5/matches/by-puuid/' + puuid + '/ids?queue=' +
                      queues[qi] + (after ? '&startTime=' + after : '') +
                      '&start=0&count=' + IDS_PER_QUEUE, key)
            .then(function (list) {{
              (list || []).forEach(function (id) {{
                if (ids.indexOf(id) < 0 && known.indexOf(id) < 0) ids.push(id);
              }});
              return nextQueue(qi + 1);
            }});
        }}

        return nextQueue(0).then(function () {{
          if (!ids.length) return [];
          // Newest first, so if the budget does run out it is the oldest of
          // the unseen games that get dropped, not the ones people care about.
          ids.sort(function (a, b) {{ return a < b ? 1 : (a > b ? -1 : 0); }});
          var room = Math.min(MAX_NEW_PER_FRIEND, matchBudget);
          if (ids.length > room) budgetSpent = true;
          var fresh = ids.slice(0, room);
          matchBudget -= fresh.length;
          var out = [];
          function nextMatch(i) {{
            if (i >= fresh.length) return Promise.resolve();
            return riot(routing, '/lol/match/v5/matches/' + fresh[i], key)
              .then(function (m) {{
                var row = summarizeMatch(m, puuid);
                if (row && !row.remake && row.gameStartMs > newestMs) out.push(row);
                return nextMatch(i + 1);
              }});
          }}
          return nextMatch(0).then(function () {{
            out.sort(function (a, b) {{ return b.gameStartMs - a.gameStartMs; }});
            applyMatches(f.label, out);
            return out;
          }});
        }});
      }}

      // Absolute ladder position, so Emerald IV 80 LP sorts above Emerald IV
      // 26 LP. Mirrors ladder_lp() in the generator.
      function ladderScore(entry) {{
        if (!entry || !entry.tier) return 0;
        var order = CFG.tierOrder || [];
        var ti = order.indexOf(entry.tier);
        if (ti < 0) ti = 0;
        var lp = entry.leaguePoints || 0;
        if ((CFG.apexTiers || []).indexOf(entry.tier) !== -1) return ti * 4 * 100 + lp;
        var division = (CFG.rankScore || {{}})[entry.rank] || 0;
        return (ti * 4 + division) * 100 + lp;
      }}

      // The table is ordered at build time, so after a refresh moves people
      // the rows still sit in their old positions with their new LP beside
      // them — #1 on 80 LP above #2 on 26 LP. Re-sort and renumber.
      function resortLeaderboard(live) {{
        var rows = [].slice.call(document.querySelectorAll('tr[data-friend-row]'));
        if (rows.length < 2) return;
        var body = rows[0].parentNode;
        rows.forEach(function (tr) {{
          var label = tr.getAttribute('data-friend-row');
          var l = live[label];
          // Anyone whose lookup failed keeps the position the build gave them.
          tr._score = l ? ladderScore(l) : ((CFG.baseScores || {{}})[label] || 0);
        }});
        rows.sort(function (a, b) {{ return b._score - a._score; }});
        rows.forEach(function (tr, i) {{
          body.appendChild(tr);
          var pos = tr.querySelector('.pos');
          if (pos) {{
            pos.textContent = i + 1;
            pos.className = i < 3 ? 'pos pos-' + (i + 1) : 'pos';
          }}
          // The friend card carries the same standing.
          var card = document.getElementById('friend-' + tr.getAttribute('data-friend-row').toLowerCase());
          var badge = card && card.querySelector('.rank-badge');
          if (badge) badge.textContent = '#' + (i + 1);
        }});
      }}

      function paint(label, entry) {{
        var row = document.querySelector('tr[data-friend-row="' + CSS.escape(label) + '"]');
        if (!row) return;
        var rankCell = row.querySelector('[data-cell="rank"]');
        var wrCell = row.querySelector('[data-cell="winrate"]');
        var recCell = row.querySelector('[data-cell="record"]');
        if (rankCell) {{
          var v = CFG.tierVars[entry && entry.tier] || '--tier-unranked';
          rankCell.style.color = 'var(' + v + ')';
          var icon = '';
          if (entry && entry.tier) {{
            var src = CFG.rankIconBase.replace('{{tier}}', entry.tier.toLowerCase());
            icon = '<img src="' + src + '" alt="" class="rank-icon" width="20" height="20" ' +
                   'onerror="this.style.visibility=\\'hidden\\'">';
          }}
          rankCell.innerHTML = icon + rankText(entry);
        }}
        var wins = (entry && entry.wins) || 0, losses = (entry && entry.losses) || 0;
        var total = wins + losses;
        if (wrCell) wrCell.textContent = total ? (Math.round(wins / total * 1000) / 10) + '%' : '—';
        if (recCell) recCell.textContent = wins + 'W / ' + losses + 'L';
        row.classList.add('row-live');
      }}

      function run(key) {{
        btn.disabled = true;
        keyBtn.disabled = true;
        var friends = CFG.friends || [];
        var done = 0, updated = 0, newGames = 0;
        // Per friend: the live rank reading plus whatever games came back, fed
        // to the chart at the end so it redraws once rather than seven times.
        var live = {{}};

        function step(i) {{
          if (i >= friends.length) {{
            resortLeaderboard(live);
            // The chart is rebuilt from the whole season, so it redraws once
            // here rather than per friend.
            var charted = 0;
            if (window.LpChart) {{
              try {{ charted = LpChart.rerender(live) || 0; }} catch (e) {{ charted = 0; }}
            }}
            var when = new Date().toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit' }});
            // Be explicit about what did and did not move: the season tiles and
            // the LP chart need the whole season, which the browser cannot
            // rebuild, so they stay on the published snapshot.
            say('Ranks updated for ' + updated + ' of ' + friends.length + ' friends' +
                (newGames ? ', ' + newGames + ' new game' + (newGames === 1 ? '' : 's') +
                            ' added to their Form and match lists' +
                            (budgetSpent ? ' (some older ones skipped to stay inside Riot’s ' +
                                           'rate limit — refresh again for the rest)' : '')
                          : ', no new games since the last build') +
                '. Live as of ' + when + '.' +
                (charted ? ' The LP chart has been redrawn with them.' : '') +
                ' Season totals and the champion breakdown still show the published ' +
                'snapshot.', 'done', 100);
            btn.disabled = false;
            keyBtn.disabled = false;
            return;
          }}
          var f = friends[i];
          say('Looking up ' + f.label + '… (' + (i + 1) + ' of ' + friends.length + ')',
              null, (i / friends.length) * 100);
          var hash = f.riotId.indexOf('#');
          var name = f.riotId.slice(0, hash), tag = f.riotId.slice(hash + 1);
          var puuid = null;
          riot(routing, '/riot/account/v1/accounts/by-riot-id/' +
                        encodeURIComponent(name) + '/' + encodeURIComponent(tag), key)
            .then(function (acct) {{
              if (!acct || !acct.puuid) return null;
              puuid = acct.puuid;
              return riot(platform, '/lol/league/v4/entries/by-puuid/' + puuid, key);
            }})
            .then(function (entries) {{
              if (entries) {{
                var solo = null;
                for (var n = 0; n < entries.length; n++) {{
                  if (entries[n].queueType === 'RANKED_SOLO_5x5') {{ solo = entries[n]; break; }}
                }}
                paint(f.label, solo);
                if (solo) {{
                  live[f.label] = {{ tier: solo.tier, rank: solo.rank,
                                     leaguePoints: solo.leaguePoints || 0, matches: [] }};
                }}
                updated++;
              }}
              if (!puuid) return [];
              say('Checking ' + f.label + '’s recent games… (' + (i + 1) + ' of ' +
                  friends.length + ')', null, ((i + 0.5) / friends.length) * 100);
              return refreshGames(f, puuid, key);
            }})
            .then(function (added) {{
              added = added || [];
              newGames += added.length;
              if (live[f.label]) live[f.label].matches = added;
              done++;
              step(i + 1);
            }})
            .catch(function (err) {{
              if (err.fatal) {{
                say(err.message, 'error');
                // A rejected key is not going to start working, so drop it.
                // Otherwise every later Refresh would fail the same way with
                // no hint that the saved key is the problem.
                if (err.rejected) forgetKey();
                btn.disabled = false;
                keyBtn.disabled = false;
                return;
              }}
              // A single friend failing shouldn't abandon the rest.
              done++;
              step(i + 1);
            }});
        }}
        step(0);
      }}

      // ---- Key handling, split from refreshing ---------------------------
      // One button used to do both, so every refresh stopped to ask for a key
      // even when one was already saved. The key lives on its own button now
      // and refreshing is a single click.
      //
      // sessionKey holds a key the user chose not to persist, so "don't
      // remember" means "this visit only" rather than "ask me again in ten
      // seconds".
      var sessionKey = '';

      function storedKey() {{
        try {{ return localStorage.getItem(KEY_STORE) || ''; }} catch (e) {{ return ''; }}
      }}
      function currentKey() {{ return sessionKey || storedKey(); }}
      function saveKey(key, remember) {{
        sessionKey = key;
        try {{
          if (remember) localStorage.setItem(KEY_STORE, key);
          else localStorage.removeItem(KEY_STORE);
        }} catch (e) {{ /* private mode — carry on without persisting */ }}
      }}
      function forgetKey() {{
        sessionKey = '';
        try {{ localStorage.removeItem(KEY_STORE); }} catch (e) {{}}
      }}

      function openKeyDialog(opts) {{
        var saved = currentKey();
        modal._opener = document.activeElement;
        modalIcon.textContent = opts.icon;
        modalTitle.textContent = opts.title;
        modalBlurb.textContent = opts.blurb;
        modalKeyField.style.display = '';
        modalPassField.style.display = 'none';
        modalKey.value = saved;
        modalGetKey.hidden = false;
        modalRememberRow.hidden = false;
        modalRemember.checked = true;
        modalForget.hidden = !storedKey();
        modalMsg.textContent = '';
        modalMsg.className = 'modal-msg';
        modalOk.textContent = opts.confirm;
        modal.hidden = false;
        setTimeout(function () {{ modalKey.focus(); modalKey.select(); }}, 30);

        modalOk.onclick = function () {{
          // Write the cleaned value back so the box shows exactly what will
          // be sent, rather than hiding a stray space or newline.
          var key = window.RiotKey.clean(modalKey.value);
          modalKey.value = key;
          var problem = window.RiotKey.problem(key);
          if (problem) {{
            modalMsg.textContent = problem;
            modalKey.focus();
            modalKey.select();
            return;
          }}
          opts.onKey(key, modalRemember.checked);
        }};
      }}

      modalForget.addEventListener('click', function () {{
        forgetKey();
        modalKey.value = '';
        modalForget.hidden = true;
        modalMsg.className = 'modal-msg ok';
        modalMsg.textContent = 'Saved key cleared from this browser.';
        modalKey.focus();
      }});

      // Refresh: use the saved key and go. Only ask if there is nothing saved.
      btn.addEventListener('click', function () {{
        var key = currentKey();
        if (key) {{ run(key); return; }}
        openKeyDialog({{
          icon: '⟳',
          title: 'Refresh ranks',
          blurb: 'This needs your own Riot API key. It is used straight from this browser and ' +
                 'is never sent to this site.',
          confirm: 'Save & refresh',
          onKey: function (key, remember) {{
            saveKey(key, remember);
            closeModal();
            run(key);
          }}
        }});
      }});

      // API key: set or replace the key, and check it before storing so an
      // expired one is caught here rather than half way through a refresh.
      keyBtn.addEventListener('click', function () {{
        openKeyDialog({{
          icon: '🔑',
          title: 'Riot API key',
          blurb: storedKey()
            ? 'A key is saved in this browser. Paste a new one to replace it — Riot development ' +
              'keys expire after 24 hours.'
            : 'Paste your own Riot API key. It stays in this browser, is never sent to this site, ' +
              'and expires after 24 hours.',
          confirm: 'Save key',
          onKey: function (key, remember) {{
            modalOk.disabled = true;
            modalMsg.className = 'modal-msg';
            modalMsg.textContent = 'Checking the key with Riot…';
            // A status lookup needs no account data, so this validates the key
            // without spending a call on anybody's match history.
            riot(platform, '/lol/status/v4/platform-data', key).then(function () {{
              saveKey(key, remember);
              modalOk.disabled = false;
              modalMsg.className = 'modal-msg ok';
              modalMsg.textContent = remember
                ? 'Key accepted and saved in this browser.'
                : 'Key accepted for this visit.';
              setTimeout(function () {{
                closeModal();
                say('Riot API key saved. Hit ⟳ Refresh ranks to update the leaderboard.', 'done', 0);
              }}, 900);
            }}).catch(function (err) {{
              modalOk.disabled = false;
              modalMsg.className = 'modal-msg';
              modalMsg.textContent = err.rejected
                ? 'Riot rejected that key. Development keys expire after 24 hours — generate a fresh one.'
                : ('Could not check the key: ' + err.message);
            }});
          }}
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
      var modalPassField = document.getElementById('modal-pass-field');
      var modalIcon = document.getElementById('modal-icon');
      var modalGetKey = document.getElementById('modal-getkey');
      var modalRememberRow = document.getElementById('modal-remember-row');
      var modalRemember = document.getElementById('remember-key');
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
        modal._opener = document.activeElement;
        modalIcon.textContent = opts.icon || '⚙';
        modalOk.textContent = opts.confirm || 'Confirm';
        modalTitle.textContent = opts.title;
        modalBlurb.textContent = opts.blurb;
        modalKeyField.style.display = opts.needsKey ? '' : 'none';
        // Replacing an expired key needs no password; spending Riot quota does.
        modalPassField.style.display = opts.needsPass ? '' : 'none';
        // Anywhere a key is asked for, offer the place to get one.
        modalGetKey.hidden = !opts.needsKey;
        modalRememberRow.hidden = true;
        modalMsg.textContent = '';
        modalMsg.className = 'modal-msg';
        modalPass.value = '';
        modalKey.value = '';
        modal.hidden = false;
        onConfirm = opts.onConfirm;
        setTimeout(function () {{
          var el = opts.needsPass ? modalPass : modalKey;
          el.focus();
          if (el === modalKey) el.select();
        }}, 30);
      }}
      function closeModal() {{
        modal.hidden = true;
        onConfirm = null;
        // The live-ranks flow (a separate block above) binds modalOk.onclick
        // directly. Escape used to leave that binding in place, so a later
        // hosted confirm would fire the stale live-ranks handler as well.
        modalOk.onclick = null;
        modalGetKey.hidden = true;
        modalRememberRow.hidden = true;
        modalOk.disabled = false;
        modalOk.textContent = 'Confirm';
        // Declared in the live-ranks script, which is a separate IIFE.
        var forget = document.getElementById('modal-forget');
        if (forget) forget.hidden = true;
        // Put focus back on whatever opened the dialog rather than dropping
        // it at the top of the document. Parked on the element because the
        // live-ranks script is a different IIFE with no shared scope.
        var opener = modal._opener;
        modal._opener = null;
        if (opener && opener.focus) {{ try {{ opener.focus(); }} catch (e) {{}} }}
      }}
      modalCancel.addEventListener('click', closeModal);
      modal.addEventListener('click', function (e) {{ if (e.target === modal) closeModal(); }});
      document.addEventListener('keydown', function (e) {{
        if (e.key === 'Escape' && !modal.hidden) closeModal();
        if (e.key === 'Enter' && !modal.hidden && e.target !== modalGetKey) modalOk.click();
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
          icon: '🔑', title: 'Update Riot API key',
          blurb: 'Riot development keys expire every 24 hours. Grab a fresh one from developer.riotgames.com and paste it here.',
          needsKey: true, needsPass: false,
          onConfirm: function () {{
            var key = window.RiotKey.clean(modalKey.value);
            modalKey.value = key;
            var problem = window.RiotKey.problem(key);
            if (problem) {{ modalMsg.textContent = problem; modalKey.focus(); modalKey.select(); return; }}
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
        // timeout on its own, but all of them together would not be. A very
        // active player can also have more new games than fit in a single
        // call — the server reports needsMore in that case, and the same
        // friend is retried (continuing:true, so the once-per-cycle cooldown
        // doesn't re-trigger) rather than moving on incomplete. Progress is
        // saved after every single call (server-side), so nothing is lost if
        // this session stops partway — clicking Refresh again later just
        // continues from wherever it left off, even a first-time sync of a
        // very high-volume account that needs more than one sitting.
        var SESSION_BUDGET_MS = 8 * 60 * 1000;
        var sessionStart = Date.now();

        function step(i, attempt) {{
          attempt = attempt || 1;
          if (i >= names.length) {{
            setStatus('Rebuilding the dashboard…', null, (total - 0.5) / total * 100);
            return post('finalize', {{}}).then(function (res) {{
              setStatus('Done — refreshed ' + res.friends + ' friends, ' + newGames +
                        ' new game' + (newGames === 1 ? '' : 's') + '. Reloading…', 'done', 100);
              setTimeout(function () {{ location.reload(); }}, 1400);
            }});
          }}
          var label = 'Fetching ' + names[i] + '… (' + (i + 1) + ' of ' + names.length + ')'
            + (attempt > 1 ? ' — lots of recent games, pass ' + attempt : '');
          setStatus(label, null, (i / total) * 100);
          return post('refresh', {{ index: i, continuing: attempt > 1 }}).then(function (res) {{
            newGames += (res && res.newMatches) || 0;
            if (res && res.needsMore) {{
              if (Date.now() - sessionStart > SESSION_BUDGET_MS) {{
                throw new Error(names[i] + ' has an unusually large backlog of new games (a first-time sync ' +
                  'of a very active player can take a while). Progress is saved — click Refresh again to continue.');
              }}
              return step(i, attempt + 1);
            }}
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
    // Patch notes. Deliberately its own dialog rather than the shared admin
    // one: that dialog carries key-entry state, and entangling the two is how
    // a stale handler ends up firing on the wrong confirm.
    (function () {{
      var btn = document.getElementById('patch-notes');
      var modal = document.getElementById('notes-modal');
      if (!btn || !modal) return;
      var dot = document.getElementById('note-dot');
      var closeBtn = document.getElementById('notes-close');
      var SEEN = 'league-dashboard/notes-seen';
      var latest = modal.getAttribute('data-latest') || '';

      function lastSeen() {{
        try {{ return localStorage.getItem(SEEN) || ''; }} catch (e) {{ return ''; }}
      }}
      function syncDot() {{ dot.hidden = lastSeen() === latest; }}

      function open() {{
        modal._opener = document.activeElement;
        modal.hidden = false;
        // Opening counts as reading: the dot is a nudge, not a task list.
        try {{ localStorage.setItem(SEEN, latest); }} catch (e) {{}}
        syncDot();
        setTimeout(function () {{ closeBtn.focus(); }}, 30);
      }}
      function close() {{
        modal.hidden = true;
        var opener = modal._opener;
        modal._opener = null;
        if (opener && opener.focus) {{ try {{ opener.focus(); }} catch (e) {{}} }}
      }}

      btn.addEventListener('click', open);
      closeBtn.addEventListener('click', close);
      modal.addEventListener('click', function (e) {{ if (e.target === modal) close(); }});
      document.addEventListener('keydown', function (e) {{
        if (e.key === 'Escape' && !modal.hidden) close();
      }});
      syncDot();
    }})();
  </script>

  <script>
    (function () {{
      var slice = function (n) {{ return Array.prototype.slice.call(n); }};
      var tabBtns   = slice(document.querySelectorAll('.tab-btn'));
      var tabPanels = slice(document.querySelectorAll('.tab-panel'));
      var pills     = slice(document.querySelectorAll('.pill[data-friend]'));
      var cards     = slice(document.querySelectorAll('.card[id^="friend-"]'));
      var tabNames    = tabBtns.map(function (b) {{ return b.getAttribute('data-tab'); }});
      var friendNames = pills.map(function (p) {{ return p.getAttribute('data-friend'); }});
      var syncing = false;

      function setSelected(btn, on) {{
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
        // Roving tabindex: the whole group is one tab stop and the arrow keys
        // move within it, which is what a tablist is expected to do.
        btn.tabIndex = on ? 0 : -1;
      }}

      function showTab(name) {{
        if (tabNames.indexOf(name) < 0) return false;
        tabBtns.forEach(function (b) {{ setSelected(b, b.getAttribute('data-tab') === name); }});
        tabPanels.forEach(function (p) {{ p.hidden = p.getAttribute('data-tab-panel') !== name; }});
        return true;
      }}

      function showFriend(label) {{
        if (friendNames.indexOf(label) < 0) return false;
        cards.forEach(function (c) {{ c.hidden = c.id !== 'friend-' + label; }});
        pills.forEach(function (p) {{ setSelected(p, p.getAttribute('data-friend') === label); }});
        return true;
      }}

      function activeOf(list, names) {{
        for (var i = 0; i < list.length; i++) {{
          if (list[i].classList.contains('active')) return names[i];
        }}
        return names[0];
      }}

      // ---- The address bar carries the current view ----------------------
      // This page exists to be pasted into a group chat, so "look at Rory's
      // season" has to survive being copied out of the bar and reopened, and
      // the Back button has to undo a tab switch rather than leave the site.
      function writeRoute(push) {{
        if (syncing) return;
        var tab = activeOf(tabBtns, tabNames);
        var friend = pills.length ? activeOf(pills, friendNames) : null;
        var hash = '#' + (tab === 'friends' && friend ? 'friends/' + friend : tab);
        if (hash === location.hash) return;
        try {{
          if (push) history.pushState(null, '', hash);
          else history.replaceState(null, '', hash);
        }} catch (e) {{
          location.hash = hash;  // history API is restricted on file:// URLs
        }}
      }}

      function applyRoute() {{
        var raw = (location.hash || '').replace(/^#/, '');
        if (!raw) return false;
        var parts = raw.split('/');
        var tab = parts[0], friend = parts[1];
        // Links shared before routing existed pointed at "#friend-name".
        if (raw.indexOf('friend-') === 0) {{ tab = 'friends'; friend = raw.slice(7); }}
        syncing = true;
        var ok = showTab(tab);
        if (ok && friend) showFriend(friend);
        syncing = false;
        return ok;
      }}

      function activate(show, value) {{
        if (show(value)) writeRoute(true);
      }}

      function keyNav(list, onPick) {{
        return function (e) {{
          var i = list.indexOf(e.currentTarget), n = -1;
          if (e.key === 'ArrowRight' || e.key === 'ArrowDown') n = (i + 1) % list.length;
          else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') n = (i - 1 + list.length) % list.length;
          else if (e.key === 'Home') n = 0;
          else if (e.key === 'End') n = list.length - 1;
          if (n < 0) return;
          e.preventDefault();
          onPick(list[n]);
          list[n].focus();
        }};
      }}

      tabBtns.forEach(function (b) {{
        var pick = function (el) {{ activate(showTab, el.getAttribute('data-tab')); }};
        b.addEventListener('click', function () {{ pick(b); }});
        b.addEventListener('keydown', keyNav(tabBtns, pick));
      }});

      pills.forEach(function (pl) {{
        var pick = function (el) {{ activate(showFriend, el.getAttribute('data-friend')); }};
        pl.addEventListener('click', function () {{ pick(pl); }});
        pl.addEventListener('keydown', keyNav(pills, pick));
      }});

      // Leaderboard rows open that player's card. The name stays a real link
      // so copy-link and open-in-new-tab keep working; the row around it is
      // just a bigger target for the same thing.
      function openFriend(label) {{
        showTab('friends');
        showFriend(label);
        writeRoute(true);
        window.scrollTo(0, 0);
        var card = document.getElementById('friend-' + label);
        if (card && card.focus) {{
          try {{ card.focus({{ preventScroll: true }}); }} catch (e) {{}}
        }}
      }}

      document.querySelectorAll('a[data-friend-link]').forEach(function (a) {{
        a.addEventListener('click', function (e) {{
          if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
          e.preventDefault();
          openFriend(a.getAttribute('data-friend-link'));
        }});
      }});

      document.querySelectorAll('tr[data-friend-row]').forEach(function (tr) {{
        tr.addEventListener('click', function (e) {{
          if (e.target.closest && e.target.closest('a')) return;  // the link handles itself
          var sel = window.getSelection && String(window.getSelection());
          if (sel) return;                                        // don't hijack text selection
          var a = tr.querySelector('a[data-friend-link]');
          if (a) openFriend(a.getAttribute('data-friend-link'));
        }});
      }});

      // Default to the top-ranked friend so the Friends panel is never blank,
      // then let the URL override it.
      if (pills.length) showFriend(friendNames[0]);
      applyRoute();
      window.addEventListener('hashchange', applyRoute);
      window.addEventListener('popstate', applyRoute);

      var skip = document.querySelector('.skip-link');
      if (skip) {{
        skip.addEventListener('click', function (e) {{
          // Move focus without writing "#main" into the address bar, which
          // would otherwise overwrite the current view's route.
          e.preventDefault();
          var m = document.getElementById('main');
          if (m) {{ m.focus(); m.scrollIntoView(); }}
        }});
      }}

      var toTop = document.getElementById('to-top');
      if (toTop) {{
        var pending = null;
        function syncToTop() {{
          var y = window.pageYOffset || document.documentElement.scrollTop || 0;
          toTop.classList.toggle('show', y > 520);
        }}
        // Trailing-edge throttle rather than requestAnimationFrame: rAF is
        // suspended in background tabs, and the last sample always lands.
        window.addEventListener('scroll', function () {{
          if (pending) return;
          pending = setTimeout(function () {{ pending = null; syncToTop(); }}, 100);
        }}, {{ passive: true }});
        syncToTop();
        toTop.addEventListener('click', function () {{
          try {{ window.scrollTo({{ top: 0, behavior: 'smooth' }}); }}
          catch (e) {{ window.scrollTo(0, 0); }}
        }});
      }}
    }})();
  </script>
</body>
</html>'''


def load_site_url():
    """Public URL of the deployed dashboard, from config.json.

    Only used for the Open Graph card, which needs absolute image URLs. Absent
    for a local-only dashboard, in which case the share tags are simply not
    emitted rather than pointing at something that will not resolve.
    """
    cfg = Path(__file__).with_name("config.json")
    if not cfg.exists():
        return ""
    try:
        return (json.loads(cfg.read_text(encoding="utf-8")).get("site_url") or "").strip()
    except Exception:
        return ""


def main():
    data_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data.json")
    out_path = Path(sys.argv[2] if len(sys.argv) > 2 else "dashboard.html")
    if not data_path.exists():
        print(f"Data file not found: {data_path}. Run fetch_data.py first (or use the bundled demo data.json).")
        sys.exit(1)
    data = json.loads(data_path.read_text(encoding="utf-8"))
    data.setdefault("siteUrl", load_site_url())
    out_path.write_text(build_html(data), encoding="utf-8")
    print(f"Wrote {out_path}")

    friends_sorted = sorted(data.get("friends", []),
                            key=lambda f: tier_score(f["ranked"].get("solo")), reverse=True)
    for name in write_share_assets(out_path.parent, friends_sorted,
                                   data.get("platform", "euw1"),
                                   data.get("generatedAt", "")):
        print(f"Wrote {out_path.parent / name}")


if __name__ == "__main__":
    main()
