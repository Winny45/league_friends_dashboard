"""How one game is scored, and how a champion is ranked from its games.

This file is the rulebook and nothing else: which numbers count for which
role, class and tag, what each rank is worth, and the arithmetic that turns
them into a score. analysis.py supplies the numbers and the baselines.

A game score, 0 to 100
    Up to ten metrics in three layers.
        role    six, chosen for the position            60%
        class   two, chosen for the champion's class    25%
        tags    up to two, from the champion's tags     15%
    Each metric becomes a percentile against everyone in the stored games who
    played the same role at the same rank tier, so 50 is an ordinary game for
    that role at that level. A metric that already counted in an earlier
    layer is not counted again; its slot is simply left empty. A layer with
    nothing in it (an unmapped tag, a jungler's roaming) gives its share to
    the others.

A top-champions score
    the average game score on that champion, each game first multiplied by
    the weight of the rank it was played at
        x  0.5 + 0.01 per game, reaching 1.0 at fifty games
        x  1 + (their winrate - the champion's usual winrate at that rank),
           in points over a hundred, held between 0.85 and 1.15
    capped at 100.

The baselines move as games are added, so every stored game is rescored on
every build. That is deliberate: a score is a place in a field, and the field
is whoever has been met so far.

Still open, and decided here only until the group says otherwise: winning
adds nothing to a game score; deaths weigh the same for everyone; the layer
weights are 60 / 25 / 15.
"""

import bisect

from champion_classes import champion_class, champion_tags

TIER_NAMES = ["Iron", "Bronze", "Silver", "Gold", "Platinum", "Emerald", "Diamond",
              "Master", "Grandmaster", "Challenger"]
TIER_SHORT = ["Iron", "Bronze", "Silver", "Gold", "Plat", "Emerald", "Diamond", "Master", "GM", "Chall"]
DIVISION_NAME = {1: "I", 2: "II", 3: "III", 4: "IV"}

LAYER_WEIGHT = {"role": 0.60, "class": 0.25, "tag": 0.15}

# key: (label, format, higher is better). Formats are the page's: pct is a
# fraction shown as a percentage, k a number shortened to thousands.
METRICS = {
    "cspm": ("CS / min", "f1", True),
    "g15": ("Gold diff @15", "signed", True),
    "solo": ("Solo kills", "f1", True),
    "dshare": ("Damage share", "pct", True),
    "tur": ("Turret damage", "k", True),
    "deaths": ("Deaths", "f1", False),
    "kp": ("Kill participation", "pct", True),
    "epics": ("Objective damage share", "pct", True),
    "ejg": ("Enemy jungle camps taken", "f1", True),
    "vpm": ("Vision / min", "f2", True),
    "wkc": ("Wards killed + control wards", "f1", True),
    "botg15": ("Bot lane gold diff @15", "signed", True),
    "roam": ("Roam takedowns", "pct", True),
    "hs": ("Heal + shield on allies", "k", True),
    "cc": ("CC score", "sec", True),
    "immob": ("Enemies immobilised", "f1", True),
    "tank": ("Damage taken + mitigated share", "pct", True),
    "tshare": ("Damage taken share", "pct", True),
    "dpm": ("Damage to champions / min", "int", True),
    "kshare": ("Kills share of team", "pct", True),
    "skh": ("Skillshots hit", "f1", True),
    "dpg": ("Damage per gold", "f2", True),
    "shpm": ("Self-healing / min", "int", True),
}

# Six per role. The jungle's second was to be "objective takedown share", but
# every jungler is part of nearly every objective their team takes (95 to 99%
# across this group), so it separated nobody. Share of the team's damage to
# epic monsters does.
ROLE_METRICS = {
    "TOP": ["cspm", "g15", "solo", "dshare", "tur", "deaths"],
    "JUNGLE": ["kp", "epics", "g15", "ejg", "vpm", "deaths"],
    "MIDDLE": ["cspm", "g15", "solo", "dshare", "kp", "deaths"],
    "BOTTOM": ["cspm", "g15", "dshare", "tur", "kp", "deaths"],
    "UTILITY": ["vpm", "wkc", "kp", "botg15", "roam", "deaths"],
}

CLASS_METRICS = {
    "Enchanter": ["hs", "kp"],
    "Catcher": ["cc", "immob"],
    "Warden": ["tank", "hs"],
    "Vanguard": ["tank", "cc"],
    "Juggernaut": ["dshare", "tank"],
    "Diver": ["kp", "dpm"],
    "Skirmisher": ["solo", "tur"],
    "Assassin": ["kshare", "solo"],
    "Burst mage": ["dshare", "kp"],
    "Battlemage": ["dpm", "tshare"],
    "Artillery": ["dshare", "skh"],
    "Marksman": ["dshare", "dpg"],
    "Specialist": ["dshare", "kp"],     # for one not named below
}

# A Specialist is a champion no class describes, so each has its own pair.
SPECIALIST_METRICS = {
    "azir": ["dpm", "dshare"],
    "chogath": ["tank", "cc"],
    "fiddlesticks": ["cc", "dshare"],
    "gangplank": ["dshare", "dpg"],
    "gnar": ["cc", "dshare"],
    "graves": ["dshare", "dpg"],
    "heimerdinger": ["dpm", "tur"],
    "kayle": ["dshare", "dpg"],
    "kennen": ["cc", "dshare"],
    "nidalee": ["kp", "ejg"],
    "quinn": ["solo", "tur"],
    "singed": ["tank", "cc"],
    "teemo": ["dpm", "tur"],
    "zilean": ["cc", "kp"],
}

# The wiki's exact tag names. The other sixteen tags (Burst, Stealth, Magic
# and so on) describe a champion without naming anything a match records.
# AoE was to be damage in teamfights; nothing in the data says what a
# teamfight is, so it is whole-game damage share, as the spec allows.
TAG_METRICS = {
    "Crowd Control": "cc",
    "Ally Protection": "hs",
    "AoE": "dshare",
    "Self Healing": "shpm",
    "Mobile": "roam",
    "Durable": "tank",
}

# Only where the defaults mislead. Keyed by lower-case champion id.
#   weight   multiply a metric's weight inside its layer
#   drop     take a role metric out (its slot goes unused)
#   add      extra role metrics, for one role only
OVERRIDES = {
    "bard": {"drop": {"UTILITY": ["wkc"]}},          # he roams instead of sweeping
    "senna": {"add": {"UTILITY": ["cspm"]}},         # a support who is meant to farm
}
# Late scalers are behind at fifteen by design. The wiki tags them
# "Hypercarry", so the rule follows the tag instead of a second list to keep.
# Late-game damage share is not stored, so whole-game damage share stands in.
HYPERCARRY_WEIGHT = {"g15": 0.5, "dshare": 1.5}

GAMES_FOR_FULL_WEIGHT = 50
WINRATE_PRIOR = (5, 10)          # (wins + 5) / (games + 10)
WINRATE_LIMITS = (0.85, 1.15)
CHAMPION_AVERAGE_MIN_GAMES = 50


def rank_weight(tier, division=1):
    """What a game at this rank is worth. Master is 1.00; every tier below is
    0.05 lower than the one above, with -0.01 a division and -0.02 for the
    bottom division, so Diamond runs 0.99 0.98 0.97 0.95."""
    if tier is None:
        return None
    if tier >= 9:
        return 1.10
    if tier == 8:
        return 1.05
    if tier == 7:
        return 1.00
    base = 0.99 - 0.05 * (6 - tier)
    return round(base - {1: 0.0, 2: 0.01, 3: 0.02, 4: 0.04}.get(division, 0.0), 2)


def rank_weight_table():
    """The whole table, for the page that explains a score."""
    rows = []
    for tier in range(9, -1, -1):
        if tier >= 7:
            rows.append([TIER_NAMES[tier], [rank_weight(tier)]])
        else:
            rows.append([TIER_NAMES[tier], [rank_weight(tier, d) for d in (1, 2, 3, 4)]])
    return rows


def rank_name(rank):
    """[tier, division, lp] -> 'Platinum IV'."""
    if not rank:
        return "Unranked"
    tier, div = rank[0], rank[1]
    return TIER_NAMES[tier] if tier >= 7 else f"{TIER_NAMES[tier]} {DIVISION_NAME.get(div, 'IV')}"


def rank_points(rank):
    """A rank as one number, so ranks can be averaged: 4 a tier, 1 a division."""
    if not rank:
        return None
    tier, div, lp = rank[0], rank[1], rank[2] if len(rank) > 2 else 0
    if tier >= 7:
        return 28.0 + (tier - 7) * 4 + min(lp, 400) / 100.0
    return tier * 4.0 + (4 - div) + min(lp, 99) / 100.0


def rank_from_points(points):
    """The nearest [tier, division] to an average of rank_points."""
    if points is None:
        return None
    if points >= 28:
        return [min(9, 7 + int((points - 28) // 4)), 1, 0]
    points = max(0.0, points)
    tier = int(points // 4)
    return [tier, 4 - int(points - tier * 4), 0]


def plan(champ, role, ddragon_tags=None):
    """Which metrics score a champion in a role.

    Returns [(layer, metric, weight inside the layer, tag or None)], in
    display order, with anything already counted left out.
    """
    slug = str(champ or "").lower()
    over = OVERRIDES.get(slug, {})
    role_keys = [m for m in ROLE_METRICS.get(role, []) if m not in over.get("drop", {}).get(role, [])]
    role_keys += [m for m in over.get("add", {}).get(role, []) if m not in role_keys]
    tags = champion_tags(champ)
    weights = dict(HYPERCARRY_WEIGHT) if "Hypercarry" in tags else {}
    weights.update(over.get("weight", {}))
    out = [("role", m, weights.get(m, 1.0), None) for m in role_keys]
    used = set(role_keys)
    cls = champion_class(champ, ddragon_tags)
    class_keys = SPECIALIST_METRICS.get(slug) if cls == "Specialist" else None
    for m in class_keys or CLASS_METRICS.get(cls, []):
        if m not in used:
            out.append(("class", m, 1.0, None))
            used.add(m)
    taken = 0
    for tag in tags:
        m = TAG_METRICS.get(tag)
        if m and m not in used and taken < 2:
            out.append(("tag", m, 1.0, tag))
            used.add(m)
            taken += 1
    return out


def percentile(quantiles, value, higher=True):
    """Where a value sits on a baseline given as evenly spaced quantiles.

    The page ranks one game with the same function written in JavaScript
    (pctOf in a1_core.js), and the two must agree to the last digit, so this
    is the whole algorithm: a value tied with several points takes the middle
    of them, which is what stops "zero solo kills" reading as the 0th
    percentile when half the field has zero; anything else is placed by
    straight line between its neighbours.
    """
    if value is None or not quantiles:
        return None
    n = len(quantiles)
    # How many points are below the value, and how many are at or below it.
    lo, hi = bisect.bisect_left(quantiles, value), bisect.bisect_right(quantiles, value)
    if hi > lo:                       # tied with points lo .. hi-1
        pos = (lo + hi - 1) / 2.0
    elif lo == 0:
        pos = 0.0
    elif lo == n:
        pos = float(n - 1)
    else:
        a, b = quantiles[lo - 1], quantiles[lo]
        pos = lo - 1 + (value - a) / (b - a)
    pct = 100.0 * pos / (n - 1)
    return pct if higher else 100.0 - pct


def game_score(plan_rows, values, baseline):
    """(score or None, breakdown).

    values     metric -> this game's number (None when it could not be measured)
    baseline   metric -> quantiles for the role and rank tier
    breakdown  [layer, metric, tag, value, percentile] for every planned
               metric that could be ranked
    """
    layers = {}
    lines = []
    for layer, metric, weight, tag in plan_rows:
        pct = percentile(baseline.get(metric), values.get(metric), METRICS[metric][2])
        if pct is None:
            continue
        acc = layers.setdefault(layer, [0.0, 0.0])
        acc[0] += pct * weight
        acc[1] += weight
        lines.append([layer, metric, tag, values.get(metric), pct])
    if "role" not in layers:
        return None, lines
    total = sum(LAYER_WEIGHT[layer] for layer in layers)
    score = sum(LAYER_WEIGHT[layer] * acc[0] / acc[1] for layer, acc in layers.items()) / total
    return score, lines


def games_multiplier(games):
    return min(1.0, 0.5 + 0.01 * games)


def adjusted_winrate(wins, games):
    """In points. Ten imaginary games at 50% first, so three wins from three
    is 61.5% and not 100%."""
    return 100.0 * (wins + WINRATE_PRIOR[0]) / (games + WINRATE_PRIOR[1])


def winrate_multiplier(wins, games, champion_average):
    if champion_average is None:
        return 1.0
    m = 1.0 + (adjusted_winrate(wins, games) - champion_average) / 100.0
    return max(WINRATE_LIMITS[0], min(WINRATE_LIMITS[1], m))


def champion_score(weighted_scores, wins, games, champion_average):
    """The top-champions score and its working, or None with no scored game.

    weighted_scores are game scores already multiplied by their rank weight.
    `games` is every game on the champion, scored or not: the multiplier is
    about how much of it they have played.
    """
    if not weighted_scores:
        return None
    avg = sum(weighted_scores) / len(weighted_scores)
    gm = games_multiplier(games)
    wm = winrate_multiplier(wins, games, champion_average)
    return {"weighted": avg, "gamesMult": gm, "wrMult": wm, "score": min(100.0, avg * gm * wm),
            "adjWr": adjusted_winrate(wins, games), "champWr": champion_average}
