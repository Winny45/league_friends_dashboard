#!/usr/bin/env python3
"""
generate_dashboard.py · reads data.json (produced by fetch_data.py, or the
bundled demo data) and renders a single self-contained dashboard.html you
can open in any browser.

Usage:
    python3 generate_dashboard.py [data.json] [dashboard.html]
"""
import html
import json
import math
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
# Taken from the mini crests the page draws beside the text, so a rank reads
# as one thing rather than two. The crest hex is in the middle of each pair;
# the light and dark values are that colour pushed toward black or white far
# enough to stay legible on the surface it sits on. Diamond was the one that
# was plainly wrong: its crest is violet (#8141EB) and the text was blue.
TIER_COLOR = {
    "IRON":        {"light": "#4a4244", "dark": "#a99ea0"},   # crest #51484A
    "BRONZE":      {"light": "#7e4833", "dark": "#d2896b"},   # crest #8C513A
    "SILVER":      {"light": "#5f757a", "dark": "#b4c8cc"},   # crest #80989D
    "GOLD":        {"light": "#96621f", "dark": "#e8a94f"},   # crest #CD8837
    "PLATINUM":    {"light": "#10809e", "dark": "#4fc6e8"},   # crest #25ACD6
    "EMERALD":     {"light": "#0f7a2c", "dark": "#2fcb5d"},   # crest #149C3A
    # Diamond and Master are both violet in game. Diamond keeps the bluer
    # half of that range and Master the redder, so the two stay apart in a
    # leaderboard even though the crests are close.
    "DIAMOND":     {"light": "#5b2ec4", "dark": "#9b6bf2"},   # crest #8141EB
    "MASTER":      {"light": "#7b2fbc", "dark": "#c77fea"},   # crest #9D48E0
    "GRANDMASTER": {"light": "#a83333", "dark": "#e87070"},   # crest #CD4545
    "CHALLENGER":  {"light": "#a87a22", "dark": "#f7d48f"},   # crest #F4C874
}
DEFAULT_TIER_COLOR = {"light": "#5a5d63", "dark": "#9aa0a8"}  # crest #63666B

# Separate from TIER_COLOR: this is a per-*friend* identity palette for the
# rank-progress chart, where each line needs its own distinguishable color
# regardless of what rank that friend happens to be. Fixed order, validated
# categorical hues — never reassign/cycle these per-render.
FRIEND_PALETTE = [
    # Deliberately no green and no red. Those two mean "won" and "lost"
    # everywhere else on the page, so a player whose identity colour was green
    # sat in a table row beside a green "+22 LP" and the colour stopped saying
    # which of the two it meant.
    #
    # Assigned by the order friends appear in config.json, not by rank, so a
    # player keeps their colour when the ladder moves under them.
    {"light": "#0e8ea6", "dark": "#2ec4de"},  # 0 Winny   cyan
    {"light": "#b83a68", "dark": "#e0699a"},  # 1 Shas     pink
    {"light": "#2a78d6", "dark": "#3987e5"},  # 2 Kirish   blue
    # Slot 3 sits next to slot 4 in every legend, so the two cannot both be
    # warm: orange beside copper reads as one colour at a glance. Rory is not
    # orange, so the warm slot is Brett's and slot 3 stays cool.
    {"light": "#4f7a95", "dark": "#8bb0c9"},  # 3 Rory     steel
    {"light": "#96522a", "dark": "#c4753c"},  # 4 Brett    copper
    {"light": "#5a49b8", "dark": "#9085e9"},  # 5 Neel     violet
    # Two accounts belonging to one person, so they are deliberately the same
    # hue: the pair should read as related rather than as two strangers who
    # happen to share the top of a leaderboard. They are five slots apart, so
    # they never sit adjacent in a legend where the likeness would confuse.
    {"light": "#c26e92", "dark": "#f2a9c6"},  # 6 Shas2nd  pale pink
    {"light": "#8a4fb0", "dark": "#b884d8"},  # 7 spare    orchid
]


def tier_var(tier):
    """CSS custom property name for a tier, e.g. 'DIAMOND' -> '--tier-diamond'."""
    return f"--tier-{(tier or 'unranked').lower()}"


def _rank_snapshot_key(h):
    return (h.get("tier"), h.get("rank"))


def snapshot_change_label(prev, curr):
    """What changed between two consecutive rank snapshots. Raw League
    Points only mean the same thing when tier and division haven't moved –
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
    if curr_score == prev_score:
        return None
    # Ladder position is linear at 100 LP per division, so the distance across
    # a promotion is a real LP count even though leaguePoints itself resets.
    # Saying only "promoted to Emerald IV, 35 LP" left out how far they moved.
    moved = ladder_lp(curr) - ladder_lp(prev)
    word = "Promoted" if curr_score > prev_score else "Demoted"
    # The rank itself is in the next column, so this says only how far. The
    # word leads, matching lp_step_label() in the game list.
    return f"{word} {'+' if moved >= 0 else '−'}{abs(moved)} LP"


def net_change_label(first, last, window=None):
    """Net movement across the whole visible window, for the small label
    under each line's end point. Same tier+division at both ends -> a plain
    net LP number; otherwise a compact 'was -> now' since raw LP isn't
    comparable across a promotion/demotion.

    `window` only names the period in the text, and defaults to naming
    nothing. It used to default to "30d", so a table whose own header already
    said which period it covered printed a contradictory suffix on the rows
    that happened to stay inside one division and no suffix at all on the rows
    that changed rank."""
    first_score, last_score = tier_score(first), tier_score(last)
    direction = 1 if last_score > first_score else (-1 if last_score < first_score else 0)
    if _rank_snapshot_key(first) == _rank_snapshot_key(last):
        delta = (last.get("leaguePoints") or 0) - (first.get("leaguePoints") or 0)
        if delta == 0:
            return None
        text = f"{'+' if delta >= 0 else ''}{delta} LP"
        return {"text": f"{text} ({window})" if window else text,
                "direction": direction, "lp": delta, "moved": False}
    first_short = rank_label(first).split(" &middot;")[0]
    last_short = rank_label(last).split(" &middot;")[0]
    moved_lp = ladder_lp(last) - ladder_lp(first)
    # A promotion resets leaguePoints, so the raw difference is meaningless
    # across one — but ladder position is linear (100 LP per division), so the
    # distance travelled is a real LP count even over a tier change. Callers
    # that want to show it read `lp`; `text` stays plain so the places that
    # escape it are unaffected.
    # `text` is the rank change alone and `lp` is the distance. Callers that
    # want both put them together; baking the figure into the text made the
    # week panel print it twice, once from the text and once from its own
    # highlighted span.
    return {"text": f"{first_short} → {last_short}",
            "direction": direction, "lp": moved_lp, "moved": True}


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


def tier_only_label(ranked_entry):
    """Tier and division, no LP. For sentences that name a rank rather than
    report a standing."""
    if not ranked_entry or not ranked_entry.get("tier"):
        return "Unranked"
    tier = ranked_entry["tier"].capitalize()
    if ranked_entry["tier"] in APEX_TIERS:
        return tier
    return f"{tier} {ranked_entry.get('rank', '')}".strip()


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
_ICON_CTX = {"version": None, "map": {}, "slugs": set(), "fold": {}}


def set_icon_context(version, icon_map):
    _ICON_CTX["version"] = version
    _ICON_CTX["map"] = icon_map or {}
    _ICON_CTX["slugs"] = set((icon_map or {}).values())
    _ICON_CTX["fold"] = {v.lower(): v for v in (icon_map or {}).values()}
    # Match data reports Data Dragon's key, so the page was printing
    # "MissFortune", "TahmKench" and "KSante". The icon map is keyed by the
    # real name, so inverting it gives the spelling a person would write.
    _ICON_CTX["display"] = {v: k for k, v in (icon_map or {}).items()}
    _ICON_CTX["displayFold"] = {v.lower(): k for k, v in (icon_map or {}).items()}


def champion_display(champion_name):
    """The champion's own name, from whatever the match data called it."""
    if not champion_name:
        return champion_name
    ctx = _ICON_CTX
    if champion_name in ctx.get("map", {}):
        return champion_name
    return (ctx.get("display", {}).get(champion_name)
            or ctx.get("displayFold", {}).get(champion_name.lower())
            or champion_name)


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
        # The map is keyed by display name ("K'Sante"), but match data reports
        # the Data Dragon key ("KSante"), so any champion whose name carries an
        # apostrophe or a space missed and rendered no icon at all. Accept a
        # name that is already a valid key.
        # Riot is not even consistent with its own keys: match data says
        # "FiddleSticks" where Data Dragon has "Fiddlesticks".
        slug = (champion_name if champion_name in _ICON_CTX["slugs"]
                else _ICON_CTX["fold"].get(champion_name.lower()))
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
    built · an ID with no tag, or a region none of the sites are mapped for."""
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


# ---------------------------------------------------------------------------
# Who played with whom
#
# Set once per render so the match renderers can mark a game as a duo without
# every caller having to thread the whole friends list through. Teammates are
# identified the same way the synergy panel does it: same match, same result.
# ---------------------------------------------------------------------------

_DUO_CTX = {"map": {}}


# A remake ends inside Riot's four minute window. Nothing else does: the
# earliest a real game can finish is a fifteen minute surrender, and the
# shortest real game in this data is six minutes.
REMAKE_MAX_MINUTES = 4.5


def mark_legacy_remakes(friends):
    """Flag remakes on records cached before the flag existed.

    fetch_data.py reads gameEndedInEarlySurrender and drops those games, but
    only for matches fetched since that was added · 2,396 of 2,565 here predate
    it and carry no such key, so 64 one and two minute games were counting as
    real games in every total, every champion record and every winrate.
    Duration is enough to tell: there is a clean gap between the three minute
    remakes and the six minute stomps.
    """
    fixed = 0
    for f in friends:
        for m in f.get("seasonMatches", []) + f.get("recentMatches", []):
            if "remake" in m:
                continue
            m["remake"] = (m.get("durationMin") or 99) < REMAKE_MAX_MINUTES
            fixed += 1 if m["remake"] else 0
    return fixed


def set_duo_context(friends_sorted, colour_order=None):
    """Duo lookups, and the one place a player's colour is decided.

    `colour_order` is the stable order colours are handed out in · the order
    the friends are listed in config.json. Handing them out by rank meant a
    promotion swapped two people's colours on every chart, table and tint.
    """
    order = colour_order or [f["label"] for f in friends_sorted]
    slot = {label: i for i, label in enumerate(order)}
    by_match = {}
    for f in friends_sorted:
        i = slot.get(f["label"], len(order))
        var = friend_var(min(i, len(FRIEND_PALETTE) - 1))
        for m in f.get("seasonMatches", []):
            if m.get("remake"):
                continue
            by_match.setdefault(m["matchId"], []).append((f["label"], var, bool(m["win"])))
        _DUO_CTX.setdefault("var", {})[f["label"]] = var
    duo = {}
    for mid, entries in by_match.items():
        if len(entries) < 2:
            continue
        for label, _var, win in entries:
            mates = [(l, v) for (l, v, w) in entries if l != label and w == win]
            if mates:
                duo[(mid, label)] = sorted(mates)
    _DUO_CTX["map"] = duo


def friend_colour(label):
    """The colour that belongs to a name, rather than to a position in a list.

    Looked up by label because the two places that need it count from
    different starting points: the chart drops anyone with no rank history,
    so its index and the friends list's index are not the same person once
    somebody is missing.
    """
    return (_DUO_CTX.get("var") or {}).get(label, "--accent")


def party_size(match_id, label):
    """How many tracked players were on this team, including this one."""
    return 1 + len(_DUO_CTX["map"].get((match_id, label)) or [])


def party_band(match_id, label, own_var):
    """A stripe made of the colours of everyone on that team.

    A single accent-coloured band said a game was shared but not with whom,
    which is the thing worth knowing when the two rows are next to each other.
    Hard stops rather than a blend, so each colour stays itself.
    """
    mates = _DUO_CTX["map"].get((match_id, label)) or []
    if not mates:
        return ""
    # One blended colour, not a stack of segments. Segments were built from
    # each row's own player outward, so the two rows of a game drew the same
    # colours in opposite order and the bar flipped halfway down. An average
    # is the same for every row of the game by construction, and gives the
    # pairing an identity of its own: Neel with Winny is one colour wherever
    # it appears.
    return f"--band: {blend_vars(sorted([own_var] + [v for _l, v in mates]))};"


def blend_vars(vars_):
    """Equal-weight mix of a set of CSS colour variables."""
    acc = f"var({vars_[0]})"
    for i, v in enumerate(vars_[1:], start=1):
        acc = f"color-mix(in srgb, {acc} {i / (i + 1) * 100:.0f}%, var({v}))"
    return acc


def render_duo_mates(match_id, label):
    """The other tracked players in this game, or a dash."""
    mates = _DUO_CTX["map"].get((match_id, label))
    if not mates:
        return '<span class="muted">&ndash;</span>'
    names = "".join(
        f'<span class="mate" style="color:var({v});">{esc(l)}</span>' for l, v in mates
    )
    who = ", ".join(l for l, _ in mates)
    return (f'<span class="duo-with" title="Played this game with {esc(who)}">'
            f'<span class="duo-with-icon" aria-hidden="true">\u21c4</span>{names}</span>')


_SIGNATURE_CACHE = {}


def signature_champion(friend):
    """The champion someone has played most this season.

    Not highest mastery, which is a lifetime score and can name a champion
    they have not touched all split, and not the weighted rating either: a
    face should be what you would actually see them on, which is the one they
    pick most, however it goes.
    """
    label = friend.get("label") or ""
    if label in _SIGNATURE_CACHE:
        return _SIGNATURE_CACHE[label]
    counts = {}
    for m in friend.get("seasonMatches", []):
        if m.get("remake"):
            continue
        c = m.get("champion")
        if c:
            counts[c] = counts.get(c, 0) + 1
    if counts:
        # Ties break on the name so a rebuild cannot silently reshuffle faces.
        champ = max(sorted(counts), key=lambda c: counts[c])
    else:
        mastery = friend.get("mastery") or []
        champ = mastery[0].get("championName") if mastery else None
    _SIGNATURE_CACHE[label] = champ
    return champ


def render_avatar(friend, size=34):
    """A friend's face on the page: their top champion.

    Falls back to their initial when there is no icon for it, so the slot is
    never empty and never a broken image.
    """
    champ = signature_champion(friend)
    url = champion_icon_url(champ) if champ else None
    initial = esc((friend.get("label") or "?")[:1].upper())
    if not url:
        return (f'<span class="avatar avatar-fallback" style="width:{size}px;height:{size}px;"'
                f' aria-hidden="true">{initial}</span>')
    # The picture is scaled past its frame and the frame clips it, so the
    # border Data Dragon draws inside every champion square is cropped away
    # rather than sitting there looking like a square in a circle.
    return (f'<span class="avatar-wrap" style="width:{size}px;height:{size}px;">'
            f'<img class="avatar" src="{esc(url)}" alt="" '
            f'loading="lazy" title="{esc(champion_display(champ))}" '
            f'onerror="this.classList.add(&#39;broken&#39;)"></span>')


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
    no internet · the champion name text next to it already carries the
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
LIVE_RANKED_QUEUES = [420, 440, 710]
LIVE_QUEUE_NAMES = {"420": "Ranked Solo/Duo", "440": "Ranked Flex", "710": "Ranked 5s"}

# The only queues allowed to reach a stat, a chart or a highlight. fetch_data
# filters on this already, both server-side in the id listing and again on the
# way out, so this is the third gate rather than the first. It is here because
# a wrong number on the page is the thing anyone actually notices, and because
# "is this counting something it should not?" is a question worth being able
# to answer by reading one line rather than by trusting three.
#
# Note what is not in it and cannot be: Teamfight Tactics is a separate game
# on a separate API (/tft/match/v1). Nothing in this project calls it, so a
# TFT game has no route into the data at all.
ALLOWED_QUEUES = frozenset(LIVE_QUEUE_NAMES.values())

# ranked-emblems-latest/ was removed from Community Dragon and every tier
# under it now 404s, which is why no card had an emblem. The mini crests are
# the supported path, and being SVG they are under 2 KB each rather than the
# 230 KB of the full emblem art, which matters when the page draws dozens of
# them at 16 to 34 pixels.
RANK_ICON_BASE = "https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-mini-crests/{tier}.svg"


def rank_icon_url(tier):
    # Community Dragon carries an unranked crest, so an unranked player gets
    # the same treatment as everyone else rather than an empty square.
    return RANK_ICON_BASE.format(tier=(tier or "unranked").lower())


def render_rank_icon(tier, size=20):
    # The crests are not drawn to a common scale: the tier ones sit inside a
    # 20x20 box with a margin around the artwork, while unranked fills a 16x16
    # box edge to edge, so at the same rendered size it came out noticeably
    # heavier than the rank beside it. Scaled back in CSS to match.
    url = rank_icon_url(tier)
    cls = "rank-icon" if tier else "rank-icon rank-icon-unranked"
    return (
        f'<img src="{esc(url)}" alt="" class="{cls}" width="{size}" height="{size}" '
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
        return "–"
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
        return date_key or "–"
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


POSITION_LABELS = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}
ROLE_VARS = {"Top": "--role-top", "Jungle": "--role-jungle", "Mid": "--role-mid",
             "ADC": "--role-adc", "Support": "--role-support"}


QUEUE_COLUMNS = (("Ranked Solo/Duo", "solo"), ("Ranked Flex", "flex"), ("Ranked 5s", "fives"))


def champion_breakdown(season_matches):
    """Per-champion games/wins/winrate/KDA for one friend's season, most-played
    first, split by queue so a total can be checked against a site that counts
    a different set of queues."""
    stats = {}
    for m in season_matches:
        s = stats.setdefault(m["champion"],
                             {"games": 0, "wins": 0, "solo": 0, "flex": 0, "fives": 0, "kdaSum": 0.0})
        s["games"] += 1
        s["kdaSum"] += match_kda(m)
        if m["win"]:
            s["wins"] += 1
        for name, key in QUEUE_COLUMNS:
            if m.get("queue") == name:
                s[key] += 1
    rows = [
        dict(s, champion=c, winrate=round(100 * s["wins"] / s["games"], 1),
             kda=round(s["kdaSum"] / s["games"], 2))
        for c, s in stats.items()
    ]
    rows.sort(key=lambda r: (-r["games"], -r["winrate"]))
    return rows


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
    lists · no extra API calls needed.

    Teammates are identified by matchId plus a matching result, not by
    teamId. League has no draws and a match has exactly two teams, so two
    players in the same game share a team if and only if they share an
    outcome · the two tests are equivalent. teamId is only present on records
    summarised after it was added to fetch_data.py, which is about 9% of the
    cache, and requiring it silently hid most of this panel: Brett and Winny
    showed 6 games together out of 130, and ten pairs did not appear at all.
    Checked against every record that does carry teamId: 48 of 48 agree.

    Solo/Duo only. A duo is a Solo/Duo idea: two people who chose each other
    out of a lobby of ten. In Flex the same two names on a team usually means
    a trio or a five man, so counting those as a pair credits the pairing with
    games three or five people played, and the stacks table already counts
    those as whole lineups."""
    by_match = {}
    for f in friends:
        for m in f.get("seasonMatches", []):
            if m.get("remake") or m.get("queue") != "Ranked Solo/Duo":
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
                    continue  # same lobby, opposite teams · not a duo
                key = tuple(sorted([fa["label"], fb["label"]]))
                stats = pair_stats.setdefault(key, {"total": {"games": 0, "wins": 0}})
                stats["total"]["games"] += 1
                if ma["win"]:
                    stats["total"]["wins"] += 1

    # Each player's own Solo/Duo winrate, so a pair's number can be read
    # against something. "66.7% together" means nothing until you know whether
    # those two usually win 45% or 60%.
    own = {}
    order = {}
    for i, f in enumerate(friends):
        order[f["label"]] = i
        pool = [m for m in f.get("seasonMatches", [])
                if not m.get("remake") and m.get("queue") == "Ranked Solo/Duo"]
        own[f["label"]] = ({"total": 100 * sum(1 for m in pool if m["win"]) / len(pool),
                            "games": len(pool)} if pool else {})

    def bucket_stats(a, b, st):
        games, wins = st["games"], st["wins"]
        if not games:
            return {"games": 0, "wins": 0, "losses": 0, "winrate": 0.0,
                    "baseline": None, "lift": None}
        winrate = round(100 * wins / games, 1)
        base = [own[x][q] for x in (a, b) for q in [st["_q"]] if q in own.get(x, {})]
        baseline = sum(base) / len(base) if base else None
        return {
            "games": games, "wins": wins, "losses": games - wins, "winrate": winrate,
            "baseline": round(baseline, 1) if baseline is not None else None,
            "lift": round(winrate - baseline, 1) if baseline is not None else None,
        }

    rows = []
    for (a, b), st in pair_stats.items():
        row = {"a": a, "b": b,
               "aVar": friend_var(min(order.get(a, 0), len(FRIEND_PALETTE) - 1)),
               "bVar": friend_var(min(order.get(b, 0), len(FRIEND_PALETTE) - 1))}
        st["total"]["_q"] = "total"
        row["total"] = bucket_stats(a, b, st["total"])
        rows.append(row)
    rows.sort(key=lambda r: (-r["total"]["games"], -r["total"]["winrate"]))
    # own[] feeds the matrix diagonal and the per-queue baselines.
    return {"rows": rows, "own": own, "players": [f["label"] for f in friends]}


def week_window(pts, cutoff):
    """The pair of snapshots that actually spans the last seven days.

    Keeping only snapshots inside the window measured whatever happened to
    fall in it, not the window: with readings on the 21st, 27th and 29th, a
    seven day trend from the 23rd compared the 27th against the 29th and
    called two days a week. Somebody who dropped fifty LP on the 24th showed
    as up, and somebody whose last two readings matched showed as nothing at
    all. The anchor is the last reading at or before the cutoff, which is what
    the rank actually was seven days ago.
    """
    if len(pts) < 2:
        return None
    before = [h for h in pts if h["date"] <= cutoff]
    start = before[-1] if before else pts[0]
    if start is pts[-1]:
        return None
    return start, pts[-1]


def weekly_trend_for(rank_history, label, now, queue="solo"):
    """Net movement over the last seven days for one friend and one queue –
    powers the ▲/▼ trend arrow on the leaderboard and on each card."""
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    pts = sorted(
        (h for h in rank_history if h.get("queue") == queue and h["label"] == label),
        key=lambda h: h["date"],
    )
    pair = week_window(pts, cutoff)
    # No suffix: every place this is shown already says the period, in a
    # column heading or a label beside it.
    return net_change_label(*pair) if pair else None


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
        pair = week_window(pts, cutoff)
        if not pair:
            continue
        delta = tier_score(pair[1]) - tier_score(pair[0])
        if delta <= 0:
            continue
        if best is None or delta > best["delta"]:
            net = net_change_label(*pair)
            best = {"label": label, "delta": delta,
                    "text": net["text"] if net else None,
                    "lp": net.get("lp") if net else None,
                    "moved": bool(net and net.get("moved")),
                    "fromLabel": tier_only_label(pair[0]),
                    "toLabel": tier_only_label(pair[1])}
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
    title = f"{when} · {champion_display(m['champion'])} · {'Win' if m['win'] else 'Loss'} · {m['kills']}/{m['deaths']}/{m['assists']} KDA {m['kda']}"
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


def render_match_row(m, friend_label=""):
    cls = "win" if m["win"] else "loss"
    label = "WIN" if m["win"] else "LOSS"
    # Same treatment as the game list on the Rank progress tab: a game shared
    # with somebody else is tinted with the pairing's own blended colour, so
    # the same duo looks the same on both pages. No grouping gap here, because
    # a card lists one player and its consecutive rows are always separate
    # games rather than the two halves of one.
    party = party_size(m.get("matchId"), friend_label)
    band = party_band(m.get("matchId"), friend_label, friend_colour(friend_label))
    row_attrs = ""
    if party > 1 and band:
        row_attrs = f' class="party party-{min(party, 5)}" style="{band}"'
    return f'''<tr{row_attrs}>
      <td class="muted small">{esc(format_match_when(m))}</td>
      <td><span class="tag {cls}">{label}</span></td>
      <td class="champ-cell"><span class="cc">{render_champion_icon(m["champion"])}{esc(champion_display(m["champion"]))}</span></td>
      <td class="with-cell">{render_duo_mates(m.get("matchId"), friend_label)}</td>
      <td class="num">{esc(m["kills"])}/{esc(m["deaths"])}/{esc(m["assists"])}</td>
      <td class="num">{esc(m["kda"])}</td>
      <td class="num">{esc(m["csPerMin"])}</td>
      <td class="muted">{esc(m.get("queue", ""))}</td>
      <td class="num muted">{esc(m.get("durationMin", ""))}m</td>
    </tr>'''


def render_peak_badge(current, peak):
    """Small 'Peak: X' note next to a rank row when the season peak is
    strictly better than the current rank · omitted otherwise (current
    rank already tells the whole story if it's the season high)."""
    if not peak or not peak.get("tier"):
        return ""
    if tier_score(peak) <= tier_score(current):
        return ""
    return f'<span class="muted small" style="margin-left:8px;">Peak: {rank_label(peak).replace("&middot;", "·")}</span>'


def render_fresh_badge(entry):
    """Flags a friend sitting at low LP in their current division · likely
    just landed there (promoted/demoted recently or on a fresh climb),
    worth a quick visual note. Not the same as the old 'promo series'
    concept, which modern ranked no longer has below Master."""
    if not entry or not entry.get("tier") or entry.get("leaguePoints") is None:
        return ""
    if entry["tier"] in APEX_TIERS:
        return ""
    if entry["leaguePoints"] <= 20:
        return '<span class="badge-fresh" title="Low LP in this division · recently promoted, demoted, or just starting the climb">Fresh</span>'
    return ""


def render_champion_breakdown(rows):
    if not rows:
        return '<div class="muted small">No ranked games this season.</div>'
    body = "".join(
        f'<tr><td class="champ-cell"><span class="cc">{render_champion_icon(r["champion"])}'
        f'{esc(champion_display(r["champion"]))}</span></td>'
        f'<td class="num">{r["games"]}</td>'
        f'<td class="num muted">{r["solo"] or "&ndash;"}</td>'
        f'<td class="num muted">{r["flex"] or "&ndash;"}</td>'
        f'<td class="num muted">{r["fives"] or "&ndash;"}</td>'
        f'<td class="num">{r["wins"]}W {r["games"] - r["wins"]}L</td>'
        f'<td class="num">{r["winrate"]}%</td>'
        f'<td class="num muted">{r["kda"]}</td></tr>'
        for r in rows
    )
    return f'''<table class="matches-table">
      <thead><tr><th>Champion</th><th class="num">Games</th><th class="num">Solo</th>
      <th class="num">Flex</th><th class="num">5s</th><th class="num">Record</th>
      <th class="num">Winrate</th><th class="num">KDA</th></tr></thead>
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


# ---------------------------------------------------------------------------
# Per-player analysis: lane matchups, a weighted champion rating built on top
# of them, and the LP a win and a loss are worth.
# ---------------------------------------------------------------------------

MATCHUP_MIN_GAMES = 5
CARRY_MIN_PX, CARRY_MAX_PX = 5.0, 13.0   # corner mark, smallest to widest gap
CARRY_MIN_GAP = 0.25                     # KDA difference below this is not a carry
# A champion somebody plays more than this often is not a counter pick, it is
# their champion: they were on it before the enemy locked in.
COUNTER_MAX_PICK_RATE = 10.0
# And a counter pick has to actually win. Sixty percent is the floor; clearing
# their own average by more than a run this short could manage is the test.
COUNTER_MIN_WINRATE = 60.0
# 15 games of the player's own average mixed into every champion's record.
# At 8 a two game 100% still beat a two hundred game main, which is the exact
# result the rating exists to avoid.
TOP_CHAMPION_PRIOR = 15
TOP_CHAMPION_VOLUME = 16.0  # most a champion can gain from being played a lot
TOP_CHAMPION_KDA = 6.0      # most it can gain or lose on KDA against their own average
# How far above or below their own average a champion's KDA has to be before
# that term is worth its full six points. The term used to reach full value
# only at double or half the account average, which nobody ever manages, so a
# six point term never moved past one point and the KDA barely counted. A
# third above average is a real difference and now scores like one.
TOP_CHAMPION_KDA_SPAN = 0.33
TOP_CHAMPION_MIN_GAMES = 10  # below this a champion is not a top champion
COUNTER_DISCOUNT = 0.5      # share of a counter pick's lift that is not credited


def duo_share(season_matches, label):
    """How much of somebody's Solo/Duo was played beside one of the others.

    Riot does not say who was premade, so this counts games where another
    tracked player was on the same team. A duo with somebody outside this
    group looks the same as playing alone from here, which is why the label
    says "with one of you" rather than "duo".
    """
    solo = [m for m in season_matches
            if m.get("queue") == "Ranked Solo/Duo" and not m.get("remake")]
    if not solo:
        return None
    with_mate = sum(1 for m in solo if _DUO_CTX["map"].get((m.get("matchId"), label)))
    return {"games": len(solo), "with": with_mate, "alone": len(solo) - with_mate,
            "withPct": round(100 * with_mate / len(solo)),
            "alonePct": round(100 * (len(solo) - with_mate) / len(solo))}


def overall_winrate(season_matches):
    played = [m for m in season_matches if not m.get("remake")]
    if not played:
        return None
    return 100 * sum(1 for m in played if m["win"]) / len(played)


def champion_matchups(season_matches, min_games=MATCHUP_MIN_GAMES):
    """Each champion this player has faced in their own lane often enough to
    mean something, split by the champion they were playing at the time.

    A matchup is a pair · Jinx into Caitlyn is not Jinx into Ashe · so the
    opposing champion alone would average away the thing being asked about.
    `opponentChampion` comes from the participant in the same teamPosition on
    the other team, so it is only present on games fetched since that field
    was added; the caller shows the count so a thin table is obviously thin
    rather than quietly wrong.
    """
    base = overall_winrate(season_matches)
    total = sum(1 for m in season_matches if not m.get("remake"))
    picks = {}
    for m in season_matches:
        if not m.get("remake"):
            picks[m["champion"]] = picks.get(m["champion"], 0) + 1
    pick_rate = {c: 100 * n / total for c, n in picks.items()} if total else {}

    pairs = {}
    for m in season_matches:
        if m.get("remake"):
            continue
        opp = m.get("opponentChampion")
        if not opp:
            continue
        key = (m["champion"], opp)
        st = pairs.setdefault(key, {"games": 0, "wins": 0, "kda": 0.0})
        st["games"] += 1
        st["wins"] += 1 if m["win"] else 0
        st["kda"] += match_kda(m)

    rows = []
    for (champ, opp), st in pairs.items():
        if st["games"] < min_games:
            continue
        wr = 100 * st["wins"] / st["games"]
        # Three tests, and it has to pass all of them. A champion played more
        # than a tenth of the time is that player's champion rather than an
        # answer to anything, so it can never be one however well it does. The
        # matchup has to win outright, not merely beat a losing average. And
        # the margin over their own winrate has to clear what a run this short
        # could produce on its own, which at five games is over twenty points.
        counter = False
        if base is not None and pick_rate.get(champ, 0) <= COUNTER_MAX_PICK_RATE:
            se = math.sqrt(base * (100 - base) / st["games"]) if 0 < base < 100 else 0.0
            counter = wr >= COUNTER_MIN_WINRATE and (wr - base) >= max(10.0, se)
        rows.append({
            "champion": champ, "opponent": opp,
            "games": st["games"], "wins": st["wins"], "losses": st["games"] - st["wins"],
            "winrate": round(wr, 1), "kda": round(st["kda"] / st["games"], 2),
            "counter": counter,
            "lift": round(wr - base, 1) if base is not None else None,
        })
    rows.sort(key=lambda r: (-r["games"], -r["winrate"]))
    return rows


def top_champions(season_matches, matchups, limit=5):
    """Champions ranked by a rating rather than by games or by winrate alone.

    Either number on its own picks the wrong champion: most games rewards a
    one-trick who loses on it, and highest winrate hands the top spot to
    somebody's 3-1 on a champion they have never played since. The rating is

        their own average winrate
      + how far this champion beats it, shrunk toward zero while the sample is
        small, and halved for the share of its games played in matchups it is
        already favoured in
      + up to six points for volume

    so a champion has to be both good and actually played to come out on top.
    """
    base = overall_winrate(season_matches)
    if base is None:
        return []
    rows = champion_breakdown([m for m in season_matches if not m.get("remake")])
    if not rows:
        return []
    max_games = max(r["games"] for r in rows)

    counter_games = {}
    for mu in matchups:
        if mu["counter"]:
            counter_games[mu["champion"]] = counter_games.get(mu["champion"], 0) + mu["games"]

    kda_total, kda_count = {}, {}
    for m in season_matches:
        if m.get("remake"):
            continue
        kda_total[m["champion"]] = kda_total.get(m["champion"], 0.0) + match_kda(m)
        kda_count[m["champion"]] = kda_count.get(m["champion"], 0) + 1

    # The account's own KDA, so a champion is judged against how this player
    # normally does rather than against an absolute.
    own_kda = (sum(kda_total.values()) / sum(kda_count.values())) if kda_count else 0.0

    out = []
    for r in rows:
        games, wr = r["games"], r["winrate"]
        confidence = games / (games + TOP_CHAMPION_PRIOR)
        counter_share = min(counter_games.get(r["champion"], 0) / games, 1.0)
        lift = (wr - base) * confidence * (1 - COUNTER_DISCOUNT * counter_share)
        volume = TOP_CHAMPION_VOLUME * math.log1p(games) / math.log1p(max_games)
        champ_kda = kda_total[r["champion"]] / kda_count[r["champion"]]
        # A champion they play better than they play in general is worth more
        # than one they merely win on. Shrunk by the same confidence as the
        # winrate lift, and capped so it can nudge an order rather than set it.
        kda_edge = 0.0
        if own_kda > 0:
            ratio = (champ_kda - own_kda) / own_kda / TOP_CHAMPION_KDA_SPAN
            kda_edge = max(-1.0, min(1.0, ratio)) * TOP_CHAMPION_KDA * confidence
        out.append(dict(
            r,
            rating=round(base + lift + volume + kda_edge, 1),
            lift=round(lift, 1),
            volume=round(volume, 1),
            kdaEdge=round(kda_edge, 1),
            counterShare=round(counter_share, 2),
            kda=round(champ_kda, 2),
        ))
    # A hard floor rather than a preference. Under ten games a winrate is a
    # story about one evening, and this used to relax the rule whenever it
    # could not fill five rows, which is exactly when the thin records were
    # least trustworthy. A short table is the honest answer.
    out = [r for r in out if r["games"] >= TOP_CHAMPION_MIN_GAMES]
    out.sort(key=lambda r: (-r["rating"], -r["games"]))
    return out[:limit]


LP_RATE_MIN_GAMES = 10   # below this the average is one bad night
LP_RATE_MIN_SIDE = 3     # and it needs both sides of the ledger
LP_RATE_RECENT = 20      # the "last N games" window


def queue_timeline(rank_history, label, queue_key, matches, queue_name):
    """One player's reconstructed per-game LP path for one queue."""
    pts = sorted((h for h in rank_history
                  if h.get("label") == label and h.get("queue") == queue_key),
                 key=lambda h: h["date"])
    played = [m for m in matches if m.get("queue") == queue_name and not m.get("remake")]
    if len(pts) < 2 or not played:
        return []
    return build_lp_timeline(pts, played)


def lp_rate(tl, window=None):
    """Average LP for a win and for a loss, read off the reconstructed path.

    The earlier version solved for one (gain, drop) pair across every gap at
    once by least squares, and it was wrong: it put Brett at 13.4 LP a loss
    where he actually loses about 19. One gap of his recorded four wins and no
    losses against +60 LP, which cannot be squared with the rest, dragged the
    whole answer.

    This reads the per-game steps the LP chart is already drawn from instead.
    Each gap is solved on its own, closest to a nominal 20 LP while still
    landing exactly on the next measured snapshot, so the answer always
    reproduces the LP that really moved: Brett's 20W 8L at 22.0 and 18.3 comes
    to +294, which is what his rank actually did. A gap that cannot be
    explained distorts only its own games rather than everybody's.
    """
    rows = [(bool(p["match"]["win"]), p["delta"] or 0) for p in tl[1:] if p["match"]]
    if window:
        rows = rows[-window:]
    gains = [d for w, d in rows if w]
    drops = [-d for w, d in rows if not w]
    if (len(rows) < LP_RATE_MIN_GAMES or len(gains) < LP_RATE_MIN_SIDE
            or len(drops) < LP_RATE_MIN_SIDE):
        return None
    gain, drop = sum(gains) / len(gains), sum(drops) / len(drops)
    return {"gain": round(gain, 1), "drop": round(drop, 1),
            "mmr": round(gain - drop, 1), "games": len(rows),
            "wins": len(gains), "losses": len(drops)}


# ---------------------------------------------------------------------------
# Ring charts. Two shares matter on a card and both are shares of a whole:
# which queue a game was played in, and which lane it was played from. A table
# of counts makes the reader do the division; a ring does not.
# ---------------------------------------------------------------------------

DONUT_VARS = ["--series-f0", "--series-f1", "--series-f2", "--series-f3",
              "--series-f4", "--series-f5", "--series-f6", "--series-f7"]


def render_donut(slices, centre, size=152, thickness=26):
    """One ring. Hovering a segment names it in the middle of the ring.

    A legend under a ring is a second copy of the same information taking up
    more room than the ring, and it makes the reader match colours by eye. The
    hole is already there and already empty, so the answer goes in it.
    """
    live = [sl for sl in slices if sl.get("value")]
    total = sum(sl["value"] for sl in live)
    if not total:
        return (f'<div class="donut"><div class="donut-empty">'
                f'<b>{esc(centre.replace(chr(10), " "))}</b>'
                f'<span class="muted small">Nothing recorded yet</span></div></div>')

    r = (size - thickness) / 2
    circ = 2 * math.pi * r
    arcs, offset = [], 0.0
    for i, sl in enumerate(live):
        frac = sl["value"] / total
        # Rounded before it is accumulated, so the offset of each segment is
        # the exact sum of the ones printed before it and the ring tiles with
        # no hairline between arcs.
        seg = round(frac * circ, 4)
        var = sl.get("var") or DONUT_VARS[i % len(DONUT_VARS)]
        arcs.append(
            f'<circle class="donut-arc" cx="{size / 2:.1f}" cy="{size / 2:.1f}" r="{r:.1f}" '
            f'fill="none" stroke="var({var})" stroke-width="{thickness}" '
            # The gap is a whole circumference, not "the rest of the circle".
            # A dash pattern repeats, and seg + (circ - seg) only equals circ
            # exactly if neither number was rounded; at two decimal places it
            # did not, so the pattern wrapped and painted a sliver of each
            # segment back over the start of the next one. A gap this long can
            # never come back round.
            f'stroke-dasharray="{seg:.4f} {circ:.4f}" stroke-dashoffset="{-offset:.4f}" '
            f'tabindex="0" role="img" data-label="{esc(sl["label"])}" '
            f'data-value="{sl["value"]}" data-pct="{frac * 100:.0f}%" '
            f'aria-label="{esc(sl["label"])}: {sl["value"]} of {total}, {frac * 100:.0f} percent">'
            f'</circle>'
        )
        offset += seg

    lines = centre.split(chr(10))
    dy = -0.1 if len(lines) > 1 else 0.35
    text = "".join(
        f'<tspan x="{size / 2:.1f}" dy="{dy if n == 0 else 1.15}em">{esc(l)}</tspan>'
        for n, l in enumerate(lines)
    )
    label = esc(centre.replace(chr(10), " "))
    return f'''<div class="donut" data-donut data-centre="{label}">
      <svg viewBox="0 0 {size} {size}" class="donut-svg">
        <g transform="rotate(-90 {size / 2:.1f} {size / 2:.1f})">{"".join(arcs)}</g>
        <text x="{size / 2:.1f}" y="{size / 2:.1f}" text-anchor="middle"
              class="donut-centre" data-donut-centre>{text}</text>
      </svg>
    </div>'''


def queue_mix(season_matches, label):
    """How a season splits across the ranked queues, with Solo/Duo divided by
    whether one of the others was on the team.

    Riot does not say who was premade, so "with one of you" means another
    tracked player was on the same side · a duo with somebody outside this
    group counts as alone from here.
    """
    played = [m for m in season_matches if not m.get("remake")]
    solo = [m for m in played if m.get("queue") == "Ranked Solo/Duo"]
    with_mate = sum(1 for m in solo if _DUO_CTX["map"].get((m.get("matchId"), label)))
    mix = [
        {"label": "Solo Queue", "value": len(solo) - with_mate, "var": "--q-solo"},
        {"label": "Duo Queue", "value": with_mate, "var": "--q-duo"},
        {"label": "Ranked Flex", "value": sum(1 for m in played if m.get("queue") == "Ranked Flex"),
         "var": "--q-flex"},
        {"label": "Ranked 5s", "value": sum(1 for m in played if m.get("queue") == "Ranked 5s"),
         "var": "--q-fives"},
    ]
    return mix, len(played)


def render_mastery_table(mastery):
    if not mastery:
        return '<div class="muted small">No mastery data.</div>'
    body = "".join(
        f'<tr><td class="champ-cell"><span class="cc">'
        f'{render_champion_icon(m["championName"], size=20)}{esc(champion_display(m["championName"]))}</span></td>'
        f'<td class="num">{m["points"]:,}</td>'
        f'<td class="num muted">M{esc(m["level"])}</td></tr>'
        for m in mastery
    )
    return (f'<table class="matches-table"><thead><tr><th>Champion</th>'
            f'<th class="num">Mastery</th><th class="num">Level</th></tr></thead>'
            f'<tbody>{body}</tbody></table>')


def render_rate_strip(rows):
    """LP a win is worth against LP a loss costs, per queue, two windows.

    MMR is the difference: positive means wins pay more than losses cost,
    which is what sitting above your hidden rating looks like.
    """
    def pair(r):
        if not r:
            return ('<td class="num muted" title="Not enough games in this window '
                    'to average">&ndash;</td><td class="num muted">&ndash;</td>')
        cls = "up" if r["mmr"] >= 0 else "down"
        return (f'<td class="num rate-pair">'
                f'<span class="up">+{r["gain"]}</span>'
                f'<span class="muted"> / </span>'
                f'<span class="down">&minus;{r["drop"]}</span></td>'
                f'<td class="num {cls}" title="Across {r["games"]} games, '
                f'{r["wins"]}W {r["losses"]}L">'
                f'{"+" if r["mmr"] >= 0 else "−"}{abs(r["mmr"]):.1f}</td>')

    body = "".join(
        f'<tr><td class="nowrap">{esc(q)}</td>{pair(season)}{pair(recent)}</tr>'
        for q, season, recent in rows
    )
    # Five columns, two of them a "+22.0 / -18.3" pair, in a card that is a
    # single phone-width column. It has to be able to scroll in place.
    return (f'<div class="table-scroll"><table class="matches-table rate-table">'
            f'<thead><tr><th>Queue</th><th class="num">Season LP</th><th class="num">MMR</th>'
            f'<th class="num">Last {LP_RATE_RECENT} LP</th><th class="num">MMR</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div>')


# A development key dies 24 hours after Riot issued it. Nothing here can know
# that moment, only when the key first worked, which is usually within minutes
# of it. Close enough to be worth showing, not close enough to state flatly.
DEV_KEY_HOURS = 24


def render_key_age(info):
    """A chip counting down a development key, or nothing at all.

    Shown because the single most common way this dashboard goes stale is a
    key quietly expiring overnight, and the first anyone knew was the numbers
    not moving.
    """
    if not info or not info.get("firstSeenMs"):
        return ""
    if info.get("permanent"):
        return '<span class="meta-chip">API key <b>does not expire</b></span>'
    added_ms = int(info["firstSeenMs"])
    expires_ms = added_ms + DEV_KEY_HOURS * 3600 * 1000
    # Both times are written as epochs and formatted in the browser. Baking a
    # formatted time in meant the builder's clock decided what the reader saw,
    # and the builder is a GitHub runner on UTC while the readers are on UK
    # time: a key added at 13:00 was printed as 12:00 to everybody.
    return (f'<span class="meta-chip key-age" data-key-added="{added_ms}" '
            f'data-key-expires="{expires_ms}" '
            f'title="Riot development keys last {DEV_KEY_HOURS} hours from when they were issued. '
            f'This counts from when the key was installed, which is usually a few minutes later, '
            f'so treat it as an estimate.">'
            f'API key added <b data-key-added-text>&ndash;</b>, <b data-key-left>&ndash;</b></span>')


def render_card_rank(entry, peak):
    """Current rank in the card's corner, with the season peak under it.

    The rank rows further down carry the winrate bars and both queues; this is
    the one number somebody scanning a card is looking for, so it sits where
    the eye lands first.
    """
    if not entry or not entry.get("tier"):
        now_html = ('<div class="cr-now" data-cr-now>'
                    '<div><b class="cr-tier">Unranked</b></div>'
                    '<span class="rank-icon rank-icon-ph" style="width:38px;height:38px;"></span>'
                    '</div>')
    else:
        var = tier_var(entry.get("tier"))
        now_html = (
            # Emblem on the outside edge of the card, past the text, so the
            # two crests line up down the right rather than sitting between
            # the words and the edge.
            f'<div class="cr-now" data-cr-now>'
            f'<div><b class="cr-tier" style="color:var({var});">'
            f'{rank_label(entry).split(" &middot;")[0]}</b>'
            f'<span class="cr-lp">{entry.get("leaguePoints", 0)} LP</span></div>'
            f'{render_rank_icon(entry.get("tier"), size=38)}</div>'
        )
    # Always rendered, even with no recorded peak, so a refresh that finds a
    # rank above anything on record has somewhere to put it.
    has_peak = bool(peak and peak.get("tier"))
    peak_html = (
        f'<div class="cr-peak" data-cr-peak data-peak-lp="{ladder_lp(peak) if has_peak else 0}"'
        f'{"" if has_peak else " hidden"}'
        f' title="Highest Solo/Duo rank recorded this season">'
        f'<span class="cr-peak-label">Peak</span>'
        f'<span>{rank_label(peak).split(" &middot;")[0] if has_peak else ""}</span>'
        f'<span class="cr-lp">{(peak or {}).get("leaguePoints", 0)} LP</span>'
        f'{render_rank_icon((peak or {}).get("tier"), size=20)}</div>'
    )
    return f'<div class="card-rank">{now_html}{peak_html}</div>'


def render_lp_rates(rates_solo, rates_flex, rates_solo_50, rates_flex_50, tracking_since):
    """The four LP readings, and an honest note about where they come from."""
    def cell(r):
        if not r:
            return '<td class="num muted" title="Not enough snapshots to solve for this">&ndash;</td>'
        cls = "up" if r["mmr"] >= 0 else "down"
        return (f'<td class="num {cls}" title="+{r["gain"]} LP a win, &minus;{r["drop"]} LP a loss, '
                f'fitted across {r["segments"]} gaps covering {r["games"]} games and reproducing '
                f'them to within {r["residual"]} LP a game">'
                f'{"+" if r["mmr"] >= 0 else "−"}{abs(r["mmr"]):.1f}'
                f'<span class="rate-detail">+{r["gain"]} / &minus;{r["drop"]}</span></td>')

    return f'''
    <table class="matches-table rate-table">
      <thead><tr><th>Queue</th><th class="num">Since tracking began</th>
      <th class="num">Last 50 games</th></tr></thead>
      <tbody>
        <tr><td>Solo/Duo</td>{cell(rates_solo)}{cell(rates_solo_50)}</tr>
        <tr><td>Flex</td>{cell(rates_flex)}{cell(rates_flex_50)}</tr>
      </tbody>
    </table>
    <p class="muted small" style="margin:8px 0 2px;">A positive number means wins are worth more
    than losses cost, which is what climbing looks like. Riot never reports the LP change for one
    game, so this is solved from the rank snapshots: each gap between two of them gives one
    equation, wins &times; gain &minus; losses &times; drop = the LP that actually moved, and the
    two figures are fitted across every gap.</p>
    <p class="muted small" style="margin:6px 0 2px;">A dash means the snapshots do not support an
    answer, which is the usual case so far: it takes {LP_RATE_MIN_SEGMENTS} usable gaps and
    {LP_RATE_MIN_GAMES} games, both figures have to land inside the range a ranked game can be
    worth, and the fit has to reproduce the gaps it came from to within
    {LP_RATE_MAX_RESIDUAL:.0f} LP a game. A gap where nothing moved across real games, or one
    moving more per game than a game can be worth, is thrown out rather than averaged in.
    Snapshots only start on {esc(tracking_since)}, so this covers that window and not the whole
    season, and it sharpens as more days are recorded.</p>'''


def render_top_champions(rows):
    if not rows:
        return '<div class="muted small">No ranked games this season.</div>'
    body = "".join(
        f'<tr><td class="num muted small">{n}</td>'
        f'<td class="champ-cell"><span class="cc">{render_champion_icon(r["champion"], size=20)}'
        f'{esc(champion_display(r["champion"]))}</span></td>'
        f'<td class="num"><b>{r["rating"]}</b></td>'
        f'<td class="num">{r["games"]}</td>'
        f'<td class="num">{r["winrate"]}%</td>'
        f'<td class="num muted">{r["kda"]}</td></tr>'
        for n, r in enumerate(rows, start=1)
    )
    return f'''<table class="matches-table">
      <thead><tr><th class="num">#</th><th>Champion</th><th class="num">Rating</th>
      <th class="num">Games</th><th class="num">Winrate</th><th class="num">KDA</th></tr></thead>
      <tbody>{body}</tbody>
    </table>'''


def render_matchups(rows, covered, total):
    """Lane matchups, and how much of the season the answer is based on."""
    coverage = ""
    if not rows:
        return (f'<div class="muted small">Nothing yet with {MATCHUP_MIN_GAMES} or more games. '
                f'Lane opponents are recorded on {covered} of {total} games.</div>')
    body = "".join(
        f'<tr><td class="champ-cell"><span class="cc">{render_champion_icon(r["champion"], size=20)}{esc(champion_display(r["champion"]))}'
        f'<span class="muted"> vs </span>{render_champion_icon(r["opponent"], size=20)}{esc(champion_display(r["opponent"]))}'
        f'{" <span class=\'counter-tag\'>counter pick</span>" if r["counter"] else ""}</span></td>'
        f'<td class="num">{r["games"]}</td>'
        f'<td class="num muted">{r["wins"]}W {r["losses"]}L</td>'
        f'<td class="num"><b>{r["winrate"]}%</b></td>'
        f'<td class="num muted">{r["kda"]}</td></tr>'
        for r in rows
    )
    return coverage + f'''<table class="matches-table">
      <thead><tr><th>Matchup</th><th class="num">Games</th><th class="num">Record</th>
      <th class="num">Winrate</th><th class="num">KDA</th></tr></thead>
      <tbody>{body}</tbody>
    </table>'''


def queue_rows_for(f):
    """Every ranked queue Riot reports for this account, in a fixed order.

    Solo/Duo and Flex are named because they always exist; anything else Riot
    returns is passed through under whatever it calls itself rather than being
    dropped, which is what used to happen to every queue that was not one of
    those two.
    """
    ranked = dict(f.get("ranked") or {})
    # A data.json written before the queueType was mapped carries Riot's own
    # name for the 5s ladder, so both are accepted and neither needs a re-fetch.
    for raw in ("RANKED_PREMADE_5x5", "RANKED_TEAM_5x5"):
        if raw in ranked and not ranked.get("fives"):
            ranked["fives"] = ranked.pop(raw)
        ranked.pop(raw, None)
    # Each bar is the colour its queue has in the ring above it.
    known = [("solo", "Ranked Solo / Duo", "--q-solo", "S"),
             ("flex", "Ranked Flex", "--q-flex", "F"),
             ("fives", "Ranked 5s", "--q-fives", "5")]
    rows, seen = [], set()
    for key, label, colour, tag in known:
        rows.append({"key": key, "label": label, "colour": colour, "tag": tag,
                     "entry": ranked.get(key)})
        seen.add(key)
    for key, entry in sorted(ranked.items()):
        if key in seen or not isinstance(entry, dict) or not entry.get("tier"):
            continue
        rows.append({"key": key, "label": key.replace("_", " ").title(),
                     "colour": "--series-4", "tag": key[:1].upper(), "entry": entry})
    return rows


def render_friend_card(f, rank_position, now, rank_history=(), tracking_since=""):
    ranked = f.get("ranked") or {}
    solo, flex = ranked.get("solo"), ranked.get("flex")
    solo_var = tier_var((solo or {}).get("tier"))
    matches = [m for m in f.get("recentMatches", []) if not m.get("remake")]
    season_matches = [m for m in f.get("seasonMatches", f.get("recentMatches", []))
                      if not m.get("remake")]
    wins = sum(1 for m in matches if m["win"])
    losses = len(matches) - wins
    dots = "".join(render_match_dot(m) for m in matches) or '<span class="muted">No recent games</span>'
    match_rows = "".join(render_match_row(m, f["label"]) for m in matches)

    weekly_min, weekly_games = weekly_playtime(season_matches, now)
    busiest_date, busiest_count = busiest_day(season_matches)
    busiest_label = format_day_label(busiest_date) if busiest_date else "–"
    season_games = len(season_matches)
    season_hours = format_minutes(sum(m.get("durationMin", 0) for m in season_matches))

    peak_rank = f.get("peakRank", {}) or {}

    champ_rows = champion_breakdown(season_matches)
    champion_pool = len(champ_rows)
    role_rows = role_breakdown(season_matches)
    matchups = champion_matchups(season_matches)
    matchup_covered = sum(1 for m in season_matches if m.get("opponentChampion"))
    top_champs = top_champions(season_matches, matchups)

    # LP a win is worth and LP a loss costs, read off the same reconstructed
    # path the LP chart is drawn from, per queue and over two windows.
    rate_rows = []
    for qr in queue_rows_for(f):
        queue_name = {"solo": "Ranked Solo/Duo", "flex": "Ranked Flex",
                      "fives": "Ranked 5s"}.get(qr["key"])
        if not queue_name:
            continue
        tl = queue_timeline(rank_history, f["label"], qr["key"], season_matches, queue_name)
        rate_rows.append((qr["label"], lp_rate(tl), lp_rate(tl, window=LP_RATE_RECENT)))

    mix, mix_total = queue_mix(season_matches, f["label"])
    role_slices = [{"label": r["role"], "value": r["games"], "var": ROLE_VARS.get(r["role"])}
                   for r in role_rows]

    signature = signature_champion(f)
    splash = champion_splash_url(signature)
    card_art = (
        f'<div class="card-art" aria-hidden="true"><img src="{esc(splash)}" alt="" '
        f'loading="lazy" decoding="async" onerror="this.parentElement.remove()"></div>'
    ) if splash else ""

    # One arrow per queue, so the header says at a glance which ladders moved
    # this week and which way.
    # Solo/Duo only. It is the ladder the rest of the page is about, and a
    # row of arrows covering three queues at once was read as one number.
    trends = render_trend_arrows(
        weekly_trend_for(rank_history, f["label"], now, queue="solo"), "Ranked Solo/Duo")

    played_by_queue = {}
    for m in season_matches:
        played_by_queue.setdefault(m.get("queue"), []).append(m)

    def queue_row(qr):
        entry = dict(qr["entry"] or {})
        # Riot has no ranked entry for every queue it runs, and one that is
        # unranked still has a record worth showing, so the season's own games
        # fill in the wins and losses when the ladder does not.
        if not entry.get("wins") and not entry.get("losses"):
            name = {"solo": "Ranked Solo/Duo", "flex": "Ranked Flex",
                    "fives": "Ranked 5s"}.get(qr["key"])
            pool = played_by_queue.get(name, [])
            if pool:
                w = sum(1 for m in pool if m["win"])
                entry.update(wins=w, losses=len(pool) - w,
                             winrate=round(100 * w / len(pool), 1))
        var = tier_var(entry.get("tier"))
        wr = entry.get("winrate")
        live = ' data-rank-row="solo"' if qr["key"] == "solo" else ""
        cell = ' data-cell="rank"' if qr["key"] == "solo" else ""
        wrcell = ' data-cell="wr-text"' if qr["key"] == "solo" else ""
        return f'''<div class="q-row"{live}>
          <div class="q-name">{esc(qr["label"])}
            <span class="q-rank rank-cell"{cell} style="color:var({var});">
              {render_rank_icon(entry.get("tier"), size=18)}{rank_label(entry if entry.get("tier") else None)}</span>
          </div>
          {winrate_bar(wr, f"var({qr['colour']})")}
          <span class="q-wr"{wrcell}>{esc(wr) + "%" if wr is not None else "–"}
            <span class="muted">({esc(entry.get("wins", 0))}W / {esc(entry.get("losses", 0))}L)</span></span>
        </div>'''

    form_net = ""
    tl_solo = queue_timeline(rank_history, f["label"], "solo", season_matches, "Ranked Solo/Duo")
    if len(tl_solo) > 1:
        recent = [p for p in tl_solo[1:] if p["match"]][-len(matches):]
        if recent:
            moved = sum(p["delta"] or 0 for p in recent)
            form_net = (f'<span class="form-net {"up" if moved >= 0 else "down"}">'
                        f'{"+" if moved >= 0 else "−"}{abs(moved):.0f} LP</span>')

    return f'''
    <section class="card" id="friend-{f["label"].lower()}" tabindex="-1"
             aria-label="{esc(f["label"])}"
             style="--card-tier: var({solo_var});">
      {card_art}
      <header class="card-head">
        <div class="rank-crest">
          {render_avatar(f, size=52)}
          <span class="rank-badge">#{rank_position}</span>
        </div>
        <div class="card-id">
          <h2>{esc(f["label"])}</h2>
          <div class="muted small">{esc(f["riotId"])} &middot; Level {esc(f.get("summonerLevel", "?"))}</div>
          {render_profile_links(f.get("riotId", ""))}
        </div>
        <div class="card-trend">
          <span class="muted small">7 day trend</span>
          <span class="tr-row">{trends}</span>
        </div>
        {render_card_rank(solo, peak_rank.get("solo"))}
      </header>

      <div class="card-mid">
        <div class="card-queues">
          {"".join(queue_row(qr) for qr in queue_rows_for(f))}
          <div class="form-line">
            <span class="section-label" data-form-label>Last {len(matches)} games ({wins}W {losses}L)</span>
            <span class="dots" data-dots>{dots}</span>
            {form_net}
          </div>
        </div>
        <div class="card-rings">
          {render_donut(mix, f"Game\ntypes")}
          {render_donut(role_slices, "Roles\nplayed")}
        </div>
      </div>

      <div class="season-stats season-stats-row">
        <div class="stat-tile">
          <div class="stat-value">{season_games}</div>
          <div class="stat-label">Games this season ({season_hours})</div>
        </div>
        <div class="stat-tile">
          <div class="stat-value">{champion_pool}</div>
          <div class="stat-label">Champions played this season</div>
        </div>
        <div class="stat-tile">
          <div class="stat-value">{weekly_games}</div>
          <div class="stat-label">Games this week ({format_minutes(weekly_min)})</div>
        </div>
        <div class="stat-tile">
          <div class="stat-value">{busiest_count if busiest_date else "–"}</div>
          <div class="stat-label">{f"games played on {busiest_label}" if busiest_date else "Busiest day"}</div>
        </div>
      </div>

      <div class="card-lower">
        <div class="cl-block cl-wide">
          <div class="section-label">Top champions
            <span class="label-note" title="Rating = {esc(f["label"])}&#39;s winrate across every game ({(overall_winrate(season_matches) or 0):.1f}%), plus how far this champion beats it, plus up to {TOP_CHAMPION_VOLUME:.0f} points for volume, plus or minus up to {TOP_CHAMPION_KDA:.0f} for KDA.&#10;&#10;The lift is multiplied by games / (games + {TOP_CHAMPION_PRIOR}), so a 3 game 100% counts for a fraction of what a 300 game record does, and halved again for the share of its games played in matchups it already wins more often than usual.&#10;&#10;KDA compares this champion&#39;s average against {esc(f["label"])}&#39;s own across every game; {TOP_CHAMPION_KDA_SPAN * 100:.0f}% above or below scores the full {TOP_CHAMPION_KDA:.0f} points, shrunk by the same confidence as the lift.&#10;&#10;Volume = {TOP_CHAMPION_VOLUME:.0f} x log(1 + games) / log(1 + most played).&#10;&#10;Champions with fewer than {TOP_CHAMPION_MIN_GAMES} games are not eligible.">weighted</span></div>
          {render_top_champions(top_champs)}
        </div>
        <div class="cl-block">
          <div class="section-label">Highest mastery</div>
          {render_mastery_table(f.get("mastery", []))}
        </div>
      </div>

      <div class="section-label">LP per win and per loss
        <span class="label-note">MMR is the difference</span></div>
      {render_rate_strip(rate_rows)}

      <details class="matches-details">
        <summary data-match-summary>Most Recent Games</summary>
        <table class="matches-table">
          <thead><tr><th>When</th><th>Result</th><th>Champion</th><th>With</th><th>K/D/A</th><th>KDA</th><th>CS/min</th><th>Queue</th><th>Length</th></tr></thead>
          <tbody data-match-rows>{match_rows}</tbody>
        </table>
      </details>

      <details class="matches-details">
        <summary>Champion Pool</summary>
        {render_champion_breakdown(champ_rows)}
      </details>

      <details class="matches-details">
        <summary>Champion Matchups</summary>
        {render_matchups(matchups, matchup_covered, len(season_matches))}
      </details>
    </section>'''


def render_trend_arrows(trend, label="", tag=""):
    """Which way a rank moved this week, then how far.

    Three states and nothing else: a green up arrow for LP gained, a red down
    arrow for LP lost, a grey dash for nothing recorded. Only once that is
    settled does the size decide the count · one arrow to 50 LP, two to 100,
    three beyond. The old hollow triangle for "no movement" was the problem:
    it is still an arrow shape, so a card with two queues and no movement in
    either read as two upward arrows.
    """
    chip = f'<span class="tr-tag">{esc(tag)}</span>' if tag else ""
    if not trend or not trend.get("direction"):
        return (f'<span class="tr-group" title="{esc(label)}: nothing recorded">'
                f'{chip}<span class="tr-none">&ndash;</span></span>')
    lp = abs(trend.get("lp") or 0)
    count = 1 if lp <= 50 else (2 if lp <= 100 else 3)
    up = trend["direction"] > 0
    glyph = "&#9650;" if up else "&#9660;"
    cls = "tr-up" if up else "tr-down"
    text = trend["text"]
    if trend.get("moved") and trend.get("lp") is not None:
        text = f"{'+' if trend['lp'] >= 0 else '−'}{abs(trend['lp'])} LP, {text}"
    return (f'<span class="tr-group" title="{esc(label)}: {esc(text)}">{chip}'
            + f'<span class="{cls}">{glyph}</span>' * count + '</span>')


def render_trend_arrow(trend, compact=False):
    """▲/▼/– since 7 days ago, for the leaderboard. `trend` is a
    net_change_label()-style dict (direction + text) or None if there's
    not enough history yet to compare.

    `compact` drops the text and keeps the glyph, for the row of arrows in
    a card header where there is room for a symbol and a tooltip but not a
    sentence."""
    if not trend:
        return ('<span class="tr-flat" title="No movement recorded">&#9651;</span>'
                if compact else '<span class="muted small">–</span>')
    # A rank change alone says a division moved but not how far, so the LP
    # travelled goes in front of it. Within a division the text already is an
    # LP figure.
    text = trend["text"]
    if trend.get("moved") and trend.get("lp") is not None:
        lp = trend["lp"]
        text = f"{'+' if lp >= 0 else '−'}{abs(lp)} LP, {text}"
    if compact:
        if trend["direction"] > 0:
            return f'<span class="tr-up" title="{esc(text)}">&#9650;</span>'
        if trend["direction"] < 0:
            return f'<span class="tr-down" title="{esc(text)}">&#9660;</span>'
        return f'<span class="tr-flat" title="{esc(text)}">&#9651;</span>'
    if trend["direction"] > 0:
        return f'<span class="small" style="color:var(--good);">▲ {esc(text)}</span>'
    if trend["direction"] < 0:
        return f'<span class="small" style="color:var(--critical);">▼ {esc(text)}</span>'
    return '<span class="muted small">–</span>'


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
      <td class="lb-name">{render_avatar(f, size=24)}<a href="#friends/{f["label"].lower()}" data-friend-link="{f["label"].lower()}">{esc(f["label"])}</a></td>
      <td class="rank-cell" data-cell="rank" style="color:var({var});font-weight:600;">{render_rank_icon((solo or {}).get("tier"))}{rank_label(solo)}</td>
      <td class="num" data-cell="winrate">{esc(wr) + '%' if wr is not None else '–'}</td>
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
    line ends at the same x. Here they don't · someone with 12 games ends a
    third of the way across · so labels landed in the middle of the plot,
    on top of the lines and each other. Placing them all at a common
    `gutter_x` means the vertical declutter below is sufficient on its own,
    and a leader line keeps each label tied to the point it describes.

    Passing gutter_x=None keeps the old line-end anchoring, which is right
    when every series really does end together.
    """
    label_groups = []
    MIN_LABEL_GAP = 25   # name plus its movement line
    ICON_SIZE = 14
    label_entries.sort(key=lambda e: e["ly"])
    for idx, e in enumerate(label_entries):
        e["draw_y"] = e["ly"] if idx == 0 else max(e["ly"], label_entries[idx - 1]["draw_y"] + MIN_LABEL_GAP)
    for e in label_entries:
        var, lx, ly, draw_y = e["var"], e["lx"], e["ly"], e["draw_y"]
        anchor_x = gutter_x if gutter_x is not None else lx
        # No leader line back to the point. Seven dashed diagonals crossing
        # the plot were more clutter than the labels they were tying down, and
        # the label already carries the line's colour and its rank emblem.
        parts = []
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
            parts.append(
                f'<text x="{text_x:.1f}" y="{draw_y + 14:.1f}" font-size="9.5" '
                f'fill="var(--muted)">{esc(e["net"]["text"])}</text>'
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
    """How to describe one game's move.

    `delta` is measured in ladder position, which is linear at 100 LP per
    division, so it stays a real LP count across a promotion even though
    League Points themselves reset. Saying only "promoted" left out the one
    number the column exists to show.
    """
    # Every step between two snapshots is reconstructed, so tagging almost all
    # of them "(est.)" said nothing and cluttered the column.
    amount = f"{'+' if delta >= 0 else '−'}{abs(delta):.0f} LP"
    if ladder_decompose(prev_value)[:2] != ladder_decompose(value)[:2]:
        return f"{'Promoted' if delta >= 0 else 'Demoted'} {amount}"
    return amount


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

    Games played *before* the first snapshot are skipped · there's no known LP
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


# The projection uses MINSTD rather than random.random() for one reason: the
# same walk has to come out of the JavaScript port, and 16807 is the largest
# multiplier whose product stays inside a double's exact integer range, so
# both languages agree bit for bit.
PROJECTION_WINDOW = 50


def projection_params(tl, window=PROJECTION_WINDOW):
    """Winrate, average LP won and average LP lost over recent games.

    None when there is nothing to extrapolate from: a player who has only won,
    or only lost, gives no figure for the other half of the walk.
    """
    rows = [(bool(p["match"]["win"]), p["delta"] or 0) for p in tl[1:] if p["match"]][-window:]
    if not rows:
        return None
    gains = [d for w, d in rows if w]
    drops = [-d for w, d in rows if not w]
    if not gains or not drops:
        return None
    return len(gains) / len(rows), sum(gains) / len(gains), sum(drops) / len(drops)


def project_scores(start, n, p_win, gain, drop, seed):
    """Where a run of `n` more games lands, one game at a time.

    A straight line to the expected finish would read as a promise, and it is
    not one. The point of the line is roughly where this ends up, and the
    shape is a reminder that it gets there through wins and losses. Seeded per
    player so the same page always draws the same walk.
    """
    state = (seed * 104729) % 2147483646 + 1
    out, score = [], start
    for _ in range(n):
        state = (state * 16807) % 2147483647
        score = score + gain if state / 2147483647.0 < p_win else score - drop
        score = max(score, 0.0)
        out.append(score)
    return out


TIER_BAND_ALPHA = 9   # percent of the tier colour mixed into the plot


def tier_bands(y_min, y_max, x0, x1, to_y, span=None):
    """A wash of each tier's own colour behind the plot.

    A grid of identical lines says where a division is but not which one, so
    reading a chart meant tracking back to the axis. A band per tier gives the
    plot a background that is already the answer.

    `span` is how much of the y axis one tier covers, and the two charts do
    not agree on it: the LP chart plots ladder position, four divisions of a
    hundred LP, while the daily chart plots tier_score, which is a thousand a
    tier. Assuming the first put the daily chart's bands in the wrong places
    entirely.
    """
    span = span or (DIVISIONS_PER_TIER * LP_PER_DIVISION)
    out = []
    first = int(y_min // span)
    last = int(y_max // span)
    for ti in range(max(first, 0), last + 1):
        if ti >= len(TIER_ORDER):
            break
        lo = max(ti * span, y_min)
        hi = min((ti + 1) * span, y_max)
        if hi <= lo:
            continue
        top, bottom = to_y(hi), to_y(lo)
        out.append(
            f'<rect class="tier-band" x="{x0:.1f}" y="{top:.1f}" width="{x1 - x0:.1f}" '
            f'height="{bottom - top:.1f}" fill="color-mix(in srgb, '
            f'var({tier_var(TIER_ORDER[ti])}) {TIER_BAND_ALPHA}%, transparent)" />'
        )
    return "".join(out)


def render_chart_stats(standings):
    """Where everyone stands, under the chart rather than above it.

    Chips above the plot pushed the chart itself below the fold and repeated
    the names the key already gives. A table reads down a column instead, so
    the four numbers can be compared between players at a glance.
    """
    rows = "".join(
        f'<tr><td class="cs-name"><span class="sw" style="background:var({s["var"]});"></span>'
        f'<b style="color:var({s["var"]});">{esc(s["label"])}</b></td>'
        f'<td class="nowrap">{render_rank_icon(s["tier"], size=18)}{s["rankLabel"]}</td>'
        f'<td class="num">{s["games"]}</td>'
        f'<td class="num {"up" if s["lp"] >= 0 else "down"}">'
        f'{"+" if s["lp"] >= 0 else "−"}{abs(s["lp"]):.0f}</td>'
        f'<td class="num">{s["winrate"]}%</td>'
        f'<td class="num muted">{esc(s["record"])}</td></tr>'
        for s in standings
    )
    return (
        '<table class="chart-stats"><thead><tr><th>Player</th><th>Rank now</th>'
        '<th class="num">Games</th><th class="num">LP</th><th class="num">Winrate</th>'
        '<th class="num">W&ndash;L</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )


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
        from zero · a zoom on the busy right-hand end. It's per friend rather
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
        # Everyone extended to the game count of whoever has played most, at
        # their own recent winrate and their own average LP per win and per
        # loss. The zoomed view rebases every line to the same length, so
        # there is nothing to extend there.
        proj = {}
        if not tail:
            for pi, pf in enumerate(chart_friends):
                pv = view[pf["label"]]
                left = max_games - (len(pv) - 1)
                if left <= 0:
                    continue
                params = projection_params(timelines[pf["label"]])
                if not params:
                    continue
                proj[pf["label"]] = project_scores(pv[-1]["score"], left, *params, seed=pi + 1)
        vis_scores = [p["score"] for v in view.values() for p in v]
        vis_scores += [sc for walk in proj.values() for sc in walk]
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
            # No right-hand gutter any more: the names live in the legend
            # under the chart, which was already there, so stacking them beside
            # the lines as well was the same key printed twice. The 175 units
            # it used to reserve go back to the plot.
            PAD_L, PAD_R, PAD_T, PAD_B = 64, 24, 16, 34
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
                y_ticks.append((xy(0, tick)[1], TIER_ORDER[ti].capitalize(), True))
            elif show_divisions:
                y_ticks.append((xy(0, tick)[1], rank_by_score.get(division, ""), False))

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
            var = friend_colour(f["label"])
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
                    title = (f"{f['label']} · game {p.get('origIdx', p['idx'])} · {'Win' if m['win'] else 'Loss'} on {champion_display(m['champion'])} · "
                             f"{move} → {score_to_rank_label(p['score'])}").replace("&middot;", "·")
                else:
                    title = (f"{f['label']} · tracking started · "
                             f"{score_to_rank_label(p['score'])}").replace("&middot;", "·")
                # Only where each line ends. Marking every game, or even every
                # measured snapshot, scattered dots across seven lines and made
                # the chart harder to read than the lines alone. The rest stay
                # as invisible hit targets so any game can still be hovered for
                # its tooltip, and the hover rule brings the point out.
                fill = f"var({var})"
                last = n == len(tl) - 1
                if last:
                    r = 3.5 if compact else 4
                    extra = ' stroke="var(--surface-1)" stroke-width="1.5"'
                    cls = "pt end"
                else:
                    r = 3
                    extra = ""
                    cls = "pt"
                parts.append(
                    f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}"'
                    f'{extra}><title>{esc(title)}</title></circle>'
                )
            walk = proj.get(f["label"])
            if walk:
                walk_xy = [coords[-1]] + [xy(len(tl) - 1 + k + 1, sc) for k, sc in enumerate(walk)]
                walk_d = " ".join(
                    f"{'M' if n == 0 else 'L'}{x:.1f},{y:.1f}" for n, (x, y) in enumerate(walk_xy)
                )
                walk_title = (f"{f['label']} · projected · {len(walk)} more games at their current "
                              f"form → {score_to_rank_label(walk[-1])}").replace("&middot;", "·")
                parts.append(
                    f'<path class="proj" d="{walk_d}" fill="none" stroke="var({var})" '
                    f'stroke-width="1.5" stroke-dasharray="5 5" stroke-linecap="round" '
                    f'opacity="0.45"><title>{esc(walk_title)}</title></path>'
                )
            series_groups.append(f'<g id="{prefix}-series-{i}">{"".join(parts)}</g>')

            if False:  # gutter labels removed; the legend is the key
                lx, ly = coords[-1]
                # Just the name. The movement underneath it was a second line
                # per friend, fourteen lines of text down the side of the
                # chart, and it was coloured green or red — the same green and
                # red the palette uses for two of the friends, so the colour
                # stopped identifying anyone. The movement lives in the
                # standings chip above the chart instead.
                if tail and len(tl) > 1:
                    d = tl[-1]["score"] - tl[0]["score"]
                    net = {"text": f"{'+' if d >= 0 else '−'}{abs(d):.0f} LP over {len(tl) - 1}"}
                else:
                    n0 = net_labels[i]
                    txt = n0["text"] if n0 else ""
                    if n0 and n0.get("moved") and n0.get("lp") is not None:
                        lp0 = n0["lp"]
                        txt = f"{'+' if lp0 >= 0 else '−'}{abs(lp0)} LP, {txt}"
                    net = {"text": txt} if txt else None
                label_entries.append({"idx": i, "var": var, "label": f["label"], "lx": lx, "ly": ly,
                                      "net": net, "tier": tiers[i]})

        # Labels sit in the reserved right gutter, not at each line's own end:
        # lines finish at different x (someone with 12 games ends a third of
        # the way across), which put labels on top of the plot and each other.
        label_groups = []

        # Tier boundaries carry weight; the divisions between them are
        # reference, not structure. Drawing all of them at the same strength
        # put ten equal lines behind the data.
        bands_svg = tier_bands(y_min, y_max, PAD_L, W - PAD_R, lambda v: xy(0, v)[1])
        grid_svg = "".join(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
            f'class="chart-grid{"" if tier else " faint"}" />'
            f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end" '
            f'class="chart-tick{"" if tier else " faint"}">{esc(label)}</text>'
            for y, label, tier in y_ticks
        )
        xticks_svg = "".join(
            f'<text x="{x:.1f}" y="{H - PAD_B + (16 if compact else 20)}" text-anchor="middle" class="chart-tick">{esc(label)}</text>'
            for x, label in x_ticks
        )
        cls = "rank-chart chart-compact" if compact else "rank-chart chart-wide"
        return (f'<svg viewBox="0 0 {W} {H}" class="{cls}" role="img" '
                f'aria-label="Ranked Solo/Duo LP game by game">'
                f'{bands_svg}{grid_svg}{xticks_svg}'
                f'{"".join(series_groups)}{"".join(label_groups)}</svg>')

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
        net_labels.append({"text": move_text, "direction": direction,
                           "moved": False, "lp": None})
        tiers.append(hist[-1].get("tier"))
        # One row per player under the chart: what the season adds up to,
        # which is a different question from which line is whose. The key
        # beside the plot answers that one and carries nothing else, so its
        # rows can be spaced evenly instead of sized by their longest text.
        standings.append({"var": friend_colour(f["label"]), "label": f["label"],
                          "tier": hist[-1].get("tier"),
                          "rankLabel": rank_label(hist[-1]), "games": games,
                          "lp": net_lp, "winrate": round(100 * wins / games) if games else 0,
                          "record": record})
        legend_items.append(
            # Names every render this legend drives: wide/compact for both the
            # full and zoomed views. Absent ids are skipped harmlessly, so this
            # stays correct whether or not the zoom variant was built.
            f'<span class="legend-item" data-chart="lp lpm lpt lpmt" data-idx="{i}">'
            f'<span class="sw" style="background:var({friend_colour(f["label"])})"></span>'
            f'<span class="legend-name" style="color:var({friend_colour(f["label"])});">'
            f'{esc(f["label"])}</span>'
            f'</span>'
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

    # The projection is a guess, and a guess is not always what you want on
    # screen. Toggled with a class on the container so it applies to both
    # renders, both zoom levels, and anything the browser redraws later.
    proj_toggle = (
        '<div class="range-toggle" role="group" aria-label="Projection">'
        '<button type="button" class="range-btn active" data-proj="on" aria-pressed="true">'
        'Projection on</button>'
        '<button type="button" class="range-btn" data-proj="off" aria-pressed="false">'
        'Projection off</button>'
        '</div>'
    )

    omitted_note = ""
    if omitted:
        omitted_note = (f'<div class="muted small" style="margin-top:8px;">Not shown: {esc(", ".join(omitted))} '
                        f'(chart shows up to {len(FRIEND_PALETTE)} friends at once).</div>')

    # Named in the caption so the dashed line has a stated finish line rather
    # than an arbitrary one.
    most_games = max(len(timelines[f["label"]]) - 1 for f in chart_friends)
    most_played = next(f["label"] for f in chart_friends
                       if len(timelines[f["label"]]) - 1 == most_games)

    # Who was in each shared Solo/Duo game, for the game list below the
    # chart. Built over every tracked friend rather than only the charted
    # ones, so the "With" column names the same people the server named.
    sides = {}
    for f in friends_sorted:
        for m in f.get("seasonMatches", []):
            if m.get("remake") or m.get("queue") != "Ranked Solo/Duo":
                continue
            sides.setdefault(m["matchId"], []).append([f["label"], bool(m["win"])])
    duo_sides = {mid: v for mid, v in sides.items() if len(v) > 1}

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
        "tierBandAlpha": TIER_BAND_ALPHA,
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
                     "win": bool(m.get("win")), "champion": m.get("champion"),
                     "matchId": m.get("matchId")}
                    for m in f.get("seasonMatches", []) if m.get("queue") == "Ranked Solo/Duo"
                ],
            }
            for f in chart_friends
        ],
        # The game list under the chart is rebuilt in the browser too, so it
        # needs the same three things the server had: which champion icon to
        # draw, which colour belongs to which name, and who else was on the
        # team. Only matches with two or more tracked players are listed;
        # every other match resolves to "no mates" without being named.
        "champIcons": _ICON_CTX["map"],
        "ddragonVersion": _ICON_CTX["version"],
        "varByLabel": {f["label"]: friend_colour(f["label"]) for f in friends_sorted},
        "duoSides": duo_sides,
    }, ensure_ascii=False)

    standings_html = render_chart_stats(standings)

    # One list for everybody, newest game first. Grouped by friend and counted
    # up from game 1, today's games sat at the bottom of whichever block they
    # fell in, so "what just happened" meant scrolling past several hundred
    # rows of somebody else's season.
    lp_events = sorted(
        (
            {"label": f["label"], "var": friend_colour(f["label"]), "idx": p["idx"], "point": p,
             "prevScore": tl[n - 1]["score"], "match": p["match"],
             "when": p["match"].get("gameStartMs") or 0}
            for i, f in enumerate(chart_friends)
            for tl in [timelines[f["label"]]]
            for n, p in enumerate(tl)
            if p["match"]
        ),
        # Grouped by match inside a timestamp so the rows of one game are
        # always adjacent, whatever order the friends were processed in.
        key=lambda e: (-e["when"], e["match"].get("matchId") or "", e["label"]),
    )

    # Which rows open and close a game, so the block is drawn once around the
    # group rather than repeated on every row inside it.
    group_pos = {}
    for n, e in enumerate(lp_events):
        mid = e["match"].get("matchId")
        group_pos[id(e)] = (
            n == 0 or lp_events[n - 1]["match"].get("matchId") != mid,
            n == len(lp_events) - 1 or lp_events[n + 1]["match"].get("matchId") != mid,
        )

    def lp_row(e):
        p, m = e["point"], e["match"]
        move = lp_step_label(e["prevScore"], p["score"], p["delta"], p["exact"])
        # Two different classes: one says which way the LP went, the other says
        # the row belongs to a shared game. They were sharing a variable, so the
        # party class overwrote the direction and every LP figure in the table
        # rendered in the plain text colour instead of green or red.
        move_cls = "up" if (p["delta"] or 0) >= 0 else "down"
        party = party_size(m.get("matchId"), e["label"])
        band = party_band(m.get("matchId"), e["label"], e["var"])
        first, last = group_pos[id(e)]
        row_cls = ""
        if party > 1:
            row_cls = "party party-" + str(min(party, 5))
            row_cls += " g-first" if first else ""
            row_cls += " g-last" if last else ""
        return (
            f'<tr class="{row_cls}"'
            f'{f" style=\"{band}\"" if band else ""}>'
            f'<td class="muted small nowrap">{esc(format_match_when(m))}</td>'
            f'<td class="nowrap"><b style="color:var({e["var"]});">{esc(e["label"])}</b>'
            f'<span class="muted small"> &middot; game {esc(e["idx"])}</span></td>'
            f'<td><span class="tag {"win" if m["win"] else "loss"}">{"W" if m["win"] else "L"}</span></td>'
            f'<td class="champ-cell"><span class="cc">{render_champion_icon(m["champion"], size=18)}{esc(champion_display(m["champion"]))}</span></td>'
            f'<td class="with-cell">{render_duo_mates(m.get("matchId"), e["label"])}</td>'
            f'<td class="num lp-move {move_cls}">{esc(move)}</td>'
            f'<td class="num nowrap">{score_to_rank_label(p["score"])}</td>'
            f'</tr>'
        )

    table_rows = "".join(lp_row(e) for e in lp_events)

    return f'''
    <div class="panel">
      <h2 style="margin-bottom:4px;">LP per game</h2>
      <div class="muted small" style="margin-bottom:12px;">Ranked Solo/Duo &middot; every game since rank tracking began on {esc(tracking_since)}</div>
      <div class="chart-toggles">{zoom_toggle}{proj_toggle}</div>
      <div class="chart-row">
        <div class="chart-plot" data-lp-charts>{charts_svg}</div>
        <div class="chart-key" role="group" aria-label="Players on this chart">{"".join(legend_items)}</div>
      </div>
      <script type="application/json" id="lp-chart-data">{lp_chart_json}</script>
      {omitted_note}
      <div class="chart-stats-wrap" data-lp-standings>{standings_html}</div>
      <details class="matches-details" style="margin-top:10px;">
        <summary>Recent Games</summary>
        <table class="matches-table lp-table">
          <thead><tr><th>When</th><th>Player</th><th>Result</th><th>Champion</th><th>With</th>
          <th class="num">LP</th><th class="num">Rank after</th></tr></thead>
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
      <div class="muted small">No rank history yet · Riot's API doesn't expose past ranks, so this
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
    # Rendered twice, wide and compact, exactly as the LP chart is. This
    # panel used to be hidden outright on a phone, which is why the Rank
    # progress tab showed only the chart above it there.
    def build_svg(compact):
        if compact:
            # Phone build. The wide chart is 900 units across, and squeezing
            # that into a 350px screen scales its 11px labels to about 4px.
            W = 360
            H = max(230, min(420, 20 * len(chart_friends) + 150))
            PAD_L, PAD_R, PAD_T, PAD_B = 40, 10, 12, 26
        else:
            W = 900
            H = max(280, min(640, 34 * len(chart_friends) + 120))
            # Same as the LP chart: the key is the legend underneath.
            PAD_L, PAD_R, PAD_T, PAD_B = 64, 24, 16, 30
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
        for i in range(0, span_days, 14 if compact else 7):
            if span_days - i < (8 if compact else 4):
                continue
            d = start_date + timedelta(days=i)
            x, _ = xy(d.strftime("%Y-%m-%d"), y_min)
            x_ticks.append((x, d.strftime("%b %d")))
        x_today, _ = xy(end_date.strftime("%Y-%m-%d"), y_min)
        x_ticks.append((x_today, "Today"))

        prefix = "dailym" if compact else "daily"
        series_groups, legend_items, standings = [], [], []
        label_entries = []  # end-of-line labels, positioned after a declutter pass below
        for i, f in enumerate(chart_friends):
            var = friend_colour(f["label"])
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
                title = f"{f['label']} · {h['date']} · {rank_label(h)}".replace("&middot;", "·")
                if change:
                    title += f" ({change})"
                series_parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3 if compact else 4}" fill="var({var})" '
                    f'stroke="var(--surface-1)" stroke-width="1.5"><title>{esc(title)}</title></circle>'
                )
            series_groups.append(f'<g id="{prefix}-series-{i}">{"".join(series_parts)}</g>')
            if coords:
                lx, ly = coords[-1]
                # Measured across the window the chart actually draws. Reading
                # from pts[0] took in snapshots left of the axis, so the table and
                # the line it sits under could disagree.
                in_window = [h for h in pts if h["date"] >= start_date.strftime("%Y-%m-%d")]
                net = net_change_label(in_window[0], in_window[-1]) if len(in_window) >= 2 else None
                label_entries.append({"idx": i, "var": var, "label": f["label"], "lx": lx, "ly": ly, "net": net, "tier": pts[-1].get("tier")})
                # Snapshots are anchored to midnight now, so the last point
                # on this chart is this morning's reading. "Rank now" has to
                # come from the live entry or it would be up to a day stale.
                live = (f.get("ranked") or {}).get("solo") or pts[-1]
                standings.append({"var": var, "label": f["label"], "tier": live.get("tier"),
                                  "rankLabel": rank_label(live), "net": net,
                                  "snapshots": len(pts)})
            legend_items.append(
                f'<span class="legend-item" data-chart="daily dailym" data-idx="{i}">'
                f'<span class="sw" style="background:var({var})"></span>'
                f'<span class="legend-name" style="color:var({var});">{esc(f["label"])}</span></span>'
            )

        label_groups = []

        # tier_score() is 1000 a tier, not the 400 the LP chart works in.
        bands_svg = tier_bands(y_min, y_max, PAD_L, W - PAD_R,
                               lambda v: xy(start_date.strftime("%Y-%m-%d"), v)[1],
                               span=1000)
        grid_svg = "".join(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" class="chart-grid" />'
            f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end" class="chart-tick">{esc(label)}</text>'
            for y, label in y_ticks
        )
        xticks_svg = "".join(
            f'<text x="{x:.1f}" y="{H - PAD_B + (15 if compact else 18)}" text-anchor="middle" class="chart-tick">{esc(label)}</text>'
            for x, label in x_ticks
        )
        cls = "rank-chart chart-compact" if compact else "rank-chart chart-wide"
        svg = (f'<svg viewBox="0 0 {W} {H}" class="{cls}" role="img" '
               f'aria-label="Ranked Solo/Duo standing over the last {span_days + 1} days">'
               f'{bands_svg}{grid_svg}{xticks_svg}'
               f'{"".join(series_groups)}{"".join(label_groups)}</svg>')
        return svg, legend_items, standings

    wide_svg, legend_items, standings = build_svg(False)
    compact_svg, _lg, _st = build_svg(True)


    omitted_note = ""
    if omitted:
        omitted_note = f'<div class="muted small" style="margin-top:8px;">Not shown: {esc(", ".join(omitted))} (chart shows up to {len(FRIEND_PALETTE)} friends at once).</div>'

    # Only the days a rank actually moved, newest first. Listing every
    # snapshot for every friend meant hundreds of rows whose Change column
    # read "—", burying the handful that said anything.
    daily_events = []
    for i, f in enumerate(chart_friends):
        pts = solo_history_by_label[f["label"]]
        for idx, h in enumerate(pts):
            change = snapshot_change_label(pts[idx - 1] if idx > 0 else None, h)
            if not change:
                continue
            daily_events.append({"date": h["date"], "label": f["label"],
                                 "var": friend_colour(f["label"]), "h": h, "change": change})
    daily_events.sort(key=lambda e: e["date"], reverse=True)

    table_rows = "".join(
        f'<tr><td class="muted small nowrap">{esc(e["date"])}</td>'
        f'<td class="nowrap"><b style="color:var({e["var"]});">{esc(e["label"])}</b></td>'
        f'<td class="nowrap">{render_rank_icon(e["h"].get("tier"), size=16)}{rank_label(e["h"])}</td>'
        f'<td class="num nowrap">{esc(e["change"])}</td></tr>'
        for e in daily_events
    ) or '<tr><td colspan="4" class="muted small">Nothing has moved yet.</td></tr>' 

    distinct_dates = {h["date"] for f in chart_friends for h in solo_history_by_label[f["label"]]}
    sparse_note = ""
    if len(distinct_dates) < 2:
        sparse_note = (f'<div class="banner" style="margin-top:12px;">Rank tracking only started '
                        f'{esc(tracking_since)}, so there\'s just one snapshot so far · the trend line '
                        f'will build in as you keep running <code>fetch_data.py</code> (ideally daily).</div>')

    # Under the chart, not above it: the same move the LP chart makes, and
    # for the same reason · the plot is what the panel is for.
    def daily_move(st):
        n = st["net"]
        if not n:
            return '<td class="num muted">&ndash;</td>'
        text = n["text"]
        if n.get("moved") and n.get("lp") is not None:
            text = f"{'+' if n['lp'] >= 0 else '−'}{abs(n['lp'])} LP, {text}"
        cls = "up" if n["direction"] > 0 else ("down" if n["direction"] < 0 else "muted")
        return f'<td class="num {cls} nowrap">{esc(text)}</td>'

    standings_html = (
        f'<table class="chart-stats"><thead><tr><th>Player</th><th>Rank now</th>'
        f'<th class="num">Over these {span_days + 1} days</th></tr></thead><tbody>'
        + "".join(
            f'<tr><td class="cs-name"><span class="sw" style="background:var({s["var"]});"></span>'
            f'<b style="color:var({s["var"]});">{esc(s["label"])}</b></td>'
            f'<td class="nowrap">{render_rank_icon(s["tier"], size=18)}{s["rankLabel"]}</td>'
            f'{daily_move(s)}</tr>'
            for s in standings
        )
        + '</tbody></table>'
    )

    header_days = span_days + 1
    return f'''
    <div class="panel">
      <h2 style="margin-bottom:4px;">Daily rank progress</h2>
      <div class="muted small" style="margin-bottom:14px;">Ranked Solo/Duo &middot; one reading a day at midnight GMT &middot; last {header_days} day{"s" if header_days != 1 else ""}, tracking since {esc(tracking_since)}</div>
      <div class="chart-row">
        <div class="chart-plot">{wide_svg}{compact_svg}</div>
        <div class="chart-key" role="group" aria-label="Players on this chart">{"".join(legend_items)}</div>
      </div>
      {omitted_note}
      {sparse_note}
      <div class="chart-stats-wrap">{standings_html}</div>
      <details class="matches-details" style="margin-top:10px;">
        <summary>Daily Changes</summary>
        <table class="matches-table daily-table">
          <thead><tr><th>Date</th><th>Player</th><th>Rank</th><th class="num">Change</th></tr></thead>
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
            "text": f"{esc(f['label'])} popped off on {esc(m['champion'])} · "
                    f"{m['kills']}/{m['deaths']}/{m['assists']} (KDA {kda_score(m):.1f}).",
        })

    # Untouchable — a win with zero deaths and a meaningful kill/assist total.
    flawless = [p for p in pairs if p[1]["win"] and p[1]["deaths"] == 0 and (p[1]["kills"] + p[1]["assists"]) >= 8]
    if flawless:
        f, m = max(flawless, key=lambda p: p[1]["kills"] + p[1]["assists"])
        awards.append({
            "icon": "🛡️", "title": "Untouchable",
            "text": f"{esc(f['label'])} didn't die once on {esc(m['champion'])} · {m['kills']}/{m['deaths']}/{m['assists']}.",
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
            "text": f"{esc(f['label'])} played {count} games on {format_day_label(date_key)} · the busiest single day this season.",
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
            "text": f"{esc(f['label'])} has racked up {count} ranked games this season · more than anyone else in the group.",
        })

    # Comeback kid — a win despite the roughest KDA of anyone's winning games.
    scrappy_wins = [p for p in pairs if p[1]["win"] and p[1]["deaths"] >= 5 and kda_score(p[1]) < 2]
    if scrappy_wins:
        f, m = max(scrappy_wins, key=lambda p: p[1]["deaths"])
        awards.append({
            "icon": "🩹", "title": "Comeback kid",
            "text": f"{esc(f['label'])} still won going {m['kills']}/{m['deaths']}/{m['assists']} on {esc(m['champion'])}. Grit over stats.",
        })

    # Every award names its player first. Matching longest first so "Shas2nd"
    # is not read as "Shas".
    labels = sorted((f["label"] for f in friends), key=len, reverse=True)
    for a in awards:
        a.setdefault("who", next((l for l in labels if l in a["text"]), None))
    return awards[:12]


def render_award(a):
    # The strip down the left is that player's own colour, the same one they
    # have on the charts and in the duo grid, rather than the same accent on
    # every card.
    who = a.get("who")
    style = f' style="--award-colour: var({friend_colour(who)});"' if who else ""
    return f'''<div class="award"{style}>
      <div class="award-icon">{a["icon"]}</div>
      <div>
        <div class="award-title">{esc(a["title"])}</div>
        <div class="award-text">{a["text"]}</div>
      </div>
    </div>'''


# Below this many games together a winrate says more about luck than about
# the pair — a 5-game pair was topping "biggest lift" at +33 points.
DUO_THIN_GAMES = 10


def match_kda(m):
    """A single game's KDA, counting a deathless game as if it were one death
    so it stays a finite number that can be averaged."""
    return ((m.get("kills") or 0) + (m.get("assists") or 0)) / max(m.get("deaths") or 0, 1)


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def compute_kda_boost(friends):
    """Who is carrying whom, judged inside the games the pair played together.

    Comparing each player's KDA in the pair's games against their average
    everywhere else measured the wrong thing: it told you whether a player has
    good games when this partner is around, which moves with the whole team.
    Comparing the two players *against each other in the same games* is the
    question actually being asked, because they shared every one of those
    games, so the map, the opponents and the result are held constant.

    Solo/Duo only, matching the grid and the pair table it appears in. On all
    queues a pair's game count here disagreed with the count in the cell right
    next to it, because most of their shared games are Flex.
    """
    by_match = {}
    for f in friends:
        for m in f.get("seasonMatches", []):
            if m.get("remake") or m.get("queue") != "Ranked Solo/Duo":
                continue
            by_match.setdefault(m["matchId"], []).append((f["label"], m))

    together = {}
    for entries in by_match.values():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                (la, ma), (lb, mb) = entries[i], entries[j]
                if bool(ma["win"]) != bool(mb["win"]):
                    continue
                key = tuple(sorted([la, lb]))
                slot = together.setdefault(key, {})
                slot.setdefault(la, []).append(ma)
                slot.setdefault(lb, []).append(mb)

    out = {}
    for key, per in together.items():
        if len(per) != 2:
            continue
        (l1, g1), (l2, g2) = per.items()
        if min(len(g1), len(g2)) < DUO_THIN_GAMES:
            continue
        k1, k2 = _mean([match_kda(m) for m in g1]), _mean([match_kda(m) for m in g2])
        if k1 is None or k2 is None:
            continue
        if k1 >= k2:
            booster, boosted, hi, lo = l1, l2, k1, k2
        else:
            booster, boosted, hi, lo = l2, l1, k2, k1
        out[key] = {"booster": booster, "boosted": boosted,
                    "boosterKda": round(hi, 2), "boostedKda": round(lo, 2),
                    "gap": round(hi - lo, 2), "games": len(g1)}
    return out


PARTY_QUEUES = ("Ranked Flex", "Ranked 5s")


def compute_party_synergy(friends, min_size=3):
    """Lineups of three or more who were on the same team, in Flex or 5s.

    Exact lineups only. A five man is one row: it is not also counted as the
    ten pairs and ten trios inside it, and two different five mans that share
    four names do not add up to a four man that never played. A group is only
    ever credited with games that exact group played.
    """
    order = {f["label"]: i for i, f in enumerate(friends)}
    own = {}
    for f in friends:
        played = [m for m in f.get("seasonMatches", [])
                  if not m.get("remake") and m.get("queue") in PARTY_QUEUES]
        if played:
            own[f["label"]] = 100 * sum(1 for m in played if m["win"]) / len(played)

    # Flex and Ranked 5s only. Solo/Duo cannot hold three premades, so three
    # tracked names on a Solo/Duo team is matchmaking coincidence rather than a
    # lineup anyone made, and counting it here would put games in this table
    # that nobody queued as a group.
    by_match = {}
    for f in friends:
        for m in f.get("seasonMatches", []):
            if m.get("remake") or m.get("queue") not in PARTY_QUEUES:
                continue
            by_match.setdefault(m["matchId"], []).append((f["label"], m))

    groups = {}
    for entries in by_match.values():
        if len(entries) < min_size:
            continue
        for won in (True, False):
            side = sorted((l for l, m in entries if bool(m["win"]) is won), key=lambda l: order[l])
            if len(side) < min_size:
                continue
            m0 = next(m for l, m in entries if l == side[0])
            # Solo/Duo cannot hold three premades, so a lineup here is Flex or the
            # old Ranked 5s queue; a "solo" column could only ever be empty.
            g = groups.setdefault(tuple(side), {"games": 0, "wins": 0, "fives": 0, "flex": 0})
            g["games"] += 1
            if won:
                g["wins"] += 1
            g["fives" if m0.get("queue") == "Ranked 5s" else "flex"] += 1

    rows = []
    for members, g in groups.items():
        # Three or five only. Flex takes 1, 2, 3 or 5, so four tracked names on
        # a team is somebody else's five man with four of you in it, not a
        # lineup anyone queued as.
        if len(members) not in (3, 5):
            continue
        winrate = round(100 * g["wins"] / g["games"], 1)
        base = [own[x] for x in members if x in own]
        baseline = round(sum(base) / len(base), 1) if base else None
        rows.append({
            "members": list(members),
            "vars": [friend_var(min(order[x], len(FRIEND_PALETTE) - 1)) for x in members],
            # Flex can be queued as one, two, three or five, never four, so four
            # tracked names on a team is a five man premade whose fifth player
            # is not in this group rather than a "four stack", which the game
            # does not let you make.
            "size": len(members),
            "kind": "Trio" if len(members) == 3 else "Five-man",
            "games": g["games"], "wins": g["wins"], "losses": g["games"] - g["wins"],
            "winrate": winrate, "fives": g["fives"], "flex": g["flex"],
            "baseline": baseline,
            "lift": round(winrate - baseline, 1) if baseline is not None else None,
        })
    rows.sort(key=lambda r: (-r["games"], -r["winrate"]))
    return rows


def party_coverage(friends):
    """Where each player's Flex and 5s games went.

    The stacks table lists exact lineups of three or five, so a player's games
    do not add up to the rows they appear in and the difference looks like
    something is being lost. It is not: this counts the rest. Four tracked
    names on a team is a five man whose fifth player is outside this group,
    because Flex has no four player party, and a game with one or two of them
    on a side is not a stack at all.
    """
    by_match = {}
    for f in friends:
        for m in f.get("seasonMatches", []):
            if m.get("remake") or m.get("queue") not in PARTY_QUEUES:
                continue
            by_match.setdefault(m["matchId"], []).append((f["label"], bool(m["win"])))

    rows = {}
    for f in friends:
        rows[f["label"]] = {"games": 0, "listed": 0, "four": 0, "under": 0}
    for entries in by_match.values():
        for label, win in entries:
            side = [l for l, w in entries if w == win]
            r = rows.get(label)
            if r is None:
                continue
            r["games"] += 1
            if len(side) in (3, 5):
                r["listed"] += 1
            elif len(side) == 4:
                r["four"] += 1
            else:
                r["under"] += 1
    return [dict(r, label=k) for k, r in rows.items() if r["games"]]


# ---------------------------------------------------------------------------
# Season highlights.
#
# Each of these is a superlative across the whole group: one winner, the
# number behind it, and enough of the runner-up's number to show it was close.
# They all take the same shape so the renderer does not care which is which.
#
# A few need fields that were only added to the extractor recently, so they
# return None until fetch_data.py has been through with --refetch-details.
# Returning None is the point: a highlight that cannot be computed should be
# absent, not wrong.
# ---------------------------------------------------------------------------

HL_MIN_GAMES = 20          # below this a season average is one bad week
SUPPORT_JUNGLE = {"Support", "Jungle"}


def _played(f, queue=None):
    return [m for m in f.get("seasonMatches", [])
            if not m.get("remake") and (queue is None or m.get("queue") == queue)]


def _has(matches, field):
    return any(field in m for m in matches)


# How each highlight is measured, keyed by title: the sentence shown when a
# card is opened, the unit its value is in, and how many decimals that value
# deserves.
#
# Kept here rather than passed at each call site because it is documentation,
# it is read together, and threading twenty-four strings through the argument
# lists would bury the code that does the work.
HIGHLIGHT_METHOD = {
    "MVP": ("Share of their ranked games ending on a KDA of 5.0 or better. "
            "KDA is (kills + assists) / deaths, counting a death-free game as "
            "if it had one death.", "%", 1),
    "KDA king": ("Mean KDA across every ranked game, each game weighted the "
                 "same regardless of length.", "", 2),
    "Farm god": ("Mean creep score a minute, counting only games played "
                 "outside support and jungle, where farm is not the job.", " CS/min", 2),
    "Marathon day": ("Most ranked games played in one calendar day.", " games", 0),
    "Season grinder": ("Total ranked games this season, remakes excluded.", " games", 0),
    "Unemployed": ("Longest run of consecutive calendar days with at least "
                   "one ranked game on each.", " days", 0),
    "Chicken dinner": ("Longest run of consecutive wins, in the order the "
                       "games were played.", " wins", 0),
    "If at first you don't succeed": ("Longest run of consecutive losses.", " losses", 0),
    "Sisyphus": ("Longest run of strictly alternating results: win, loss, "
                 "win, loss, with no two the same in a row.", " games", 0),
    "The assassin": ("Damage taken divided by kills plus assists. Measured "
                     "only across games where damage taken was recorded, so "
                     "the top and bottom of the fraction cover the same "
                     "games. The season games column is their whole season, not the smaller set this was measured over.", " per takedown", 0),
    "The wall": ("Damage taken divided by deaths, across the games where "
                 "damage taken was recorded. The season games column is their whole season, not the smaller set this was measured over.", " per death", 0),
    "The DPS": ("Mean damage dealt to champions a game. Damage to towers, "
                "jungle and minions is not counted.", " damage", 0),
    "On a mission": ("Kills divided by total minutes played. The card reports "
                     "the totals behind it; this ranks on the rate, so a long "
                     "season does not win by itself.", " kills/min", 3),
    "Int alert": ("Deaths divided by total minutes played.", " deaths/min", 3),
    "I cannot see, I'm legally blind": ("Mean vision score a game, lowest "
                                        "wins. Only games where vision score "
                                        "was recorded. The season games column is their whole season, not the smaller set this was measured over.", "", 1),
    "Tickle monster": ("Damage dealt to champions divided by kills. Highest "
                       "wins: the most damage spent per kill.", " per kill", 0),
    "Dirty KSer": ("Damage dealt to champions divided by kills, lowest wins.",
                   " per kill", 0),
    "Passenger": ("Mean KDA in games they won, lowest wins. Losses are "
                  "excluded on purpose: a low KDA in a game you lost is "
                  "losing, a low KDA in a game your team won anyway is being "
                  "carried.", "", 2),
    "Speedrunner": ("Share of all their games that were wins finishing inside "
                    "16 minutes, which is a surrender rather than a game.", "%", 1),
    "Besto Friendo": ("Their best winrate alongside a given champion on their "
                      "own team, over at least 10 games with it. Only games "
                      "where the allied champions were recorded. The season games column is their whole season, not the smaller set this was measured over.", "%", 1),
    "Just this once": ("Largest gap between their single best KDA on a "
                       "champion and their average on that champion, across "
                       "champions with at least 10 games.", " KDA above", 1),
    "Diffed": ("Share of games where their KDA came out below their direct "
               "lane opponent's. Only games where the opponent was "
               "identified. The season games column is their whole season, not the smaller set this was measured over.", "%", 0),
    "Lights were too bright": ("Winrate in the games that immediately follow "
                               "a win, lowest wins. Needs at least 10 such "
                               "games.", "%", 1),
    "Resilient": ("Mean length of the games they lose. Longest wins.", " min", 1),
}


def _best(friends, value, fmt, min_games=HL_MIN_GAMES, lowest=False,
          method=None, unit="", places=2):
    """Pick the friend with the highest (or lowest) `value`, and describe it.

    `value` returns None for anyone the measure cannot be taken on, so a
    missing field or a thin sample drops that player rather than the award.

    The whole scoreboard comes back, not just the winner. A card that says
    somebody is the best at something invites exactly one question, which is
    "by how much, and over whom", and the numbers to answer it were already
    computed and then thrown away.

    `method` is how the number was arrived at, in a sentence, and `excluded`
    records who could not be measured and why, because "not on the list" and
    "last on the list" mean very different things.
    """
    scored, excluded = [], []
    for f in friends:
        games = _played(f)
        if len(games) < min_games:
            excluded.append((f["label"], f"{len(games)} games, needs {min_games}"))
            continue
        v = value(f, games)
        if v is None:
            excluded.append((f["label"], "not enough data recorded"))
        else:
            scored.append((v, f, games))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=not lowest)
    v, f, games = scored[0]
    runner = scored[1][0] if len(scored) > 1 else None
    return {
        "who": f["label"],
        "text": fmt(f, games, v, runner),
        "method": method,
        "standings": [{"label": e[1]["label"], "value": e[0], "games": len(e[2])}
                      for e in scored],
        "excluded": excluded,
        "unit": unit,
        "places": places,
        "lowest": lowest,
    }


def streaks(results):
    """Longest run of wins, of losses, and of strict alternation."""
    best_w = best_l = best_alt = 0
    run_w = run_l = 0
    alt = 0
    prev = None
    for won in results:
        run_w = run_w + 1 if won else 0
        run_l = 0 if won else run_l + 1
        best_w, best_l = max(best_w, run_w), max(best_l, run_l)
        alt = alt + 1 if (prev is not None and won != prev) else 1
        best_alt = max(best_alt, alt)
        prev = won
    return best_w, best_l, best_alt


def longest_daily_run(dates):
    """Most consecutive days with at least one game, and the dates of it."""
    days = sorted({datetime.strptime(d, "%Y-%m-%d").date() for d in dates if d})
    if not days:
        return 0, None, None
    best = run = 1
    start = best_start = best_end = days[0]
    for prev, cur in zip(days, days[1:]):
        if (cur - prev).days == 1:
            run += 1
        else:
            run, start = 1, cur
        if run > best:
            best, best_start, best_end = run, start, cur
    return best, best_start, best_end


# The order cards appear in, read left to right, three to a row. Kept as a
# list rather than as the order the add() calls happen to run in: the code
# groups them by what they measure, which is the right way to read the code
# and the wrong way to read the page. Anything not named here sorts to the
# end rather than disappearing, so adding a card cannot silently lose it.
WEEK_TILE_ORDER = [
    "Total games this week", "Most active player", "Games played together",
    "Biggest climber", "Hottest streak", "Animal of the week",
    "Most loved champion", "Adaptable", "Grasshopper",
]

SEASON_HIGHLIGHT_ORDER = [
    "MVP", "KDA king", "Farm god",
    "Marathon day", "Season grinder", "Unemployed",
    "Chicken dinner", "If at first you don't succeed", "Sisyphus",
    "The assassin", "The wall", "The DPS",
    "On a mission", "Int alert", "I cannot see, I'm legally blind",
    "Tickle monster", "Dirty KSer", "Passenger",
    "Speedrunner", "Besto Friendo", "Just this once",
    "Diffed", "Lights were too bright", "Resilient",
]

DUO_CARD_ORDER = [
    "Lovers", "Perfect couple", "Healthy relationship",
    "Exes", "Vegas wedding", "Sneaky link",
]


def in_declared_order(items, order, title_of):
    """Sort to `order`, keeping anything unlisted at the end in its own order."""
    rank = {title: i for i, title in enumerate(order)}
    return sorted(items, key=lambda x: rank.get(title_of(x), len(order)))


def season_highlights(friends, now):
    """Every superlative that can be taken from what is stored."""
    out = []

    def add(card):
        if card:
            out.append(card)

    # ---- performance -------------------------------------------------------
    add(_wrap(_best(friends, lambda f, g: 100 * sum(1 for m in g if match_kda(m) >= 5.0) / len(g),
                    lambda f, g, v, r: (f'ended <strong>{v:.0f}%</strong> of {len(g)} games on a '
                                        f'KDA of 5.0 or better.')),
              "\U0001f3c6", "MVP"))

    add(_wrap(_best(friends, lambda f, g: sum(match_kda(m) for m in g) / len(g),
                    lambda f, g, v, r: f'averages <strong>{v:.2f}</strong> KDA across {len(g)} games.'),
              "\U0001f451", "KDA king"))

    add(_wrap(_best(friends,
                    lambda f, g: _mean([m["csPerMin"] for m in g
                                        if POSITION_LABELS.get(m.get("position") or "")
                                        not in SUPPORT_JUNGLE and m.get("csPerMin")]),
                    lambda f, g, v, r: f'farms <strong>{v:.1f}</strong> CS a minute outside support and jungle.'),
              "\U0001f33e", "Farm god"))

    # ---- volume ------------------------------------------------------------
    def busiest(f, g):
        _d, n = busiest_day(g)
        return n

    add(_wrap(_best(friends, busiest,
                    lambda f, g, v, r: (lambda d, n: f'played <strong>{n}</strong> games on '
                                        f'{format_day_label(d)}, {format_minutes(sum(m.get("durationMin", 0) for m in g if m.get("dateKey") == d))} of League.')
                    (*busiest_day(g))),
              "\U0001f4c5", "Marathon day"))

    add(_wrap(_best(friends, lambda f, g: len(g),
                    lambda f, g, v, r: (f'has played <strong>{v}</strong> ranked games, '
                                        f'{format_minutes(sum(m.get("durationMin", 0) for m in g))} in all.')),
              "\U0001f3ae", "Season grinder"))

    def run_days(f, g):
        n, _a, _b = longest_daily_run([m.get("dateKey") for m in g])
        return n

    add(_wrap(_best(friends, run_days,
                    lambda f, g, v, r: (lambda n, a, b: f'played <strong>{n}</strong> days running, '
                                        f'{a.strftime("%b %d")} to {b.strftime("%b %d")}.')
                    (*longest_daily_run([m.get("dateKey") for m in g]))),
              "\U0001f6cf\ufe0f", "Unemployed"))

    # ---- streaks -----------------------------------------------------------
    def ordered(g):
        return [bool(m["win"]) for m in sorted(g, key=lambda m: m.get("gameStartMs") or 0)]

    add(_wrap(_best(friends, lambda f, g: streaks(ordered(g))[0],
                    lambda f, g, v, r: f'won <strong>{v}</strong> in a row.'),
              "\U0001f357", "Chicken dinner"))
    add(_wrap(_best(friends, lambda f, g: streaks(ordered(g))[1],
                    lambda f, g, v, r: f'lost <strong>{v}</strong> in a row.'),
              "\U0001f4c9", "If at first you don't succeed"))
    add(_wrap(_best(friends, lambda f, g: streaks(ordered(g))[2],
                    lambda f, g, v, r: f'alternated win, loss, win for <strong>{v}</strong> games.'),
              "\u26f0\ufe0f", "Sisyphus"))

    # ---- damage ------------------------------------------------------------
    add(_wrap(_best(friends, lambda f, g: _mean([m.get("damageDealt", 0) for m in g]),
                    lambda f, g, v, r: (f'averages <strong>{v:,.0f}</strong> damage dealt to '
                                        f'champions per game.')),
              "\U0001f4a5", "The DPS"))

    def dmg_per_kill(f, g):
        kills = sum(m["kills"] for m in g)
        return (sum(m.get("damageDealt", 0) for m in g) / kills) if kills else None

    add(_wrap(_best(friends, dmg_per_kill,
                    lambda f, g, v, r: (f'It takes {esc(f["label"])} <strong>{v:,.0f}</strong> '
                                        f'damage to get a kill.')),
              "\U0001f54a\ufe0f", "Tickle monster", whole=True))
    add(_wrap(_best(friends, dmg_per_kill, lowest=True,
                    fmt=lambda f, g, v, r: (f'{esc(f["label"])} only needs <strong>{v:,.0f}</strong> '
                                            f'damage to get a kill, suspicious if you ask me.')),
              "\U0001f9f9", "Dirty KSer", whole=True))

    # ---- pace --------------------------------------------------------------
    def per_min(field):
        def inner(f, g):
            mins = sum(m.get("durationMin", 0) for m in g)
            return (sum(m[field] for m in g) / mins) if mins else None
        return inner

    def between_deaths(g):
        deaths = sum(m["deaths"] for m in g)
        mins = sum(m.get("durationMin", 0) for m in g)
        return (mins / deaths) if deaths else None

    def total_hours(g):
        return sum(m.get("durationMin", 0) for m in g) / 60.0

    add(_wrap(_best(friends, per_min("kills"),
                    lambda f, g, v, r: (lambda k, h: f'has got <strong>{k:,}</strong> total kills in '
                                        f'{h:,.0f} total hours, that&#39;s '
                                        f'{(h * 60 / k) if k else 0:.1f} minutes between each kill.')
                    (sum(m["kills"] for m in g), total_hours(g))),
              "\U0001f3af", "On a mission"))
    add(_wrap(_best(friends, per_min("deaths"),
                    lambda f, g, v, r: (lambda d, h: f'has died a total of <strong>{d:,}</strong> '
                                        f'times in {h:,.0f} total hours, that&#39;s '
                                        f'{(h * 60 / d) if d else 0:.1f} minutes between each death.')
                    (sum(m["deaths"] for m in g), total_hours(g))),
              "\U0001f480", "Int alert"))
    add(_wrap(_best(friends,
                    lambda f, g: _mean([m["visionScore"] for m in g if "visionScore" in m])
                    if _has(g, "visionScore") else None,
                    lowest=True,
                    fmt=lambda f, g, v, r: (f'averages <strong>{v:.0f}</strong> vision score, '
                                            f'{v / max(_mean([m.get("durationMin", 1) for m in g]), 1):.2f} a minute.')),
              "\U0001f576", "I cannot see, I'm legally blind"))

    # ---- losses ------------------------------------------------------------
    def winning_kda(f, g):
        won = [m for m in g if m["win"]]
        return _mean([match_kda(m) for m in won]) if won else None

    # Wins, not losses. A low KDA in a game you lost is just losing; a low KDA
    # in a game your team won anyway is being carried, which is the joke.
    add(_wrap(_best(friends, winning_kda, lowest=True,
                    fmt=lambda f, g, v, r: (f'averages <strong>{v:.2f}</strong> KDA in the games '
                                            f'they win.')),
              "\U0001f697", "Passenger"))

    def long_losses(f, g):
        lost = [m.get("durationMin", 0) for m in g if not m["win"]]
        return _mean(lost) if lost else None

    add(_wrap(_best(friends, long_losses,
                    lambda f, g, v, r: (f'averages <strong>{v:.0f}</strong> minutes during losses, '
                                        f'truly a fighter until the end.')),
              "\U0001f6e1\ufe0f", "Resilient"))

    # ---- oddities ----------------------------------------------------------
    def besto(f, g):
        pool = [m for m in g if m.get("allies")]
        if not pool:
            return None
        stats = {}
        for m in pool:
            for ally in m["allies"]:
                st = stats.setdefault(ally, [0, 0])
                st[0] += 1
                st[1] += 1 if m["win"] else 0
        rated = [(100 * w / n, c, n) for c, (n, w) in stats.items() if n >= 10]
        return max(rated)[0] if rated else None

    def quick_wins(f, g):
        fast = [m for m in g if m["win"] and m.get("durationMin", 99) < 16]
        return 100 * len(fast) / len(g)

    add(_wrap(_best(friends, quick_wins,
                    lambda f, g, v, r: (f'wins <strong>{v:.1f}%</strong> of their games via an FF15, '
                                        f'kachow.')),
              "\u26a1", "Speedrunner"))
    add(_wrap(_best(friends, besto,
                    lambda f, g, v, r: (lambda b: f'wins <strong>{v:.0f}%</strong> of games with a '
                                        f'{champion_display(b[1])} on the team ({b[2]} of them).')
                    (_besto_detail(g))),
              "\U0001f465", "Besto Friendo"))

    def after_a_win(f, g):
        seq = sorted(g, key=lambda m: m.get("gameStartMs") or 0)
        nxt = [b for a, b in zip(seq, seq[1:]) if a["win"]]
        if len(nxt) < 10:
            return None
        return 100 * sum(1 for m in nxt if m["win"]) / len(nxt)

    add(_wrap(_best(friends, after_a_win, lowest=True,
                    fmt=lambda f, g, v, r: (f'wins only <strong>{v:.0f}%</strong> of the games that '
                                            f'follow a win.')),
              "\U0001f4a1", "Lights were too bright"))

    def one_off(f, g):
        by_champ = {}
        for m in g:
            by_champ.setdefault(m["champion"], []).append(m)
        best = None
        for champ, ms in by_champ.items():
            if len(ms) < 10:
                continue
            kdas = [match_kda(m) for m in ms]
            gap = max(kdas) - (sum(kdas) / len(kdas))
            if best is None or gap > best[0]:
                best = (gap, champ, max(kdas))
        return best[0] if best else None

    add(_wrap(_best(friends, one_off,
                    lambda f, g, v, r: (lambda b: f'once went <strong>{b[2]:.1f}</strong> KDA on '
                                        f'{champion_display(b[1])}, {v:.1f} above their average on it.')
                    (_one_off_detail(g))),
              "\u2728", "Just this once"))

    # ---- these need fields the extractor only records since the last change --


    def damage_taken_per_takedown(f, g):
        # Same trap as The wall: only the matches that carry the field.
        pool = [m for m in g if "damageTaken" in m]
        takedowns = sum(m["kills"] + m["assists"] for m in pool)
        if len(pool) < HL_MIN_GAMES or not takedowns:
            return None
        return sum(m["damageTaken"] for m in pool) / takedowns

    add(_wrap(_best(friends, damage_taken_per_takedown, lowest=True,
                    fmt=lambda f, g, v, r: (f'takes only <strong>{v:,.0f}</strong> damage for every '
                                            f'kill or assist they get.')),
              "\U0001f5e1\ufe0f", "The assassin"))
    def damage_taken_per_death(f, g):
        pool = [m for m in g if "damageTaken" in m]
        deaths = sum(m["deaths"] for m in pool)
        if len(pool) < HL_MIN_GAMES or not deaths:
            return None
        return sum(m["damageTaken"] for m in pool) / deaths

    add(_wrap(_best(friends, damage_taken_per_death,
                    lambda f, g, v, r: f'soaks <strong>{v:,.0f}</strong> damage for every death.'),
              "\U0001f9f1", "The wall"))

    def diffed(f, g):
        pool = [m for m in g if m.get("opponentKda") is not None]
        if len(pool) < HL_MIN_GAMES:
            return None
        return 100 * sum(1 for m in pool if match_kda(m) < m["opponentKda"]) / len(pool)

    add(_wrap(_best(friends, diffed,
                    lambda f, g, v, r: (f'had a lower KDA than their lane opponent in '
                                        f'<strong>{v:.0f}%</strong> of games.')),
              "\U0001f44e", "Diffed"))

    return in_declared_order(out, SEASON_HIGHLIGHT_ORDER, lambda c: c["title"])


def _wrap(card, icon, title, whole=False):
    """A finished card.

    Most read "Winny averages 4.2 KDA", so the name is prepended and the
    formatter writes only the predicate. A few need the name somewhere else
    in the sentence ("It takes Winny 45,000 damage to get a kill"); those pass
    whole=True and write the whole thing, name included.
    """
    if not card:
        return None
    text = card["text"] if whole else f'{esc(card["who"])} {card["text"]}'
    method, unit, places = HIGHLIGHT_METHOD.get(title, (card.get("method"), "", 2))
    if card.get("lowest") and method:
        method += " Lowest wins, so first place is the smallest number."
    return {"icon": icon, "title": title, "text": text, "who": card["who"],
            "method": method, "standings": card.get("standings"),
            "excluded": card.get("excluded"), "unit": unit,
            "games_label": "Season games",
            "places": places, "lowest": card.get("lowest", False)}


def _one_off_detail(g):
    by_champ = {}
    for m in g:
        by_champ.setdefault(m["champion"], []).append(m)
    best = None
    for champ, ms in by_champ.items():
        if len(ms) < 10:
            continue
        kdas = [match_kda(m) for m in ms]
        gap = max(kdas) - (sum(kdas) / len(kdas))
        if best is None or gap > best[0]:
            best = (gap, champ, max(kdas))
    return best


def _besto_detail(g):
    stats = {}
    for m in g:
        for ally in (m.get("allies") or []):
            st = stats.setdefault(ally, [0, 0])
            st[0] += 1
            st[1] += 1 if m["win"] else 0
    rated = [(100 * w / n, c, n) for c, (n, w) in stats.items() if n >= 10]
    return max(rated) if rated else (0, "", 0)


def render_duo_synergy_panel(friends):
    """A matrix, not a list of cards.

    Seventeen near-identical cards in a three-column grid make it impossible
    to see who plays with whom, and a bar running from 0% wastes its whole
    length on a range nobody occupies · the signal in a winrate sits within
    about ten points of even. A grid of everyone against everyone fits in less
    space than three cards and shows the shape of the group at once.
    """
    data = compute_duo_synergy(friends)
    rows, own, players = data["rows"], data["own"], data["players"]
    if not [r for r in rows if r["total"]["games"] >= 2]:
        return ""

    # A pair can only be spotted in a game both players' histories cover, and
    # Riot's incremental scraping leaves those histories starting on different
    # dates. Saying so is the difference between "they never duo'd" and "we
    # cannot see that far back for one of them".
    starts = {}
    for f in friends:
        sm = f.get("seasonMatches") or []
        if sm:
            starts[f["label"]] = min(m["dateKey"] for m in sm if m.get("dateKey"))
    coverage_note = ""
    if False:
        # Shallowest first: those are the histories actually constraining what
        # can be seen, and a pair is limited by the later of its two dates.
        listed = " &middot; ".join(
            f'{esc(k)} <b>{esc(v)}</b>'
            for k, v in sorted(starts.items(), key=lambda kv: kv[1], reverse=True))
        coverage_note = (
            '<p class="muted small" style="margin-top:10px;">A pairing only shows up in games '
            "that are inside <em>both</em> players' match history, and those histories start on "
            f'different dates: {listed}. Anything two players did together before the later of '
            'their dates cannot be seen from here. '
            '<code>python fetch_data.py --resync</code> re-lists everyone from the season start.</p>'
        )

    by_pair = {tuple(sorted([r["a"], r["b"]])): r for r in rows}
    boost_by_pair = compute_kda_boost(friends)
    widest_gap = max((b["gap"] for b in boost_by_pair.values()), default=0) or 0
    idx = {label: i for i, label in enumerate(players)}

    def qattrs(prefix, buckets):
        b = buckets["total"]
        return (
            f'data-total-games="{b["games"]}" data-total-wr="{b["winrate"]}" '
            f'data-total-w="{b["wins"]}" data-total-l="{b["losses"]}" '
            f'data-total-lift="{b["lift"] if b["lift"] is not None else -999}" '
            f'data-total-base="{b["baseline"] if b["baseline"] is not None else ""}"')

    head = "".join(
        f'<th scope="col"><span style="color:var({friend_colour(x)});">'
        f'{esc(x)}</span></th>' for x in players
    )

    body = []
    for a in players:
        cells = []
        for b in players:
            if a == b:
                # The diagonal is the player's own winrate, which is the number
                # every cell in that row is being compared against.
                # The diagonal used to show a bare winrate with the word
                # "alone" under it and no colour: the one number every other
                # cell in the row is measured against was the only cell that
                # did not say how many games it rests on or which side of even
                # it sits. Its "lift" is its distance from an even 50%, which
                # is what makes it green or red.
                rates = own.get(a, {})
                wr = round(rates.get("total", 0), 1)
                own_games = rates.get("games", 0)
                attrs = (f'data-total-games="{own_games}" data-total-wr="{wr}" '
                         f'data-total-lift="{round(wr - 50, 1) if own_games else -999}" '
                         f'data-total-base=""')
                cells.append(f'<td class="duo-cell duo-self" {attrs} '
                             f'title="{esc(a)} across every Solo/Duo game, whoever they played with">'
                             f'<span class="cell-wr"></span>'
                             f'<span class="cell-g">{own_games}g alone</span></td>')
                continue
            r = by_pair.get(tuple(sorted([a, b])))
            if not r:
                cells.append('<td class="duo-cell duo-none"><span class="cell-wr">\u2013</span></td>')
                continue
            # A ring around the cell where the row's player is the one
            # carrying the pair. Reading across a row then shows at a glance
            # which pairings they lift and which lift them, without a column
            # of names to cross-reference.
            b = boost_by_pair.get(tuple(sorted([a, b])))
            carry = ""
            if b and b["booster"] == a and b["gap"] >= CARRY_MIN_GAP:
                # Sized by how far ahead they are, against the widest gap in
                # the group, so the marks rank as well as flag. A floor keeps
                # the smallest one visible.
                share = (b["gap"] / widest_gap) if widest_gap else 0
                size = CARRY_MIN_PX + (CARRY_MAX_PX - CARRY_MIN_PX) * share
                carry = (f' data-carry="1" style="--carry:{size:.1f}px;"'
                         f' title="{esc(a)} holds the higher KDA in these '
                         f'{b["games"]} games, {b["boosterKda"]} against {b["boostedKda"]}, '
                         f'a gap of {b["gap"]:.2f}"')
            cells.append(
                f'<td class="duo-cell{" duo-carry" if carry else ""}" tabindex="0" role="button" '
                f'data-a="{esc(r["a"])}" data-b="{esc(r["b"])}"{carry} {qattrs("", r)}>'
                f'<span class="cell-wr"></span><span class="cell-g"></span></td>')
        colour = friend_colour(a)
        body.append(f'<tr><th scope="row"><span style="color:var({colour});">{esc(a)}</span></th>'
                    f'{"".join(cells)}</tr>')

    # Sorting is the reader's job, so both tables ship every number as a data
    # attribute and let the headers reorder them. The pair table opens
    # alphabetically, which is the only order that does not assert something.
    SYN_FULL_SCALE = 15.0   # points of lift that fill half the bar

    boost = boost_by_pair
    parties = compute_party_synergy(friends)

    def syn_cell(t):
        if t["lift"] is None:
            return '<td class="num syn"><span class="syn-val muted">&ndash;</span></td>'
        lift = t["lift"]
        cls = "up" if lift > 0 else ("down" if lift < 0 else "flat")
        thin = " thin" if t["games"] < DUO_THIN_GAMES else ""
        sign = "+" if lift > 0 else ("\u2212" if lift < 0 else "\u00b1")
        width = min(abs(lift) / SYN_FULL_SCALE, 1.0) * 50
        base = t.get("baseline")
        tip = (f'{t["winrate"]}% together against the {base}% those two average apart'
               if base is not None else "")
        return (f'<td class="num syn {cls}{thin}"{f" title={chr(34)}{esc(tip)}{chr(34)}" if tip else ""}>'
                f'<span class="syn-val">{sign}{abs(lift):.1f}%</span>'
                f'<span class="syn-bar"><i style="width:{width:.1f}%;"></i></span></td>')

    def boost_cell(r):
        b = boost.get(tuple(sorted([r["a"], r["b"]])))
        if not b:
            return '<td class="num muted">&ndash;</td>'
        return (f'<td class="num boost" title="Across their {b["games"]} games together, '
                f'{esc(b["booster"])} averages {b["boosterKda"]} KDA and '
                f'{esc(b["boosted"])} {b["boostedKda"]}">'
                f'<b>{esc(b["booster"])}</b> '
                f'<span class="boost-val">+{b["gap"]:.2f}</span></td>')

    def boost_value(r):
        b = boost.get(tuple(sorted([r["a"], r["b"]])))
        return b["gap"] if b else -999

    # Each pairing twice, once under each name. A single row per pair means
    # half the group can only find themselves by scanning the second column,
    # and sorting by name then only sorts the half that happened to be first.
    # The numbers are the pair's, so both rows carry the same ones.
    listed = []
    for r in rows:
        if r["total"]["games"] < 2:
            continue
        listed.append(r)
        listed.append(dict(r, a=r["b"], b=r["a"], aVar=r["bVar"], bVar=r["aVar"]))
    listed.sort(key=lambda r: (r["a"].lower(), r["b"].lower()))

    table_rows = "".join(
        f'<tr data-pair="{esc(r["a"] + " & " + r["b"])}" '
        f'data-syn="{r["total"]["lift"] if r["total"]["lift"] is not None else -999}" '
        f'data-wr="{r["total"]["winrate"]}" data-games="{r["total"]["games"]}" '
        f'data-boost="{boost_value(r)}">'
        f'<td class="num muted small seq"></td>'
        f'<td class="duo-pair">'
        # The same blend the shared-game blocks use on the Rank progress tab,
        # so a pairing can be recognised across the two pages by colour alone.
        f'<span class="duo-dot" style="background:{blend_vars(sorted([r["aVar"], r["bVar"]]))};"></span>'
        f'<span style="color:var({r["aVar"]});">{esc(r["a"])}</span>'
        f'<span class="duo-amp">&amp;</span>'
        f'<span style="color:var({r["bVar"]});">{esc(r["b"])}</span></td>'
        f'{syn_cell(r["total"])}'
        f'<td class="num"><b>{r["total"]["winrate"]}%</b></td>'
        f'<td class="num muted">{r["total"]["wins"]}W {r["total"]["losses"]}L</td>'
        f'<td class="num">{r["total"]["games"]}'
        f'{" <span class=\'duo-thin\'>!</span>" if r["total"]["games"] < DUO_THIN_GAMES else ""}</td>'
        f'{boost_cell(r)}'
        f'</tr>'
        for r in listed
    )

    party_rows = "".join(
        f'<tr data-lineup="{esc(" + ".join(r["members"]))}" '
        f'data-size="{r["size"]}" '
        f'data-syn="{r["lift"] if r["lift"] is not None else -999}" '
        f'data-wr="{r["winrate"]}" data-games="{r["games"]}" '
        f'data-fives="{r["fives"]}" data-flex="{r["flex"]}">'
        f'<td class="num muted small seq"></td>'
        f'<td class="duo-pair">'
        + "".join(
            f'<span style="color:var({v});">{esc(m)}</span>'
            + ('<span class="duo-amp">+</span>' if k < r["size"] - 1 else '')
            for k, (m, v) in enumerate(zip(r["members"], r["vars"]))
        )
        + f'</td>'
        f'<td class="muted nowrap">{r["kind"]}</td>'
        f'{syn_cell(r)}'
        f'<td class="num"><b>{r["winrate"]}%</b></td>'
        f'<td class="num muted">{r["wins"]}W {r["losses"]}L</td>'
        f'<td class="num">{r["games"]}'
        f'{" <span class=\'duo-thin\'>!</span>" if r["games"] < DUO_THIN_GAMES else ""}</td>'
        f'<td class="num muted">{r["flex"] or "&ndash;"}</td>'
        f'<td class="num muted">{r["fives"] or "&ndash;"}</td>'
        f'</tr>'
        for r in parties
    )

    # Queue 42 was removed from the game in 2016, so a Ranked 5s column would
    # be a column of dashes. It appears on its own if the queue ever returns.
    has_fives = any(m.get("queue") == "Ranked 5s"
                    for f in friends for m in f.get("seasonMatches", []))

    # An empty size reads as a broken table unless the table says so. Nobody
    # here has queued as an exact trio, and without this line that looks like
    # trios are not being counted rather than that there are none.
    party_table = ""
    if parties:
        party_table = f'''
      <details class="matches-details duo-table-details" style="margin-top:12px;">
        <summary>Trios and five mans</summary>

        <table class="matches-table duo-table" data-sortable>
          <thead><tr><th class="num">#</th><th class="sortable" data-key="lineup">Lineup</th>
          <th class="sortable" data-key="size" data-numeric>Party</th>
          <th class="num sortable" data-key="syn" data-numeric>Synergy</th>
          <th class="num sortable" data-key="wr" data-numeric>Winrate</th>
          <th class="num">Record</th>
          <th class="num sortable sorted" data-key="games" data-numeric data-dir="desc">Games</th>
          <th class="num sortable" data-key="flex" data-numeric>Flex</th>
          <th class="num sortable" data-key="fives" data-numeric>5s</th></tr></thead>
          <tbody>{party_rows}</tbody>
        </table>
      </details>'''

    return f'''
    <div class="panel">
      <h2 style="margin-bottom:4px;">Duo synergy</h2>
      <p class="panel-hint" style="margin:6px 0 14px;">Ranked Solo/Duo. Winrate together, coloured
      by how far it beats the winrate those two average apart.</p>
      <div class="duo-controls">
        <div class="duo-scale" aria-hidden="true">
          <span class="duo-carry-key"><i></i> carries the pair</span>
          <span>worse together</span>
          <span class="sw lift-down-2"></span><span class="sw lift-down-1"></span>
          <span class="sw lift-flat"></span>
          <span class="sw lift-up-1"></span><span class="sw lift-up-2"></span>
          <span>better</span>
        </div>
      </div>
      <div class="duo-matrix-wrap">
        <table class="duo-matrix">
          <thead><tr><td></td>{head}</tr></thead>
          <tbody>{"".join(body)}</tbody>
        </table>
      </div>
      <div class="duo-highlights" data-duo-highlights></div>
      <div class="awards duo-cards">{render_award_tiles(duo_cards(friends, rows, datetime.now()), friends)}</div>
      {coverage_note}
      <div class="duo-detail" data-duo-detail hidden></div>
      <details class="matches-details duo-table-details" style="margin-top:12px;">
        <summary>Ranked Pairs</summary>

        <table class="matches-table duo-table" data-sortable>
          <thead><tr><th class="num">#</th>
          <th class="sortable sorted" data-key="pair" data-dir="asc">Pair</th>
          <th class="num sortable" data-key="syn" data-numeric>Synergy</th>
          <th class="num sortable" data-key="wr" data-numeric>Winrate</th>
          <th class="num">Record</th>
          <th class="num sortable" data-key="games" data-numeric>Games</th>
          <th class="num sortable" data-key="boost" data-numeric>Booster</th></tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
      </details>
      {party_table}</div>'''


def week_tiles(friends_sorted, rank_history, now):
    """Nine readings on the last seven days, in a fixed order."""
    cut = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week = {f["label"]: [m for m in f.get("seasonMatches", [])
                         if not m.get("remake") and (m.get("dateKey") or "") >= cut]
            for f in friends_sorted}
    tiles = []

    def mins(ms):
        return format_minutes(sum(m.get("durationMin", 0) for m in ms))

    everyone = [m for ms in week.values() for m in ms]
    # Both of the next two rank on the same thing, so it is built once.
    per_player = sorted(((label, len(ms), len(ms)) for label, ms in week.items()),
                        key=lambda r: -r[1])
    if everyone:
        tiles.append(("\U0001f4bb", "Total games this week",
                      f'<strong>{len(everyone)}</strong> ranked games, {mins(everyone)} of League.',
                      _detail("Every ranked game any of them played in the last seven days, "
                              "remakes excluded. The table is who contributed what.",
                              per_player, " games", 0)))

    busiest = max(week.items(), key=lambda kv: len(kv[1]), default=None)
    if busiest and busiest[1]:
        tiles.append(("\u23f1\ufe0f", "Most active player",
                      f'{esc(busiest[0])} played <strong>{len(busiest[1])}</strong> games, '
                      f'{mins(busiest[1])}.',
                      _detail("Ranked games played in the last seven days.",
                              per_player, " games", 0)))

    # A shared game counted once, not once per player who was in it.
    shared = {}
    for label, ms in week.items():
        for m in ms:
            if _DUO_CTX["map"].get((m.get("matchId"), label)):
                shared[m["matchId"]] = m
    if shared:
        in_shared = sorted(
            ((label, sum(1 for m in ms if _DUO_CTX["map"].get((m.get("matchId"), label))),
              len(ms)) for label, ms in week.items()),
            key=lambda r: -r[1])
        tiles.append(("\U0001f465", "Games played together",
                      f'<strong>{len(shared)}</strong> games were played together, '
                      f'{mins(shared.values())} of League.',
                      _detail("Games in the last seven days with two or more of them on the "
                              "same team, counted once each however many were in it. The "
                              "table is how many of those each person appeared in, so it "
                              "sums to more than the total.",
                              in_shared, " games", 0)))

    climber = weekly_rank_leader(rank_history, now)
    if climber and climber.get("text"):
        gained = abs(climber.get("lp") or 0)
        moved = (climber.get("fromLabel") and climber.get("toLabel")
                 and climber["fromLabel"] != climber["toLabel"])
        where = (f' and climbed from {climber["fromLabel"]} to {climber["toLabel"]}'
                 if moved else '')
        moves = []
        by_label = {}
        for h in rank_history:
            if h.get("queue") == "solo":
                by_label.setdefault(h["label"], []).append(h)
        cut = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        for label, pts in by_label.items():
            pts.sort(key=lambda h: h["date"])
            pair = week_window(pts, cut)
            if pair:
                moves.append((label, tier_score(pair[1]) - tier_score(pair[0]), len(pts)))
        moves.sort(key=lambda r: -r[1])
        tiles.append(("\U0001f4c8", "Biggest climber",
                      f'{esc(climber["label"])} gained <strong>{gained}</strong> LP this week'
                      f'{where}.',
                      _detail("Ladder position at the end of the week minus its position at "
                              "the start, in LP, from the daily rank snapshots. Anyone "
                              "without a snapshot at both ends of the window cannot be "
                              "measured.",
                              moves, " LP", 0)))

    form = [(100 * sum(1 for m in ms if m["win"]) / len(ms), label, ms)
            for label, ms in week.items() if len(ms) >= 5]
    if form:
        rate, label, ms = max(form)
        wins = sum(1 for m in ms if m["win"])
        thin = [(l, f"{len(m)} games, needs 5") for l, m in week.items() if 0 < len(m) < 5]
        tiles.append(("\U0001f525", "Hottest streak",
                      f'{esc(label)} is winning <strong>{rate:.0f}%</strong> this week, '
                      f'{wins}W {len(ms) - wins}L.',
                      _detail("Winrate over the last seven days, for anyone with at least "
                              "five games in that window.",
                              sorted(((l, r, len(m)) for r, l, m in form), key=lambda x: -x[1]),
                              "%", 1, excluded=thin)))

    # A champion two or more of them picked up this week, ranked by how the
    # group did on it rather than by how any one of them did.
    shared_champs = {}
    for label, ms in week.items():
        for m in ms:
            st = shared_champs.setdefault(m["champion"], {"players": set(), "games": 0, "wins": 0})
            st["players"].add(label)
            st["games"] += 1
            st["wins"] += 1 if m["win"] else 0
    herd = [(100 * v["wins"] / v["games"], c, v) for c, v in shared_champs.items()
            if len(v["players"]) >= 2 and v["games"] >= 4]
    if herd:
        rate, champ, v = max(herd)
        n_players = len(v["players"])
        tiles.append(("\U0001f43e", "Animal of the week",
                      f'{esc(champion_display(champ))} was played by <strong>{n_players}</strong> '
                      f'people and had a winrate of {rate:.0f}% across {v["games"]} games.',
                      _detail("Champions at least two of them picked this week, over at least "
                              "four games between them, ranked by the group's winrate on it "
                              "rather than by any one person's.",
                              sorted(((champion_display(c), r, vv["games"]) for r, c, vv in herd),
                                     key=lambda x: -x[1]),
                              "%", 1, players=False)))

    # Pick rate averaged over the players who played at all, so a champion one
    # person spams does not beat one everybody reaches for.
    loved = {}
    for label, ms in week.items():
        if not ms:
            continue
        for champ in {m["champion"] for m in ms}:
            n = sum(1 for m in ms if m["champion"] == champ)
            loved.setdefault(champ, []).append(100 * n / len(ms))
    active = sum(1 for ms in week.values() if ms)
    rated = [(sum(v) / active, c, len(v)) for c, v in loved.items()
             if active and len(v) >= 2]
    if rated:
        rate, champ, players = max(rated)
        tiles.append(("\u2764\ufe0f", "Most loved champion",
                      f'{esc(champion_display(champ))} was picked <strong>{rate:.0f}%</strong> on '
                      f'average across the group this week.',
                      _detail("Each person's pick rate for a champion this week, averaged over "
                              "everyone who played at all. Averaging rather than totalling "
                              "stops one person spamming a champion beating one everybody "
                              "reaches for. Needs two or more players.",
                              sorted(((champion_display(c), sum(v) / active, len(v))
                                      for c, v in loved.items() if len(v) >= 2),
                                     key=lambda x: -x[1]),
                              "%", 1, players=False)))

    pool = [(len({m["champion"] for m in ms}), label, len(ms))
            for label, ms in week.items() if ms]
    if pool:
        n, label, games = max(pool)
        tiles.append(("\U0001f9ec", "Adaptable",
                      f'{esc(label)} played <strong>{n}</strong> different champions in '
                      f'{games} games.',
                      _detail("Distinct champions played in the last seven days. Not adjusted "
                              "for how many games each played, so more games makes a wider "
                              "pool easier.",
                              sorted(((l, c, g) for c, l, g in pool), key=lambda x: -x[1]),
                              " champions", 0)))

    # Untouched in the week before this one, and under 5% of their picks
    # before that. "Never played this season" ruled out anyone coming back to
    # something after a long gap, which is exactly the case worth naming.
    GRASSHOPPER_MAX_SHARE = 5.0
    prev_cut = (now - timedelta(days=14)).strftime("%Y-%m-%d")
    fresh = []
    for f in friends_sorted:
        played = [m for m in f.get("seasonMatches", []) if not m.get("remake")]
        earlier = [m for m in played if (m.get("dateKey") or "") < cut]
        prev_week = {m["champion"] for m in earlier
                     if (m.get("dateKey") or "") >= prev_cut}
        counts = {}
        for m in week.get(f["label"], []):
            counts[m["champion"]] = counts.get(m["champion"], 0) + 1
        for champ in sorted(counts):
            if counts[champ] < 2 or champ in prev_week:
                continue
            share = (100 * sum(1 for m in earlier if m["champion"] == champ) / len(earlier)
                     if earlier else 0.0)
            if share >= GRASSHOPPER_MAX_SHARE:
                continue
            fresh.append((counts[champ], f["label"], champ))
    if fresh:
        n, label, champ = max(fresh)
        tiles.append(("\U0001f997", "Grasshopper",
                      f'{esc(label)} picked up {esc(champion_display(champ))} and played it '
                      f'<strong>{n}</strong> time{"s" if n != 1 else ""} already.',
                      _detail(f"Champions played at least twice this week that they had not "
                              f"touched in the seven days before, and that were under "
                              f"{GRASSHOPPER_MAX_SHARE:.0f}% of their picks before that. "
                              f"Ranked by games this week.",
                              sorted(((f"{l} on {champion_display(c)}", cnt, cnt)
                                      for cnt, l, c in fresh), key=lambda x: -x[1]),
                              " games", 0, players=False)))

    return in_declared_order(tiles, WEEK_TILE_ORDER, lambda t: t[1])


def duo_cards(friends, rows, now):
    """Six readings on the pairs, from the same numbers the grid is built on."""
    listed = [r for r in rows if r["total"]["games"] >= 2]
    if not listed:
        return []
    cards = []

    def name(r):
        return f'{esc(r["a"])} &amp; {esc(r["b"])}'

    def pair_label(r):
        return f'{r["a"]} & {r["b"]}'

    # Every pair, however few games, so a card that applies a threshold can
    # show who the threshold excluded rather than just omitting them.
    thin = [(pair_label(r), f'{r["total"]["games"]} games, needs {DUO_THIN_GAMES}')
            for r in listed if r["total"]["games"] < DUO_THIN_GAMES]

    most = max(listed, key=lambda r: r["total"]["games"])
    cards.append(("\U0001f496", "Lovers",
                  f'{name(most)} have played <strong>{most["total"]["games"]}</strong> games '
                  f'together.',
                  _detail("Games with both of them on the same team, in any ranked queue. "
                          "Every pair with at least two games is listed.",
                          sorted(((pair_label(r), r["total"]["games"], r["total"]["games"])
                                  for r in listed), key=lambda x: -x[1]),
                          " games", 0, players=False)))

    rated = [r for r in listed if r["total"]["games"] >= DUO_THIN_GAMES]
    if rated:
        by_wr = sorted(((pair_label(r), r["total"]["winrate"], r["total"]["games"])
                        for r in rated), key=lambda x: -x[1])
        best = max(rated, key=lambda r: r["total"]["winrate"])
        cards.append(("\U0001f48d", "Perfect couple",
                      f'{name(best)} win <strong>{best["total"]["winrate"]}%</strong> of '
                      f'{best["total"]["games"]} games together.',
                      _detail(f"Winrate in games the pair played together, over at least "
                              f"{DUO_THIN_GAMES} games. Below that a winrate is one evening.",
                              by_wr, "%", 1, players=False, excluded=thin)))
        lifted = [r for r in rated if r["total"]["lift"] is not None]
        if lifted:
            top = max(lifted, key=lambda r: r["total"]["lift"])
            cards.append(("\U0001f331", "Healthy relationship",
                          f'{name(top)} beat their own winrates by '
                          f'<strong>{top["total"]["lift"]:+.1f}%</strong> when they queue together.',
                          _detail("The pair's winrate together minus what the two of them "
                                  "average apart. Positive means they are better as a pair "
                                  "than the sum of their parts, which is not the same as "
                                  "winning the most.",
                                  sorted(((pair_label(r), r["total"]["lift"], r["total"]["games"])
                                          for r in lifted), key=lambda x: -x[1]),
                                  "%", 1, players=False, excluded=thin)))
        worst = min(rated, key=lambda r: r["total"]["winrate"])
        cards.append(("\U0001f3b0", "Vegas wedding",
                      f'{name(worst)} win <strong>{worst["total"]["winrate"]}%</strong> of '
                      f'{worst["total"]["games"]}. It might be time to split up.',
                      _detail(f"The same table as Perfect couple, read from the bottom: "
                              f"lowest winrate together over at least {DUO_THIN_GAMES} games.",
                              list(reversed(by_wr)), "%", 1, players=False, excluded=thin)))

    # When each pair last shared a game, so the ones who have drifted show up.
    last_seen = {}
    for f in friends:
        for m in f.get("seasonMatches", []):
            if m.get("remake"):
                continue
            for mate, _v in (_DUO_CTX["map"].get((m.get("matchId"), f["label"])) or []):
                key = tuple(sorted([f["label"], mate]))
                ms = m.get("gameStartMs") or 0
                if ms > last_seen.get(key, 0):
                    last_seen[key] = ms
    stale = [(ms, k) for k, ms in last_seen.items() if ms]
    if stale:
        ms, key = min(stale)
        days = (now - datetime.fromtimestamp(ms / 1000)).days
        gaps = sorted(((f"{k[0]} & {k[1]}",
                        (now - datetime.fromtimestamp(v / 1000)).days, 0)
                       for k, v in last_seen.items() if v), key=lambda x: -x[1])
        cards.append(("\U0001f494", "Exes",
                      f'{esc(key[0])} &amp; {esc(key[1])} have not queued together in '
                      f'<strong>{days}</strong> days.',
                      _detail("Days since each pair last shared a game. Pairs who have never "
                              "played together at all are not here: this measures drifting "
                              "apart, not never having met.",
                              gaps, " days", 0, players=False)))

    # A pair who do better together than either does with their usual partner.
    by_player = {}
    for r in listed:
        for who, other in ((r["a"], r["b"]), (r["b"], r["a"])):
            by_player.setdefault(who, []).append(r)
    sneaky, sneaky_all = None, []
    for who, rs in by_player.items():
        usual = max(rs, key=lambda r: r["total"]["games"])
        for r in rs:
            if r is usual or r["total"]["games"] < DUO_THIN_GAMES:
                continue
            if r["total"]["winrate"] <= usual["total"]["winrate"]:
                continue
            gap = r["total"]["winrate"] - usual["total"]["winrate"]
            sneaky_all.append((gap, who, r, usual))
            if sneaky is None or gap > sneaky[0]:
                sneaky = (gap, who, r, usual)
    if sneaky:
        gap, who, r, usual = sneaky
        cands = sorted(((f'{w} with {(rr["b"] if rr["a"] == w else rr["a"])}', g, rr["total"]["games"])
                        for g, w, rr, _u in sneaky_all), key=lambda x: -x[1])
        cards.append(("\U0001f92b", "Sneaky link",
                      f'{name(r)} win <strong>{r["total"]["winrate"]}%</strong> together, '
                      f'{gap:.1f}% better than with their usual partners.',
                      _detail("For each person, their winrate with someone other than their "
                              "most-played partner, minus their winrate with that usual "
                              "partner. The biggest such gap wins. Only pairs over the "
                              "minimum game count are considered.",
                              cands, "% better", 1, players=False)))

    return in_declared_order(cards, DUO_CARD_ORDER, lambda c: c[1])


def group_top_champions(friends, limit=10):
    """The highest rated champion performances anywhere in the group."""
    out = []
    for f in friends:
        played = [m for m in f.get("seasonMatches", []) if not m.get("remake")]
        if not played:
            continue
        for r in top_champions(played, champion_matchups(played), limit=limit):
            out.append(dict(r, player=f["label"]))
    out.sort(key=lambda r: (-r["rating"], -r["games"]))
    return out[:limit]


def render_week_glance_panel(friends_sorted, awards, rank_history, now):
    tiles = week_tiles(friends_sorted, rank_history, now)
    if not tiles:
        return ""
    return f'''
    <div class="panel">
      <h2 style="margin-bottom:14px;">This week at a glance</h2>
      <div class="awards">{render_award_tiles(tiles, friends_sorted)}</div>
    </div>'''


def _detail(method, rows, unit="", places=2, players=True, excluded=None):
    """Working for a card that ranked things itself.

    `rows` is (label, value, count). `players` says whether those labels are
    people, which decides whether they are painted in someone's colour: a
    champion in Winny's blue reads as Winny.
    """
    return {
        "method": method,
        "unit": unit,
        "places": places,
        "excluded": excluded or [],
        "standings": [{"label": lbl, "value": val, "games": n,
                       **({} if players else {"colour": None})}
                      for lbl, val, n in rows],
    }


def render_award_why(detail):
    """The working behind a card: how the number was reached, and everyone
    else's, in order.

    Folded away by default. The claim is the point of the card; the arithmetic
    is what you go looking for once you disagree with it.
    """
    if not detail:
        return ""
    rows = detail.get("standings") or []
    if not rows:
        return ""
    places = detail.get("places", 2)
    unit = detail.get("unit", "")
    top = rows[0]["value"]

    # On a card that ranks by games played, a Games column repeats the Value
    # column exactly. Drop it rather than print the same number twice.
    show_games = any(r.get("games") for r in rows) and not all(
        abs(r["value"] - r.get("games", 0)) < 1e-9 for r in rows)

    def cell(r, n):
        gap = r["value"] - top
        # Just the size of the gap, with the word "behind" once in the column
        # heading rather than on every row. Repeating it cost more width than
        # the numbers did, in a table that has to fit a card three to a row.
        gap_txt = f'{abs(gap):,.{places}f}' if n > 1 and gap else ""
        colour = r.get("colour", friend_colour(r["label"]))
        name = (f'<b style="color:var({colour});">{esc(r["label"])}</b>' if colour
                else f'<b>{esc(r["label"])}</b>')
        return (f'<tr><td class="num muted small">{n}</td>'
                f'<td class="why-name">{name}</td>'
                f'<td class="num"><b>{r["value"]:,.{places}f}</b></td>'
                + (f'<td class="num muted small">{r["games"]}</td>' if show_games else "")
                + f'<td class="num why-gap">{gap_txt}</td></tr>')

    body = "".join(cell(r, n) for n, r in enumerate(rows, start=1))
    method = detail.get("method")
    method_html = f'<div class="why-method">{method}</div>' if method else ""
    excluded = detail.get("excluded") or []
    excl_html = ""
    if excluded:
        items = ", ".join(f"{esc(lbl)} ({esc(why)})" for lbl, why in excluded)
        excl_html = f'<div class="why-excluded">Not measured: {items}</div>'
    # The unit is written once, in the heading, rather than after every
    # number. "per takedown" on each of seven rows was most of the width of
    # the column it was in.
    unit_html = f'<span class="why-unit">{esc(unit.strip())}</span>' if unit.strip() else ""
    games_head = esc(detail.get("games_label", "Games")).replace("Season games", "Games")
    return (f'<details class="award-why"><summary>How this was worked out</summary>'
            f'{method_html}'
            f'<div class="why-scroll"><table class="why-table">'
            f'<thead><tr><th class="num">#</th><th>Player</th>'
            f'<th class="num">Value{unit_html}</th>'
            + (f'<th class="num">{games_head}</th>' if show_games else "")
            + f'<th class="num">Behind</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>'
            f'{excl_html}</details>')


def render_award_tiles(tiles, friends_sorted):
    """Award cards, each striped in the colour of whoever it names.

    A card about two people gets both: the first named at the top, the second
    at the bottom, blended through the middle. Longest name first so "Shas2nd"
    is not read as "Shas", and each match is masked out of the text so the
    shorter name cannot then match inside it.
    """
    labels = sorted((f["label"] for f in friends_sorted), key=len, reverse=True)

    def named_in(text):
        masked, found = text, []
        for l in labels:
            i = masked.find(l)
            if i >= 0:
                found.append((i, l))
                masked = masked[:i] + ("\x00" * len(l)) + masked[i + len(l):]
        return [l for _i, l in sorted(found)]

    def style(text):
        who = named_in(text)
        if not who:
            return ""
        if len(who) == 1:
            return f' style="--award-colour: var({friend_colour(who[0])});"'
        a, b = friend_colour(who[0]), friend_colour(who[1])
        return (f' style="--award-colour: linear-gradient(180deg, var({a}) 0%, '
                f'var({a}) 20%, var({b}) 80%, var({b}) 100%);"')

    def one(tile):
        icon, title, text = tile[0], tile[1], tile[2]
        detail = tile[3] if len(tile) > 3 else None
        return (f'<div class="award"{style(text)}><div class="award-icon">{icon}</div>'
                f'<div class="award-body">'
                f'<div class="award-title">{esc(title)}</div>'
                f'<div class="award-text">{text}</div>'
                f'{render_award_why(detail)}'
                f'</div></div>')

    return "".join(one(t) for t in tiles)


def render_season_highlights_panel(friends_sorted, now):
    cards = season_highlights(friends_sorted, now)
    if not cards:
        return ""
    tiles = [(c["icon"], c["title"], c["text"], c) for c in cards]
    return f'''
    <div class="panel">
      <h2 style="margin-bottom:14px;">Season highlights</h2>
      <div class="awards">{render_award_tiles(tiles, friends_sorted)}</div>
    </div>'''


def render_group_top_champions(friends_sorted):
    rows = group_top_champions(friends_sorted)
    if not rows:
        return ""
    body = "".join(
        f'<tr><td class="num muted small">{n}</td>'
        f'<td class="champ-cell"><span class="cc">'
        f'{render_champion_icon(r["champion"], size=20)}'
        f'{esc(champion_display(r["champion"]))}</span></td>'
        f'<td class="nowrap"><b style="color:var({friend_colour(r["player"])});">'
        f'{esc(r["player"])}</b></td>'
        f'<td class="num"><b>{r["rating"]}</b></td>'
        f'<td class="num">{r["games"]}</td>'
        f'<td class="num">{r["winrate"]}%</td></tr>'
        for n, r in enumerate(rows, start=1)
    )
    return f'''
      <div class="muted small" style="margin:18px 0 8px;">Top champions across everyone</div>
      <div class="table-scroll">
        <table class="matches-table group-top">
          <thead><tr><th class="num">#</th><th>Champion</th><th>Player</th>
          <th class="num">Rating</th><th class="num">Games</th>
          <th class="num">Winrate</th></tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>'''


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

  // One place a player's colour is decided, matching friend_colour() on the
  // server. Also lent to the live-refresh block so a row it adds is tinted
  // with exactly the blend the server would have used.
  function colourFor(label) { return (D && D.varByLabel && D.varByLabel[label]) || '--accent'; }

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
    // delta is ladder position, linear at 100 LP per division, so it is a
    // real LP count across a promotion. See lp_step_label().
    var amount = (delta >= 0 ? '+' : '\u2212') + fixed(Math.abs(delta), 0) + ' LP' +
                 '';
    var a = ladderDecompose(prevValue), b = ladderDecompose(value);
    if (a[0] !== b[0] || a[1] !== b[1]) {
      return (delta >= 0 ? 'Promoted ' : 'Demoted ') + amount;
    }
    return amount;
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
    var MIN_LABEL_GAP = 25, ICON_SIZE = 14, out = [];
    entries.sort(function (a, b) { return a.ly - b.ly; });
    entries.forEach(function (e, i) {
      e.drawY = i === 0 ? e.ly : Math.max(e.ly, entries[i - 1].drawY + MIN_LABEL_GAP);
    });
    entries.forEach(function (e) {
      var anchorX = gutterX === null ? e.lx : gutterX;
      var parts = [];
      // No leader line; see the note in end_label_groups().
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
        parts.push('<text x="' + fixed(textX, 1) + '" y="' + fixed(e.drawY + 14, 1) +
          '" font-size="9.5" fill="var(--muted)">' + esc(e.net.text) + '</text>');
      }
      out.push('<g id="' + prefix + '-label-' + e.idx + '">' + parts.join('') + '</g>');
    });
    return out;
  }

  // Port of projection_params()/project_scores(). MINSTD is used on both
  // sides because 16807 * 2147483646 still lands inside a double's exact
  // integer range, so Python and JavaScript walk the same sequence.
  function projectionParams(tl) {
    var rows = [];
    for (var n = 1; n < tl.length; n++) {
      if (tl[n].match) rows.push([!!tl[n].match.win, tl[n].delta || 0]);
    }
    rows = rows.slice(Math.max(0, rows.length - 50));
    if (!rows.length) return null;
    var gains = [], drops = [];
    rows.forEach(function (r) { if (r[0]) gains.push(r[1]); else drops.push(-r[1]); });
    if (!gains.length || !drops.length) return null;
    function sum(a) { var t = 0; for (var i = 0; i < a.length; i++) t += a[i]; return t; }
    return [gains.length / rows.length, sum(gains) / gains.length, sum(drops) / drops.length];
  }

  function projectScores(start, n, pWin, gain, drop, seed) {
    var st = (seed * 104729) % 2147483646 + 1, out = [], score = start;
    for (var k = 0; k < n; k++) {
      st = (st * 16807) % 2147483647;
      score = (st / 2147483647.0 < pWin) ? score + gain : score - drop;
      if (score < 0) score = 0;
      out.push(score);
    }
    return out;
  }

  // -------------------------------------------------------------------------
  // The game list under the chart. Port of lp_row() and the helpers it uses.
  //
  // It was the one part of this panel a refresh could not touch: the rows are
  // ordered across every player at once and each one carries an LP step that
  // only exists once the whole timeline is rebuilt, so patching a row in was
  // never possible. Rebuilt wholesale here instead, from the same state the
  // chart is drawn from, and verifySelf() compares it against the server's
  // rows the same way it compares the SVGs.
  // -------------------------------------------------------------------------
  var MONTHS_LP = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function whenTextLp(ms) {
    if (!ms) return '\u2013';
    var d = new Date(ms), h = d.getHours(), h12 = h % 12 || 12;
    return MONTHS_LP[d.getMonth()] + ' ' + ('0' + d.getDate()).slice(-2) + ', ' +
           h12 + ':' + ('0' + d.getMinutes()).slice(-2) + ' ' + (h >= 12 ? 'PM' : 'AM');
  }

  // Match data reports Data Dragon's key, so "Nunu" is really "Nunu &
  // Willump" and "MissFortune" is "Miss Fortune". The icon map is keyed by
  // the real name, so inverting it gives the spelling a person would write.
  // Port of champion_display(); the server prints the same, and verifySelf()
  // is what noticed when it did not.
  var _DISPLAY = null;
  function champDisplay(name) {
    if (!name) return name;
    var icons = D.champIcons || {};
    if (Object.prototype.hasOwnProperty.call(icons, name)) return name;
    if (!_DISPLAY) {
      _DISPLAY = { exact: {}, fold: {} };
      for (var k in icons) {
        _DISPLAY.exact[icons[k]] = k;
        _DISPLAY.fold[String(icons[k]).toLowerCase()] = k;
      }
    }
    return _DISPLAY.exact[name] || _DISPLAY.fold[String(name).toLowerCase()] || name;
  }

  // Same fallbacks as champion_icon_url(): the map is keyed by display name,
  // match data reports the Data Dragon key, and Riot's own casing differs
  // between the two for at least one champion.
  function champIconLp(name, size) {
    var icons = D.champIcons || {}, slug = icons[name];
    if (!slug && name) {
      var want = String(name).toLowerCase();
      for (var k in icons) {
        if (icons[k] === name) { slug = icons[k]; break; }
      }
      if (!slug) {
        for (var k2 in icons) {
          if (icons[k2].toLowerCase() === want) { slug = icons[k2]; break; }
        }
      }
    }
    if (!D.ddragonVersion || !slug) {
      return '<span class="champ-icon champ-icon-ph" style="width:' + size +
             'px;height:' + size + 'px;"></span>';
    }
    return '<img src="' + esc('https://ddragon.leagueoflegends.com/cdn/' +
      D.ddragonVersion + '/img/champion/' + slug + '.png') +
      '" alt="" class="champ-icon" width="' + size + '" height="' + size +
      '" loading="lazy" onerror="this.style.visibility=&#x27;hidden&#x27;">';
  }

  // Port of blend_vars(): one colour for a shared game, the same one whichever
  // row of it you are looking at.
  function blendVars(vars) {
    var acc = 'var(' + vars[0] + ')';
    for (var i = 1; i < vars.length; i++) {
      acc = 'color-mix(in srgb, ' + acc + ' ' + fixed(i / (i + 1) * 100, 0) +
            '%, var(' + vars[i] + '))';
    }
    return acc;
  }

  function matesFor(matchId, label, win) {
    var side = (D.duoSides || {})[matchId];
    if (!side) return [];
    var out = [];
    side.forEach(function (e) {
      if (e[0] !== label && !!e[1] === !!win) {
        out.push([e[0], (D.varByLabel || {})[e[0]] || '--muted']);
      }
    });
    out.sort(function (a, b) { return a[0] < b[0] ? -1 : (a[0] > b[0] ? 1 : 0); });
    return out;
  }

  function tableHtml(state) {
    var events = [];
    state.friends.forEach(function (f, i) {
      var tl = state.timelines[f.label];
      tl.forEach(function (pt, n) {
        if (!pt.match) return;
        events.push({ label: f.label, varName: colourFor(f.label), idx: pt.idx, point: pt,
                      prevScore: tl[n - 1].score, match: pt.match,
                      when: pt.match.gameStartMs || 0 });
      });
    });
    // Newest first, with the rows of one game kept together; mirrors the sort
    // key in render_lp_chart().
    events.sort(function (a, b) {
      if (a.when !== b.when) return b.when - a.when;
      var am = a.match.matchId || '', bm = b.match.matchId || '';
      if (am !== bm) return am < bm ? -1 : 1;
      return a.label < b.label ? -1 : (a.label > b.label ? 1 : 0);
    });

    return events.map(function (e, n) {
      var m = e.match, pt = e.point;
      var move = lpStepLabel(e.prevScore, pt.score, pt.delta, pt.exact);
      var moveCls = (pt.delta || 0) >= 0 ? 'up' : 'down';
      var mates = matesFor(m.matchId, e.label, m.win);
      var party = 1 + mates.length;
      var rowCls = '', band = '';
      if (party > 1) {
        var mid = m.matchId || '';
        var first = n === 0 || (events[n - 1].match.matchId || '') !== mid;
        var last = n === events.length - 1 || (events[n + 1].match.matchId || '') !== mid;
        rowCls = 'party party-' + Math.min(party, 5) +
                 (first ? ' g-first' : '') + (last ? ' g-last' : '');
        var vars = [e.varName];
        mates.forEach(function (x) { vars.push(x[1]); });
        vars.sort();
        band = '--band: ' + blendVars(vars) + ';';
      }
      var withCell;
      if (!mates.length) {
        withCell = '<span class="muted">&ndash;</span>';
      } else {
        var names = mates.map(function (x) {
          return '<span class="mate" style="color:var(' + x[1] + ');">' + esc(x[0]) + '</span>';
        }).join('');
        var who = mates.map(function (x) { return x[0]; }).join(', ');
        withCell = '<span class="duo-with" title="Played this game with ' + esc(who) + '">' +
          '<span class="duo-with-icon" aria-hidden="true">\u21c4</span>' + names + '</span>';
      }
      return '<tr class="' + rowCls + '"' + (band ? ' style="' + band + '"' : '') + '>' +
        '<td class="muted small nowrap">' + esc(whenTextLp(m.gameStartMs)) + '</td>' +
        '<td class="nowrap"><b style="color:var(' + e.varName + ');">' + esc(e.label) + '</b>' +
        '<span class="muted small"> &middot; game ' + esc(e.idx) + '</span></td>' +
        '<td><span class="tag ' + (m.win ? 'win' : 'loss') + '">' + (m.win ? 'W' : 'L') +
        '</span></td>' +
        '<td class="champ-cell"><span class="cc">' + champIconLp(m.champion, 18) +
        esc(champDisplay(m.champion)) + '</span></td>' +
        '<td class="with-cell">' + withCell + '</td>' +
        '<td class="num lp-move ' + moveCls + '">' + esc(move) + '</td>' +
        '<td class="num nowrap">' + scoreToRankLabel(pt.score) + '</td></tr>';
    }).join('');
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
    // Everyone extended to the leader's game count; see render_lp_chart().
    var proj = {};
    if (!tail) {
      friends.forEach(function (pf, pi) {
        var pv = view[pf.label], left = maxGames - (pv.length - 1);
        if (left <= 0) return;
        var params = projectionParams(timelines[pf.label]);
        if (!params) return;
        proj[pf.label] = projectScores(pv[pv.length - 1].score, left,
                                       params[0], params[1], params[2], pi + 1);
      });
    }
    var scores = [];
    Object.keys(view).forEach(function (k) {
      view[k].forEach(function (p) { scores.push(p.score); });
    });
    Object.keys(proj).forEach(function (k) {
      proj[k].forEach(function (sc) { scores.push(sc); });
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
      // No right-hand gutter; see render_lp_chart().
      PAD_L = 64; PAD_R = 24; PAD_T = 16; PAD_B = 34;
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
      if (tick % tierSpan === 0) yTicks.push([xy(0, tick)[1], cap(D.tierOrder[dec[0]]), true]);
      else if (showDivisions) yTicks.push([xy(0, tick)[1], rankBySc(dec[1]), false]);
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
      var varName = colourFor(f.label);
      var tl = view[f.label];
      var coords = tl.map(function (p) { return xy(p.idx, p.score); });
      var parts = [];
      var d = coords.map(function (c, n) {
        return (n === 0 ? 'M' : 'L') + fixed(c[0], 1) + ',' + fixed(c[1], 1);
      }).join(' ');
      parts.push('<path d="' + d + '" fill="none" stroke="var(' + varName +
                 ')" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />');
      tl.forEach(function (p, n) {
        var m = p.match, title;
        if (m) {
          var move = lpStepLabel(p.prevScore, p.score, p.delta, p.exact);
          title = (f.label + ' \u00b7 game ' + (p.origIdx === undefined ? p.idx : p.origIdx) +
                   ' \u00b7 ' + (m.win ? 'Win' : 'Loss') + ' on ' + champDisplay(m.champion) +
                   ' \u00b7 ' +
                   move + ' \u2192 ' + scoreToRankLabel(p.score)).replace('&middot;', '\u00b7');
        } else {
          title = (f.label + ' \u00b7 tracking started \u00b7 ' +
                   scoreToRankLabel(p.score)).replace('&middot;', '\u00b7');
        }
        // Only where the line ends; see the note in render_lp_chart(). The
        // rest stay as invisible hit targets so every game is still hoverable.
        var fill = 'var(' + varName + ')', r, extra, cls;
        if (n === tl.length - 1) {
          r = compact ? 3.5 : 4;
          extra = ' stroke="var(--surface-1)" stroke-width="1.5"';
          cls = 'pt end';
        } else {
          r = 3;
          extra = '';
          cls = 'pt';
        }
        parts.push('<circle class="' + cls + '" cx="' + fixed(coords[n][0], 1) + '" cy="' +
          fixed(coords[n][1], 1) + '" r="' + r + '" fill="' + fill + '"' + extra + '>' +
          '<title>' + esc(title) + '</title></circle>');
      });
      var walk = proj[f.label];
      if (walk) {
        var walkXY = [coords[coords.length - 1]];
        walk.forEach(function (sc, k) { walkXY.push(xy(tl.length - 1 + k + 1, sc)); });
        var walkD = walkXY.map(function (c, n) {
          return (n === 0 ? 'M' : 'L') + fixed(c[0], 1) + ',' + fixed(c[1], 1);
        }).join(' ');
        var walkTitle = (f.label + ' \u00b7 projected \u00b7 ' + walk.length +
          ' more games at their current form \u2192 ' +
          scoreToRankLabel(walk[walk.length - 1])).replace('&middot;', '\u00b7');
        parts.push('<path class="proj" d="' + walkD + '" fill="none" stroke="var(' + varName +
          ')" stroke-width="1.5" stroke-dasharray="5 5" stroke-linecap="round" ' +
          'opacity="0.45"><title>' + esc(walkTitle) + '</title></path>');
      }
      seriesGroups.push('<g id="' + prefix + '-series-' + fi + '">' + parts.join('') + '</g>');

      // Gutter labels removed; the legend under the chart is the key.
    });

    var labelGroups = [];

    // Port of tier_bands().
    var bandSvg = '';
    (function () {
      var span = D.divisionsPerTier * D.lpPerDivision;
      var first = Math.floor(yMin / span), last = Math.floor(yMax / span), parts = [];
      for (var ti = Math.max(first, 0); ti <= last; ti++) {
        if (ti >= D.tierOrder.length) break;
        var lo = Math.max(ti * span, yMin), hi = Math.min((ti + 1) * span, yMax);
        if (hi <= lo) continue;
        var top = xy(0, hi)[1], bottom = xy(0, lo)[1];
        parts.push('<rect class="tier-band" x="' + fixed(PAD_L, 1) + '" y="' + fixed(top, 1) +
          '" width="' + fixed(W - PAD_R - PAD_L, 1) + '" height="' + fixed(bottom - top, 1) +
          '" fill="color-mix(in srgb, var(--tier-' + D.tierOrder[ti].toLowerCase() + ') ' +
          D.tierBandAlpha + '%, transparent)" />');
      }
      bandSvg = parts.join('');
    })();

    var gridSvg = yTicks.map(function (t) {
      var faint = t[2] ? '' : ' faint';
      return '<line x1="' + PAD_L + '" y1="' + fixed(t[0], 1) + '" x2="' + (W - PAD_R) +
        '" y2="' + fixed(t[0], 1) + '" class="chart-grid' + faint + '" /><text x="' + (PAD_L - 6) +
        '" y="' + fixed(t[0] + 4, 1) + '" text-anchor="end" class="chart-tick' + faint + '">' +
        esc(t[1]) + '</text>';
    }).join('');
    var xticksSvg = xTicks.map(function (t) {
      return '<text x="' + fixed(t[0], 1) + '" y="' + (H - PAD_B + (compact ? 16 : 20)) +
        '" text-anchor="middle" class="chart-tick">' + esc(t[1]) + '</text>';
    }).join('');
    var cls = compact ? 'rank-chart chart-compact' : 'rank-chart chart-wide';
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" class="' + cls + '" role="img" ' +
      'aria-label="Ranked Solo/Duo LP game by game">' + bandSvg + gridSvg + xticksSvg +
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
      // Raw LP only means the same thing while tier and division hold still –
      // a promotion resets LP, so across one the ladder distance is not an LP
      // number worth printing.
      if (first.tier === last.tier && first.rank === last.rank) {
        var lp = (last.leaguePoints || 0) - (first.leaguePoints || 0);
        moveText = (lp >= 0 ? '+' : '\u2212') + Math.abs(lp) + ' LP';
      } else {
        var mv = ladderLp(last) - ladderLp(first);
        moveText = (mv >= 0 ? '+' : '\u2212') + Math.abs(mv) + ' LP, ' +
                   rankName(first) + ' \u2192 ' + rankName(last);
      }
      netLabels.push({ text: moveText, direction: netLp > 0 ? 1 : (netLp < 0 ? -1 : 0) });
      tiers.push(last.tier);
      standings.push({ varName: colourFor(f.label), label: f.label, tier: last.tier,
                       rank: last.rank, leaguePoints: last.leaguePoints || 0,
                       rankLabel: rankLabelOf(last), games: games, lp: netLp,
                       winrate: games ? Math.round(100 * wins / games) : 0,
                       record: record });
    });
    return { netLabels: netLabels, tiers: tiers, standings: standings };
  }

  // Ladder position of a standings row, from the rank it is displaying.
  function ladderOf(s) {
    if (!s.tier) return -1;
    var ti = D.tierOrder.indexOf(s.tier);
    if (ti < 0) ti = 0;
    var lp = s.leaguePoints || 0;
    if (D.apexTiers.indexOf(s.tier) !== -1) {
      return ti * D.divisionsPerTier * D.lpPerDivision + lp;
    }
    return (ti * D.divisionsPerTier + (D.rankScore[s.rank] || 0)) * D.lpPerDivision + lp;
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

  // Mirrors render_chart_stats(). Not covered by verifySelf(), which only
  // compares the SVGs and the game list, so it is kept short and structural.
  //
  // Sorted here rather than taken in state order. state.friends is the order
  // the page was published in, and after a refresh that is last week's ladder:
  // somebody who dropped to 0 LP stayed above somebody who did not. The chart
  // series keep their published order, because that is what ties a line to a
  // colour.
  function standingsHtml(state) {
    var ordered = state.standings.slice().sort(function (a, b) {
      return ladderOf(b) - ladderOf(a);
    });
    var rows = ordered.map(function (s) {
      var icon = '<img src="' +
        esc(D.rankIconBase.replace('{tier}', (s.tier || 'unranked').toLowerCase())) +
        '" alt="" class="rank-icon' + (s.tier ? '' : ' rank-icon-unranked') +
        '" width="18" height="18" loading="lazy" ' +
        'onerror="this.style.visibility=&#x27;hidden&#x27;">';
      var up = s.lp >= 0;
      return '<tr data-standing="' + esc(s.label) + '"><td class="cs-name">' +
        '<span class="sw" style="background:var(' + s.varName +
        ');"></span><b style="color:var(' + s.varName + ');">' + esc(s.label) + '</b></td>' +
        '<td class="nowrap">' + icon + s.rankLabel + '</td>' +
        '<td class="num">' + s.games + '</td>' +
        '<td class="num ' + (up ? 'up' : 'down') + '">' + (up ? '+' : '\u2212') +
        fixed(Math.abs(s.lp), 0) + '</td>' +
        '<td class="num">' + s.winrate + '%</td>' +
        '<td class="num muted">' + esc(s.record) + '</td></tr>';
    }).join('');
    return '<table class="chart-stats"><thead><tr><th>Player</th><th>Rank now</th>' +
      '<th class="num">Games</th><th class="num">LP</th><th class="num">Winrate</th>' +
      '<th class="num">W&ndash;L</th></tr></thead><tbody>' + rows + '</tbody></table>';
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
    function diff(mine, theirs, what) {
      if (mine === theirs) return null;
      var at = 0;
      while (at < mine.length && at < theirs.length && mine[at] === theirs[at]) at++;
      return { ok: false, part: what, at: at,
               mine: mine.slice(Math.max(0, at - 70), at + 70),
               theirs: theirs.slice(Math.max(0, at - 70), at + 70),
               lens: [mine.length, theirs.length] };
    }
    var bad = diff(norm(box.innerHTML), norm(host.innerHTML), 'charts');
    if (bad) return bad;
    // The game list is rebuilt from the same state, so it is held to the same
    // standard. Its rows carry inline colour, which the DOM normalises, so
    // both sides are read back through it.
    var body = document.querySelector('.lp-table tbody');
    if (body) {
      var tbox = document.createElement('table');
      tbox.innerHTML = '<tbody>' + tableHtml(state) + '</tbody>';
      bad = diff(norm(tbox.querySelector('tbody').innerHTML), norm(body.innerHTML), 'table');
      if (bad) return bad;
    }
    return { ok: true, bytes: norm(host.innerHTML).length };
  }

  // Redraw with a live LP reading and any games played since the publish.
  // `live` is { label: {tier, rank, leaguePoints, matches: [...] } }.
  function rerender(live) {
    if (!D) return 0;
    var today = new Date();
    var dateKey = today.getFullYear() + '-' +
                  ('0' + (today.getMonth() + 1)).slice(-2) + '-' +
                  ('0' + today.getDate()).slice(-2);
    var touched = 0, ranked = 0;
    var friends = D.friends.map(function (f) {
      var copy = { label: f.label, history: f.history.slice(), matches: f.matches.slice() };
      var l = live[f.label];
      if (!l || !l.tier) return copy;
      // The live reading becomes today's snapshot whether or not games came
      // with it. Without this the "Rank now" column under the chart kept
      // showing the published rank after a refresh that found no new games,
      // while the leaderboard three inches above it showed the live one.
      var lastHist = copy.history[copy.history.length - 1];
      var snap = { date: dateKey, tier: l.tier, rank: l.rank, leaguePoints: l.leaguePoints };
      if (lastHist && lastHist.date === dateKey) copy.history[copy.history.length - 1] = snap;
      else copy.history.push(snap);
      ranked++;
      var added = (l.matches || []).filter(function (m) {
        return m.queue === 'Ranked Solo/Duo';
      }).map(function (m) {
        return { dateKey: dateKey, gameStartMs: m.gameStartMs, win: !!m.win,
                 champion: m.champion, matchId: m.matchId };
      });
      if (!added.length) return copy;
      // With games, the new snapshot closes an ordinary segment: the same
      // shape every other part of this chart is built from.
      copy.matches = copy.matches.concat(added);
      // A game two of them just played has to reach the duo map as well, or
      // the list draws it as two unrelated rows.
      added.forEach(function (m) {
        if (!m.matchId) return;
        if (!D.duoSides[m.matchId]) D.duoSides[m.matchId] = [];
        var side = D.duoSides[m.matchId], seen = false;
        side.forEach(function (x) { if (x[0] === f.label) seen = true; });
        if (!seen) side.push([f.label, !!m.win]);
      });
      touched += added.length;
      return copy;
    });
    if (!touched && !ranked) return 0;
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
    // Scoped to the zoom control: the projection switch beside it also
    // carries .active, and it has no data-range to restore.
    var activeBtn = document.querySelector('.range-btn.active[data-range]');
    if (activeBtn) activeRange = activeBtn.getAttribute('data-range');

    host.innerHTML = chartsHtml(state);
    if (chips) chips.innerHTML = standingsHtml(state);
    var body = document.querySelector('.lp-table tbody');
    if (body) body.innerHTML = tableHtml(state);

    // The key is static markup, so it is reordered rather than rebuilt: the
    // click handlers on it look their series up by id and survive the move.
    var key = document.querySelector('.chart-key');
    if (key && chips) {
      var order = [];
      chips.querySelectorAll('[data-standing]').forEach(function (tr) {
        order.push(tr.getAttribute('data-standing'));
      });
      var byLabel = {};
      key.querySelectorAll('.legend-item').forEach(function (el) {
        var name = el.querySelector('.legend-name');
        if (name) byLabel[name.textContent] = el;
      });
      order.forEach(function (label) {
        if (byLabel[label]) key.appendChild(byLabel[label]);
      });
    }

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

  return { init: init, verifySelf: verifySelf, rerender: rerender,
           blend: blendVars, colourFor: colourFor };
})();
'''


def build_html(data):
    friends = data.get("friends", [])
    friends_sorted = sorted(friends, key=lambda f: tier_score(f["ranked"].get("solo")), reverse=True)
    now = datetime.now()
    rank_history = data.get("rankHistory", [])
    # Read before the cards now: they price a win and a loss from these
    # snapshots, and have to say which window that is.
    tracking_since = data.get("rankTrackingSince", "recently")
    # Before anything counts a game. Everything downstream filters on
    # m["remake"], and until this runs most records have no such key.
    mark_legacy_remakes(friends)
    set_icon_context(data.get("ddragonVersion"), data.get("championIconMap", {}))
    set_platform(data.get("platform"))
    # data.json keeps the friends in config order, which is stable; the
    # dashboard sorts by rank for display only.
    set_duo_context(friends_sorted, [f["label"] for f in friends])

    leaderboard_rows = "".join(
        render_leaderboard_row(f, i + 1, weekly_trend_for(rank_history, f["label"], now))
        for i, f in enumerate(friends_sorted)
    )
    cards = "".join(
        render_friend_card(f, i + 1, now, rank_history, tracking_since)
        for i, f in enumerate(friends_sorted)
    )
    # Every card is on screen now, so a pill jumps to someone and highlights
    # them rather than hiding the other six. That makes them toggles, not tabs
    # — a tablist implies only one panel exists at a time, which is no longer
    # true, so they are plain buttons with aria-pressed.
    # An explicit All, then one button per person. Picking someone shows
    # only them; All brings everyone back. Each button carries that player's
    # face, which is their most mastered champion.
    friend_pills = (
        '<button class="pill pill-all active" type="button" data-friend=""'
        ' aria-pressed="true">All friends</button>'
    ) + "".join(
        f'<button class="pill" type="button" id="pill-{f["label"].lower()}"'
        f' aria-pressed="false" data-friend="{f["label"].lower()}">'
        f'{render_avatar(f, size=20)}'
        f'{render_rank_icon((f["ranked"].get("solo") or {{}}).get("tier"), size=15)}'
        f'{esc(f["label"])}</button>'
        for f in friends_sorted
    )

    awards = compute_awards(friends_sorted, now)
    awards_panel = render_season_highlights_panel(friends_sorted, now)
    week_glance_panel = render_week_glance_panel(friends_sorted, awards, rank_history, now)
    group_top_html = render_group_top_champions(friends_sorted)
    duo_synergy_panel = render_duo_synergy_panel(friends_sorted)

    notes_html, notes_latest = render_patch_notes(load_patch_notes())

    # Season totals for the group as a whole. The leaderboard answers "who is
    # ahead"; this answers "how much has this lot actually played". The
    # week's numbers live in the week panel with the rest of the week.
    all_season = [m for f in friends_sorted for m in f.get("seasonMatches", [])]
    solo_w = sum((f["ranked"].get("solo") or {}).get("wins", 0) for f in friends_sorted)
    solo_l = sum((f["ranked"].get("solo") or {}).get("losses", 0) for f in friends_sorted)
    solo_total = solo_w + solo_l
    champ_pool = len({m.get("champion") for m in all_season if m.get("champion")})
    group_stats = f'''
      <div class="season-stats" style="margin-top:0;">
        <div class="stat-tile">
          <div class="stat-value">{len(all_season)}</div>
          <div class="stat-label">Ranked games this season ({format_minutes(sum(m.get("durationMin", 0) for m in all_season))})</div>
        </div>
        <div class="stat-tile">
          <div class="stat-value">{round(100 * solo_w / solo_total, 1) if solo_total else "&ndash;"}%</div>
          <div class="stat-label">Combined Solo/Duo winrate ({solo_w}W {solo_l}L)</div>
        </div>
        <div class="stat-tile">
          <div class="stat-value">{champ_pool}</div>
          <div class="stat-label">Different champions played</div>
        </div>
      </div>'''

    # Per-game LP is the primary view; it needs at least one snapshot-to-
    # snapshot interval with games in it, so fall back to the daily-snapshot
    # chart alone until that exists.
    lp_chart_panel = render_lp_chart(friends_sorted, rank_history, now, tracking_since)
    daily_chart_panel = render_rank_chart(friends_sorted, rank_history, now, tracking_since)
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
        # The snapshot each friend's week is measured from: the last reading
        # at or before the cutoff. Only the far end of that span changes when
        # a rank is refreshed, so shipping the anchor is enough to redraw the
        # arrow without shipping the whole history.
        "weekAnchor": {
            f["label"]: (lambda pair: {"tier": pair[0].get("tier"), "rank": pair[0].get("rank"),
                                       "leaguePoints": pair[0].get("leaguePoints") or 0}
                         if pair else None)(
                week_window(
                    sorted((h for h in rank_history
                            if h.get("queue") == "solo" and h["label"] == f["label"]),
                           key=lambda h: h["date"]),
                    (now - timedelta(days=7)).strftime("%Y-%m-%d")))
            for f in friends_sorted
        },
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
<meta name="theme-color" content="#090a0e">
<meta property="og:type" content="website">
<meta property="og:site_name" content="League Friends Dashboard">
<meta property="og:title" content="League Friends Dashboard">
<meta property="og:description" content="{esc(share_desc)}">{og_tags}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  /* One theme. The light one existed because the browser asked for it, not
     because anyone wanted it here; keeping both meant every colour had two
     values and every new rule two chances to be wrong. */
  :root {{
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
    /* The queue bars ask for one of these by name. Only two existed, so the
       Ranked 5s bar was pointing at an undefined variable: its gradient never
       parsed and the bar rendered empty. */
    --series-3: #a78bfa;
    --series-4: #2ec4de;

    /* Queues: two families, each a base and a lighter sibling, so Solo reads
       against Duo and Flex against 5s at a glance. Deliberately off the
       accents and off the win/loss greens and reds, which mean something
       else everywhere on this page. */
    /* Solo and Duo are the same hue, Duo the weaker of the two, because they
       are the same queue counted two ways. Flex and 5s are separate queues, so
       they get separate hues rather than two shades of one. */
    --q-solo:  #4f7de8;                  /* blue */
    --q-duo:   #93b2f2;                  /* the same blue, drained */
    --q-flex:  #b0508f;                  /* magenta */
    --q-fives: #d8a13c;                  /* amber */

    /* Roles: the hues the game uses, pulled down and desaturated so none of
       them can be mistaken for a winrate colour or a friend's identity. */
    --role-top:     #c9584c;
    --role-jungle:  #6b9e3f;
    --role-mid:     #4a7fc1;
    --role-adc:     #c9a227;
    --role-support: #d1793c;
    --good: #2ecc71;
    --critical: #ff5f5f;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.4);
    --shadow-md: 0 6px 18px rgba(0,0,0,0.45);
    --shadow-lg: 0 18px 44px rgba(0,0,0,0.55);
    --radius: 14px;
    --radius-sm: 10px;
    --halo: rgba(76,141,255,0.16);
    {tier_vars_dark}
    {friend_vars_dark}
  }}

  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  ::selection {{ background: color-mix(in srgb, var(--accent) 28%, transparent); }}
  /* Themed scrollbars · the default light-grey ones cut straight through the
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
  /* Amber under six hours, red under one. The chip is only worth the space
     it takes if it changes appearance before the key actually dies. */
  .key-age.soon b {{ color: var(--warn, #e0a63c); }}
  .key-age.now b {{ color: var(--critical); }}
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
  /* A table will happily crush its columns down to fit rather than overflow,
     which is why these read as broken rather than scrollable: the header wraps
     to three lines and nothing moves. A min-width makes the box scroll. */
  .table-scroll .rate-table {{ min-width: 420px; }}
  .table-scroll .group-top {{ min-width: 460px; }}
  .table-scroll .rate-table th, .table-scroll .group-top th {{ white-space: nowrap; }}
  .leaderboard {{ table-layout: fixed; min-width: 100%; }}
  /* Rank needs the most room of the text columns · "Platinum III · 91 LP"
     plus an emblem · and previously got 17%, leaving ~3px of slack, so a
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
     name · the row is what people aim at. */
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
  /* Three to a row, declared rather than fitted. auto-fill gave two, three or
     four across depending on how wide the window happened to be, so the rows
     the cards are grouped into were only sometimes the rows on screen. Below
     900px it drops to two and then one, since three columns of a card that
     wants 258px does not fit a phone. */
  .awards {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
  @media (max-width: 900px) {{ .awards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
  .award {{
    display: flex; gap: 12px; align-items: flex-start; background: var(--surface-2);
    border: 1px solid var(--border); border-radius: 12px; padding: 13px 14px;
    position: relative; overflow: hidden;
    transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
  }}
  .award::before {{
    content: ""; position: absolute; inset: 0 auto 0 0; width: 3px;
    background: var(--award-colour, linear-gradient(var(--accent), var(--accent-2)));
    opacity: .85;
  }}
  .award:hover {{ transform: translateY(-2px); box-shadow: var(--shadow-md); border-color: color-mix(in srgb, var(--accent) 32%, var(--border)); }}
  .award-icon {{
    font-size: 19px; line-height: 1; flex-shrink: 0;
    width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
    background: var(--surface-1); border: 1px solid var(--border);
  }}
  .award-title {{ font-weight: 700; font-size: 13px; margin-bottom: 3px; letter-spacing: -0.01em; }}
  .award-text {{ font-size: 12px; color: var(--text-secondary); line-height: 1.45; }}
  .award-text strong {{ color: var(--text-primary); font-weight: 700; }}
  /* The card is a claim; this is the working. Folded away because the claim
     is what the card is for, and open on a click because the first thing
     anyone says to a superlative is "by how much?". */
  .award-body {{ min-width: 0; flex: 1; }}
  .award-why {{ margin-top: 8px; }}
  .award-why > summary {{
    font-size: 11px; padding: 3px 0; color: var(--muted);
    list-style: none; user-select: none;
  }}
  .award-why > summary::-webkit-details-marker {{ display: none; }}
  /* The character itself, not a CSS escape. This stylesheet lives inside a
     Python f-string, and Python reads a backslash followed by digits as an
     octal escape long before CSS sees it, so the triangle written as a CSS
     escape arrived as a control character followed by the literal text "b8".
     Writing that escape here to explain it put the control character back. */
  .award-why > summary::before {{ content: "▸"; display: inline-block; margin-right: 5px; transition: transform .15s ease; }}
  .award-why[open] > summary::before {{ transform: rotate(90deg); }}
  .award-why > summary:hover {{ color: var(--text-secondary); }}
  .why-method {{
    font-size: 11px; color: var(--text-secondary); line-height: 1.5;
    margin: 6px 0 8px; padding-left: 10px;
    border-left: 2px solid var(--border);
  }}
  /* A last resort. The table is built to fit, but a long name and a big
     number together can still beat a narrow card, and scrolling in place
     beats spilling past the card's rounded edge. */
  .why-scroll {{ overflow-x: auto; }}
  .why-table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  .why-table th {{
    text-align: left; font-weight: 600; color: var(--muted);
    padding: 3px 4px; border-bottom: 1px solid var(--border);
    white-space: nowrap; vertical-align: bottom;
  }}
  .why-table td {{ padding: 3px 4px; border-bottom: 1px solid var(--border); }}
  .why-table tr:last-child td {{ border-bottom: none; }}
  .why-table .num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  /* The unit under the heading instead of after all seven numbers. */
  .why-unit {{
    display: block; font-weight: 400; font-size: 9px; letter-spacing: 0;
    text-transform: none; opacity: .75;
  }}
  .why-name {{ max-width: 96px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .why-gap {{ color: var(--muted); font-size: 10px; white-space: nowrap; }}
  .why-excluded {{ font-size: 10px; color: var(--muted); margin-top: 6px; line-height: 1.45; }}
  /* The LP behind a promotion: "Platinum I → Emerald IV" says how far, this
     says how much. */
  .lp-gain {{
    display: inline-block; font-weight: 700; color: var(--good);
    background: color-mix(in srgb, var(--good) 12%, transparent);
    border-radius: 999px; padding: 0 7px; margin: 0 1px;
  }}

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
     cover the header · everything except the art is lifted above it.
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
       rows sit, so the art itself has to be faint for text to stay crisp –
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
  /* Current rank in the corner. The rank rows below carry both queues and the
     winrate bars; this is the single number a card is usually opened for. */
  .card-rank {{ margin-left: auto; text-align: right; }}
  .cr-now {{ display: flex; align-items: center; gap: 9px; justify-content: flex-end; }}
  .cr-now > div {{ display: flex; flex-direction: column; line-height: 1.25; }}
  .cr-tier {{ font-size: 15px; font-weight: 800; }}
  .cr-lp {{ font-size: 12px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }}
  .cr-peak {{
    display: flex; align-items: center; justify-content: flex-end; gap: 5px;
    margin-top: 5px; font-size: 11.5px; color: var(--muted);
  }}
  .cr-peak-label {{ text-transform: uppercase; letter-spacing: .06em; font-weight: 700; }}
  .cr-peak .cr-lp {{ font-size: 11.5px; color: var(--muted); }}

  .stat-pct {{ font-size: 13px; font-weight: 700; color: var(--text-secondary); }}
  .duo-carry-key i {{ border-top-width: 9px; border-left-width: 9px; }}
  .live-at {{ color: var(--accent); font-weight: 600; }}
  /* Gold's crest is 17x13 where the rest are square, so contain rather than
     stretch, and unranked comes back to the weight of a tier crest. */
  .rank-icon {{ object-fit: contain; }}
  .rank-icon-unranked {{ transform: scale(0.8); }}
  /* ---- Friend card ------------------------------------------------------ */
  /* Two columns while there is room: the ranked queues read down the left,
     the two shares of the season read as rings on the right. Both collapse to
     one column on a narrow screen rather than shrinking to illegibility. */
  .card-id {{ min-width: 0; }}
  .card-trend {{ display: flex; flex-direction: column; gap: 3px; margin-left: 18px; }}
  .tr-row {{ display: flex; gap: 12px; font-size: 13px; line-height: 1; align-items: center; }}
  .tr-group {{ display: inline-flex; gap: 2px; align-items: center; }}
  .tr-tag {{
    font-size: 9.5px; font-weight: 800; letter-spacing: .04em; color: var(--muted);
    margin-right: 3px;
  }}
  .tr-none {{ color: var(--muted); font-weight: 700; }}
  .tr-up {{ color: var(--good); }}
  .tr-down {{ color: var(--critical); }}
  .tr-flat {{ color: var(--muted); }}

  .card-mid {{
    display: grid; grid-template-columns: minmax(0, 1fr) auto;
    gap: 22px; align-items: start; margin-bottom: 18px;
  }}
  .card-queues {{ display: flex; flex-direction: column; gap: 12px; min-width: 0; }}
  /* The last column is a fixed width, not auto. On auto it took whatever the
     record text needed, so a queue reading "(0W / 0L)" gave the bar beside it
     more room than one reading "(447W / 446L)" and the bars did not line up
     down the card. */
  .q-row {{
    display: grid; grid-template-columns: minmax(150px, 1.1fr) minmax(90px, 1fr) 148px;
    gap: 6px 14px; align-items: center;
  }}
  .q-wr {{ text-align: right; }}
  .q-name {{ display: flex; flex-direction: column; gap: 2px; font-weight: 700; font-size: 14px; }}
  .q-rank {{ font-size: 12.5px; font-weight: 600; }}
  .q-wr {{ font-size: 12.5px; font-variant-numeric: tabular-nums; white-space: nowrap; }}

  .form-line {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 2px; }}
  .form-line .section-label {{ margin: 0; }}
  .form-line .dots {{ margin: 0; }}
  .form-net {{ font-weight: 800; font-variant-numeric: tabular-nums; }}
  .form-net.up {{ color: var(--good); }}
  .form-net.down {{ color: var(--critical); }}

  .card-rings {{ display: flex; gap: 18px; flex-wrap: wrap; justify-content: flex-end; }}
  .donut {{ width: 168px; }}
  .donut-svg {{ width: 152px; height: 152px; display: block; margin: 0 auto; }}
  .donut-centre {{
    fill: var(--text-secondary); font-size: 15px; font-weight: 700;
    font-family: inherit;
  }}
  .donut-empty {{
    width: 152px; height: 152px; margin: 0 auto; border-radius: 50%;
    border: 26px solid var(--surface-2); display: flex; flex-direction: column;
    align-items: center; justify-content: center; text-align: center; gap: 3px;
    color: var(--text-secondary); font-size: 13px;
  }}
  .donut-arc {{ transition: opacity .12s ease, stroke-width .12s ease; cursor: default; }}
  .donut:hover .donut-arc {{ opacity: .35; }}
  .donut .donut-arc:hover, .donut .donut-arc:focus {{ opacity: 1; outline: none; }}
  .donut-centre tspan.dc-value {{ font-size: 19px; fill: var(--text-primary); }}
  .donut-centre tspan.dc-small {{ font-size: 11px; fill: var(--muted); }}

  /* Three blocks that wrap: the weighted table, the mastery table, the tiles. */
  /* The two champion tables want more room than the tiles, and the tiles read
     better two across than in a single tall column. */
  /* Two tables, and the wider one gets the room: the weighted table carries
     five columns where mastery carries three. */
  .card-lower {{
    display: grid; grid-template-columns: minmax(0, 1.75fr) minmax(0, 1fr);
    gap: 22px; margin-bottom: 6px;
  }}
  @media (max-width: 900px) {{
    .card-lower {{ grid-template-columns: minmax(0, 1fr); }}
  }}
  .season-stats-row {{ margin: 4px 0 18px; }}
  .cl-block {{ min-width: 0; overflow-x: auto; }}
  .cl-block .season-stats {{
    margin: 0; grid-template-columns: repeat(2, minmax(0, 1fr));
  }}
  /* The two tables sit side by side, so their rows have to be the same
     height or they drift apart down the card. Fixed row height rather than
     matching icon sizes, which only holds until one of them changes. */
  .cl-block .matches-table th, .cl-block .matches-table td {{ padding-left: 6px; padding-right: 6px; }}
  .cl-block .matches-table td {{ height: 38px; }}
  .cl-block .matches-table th {{ height: 30px; }}
  .cl-block .champ-cell .champ-icon {{ width: 20px; height: 20px; }}
  .rate-pair {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .rate-pair .up {{ color: var(--good); font-weight: 700; }}
  .rate-pair .down {{ color: var(--critical); font-weight: 700; }}
  .label-note[title] {{ cursor: help; border-bottom: 1px dotted var(--muted); }}
  .label-note {{
    font-weight: 500; text-transform: none; letter-spacing: 0;
    color: var(--muted); margin-left: 6px;
  }}
  .counter-tag {{
    display: inline-block; margin-left: 6px; padding: 1px 7px; border-radius: 999px;
    font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em;
    background: color-mix(in srgb, var(--gold) 18%, transparent); color: var(--gold);
    white-space: nowrap;
  }}
  .rate-table td.up {{ color: var(--good); font-weight: 700; }}
  .rate-table td.down {{ color: var(--critical); font-weight: 700; }}
  .rate-detail {{
    display: block; font-size: 10.5px; font-weight: 500; color: var(--muted);
    font-variant-numeric: tabular-nums;
  }}
  .rank-badge {{
    width: 38px; height: 38px; border-radius: 12px; background: var(--surface-2);
    border: 1px solid var(--border); display: flex; align-items: center; justify-content: center;
    font-family: "Outfit", sans-serif; font-weight: 700; font-size: 14px; color: var(--text-secondary); flex-shrink: 0;
  }}
  .card-head h2 {{ margin: 0; font-size: 19px; }}

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
  /* A game added by a refresh is a game like any other, and tinting it blue
     fought with the shared-game colour on the same row. */

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
  .rank-chart circle {{ transition: r .12s ease, opacity .12s ease; }}
  /* Invisible but hoverable: the dot appears under the cursor with its
     tooltip, so every game is still reachable without any of them being
     drawn across the lines. */
  .rank-chart circle.pt {{ opacity: 0; }}
  .rank-chart circle.pt.end {{ opacity: 1; }}
  .rank-chart circle:hover {{ r: 6; opacity: 1; }}
  .chart-grid.faint {{ opacity: .38; }}
  .chart-tick.faint {{ opacity: .55; }}
  /* Hovering a legend name fades the other lines back, which is the quickest
     way to follow one person through seven overlapping series. */
  .rank-chart g[id*="-series-"], .rank-chart g[id*="-label-"] {{ transition: opacity .15s ease; }}
  .rank-chart.has-focus g[id*="-series-"]:not(.focus-on),
  .rank-chart.has-focus g[id*="-label-"]:not(.focus-on) {{ opacity: 0.12; }}
  .legend-item {{ position: relative; }}
  .duo-dot {{
    display: inline-block; width: 11px; height: 11px; border-radius: 50%;
    margin-right: 8px; vertical-align: -1px; flex: 0 0 auto;
    box-shadow: 0 0 0 1px rgba(0,0,0,0.45) inset;
  }}

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
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    justify-content: space-between; margin-bottom: 14px;
  }}
  .duo-scale {{ display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--muted); }}
  .duo-scale .sw {{ width: 16px; height: 12px; border-radius: 3px; display: inline-block; }}

  /* On a phone the grid is wider than the screen; it scrolls in place rather
     than shrinking the cells past readability. */
  .duo-matrix-wrap {{ overflow-x: auto; }}
  .duo-matrix {{ border-collapse: separate; border-spacing: 3px; width: 100%; }}
  .duo-matrix th {{
    font-size: 11.5px; font-weight: 700; padding: 4px 6px; border: none;
    text-transform: none; letter-spacing: 0; white-space: nowrap;
  }}
  .duo-matrix thead th {{ text-align: center; }}
  .duo-matrix tbody th {{ text-align: right; }}
  .duo-cell {{
    border: 1px solid var(--border); border-radius: 8px; padding: 7px 4px;
    text-align: center; background: var(--surface-2); min-width: 62px;
    transition: transform .12s ease, box-shadow .12s ease;
  }}
  .duo-cell[tabindex] {{ cursor: pointer; }}
  .duo-cell[tabindex]:hover {{ transform: scale(1.06); box-shadow: var(--shadow-md); }}
  .duo-cell.selected {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  /* The row's player carries this pairing on KDA. A corner mark rather than a
     different fill, so it does not compete with the winrate colour. */
  .duo-carry::after {{
    content: ""; position: absolute; top: 2px; right: 2px;
    border-top: var(--carry, 7px) solid var(--gold);
    border-left: var(--carry, 7px) solid transparent;
    opacity: .85;
  }}
  .duo-cell {{ position: relative; }}
  .cell-wr {{
    display: block; font-size: 13.5px; font-weight: 700;
    font-variant-numeric: tabular-nums; line-height: 1.2;
  }}
  .cell-g {{ display: block; font-size: 10px; color: var(--muted); margin-top: 1px; }}
  /* Never played together, and the diagonal: both are context, not results. */
  .duo-none, .duo-self {{ background: transparent; border-style: dashed; color: var(--muted); }}
  .duo-self .cell-wr {{ color: var(--text-secondary); font-weight: 600; }}
  /* Fewer than DUO_THIN_GAMES games: shown, but not coloured as if it meant
     something. */
  .duo-cell.thin {{ opacity: .55; }}

  /* Diverging scale on how the pair does versus how those two do apart. */
  .lift-flat    {{ background: var(--surface-2); }}
  .lift-up-1    {{ background: color-mix(in srgb, var(--good) 22%, var(--surface-2)); }}
  .lift-up-2    {{ background: color-mix(in srgb, var(--good) 45%, var(--surface-2)); }}
  .lift-down-1  {{ background: color-mix(in srgb, var(--critical) 22%, var(--surface-2)); }}
  .lift-down-2  {{ background: color-mix(in srgb, var(--critical) 45%, var(--surface-2)); }}

  /* ---- Duo table ------------------------------------------------------ */
  .duo-table td, .duo-table th {{ vertical-align: middle; }}
  .duo-table .duo-pair {{ font-weight: 700; white-space: nowrap; }}
  .duo-table .duo-pair .duo-amp {{ margin: 0 5px; }}
  .duo-table tbody tr:hover {{ background: var(--surface-2); }}
  th.sortable {{ cursor: pointer; user-select: none; white-space: nowrap; }}
  th.sortable:hover {{ color: var(--text-primary); }}
  /* Literal arrows rather than CSS hex escapes: this stylesheet passes
     through a Python f-string, where a backslash followed by digits is an
     octal escape, so the escape arrived as a control character plus the
     leftover text. */
  th.sortable::after {{ content: "↕"; opacity: .3; margin-left: 4px; font-size: 10px; }}
  th.sortable.sorted {{ color: var(--accent); }}
  th.sortable.sorted::after {{ content: "▾"; opacity: 1; }}
  th.sortable.sorted[data-dir="asc"]::after {{ content: "▴"; }}
  .boost-val {{ color: var(--good); font-weight: 700; }}
  .syn {{ min-width: 96px; }}
  .syn-val {{ display: block; font-weight: 700; font-variant-numeric: tabular-nums; }}
  .syn.up .syn-val {{ color: var(--good); }}
  .syn.down .syn-val {{ color: var(--critical); }}
  .syn.flat .syn-val {{ color: var(--muted); }}
  .syn.thin .syn-val {{ opacity: .5; }}
  /* A bar that grows out from the centre: left of the line is worse together,
     right is better. A plain 0-100 bar would put every pair in the same place,
     since the differences that matter here are a few points wide. */
  .syn-bar {{
    position: relative; display: block; height: 5px; margin: 4px 0 0 auto; width: 88px;
    border-radius: 999px; background: var(--gridline); overflow: hidden;
  }}
  .syn-bar::before {{
    content: ""; position: absolute; left: 50%; top: 0; bottom: 0; width: 1px;
    background: var(--border);
  }}
  .syn-bar i {{ position: absolute; top: 0; bottom: 0; border-radius: 999px; }}
  .syn.up .syn-bar i {{ left: 50%; background: var(--good); }}
  .syn.down .syn-bar i {{ right: 50%; background: var(--critical); }}
  .syn.thin .syn-bar i {{ opacity: .45; }}

  .nowrap {{ white-space: nowrap; }}
  /* Games played alongside another tracked player. The arrows read as "these
     two were on the same team", and each name keeps that player's colour so
     it ties back to the chart and the duo grid. */
  .with-cell {{ white-space: nowrap; }}
  .duo-with {{
    display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 600;
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--accent) 26%, transparent);
    border-radius: 999px; padding: 2px 9px;
  }}
  .duo-with-icon {{ color: var(--muted); font-size: 11px; }}
  .duo-with .mate + .mate::before {{ content: ", "; color: var(--muted); font-weight: 500; }}
  .lp-table .lp-move.up {{ color: var(--good); font-weight: 700; }}
  .lp-table .lp-move.down {{ color: var(--critical); font-weight: 700; }}
  .lp-table tbody tr:hover, .daily-table tbody tr:hover {{ background: var(--surface-2); }}
  /* Games two or more of them were in together. The rows are already next to
     each other because the table is ordered by time; the band ties them into
     one game rather than leaving them as rows sharing a timestamp. */
  /* One game, one block. The rows of a shared game are adjacent, so the rule
     between them comes out and the pairing's colour runs down the side of the
     whole group. A gap under the last row separates one game from the next,
     which matters most during a long duo queue session where every row would
     otherwise be tinted the same. */
  .matches-table tr.party td {{
    background: color-mix(in srgb, var(--band) 12%, transparent);
  }}
  .matches-table tr.party td:first-child {{
    box-shadow: inset 4px 0 0 var(--band);
    padding-left: 14px;
  }}
  /* Only the game list groups the rows of one game together, so only it drops
     the rule between them and opens a gap after the last one. */
  .lp-table tr.party td {{ border-bottom-color: transparent; }}
  .lp-table tr.party.g-last td {{ border-bottom: 7px solid var(--surface-1); }}
  /* Not display:flex · on a <td> that removes the cell from the table's
     column layout, so it collapses to zero width and the emblem disappears.
     The same mistake is documented on td.rank-cell above. */
  .daily-table td:nth-child(3) .rank-icon,
  .daily-table td:nth-child(3) .rank-icon-ph {{ margin-right: 6px; }}

  .duo-highlights {{ font-size: 12.5px; color: var(--text-secondary); margin-top: 12px; line-height: 1.6; }}
  .duo-highlights b {{ font-weight: 700; }}
  .duo-detail {{
    margin-top: 12px; padding: 13px 15px; border-radius: 11px;
    background: var(--surface-2); border: 1px solid var(--border);
  }}
  .duo-detail[hidden] {{ display: none; }}
  .duo-detail-names {{ font-weight: 700; font-size: 14px; margin-bottom: 6px; }}
  .duo-detail-line {{ font-size: 12.5px; color: var(--text-secondary); line-height: 1.6; }}
  .duo-thin {{ color: var(--critical); opacity: .8; font-weight: 600; }}
  .duo-cards {{ margin: 4px 0 16px; }}
  .duo-carry-key {{ display: inline-flex; align-items: center; gap: 5px; margin-right: 10px; }}
  .duo-carry-key i {{
    width: 0; height: 0; display: inline-block;
    border-top: 7px solid var(--gold); border-left: 7px solid transparent;
  }}
  .duo-lift-up {{ color: var(--good); font-weight: 700; }}
  .duo-lift-down {{ color: var(--critical); font-weight: 700; }}

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
  /* A table cell laid out as a flex container stops behaving like a cell: it
     sizes to its content rather than to the row, so on a tinted row the
     champion column's background sat short of the rest and the row looked
     ragged. The flex box goes on a span inside the cell instead. */
  .champ-cell {{ vertical-align: middle; }}
  .champ-cell > .cc {{ display: flex; align-items: center; gap: 8px; }}

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
    /* The match/champion tables are wider than a phone viewport · scroll
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
  .legend span.sw, .chart-key span.sw, .chart-stats span.sw {{
    display: inline-block; width: 10px; height: 10px; border-radius: 3px;
    margin-right: 5px; vertical-align: -1px; flex: 0 0 auto;
  }}
  .legend-item {{
    cursor: pointer; user-select: none; transition: opacity .15s, background .15s;
    padding: 3px 9px; border-radius: 999px; background: var(--surface-2); font-weight: 600;
  }}
  .legend-item:hover {{ background: var(--gridline); }}

  /* ---- Chart + key ----------------------------------------------------- */
  /* The key sits beside the plot rather than under it. Its rows are spread
     over the chart's own height with equal gaps, so the spacing is the same
     whoever is on the chart · anchoring each name to the end of its line put
     them on top of each other whenever two people were at a similar rank,
     which is exactly when the key is needed most. */
  .chart-row {{ display: flex; gap: 16px; align-items: stretch; }}
  .chart-plot {{ flex: 1 1 auto; min-width: 0; }}
  .chart-key {{
    flex: 0 0 148px; display: flex; flex-direction: column;
    justify-content: space-evenly; gap: 4px; padding: 10px 0;
  }}
  .chart-key .legend-item {{
    display: flex; align-items: center; font-size: 12px; padding: 5px 10px;
    border: 1px solid var(--border); background: var(--surface-2);
    border-radius: 9px; white-space: nowrap; overflow: hidden;
  }}
  .chart-key .legend-name {{ overflow: hidden; text-overflow: ellipsis; }}

  .chart-stats-wrap {{ overflow-x: auto; margin-top: 14px; }}
  .chart-stats {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  .chart-stats th {{
    text-align: left; font-size: 11px; text-transform: uppercase;
    letter-spacing: .05em; color: var(--muted); font-weight: 700;
    padding: 0 10px 6px; border-bottom: 1px solid var(--border);
  }}
  .chart-stats th.num, .chart-stats td.num {{ text-align: right; }}
  .chart-stats td {{
    padding: 7px 10px; border-bottom: 1px solid var(--border);
    font-variant-numeric: tabular-nums;
  }}
  .chart-stats tr:last-child td {{ border-bottom: 0; }}
  .chart-stats td.cs-name {{ display: table-cell; white-space: nowrap; }}
  .chart-stats td.up {{ color: var(--good); font-weight: 700; }}
  .chart-stats td.down {{ color: var(--critical); font-weight: 700; }}
  /* The projected tail is a guess and reads as one: thinner, dashed, and it
     does not respond to hover so it never steals a tooltip from a real game. */
  .rank-chart path.proj {{ pointer-events: none; }}
  .tier-band {{ pointer-events: none; }}
  .chart-plot.hide-proj .rank-chart path.proj {{ display: none; }}
  .chart-toggles {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
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
  .pill {{ display: inline-flex; align-items: center; gap: 7px; }}
  .pill .rank-icon, .pill .rank-icon-ph, .pill .avatar-wrap {{ flex-shrink: 0; }}
  .pill-all {{ font-weight: 700; }}

  /* Each player's face: their most mastered champion. */
  /* The ring is a shadow, not a border. A border sits inside the box, so a
     44px avatar was drawing 42px of champion inside a 44px circle and the
     ring read as a gap between the art and the edge. */
  /* Data Dragon squares carry a border of their own inside the image, so a
     straight circular crop still reads as a square in a circle. Scaling the
     picture past the frame and clipping it takes that border off. */
  .avatar-wrap {{
    display: inline-block; border-radius: 50%; overflow: hidden;
    line-height: 0; flex-shrink: 0; vertical-align: middle;
    background: var(--surface-2); box-shadow: 0 0 0 1px var(--border);
  }}
  .avatar {{
    width: 100%; height: 100%; display: block;
    object-fit: cover; object-position: center;
    scale: 1.2;
  }}
  .avatar.broken {{ visibility: hidden; }}
  .avatar-fallback {{
    display: inline-flex; align-items: center; justify-content: center;
    font-family: "Outfit", sans-serif; font-weight: 700; font-size: 12px;
    color: var(--text-secondary);
  }}
  .lb-name {{ white-space: nowrap; }}
  .lb-name .avatar-wrap {{ margin-right: 9px; }}
  /* The picked friend, scrolled to and ringed. Everyone stays on screen –
     the button is a way of finding someone, not of hiding the rest. */
  .card.card-focus {{
    border-color: color-mix(in srgb, var(--card-tier, var(--accent)) 60%, var(--border));
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--card-tier, var(--accent)) 30%, transparent),
                var(--shadow-md);
  }}
  /* The player's face, with their tier emblem and standing pinned to it. */
  .rank-crest {{ position: relative; width: 44px; height: 44px; flex-shrink: 0; }}
  .rank-crest .avatar-wrap {{ display: block; width: 44px; height: 44px; }}
  .rank-crest .rank-icon, .rank-crest .rank-icon-ph {{
    position: absolute; left: -8px; top: -6px; width: 26px; height: 26px;
    filter: drop-shadow(0 1px 2px rgba(0,0,0,.5));
  }}
  .rank-crest .rank-badge {{
    position: absolute; right: -4px; bottom: -3px;
    min-width: 22px; height: 18px; padding: 0 5px; border-radius: 999px;
    display: flex; align-items: center; justify-content: center;
    font-family: "Outfit", sans-serif; font-weight: 700; font-size: 11px;
    background: var(--surface-2); border: 1px solid var(--border);
    color: var(--text-secondary);
  }}
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
  /* A refreshed row used to be tinted. The banner already says the reading
     is live, and the tint fought with the shared-game colour underneath it. */
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
  /* An API key is a token, not prose · monospace makes a mistyped character
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
  /* No permanent blank gap when there is nothing to say · collapsed rather
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

  /* ---- Responsive ----------------------------------------------------- */
  @media (max-width: 720px) {{
    .wrap {{ padding: 14px 12px 56px; }}
    header.top {{ margin-bottom: 16px; gap: 10px; }}
    header.top h1 {{ font-size: 19px; margin-bottom: 3px; }}
    .brand {{ gap: 10px; }}
    .brand-mark {{ width: 38px; height: 38px; border-radius: 11px; font-size: 18px; }}
    /* Meta chips collapse to one line of plain text · three pill rows pushed
       the actual content most of a screen down. */
    .meta-row {{ gap: 4px; }}
    .meta-chip {{ border: none; background: none; padding: 0; font-size: 11px; }}
    .meta-chip::after {{ content: "·"; margin-left: 4px; opacity: .5; }}
    .meta-chip:last-child::after {{ content: ""; }}

    .panel, .card {{ padding: 15px 13px; border-radius: 12px; }}
    /* Narrower column means the horizontal veil has less room to fade, so
       the art gets shorter and sits further back. */
    .ext-link {{ min-height: 38px; padding: 8px 13px; font-size: 12px; }}
    .duo-controls {{ gap: 10px; }}
    /* Three labels at the shared .range-btn padding wrapped onto a second row
       inside the pill, which reads as broken rather than as a toggle. */
    .duo-controls .range-toggle {{ width: 100%; }}
    .duo-controls .range-btn {{ flex: 1; padding: 11px 6px; font-size: 12px; }}
    .duo-matrix {{ border-spacing: 2px; }}
    .duo-cell {{ min-width: 52px; padding: 6px 2px; }}
    .cell-wr {{ font-size: 12px; }}
    .duo-matrix th {{ font-size: 10.5px; padding: 3px 4px; }}
    /* The bar is the first thing to go when there is no width for it. */
    .syn-bar {{ display: none; }}
    .syn {{ min-width: 0; }}
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
    #patch-notes {{ padding: 0; }}
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
    .card-mid {{ grid-template-columns: minmax(0, 1fr); }}
    /* Two fixed 168px rings plus their gap want 354px, which is wider than
       the inside of a card on a 375px phone, so they wrapped and sat one on
       top of the other. Sharing the row and scaling to fit keeps both rings
       in one glance, which is the whole point of putting them next to each
       other. */
    .card-rings {{ justify-content: space-between; flex-wrap: nowrap; gap: 10px; }}
    .card-rings .donut {{ width: auto; flex: 1 1 0; min-width: 0; }}
    .card-rings .donut-svg {{ width: 100%; height: auto; max-width: 152px; }}
    /* The empty state is a bordered circle, not an svg, so it needs telling
       to be square at whatever width it ends up. */
    .card-rings .donut-empty {{
      width: 100%; max-width: 152px; height: auto; aspect-ratio: 1;
      box-sizing: border-box; border-width: 20px;
    }}
    .card-trend {{ margin-left: 0; }}
    .q-row {{ grid-template-columns: minmax(0, 1fr) auto; }}
    .q-row .wr-track {{ grid-column: 1 / -1; }}
    .chart-row {{ flex-direction: column; gap: 8px; }}
    .chart-key {{
      flex: 0 0 auto; flex-direction: row; flex-wrap: wrap;
      justify-content: flex-start; padding: 0;
    }}
    .chart-stats {{ font-size: 12px; }}
    .chart-stats th, .chart-stats td {{ padding-left: 6px; padding-right: 6px; }}

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
            <span class="meta-chip" data-updated{f' data-generated-ms="{int(data["generatedAtMs"])}"' if data.get("generatedAtMs") else ""}>Data from <b data-generated-text>{esc(data.get("generatedAt", ""))}</b></span>
            {render_key_age(data.get("apiKey"))}
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
      <div class="panel">
        <h2 style="margin-bottom:14px;">Ranked Solo/Duo leaderboard</h2>
        <p class="panel-hint">Click any row to open that player&rsquo;s full season.</p>
        <div class="table-scroll">
          <table class="leaderboard">
            <thead><tr><th class="num">#</th><th>Friend</th><th>Rank</th><th class="num">Winrate</th><th class="num">Record</th><th class="num">7-day trend</th></tr></thead>
            <tbody>{leaderboard_rows}</tbody>
          </table>
        </div>
        <div class="muted small" style="margin:16px 0 8px;">Across everyone</div>
        {group_stats}
        {group_top_html}
      </div>

      {week_glance_panel}
      {awards_panel}
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
        if (k.indexOf('RGAPI-') !== 0) return 'A Riot key starts with RGAPI- · that one does not.';
        if (k.length > this.LEN) return 'That looks like two keys run together (' + k.length +
          ' characters, expected ' + this.LEN + '). Clear the box, then paste just the new key.';
        if (k.length < this.LEN) return 'That key is incomplete · ' + k.length +
          ' characters, expected ' + this.LEN + '. Copy the whole key from developer.riotgames.com.';
        return 'That is not a valid Riot key · expected RGAPI- followed by 36 characters.';
      }}
    }};
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
    // Click a heading to sort. Applies to any table marked data-sortable whose
    // rows carry the values as data attributes, so the numbers a column sorts
    // on are the ones the build produced rather than parsed back out of text.
    (function () {{
      function renumber(t) {{
        var n = 1;
        [].slice.call(t.tBodies[0].rows).forEach(function (r) {{
          var seq = r.querySelector('.seq');
          if (seq) seq.textContent = n++;
        }});
      }}
      document.querySelectorAll('table[data-sortable]').forEach(function (t) {{
        renumber(t);
        t.querySelectorAll('th[data-key]').forEach(function (th) {{
          th.setAttribute('tabindex', '0');
          function run() {{
            var key = th.getAttribute('data-key');
            var numeric = th.hasAttribute('data-numeric');
            // First click on a column: numbers open biggest first, names A to Z.
            var dir = th.getAttribute('data-dir');
            var desc = dir ? dir !== 'desc' : numeric;
            t.querySelectorAll('th[data-key]').forEach(function (o) {{
              o.removeAttribute('data-dir');
              o.classList.remove('sorted');
            }});
            th.setAttribute('data-dir', desc ? 'desc' : 'asc');
            th.classList.add('sorted');
            var body = t.tBodies[0];
            var rows = [].slice.call(body.rows);
            rows.sort(function (a, b) {{
              var x = a.getAttribute('data-' + key), y = b.getAttribute('data-' + key);
              if (numeric) {{
                x = parseFloat(x); y = parseFloat(y);
                if (isNaN(x)) x = -Infinity;
                if (isNaN(y)) y = -Infinity;
                return desc ? y - x : x - y;
              }}
              return desc ? String(y).localeCompare(String(x))
                          : String(x).localeCompare(String(y));
            }});
            rows.forEach(function (r) {{ body.appendChild(r); }});
            renumber(t);
          }}
          th.addEventListener('click', run);
          th.addEventListener('keydown', function (e) {{
            if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); run(); }}
          }});
        }});
      }});
    }})();
  </script>

  <script>
    // Duo synergy matrix. Every queue's numbers are written onto each cell at
    // build time, so switching queue is a read, never a recalculation that
    // could disagree with the build.
    (function () {{
      var table = document.querySelector('.duo-matrix');
      if (!table) return;
      var cells = [].slice.call(table.querySelectorAll('.duo-cell'));
      var pairCells = cells.filter(function (c) {{ return c.hasAttribute('data-a'); }});
      var detail = document.querySelector('[data-duo-detail]');
      var highlights = document.querySelector('[data-duo-highlights]');
      var THIN = {DUO_THIN_GAMES};
      var queue = 'total', selected = null;
      var QUEUE_NAME = {{ total: 'Solo/Duo' }};

      function num(c, key) {{
        return parseFloat(c.getAttribute('data-' + queue + '-' + key));
      }}
      function liftClass(v, games) {{
        if (isNaN(v) || v === -999 || games < THIN) return 'lift-flat';
        if (v >= 5) return 'lift-up-2';
        if (v >= 1.5) return 'lift-up-1';
        if (v <= -5) return 'lift-down-2';
        if (v <= -1.5) return 'lift-down-1';
        return 'lift-flat';
      }}
      function signed(v) {{
        return (v > 0 ? '+' : (v < 0 ? '\u2212' : '\u00b1')) + Math.abs(v).toFixed(1);
      }}

      function paint() {{
        cells.forEach(function (c) {{
          var wrEl = c.querySelector('.cell-wr'), gEl = c.querySelector('.cell-g');
          c.className = c.className.replace(/ ?lift-[a-z0-9-]+| ?thin/g, '');
          if (c.classList.contains('duo-none')) return;
          var wr = num(c, 'wr'), games = num(c, 'games');
          if (c.classList.contains('duo-self')) {{
            // The reference number every other cell in the row is measured
            // against, coloured by its own distance from an even 50%.
            if (wrEl) wrEl.textContent = isNaN(wr) || wr === 0 ? '\u2013' : wr.toFixed(0) + '%';
            if (games) c.classList.add(liftClass(num(c, 'lift'), THIN));
            return;
          }}
          if (!games) {{
            if (wrEl) wrEl.textContent = '\u2013';
            if (gEl) gEl.textContent = '';
            c.classList.add('lift-flat');
            return;
          }}
          if (wrEl) wrEl.textContent = wr.toFixed(0) + '%';
          if (gEl) gEl.textContent = games + 'g';
          c.classList.add(liftClass(num(c, 'lift'), games));
          if (games < THIN) c.classList.add('thin');
        }});
        showHighlights();
        if (selected) showDetail(selected);
      }}

      function showHighlights() {{
        if (!highlights) return;
        var rated = pairCells.filter(function (c) {{
          return num(c, 'games') >= THIN && num(c, 'lift') !== -999 && !isNaN(num(c, 'lift'));
        }});
        if (!rated.length) {{
          highlights.innerHTML = '<span class="muted">No pair has ' + THIN +
            ' or more games in ' + QUEUE_NAME[queue] + ' yet.</span>';
          return;
        }}
        rated.sort(function (a, b) {{ return num(b, 'lift') - num(a, 'lift'); }});
        var best = rated[0], worst = rated[rated.length - 1];
        var most = pairCells.slice().sort(function (a, b) {{
          return num(b, 'games') - num(a, 'games');
        }})[0];
        function name(c) {{ return c.getAttribute('data-a') + ' &amp; ' + c.getAttribute('data-b'); }}
        highlights.innerHTML =
          'Best together: <b>' + name(best) + '</b> <span class="duo-lift-up">' +
            signed(num(best, 'lift')) + '%</span> over ' + num(best, 'games') + ' games' +
          ' &nbsp;\u00b7&nbsp; Worst: <b>' + name(worst) + '</b> <span class="duo-lift-down">' +
            signed(num(worst, 'lift')) + '%</span> over ' + num(worst, 'games') + ' games' +
          ' &nbsp;\u00b7&nbsp; Most played: <b>' + name(most) + '</b>, ' +
            num(most, 'games') + ' games';
      }}

      function showDetail(c) {{
        if (!detail) return;
        var games = num(c, 'games');
        if (!games) {{ detail.hidden = true; return; }}
        var lift = num(c, 'lift'), base = c.getAttribute('data-' + queue + '-base');
        var liftTxt = (lift === -999 || isNaN(lift) || !base) ? ''
          : ' &nbsp;\u00b7&nbsp; <span class="duo-lift-' + (lift >= 0 ? 'up' : 'down') + '">' +
            signed(lift) + '%</span> vs their usual ' + Math.round(parseFloat(base)) + '%';
        detail.hidden = false;
        detail.innerHTML =
          '<div class="duo-detail-names">' + c.getAttribute('data-a') + ' &amp; ' +
            c.getAttribute('data-b') + '</div>' +
          '<div class="duo-detail-line">' + num(c, 'wr').toFixed(1) + '% \u00b7 ' +
            num(c, 'w') + 'W ' + num(c, 'l') + 'L over ' + games + ' games in ' +
            QUEUE_NAME[queue] + liftTxt +
            (games < THIN ? ' <span class="duo-thin">\u00b7 small sample</span>' : '') +
          '</div>';
      }}

      function select(c) {{
        cells.forEach(function (o) {{ o.classList.remove('selected'); }});
        if (!c || !num(c, 'games')) {{ selected = null; if (detail) detail.hidden = true; return; }}
        c.classList.add('selected');
        selected = c;
        showDetail(c);
      }}

      pairCells.forEach(function (c) {{
        c.addEventListener('click', function () {{ select(c === selected ? null : c); }});
        c.addEventListener('keydown', function (e) {{
          if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); select(c === selected ? null : c); }}
        }});
      }});

      paint();
    }})();
  </script>

  <script>
    (function () {{
      // Zoom toggle: both ranges are already in the DOM, so this only swaps
      // which one is shown.
      // A ring answers in its own hole: hovering a segment replaces the title
      // with that segment's share, and leaving puts the title back.
      document.querySelectorAll('[data-donut]').forEach(function (d) {{
        var centre = d.querySelector('[data-donut-centre]');
        if (!centre) return;
        var original = centre.innerHTML;
        var x = centre.getAttribute('x');
        function show(arc) {{
          var name = arc.getAttribute('data-label');
          var parts = name.split(', ');
          var head = parts.shift();
          var tail = parts.join(', ');
          centre.innerHTML =
            '<tspan x="' + x + '" dy="-0.85em" class="dc-value">' +
              arc.getAttribute('data-value') + '</tspan>' +
            '<tspan x="' + x + '" dy="1.15em" class="dc-value">' +
              arc.getAttribute('data-pct') + '</tspan>' +
            '<tspan x="' + x + '" dy="1.5em" class="dc-small">' + head + '</tspan>' +
            (tail ? '<tspan x="' + x + '" dy="1.15em" class="dc-small">' + tail + '</tspan>' : '');
        }}
        function reset() {{ centre.innerHTML = original; }}
        d.querySelectorAll('.donut-arc').forEach(function (arc) {{
          arc.addEventListener('mouseenter', function () {{ show(arc); }});
          arc.addEventListener('focus', function () {{ show(arc); }});
          arc.addEventListener('blur', reset);
        }});
        d.addEventListener('mouseleave', reset);
      }});

      document.querySelectorAll('.range-btn[data-proj]').forEach(function (b) {{
        b.addEventListener('click', function () {{
          var host = document.querySelector('[data-lp-charts]');
          var off = b.getAttribute('data-proj') === 'off';
          if (host) host.classList.toggle('hide-proj', off);
          document.querySelectorAll('.range-btn[data-proj]').forEach(function (o) {{
            var on = o === b;
            o.classList.toggle('active', on);
            o.setAttribute('aria-pressed', on ? 'true' : 'false');
          }});
        }});
      }});

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

      // "Data from" in the reader's timezone, and how long ago that was.
      // The page is built on a UTC runner, so a UK reader was shown a time an
      // hour behind their own clock and the page looked an hour more stale
      // than it was. The string in the markup stays as the no-script
      // fallback.
      (function () {{
        var chip = document.querySelector('[data-generated-ms]');
        if (!chip) return;
        var el = chip.querySelector('[data-generated-text]');
        var ms = parseInt(chip.getAttribute('data-generated-ms'), 10);
        if (!el || !ms) return;

        function ago(then) {{
          var mins = Math.max(0, Math.round((Date.now() - then) / 60000));
          if (mins < 1) return 'just now';
          if (mins < 60) return mins + 'm ago';
          var h = Math.floor(mins / 60);
          return h + 'h ' + (mins % 60) + 'm ago';
        }}

        function paint() {{
          var d = new Date(ms);
          el.textContent = d.toLocaleString(undefined, {{
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
          }}) + ' · ' + ago(ms);
        }}
        paint();
        setInterval(paint, 30000);
      }})();

      // The API key chip counts down in the browser rather than being baked
      // into the page. A build is at most an hour old, but the page itself
      // can sit open on somebody's second monitor all day, and a chip that
      // still claims "6h left" the morning after is worse than no chip.
      (function () {{
        var chip = document.querySelector('[data-key-expires]');
        if (!chip) return;
        var left = chip.querySelector('[data-key-left]');
        var expires = parseInt(chip.getAttribute('data-key-expires'), 10);
        if (!left || !expires) return;

        // Formatted here, in the reader's own timezone, from the epochs the
        // page carries.
        var addedAt = parseInt(chip.getAttribute('data-key-added'), 10);
        var addedText = chip.querySelector('[data-key-added-text]');
        if (addedText && addedAt) {{
          var d = new Date(addedAt);
          addedText.textContent = d.toLocaleString(undefined, {{
            month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
          }});
        }}

        function tick() {{
          var ms = expires - Date.now();
          chip.classList.toggle('soon', ms > 0 && ms <= 6 * 3600 * 1000);
          chip.classList.toggle('now', ms <= 3600 * 1000);
          if (ms <= 0) {{
            left.textContent = 'expired';
            return;
          }}
          var h = Math.floor(ms / 3600000);
          var m = Math.floor((ms % 3600000) / 60000);
          left.textContent = h ? h + 'h ' + m + 'm left' : m + 'm left';
        }}
        tick();
        setInterval(tick, 60000);
      }})();

      // Hover a legend name to bring that line forward and fade the rest.
      // Pure presentation · it changes no state, so it can't get out of sync
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
    // cross-origin calls, so this needs no server at all · which means it
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
            var e = new Error('Riot rejected the key (' + r.status + ') · development keys expire ' +
                              'after 24 hours. Use the 🔑 API key button to paste a fresh one.');
            e.fatal = true; e.rejected = true; throw e;
          }}
          if (r.status === 429) {{
            var e2 = new Error('Riot rate limit reached. Wait a minute and try again.');
            e2.fatal = true; throw e2;
          }}
          if (r.status === 0) throw new Error('Could not reach Riot · check your connection.');
          if (r.status === 404) return null;
          if (!r.ok) throw new Error('Riot returned HTTP ' + r.status);
          return r.json();
        }});
      }}

      // Same shape net_change_label() produces, so render_trend_arrows() and
      // the leaderboard cell can be rebuilt from it.
      function weekTrend(label, live) {{
        var a = (CFG.weekAnchor || {{}})[label];
        if (!a || !a.tier || !live || !live.tier) return null;
        var from = ladderScore(a), to = ladderScore(live);
        var moved = to - from;
        if (!moved) return null;
        var same = a.tier === live.tier && a.rank === live.rank;
        return {{
          moved: !same, lp: moved, direction: moved > 0 ? 1 : -1,
          text: same
            ? (moved >= 0 ? '+' : '\u2212') + Math.abs(moved) + ' LP'
            : rankShort(a) + ' \u2192 ' + rankShort(live)
        }};
      }}

      // Port of render_trend_arrows(): direction first, then how far.
      function trendArrows(t, compact) {{
        if (!t) {{
          return compact
            ? '<span class="tr-group" title="nothing recorded"><span class="tr-none">'
              + '&ndash;</span></span>'
            : '<span class="muted small">\u2013</span>';
        }}
        var text = t.text;
        if (t.moved && t.lp !== null) {{
          text = (t.lp >= 0 ? '+' : '\u2212') + Math.abs(t.lp) + ' LP, ' + text;
        }}
        if (!compact) {{
          var col = t.direction > 0 ? 'var(--good)' : 'var(--critical)';
          var gl = t.direction > 0 ? '\u25b2' : '\u25bc';
          return '<span class="small" style="color:' + col + ';">' + gl + ' ' +
                 escapeHtml(text) + '</span>';
        }}
        var lp = Math.abs(t.lp || 0);
        var n = lp <= 50 ? 1 : (lp <= 100 ? 2 : 3);
        var cls = t.direction > 0 ? 'tr-up' : 'tr-down';
        var gly = t.direction > 0 ? '&#9650;' : '&#9660;';
        var out = '<span class="tr-group" title="Ranked Solo/Duo: ' + escapeHtml(text) + '">';
        for (var k = 0; k < n; k++) out += '<span class="' + cls + '">' + gly + '</span>';
        return out + '</span>';
      }}

      function rankText(e) {{
        if (!e || !e.tier) return 'Unranked';
        return rankShort(e) + ' · ' + (e.leaguePoints || 0) + ' LP';
      }}

      // Tier and division without the LP, for the card's corner where the LP
      // sits on its own line underneath.
      function rankShort(e) {{
        if (!e || !e.tier) return 'Unranked';
        var tier = e.tier.charAt(0) + e.tier.slice(1).toLowerCase();
        return CFG.apexTiers.indexOf(e.tier) !== -1 ? tier : tier + ' ' + (e.rank || '');
      }}

      function rankIconHtml(e, size) {{
        var tier = (e && e.tier) ? e.tier.toLowerCase() : 'unranked';
        var cls = (e && e.tier) ? 'rank-icon' : 'rank-icon rank-icon-unranked';
        return '<img src="' + CFG.rankIconBase.replace('{{tier}}', tier) +
               '" alt="" class="' + cls + '" width="' + size + '" height="' + size +
               '" onerror="this.style.visibility=&#x27;hidden&#x27;">';
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
      // Every friend gets their full window. At 40 the budget ran out partway
      // down a seven person list, so whoever came last silently got nothing
      // and it looked as though only one person had played.
      var matchBudget = 7 * MAX_NEW_PER_FRIEND;
      var budgetSpent = false;

      function escapeHtml(v) {{
        return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {{
          return {{ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }}[c];
        }});
      }}

      // "Aug 22, 11:09 PM" · the same shape the built page uses, so a live
      // row and a snapshot row are indistinguishable.
      var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      function whenText(m) {{
        if (!m.gameStartMs) return '\u00b7';
        var d = new Date(m.gameStartMs);
        var h = d.getHours(), h12 = h % 12 || 12;
        return MONTHS[d.getMonth()] + ' ' + ('0' + d.getDate()).slice(-2) + ', ' +
               h12 + ':' + ('0' + d.getMinutes()).slice(-2) + ' ' + (h >= 12 ? 'PM' : 'AM');
      }}

      // Same inversion as champDisplay() in the chart module: the two blocks
      // are separate IIFEs and neither can see the other's helpers.
      var _display = null;
      function champName(name) {{
        var icons = CFG.championIcons || {{}};
        if (!name || Object.prototype.hasOwnProperty.call(icons, name)) return name;
        if (!_display) {{
          _display = {{}};
          for (var k in icons) {{ _display[String(icons[k]).toLowerCase()] = k; }}
        }}
        return _display[String(name).toLowerCase()] || name;
      }}

      function championIcon(name) {{
        // The map is keyed by display name, but match-v5 already returns the
        // Data Dragon key, so fall through to the raw name.
        // Same fallback as champion_icon_url(): the map is keyed by display
        // name, match data reports the Data Dragon key, and Riot's own casing
        // differs between the two for at least one champion.
        var icons = CFG.championIcons || {{}};
        var slug = icons[name];
        if (!slug) {{
          var want = String(name || '').toLowerCase();
          for (var kk in icons) {{
            if (icons[kk].toLowerCase() === want) {{ slug = icons[kk]; break; }}
          }}
        }}
        if (!slug) slug = name;
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
        var title = whenText(m) + ' \u00b7 ' + champName(m.champion) + ' \u00b7 ' + (m.win ? 'Win' : 'Loss') +
                    ' \u00b7 ' + m.kills + '/' + m.deaths + '/' + m.assists + ' KDA ' + m.kda;
        return '<span class="dot ' + (m.win ? 'win' : 'loss') + ' dot-new" title="' +
               escapeHtml(title) + '"></span>';
      }}

      // Who else in the group was on this team, from the games this refresh
      // just fetched. Built once per refresh in run(), keyed by match id.
      var freshSides = {{}};

      function matesFor(matchId, label, win) {{
        var side = freshSides[matchId];
        if (!side) return [];
        var out = [];
        side.forEach(function (e) {{
          if (e[0] !== label && !!e[1] === !!win) {{
            out.push([e[0], (window.LpChart && LpChart.colourFor(e[0])) || '--accent']);
          }}
        }});
        out.sort(function (a, b) {{ return a[0] < b[0] ? -1 : (a[0] > b[0] ? 1 : 0); }});
        return out;
      }}

      function rowHtml(m, label) {{
        // Nine cells, matching render_match_row(). It used to build eight: the
        // "With" column was missing entirely, so every column from Champion
        // rightwards landed one place left of its own heading on any row a
        // refresh added.
        var mates = matesFor(m.matchId, label, m.win);
        var withCell = '<span class="muted">&ndash;</span>';
        var cls = 'row-new', style = '';
        if (mates.length) {{
          var names = mates.map(function (x) {{
            return '<span class="mate" style="color:var(' + x[1] + ');">' +
                   escapeHtml(x[0]) + '</span>';
          }}).join('');
          var who = mates.map(function (x) {{ return x[0]; }}).join(', ');
          withCell = '<span class="duo-with" title="Played this game with ' + escapeHtml(who) +
            '"><span class="duo-with-icon" aria-hidden="true">\u21c4</span>' + names + '</span>';
          var vars = [(window.LpChart && LpChart.colourFor(label)) || '--accent'];
          mates.forEach(function (x) {{ vars.push(x[1]); }});
          vars.sort();
          cls += ' party party-' + Math.min(mates.length + 1, 5);
          if (window.LpChart && LpChart.blend) {{
            style = ' style="--band: ' + LpChart.blend(vars) + ';"';
          }}
        }}
        return '<tr class="' + cls + '"' + style + '>' +
          '<td class="muted small">' + escapeHtml(whenText(m)) + '</td>' +
          '<td><span class="tag ' + (m.win ? 'win' : 'loss') + '">' +
            (m.win ? 'WIN' : 'LOSS') + '</span></td>' +
          '<td class="champ-cell"><span class="cc">' + championIcon(m.champion) +
            escapeHtml(champName(m.champion)) + '</span></td>' +
          '<td class="with-cell">' + withCell + '</td>' +
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
          if (rows) rows.insertAdjacentHTML('afterbegin', rowHtml(m, label));
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
        // The heading no longer carries a count, so a refresh has nothing to
        // rewrite here.
        return matches.length;
      }}

      // What this session has already taken in, seeded from the published
      // page and then kept up to date. Reading CFG directly meant a second
      // refresh saw the same games as new again, because CFG is a constant
      // baked in at build time: every game found by the first refresh was
      // added to the card a second time, and a third.
      var seenIds = {{}}, seenNewest = {{}};
      function seenFor(label) {{
        if (!seenIds[label]) {{
          seenIds[label] = ((CFG.knownMatches || {{}})[label] || []).slice();
          seenNewest[label] = (CFG.newestMatchMs || {{}})[label] || 0;
        }}
        return seenIds[label];
      }}

      function refreshGames(f, puuid, key) {{
        var known = seenFor(f.label);
        var newestMs = seenNewest[f.label];
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
            // Recorded before the DOM is touched, so a failure further down
            // cannot leave a game counted as unseen and get it added twice.
            out.forEach(function (m) {{
              if (known.indexOf(m.matchId) < 0) known.push(m.matchId);
              if (m.gameStartMs > seenNewest[f.label]) seenNewest[f.label] = m.gameStartMs;
              if (!freshSides[m.matchId]) freshSides[m.matchId] = [];
              freshSides[m.matchId].push([f.label, !!m.win]);
            }});
            // Rows are written after every friend has been fetched, in run():
            // a game two of them just played is only recognisable as shared
            // once both of their fetches have come back.
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
      // them · #1 on 80 LP above #2 on 26 LP. Re-sort and renumber.
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
        var v = CFG.tierVars[entry && entry.tier] || '--tier-unranked';
        if (rankCell) {{
          rankCell.style.color = 'var(' + v + ')';
          rankCell.innerHTML = rankIconHtml(entry, 20) + rankText(entry);
        }}
        var wins = (entry && entry.wins) || 0, losses = (entry && entry.losses) || 0;
        var total = wins + losses;
        var wrText = total ? (Math.round(wins / total * 1000) / 10) + '%' : '\u2013';
        if (wrCell) wrCell.textContent = wrText;
        if (recCell) recCell.textContent = wins + 'W / ' + losses + 'L';
        row.classList.add('row-live');

        // The trend column and the card's arrows both measure to the rank
        // being shown, so a refresh moves them too.
        var t = weekTrend(label, entry);
        var trendCell = row.children[row.children.length - 1];
        if (trendCell) trendCell.innerHTML = trendArrows(t, false);

        // The same reading, on the card. It used to stop at the leaderboard,
        // so a refresh left the rank in the card's corner and the rank row
        // underneath it showing whatever was true when the page was built ·
        // two different answers to the same question on one screen.
        var card = document.getElementById('friend-' + label.toLowerCase());
        if (!card) return;
        card.style.setProperty('--card-tier', 'var(' + v + ')');
        var now = card.querySelector('[data-cr-now]');
        if (now) {{
          now.innerHTML =
            '<div><b class="cr-tier" style="color:var(' + v + ');">' + rankShort(entry) +
            '</b><span class="cr-lp">' + ((entry && entry.leaguePoints) || 0) + ' LP</span></div>' +
            rankIconHtml(entry, 38);
        }}
        // A live reading above anything on record is the new peak. Leaving
        // it alone printed "Diamond IV" with "Peak Emerald II" underneath.
        var peakEl = card.querySelector('[data-cr-peak]');
        if (peakEl && entry && entry.tier) {{
          var live = ladderScore(entry);
          if (live > (parseFloat(peakEl.getAttribute('data-peak-lp')) || 0)) {{
            peakEl.setAttribute('data-peak-lp', live);
            peakEl.hidden = false;
            peakEl.innerHTML = '<span class="cr-peak-label">Peak</span>' +
              '<span>' + rankShort(entry) + '</span>' +
              '<span class="cr-lp">' + (entry.leaguePoints || 0) + ' LP</span>' +
              rankIconHtml(entry, 20);
          }}
        }}
        var trendRow = card.querySelector('.tr-row');
        if (trendRow) trendRow.innerHTML = trendArrows(t, true);
        var soloRow = card.querySelector('[data-rank-row="solo"]');
        if (soloRow) {{
          var lbl = soloRow.querySelector('[data-cell="rank"]');
          if (lbl) {{
            lbl.style.color = 'var(' + v + ')';
            lbl.innerHTML = rankIconHtml(entry, 22) + rankText(entry);
          }}
          var fill = soloRow.querySelector('.wr-fill');
          if (fill) fill.style.width = (total ? (wins / total * 100) : 0) + '%';
          var txt = soloRow.querySelector('[data-cell="wr-text"]');
          if (txt) txt.textContent = wrText + ' (' + wins + 'W ' + losses + 'L)';
        }}
        // No .row-live on the card: that rule tints every td it contains, and
        // a card contains four tables. The banner and the leaderboard already
        // say the reading is live.
      }}

      function run(key) {{
        btn.disabled = true;
        keyBtn.disabled = true;
        var friends = CFG.friends || [];
        var done = 0, updated = 0, newGames = 0;
        // Held back until every friend has been fetched, so a game two of
        // them played is drawn as one shared game rather than two loose rows.
        var pending = {{}};
        // Per friend: the live rank reading plus whatever games came back, fed
        // to the chart at the end so it redraws once rather than seven times.
        var live = {{}};

        function step(i) {{
          if (i >= friends.length) {{
            Object.keys(pending).forEach(function (label) {{
              applyMatches(label, pending[label]);
            }});
            resortLeaderboard(live);
            // The chart is rebuilt from the whole season, so it redraws once
            // here rather than per friend.
            var charted = 0;
            if (window.LpChart) {{
              try {{ charted = LpChart.rerender(live) || 0; }} catch (e) {{ charted = 0; }}
            }}
            var when = new Date().toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit' }});
            // The header carries the build date, which is what a shared link
            // shows. Say when the live reading on top of it was taken.
            var chip = document.querySelector('[data-updated]');
            if (chip && !chip.querySelector('.live-at')) {{
              chip.insertAdjacentHTML('beforeend',
                ' <span class="live-at">&middot; ranks live ' + when + '</span>');
            }} else if (chip) {{
              chip.querySelector('.live-at').textContent = '\u00b7 ranks live ' + when;
            }}
            // Be explicit about what did and did not move: the season tiles and
            // the LP chart need the whole season, which the browser cannot
            // rebuild, so they stay on the published snapshot.
            // Named rather than counted: "3 new games" leaves you guessing
            // whose, and whether somebody was skipped.
            var who = Object.keys(pending).map(function (l) {{
              return l + ' ' + pending[l].length;
            }});
            say('Ranks updated for ' + updated + ' of ' + friends.length + ' friends' +
                (who.length ? ', new games for ' + who.join(', ') +
                            (budgetSpent ? ' (some older ones skipped to stay inside Riot’s ' +
                                           'rate limit · refresh again for the rest)' : '')
                          : ', no new games for anyone since the last build') +
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
              if (added.length) pending[f.label] = added;
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

      // Another tab saving a key must not leave this one using the old one.
      // sessionKey is preferred over storage (so "don't remember" works for
      // the visit), which means a tab opened earlier would otherwise keep
      // its stale copy forever and keep reporting the key as rejected even
      // though a fresh one had just been entered next door.
      window.addEventListener('storage', function (e) {{
        if (e.key === KEY_STORE) sessionKey = e.newValue || '';
      }});
      function saveKey(key, remember) {{
        sessionKey = key;
        try {{
          if (remember) localStorage.setItem(KEY_STORE, key);
          else localStorage.removeItem(KEY_STORE);
        }} catch (e) {{ /* private mode · carry on without persisting */ }}
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
            ? 'A key is saved in this browser. Paste a new one to replace it · Riot development ' +
              'keys expire after 24 hours.'
            : 'Paste your own Riot API key. It stays in this browser, is never sent to this site, ' +
              'and expires after 24 hours.',
          confirm: 'Save key',
          onKey: function (key, remember) {{
            modalOk.disabled = true;
            modalMsg.className = 'modal-msg';
            modalMsg.textContent = 'Checking the key with Riot…';

            // Riot rejects a development key for a short window after issuing
            // it. Reporting that as "expired, generate a fresh one" is the
            // worst possible advice: the replacement behaves identically, so
            // every new key looks rejected and you end up generating them in
            // a loop. Retry a few times before believing the rejection.
            //
            // A status lookup needs no account data, so this validates the key
            // without spending a call on anybody's match history.
            function verify(attempt) {{
              return riot(platform, '/lol/status/v4/platform-data', key)
                .catch(function (err) {{
                  if (err && err.rejected && attempt < 3) {{
                    modalMsg.className = 'modal-msg';
                    modalMsg.textContent = 'Riot has not activated this key yet · ' +
                      'retrying in 5s (' + attempt + ' of 3)…';
                    return new Promise(function (go) {{ setTimeout(go, 5000); }})
                      .then(function () {{ return verify(attempt + 1); }});
                  }}
                  throw err;
                }});
            }}
            verify(1).then(function () {{
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
                ? 'Riot is still rejecting that key. A newly generated key can take a minute ' +
                  'to start working · wait a moment and press Save key again. If it was ' +
                  'generated more than 24 hours ago it has expired instead.'
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
        if (!s.hasKey) setStatus('No Riot API key stored yet · use the 🔑 API key button before refreshing.', 'error', 0);
        else if (s.keyAgeHours !== null && s.keyAgeHours >= 24)
          setStatus('The stored Riot API key is ' + Math.floor(s.keyAgeHours) + 'h old · dev keys expire after 24h, so it probably needs replacing.', 'error', 0);
      }}).catch(function () {{ /* not hosted · leave the buttons hidden */ }});

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
        // call · the server reports needsMore in that case, and the same
        // friend is retried (continuing:true, so the once-per-cycle cooldown
        // doesn't re-trigger) rather than moving on incomplete. Progress is
        // saved after every single call (server-side), so nothing is lost if
        // this session stops partway · clicking Refresh again later just
        // continues from wherever it left off, even a first-time sync of a
        // very high-volume account that needs more than one sitting.
        var SESSION_BUDGET_MS = 8 * 60 * 1000;
        var sessionStart = Date.now();

        function step(i, attempt) {{
          attempt = attempt || 1;
          if (i >= names.length) {{
            setStatus('Rebuilding the dashboard…', null, (total - 0.5) / total * 100);
            return post('finalize', {{}}).then(function (res) {{
              setStatus('Done · refreshed ' + res.friends + ' friends, ' + newGames +
                        ' new game' + (newGames === 1 ? '' : 's') + '. Reloading…', 'done', 100);
              setTimeout(function () {{ location.reload(); }}, 1400);
            }});
          }}
          var label = 'Fetching ' + names[i] + '… (' + (i + 1) + ' of ' + names.length + ')'
            + (attempt > 1 ? ' · lots of recent games, pass ' + attempt : '');
          setStatus(label, null, (i / total) * 100);
          return post('refresh', {{ index: i, continuing: attempt > 1 }}).then(function (res) {{
            newGames += (res && res.newMatches) || 0;
            if (res && res.needsMore) {{
              if (Date.now() - sessionStart > SESSION_BUDGET_MS) {{
                throw new Error(names[i] + ' has an unusually large backlog of new games (a first-time sync ' +
                  'of a very active player can take a while). Progress is saved · click Refresh again to continue.');
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
      // Includes the All button as an empty string, so this stays index-aligned
      // with pills[].
      var friendNames = pills.map(function (p) {{ return p.getAttribute('data-friend') || ''; }});
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

      // An empty label means All: every card shown, the All button lit.
      // Otherwise only that person's card is shown.
      function showFriend(label, scroll) {{
        var all = !label;
        if (!all && friendNames.indexOf(label) <= 0) return false;
        cards.forEach(function (c) {{
          c.hidden = !all && c.id !== 'friend-' + label;
        }});
        pills.forEach(function (p) {{
          var on = (p.getAttribute('data-friend') || '') === (label || '');
          p.classList.toggle('active', on);
          p.setAttribute('aria-pressed', on ? 'true' : 'false');
        }});
        if (scroll && !all) {{
          // The card is now the first thing in the panel, so go to the top of
          // the list rather than scrolling to something already at the top.
          window.scrollTo(0, 0);
        }}
        return true;
      }}

      function activeOf(list, names) {{
        for (var i = 0; i < list.length; i++) {{
          // names[] has no entry for the All button, which carries no label.
          if (list[i].classList.contains('active')) return names[i] || null;
        }}
        return null;
      }}

      // ---- The address bar carries the current view ----------------------
      // This page exists to be pasted into a group chat, so "look at Rory's
      // season" has to survive being copied out of the bar and reopened, and
      // the Back button has to undo a tab switch rather than leave the site.
      function writeRoute(push) {{
        if (syncing) return;
        var tab = activeOf(tabBtns, tabNames) || tabNames[0];
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
        if (ok && friend) showFriend(friend, true);
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
        pl.addEventListener('click', function () {{
          // Pressing the person you are already on goes back to All, so the
          // same button both filters and clears.
          var label = pl.getAttribute('data-friend') || '';
          if (label && pl.classList.contains('active')) label = '';
          showFriend(label, true);
          writeRoute(true);
        }});
      }});

      // Leaderboard rows open that player's card. The name stays a real link
      // so copy-link and open-in-new-tab keep working; the row around it is
      // just a bigger target for the same thing.
      function openFriend(label) {{
        showTab('friends');
        showFriend(label, true);
        writeRoute(true);
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

      // Opens on All. A link like #friends/rory still picks that person.
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


def report_and_filter_queues(data):
    """Drop anything outside ALLOWED_QUEUES, and say what was counted.

    Printed on every build so the queue mix is visible rather than assumed.
    Anything dropped here is a bug upstream, so it is reported loudly rather
    than silently discarded.
    """
    counts, dropped = {}, {}
    for f in data.get("friends", []):
        keep = []
        for m in f.get("seasonMatches", []):
            q = m.get("queue")
            if q in ALLOWED_QUEUES:
                counts[q] = counts.get(q, 0) + 1
                keep.append(m)
            else:
                dropped[q] = dropped.get(q, 0) + 1
        f["seasonMatches"] = keep

    total = sum(counts.values())
    mix = ", ".join(f"{q} {n}" for q, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    print(f"Counting {total} ranked games: {mix}")
    if dropped:
        detail = ", ".join(f"{q!r} {n}" for q, n in sorted(dropped.items()))
        print(f"  ! dropped {sum(dropped.values())} game(s) from queues that should not be "
              f"here: {detail}")


def main():
    data_path = Path(sys.argv[1] if len(sys.argv) > 1 else "data.json")
    out_path = Path(sys.argv[2] if len(sys.argv) > 2 else "dashboard.html")
    if not data_path.exists():
        print(f"Data file not found: {data_path}. Run fetch_data.py first (or use the bundled demo data.json).")
        sys.exit(1)
    data = json.loads(data_path.read_text(encoding="utf-8"))
    data.setdefault("siteUrl", load_site_url())
    report_and_filter_queues(data)
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
