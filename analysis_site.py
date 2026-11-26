"""The numbers the site's newer pages need on top of the analysis tabs.

Methods of Analysis, like analysis_views.py. The overhaul turned the site into
one set of pages with a profile for each player, and most of what a profile
shows is a view of rows analysis.py has already built. What is new is here:

    the champion index        one row per champion, role, rank and patch, so
                              the page can filter without a round trip
    champion files            one small file per champion for its page,
                              fetched when it is opened, like the game files
    overview                  top ten champions and this week
    profiles                  per player: champion cards, classes, friends
                              played with, stack sizes, the biggest comeback
    game bests                single-game records with a top three
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import scoring
from analysis_util import LANE_ZONE, ROLES, STATS, mean, pct_of, rnd, uk_time
from analysis_views import CALLOUT_GAMES, LOW_GAMES


def _division(v):
    """A ladder position (400 a tier, 100 a division) as a whole number of
    divisions, Master and above counting as one step each."""
    tier = min(9, int(v // 400))
    return tier * 4 + (3 if tier >= 7 else int((v - tier * 400) // 100))


def _ladder_name(v):
    tier = min(9, int(v // 400))
    if tier >= 7:
        return scoring.TIER_NAMES[tier]
    return f"{scoring.TIER_NAMES[tier]} {scoring.DIVISION_NAME[4 - int((v - tier * 400) // 100)]}"

CARD_MIN = 10           # a champion card on a profile needs this many games
CHAMPION_ROLE_MIN = 5   # a champion's page lists a role from this many games
COUNTER_SHOW = 12       # matchups listed on a champion's page
TOP_MIN = 10            # a top-ten champion needs this many games


def patch_key(p):
    try:
        a, b = str(p).split(".")[:2]
        return int(a), int(b)
    except ValueError:
        return 0, 0


class SiteViews:

    # -- set-up ------------------------------------------------------------

    def _site_init(self):
        champs = {r["champ"] for r in self.rows}
        for side in self.season_games.values():
            champs.update(f["champ"] for f in side["friends"] if f["champ"])
        self.champ_index = sorted(c for c in champs if c)
        self.patches = sorted({g.get("patch") for g in self.games.values() if g.get("patch")}, key=patch_key)

    # -- the champion index ---------------------------------------------------

    def _champ_cube(self):
        """[champion, role, tier, patch, group games, group wins, all games, all wins].

        Champion, role and patch are numbers into champIndex, roles and
        patches; tier is the rank tier the row was played at, -1 for none.
        "All" is every player in the stored games, the group among them.
        """
        cix = {c: i for i, c in enumerate(self.champ_index)}
        pix = {p: i for i, p in enumerate(self.patches)}
        cells = defaultdict(lambda: [0, 0, 0, 0])
        for r in self.rows:
            if not r["role"]:
                continue
            patch = self.games[r["game"]].get("patch")
            key = (cix[r["champ"]], ROLES.index(r["role"]), -1 if r["tier"] is None else r["tier"], pix.get(patch, -1))
            c = cells[key]
            c[2] += 1
            c[3] += 1 if r["win"] else 0
            if r["friend"]:
                c[0] += 1
                c[1] += 1 if r["win"] else 0
        return [list(k) + v for k, v in sorted(cells.items())]

    def _ban_table(self):
        """How often each champion is banned, for ban rates beside the cube.

        bans   [[champion, tier, patch, games it was banned in]]
        games  [[tier, patch, games with bans recorded]]

        Only games stored with their bans count (record version 4), and a
        champion banned by both teams counts once. A game's tier is the
        middle of its players' tiers, since a ban belongs to nobody's rank.
        """
        by_key = {str(k): v for k, v in (self.data.get("championByKey") or {}).items()}
        cix = {c.lower(): i for i, c in enumerate(self.champ_index)}
        pix = {p: i for i, p in enumerate(self.patches)}
        tiers = defaultdict(list)
        for r in self.rows:
            if r["tier"] is not None:
                tiers[r["game"]].append(r["tier"])
        bans, games = defaultdict(int), defaultdict(int)
        for gid in {r["game"] for r in self.rows}:
            g = self.games[gid]
            if "bans" not in g:
                continue
            ts = sorted(tiers.get(gid, []))
            key = (ts[len(ts) // 2] if ts else -1, pix.get(g.get("patch"), -1))
            games[key] += 1
            seen = set()
            for side in g["bans"]:
                for cid in side:
                    slug = by_key.get(str(cid))
                    ci = cix.get(slug.lower()) if slug else None
                    if ci is not None and ci not in seen:
                        seen.add(ci)
                        bans[(ci,) + key] += 1
        return {"bans": [list(k) + [n] for k, n in sorted(bans.items())],
                "games": [list(k) + [n] for k, n in sorted(games.items())]}

    # -- one file per champion -----------------------------------------------

    def champion_files(self):
        """{champion: its page's data}, for every champion seen in a role."""
        by_cr = defaultdict(list)
        for r in self.rows:
            if r["role"]:
                by_cr[(r["champ"], r["role"])].append(r)
        role_totals = Counter(r["role"] for r in self.rows if r["role"])
        out = defaultdict(lambda: {"roles": {}})
        for (champ, role), rows in by_cr.items():
            if len(rows) < CHAMPION_ROLE_MIN:
                continue
            group = [r for r in rows if r["friend"]]
            wins = self._wins(rows)
            overall = 100.0 * wins / len(rows)

            # winrate per patch, everyone and the group
            per_patch = defaultdict(lambda: [0, 0, 0, 0])
            for r in rows:
                c = per_patch[self.games[r["game"]].get("patch")]
                c[0] += 1
                c[1] += 1 if r["win"] else 0
                if r["friend"]:
                    c[2] += 1
                    c[3] += 1 if r["win"] else 0
            patch = [[p] + per_patch[p] for p in sorted(per_patch, key=patch_key) if p]

            # counters: each lane opponent, from every stored game
            vs = defaultdict(list)
            for r in rows:
                if r["opp"]:
                    vs[r["opp"]].append(r)
            counters = sorted(([opp, len(lst), self._wins(lst)] for opp, lst in vs.items()),
                              key=lambda c: -c[1])[:COUNTER_SHOW * 2]

            # the average player of it at each rank
            by_tier = defaultdict(list)
            for r in rows:
                if r["tier"] is not None:
                    by_tier[r["tier"]].append(r)
            by_rank = [[t, len(lst), self._wins(lst), rnd(self.agg(lst, "cspm"), 2),
                        rnd(self.agg(lst, "dshare"), 3), rnd(self.agg(lst, "g15"), 0),
                        rnd(self.agg(lst, "roam"), 3)]
                       for t, lst in sorted(by_tier.items()) if len(lst) >= 5]

            # the group on it
            per_friend = defaultdict(list)
            for r in group:
                per_friend[r["friend"]].append(r)
            friends = []
            for label, mine in sorted(per_friend.items(), key=lambda kv: -len(kv[1])):
                friends.append([label, len(mine), self._wins(mine), rnd(self.agg(mine, "kda"), 1),
                                rnd(self.agg(mine, "g15"), 0), rnd(mean(r["score"] for r in mine), 0)])

            builds, skill = self._builds(rows)
            out[champ]["roles"][role] = {
                "all": [len(rows), wins], "group": [len(group), self._wins(group)],
                "pick": round(100.0 * len(rows) / role_totals[role], 2) if role_totals[role] else None,
                "patch": patch, "counters": counters, "byRank": by_rank, "friends": friends,
                "builds": builds, "skill": skill, "overall": round(overall, 2),
            }
        return dict(out)

    # -- overview ------------------------------------------------------------

    def _top10(self):
        """The ten best champion-and-player pairs by the top champions score."""
        best = []
        for label in self.labels:
            season = Counter()
            wins = Counter()
            roles = defaultdict(Counter)
            for m in self.season[label]:
                season[m.get("champion")] += 1
                wins[m.get("champion")] += 1 if m.get("win") else 0
                if m.get("position"):
                    roles[m.get("champion")][m["position"]] += 1
            rows = defaultdict(list)
            for r in self.friend_rows[label]:
                rows[r["champ"]].append(r)
            for champ, n in season.items():
                if n < TOP_MIN:
                    continue
                top = self.top_score(rows.get(champ, []), wins[champ], n)
                if not top:
                    continue
                role = roles[champ].most_common(1)[0][0] if roles[champ] else ""
                best.append([label, champ, role, round(top["score"], 1), n, pct_of(wins[champ], n)])
        best.sort(key=lambda b: -b[3])
        return best[:10]

    def _week(self):
        """Five lines for "this week", Monday to now, UK time."""
        ms = self.data.get("generatedAtMs") or 0
        now = uk_time(ms)
        monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        # uk_time shifts the clock rather than changing its zone, so Monday on
        # the shifted clock is turned back into a real moment by the same shift.
        offset = now - datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        since_ms = int((monday - offset).timestamp() * 1000)
        sides = [s for s in self.season_games.values() if uk_time(s["t0"]) >= monday]
        out = {"from": monday.strftime("%a %d %b").replace(" 0", " "), "items": []}

        rec = defaultdict(lambda: [0, 0])
        for s in sides:
            for f in s["friends"]:
                rec[f["label"]][0 if s["win"] else 1] += 1
        if rec:
            label, (w, l) = max(rec.items(), key=lambda kv: (kv[1][0] - kv[1][1], kv[1][0]))
            if w + l >= 4 and w > l:
                out["items"].append(["streak", label, f"{label} is {w}W {l}L this week", None])

        notes = self.week_notes(since_ms)
        if notes.get("objective"):
            n = notes["objective"]
            out["items"].append(["objective", n["label"], f"{n['label']} took part in {n['pct']}% of their team's objectives", None])
        night = [s for s in sides if uk_time(s["t0"]).hour < 5]
        if len(night) >= 3:
            w = sum(1 for s in night if s["win"])
            out["items"].append(["night", None, f"The group is {w}W {len(night) - w}L after midnight", None])

        pairs = defaultdict(lambda: [0, 0, Counter()])
        for s in sides:
            labs = sorted(s["friends"], key=lambda f: f["label"])
            for i in range(len(labs)):
                for j in range(i + 1, len(labs)):
                    p = pairs[(labs[i]["label"], labs[j]["label"])]
                    p[0 if s["win"] else 1] += 1
                    p[2][frozenset((labs[i]["role"], labs[j]["role"]))] += 1
        if pairs:
            (a, b), (w, l, rl) = max(pairs.items(), key=lambda kv: (kv[1][0] - kv[1][1], kv[1][0]))
            if w + l >= 3 and w > l:
                bot = rl.most_common(1)[0][0] == frozenset(("BOTTOM", "UTILITY"))
                out["items"].append(["duo", a, f"{a} + {b}: {w}W {l}L{' bot lane' if bot else ''}", b])

        # Ranks this week, from each login's end-of-day solo and flex readings:
        # the last reading before Monday against the latest one.
        monday_key = monday.strftime("%Y-%m-%d")
        owner = {}
        for f in self.friends:
            for a in f.get("accounts") or [f["label"]]:
                owner[a] = f["label"]
        climb, promos = Counter(), []
        for acct, acc in (self.accounts or {}).items():
            for qk, qn in (("solo", "Solo/Duo"), ("flex", "Flex")):
                daily = ((acc.get("q") or {}).get(qk) or {}).get("daily") or []
                if not daily or daily[-1][0] < monday_key:
                    continue
                before = [v for d, v in daily if d < monday_key]
                start, end = (before[-1] if before else daily[0][1]), daily[-1][1]
                if qk == "solo":
                    climb[owner.get(acct, acct)] += end - start
                if before and _division(end) > _division(start):
                    promos.append((acct, f"{_ladder_name(start)} → {_ladder_name(end)}"
                                   + ("" if qk == "solo" else " in Flex")))
        if climb:
            label, lp = climb.most_common(1)[0]
            if lp > 0:
                out["items"].append(["climber", label, f"{label} is up {lp} LP in Solo/Duo since Monday", None])
        if promos:
            out["items"].append(["promo", promos[0][0], " · ".join(f"{l}: {txt}" for l, txt in promos), None])

        # The best single game, and who played the most.
        week_rows = [r for r in self.rows if r["friend"] and r["score"] is not None and r["t0"] >= since_ms]
        if week_rows:
            r = max(week_rows, key=lambda r: r["score"])
            day = uk_time(r["t0"]).strftime("%A")
            out["items"].append(["best", r["friend"], f"{r['friend']} on {self.champ_name(r['champ'])}, {day}",
                                 [r["game"], r["team"], round(r["score"], 1)]])
        if rec:
            label, (w, l) = max(rec.items(), key=lambda kv: (sum(kv[1]), kv[1][0]))
            if w + l >= 5:
                out["items"].append(["grinder", label, f"{label} has played {w + l} games this week ({w}W {l}L)", None])

        # A champion someone played this week and never before this season.
        scored = {(r["friend"], r["game"]): r["score"] for r in self.rows if r["friend"]}
        newest = []
        for label in self.labels:
            seen, fresh = set(), defaultdict(list)
            for m in sorted(self.season[label], key=lambda m: m.get("gameStartMs") or 0):
                c = m.get("champion")
                if (m.get("gameStartMs") or 0) < since_ms:
                    seen.add(c)
                elif c not in seen:
                    fresh[c].append(m)
            for c, ms_ in fresh.items():
                newest.append((len(ms_), sum(1 for m in ms_ if m.get("win")), label, c, ms_))
        if newest:
            n, w, label, c, ms_ = max(newest, key=lambda x: (x[0], x[1]))
            sc = [scored[(label, m["matchId"])] for m in ms_ if scored.get((label, m.get("matchId"))) is not None]
            avg = f", average score {round(sum(sc) / len(sc))}" if sc else ""
            out["items"].append(["newpick", label, f"{label} tried {self.champ_name(c)} for the first time: {w}W {n - w}L{avg}", c])

        comebacks = [self.sides[(s["id"], s["team"])] for s in sides
                     if (s["id"], s["team"]) in self.sides and self.sides[(s["id"], s["team"])]["comeback"]]
        if comebacks:
            c = min(comebacks, key=lambda s: s["min"])
            who = c["friends"][0]
            day = uk_time(c["t0"]).strftime("%A")
            out["items"].append(["comeback", who, f"{who} won from {self._gold(c['min'])} on {day}", [c["id"], c["team"]]])
        return out

    @staticmethod
    def _gold(v):
        a = abs(v)
        s = f"{a / 1000:.1f}k" if a >= 1000 else str(round(a))
        return ("+" if v > 0 else "−" if v < 0 else "") + s

    # -- profiles --------------------------------------------------------------

    def _champ_card(self, label, champ, season_rows, stored):
        """One champion on a player's Champions tab."""
        n = len(season_rows)
        wins = sum(1 for m in season_rows if m.get("win"))
        roles = Counter(m.get("position") for m in season_rows if m.get("position") in ROLES)
        role = roles.most_common(1)[0][0] if roles else None
        kda = mean(((m.get("kills", 0) + m.get("assists", 0)) / max(1, m.get("deaths", 0))) for m in season_rows)
        card = {"champ": champ, "role": role, "games": n, "wins": wins, "kda": rnd(kda, 1),
                "score": rnd(mean(r["score"] for r in stored), 0), "top": self.pack_score(self.top_score(stored, wins, n))}
        in_role = [r for r in stored if r["role"] == role]
        if role and len(in_role) >= 3:
            tier = Counter(r["tier"] for r in in_role if r["tier"] is not None).most_common(1)
            tier = tier[0][0] if tier else None
            # Against that champion in that role at their rank, then at every
            # rank, then the role at their rank: the narrowest group that has
            # enough games in it to rank against.
            pool = [r for r in self.role_rows[role] if r["champ"] == champ and not r["friend"]]
            ref, scope = [r for r in pool if r["tier"] == tier], "rank"
            if len(ref) < 30:
                ref, scope = pool, "all"
            if len(ref) < 30:
                ref, scope = [r for r in self.role_rows[role] if r["tier"] == tier and not r["friend"]], "role"
            axes = scoring.ROLE_METRICS[role]
            vals = []
            for s in axes:
                srt = sorted(r[s] for r in ref if r.get(s) is not None)
                vals.append(rnd(self.pct_in(srt, self.agg(in_role, s), STATS[s][2]), 0))
            card["radar"] = {"axes": axes, "vals": vals, "tier": tier, "scope": scope, "n": len(ref)}
        return card

    def _profiles(self):
        out = {}
        for f in self.friends:
            label = f["label"]
            season = self.season[label]
            stored = self.friend_rows[label]
            prof = {}

            by_champ = defaultdict(list)
            for m in season:
                by_champ[m.get("champion")].append(m)
            rows_by_champ = defaultdict(list)
            for r in stored:
                rows_by_champ[r["champ"]].append(r)
            prof["champs"] = [self._champ_card(label, c, lst, rows_by_champ.get(c, []))
                              for c, lst in sorted(by_champ.items(), key=lambda kv: -len(kv[1]))
                              if c and len(lst) >= CARD_MIN]

            # by class, against that class at their rank among everyone else
            tier = Counter(r["tier"] for r in stored if r["tier"] is not None).most_common(1)
            tier = tier[0][0] if tier else None
            classes = defaultdict(lambda: {"champs": Counter(), "games": 0, "wins": 0})
            for m in season:
                c = classes[self.champ_class(m.get("champion"))]
                c["champs"][m.get("champion")] += 1
                c["games"] += 1
                c["wins"] += 1 if m.get("win") else 0
            ref = defaultdict(lambda: [0, 0])
            for role in ROLES:
                for r in self.lobby_rows[role]:
                    if r["tier"] == tier:
                        x = ref[r["cls"]]
                        x[0] += 1
                        x[1] += 1 if r["win"] else 0
            score_by_cls = defaultdict(list)
            for r in stored:
                if r["score"] is not None:
                    score_by_cls[r["cls"]].append(r["score"])
            prof["classes"] = sorted(
                ([cls, [ch for ch, _ in c["champs"].most_common(5)], c["games"], c["wins"],
                  pct_of(ref[cls][1], ref[cls][0]) if ref[cls][0] >= 30 else None,
                  rnd(mean(score_by_cls[cls]), 0)] for cls, c in classes.items()),
                key=lambda c: -c[2])
            prof["tier"] = tier

            # with each friend: together, and the friend's winrate without them
            together = defaultdict(lambda: [0, 0])
            for s in self.season_games.values():
                labs = [x["label"] for x in s["friends"]]
                if label in labs:
                    for o in labs:
                        if o != label:
                            together[o][0] += 1
                            together[o][1] += 1 if s["win"] else 0
            withf = []
            for o, (g, w) in sorted(together.items(), key=lambda kv: -kv[1][0]):
                apart = [s for s in self.season_games.values()
                         if any(x["label"] == o for x in s["friends"]) and not any(x["label"] == label for x in s["friends"])]
                roles = Counter(x["role"] for s in self.season_games.values() for x in s["friends"]
                                if x["label"] == o and x["role"] in ROLES)
                withf.append([o, [r for r, _ in roles.most_common(2)], g, w, len(apart), sum(1 for s in apart if s["win"])])
            prof["with"] = withf

            stacks = [[0, 0] for _ in range(5)]
            for s in self.season_games.values():
                if any(x["label"] == label for x in s["friends"]):
                    k = min(len(s["friends"]), 5) - 1
                    stacks[k][0] += 1
                    stacks[k][1] += 1 if s["win"] else 0
            prof["stacks"] = stacks

            mine = [s for s in self.sides.values() if label in s["friends"] and s["comeback"]]
            if mine:
                prof["comeback"] = self._flow_story(min(mine, key=lambda s: s["lo"][0]), True)
            out[label] = prof
        return out

    def _roam_extra(self, rows, role, tier):
        """What the Roaming tab adds to the roaming numbers already on a role."""
        own = LANE_ZONE.get(role)
        if not own:
            return None
        ref_rows, _t = self._ref_rows(role, tier)
        rated = [r for r in rows if r["roam"] is not None]
        out = {}
        if len(rated) >= 2 * LOW_GAMES:
            cut = sorted(r["roam"] for r in rated)[len(rated) // 2]
            high = [r for r in rated if r["roam"] >= cut and r["roam"] > 0]
            hi_ids = {id(r) for r in high}
            low = [r for r in rated if id(r) not in hi_ids]

            def share(pop, lane):
                mates = [r if lane == role else self._teammate(r, lane) for r in pop]
                return rnd(mean(m["gs15"] for m in mates if m and m.get("gs15") is not None), 4)
            out["gs"] = {lane: [share(high, lane), share(low, lane)] for lane in ROLES}
            out["ts"] = [rnd(mean(r["ts15"] for r in high if r.get("ts15") is not None), 4),
                         rnd(mean(r["ts15"] for r in low if r.get("ts15") is not None), 4)]

        def dead(pop):
            n = sum(r["roam_n"] for r in pop)
            return rnd(100.0 * sum(r.get("roam_dead", 0) for r in pop) / n, 1) if n else None
        out["dead"] = [dead(rows), dead(ref_rows)]
        t = [sum(r.get("roam_t", [0, 0, 0, 0])[k] for r in rows) for k in range(4)]
        out["timing"] = [rnd(100.0 * v / sum(t), 1) for v in t] if sum(t) else None
        champs = defaultdict(list)
        for r in rows:
            champs[r["champ"]].append(r)
        out["byChamp"] = [[c, len(lst), rnd(self.agg(lst, "roam"), 3), pct_of(self._wins(lst), len(lst))]
                          for c, lst in sorted(champs.items(), key=lambda kv: -len(kv[1])) if len(lst) >= LOW_GAMES]
        return out

    # -- single-game records ------------------------------------------------

    def _game_bests(self):
        """The best single games, with a top three each, so a profile can show
        the ones its player holds or is close to."""
        defs = [("hs", "Guardian angel", "✨", "Most heal and shield on allies in a game", lambda r: r["hs"]),
                ("vis", "Eagle eye", "👁️", "Highest vision score in a game", lambda r: r["vpm"] * r["dur"]),
                ("k", "Killing spree", "⚔️", "Most kills in a game", lambda r: r["k"]),
                ("dmg", "Heavy hitter", "💥", "Most damage to champions in a game", lambda r: r["dpm"] * r["dur"]),
                ("score", "Masterclass", "🏅", "Highest game score", lambda r: r["score"]),
                ("cs", "Farmer", "🌾", "Most CS in a game", lambda r: round(r["cspm"] * r["dur"]) if r.get("cspm") is not None else None),
                ("dshare", "Main character", "🎯", "Highest share of the team's damage in a game",
                 lambda r: r["dshare"]),
                # Ranked cannot be surrendered before fifteen minutes, so anything
                # shorter is a remake or a leaver, not a fast win.
                ("fast", "Speedrun", "⏱️", "Fastest win", lambda r: r["dur"] * 60 if r["win"] and r["dur"] >= 15 else None),
                ("long", "Marathon game", "🕰️", "Longest game", lambda r: r["dur"] * 60)]
        # How the page shows each number: a count unless named here.
        fmt = {"dshare": "pct", "fast": "time", "long": "time"}
        low = {"fast"}
        out = []
        for key, title, icon, desc, fn in defs:
            vals = [(fn(r), r) for label in self.labels for r in self.friend_rows[label] if fn(r) is not None]
            vals.sort(key=lambda v: v[0] if key in low else -v[0])
            top, seen = [], set()
            for v, r in vals:
                if r["friend"] in seen:
                    continue
                seen.add(r["friend"])
                top.append([r["friend"], (round(v, 4) if key == "dshare" else round(v, 1)) if isinstance(v, float) else v, r["game"], r["team"], r["champ"], r["t0"]])
                if len(top) == 3:
                    break
            if top:
                out.append({"key": key, "title": title, "icon": icon, "desc": desc, "top": top, "fmt": fmt.get(key, "int")})
        return out

    # -- everything ------------------------------------------------------------

    def _site_payload(self):
        return {
            "champIndex": self.champ_index,
            "patches": self.patches,
            "cube": self._champ_cube(),
            "banc": self._ban_table(),
            "top10": self._top10(),
            "week": self._week(),
            "profiles": self._profiles(),
            "bests": self._game_bests(),
            "spells": self.data.get("spells") or {},
            "runes": self.data.get("runes") or {},
        }
