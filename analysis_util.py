"""Constants and small functions shared by the analysis modules.

Nothing in here knows about the dataset. It is the vocabulary: what the roles
are called, where the game phases start, how a stored position becomes an
area of the map, and the handful of sums everything else is built from.
"""

import math
from datetime import datetime, timedelta, timezone

import rift_zones
from scoring import METRICS

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
ROLE_NAME = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}
LANE_ZONE = {"TOP": "top", "MIDDLE": "mid", "BOTTOM": "bot", "UTILITY": "bot"}
QUEUE_ID_NAME = {420: "Ranked Solo/Duo", 440: "Ranked Flex"}
MAP_Q = 232          # the far corner of the map in stored (// 64) units

# One set of game phases for every view: laning to 15, mid game to 25, late
# after. In seconds, and as the minute a per-minute sample falls in.
LANING_END, MID_END = 900, 1500


def phase_of_second(t):
    return 0 if t < LANING_END else 1 if t < MID_END else 2


def phase_of_minute(m):
    return 0 if m < 15 else 1 if m < 25 else 2


# Everything a row can be averaged over. The scoring metrics, plus the few
# that are shown but never scored.
STATS = dict(METRICS)
STATS.update({
    "heal": ("Heal on allies", "k", True),
    "shield": ("Shield on allies", "k", True),
    "objp": ("Objective participation", "pct", True),
    "objd": ("Objective damage", "k", True),
    "kda": ("KDA", "f1", True),
})
STATS["deaths"] = ("Deaths / game", "f1", False)

# The side-by-side table on the roles tab: role-only stats, so a support is
# never shown a CS column to look bad in.
ROLE_TABLE = {
    "UTILITY": ["kp", "vpm", "hs", "cc", "roam", "deaths", "botg15"],
    "JUNGLE": ["kp", "epics", "ejg", "vpm", "cc", "deaths", "g15"],
    "TOP": ["kp", "cspm", "dshare", "solo", "tur", "deaths", "g15"],
    "MIDDLE": ["kp", "cspm", "dshare", "solo", "roam", "deaths", "g15"],
    "BOTTOM": ["kp", "cspm", "dshare", "dpg", "tur", "deaths", "g15"],
}
# Pooled across games rather than averaged game by game: a 1-for-1 lane phase
# should not weigh the same as a 9-for-12 one.
POOLED = {"roam": ("roam_n", "tk_n"), "objp": ("objp_n", "objp_d"), "kp": ("kp_n", "kp_d")}

MONSTER_NAME = {
    "DRAGON:FIRE_DRAGON": "Infernal Drake", "DRAGON:WATER_DRAGON": "Ocean Drake",
    "DRAGON:EARTH_DRAGON": "Mountain Drake", "DRAGON:AIR_DRAGON": "Cloud Drake",
    "DRAGON:HEXTECH_DRAGON": "Hextech Drake", "DRAGON:CHEMTECH_DRAGON": "Chemtech Drake",
    "DRAGON:ELDER_DRAGON": "Elder Dragon", "RIFTHERALD": "Rift Herald",
    "BARON_NASHOR": "Baron Nashor", "HORDE": "Voidgrubs", "ATAKHAN": "Atakhan",
}


def monster_letter(code):
    if code.startswith("DRAGON"):
        return "E" if "ELDER" in code else "D"
    return {"RIFTHERALD": "H", "BARON_NASHOR": "B", "HORDE": "G", "ATAKHAN": "A"}.get(code, "?")


# --- small maths --------------------------------------------------------------

def sigmoid(x):
    if x < -40:
        return 0.0
    if x > 40:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def rnd(v, places=1):
    return None if v is None else round(v, places)


def pct_of(wins, games):
    return round(100.0 * wins / games, 1) if games else None


def uk_time(ms):
    """A game's start in UK wall-clock time, worked out by hand.

    British Summer Time runs from 01:00 UTC on the last Sunday of March to
    01:00 UTC on the last Sunday of October. Done here rather than with
    zoneinfo because that needs a timezone database Windows does not ship,
    and a local rehearsal build has to give the same answer as the runner.
    """
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

    def last_sunday(month):
        d = datetime(dt.year, month, 31, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    summer = last_sunday(3) <= dt < last_sunday(10)
    return dt + timedelta(hours=1 if summer else 0)


# --- the map ------------------------------------------------------------------

def zone_of(xq, yq, team):
    """Which area a stored position is in, from that player's side of things.

    One of: top, mid, bot, river_top, river_bot, jungle_own, jungle_enemy,
    base. The areas are the ones the page draws (rift_zones.py is made from
    the same drawing), so a takedown counted in the top river is one that
    would be drawn on it.
    """
    z = rift_zones.raw_zone(xq, yq)
    if z.startswith("jungle"):
        mine = "jungle_blue" if team == 100 else "jungle_red"
        return "jungle_own" if z == mine else "jungle_enemy"
    if z.startswith("base"):
        return "base"
    return z


def broad_zone(z):
    """top / mid / bot / river / jungle: the five blocks of the roaming bar."""
    return "river" if z.startswith("river") else "jungle" if z.startswith("jungle") else z


def blue_side(xq, yq, team):
    """A position as it would be if the player were on blue, so every game can
    be drawn on one map.

    A reflection across the river, not a turn about the centre. Turning the
    map half way round does put red's base where blue's is, but it also sends
    the top lane to the bottom, so a red-side top laner's whole game was being
    drawn in the bot lane. Reflecting across the line from the baron pit to
    the dragon pit swaps the bases and leaves every lane where it is.
    """
    return (xq, yq) if team == 100 else (MAP_Q - yq, MAP_Q - xq)


def blue_camps(xq, yq, team):
    """The same idea for a jungle route, where it is the camps that have to
    land in the right place and not the lanes.

    The jungle is not mirrored across the river: red team's blue buff is on
    their bot side, blue team's on their top side. It is the map turned half
    way round. So a route is turned, and a red-side jungler who starts at
    their red buff is drawn starting at blue side's red buff.
    """
    return (xq, yq) if team == 100 else (MAP_Q - xq, MAP_Q - yq)


# Where blue team's camps stand, in stored units. A jungler's position at
# 1:00, five seconds after the camps appear, is beside the one they start on.
JUNGLE_CAMPS = {
    "blue": (3821 // 64, 7901 // 64), "gromp": (2110 // 64, 8450 // 64), "wolves": (3780 // 64, 6444 // 64),
    "raptors": (6944 // 64, 5459 // 64), "red": (7765 // 64, 4020 // 64), "krugs": (8400 // 64, 2700 // 64),
}
CAMP_NAME = {"blue": "Blue buff", "gromp": "Gromp", "wolves": "Wolves", "raptors": "Raptors",
             "red": "Red buff", "krugs": "Krugs"}


def nearest_camp(xq, yq):
    """(camp, distance in stored units) for a position already turned to blue side."""
    best = min(JUNGLE_CAMPS.items(), key=lambda kv: math.hypot(kv[1][0] - xq, kv[1][1] - yq))
    return best[0], math.hypot(best[1][0] - xq, best[1][1] - yq)


# --- the win-chance model -----------------------------------------------------

def fit_slope(points):
    """b in P(win) = sigmoid(b * lead_in_thousands), by Newton's method.

    `points` are (lead, won) for one team per game. Each is used twice, once
    as it is and once from the other team's chair, which is what pins the
    curve to 50% at an even game without having to fit an intercept.
    Returns (b, standard error).
    """
    if len(points) < 20:
        return None, None
    xs = [p[0] / 1000.0 for p in points]
    ys = [1.0 if p[1] else 0.0 for p in points]
    b = 0.3
    info = 0.0
    for _ in range(40):
        grad = info = 0.0
        for x, y in zip(xs, ys):
            s = sigmoid(b * x)
            # Both chairs give the same contribution, hence the factor of two
            # in neither: it cancels in the Newton step.
            grad += x * (y - s)
            info += x * x * s * (1 - s)
        if info <= 1e-12:
            return None, None
        step = grad / info
        b += max(-1.0, min(1.0, step))
        if abs(step) < 1e-7:
            break
    return b, 1.0 / math.sqrt(info) if info > 0 else None


def fit_two(points, start_b=0.3):
    """(b, d) in P(win) = sigmoid(b * lead_in_thousands + d * scaling_gap).

    The same symmetric trick as fit_slope with a second term: how far one
    team's champions out-scale the other's. Returns (b, d), or (None, None)
    when the fit does not settle.
    """
    if len(points) < 40:
        return None, None
    rows = [(p[0] / 1000.0, p[1], 1.0 if p[2] else 0.0) for p in points]
    b, d = start_b, 0.0
    for _ in range(60):
        g1 = g2 = h11 = h12 = h22 = 0.0
        for x, z, y in rows:
            s = sigmoid(b * x + d * z)
            w = s * (1 - s)
            g1 += x * (y - s)
            g2 += z * (y - s)
            h11 += x * x * w
            h12 += x * z * w
            h22 += z * z * w
        det = h11 * h22 - h12 * h12
        if det <= 1e-12:
            return None, None
        s1 = (h22 * g1 - h12 * g2) / det
        s2 = (h11 * g2 - h12 * g1) / det
        b += max(-1.0, min(1.0, s1))
        d += max(-5.0, min(5.0, s2))
        if abs(s1) < 1e-7 and abs(s2) < 1e-7:
            break
    return b, d
