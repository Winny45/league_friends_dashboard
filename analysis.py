"""Everything the analysis pages show, worked out from the game store.

generate_dashboard.py answers "how is each friend doing". This module answers
the questions that need the other nine players in the game: is this support's
vision good *for a support in these lobbies*, does a gold lead at fifteen
minutes actually win, who plays worse in the sixth game of a night.

Shape
    Analysis(data, store)   builds one row per player per stored game, the
                            lobby baselines, and the win-chance model
    .payload()              the JSON the analysis page renders from
    .game_files()           per-day public game files for the breakdown tab
    .for_basic()            the handful of numbers the main page borrows

Three populations are compared throughout, and the names are used
consistently so a caption can be trusted:
    the player     one friend's own games
    the group      every tracked friend's games
    the lobby      everyone else who was in those games, friend or not,
                   which is as close to "players at this level" as the API
                   lets this get without scraping strangers
A lobby baseline is always role-for-role. A support is never held against a
mid laner, which is the mistake that makes every support look blind and broke.
"""

import bisect
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from champion_classes import CLASSES, champion_class

ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]
ROLE_NAME = {"TOP": "Top", "JUNGLE": "Jungle", "MIDDLE": "Mid", "BOTTOM": "ADC", "UTILITY": "Support"}
LANE_ZONE = {"TOP": "top", "MIDDLE": "mid", "BOTTOM": "bot", "UTILITY": "bot"}
QUEUE_NAME = {420: "Ranked Solo/Duo", 440: "Ranked Flex"}
MAP_Q = 232          # the far corner of the map in stored (// 64) units
LANING = (180, 840)  # seconds: after the first clear, before lanes dissolve

# key: (label, format, higher is better)
STATS = {
    "kp": ("Kill participation", "pct", True),
    "vpm": ("Vision / min", "f2", True),
    "hs": ("Heal + shield on allies", "k", True),
    "heal": ("Heal on allies", "k", True),
    "shield": ("Shield on allies", "k", True),
    "cc": ("CC score", "sec", True),
    "roam": ("Roam takedowns", "pct", True),
    "deaths": ("Deaths / game", "f1", False),
    "g15": ("Gold diff @15", "signed", True),
    "cspm": ("CS / min", "f1", True),
    "dshare": ("Damage share", "pct", True),
    "dpm": ("Damage / min", "int", True),
    "solo": ("Solo kills", "f1", True),
    "objp": ("Objective participation", "pct", True),
    "objd": ("Objective damage", "k", True),
    "kda": ("KDA", "f1", True),
}
# Six per role: the axes of the radar and the tiles above it.
ROLE_STATS = {
    "UTILITY": ["vpm", "kp", "hs", "roam", "deaths", "cc"],
    "JUNGLE": ["kp", "objp", "objd", "g15", "vpm", "cc"],
    "TOP": ["cspm", "g15", "dshare", "kp", "deaths", "solo"],
    "MIDDLE": ["cspm", "g15", "dshare", "kp", "deaths", "roam"],
    "BOTTOM": ["cspm", "g15", "dshare", "kp", "deaths", "dpm"],
}
# Eight per role for the long comparison table.
ROLE_COMPARE = {
    "UTILITY": ["vpm", "kp", "heal", "shield", "cc", "dshare", "g15", "objp"],
    "JUNGLE": ["kp", "objp", "objd", "g15", "vpm", "cc", "dshare", "deaths"],
    "TOP": ["cspm", "g15", "dshare", "dpm", "kp", "deaths", "solo", "objp"],
    "MIDDLE": ["cspm", "g15", "dshare", "dpm", "kp", "deaths", "roam", "objp"],
    "BOTTOM": ["cspm", "g15", "dshare", "dpm", "kp", "deaths", "vpm", "objp"],
}
# The side-by-side table on the roles tab.
ROLE_TABLE = {
    "UTILITY": ["kp", "vpm", "hs", "cc", "roam", "deaths", "g15"],
    "JUNGLE": ["kp", "objp", "objd", "vpm", "cc", "deaths", "g15"],
    "TOP": ["kp", "cspm", "dshare", "solo", "deaths", "g15"],
    "MIDDLE": ["kp", "cspm", "dshare", "roam", "deaths", "g15"],
    "BOTTOM": ["kp", "cspm", "dshare", "dpm", "deaths", "g15"],
}
# Pooled across games rather than averaged game by game: a 1-for-1 lane phase
# should not weigh the same as a 9-for-12 one.
_POOLED = {"roam": ("roam_n", "tk_n"), "objp": ("objp_n", "objp_d"), "kp": ("kp_n", "kp_d")}

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


def zone_of(xq, yq):
    """Which part of the map a stored position is in. Symmetric, so it reads
    the same for both teams."""
    x, y = xq * 64, yq * 64
    if math.hypot(x, y) < 4300 or math.hypot(14800 - x, 14800 - y) < 4300:
        return "base"
    if x < 2600 or y > 12300:
        return "top"
    if y < 2600 or x > 12300:
        return "bot"
    if abs(x - y) < 1500:
        return "mid"
    if abs(x + y - 14800) < 1300:
        return "river"
    return "jungle"


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


# --- the analysis -------------------------------------------------------------

class Analysis:
    def __init__(self, data, store_games):
        self.data = data
        self.friends = data.get("friends", [])
        self.labels = [f["label"] for f in self.friends]
        self.friend_of = {f.get("puuid"): f["label"] for f in self.friends if f.get("puuid")}
        self.slug_info = {k.lower(): v for k, v in (data.get("championBySlug") or {}).items()}
        self.items = data.get("items") or {}
        self.games = {g["id"]: g for g in store_games if not g.get("remake")}
        # A friend's season, remakes out. The generator flags the old cached
        # rows that predate the remake field before this is built.
        self.season = {f["label"]: [m for m in f.get("seasonMatches", []) if not m.get("remake")]
                       for f in self.friends}
        self.season_games = self._season_games()
        self.rows = []
        self.by_game = {}
        self.sides = {}
        self.objectives = {}
        for g in self.games.values():
            self._ingest(g)
        self.friend_rows = defaultdict(list)
        self.lobby_rows = defaultdict(list)
        for r in self.rows:
            if r["friend"]:
                self.friend_rows[r["friend"]].append(r)
            elif r["role"]:
                self.lobby_rows[r["role"]].append(r)
        self._build_baselines()
        self._fit_model()
        for r in self.rows:
            if r["friend"]:
                r["pc"] = self._row_percentiles(r)
        self._perf_cache = {}
        self.row_of = {(r["friend"], r["game"]): r for r in self.rows if r["friend"]}

    # -- names ---------------------------------------------------------------

    def champ_name(self, slug):
        info = self.slug_info.get(str(slug).lower())
        return info["name"] if info else slug

    def champ_class(self, slug):
        info = self.slug_info.get(str(slug).lower()) or {}
        return champion_class(slug, info.get("tags"))

    def champ_tag(self, slug):
        info = self.slug_info.get(str(slug).lower()) or {}
        return (info.get("tags") or [""])[0]

    # -- season games from data.json (every friend game, stored or not) ------

    def _season_games(self):
        """{(matchId, teamId): {"friends": [...], "win", "t0", "dur", "queue"}}

        Built from the friends' own match rows, so it covers the whole season
        whether or not the game store has caught up to it yet.
        """
        out = {}
        for f in self.friends:
            for m in self.season[f["label"]]:
                key = (m["matchId"], m.get("teamId"))
                side = out.setdefault(key, {
                    "id": m["matchId"], "team": m.get("teamId"), "win": bool(m.get("win")),
                    "t0": m.get("gameStartMs") or 0, "dur": m.get("durationMin") or 0,
                    "queue": m.get("queue"), "friends": []})
                side["friends"].append({
                    "label": f["label"], "champ": m.get("champion"), "role": m.get("position") or "",
                    "k": m.get("kills", 0), "d": m.get("deaths", 0), "a": m.get("assists", 0)})
        return out

    # -- one stored game into rows ------------------------------------------

    def _ingest(self, g):
        P = g["p"]
        dur_min = max(g["dur"] / 60.0, 1.0)
        frames = len(P[0]["g"])
        last_whole = frames - 2          # the final frame is "game over", not a minute

        def at(arr, minute):
            return arr[minute] if minute <= last_whole and minute < len(arr) else None

        team_of = [p["t"] for p in P]
        kills_by_team = {100: 0, 200: 0}
        dmg_by_team = {100: 0, 200: 0}
        for p in P:
            kills_by_team[p["t"]] = kills_by_team.get(p["t"], 0) + p["k"]
            dmg_by_team[p["t"]] = dmg_by_team.get(p["t"], 0) + p["dmg"]

        # Team gold lead, blue minus red, one value per frame.
        lead = [sum(P[i]["g"][m] for i in range(10) if team_of[i] == 100)
                - sum(P[i]["g"][m] for i in range(10) if team_of[i] == 200)
                for m in range(frames)]

        # Epic monsters. Three voidgrubs die within seconds of each other and
        # would otherwise count as three objectives to a dragon's one.
        objs = []
        for ev in sorted(g.get("mon", []), key=lambda e: e[0]):
            t, code, killer, team = ev[0], ev[1], ev[2], ev[3]
            # The API lists everyone who damaged it as assisting, enemies
            # included, so participation is only counted for the takers.
            parts = {pid for pid in [killer] + ev[4:] if 1 <= pid <= 10 and team_of[pid - 1] == team}
            # Not necessarily the previous event: the two junglers often
            # split a camp, and the kills then arrive blue, red, blue.
            camp = next((o for o in reversed(objs) if o["code"] == "HORDE" and o["team"] == team
                         and t - o["t"] < 90), None) if code == "HORDE" else None
            if camp:
                camp["n"] += 1
                camp["parts"] |= parts
                continue
            objs.append({"t": t, "code": code, "team": team, "killer": killer,
                         "parts": parts, "n": 1, "stolen": False})
        # A steal is only labelled when it cannot be anything else: the player
        # is credited with exactly as many steals as epic monsters they killed.
        for i, p in enumerate(P):
            if p.get("stolen"):
                mine = [o for o in objs if o["killer"] == i + 1]
                if len(mine) == p["stolen"]:
                    for o in mine:
                        o["stolen"] = True
        self.objectives[g["id"]] = objs
        objs_by_team = {100: [o for o in objs if o["team"] == 100],
                        200: [o for o in objs if o["team"] == 200]}

        # Takedowns in the laning window, by where they happened.
        takedowns = defaultdict(list)
        for ev in g.get("kills", []):
            t, x, y, killer = ev[0], ev[1], ev[2], ev[3]
            if LANING[0] <= t < LANING[1]:
                for pid in [killer] + ev[5:]:
                    if 1 <= pid <= 10:
                        takedowns[pid].append(zone_of(x, y))

        by_role = {}
        for i, p in enumerate(P):
            if p["r"]:
                by_role[(p["t"], p["r"])] = i

        game_rows = []
        for i, p in enumerate(P):
            role = p["r"] if p["r"] in ROLES else ""
            opp = by_role.get((300 - p["t"], role)) if role else None
            g15 = g10 = x15 = c15 = None
            if opp is not None:
                o = P[opp]
                a, b = at(p["g"], 15), at(o["g"], 15)
                g15 = a - b if a is not None and b is not None else None
                a, b = at(p["g"], 10), at(o["g"], 10)
                g10 = a - b if a is not None and b is not None else None
                if p.get("x15") is not None and o.get("x15") is not None:
                    x15 = p["x15"] - o["x15"]
                if p.get("c15") is not None and o.get("c15") is not None:
                    c15 = p["c15"] - o["c15"]

            own_lane = LANE_ZONE.get(role)
            tk = takedowns.get(i + 1, [])
            roam_n = sum(1 for z in tk if z != own_lane) if own_lane else 0
            zones = Counter(tk)

            # Minutes 3 to 14 spent away from lane. Time in base is neither:
            # walking back from a recall is not a roam.
            out_n = lane_n = 0
            if own_lane:
                partner = by_role.get((p["t"], "BOTTOM")) if role == "UTILITY" else None
                for m in range(3, min(15, last_whole + 1)):
                    z = zone_of(p["xy"][2 * m], p["xy"][2 * m + 1])
                    if z == "base":
                        continue
                    if partner is not None:
                        pz = zone_of(P[partner]["xy"][2 * m], P[partner]["xy"][2 * m + 1])
                        if pz != "bot":
                            continue    # the lane had already moved; nothing was left behind
                    lane_n += 1
                    if z != own_lane:
                        out_n += 1

            team_objs = objs_by_team.get(p["t"], [])
            row = {
                "game": g["id"], "pid": i + 1, "t0": g["t0"], "dur": dur_min, "q": g.get("q"),
                "team": p["t"], "win": p["t"] == g.get("win"), "role": role, "champ": p["c"],
                "cls": self.champ_class(p["c"]), "friend": self.friend_of.get(p.get("pu")),
                "name": p.get("n", ""),
                "k": p["k"], "d": p["d"], "a": p["a"],
                "kda": (p["k"] + p["a"]) / max(p["d"], 1),
                "kp_n": p["k"] + p["a"], "kp_d": kills_by_team.get(p["t"], 0),
                "kp": (p["k"] + p["a"]) / kills_by_team[p["t"]] if kills_by_team.get(p["t"]) else None,
                "cspm": p["cs"] / dur_min, "dpm": p["dmg"] / dur_min,
                "dshare": p["dmg"] / dmg_by_team[p["t"]] if dmg_by_team.get(p["t"]) else None,
                "vpm": p["vis"] / dur_min, "heal": p.get("heal", 0), "shield": p.get("shield", 0),
                "hs": p.get("heal", 0) + p.get("shield", 0), "cc": p.get("cc", 0),
                "objd": p.get("objDmg", 0), "solo": p.get("solo", 0), "deaths": p["d"],
                "g15": g15, "g10": g10, "x15": x15, "c15": c15,
                "tk_n": len(tk) if own_lane else 0, "roam_n": roam_n,
                "roam": roam_n / len(tk) if own_lane and tk else None,
                "zones": zones, "out_n": out_n, "lane_n": lane_n,
                "objp_n": sum(1 for o in team_objs if (i + 1) in o["parts"]),
                "objp_d": len(team_objs),
                "objp": (sum(1 for o in team_objs if (i + 1) in o["parts"]) / len(team_objs)
                         if team_objs else None),
                "opp": P[opp]["c"] if opp is not None else None,
            }
            game_rows.append(row)
        self.rows.extend(game_rows)
        self.by_game[g["id"]] = game_rows

        for team in (100, 200):
            sign = 1 if team == 100 else -1
            series = [sign * v for v in lead]
            self.sides[(g["id"], team)] = {
                "id": g["id"], "team": team, "win": g.get("win") == team, "t0": g["t0"],
                "dur": g["dur"], "lead": series,
                "lead15": series[15] if 15 <= last_whole else None,
                "lead20": series[20] if 20 <= last_whole else None,
                "max": max(series), "min": min(series),
                "friends": [r["friend"] for r in game_rows if r["team"] == team and r["friend"]],
            }

    # -- baselines -----------------------------------------------------------

    def _build_baselines(self):
        """Sorted lobby values per role and stat, for percentiles."""
        self.sorted_lobby = {}
        for role in ROLES:
            for stat in STATS:
                vals = sorted(r[stat] for r in self.lobby_rows[role] if r.get(stat) is not None)
                self.sorted_lobby[(role, stat)] = vals

    def percentile(self, role, stat, value):
        """Where a value sits among lobby players in that role, 0 to 100.
        Already flipped for stats where lower is better, so high is always good."""
        vals = self.sorted_lobby.get((role, stat)) or []
        if value is None or len(vals) < 20:
            return None
        lo, hi = bisect.bisect_left(vals, value), bisect.bisect_right(vals, value)
        pct = 100.0 * (lo + hi) / 2.0 / len(vals)
        return pct if STATS[stat][2] else 100.0 - pct

    def _row_percentiles(self, r):
        if not r["role"]:
            return {}
        wanted = set(ROLE_STATS[r["role"]]) | set(ROLE_COMPARE[r["role"]]) | set(ROLE_TABLE[r["role"]])
        out = {}
        for stat in wanted:
            p = self.percentile(r["role"], stat, r.get(stat))
            if p is not None:
                out[stat] = p
        return out

    @staticmethod
    def agg(rows, stat):
        """A stat over a set of rows: pooled where that is the honest average."""
        if stat in _POOLED:
            n_key, d_key = _POOLED[stat]
            d = sum(r[d_key] for r in rows)
            return sum(r[n_key] for r in rows) / d if d else None
        return mean(r.get(stat) for r in rows)

    @staticmethod
    def agg_pc(rows, stat):
        """Mean of the per-game percentiles: how a typical game of theirs ranks."""
        return mean((r.get("pc") or {}).get(stat) for r in rows)

    def play_score(self, rows):
        """How someone plays against the lobby in their role, 0 to 100, as the
        average percentile over that role's six stats."""
        vals = []
        for r in rows:
            if not r["role"]:
                continue
            got = [r["pc"][s] for s in ROLE_STATS[r["role"]] if s in r.get("pc", {})]
            if got:
                vals.append(sum(got) / len(got))
        return mean(vals)

    # -- the win-chance model --------------------------------------------------

    def _fit_model(self):
        """One slope per minute: what a gold lead at that minute is worth."""
        by_minute = defaultdict(list)
        for (gid, team), s in self.sides.items():
            if team != 100:
                continue
            for m in range(3, len(s["lead"]) - 1):
                by_minute[m].append((s["lead"][m], s["win"]))
        self.slopes, self.slope_se = {}, {}
        for m in sorted(by_minute):
            b, se = fit_slope(by_minute[m])
            if b is not None and len(by_minute[m]) >= 40:
                self.slopes[m], self.slope_se[m] = b, se
        self.model_games = len({gid for gid, team in self.sides if team == 100})
        self.model_points = by_minute

    def slope_at(self, minute):
        if not self.slopes:
            return None
        if minute in self.slopes:
            return self.slopes[minute]
        nearest = min(self.slopes, key=lambda m: abs(m - minute))
        return self.slopes[nearest]

    def win_chance(self, lead, minute):
        b = self.slope_at(minute)
        return None if b is None or lead is None else sigmoid(b * lead / 1000.0)

    # -- performance and comfort ----------------------------------------------

    @staticmethod
    def comfort(games):
        return "Main" if games >= 25 else "Comfortable" if games >= 10 else "Learning"

    def performance(self, wins, games, rows):
        """0 to 100. Half is winrate, pulled toward 50% until there are enough
        games to believe it; half is how they played against the lobby in that
        role. Six wins from six on a champion does not outrank sixty from a
        hundred, which a bare winrate would have it do.
        """
        # Forty imaginary games at 50% before the real ones count. Anything
        # weaker and the docstring above is false: with ten, six from six
        # scored 97 against 73 for sixty from a hundred.
        adj = (wins + 20.0) / (games + 40.0)
        from_wins = max(0.0, min(100.0, 50.0 + (adj - 0.5) * 400.0))
        play = self.play_score(rows)
        score = from_wins if play is None else 0.5 * from_wins + 0.5 * play
        verdict = None if play is None else "above" if play >= 55 else "below" if play <= 45 else "average"
        return round(score), verdict, play

    # ======================================================================
    # Payload sections
    # ======================================================================

    def _stat_meta(self):
        return {k: {"label": v[0], "fmt": v[1], "up": v[2]} for k, v in STATS.items()}

    def _champ_meta(self):
        """Display name, icon id and class for every champion that appears."""
        keys = {k.lower(): k for k in (self.data.get("championBySlug") or {})}
        out = {}
        for r in self.rows:
            c = r["champ"]
            if c not in out:
                out[c] = {"n": self.champ_name(c), "i": keys.get(c.lower(), c),
                          "c": r["cls"], "t": self.champ_tag(c)}
        for side in self.season_games.values():
            for f in side["friends"]:
                c = f["champ"]
                if c and c not in out:
                    out[c] = {"n": self.champ_name(c), "i": keys.get(c.lower(), c),
                              "c": self.champ_class(c), "t": self.champ_tag(c)}
        return out

    def _meta(self):
        season_ids = {k[0] for k in self.season_games}
        return {
            "generatedAt": self.data.get("generatedAt"),
            "generatedAtMs": self.data.get("generatedAtMs"),
            "platform": self.data.get("platform"),
            "seasonStart": self.data.get("seasonStart"),
            "ddragon": self.data.get("ddragonVersion"),
            "seasonGames": len(season_ids),
            "storedGames": len(season_ids & set(self.games)),
            "friends": [{"label": f["label"], "second": bool(f.get("second"))} for f in self.friends],
            "roles": ROLES, "roleName": ROLE_NAME, "classes": CLASSES,
            "roleStats": ROLE_STATS, "stats": self._stat_meta(),
        }

    # -- players ---------------------------------------------------------------

    def _tile(self, rows, role, stat):
        return {"k": stat, "v": rnd(self.agg(rows, stat), 4), "pc": rnd(self.agg_pc(rows, stat), 0),
                "lobby": rnd(self.agg(self.lobby_rows[role], stat), 4)}

    def _heat(self, rows):
        """Where a player stands, kills and dies, by phase, drawn as blue side."""
        size = 28
        grids = [[0] * (size * size) for _ in range(3)]
        dots = {"k": [[], [], []], "a": [[], [], []], "d": [[], [], []]}
        for r in sorted(rows, key=lambda r: -r["t0"]):
            g = self.games[r["game"]]
            p = g["p"][r["pid"] - 1]
            for m in range(2, len(p["g"]) - 1):
                phase = 0 if m < 14 else 1 if m < 25 else 2
                x, y = blue_side(p["xy"][2 * m], p["xy"][2 * m + 1], r["team"])
                cx, cy = min(size - 1, x * size // (MAP_Q + 1)), min(size - 1, y * size // (MAP_Q + 1))
                grids[phase][cy * size + cx] += 1
            for ev in g.get("kills", []):
                kind = "k" if ev[3] == r["pid"] else "d" if ev[4] == r["pid"] else \
                    "a" if r["pid"] in ev[5:] else None
                if not kind:
                    continue
                phase = 0 if ev[0] < 840 else 1 if ev[0] < 1500 else 2
                if len(dots[kind][phase]) < 300:     # 150 points, two numbers each
                    dots[kind][phase].extend(blue_side(ev[1], ev[2], r["team"]))
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        packed, tops = [], []
        for grid in grids:
            top = max(grid) or 1
            tops.append(top)
            packed.append("".join(digits[min(35, v * 35 // top)] for v in grid))
        # "gm" is each phase's own maximum: the digits are scaled per phase to
        # keep their resolution, and the page needs the scale back to add
        # phases together for the all-game view.
        return {"size": size, "g": packed, "gm": tops, "k": dots["k"], "a": dots["a"], "d": dots["d"]}

    def _teammate(self, row, role):
        return next((r for r in self.by_game[row["game"]]
                     if r["team"] == row["team"] and r["role"] == role), None)

    def _roaming(self, rows, role):
        zones = Counter()
        for r in rows:
            zones.update(r["zones"])
        zones.pop("base", None)
        total = sum(zones.values())
        if total < 5:
            return None
        own = LANE_ZONE.get(role)
        order = ([own] if own else []) + [z for z in ("top", "mid", "bot", "river", "jungle") if z != own]
        bar = [[z, round(100.0 * zones.get(z, 0) / total, 1)] for z in order if zones.get(z)]

        def own_share(pop):
            z = Counter()
            for r in pop:
                z.update(r["zones"])
            z.pop("base", None)
            t = sum(z.values())
            return round(100.0 * z.get(own, 0) / t, 1) if t and own else None

        def out_share(pop):
            n = sum(r["lane_n"] for r in pop)
            return round(100.0 * sum(r["out_n"] for r in pop) / n, 1) if n else None

        group = [r for lab in self.labels for r in self.friend_rows[lab] if r["role"] == role]
        lobby = self.lobby_rows[role]
        out = {"bar": bar, "takedowns": total, "jungle": role == "JUNGLE",
               "lobbyOwn": own_share(lobby), "groupOwn": own_share(group)}
        if role == "JUNGLE":
            # A jungler has no lane to leave. What is worth knowing instead is
            # how many early takedowns they find and which lanes get them.
            out["perGame"] = round(total / len(rows), 2)
            lz = Counter()
            for r in lobby:
                lz.update(r["zones"])
            lz.pop("base", None)
            lt = sum(lz.values())
            out["lobbyPerGame"] = round(lt / len(lobby), 2) if lobby else None
            out["lobbyBar"] = [[z, round(100.0 * lz.get(z, 0) / lt, 1)] for z in order if lt and lz.get(z)]
            return out

        mine = self.agg(rows, "roam")
        out["roamShare"] = rnd(100.0 * mine, 1) if mine is not None else None
        lob = self.agg(lobby, "roam")
        out["lobbyRoam"] = rnd(100.0 * lob, 1) if lob is not None else None
        out["outLane"], out["lobbyOut"] = out_share(rows), out_share(lobby)

        # Does it pay? Their own games, split at their own median, so "high"
        # means high for them rather than high for a support in general.
        rated = [r for r in rows if r["roam"] is not None]
        if len(rated) >= 10:
            cut = sorted(r["roam"] for r in rated)[len(rated) // 2]
            high = [r for r in rated if r["roam"] >= cut and r["roam"] > 0]
            high_ids = {id(r) for r in high}
            low = [r for r in rated if id(r) not in high_ids]
            if role == "UTILITY":
                first, second = ("BOTTOM", "ADC"), ("MIDDLE", "Mid")
            elif role == "MIDDLE":
                first, second = (role, "Own lane"), ("BOTTOM", "ADC")
            else:
                first, second = (role, "Own lane"), ("MIDDLE", "Mid")

            def col(pop):
                def lane(which):
                    mates = [self._teammate(r, which) for r in pop]
                    return rnd(mean(m["g15"] for m in mates if m), 0)
                return {"games": len(pop), "wr": pct_of(sum(r["win"] for r in pop), len(pop)),
                        "a": lane(first[0]), "b": lane(second[0])}
            if len(high) >= 4 and len(low) >= 4:
                out["split"] = {"high": col(high), "low": col(low),
                                "aLabel": first[1] + " gold @15", "bLabel": second[1] + " gold @15"}
        return out

    def _players(self):
        out = {}
        for label in self.labels:
            per_role = {}
            mine = self.friend_rows[label]
            counts = Counter(r["role"] for r in mine if r["role"])
            for role, n in counts.most_common():
                if n < 3:
                    continue
                rows = [r for r in mine if r["role"] == role]
                champs = Counter(r["champ"] for r in rows)
                top_champ = champs.most_common(1)[0][0]
                cls = Counter(r["cls"] for r in rows).most_common(1)[0][0]
                lobby = self.lobby_rows[role]
                cls_lobby = [r for r in lobby if r["cls"] == cls]
                group = [r for lab in self.labels for r in self.friend_rows[lab] if r["role"] == role]
                champ_rows = [r for r in rows if r["champ"] == top_champ]
                axes = ROLE_STATS[role]
                compare = []
                for stat in ROLE_COMPARE[role]:
                    compare.append({
                        "k": stat, "me": rnd(self.agg(rows, stat), 4),
                        "champ": rnd(self.agg(champ_rows, stat), 4),
                        "group": rnd(self.agg(group, stat), 4),
                        "cls": rnd(self.agg(cls_lobby, stat), 4) if len(cls_lobby) >= 20 else None,
                        "lobby": rnd(self.agg(lobby, stat), 4),
                        "pc": rnd(self.agg_pc(rows, stat), 0)})
                per_role[role] = {
                    "games": n, "wins": sum(r["win"] for r in rows),
                    "tiles": [self._tile(rows, role, s) for s in axes],
                    "radar": {
                        "axes": axes,
                        "me": [rnd(self.agg_pc(rows, s), 0) for s in axes],
                        "ref": ([rnd(self.percentile(role, s, self.agg(cls_lobby, s)), 0) for s in axes]
                                if len(cls_lobby) >= 20 else None),
                        "refLabel": f"{cls} {ROLE_NAME[role].lower()}s in lobbies",
                    },
                    "heat": self._heat(rows),
                    "roam": self._roaming(rows, role),
                    "compare": {"champ": top_champ, "champGames": len(champ_rows), "cls": cls,
                                "clsGames": len(cls_lobby), "rows": compare},
                }
            if per_role:
                out[label] = per_role
        return out

    # -- champions -------------------------------------------------------------

    @staticmethod
    def _pct_in(sorted_vals, value, higher=True):
        if value is None or not sorted_vals:
            return None
        lo, hi = bisect.bisect_left(sorted_vals, value), bisect.bisect_right(sorted_vals, value)
        pct = 100.0 * (lo + hi) / 2.0 / len(sorted_vals)
        return pct if higher else 100.0 - pct

    def _completed(self, item_id):
        it = self.items.get(str(item_id))
        return bool(it) and it.get("into", 1) == 0 and it.get("gold", 0) >= 1600 and it.get("from", 0) > 0

    def _is_boots(self, item_id):
        it = self.items.get(str(item_id))
        return bool(it) and "Boots" in (it.get("tags") or []) and it.get("gold", 0) >= 900

    def _builds(self, rows):
        seen = defaultdict(lambda: {"games": 0, "wins": 0, "boots": Counter()})
        orders = Counter()
        for r in rows:
            p = self.games[r["game"]]["p"][r["pid"] - 1]
            core, boots = [], None
            for item in p.get("buy", []):
                if self._is_boots(item):
                    boots = boots or item
                elif self._completed(item) and item not in core:
                    core.append(item)
            if len(core) >= 3:
                b = seen[tuple(core[:3])]
                b["games"] += 1
                b["wins"] += 1 if r["win"] else 0
                if boots:
                    b["boots"][boots] += 1
            # Which basic ability is finished first, second, third.
            sk, done, counts = p.get("sk", ""), [], Counter()
            for ch in sk:
                if ch in "QWE":
                    counts[ch] += 1
                    if counts[ch] == 5:
                        done.append(ch)
            if len(done) < 3 and len(sk) >= 9:
                done += [c for c, _ in counts.most_common() if c not in done]
            if len(done) >= 3:
                orders[" → ".join(done[:3])] += 1
        builds = sorted(seen.items(), key=lambda kv: -kv[1]["games"])[:3]
        skill = None
        if orders:
            order, n = orders.most_common(1)[0]
            skill = {"order": order, "share": round(100.0 * n / sum(orders.values()))}
        return ([{"items": list(k), "boots": (v["boots"].most_common(1)[0][0] if v["boots"] else None),
                  "games": v["games"], "wr": pct_of(v["wins"], v["games"])} for k, v in builds], skill)

    def _first_clear(self, rows):
        """Where a jungler is at 2, 3 and 4 minutes, split by which side of the
        map they started on."""
        paths = {"top": [], "bot": []}
        for r in rows:
            p = self.games[r["game"]]["p"][r["pid"] - 1]
            if len(p["g"]) < 7:
                continue
            pts = [blue_side(p["xy"][2 * m], p["xy"][2 * m + 1], r["team"]) for m in (2, 3, 4)]
            paths["top" if pts[0][1] > pts[0][0] else "bot"].append(pts)
        total = len(paths["top"]) + len(paths["bot"])
        if total < 5:
            return None
        out = []
        for side, lst in paths.items():
            if not lst:
                continue
            avg = [[round(mean(p[i][0] for p in lst)), round(mean(p[i][1] for p in lst))] for i in range(3)]
            ends = "top" if avg[2][1] > avg[2][0] else "bot"
            out.append({"start": side, "end": ends, "share": round(100.0 * len(lst) / total), "pts": avg})
        return sorted(out, key=lambda p: -p["share"])

    def _champions(self):
        group = [r for lab in self.labels for r in self.friend_rows[lab] if r["role"]]
        by_key = defaultdict(list)
        for r in group:
            by_key[(r["champ"], r["role"])].append(r)
        lobby_by_key = defaultdict(list)
        for role in ROLES:
            for r in self.lobby_rows[role]:
                lobby_by_key[(r["champ"], role)].append(r)

        out, index = {}, defaultdict(list)
        for (champ, role), rows in by_key.items():
            index[champ].append([role, len(rows)])
            if len(rows) < 3:
                continue
            axes = ROLE_STATS[role]
            own_lobby = lobby_by_key.get((champ, role), [])
            # A champion-specific baseline when there is enough of one,
            # otherwise the whole role, and the page says which.
            scoped = len(own_lobby) >= 30
            base = own_lobby if scoped else self.lobby_rows[role]
            sorted_base = {s: sorted(r[s] for r in base if r.get(s) is not None) for s in axes}

            who = []
            per_friend = defaultdict(list)
            for r in rows:
                per_friend[r["friend"]].append(r)
            for label, mine in sorted(per_friend.items(), key=lambda kv: -len(kv[1])):
                wins = sum(r["win"] for r in mine)
                perf, verdict, _ = self.performance(wins, len(mine), mine)
                who.append({"label": label, "games": len(mine), "perf": perf, "wr": pct_of(wins, len(mine)),
                            "kda": rnd(self.agg(mine, "kda"), 1), "g15": rnd(self.agg(mine, "g15"), 0),
                            "objp": rnd(self.agg(mine, "objp"), 3), "verdict": verdict})

            radar_players = []
            for w in who[:2]:
                mine = per_friend[w["label"]]
                if len(mine) < 3:
                    continue
                radar_players.append({"label": w["label"], "games": len(mine), "vals": [
                    rnd(mean(self._pct_in(sorted_base[s], r.get(s), STATS[s][2]) for r in mine), 0)
                    for s in axes]})

            def gold_curve(pop, minimum):
                ys = []
                for m in range(0, 26):
                    vals = []
                    for r in pop:
                        g = self.games[r["game"]]["p"][r["pid"] - 1]["g"]
                        if m <= len(g) - 2:
                            vals.append(g[m])
                    ys.append(vals if len(vals) >= minimum else None)
                return ys

            gold_players = []
            for w in who[:3]:
                mine = per_friend[w["label"]]
                if len(mine) < 3:
                    continue
                gold_players.append({"label": w["label"], "y": [
                    (round(sum(v) / len(v)) if v else None) for v in gold_curve(mine, 2)]})
            band = {"p25": [], "p50": [], "p75": []}
            for vals in gold_curve(base, 10):
                if not vals:
                    for k in band:
                        band[k].append(None)
                    continue
                vals.sort()
                band["p25"].append(vals[len(vals) // 4])
                band["p50"].append(vals[len(vals) // 2])
                band["p75"].append(vals[(3 * len(vals)) // 4])

            by_opp = defaultdict(list)
            for r in rows:
                if r["opp"]:
                    by_opp[r["opp"]].append(r)
            matchups = [{"opp": opp, "games": len(lst), "wr": pct_of(sum(r["win"] for r in lst), len(lst)),
                         "g15": rnd(self.agg(lst, "g15"), 0)}
                        for opp, lst in sorted(by_opp.items(), key=lambda kv: -len(kv[1]))[:8]]

            builds, skill = self._builds(rows)
            wins = sum(r["win"] for r in rows)
            out[f"{champ}|{role}"] = {
                "champ": champ, "role": role, "games": len(rows), "wr": pct_of(wins, len(rows)),
                "lobby": {"n": len(own_lobby),
                          "wr": pct_of(sum(r["win"] for r in own_lobby), len(own_lobby)) if own_lobby else None},
                "scoped": scoped, "g15": rnd(self.agg(rows, "g15"), 0),
                "who": who,
                "radar": {"axes": axes, "players": radar_players},
                "gold": {"players": gold_players, "band": band},
                "matchups": matchups, "builds": builds, "skill": skill,
                "clear": (self._first_clear(per_friend[who[0]["label"]]) if role == "JUNGLE" else None),
                "clearWho": who[0]["label"],
            }
        listing = [{"champ": c, "roles": sorted(roles, key=lambda x: -x[1]),
                    "games": sum(n for _, n in roles)} for c, roles in index.items()]
        listing.sort(key=lambda x: -x["games"])
        return {"list": listing, "detail": out}

    # -- roles and classes -----------------------------------------------------

    def _role_view(self, role, cls=None):
        def keep(r):
            return r["role"] == role and (cls is None or r["cls"] == cls)
        cols = ROLE_TABLE[role]

        def line(pop, with_pc):
            games = len(pop)
            wins = sum(r["win"] for r in pop)
            vals = {}
            for s in cols + ["kda"]:
                vals[s] = [rnd(self.agg(pop, s), 4), rnd(self.agg_pc(pop, s), 0) if with_pc else None]
            return {"games": games, "wr": pct_of(wins, games), "vals": vals}

        rows = []
        for label in self.labels:
            mine = [r for r in self.friend_rows[label] if keep(r)]
            if mine:
                rows.append(dict(line(mine, True), label=label))
        rows.sort(key=lambda r: -r["games"])
        group = [r for lab in self.labels for r in self.friend_rows[lab] if keep(r)]
        lobby = [r for r in self.lobby_rows[role] if cls is None or r["cls"] == cls]
        return {"rows": rows, "group": line(group, False) if group else None,
                "lobby": line(lobby, False) if lobby else None}

    def _class_matrix(self):
        """Winrate by class for each friend, from every season game rather
        than only the stored ones: it needs nothing but champion and result."""
        cells = defaultdict(lambda: [0, 0])
        for f in self.friends:
            for m in self.season[f["label"]]:
                c = cells[(self.champ_class(m.get("champion")), f["label"])]
                c[0] += 1
                c[1] += 1 if m.get("win") else 0
        return {cls: {lab: cells[(cls, lab)] for lab in self.labels if cells[(cls, lab)][0]}
                for cls in CLASSES if any(cells[(cls, lab)][0] for lab in self.labels)}

    def _insights(self):
        notes = []
        group = [r for lab in self.labels for r in self.friend_rows[lab] if r["role"]]

        def wr(pop):
            return pct_of(sum(r["win"] for r in pop), len(pop))

        ench = [r for r in group if r["role"] == "UTILITY" and r["cls"] == "Enchanter"]
        ench_l = [r for r in self.lobby_rows["UTILITY"] if r["cls"] == "Enchanter"]
        if len(ench) >= 30 and len(ench_l) >= 30:
            a, b = self.agg(ench, "hs"), self.agg(ench_l, "hs")
            if a and b:
                d = round(100.0 * (a - b) / b)
                notes.append(["✨", f"Enchanter supports average {abs(d)}% {'more' if d >= 0 else 'less'} "
                                    f"heal + shield than lobby enchanters ({len(ench)} games)"])
        ass = [r for r in group if r["role"] == "MIDDLE" and r["cls"] == "Assassin"]
        if len(ass) >= 30:
            ahead = [r for r in ass if (self.sides[(r["game"], r["team"])]["lead15"] or 0) >= 2000]
            g15 = self.agg(ass, "g15")
            msg = f"Assassins in mid: {wr(ass)}% winrate over {len(ass)} games"
            if g15 is not None:
                msg += f", gold diff @15 {g15:+.0f}"
            if len(ahead) >= 10:
                lost = sum(1 for r in ahead if not r["win"])
                msg += f", and {round(100.0 * lost / len(ahead))}% of 2k+ team leads at 15 still lost"
            notes.append(["🗡️", msg])
        adc = [r for r in group if r["role"] == "BOTTOM" and r["cls"] == "Marksman"]
        with_w, without = [], []
        for r in adc:
            sup = self._teammate(r, "UTILITY")
            if sup:
                (with_w if sup["cls"] == "Warden" else without).append(r)
        if len(with_w) >= 15 and len(without) >= 30:
            d = self.agg(without, "deaths") - self.agg(with_w, "deaths")
            notes.append(["🎯", f"Marksmen die {abs(d):.1f} {'fewer' if d >= 0 else 'more'} times a game "
                                f"with a Warden support ({len(with_w)} games)"])
        van = [r for r in group if r["cls"] == "Vanguard"]
        if len(van) >= 30:
            first = [r for r in van if self.objectives.get(r["game"])
                     and self.objectives[r["game"]][0]["team"] == r["team"]]
            if len(first) >= 15:
                notes.append(["🛡️", f"Group Vanguards win {wr(first)}% when their team takes the first "
                                    f"objective ({len(first)} games), {wr(van)}% overall"])
        best = None
        for cls in CLASSES:
            mine = [r for r in group if r["cls"] == cls]
            if len(mine) >= 40:
                a = self.play_score(mine)
                if a is not None and (best is None or a > best[0]):
                    best = (a, cls, len(mine))
        if best:
            notes.append(["📈", f"{best[1]}s are what this group plays best against the lobby: "
                                f"{best[0]:.0f}th percentile on average over {best[2]} games"])
        return notes

    def _roles(self):
        views = {}
        for role in ROLES:
            classes = Counter(r["cls"] for lab in self.labels for r in self.friend_rows[lab]
                              if r["role"] == role)
            per = {"All": self._role_view(role)}
            for cls, n in classes.most_common():
                if n >= 5:
                    per[cls] = self._role_view(role, cls)
            views[role] = {"cols": ROLE_TABLE[role], "views": per,
                           "classes": [[c, n] for c, n in classes.most_common() if n >= 5]}
        group = [r for lab in self.labels for r in self.friend_rows[lab] if r["role"]]
        obj = [{"role": role,
                "group": rnd(self.agg([r for r in group if r["role"] == role], "objp"), 3),
                "lobby": rnd(self.agg(self.lobby_rows[role], "objp"), 3)} for role in ROLES]
        obj.sort(key=lambda o: -(o["group"] or 0))
        return {"roles": views, "matrix": self._class_matrix(), "objectives": obj,
                "insights": self._insights()}

    # -- time patterns ---------------------------------------------------------

    @staticmethod
    def _night_of(ms):
        """(weekday, hour) in UK time, with the small hours filed under the
        evening they belong to: a 1am game on Saturday's calendar date is the
        tail of Friday night, and reads that way across one row."""
        uk = uk_time(ms)
        day, hour = uk.weekday(), uk.hour
        if hour < 6:
            day = (day - 1) % 7
        return day, hour

    @staticmethod
    def _hour_label(h):
        return f"{(h % 12) or 12}{'am' if h < 12 else 'pm'}"

    def _time_view(self, entries):
        """entries: (start ms, won, team lead at 15 or None)."""
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        cells = [[[0, 0, 0, 0] for _ in range(24)] for _ in range(7)]
        for t0, win, lead in entries:
            d, h = self._night_of(t0)
            c = cells[d][h]
            c[0] += 1
            c[1] += 1 if win else 0
            if lead is not None:
                c[2] += lead
                c[3] += 1
        total = sum(c[0] for row in cells for c in row)
        order = list(range(6, 24)) + list(range(0, 6))      # an evening, in the order it happens

        def window(day_set, start_idx):
            g = w = 0
            for d in day_set:
                for h in order[start_idx:start_idx + 3]:
                    g += cells[d][h][0]
                    w += cells[d][h][1]
            return g, w

        candidates = []
        for i in range(len(order) - 2):
            span = f"{self._hour_label(order[i])}–{self._hour_label((order[i + 2] + 1) % 24)}"
            g, w = window(range(7), i)
            if g >= max(25, total * 0.03):
                candidates.append((w / g, g, "Any day " + span))
            for d in range(7):
                g, w = window([d], i)
                if g >= max(12, total * 0.015):
                    candidates.append((w / g, g, f"{days[d]} {span}"))
        tiles = {}
        if candidates:
            best, worst = max(candidates), min(candidates)
            tiles["best"] = {"label": best[2], "wr": round(100 * best[0], 1), "games": best[1]}
            tiles["worst"] = {"label": worst[2], "wr": round(100 * worst[0], 1), "games": worst[1]}
        busiest = max(((cells[d][h][0], d, h) for d in range(7) for h in range(24)), default=None)
        if busiest and busiest[0]:
            tiles["busiest"] = {"label": f"{days[busiest[1]]} {self._hour_label(busiest[2])}",
                                "games": busiest[0]}

        def wr_days(ds):
            g = sum(cells[d][h][0] for d in ds for h in range(24))
            w = sum(cells[d][h][1] for d in ds for h in range(24))
            return pct_of(w, g)
        tiles["weekday"], tiles["weekend"] = wr_days(range(5)), wr_days((5, 6))
        packed = [[[c[0], c[1], (round(c[2] / c[3]) if c[3] else None)] for c in row] for row in cells]
        return {"cells": packed, "tiles": tiles, "games": total}

    def _sessions(self, labels):
        """Game number within a sitting, and what the previous result does to
        the next one. A sitting ends when an hour passes with no game."""
        by_number = [[0, 0, 0.0, 0] for _ in range(7)]
        after = {"win": [0, 0], "l1": [0, 0], "l2": [0, 0], "l3": [0, 0]}
        per_label = {}
        for f in self.friends:
            if f["label"] not in labels:
                continue
            mine = [[0, 0] for _ in range(7)]
            games = sorted(self.season[f["label"]], key=lambda m: m.get("gameStartMs") or 0)
            prev_end, number, streak = None, 0, 0
            for m in games:
                t0 = m.get("gameStartMs") or 0
                if prev_end is None or t0 - prev_end > 3600_000:
                    number, streak = 0, None
                number += 1
                idx = min(number, 7) - 1
                win = bool(m.get("win"))
                row = self.row_of.get((f["label"], m["matchId"]))
                for bucket in (by_number[idx], ):
                    bucket[0] += 1
                    bucket[1] += 1 if win else 0
                    if row and row["g15"] is not None:
                        bucket[2] += row["g15"]
                        bucket[3] += 1
                mine[idx][0] += 1
                mine[idx][1] += 1 if win else 0
                if streak is not None:
                    key = "win" if streak == 0 else "l1" if streak == 1 else "l2" if streak == 2 else "l3"
                    after[key][0] += 1
                    after[key][1] += 1 if win else 0
                streak = 0 if win else (streak or 0) + 1
                prev_end = t0 + int((m.get("durationMin") or 0) * 60_000)
            per_label[f["label"]] = mine
        return by_number, after, per_label

    def _time(self):
        def entries(pred):
            return [(s["t0"], s["win"], (self.sides.get((s["id"], s["team"])) or {}).get("lead15"))
                    for s in self.season_games.values() if pred(s)]
        views = {"All": self._time_view(entries(lambda s: True))}
        for label in self.labels:
            views[label] = self._time_view(
                entries(lambda s, label=label: any(f["label"] == label for f in s["friends"])))

        def pack(by_number, after):
            return {"byNumber": [[b[0], b[1], (round(b[2] / b[3]) if b[3] >= 8 else None)] for b in by_number],
                    "after": after}
        by_number, after, per_label = self._sessions(set(self.labels))
        sessions = {"All": pack(by_number, after)}
        for label in self.labels:
            bn, af, _ = self._sessions({label})
            sessions[label] = pack(bn, af)

        fade = []
        for label in self.labels:
            # Ten games a bucket and four buckets, or there is no trend to
            # speak of: with less, one good evening reads as "+40 by game 7".
            pts = [(i, 100.0 * b[1] / b[0], b[0]) for i, b in enumerate(per_label.get(label, [])) if b[0] >= 10]
            if len(pts) < 4:
                continue
            # Weighted least squares through winrate against game number, so
            # one unlucky seventh game cannot draw the line by itself.
            sw = sum(p[2] for p in pts)
            mx = sum(p[0] * p[2] for p in pts) / sw
            my = sum(p[1] * p[2] for p in pts) / sw
            var = sum(p[2] * (p[0] - mx) ** 2 for p in pts)
            slope = sum(p[2] * (p[0] - mx) * (p[1] - my) for p in pts) / var if var else 0.0
            fade.append({"label": label, "delta": round(slope * 6),
                         "pts": [(round(100.0 * b[1] / b[0], 1) if b[0] >= 10 else None)
                                 for b in per_label[label]]})
        steadiest = min(fade, key=lambda f: abs(f["delta"]))["label"] if fade else None
        return {"views": views, "sessions": sessions, "fade": fade, "steadiest": steadiest}

    # -- duos and stacks -------------------------------------------------------

    def _duos(self):
        sides = list(self.season_games.values())
        queues = sorted({s["queue"] for s in sides if s["queue"]})
        solo_q = "Ranked Solo/Duo"

        own = defaultdict(lambda: [0, 0])
        alone = defaultdict(lambda: [0, 0])
        pair = defaultdict(lambda: [0, 0])
        for s in sides:
            if s["queue"] != solo_q:
                continue
            labs = [f["label"] for f in s["friends"]]
            for a in labs:
                own[a][0] += 1
                own[a][1] += 1 if s["win"] else 0
            if len(labs) == 1:
                alone[labs[0]][0] += 1
                alone[labs[0]][1] += 1 if s["win"] else 0
            for i in range(len(labs)):
                for j in range(i + 1, len(labs)):
                    for key in ((labs[i], labs[j]), (labs[j], labs[i])):
                        pair[key][0] += 1
                        pair[key][1] += 1 if s["win"] else 0

        def rate(c):
            return 100.0 * c[1] / c[0] if c[0] else None
        matrix = {}
        for a in self.labels:
            row = {}
            for b in self.labels:
                if a == b:
                    if alone[a][0]:
                        row[b] = [rnd(rate(alone[a]), 1), alone[a][0], None]
                elif pair[(a, b)][0]:
                    apart = mean([rate(own[a]), rate(own[b])])
                    wr = rate(pair[(a, b)])
                    row[b] = [rnd(wr, 1), pair[(a, b)][0], rnd(wr - apart, 1) if apart is not None else None]
            matrix[a] = row

        stacks = {}
        for q in ["All"] + queues:
            sizes = [[0, 0] for _ in range(5)]
            for s in sides:
                if q != "All" and s["queue"] != q:
                    continue
                n = min(len(s["friends"]), 5)
                sizes[n - 1][0] += 1
                sizes[n - 1][1] += 1 if s["win"] else 0
            stacks[q] = sizes

        role_pairs = defaultdict(lambda: [0, 0])
        champ_pairs = defaultdict(lambda: [0, 0])
        bot = defaultdict(lambda: {"g": 0, "w": 0, "lane": []})
        on_champ = defaultdict(lambda: [0, 0])
        for s in sides:
            fr = s["friends"]
            for f in fr:
                c = on_champ[(f["label"], f["champ"])]
                c[0] += 1
                c[1] += 1 if s["win"] else 0
            for i in range(len(fr)):
                for j in range(i + 1, len(fr)):
                    a, b = fr[i], fr[j]
                    if a["role"] in ROLES and b["role"] in ROLES and a["role"] != b["role"]:
                        ra, rb = sorted((a["role"], b["role"]), key=ROLES.index)
                        role_pairs[(ra, rb)][0] += 1
                        role_pairs[(ra, rb)][1] += 1 if s["win"] else 0
                    x, y = sorted((a, b), key=lambda f: f["label"])
                    key = (x["label"], x["champ"], y["label"], y["champ"])
                    champ_pairs[key][0] += 1
                    champ_pairs[key][1] += 1 if s["win"] else 0
            adc = next((f for f in fr if f["role"] == "BOTTOM"), None)
            sup = next((f for f in fr if f["role"] == "UTILITY"), None)
            if adc and sup:
                b = bot[(adc["label"], adc["champ"], sup["label"], sup["champ"])]
                b["g"] += 1
                b["w"] += 1 if s["win"] else 0
                ra, rs = self.row_of.get((adc["label"], s["id"])), self.row_of.get((sup["label"], s["id"]))
                if ra and rs and ra["g15"] is not None and rs["g15"] is not None:
                    b["lane"].append(ra["g15"] + rs["g15"])

        cp = []
        for (la, ca, lb, cb), (g, w) in champ_pairs.items():
            if g < 5:
                continue
            usual = mean([rate(on_champ[(la, ca)]), rate(on_champ[(lb, cb)])])
            wr = 100.0 * w / g
            cp.append({"a": [la, ca], "b": [lb, cb], "games": g, "wr": round(wr, 1),
                       "vs": rnd(wr - usual, 1) if usual is not None else None})
        cp.sort(key=lambda p: -p["games"])
        bl = [{"adc": [k[0], k[1]], "sup": [k[2], k[3]], "games": v["g"], "wr": pct_of(v["w"], v["g"]),
               "lane": rnd(mean(v["lane"]), 0), "laneGames": len(v["lane"])}
              for k, v in bot.items() if v["g"] >= 3]
        bl.sort(key=lambda p: -p["games"])
        return {
            "matrix": matrix, "queues": ["All"] + queues, "stacks": stacks,
            "rolePairs": {f"{a}|{b}": [pct_of(v[1], v[0]), v[0]] for (a, b), v in role_pairs.items()},
            "champPairs": cp[:14], "botPairs": bl[:10],
        }

    # -- game flow -------------------------------------------------------------

    def _lowest_chance(self, side, highest=False):
        best = None
        for m in range(3, len(side["lead"]) - 1):
            p = self.win_chance(side["lead"][m], m)
            if p is None:
                continue
            if best is None or (p > best[0] if highest else p < best[0]):
                best = (p, m)
        return best

    def _turning_point(self, side, after_minute, team):
        """The first baron the given team took after a minute, if any."""
        for o in self.objectives.get(side["id"], []):
            if o["code"] == "BARON_NASHOR" and o["team"] == team and o["t"] > after_minute * 60:
                return {"t": o["t"], "stolen": o["stolen"]}
        return None

    def _flow_story(self, side, comeback):
        rows = [r for r in self.by_game[side["id"]] if r["team"] == side["team"] and r["friend"]]
        extreme = self._lowest_chance(side, highest=not comeback)
        team = side["team"] if comeback else 300 - side["team"]
        return {
            "id": side["id"], "t0": side["t0"], "dur": side["dur"], "lead": side["lead"],
            "friends": [[r["friend"], r["champ"]] for r in rows],
            "from": side["min"] if comeback else side["max"],
            "chance": {"p": round(100 * extreme[0]), "minute": extreme[1]} if extreme else None,
            "baron": self._turning_point(side, extreme[1], team) if extreme else None,
            "objs": [[o["t"], monster_letter(o["code"]), 1 if o["team"] == side["team"] else 0,
                      1 if o["stolen"] else 0] for o in self.objectives.get(side["id"], [])],
        }

    def _flow(self):
        mine = [s for s in self.sides.values() if s["friends"]]
        with15 = [s for s in mine if s["lead15"] is not None]
        everyone15 = [s for s in self.sides.values() if s["lead15"] is not None]
        comebacks = [s for s in mine if s["win"] and s["min"] <= -3000]
        throws = [s for s in mine if not s["win"] and s["max"] >= 3000]
        ahead = [s for s in with15 if s["lead15"] >= 2000]
        ahead_all = [s for s in everyone15 if s["lead15"] >= 2000]

        def wr(pop):
            return pct_of(sum(1 for s in pop if s["win"]), len(pop))

        def buckets(minute):
            got = defaultdict(lambda: [0, 0])
            for lead, win in self.model_points.get(minute, []):
                for l, w in ((lead, win), (-lead, not win)):
                    k = max(-6, min(6, round(l / 1000.0)))
                    got[k][0] += 1
                    got[k][1] += 1 if w else 0
            return [[k, round(100.0 * v[1] / v[0], 1), v[0] // 1] for k, v in sorted(got.items()) if v[0] >= 8]

        players = []
        for label in self.labels:
            ps = [s for s in mine if label in s["friends"]]
            p15 = [s for s in ps if s["lead15"] is not None]
            if len(p15) < 5:
                continue
            up = [s for s in p15 if s["lead15"] >= 2000]
            expected = sum(self.win_chance(s["lead15"], 15) or 0.5 for s in p15)
            players.append({
                "label": label, "games": len(p15), "ahead": len(up), "conv": wr(up) if len(up) >= 3 else None,
                "throws": sum(1 for s in ps if not s["win"] and s["max"] >= 3000),
                "comebacks": sum(1 for s in ps if s["win"] and s["min"] <= -3000),
                "flow": round(10.0 * (sum(1 for s in p15 if s["win"]) - expected) / len(p15), 1)})
        players.sort(key=lambda p: -p["flow"])

        def others(row):
            mates = [r["g15"] for r in self.by_game[row["game"]]
                     if r["team"] == row["team"] and r is not row and r["g15"] is not None]
            return mean(mates)
        spill = []
        for label in self.labels:
            led = [r for r in self.friend_rows[label] if r["g15"] is not None and r["g15"] >= 1000 and r["role"]]
            vals = [v for v in (others(r) for r in led) if v is not None]
            if len(vals) >= 8:
                role = Counter(r["role"] for r in led).most_common(1)[0][0]
                spill.append({"label": label, "role": role, "v": round(mean(vals)), "games": len(vals)})
        spill.sort(key=lambda s: -s["v"])
        base_vals = [v for v in (others(r) for r in self.rows
                                 if r["g15"] is not None and r["g15"] >= 1000) if v is not None]

        big_c = min(comebacks, key=lambda s: s["min"]) if comebacks else None
        big_t = max(throws, key=lambda s: s["max"]) if throws else None
        return {
            "tiles": {"comebacks": len(comebacks), "throws": len(throws),
                      "conv": wr(ahead), "convN": len(ahead), "convLobby": wr(ahead_all),
                      "ahead15": pct_of(sum(1 for s in with15 if s["lead15"] > 0), len(with15)),
                      "games": len(with15), "modelGames": self.model_games},
            "curve": {"b15": rnd(self.slopes.get(15), 4), "b20": rnd(self.slopes.get(20), 4),
                      "se15": rnd(self.slope_se.get(15), 4), "dots": buckets(15)},
            "slopes": {str(m): round(b, 4) for m, b in self.slopes.items()},
            "players": players, "spill": spill,
            "spillBase": round(mean(base_vals)) if base_vals else None,
            "comeback": self._flow_story(big_c, True) if big_c else None,
            "throw": self._flow_story(big_t, False) if big_t else None,
        }

    # -- the game list and the per-day game files -----------------------------

    def _games_index(self):
        """Every stored game a friend was in, newest first, for the picker."""
        out = []
        for (gid, team), s in self.sides.items():
            if not s["friends"]:
                continue
            rows = [r for r in self.by_game[gid] if r["team"] == team and r["friend"]]
            out.append([gid, s["t0"], s["dur"], self.games[gid].get("q"), team, 1 if s["win"] else 0,
                        [[r["friend"], r["champ"], r["role"], r["k"], r["d"], r["a"],
                          r["g15"] if r["g15"] is not None else None] for r in rows]])
        out.sort(key=lambda g: -g[1])
        return out

    @staticmethod
    def day_key(t0):
        return datetime.fromtimestamp(t0 / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")

    def _usual(self):
        """{label: {"Champ|ROLE": [games, [percentile per radar axis]]}}: what a
        normal game on that champion looks like, for "this game vs usual"."""
        groups = defaultdict(list)
        for label in self.labels:
            for r in self.friend_rows[label]:
                if r["role"]:
                    groups[(label, r["champ"], r["role"])].append(r)
        out = defaultdict(dict)
        for (label, champ, role), rows in groups.items():
            out[label][f"{champ}|{role}"] = [len(rows), [rnd(self.agg_pc(rows, s), 0) for s in ROLE_STATS[role]]]
        return out

    def _quantiles(self):
        """The lobby baseline as 101 points per role and stat, so the page can
        rank one game's raw value the same way this module ranks a row."""
        out = {}
        for role in ROLES:
            per = {}
            for stat in ROLE_STATS[role]:
                vals = self.sorted_lobby.get((role, stat)) or []
                if len(vals) >= 20:
                    per[stat] = [round(vals[(len(vals) - 1) * q // 100], 4) for q in range(101)]
            out[role] = per
        return out

    def public_game(self, g):
        """One game as the breakdown tab reads it: no puuids, friends labelled,
        and the comparisons that need the whole dataset already worked out."""
        rows = self.by_game[g["id"]]
        players = []
        for i, p in enumerate(g["p"]):
            r = rows[i]
            entry = {"n": p.get("n", ""), "c": p["c"], "t": p["t"], "r": p["r"],
                     "k": p["k"], "d": p["d"], "a": p["a"], "cs": p["cs"], "gold": p["gold"],
                     "dmg": p["dmg"], "vis": p["vis"], "g": p["g"], "xy": p["xy"],
                     "x15": p.get("x15"), "c10": p.get("c10"), "c15": p.get("c15")}
            if r["friend"]:
                entry["f"] = r["friend"]
            if r["role"]:
                # Raw values, not percentiles. A percentile moves every time
                # the lobby baseline grows, which would change every game file
                # on every build and re-upload a season of them each hour. The
                # values never change; the page holds the baseline and does
                # the ranking.
                entry["fx"] = [rnd(r.get(s), 4) for s in ROLE_STATS[r["role"]]]
            players.append(entry)
        objs = [[o["t"], o["code"], o["team"], o["killer"], o["n"], 1 if o["stolen"] else 0,
                 sorted(o["parts"] - {o["killer"]})] for o in self.objectives.get(g["id"], [])]
        return {"id": g["id"], "q": g.get("q"), "t0": g["t0"], "dur": g["dur"], "patch": g.get("patch"),
                "win": g.get("win"), "p": players, "kills": g.get("kills", []), "obj": objs}

    def game_files(self):
        """{'2026-11-12': {matchId: public game}} for every game with a friend in it."""
        days = defaultdict(dict)
        wanted = {gid for (gid, team), s in self.sides.items() if s["friends"]}
        for gid in wanted:
            g = self.games[gid]
            days[self.day_key(g["t0"])][gid] = self.public_game(g)
        return days

    # -- everything ------------------------------------------------------------

    def payload(self):
        return {
            "meta": self._meta(),
            "champs": self._champ_meta(),
            "items": {k: v["name"] for k, v in self.items.items()},
            "games": self._games_index(),
            "players": self._players(),
            "champions": self._champions(),
            "roles": self._roles(),
            "time": self._time(),
            "duos": self._duos(),
            "flow": self._flow(),
            "quant": self._quantiles(),
            "usual": self._usual(),
        }

    # -- what the main page borrows ---------------------------------------------

    def for_basic(self):
        """The few figures the main dashboard shows from here.

        Keyed for lookup rather than shaped for display: generate_dashboard.py
        already knows how its own tables look, and only needs the numbers it
        has no way of working out from a friend's own match rows.
        """
        g15 = {(r["friend"], r["game"]): r["g15"] for r in self.rows if r["friend"]}

        seasons = defaultdict(lambda: {"games": 0, "wins": 0, "roles": Counter()})
        for f in self.friends:
            for m in self.season[f["label"]]:
                if m.get("remake"):
                    continue
                s = seasons[(f["label"], m.get("champion"))]
                s["games"] += 1
                s["wins"] += 1 if m.get("win") else 0
                if m.get("position"):
                    s["roles"][m["position"]] += 1
        stored = defaultdict(list)
        for label in self.labels:
            for r in self.friend_rows[label]:
                stored[(label, r["champ"])].append(r)
        champ = {}
        for key, s in seasons.items():
            perf, verdict, _ = self.performance(s["wins"], s["games"], stored.get(key, []))
            role = s["roles"].most_common(1)[0][0] if s["roles"] else ""
            champ[key] = {"perf": perf, "verdict": verdict, "comfort": self.comfort(s["games"]),
                          "role": ROLE_NAME.get(role, ""), "games": s["games"], "wins": s["wins"]}

        player = {}
        for label in self.labels:
            rows = [r for r in self.friend_rows[label] if r["role"]]
            if not rows:
                continue
            role = Counter(r["role"] for r in rows).most_common(1)[0][0]
            in_role = [r for r in rows if r["role"] == role]
            player[label] = {
                "role": ROLE_NAME[role], "games": len(rows),
                "g15": rnd(self.agg(rows, "g15"), 0),
                "kp": rnd(self.agg(in_role, "kp"), 3),
                "kpLobby": rnd(self.agg(self.lobby_rows[role], "kp"), 3),
            }
        return {"g15": g15, "stored": set(self.games), "champ": champ, "player": player}

    def week_notes(self, since_ms):
        """Three lines for "this week at a glance" that need the game store."""
        notes = {}
        recent = {label: [r for r in self.friend_rows[label] if r["t0"] >= since_ms and r["role"]]
                  for label in self.labels}

        hogs = [(self.agg(rows, "objp"), label, len(rows)) for label, rows in recent.items()
                if len(rows) >= 4 and self.agg(rows, "objp") is not None]
        if hogs:
            hogs.sort(reverse=True)
            notes["objective"] = {"label": hogs[0][1], "pct": round(100 * hogs[0][0]),
                                  "table": [(l, round(100 * v), n) for v, l, n in hogs]}

        roamers = []
        for label, rows in recent.items():
            laners = [r for r in rows if LANE_ZONE.get(r["role"])]
            if sum(r["tk_n"] for r in laners) >= 6:
                role = Counter(r["role"] for r in laners).most_common(1)[0][0]
                roamers.append((self.agg(laners, "roam"), label, len(laners), LANE_ZONE[role]))
        if roamers:
            roamers.sort(reverse=True)
            notes["roam"] = {"label": roamers[0][1], "pct": round(100 * roamers[0][0]),
                             "lane": roamers[0][3],
                             "table": [(l, round(100 * v), n) for v, l, n, _ in roamers]}

        late = [s for s in self.season_games.values()
                if s["t0"] >= since_ms and uk_time(s["t0"]).hour < 6]
        if len(late) >= 3:
            wins = sum(1 for s in late if s["win"])
            notes["night"] = {"wins": wins, "losses": len(late) - wins}
        return notes
