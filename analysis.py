"""Everything the analysis pages show, worked out from the game store.

generate_dashboard.py answers "how is each friend doing". This module answers
the questions that need the other nine players in the game: is this support's
vision good *for a support at this rank*, does a gold lead at fifteen minutes
actually win, who plays worse in the sixth game of a night.

Shape
    Analysis(data, store)   builds one row per player per stored game, the
                            baselines, every game's score and the win-chance
                            model
    .payload()              the JSON the analysis page renders from
    .game_files()           per-day public game files for the breakdown tab
    .for_basic()            the handful of numbers the main page borrows

The work is split by what it is about, not by size:
    analysis_util.py     constants, the map, the two logistic fits
    scoring.py           the rulebook for a game score and a champion score
    analysis.py          this file: rows, ranks, baselines, scores, the model
    analysis_views.py    Players (and jungle) and Champions
    analysis_views2.py   Roles, Time, Duos, Game flow, Records

Three populations are compared throughout, and the names are used
consistently so a caption can be trusted:
    the player     one friend's own games
    the group      every tracked friend's games
    the lobby      everyone else who was in those games, friend or not,
                   which is as close to "players at this level" as the API
                   lets this get without scraping strangers
A baseline is always role-for-role, and for a score rank-for-rank as well. A
support is never held against a mid laner, which is the mistake that makes
every support look blind and broke.

Ranks
    A row's rank is the one read for that player when the game was collected
    (game_store keeps it). Where there is none, because the lookup has not
    reached that game yet, the player was unranked, or the read failed, it is
    the rank of the friend in that game, as the spec asks. Every row therefore
    has a tier, and the pages say how many games have real readings behind
    them.
"""

import bisect
from collections import Counter, defaultdict
from datetime import datetime, timezone

import scoring
from analysis_util import (LANE_ZONE, LANING_END, POOLED, ROLE_NAME, ROLE_TABLE, ROLES, STATS,
                           blue_camps, broad_zone, fit_slope, fit_two, mean, nearest_camp, pct_of,
                           rnd, sigmoid, uk_time, zone_of)
from analysis_site import SiteViews
from analysis_views import PlayerViews
from analysis_views2 import GroupViews
from champion_classes import CLASSES, champion_class, champion_classes, champion_tags

QUANTILE_POINTS = 41
# A rank tier gets its own baseline once this many rows of a role have been
# seen at it. Below that a game is ranked against the whole role, and says so.
TIER_MIN_ROWS = 250
THROW_GOLD = 5000
# A comeback has to have been unlikely as well as far behind: a team of late
# scalers that was 5k down at fifteen and expected to win anyway is not one.
UNLIKELY = 0.40

_TIER_INDEX = {name.upper(): i for i, name in enumerate(scoring.TIER_NAMES)}
_DIVISION = {"I": 1, "II": 2, "III": 3, "IV": 4}


def quantiles(sorted_vals, points=QUANTILE_POINTS):
    last = len(sorted_vals) - 1
    return [round(sorted_vals[round(last * i / (points - 1))], 6) for i in range(points)]


class Analysis(PlayerViews, GroupViews, SiteViews):
    def __init__(self, data, store_games, highlights=None, accounts=None):
        self.data = data
        self.highlights = highlights or []
        # LP, ranks and form per login, from generate_dashboard.lp_export.
        self.accounts = accounts or {}
        self.friends = data.get("friends", [])
        self.labels = [f["label"] for f in self.friends]
        self.merged = bool(data.get("mergedAccounts"))
        # A merged friend carries every account's puuid, so the second
        # account's games are simply more of that person's games.
        self.friend_of = {}
        self.account_of = {}
        for f in self.friends:
            accounts = f.get("puuidLabels") or [f["label"]]
            for k, pu in enumerate(f.get("puuids") or [f.get("puuid")]):
                if pu:
                    self.friend_of[pu] = f["label"]
                    self.account_of[pu] = accounts[k] if k < len(accounts) else f["label"]
        self.current_rank = {f["label"]: self._ranked_now(f) for f in self.friends}
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
        self.lobby_rank = {}
        self._plans = {}
        for g in self.games.values():
            self._ingest(g)
        self.friend_rows = defaultdict(list)
        self.lobby_rows = defaultdict(list)
        self.role_rows = defaultdict(list)
        for r in self.rows:
            if r["role"]:
                self.role_rows[r["role"]].append(r)
            if r["friend"]:
                self.friend_rows[r["friend"]].append(r)
            elif r["role"]:
                self.lobby_rows[r["role"]].append(r)
        self.group_rows = [r for label in self.labels for r in self.friend_rows[label] if r["role"]]
        self._build_baselines()
        self._score_rows()
        self._fit_model()
        self.row_of = {(r["friend"], r["game"]): r for r in self.rows if r["friend"]}
        self._site_init()

    # -- names ---------------------------------------------------------------

    def champ_name(self, slug):
        info = self.slug_info.get(str(slug).lower())
        return info["name"] if info else slug

    def _ddragon_tags(self, slug):
        return (self.slug_info.get(str(slug).lower()) or {}).get("tags")

    def champ_class(self, slug):
        return champion_class(slug, self._ddragon_tags(slug))

    @staticmethod
    def _ranked_now(friend):
        """{0: solo, 1: flex} as [tier, division, lp], from the friend's own
        current rank. The stand-in when a game has no reading of its own."""
        out = {}
        for slot, key in ((0, "solo"), (1, "flex")):
            e = (friend.get("ranked") or {}).get(key) or {}
            if e.get("tier") in _TIER_INDEX:
                out[slot] = [_TIER_INDEX[e["tier"]], _DIVISION.get(e.get("rank"), 1), int(e.get("leaguePoints") or 0)]
        return out

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

    def _ranks_for(self, g):
        """(rank per player, lobby rank, whether any of it was really read).

        Solo queue rank for a solo queue game and flex for anything else, each
        falling back to the other, because a rank in the wrong queue is still
        a far better guess at someone's level than nothing.
        """
        P = g["p"]
        rk = g.get("rk")
        slot = 0 if g.get("q") == 420 else 1

        def read(i):
            pair = rk[i] if rk and i < len(rk) else None
            if not pair:
                return None
            return pair[slot] or pair[1 - slot] or None

        own = [read(i) for i in range(10)]
        mates = []
        for i, p in enumerate(P):
            label = self.friend_of.get(p.get("pu"))
            if label:
                now = self.current_rank.get(label, {})
                r = own[i] or now.get(slot) or now.get(1 - slot)
                if r:
                    own[i] = own[i] or r
                    mates.append(scoring.rank_points(r))
        fallback = scoring.rank_from_points(mean(mates)) if mates else None
        known = [scoring.rank_points(r) for r in own if r]
        lobby = scoring.rank_from_points(mean(known)) if len(known) >= 5 else fallback
        return [r or fallback or lobby for r in own], lobby, own, bool(rk)

    def _ingest(self, g):
        P = g["p"]
        dur_min = max(g["dur"] / 60.0, 1.0)
        frames = len(P[0]["g"])
        last_whole = frames - 2          # the final frame is "game over", not a minute
        v2 = g.get("pv", 1) >= 2

        def at(arr, minute):
            return arr[minute] if minute <= last_whole and minute < len(arr) else None

        ranks, lobby_rank, own_ranks, has_ranks = self._ranks_for(g)
        self.lobby_rank[g["id"]] = lobby_rank

        team_of = [p["t"] for p in P]
        totals = {t: defaultdict(float) for t in (100, 200)}
        for p in P:
            tt = totals[p["t"]]
            tt["k"] += p["k"]
            tt["dmg"] += p["dmg"]
            tt["taken"] += p.get("taken", 0)
            if v2:
                tt["tank"] += p.get("taken", 0) + p.get("mit", 0)
                tt["epic"] += p.get("epic", 0)

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

        # Takedowns in the laning phase, by where they happened, and when each
        # player first took part in one or died.
        takedowns = defaultdict(list)
        first_td, first_death = {}, {}
        deaths_at = defaultdict(list)
        for ev in g.get("kills", []):
            t, x, y, killer, victim = ev[0], ev[1], ev[2], ev[3], ev[4]
            first_death.setdefault(victim, t)
            deaths_at[victim].append(t)
            for pid in [killer] + ev[5:]:
                if 1 <= pid <= 10:
                    first_td.setdefault(pid, t)
                    if t < LANING_END:
                        takedowns[pid].append((zone_of(x, y, team_of[pid - 1]), t))

        by_role = {}
        for i, p in enumerate(P):
            if p["r"]:
                by_role[(p["t"], p["r"])] = i

        game_rows = []
        for i, p in enumerate(P):
            role = p["r"] if p["r"] in ROLES else ""
            team = p["t"]
            tt = totals[team]
            opp = by_role.get((300 - team, role)) if role else None
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
            tk = [z for z, _t in takedowns.get(i + 1, []) if z != "base"]
            roam_n = sum(1 for z in tk if z != own_lane) if own_lane else 0
            # When the roams happened, and how many cost the roamer their life
            # within thirty seconds: a takedown away from lane followed by a
            # death on the way back is a roam that was paid for.
            roam_t, roam_dead = [0, 0, 0, 0], 0
            if own_lane:
                for z, t in takedowns.get(i + 1, []):
                    if z in ("base", own_lane):
                        continue
                    if 180 <= t < LANING_END:
                        roam_t[min(3, (t - 180) // 180)] += 1
                    if any(t < d <= t + 30 for d in deaths_at.get(i + 1, [])):
                        roam_dead += 1

            # Minutes 3 to 14 spent away from lane. Time in base is neither:
            # walking back from a recall is not a roam.
            out_n = lane_n = 0
            if own_lane:
                partner = by_role.get((team, "BOTTOM")) if role == "UTILITY" else None
                for m in range(3, min(15, last_whole + 1)):
                    z = zone_of(p["xy"][2 * m], p["xy"][2 * m + 1], team)
                    if z == "base":
                        continue
                    if partner is not None:
                        pz = zone_of(P[partner]["xy"][2 * m], P[partner]["xy"][2 * m + 1], team)
                        if pz != "bot":
                            continue    # the lane had already moved; nothing was left behind
                    lane_n += 1
                    if z != own_lane:
                        out_n += 1

            team_objs = objs_by_team.get(team, [])
            rank = ranks[i]
            taken = p.get("taken", 0)
            row = {
                "game": g["id"], "pid": i + 1, "t0": g["t0"], "dur": dur_min, "q": g.get("q"),
                "team": team, "win": team == g.get("win"), "role": role, "champ": p["c"],
                "cls": self.champ_class(p["c"]), "friend": self.friend_of.get(p.get("pu")),
                "name": p.get("n", ""),
                "rank": rank, "tier": rank[0] if rank else None, "ranked": bool(own_ranks[i]) and has_ranks,
                "k": p["k"], "d": p["d"], "a": p["a"],
                "kda": (p["k"] + p["a"]) / max(p["d"], 1),
                "kp_n": p["k"] + p["a"], "kp_d": tt["k"],
                "kp": (p["k"] + p["a"]) / tt["k"] if tt["k"] else None,
                "kshare": p["k"] / tt["k"] if tt["k"] else None,
                "cspm": p["cs"] / dur_min, "dpm": p["dmg"] / dur_min,
                "dshare": p["dmg"] / tt["dmg"] if tt["dmg"] else None,
                "dpg": p["dmg"] / p["gold"] if p.get("gold") else None,
                "tshare": taken / tt["taken"] if tt["taken"] else None,
                "vpm": p["vis"] / dur_min, "heal": p.get("heal", 0), "shield": p.get("shield", 0),
                "hs": p.get("heal", 0) + p.get("shield", 0), "cc": p.get("cc", 0),
                "wkc": p.get("wk", 0) + p.get("ctrl", 0),
                "objd": p.get("objDmg", 0), "solo": p.get("solo", 0), "deaths": p["d"],
                # Kept from the newer records only; an older one has no way
                # of telling a tower from a dragon, or a hook from a miss.
                "tur": p.get("tur") if v2 else None,
                "ejg": p.get("ejg") if v2 else None,
                "immob": p.get("immob") if v2 else None,
                "skh": p.get("skh") if v2 else None,
                "epics": p.get("epic", 0) / tt["epic"] if v2 and tt["epic"] else None,
                "tank": (taken + p.get("mit", 0)) / tt["tank"] if v2 and tt["tank"] else None,
                "shpm": max(0, p.get("th", 0) - p.get("heal", 0)) / dur_min if v2 else None,
                "botg15": None,
                "g15": g15, "g10": g10, "x15": x15, "c15": c15,
                "tk_n": len(tk) if own_lane else 0, "roam_n": roam_n,
                "roam_t": roam_t, "roam_dead": roam_dead, "gold15": at(p["g"], 15),
                "roam": roam_n / len(tk) if own_lane and tk else None,
                "zones": Counter(tk), "out_n": out_n, "lane_n": lane_n,
                "objp_n": sum(1 for o in team_objs if (i + 1) in o["parts"]),
                "objp_d": len(team_objs),
                "objp": (sum(1 for o in team_objs if (i + 1) in o["parts"]) / len(team_objs)
                         if team_objs else None),
                "opp": P[opp]["c"] if opp is not None else None,
                "stolen": p.get("stolen", 0), "penta": p.get("penta", 0) if v2 else 0,
            }
            if role == "JUNGLE":
                row["jg"] = self._first_clear_of(p, i + 1, team, last_whole, takedowns, first_td, first_death, v2)
            game_rows.append(row)

        # Each player's share of their team's gold at 15, and each team's share
        # of all the gold in the game, for "did roaming move the gold".
        team15 = {t: sum(r["gold15"] for r in game_rows if r["team"] == t and r["gold15"] is not None)
                  for t in (100, 200)}
        both15 = team15[100] + team15[200]
        for r in game_rows:
            r["gs15"] = r["gold15"] / team15[r["team"]] if r["gold15"] is not None and team15[r["team"]] else None
            r["ts15"] = team15[r["team"]] / both15 if both15 and r["gold15"] is not None else None
        for team in (100, 200):
            adc, sup = by_role.get((team, "BOTTOM")), by_role.get((team, "UTILITY"))
            if adc is not None and sup is not None:
                a, b = game_rows[adc]["g15"], game_rows[sup]["g15"]
                if a is not None and b is not None:
                    game_rows[adc]["botg15"] = game_rows[sup]["botg15"] = a + b
        # The average rank of the other nine, for "winrate by lobby rank".
        points = [scoring.rank_points(r) for r in own_ranks]
        for i, row in enumerate(game_rows):
            others = [v for j, v in enumerate(points) if j != i and v is not None]
            row["lobby"] = scoring.rank_from_points(mean(others)) if len(others) >= 4 else lobby_rank
        self.rows.extend(game_rows)
        self.by_game[g["id"]] = game_rows

        for team in (100, 200):
            sign = 1 if team == 100 else -1
            series = [sign * v for v in lead]
            self.sides[(g["id"], team)] = {
                "id": g["id"], "team": team, "win": g.get("win") == team, "t0": g["t0"],
                "dur": g["dur"], "lead": series, "q": g.get("q"),
                "lead15": series[15] if 15 <= last_whole else None,
                "lead20": series[20] if 20 <= last_whole else None,
                "max": max(series), "min": min(series),
                "champs": [r["champ"] for r in game_rows if r["team"] == team],
                "friends": [r["friend"] for r in game_rows if r["team"] == team and r["friend"]],
            }

    def _first_clear_of(self, p, pid, team, last_whole, takedowns, first_td, first_death, v2):
        """What a jungler did before level 4.

        Camps appear at 0:55, so the 1:00 sample finds them at the camp they
        start on. Level 4 is the end of a first clear. Anything that pulled
        them into a lane or a fight before it is a gank before the clear; a
        first two minutes in the enemy's jungle is an invade.
        """
        if last_whole < 4:
            return None
        xy = p["xy"]
        raw = [(xy[2 * m], xy[2 * m + 1]) for m in range(1, 5)]
        zones = [zone_of(x, y, team) for x, y in raw]
        path = [blue_camps(x, y, team) for x, y in raw]
        camp, dist = nearest_camp(*path[0])
        if zones[0] == "jungle_enemy":
            start = "invade"
        elif dist <= 24:                 # about 1,500 units: at the camp, or walking round it
            start = camp
        else:
            start = "elsewhere"
        out = {"start": start, "path": path, "crab": p.get("crab0") if v2 else None,
               "clear": None, "l4": None, "gankOk": None, "gankLane": None}
        l4 = p.get("l4") if v2 else None
        if l4 is None:
            return out
        out["l4"] = l4
        td = first_td.get(pid)
        fought = td is not None and td < l4
        lane = next((zones[m - 1] for m in (2, 3) if m * 60 < l4 and zones[m - 1] in ("top", "mid", "bot")), None)
        if fought and not lane:
            lane = next((broad_zone(z) for z, t in takedowns.get(pid, []) if t < l4), None)
        if zones[0] == "jungle_enemy" or zones[1] == "jungle_enemy":
            out["clear"] = "invade"
        elif fought or lane:
            out["clear"] = "gank"
            died = first_death.get(pid)
            out["gankOk"] = bool(fought and not (died is not None and died < l4))
            out["gankLane"] = lane
        else:
            out["clear"] = "full"
        return out

    # -- baselines -----------------------------------------------------------

    def _build_baselines(self):
        """Quantiles of every stat for each role, at every rank tier seen
        often enough, and for the role as a whole."""
        pools = defaultdict(lambda: defaultdict(list))
        self.tier_rows = Counter()
        for r in self.rows:
            role = r["role"]
            if not role:
                continue
            self.tier_rows[(role, None)] += 1
            if r["tier"] is not None:
                self.tier_rows[(role, r["tier"])] += 1
            for stat in STATS:
                v = r.get(stat)
                if v is None:
                    continue
                pools[(role, None)][stat].append(v)
                if r["tier"] is not None:
                    pools[(role, r["tier"])][stat].append(v)
        self.quant, self.avg, self.sorted_role = {}, {}, {}
        for key, per in pools.items():
            if key[1] is not None and self.tier_rows[key] < TIER_MIN_ROWS:
                continue
            q, a = {}, {}
            for stat, vals in per.items():
                if len(vals) < 40:
                    continue
                vals.sort()
                q[stat] = quantiles(vals)
                a[stat] = sum(vals) / len(vals)
                if key[1] is None:
                    self.sorted_role[(key[0], stat)] = vals
            self.quant[key], self.avg[key] = q, a
        self.tiers_with_baseline = {role: sorted(t for (r, t) in self.quant if r == role and t is not None)
                                    for role in ROLES}

    def baseline(self, role, tier):
        return self.quant.get((role, tier)) or self.quant.get((role, None)) or {}

    def tier_average(self, role, tier, stat):
        return (self.avg.get((role, tier)) or {}).get(stat)

    def percentile(self, role, stat, value, tier=None):
        """Where a value sits among everyone in that role (at that tier when
        one is given and has a baseline), 0 to 100, high always meaning good."""
        return scoring.percentile(self.baseline(role, tier).get(stat), value, STATS[stat][2])

    @staticmethod
    def pct_in(sorted_vals, value, higher=True):
        """The same, against any sorted list of values."""
        if value is None or not sorted_vals or len(sorted_vals) < 20:
            return None
        lo, hi = bisect.bisect_left(sorted_vals, value), bisect.bisect_right(sorted_vals, value)
        pct = 100.0 * (lo + hi) / 2.0 / len(sorted_vals)
        return pct if higher else 100.0 - pct

    @staticmethod
    def agg(rows, stat):
        """A stat over a set of rows: pooled where that is the honest average."""
        if stat in POOLED:
            n_key, d_key = POOLED[stat]
            d = sum(r[d_key] for r in rows)
            return sum(r[n_key] for r in rows) / d if d else None
        return mean(r.get(stat) for r in rows)

    @staticmethod
    def agg_pc(rows, stat, key="pc"):
        """Mean of the per-game percentiles: how a typical game of theirs ranks."""
        return mean((r.get(key) or {}).get(stat) for r in rows)

    # -- scores --------------------------------------------------------------

    def plan(self, champ, role):
        key = (champ, role)
        if key not in self._plans:
            self._plans[key] = scoring.plan(champ, role, self._ddragon_tags(champ))
        return self._plans[key]

    def _score_rows(self):
        """A game score for every player with a role, and for friends the
        percentile of every stat, at their tier ("pc") and against the whole
        role ("pa"), which the radars and tiles are drawn from."""
        self.champ_wr = defaultdict(lambda: [0, 0])
        for r in self.rows:
            role = r["role"]
            r["score"] = r["wscore"] = r["w"] = None
            if not role:
                continue
            base = self.baseline(role, r["tier"])
            score, _lines = scoring.game_score(self.plan(r["champ"], role), r, base)
            r["score"] = score
            if r["friend"]:
                everyone = self.baseline(role, None)
                r["pc"], r["pa"] = {}, {}
                for stat, meta in STATS.items():
                    v = r.get(stat)
                    if v is None:
                        continue
                    p = scoring.percentile(base.get(stat), v, meta[2])
                    if p is not None:
                        r["pc"][stat] = p
                    p = scoring.percentile(everyone.get(stat), v, meta[2])
                    if p is not None:
                        r["pa"][stat] = p
                w = scoring.rank_weight(r["rank"][0], r["rank"][1]) if r["rank"] else None
                r["w"] = w
                if score is not None and w is not None:
                    r["wscore"] = min(100.0, score * w)
            else:
                # What a champion usually wins, from the people who are not
                # in the group: their own games are the thing being measured.
                for key in ((r["champ"], r["tier"]), (r["champ"], None), ("class:" + r["cls"], None)):
                    c = self.champ_wr[key]
                    c[0] += 1 if r["win"] else 0
                    c[1] += 1

    def champion_average(self, champ, tier):
        """(winrate in points, what it is the winrate of, games behind it).

        The champion at that rank; with too few games, the champion at every
        rank; with too few of those, its class.
        """
        name = self.champ_name(champ)
        cls = self.champ_class(champ)
        tries = [((champ, None), f"{name}, all ranks"), (("class:" + cls, None), f"all {cls}s")]
        if tier is not None:
            tries.insert(0, ((champ, tier), f"{name} in {scoring.TIER_NAMES[tier]}"))
        for key, label in tries:
            w, n = self.champ_wr.get(key, (0, 0))
            if n >= scoring.CHAMPION_AVERAGE_MIN_GAMES:
                return 100.0 * w / n, label, n
        return None, None, 0

    def top_score(self, rows, wins=None, games=None):
        """The top-champions score for a set of one friend's games on one
        champion, with everything needed to show how it was reached."""
        scored = [r for r in rows if r.get("wscore") is not None]
        games = len(rows) if games is None else games
        wins = sum(1 for r in rows if r["win"]) if wins is None else wins
        if not scored or not games:
            return None
        tier = Counter(r["tier"] for r in scored).most_common(1)[0][0]
        spread = Counter((r["rank"][0], r["rank"][1]) for r in scored)
        rank = spread.most_common(1)[0][0]
        champ = Counter(r["champ"] for r in scored).most_common(1)[0][0]
        avg, source, n = self.champion_average(champ, tier)
        out = scoring.champion_score([r["wscore"] for r in scored], wins, games, avg)
        raw = mean(r["score"] for r in scored)
        out.update({
            "raw": raw, "rankW": out["weighted"] / raw if raw else None,
            # Every game carries the weight of the rank it was played at; this
            # is only the spread, so the page can show what those games were
            # rather than pretending they were all at one rank.
            "rank": list(rank), "ranks": [[t, d, c] for (t, d), c in spread.most_common()],
            "wrSource": source, "wrGames": n,
            "scored": len(scored), "games": games, "wins": wins,
            "verdict": "above" if raw >= 55 else "below" if raw <= 45 else "average",
        })
        return out

    @staticmethod
    def pack_score(s):
        """A top-champions score as the page reads it."""
        if not s:
            return None
        return {"score": round(s["score"], 1), "raw": round(s["raw"], 1), "weighted": round(s["weighted"], 1),
                "rankW": rnd(s["rankW"], 3), "rank": s["rank"], "ranks": s["ranks"],
                "gamesMult": round(s["gamesMult"], 2),
                "wrMult": round(s["wrMult"], 3), "adjWr": round(s["adjWr"], 1),
                "champWr": rnd(s["champWr"], 1), "wrSource": s["wrSource"], "wrGames": s["wrGames"],
                "scored": s["scored"], "games": s["games"], "wins": s["wins"], "verdict": s["verdict"]}

    @staticmethod
    def comfort(games):
        return "Main" if games >= 25 else "Comfortable" if games >= 10 else "Learning"

    # -- the win-chance model --------------------------------------------------

    def _fit_model(self):
        """What a gold lead is worth at each minute, twice over.

        First gold alone: one slope a minute. Then gold and how well each
        team's champions hold up from behind. A champion's scaling score is
        how much more often its team wins than its gold at fifteen said it
        would, pulled toward its class until it has thirty games of its own,
        so Twitch does not need a hundred games to be told it is a late
        champion. A team's score is the five added up, and the gap between
        the two teams goes into the fit beside the gold.
        """
        by_minute = defaultdict(list)
        blue = [s for (gid, team), s in self.sides.items() if team == 100]
        for s in blue:
            for m in range(3, len(s["lead"]) - 1):
                by_minute[m].append((s["lead"][m], s["win"]))
        self.slopes, self.slope_se = {}, {}
        for m in sorted(by_minute):
            b, se = fit_slope(by_minute[m])
            if b is not None and len(by_minute[m]) >= 40:
                self.slopes[m], self.slope_se[m] = b, se
        self.model_games = len(blue)
        self.model_points = by_minute

        b15 = self.slopes.get(15)
        by_champ, by_class = defaultdict(lambda: [0.0, 0]), defaultdict(lambda: [0.0, 0])
        miss_of = {}
        if b15 is not None:
            for key, s in self.sides.items():
                if s["lead15"] is None:
                    continue
                miss = (1.0 if s["win"] else 0.0) - sigmoid(b15 * s["lead15"] / 1000.0)
                miss_of[key] = miss
                for c in s["champs"]:
                    for acc in (by_champ[c], by_class[self.champ_class(c)]):
                        acc[0] += miss
                        acc[1] += 1
        class_score = {cls: v[0] / (v[1] + 100.0) for cls, v in by_class.items()}

        def score(c, without=None):
            """A champion's scaling score, optionally with one game's own
            contribution taken back out."""
            total, n = by_champ.get(c, (0.0, 0))
            if without is not None:
                total, n = total - without, n - 1
            return (total + 30.0 * class_score.get(self.champ_class(c), 0.0)) / (n + 30.0)

        self.scaling = {c: score(c) for c in by_champ}
        self.scaling_games = {c: v[1] for c, v in by_champ.items()}
        # A game's own result is left out of the scores used on that game.
        # Otherwise the model is told the answer: a champion's score is made
        # of who won, and the fit would then "discover" that it predicts who
        # won. Leaving it out is what makes the second coefficient honest.
        for key, s in self.sides.items():
            s["scale"] = sum(score(c, miss_of.get(key)) for c in s["champs"])
        for (gid, team), s in self.sides.items():
            s["gap"] = s["scale"] - self.sides[(gid, 300 - team)]["scale"]
        self.slopes2 = {}
        for m in sorted(self.slopes):
            pts = [(s["lead"][m], s["gap"], s["win"]) for s in blue if m < len(s["lead"]) - 1]
            b, d = fit_two(pts, self.slopes[m])
            if b is not None:
                self.slopes2[m] = (b, d)
        gaps = sorted(abs(s["gap"]) for s in blue)
        self.gap_typical = gaps[int(len(gaps) * 0.84)] if gaps else 0.0     # about one standard deviation
        for s in self.sides.values():
            self._extremes(s)

    def _nearest(self, table, minute):
        if not table:
            return None
        if minute in table:
            return table[minute]
        return table[min(table, key=lambda m: abs(m - minute))]

    def win_chance(self, lead, minute, gap=None):
        """Gold alone when no scaling gap is given, both when one is."""
        if lead is None:
            return None
        if gap is not None and self.slopes2:
            b, d = self._nearest(self.slopes2, minute)
            return sigmoid(b * lead / 1000.0 + d * gap)
        b = self._nearest(self.slopes, minute)
        return None if b is None else sigmoid(b * lead / 1000.0)

    def _extremes(self, side):
        """The lowest and highest the scaling-aware win chance went, and
        whether the game counts as a comeback or a throw."""
        lo = hi = None
        for m in range(3, len(side["lead"]) - 1):
            p = self.win_chance(side["lead"][m], m, side["gap"])
            if p is None:
                continue
            if lo is None or p < lo[0]:
                lo = (p, m)
            if hi is None or p > hi[0]:
                hi = (p, m)
        side["lo"], side["hi"] = lo, hi
        side["comeback"] = bool(side["win"] and side["min"] <= -THROW_GOLD and lo and lo[0] < UNLIKELY)
        side["throw"] = bool(not side["win"] and side["max"] >= THROW_GOLD and hi and hi[0] > 1 - UNLIKELY)

    # ======================================================================
    # Payload
    # ======================================================================

    def _stat_meta(self):
        return {k: {"label": v[0], "fmt": v[1], "up": v[2]} for k, v in STATS.items()}

    def _champ_meta(self):
        """Display name, icon id, classes, tags and scaling score for every
        champion that appears."""
        keys = {k.lower(): k for k in (self.data.get("championBySlug") or {})}
        out = {}

        def add(c):
            if c and c not in out:
                classes = champion_classes(c, self._ddragon_tags(c))
                out[c] = {"n": self.champ_name(c), "i": keys.get(c.lower(), c), "c": classes[0],
                          "cs": classes, "tg": champion_tags(c),
                          "s": round(self.scaling.get(c, 0.0), 4)}
        for r in self.rows:
            add(r["champ"])
        for side in self.season_games.values():
            for f in side["friends"]:
                add(f["champ"])
        return out

    def _meta(self):
        season_ids = {k[0] for k in self.season_games}
        stored = season_ids & set(self.games)
        return {
            "generatedAt": self.data.get("generatedAt"),
            "generatedAtMs": self.data.get("generatedAtMs"),
            "platform": self.data.get("platform"),
            "seasonStart": self.data.get("seasonStart"),
            "rankTrackingSince": self.data.get("rankTrackingSince"),
            "ddragon": self.data.get("ddragonVersion"),
            "seasonGames": len(season_ids),
            "storedGames": len(stored),
            "rankedGames": sum(1 for gid in stored if self.games[gid].get("rk")),
            "detailGames": sum(1 for gid in stored if self.games[gid].get("pv", 1) >= 2),
            "merged": self.merged,
            "friends": [{"label": f["label"], "second": bool(f.get("second")),
                         "accounts": f.get("accounts") or [f["label"]]} for f in self.friends],
            "roles": ROLES, "roleName": ROLE_NAME, "classes": CLASSES,
            "roleStats": scoring.ROLE_METRICS, "roleTable": ROLE_TABLE, "stats": self._stat_meta(),
            "tiers": scoring.TIER_NAMES, "tierShort": scoring.TIER_SHORT,
        }

    def _scoring_payload(self):
        """The baselines and the rulebook, so the page can score one game the
        way this module scores a row."""
        quant, avg = {}, {}
        for (role, tier), per in self.quant.items():
            key = "all" if tier is None else str(tier)
            quant.setdefault(role, {})[key] = {m: per[m] for m in scoring.METRICS if m in per}
            avg.setdefault(role, {})[key] = {m: round(v, 4) for m, v in self.avg[(role, tier)].items()
                                              if m in scoring.METRICS}
        return {
            "quant": quant, "avg": avg,
            "rows": {role: {("all" if t is None else str(t)): n for (r, t), n in self.tier_rows.items() if r == role}
                     for role in ROLES},
            "layer": scoring.LAYER_WEIGHT, "role": scoring.ROLE_METRICS, "cls": scoring.CLASS_METRICS,
            "specialist": scoring.SPECIALIST_METRICS, "tag": scoring.TAG_METRICS,
            "overrides": scoring.OVERRIDES, "hypercarry": scoring.HYPERCARRY_WEIGHT,
            "weights": scoring.rank_weight_table(),
            "full": scoring.GAMES_FOR_FULL_WEIGHT, "prior": list(scoring.WINRATE_PRIOR),
            "limits": list(scoring.WINRATE_LIMITS), "tierMin": TIER_MIN_ROWS,
            # A few plans and scores worked out here, for the page to check
            # its own copy of the arithmetic against. See Check in a4_more.js.
            "check": self._check_sample(),
        }

    def _check_sample(self):
        out = []
        for r in sorted((r for r in self.group_rows if r["score"] is not None), key=lambda r: -r["t0"])[:12]:
            out.append({"game": r["game"], "pid": r["pid"], "champ": r["champ"], "role": r["role"],
                        "tier": r["tier"], "score": round(r["score"], 3),
                        "plan": [[layer, m, w, tag] for layer, m, w, tag in self.plan(r["champ"], r["role"])]})
        return out

    # -- the game list and the per-day game files -----------------------------

    def _games_index(self):
        """Every stored game a friend was in, newest first.

        [id, start, seconds, queue, team, won, friends, lobby rank, flag,
         scaling gap, lobby]
        friends  one row each: [label, champion, role, k, d, a, gold @15,
                 game score, rank, level, cs, vision, kill participation %,
                 items in slot order with the trinket last, spells, runes,
                 account]. Account is the login that played it, which differs
                 from the label on a page where second accounts are merged.
        lobby    all ten champions as numbers into champIndex, this team's
                 five first, each team top to support; the names arrive with
                 the game's own file when it is opened
        """
        cix = {c: i for i, c in enumerate(self.champ_index)}
        out = []
        for (gid, team), s in self.sides.items():
            if not s["friends"]:
                continue
            g = self.games[gid]
            rows = [r for r in self.by_game[gid] if r["team"] == team and r["friend"]]
            friends = []
            for r in rows:
                p = g["p"][r["pid"] - 1]
                items = p.get("it") or ((p.get("items") or []) + [0] * 7)[:7]
                friends.append([r["friend"], r["champ"], r["role"], r["k"], r["d"], r["a"], r["g15"],
                                rnd(r["score"], 1), r["rank"][:2] if r["rank"] else None,
                                p.get("lvl"), p.get("cs"), p.get("vis"),
                                round(100 * r["kp"]) if r["kp"] is not None else None,
                                items, p.get("sp") or [0, 0], (p.get("ru") or [0, 0, 0])[:3],
                                self.account_of.get(p.get("pu"), r["friend"])])
            order = sorted(self.by_game[gid], key=lambda r: (r["team"] != team, ROLES.index(r["role"]) if r["role"] else 9))
            out.append([gid, s["t0"], s["dur"], g.get("q"), team, 1 if s["win"] else 0, friends,
                        (self.lobby_rank.get(gid) or [None, None])[:2],
                        1 if s["comeback"] else 2 if s["throw"] else 0, round(s["gap"], 4),
                        [cix.get(r["champ"], -1) for r in order]])
        out.sort(key=lambda g: -g[1])
        return out

    @staticmethod
    def day_key(t0):
        return datetime.fromtimestamp(t0 / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")

    def public_game(self, g):
        """One game as the breakdown tab reads it: no puuids, friends labelled.

        Raw values only, never a percentile or a score. Those move every time
        a baseline grows, which would change every game file on every build
        and upload a season of them each hour. The values never change; the
        page holds the baselines and does the ranking.
        """
        rows = self.by_game[g["id"]]
        rk = g.get("rk")
        slot = 0 if g.get("q") == 420 else 1
        players = []
        for i, p in enumerate(g["p"]):
            r = rows[i]
            # A tracked friend is only ever named by their label, so their
            # Riot ID is left out; everyone else is who the scoreboard said.
            entry = {"n": "" if r["friend"] else p.get("n", ""), "c": p["c"], "t": p["t"], "r": p["r"],
                     "k": p["k"], "d": p["d"], "a": p["a"], "cs": p["cs"], "gold": p["gold"],
                     "dmg": p["dmg"], "vis": p["vis"], "g": p["g"], "xy": p["xy"],
                     "x15": p.get("x15"), "c10": p.get("c10"), "c15": p.get("c15")}
            if r["friend"]:
                entry["f"] = r["friend"]
            pair = rk[i] if rk and i < len(rk) else None
            read = (pair[slot] or pair[1 - slot]) if pair else None
            if read:
                entry["rk"] = read[:2]
            if r["role"]:
                entry["m"] = {m: round(r[m], 6) for m in scoring.METRICS if r.get(m) is not None}
            # What a scoreboard shows beside a champion. Facts about the game,
            # so the file stays the same from one build to the next.
            entry["lvl"] = p.get("lvl")
            if p.get("it"):
                entry["it"], entry["sp"], entry["ru"] = p["it"], p.get("sp"), p.get("ru")
            elif p.get("items"):
                entry["it"] = (p["items"] + [0] * 7)[:7]
            if r.get("jg"):
                # How this jungler's first clear went: where they started, how
                # it ended, when they hit level 4, how many of the first two
                # scuttles they took. Facts about this game alone.
                jg = r["jg"]
                entry["jg"] = [jg["start"], jg["clear"], jg["l4"], jg["crab"]]
            players.append(entry)
        objs = [[o["t"], o["code"], o["team"], o["killer"], o["n"], 1 if o["stolen"] else 0,
                 sorted(o["parts"] - {o["killer"]})] for o in self.objectives.get(g["id"], [])]
        return {"id": g["id"], "q": g.get("q"), "t0": g["t0"], "dur": g["dur"], "patch": g.get("patch"),
                "win": g.get("win"), "p": players, "kills": g.get("kills", []), "obj": objs,
                "bld": g.get("bld", [])}

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
            "jungle": self._jungle_table(),
            "roles": self._roles(),
            "time": self._time(),
            "duos": self._duos(),
            "flow": self._flow(),
            "records": self._records(),
            "usual": self._usual(),
            "scoring": self._scoring_payload(),
            "acc": self.accounts,
            **self._site_payload(),
        }

    # -- what the main page borrows ---------------------------------------------

    def for_basic(self):
        """The few figures the main dashboard shows from here.

        Keyed for lookup rather than shaped for display: generate_dashboard.py
        already knows how its own tables look, and only needs the numbers it
        has no way of working out from a friend's own match rows.
        """
        g15 = {(r["friend"], r["game"]): r["g15"] for r in self.rows if r["friend"]}
        score = {(r["friend"], r["game"]): r["score"] for r in self.rows if r["friend"] and r["score"] is not None}

        seasons = defaultdict(lambda: {"games": 0, "wins": 0, "roles": Counter()})
        for f in self.friends:
            for m in self.season[f["label"]]:
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
            top = self.top_score(stored.get(key, []), s["wins"], s["games"])
            role = s["roles"].most_common(1)[0][0] if s["roles"] else ""
            champ[key] = {"perf": round(top["score"]) if top else 0,
                          "raw": round(top["raw"]) if top else None,
                          "verdict": top["verdict"] if top else None,
                          "comfort": self.comfort(s["games"]), "scored": bool(top),
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
                "score": rnd(mean(r["score"] for r in rows), 0),
            }
        return {"g15": g15, "score": score, "stored": set(self.games), "champ": champ, "player": player}

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
                if s["t0"] >= since_ms and uk_time(s["t0"]).hour < 5]
        if len(late) >= 3:
            wins = sum(1 for s in late if s["win"])
            notes["night"] = {"wins": wins, "losses": len(late) - wins}
        return notes
