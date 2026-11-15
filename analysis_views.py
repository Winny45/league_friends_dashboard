"""The Players tab (with jungle pathing) and the Champions tab.

Methods of Analysis, kept in their own file because they are about what one
page shows rather than about the dataset. Everything here reads rows that
analysis.py has already built and scored; nothing here changes them.
"""

from collections import Counter, defaultdict

import scoring
from analysis_util import (CAMP_NAME, LANE_ZONE, MAP_Q, ROLE_NAME, ROLE_TABLE, ROLES, STATS,
                           blue_side, broad_zone, mean, pct_of, phase_of_minute, phase_of_second, rnd)

# Small-sample rules, the same everywhere: an average over fewer than ten
# games is shown greyed, a cell with fewer than five is left blank, and
# nothing is called best or worst on fewer than thirty.
LOW_GAMES, BLANK_GAMES, CALLOUT_GAMES = 10, 5, 30
TIER_LINE_MIN = 100          # rows of a role at a tier before it gets a radar line
BAR_ORDER = ("top", "mid", "bot", "river", "jungle")
BAR_PARTS = {"river": ("river_top", "river_bot"), "jungle": ("jungle_own", "jungle_enemy")}


class PlayerViews:

    # -- shared ---------------------------------------------------------------

    def _rows_at(self, role, tier):
        """Everyone's rows for a role at a tier (None for every tier)."""
        cache = self.__dict__.setdefault("_rt_cache", {})
        key = (role, tier)
        if key not in cache:
            cache[key] = [r for r in self.role_rows[role] if tier is None or r["tier"] == tier]
        return cache[key]

    def _ref_rows(self, role, tier):
        """The comparison group for a player: their role at their tier when
        that tier has a baseline, otherwise the whole role. Returns
        (rows, tier or None)."""
        if tier is not None and tier in self.tiers_with_baseline.get(role, []):
            return self._rows_at(role, tier), tier
        return self._rows_at(role, None), None

    @staticmethod
    def _wins(rows):
        return sum(1 for r in rows if r["win"])

    # -- players ---------------------------------------------------------------

    def _heat(self, rows):
        """Where a player stands, kills and dies, by phase, drawn as blue side."""
        size = 28
        grids = [[0] * (size * size) for _ in range(3)]
        dots = {"k": [[], [], []], "a": [[], [], []], "d": [[], [], []]}
        for r in sorted(rows, key=lambda r: -r["t0"]):
            g = self.games[r["game"]]
            p = g["p"][r["pid"] - 1]
            for m in range(2, len(p["g"]) - 1):
                x, y = blue_side(p["xy"][2 * m], p["xy"][2 * m + 1], r["team"])
                cx, cy = min(size - 1, x * size // (MAP_Q + 1)), min(size - 1, y * size // (MAP_Q + 1))
                grids[phase_of_minute(m)][cy * size + cx] += 1
            for ev in g.get("kills", []):
                kind = "k" if ev[3] == r["pid"] else "d" if ev[4] == r["pid"] else \
                    "a" if r["pid"] in ev[5:] else None
                if not kind:
                    continue
                phase = phase_of_second(ev[0])
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

    @staticmethod
    def _zone_shares(rows):
        """({zone: share of takedowns}, total) over the detailed zones."""
        zones = Counter()
        for r in rows:
            zones.update(r["zones"])
        total = sum(zones.values())
        return ({z: 100.0 * n / total for z, n in zones.items()} if total else {}), total

    def _roaming(self, rows, role, tier):
        shares, total = self._zone_shares(rows)
        if total < 5:
            return None
        ref_rows, ref_tier = self._ref_rows(role, tier)
        ref, _n = self._zone_shares(ref_rows)

        def block(z, src):
            parts = BAR_PARTS.get(z)
            if parts:
                return sum(src.get(p, 0.0) for p in parts)
            return src.get(z, 0.0)

        bar = []
        for z in BAR_ORDER:
            v = block(z, shares)
            if v <= 0 and block(z, ref) <= 0:
                continue
            entry = {"z": z, "v": round(v, 1), "ref": round(block(z, ref), 1)}
            if z in BAR_PARTS:
                entry["parts"] = [[p, round(shares.get(p, 0.0), 1), round(ref.get(p, 0.0), 1)] for p in BAR_PARTS[z]]
            bar.append(entry)
        bar.sort(key=lambda b: -b["v"])
        out = {"bar": bar, "takedowns": total, "jungle": role == "JUNGLE",
               "refTier": ref_tier, "refGames": len(ref_rows)}
        if role == "JUNGLE":
            # A jungler has no lane to leave. What is worth knowing instead is
            # how many early takedowns they find and which lanes get them.
            out["perGame"] = round(total / len(rows), 2)
            rt = sum(sum(r["zones"].values()) for r in ref_rows)
            out["refPerGame"] = round(rt / len(ref_rows), 2) if ref_rows else None
            return out

        def out_share(pop):
            n = sum(r["lane_n"] for r in pop)
            return round(100.0 * sum(r["out_n"] for r in pop) / n, 1) if n else None

        mine = self.agg(rows, "roam")
        out["roamShare"] = rnd(100.0 * mine, 1) if mine is not None else None
        theirs = self.agg(ref_rows, "roam")
        out["refRoam"] = rnd(100.0 * theirs, 1) if theirs is not None else None
        out["outLane"], out["refOut"] = out_share(rows), out_share(ref_rows)

        # Does it pay? Their own games, split at their own median, so "high"
        # means high for them rather than high for a support in general. Every
        # lane is shown, because a roam that wins mid can cost the lane it left.
        rated = [r for r in rows if r["roam"] is not None]
        if len(rated) >= 2 * LOW_GAMES:
            cut = sorted(r["roam"] for r in rated)[len(rated) // 2]
            high = [r for r in rated if r["roam"] >= cut and r["roam"] > 0]
            high_ids = {id(r) for r in high}
            low = [r for r in rated if id(r) not in high_ids]

            def col(pop):
                lanes = {}
                for lane in ROLES:
                    mates = [r if lane == role else self._teammate(r, lane) for r in pop]
                    lanes[lane] = rnd(mean(m["g15"] for m in mates if m), 0)
                return {"games": len(pop), "wr": pct_of(self._wins(pop), len(pop)), "lanes": lanes}
            if len(high) >= LOW_GAMES and len(low) >= LOW_GAMES:
                out["split"] = {"high": col(high), "low": col(low)}
        return out

    def _routes(self, rows):
        """The usual position at 1:00 to 4:00 for the two commonest starting
        camps, already turned to blue side."""
        by_start = defaultdict(list)
        for r in rows:
            jg = r.get("jg")
            if jg and jg["start"] in CAMP_NAME:
                by_start[jg["start"]].append(jg["path"])
        total = sum(len(v) for v in by_start.values())
        if total < 5:
            return []
        out = []
        def usual_spot(points):
            """Where most of them were, not the middle of where they all were.

            After the first camp a route forks: some go on to the next camp,
            some to the river, some to a lane. The average of those is a spot
            in the middle of the map that nobody stood on. The busiest
            1,000-unit square is somewhere people actually were.
            """
            cells = defaultdict(list)
            for x, y in points:
                cells[(x // 16, y // 16)].append((x, y))
            best = max(cells.values(), key=len)
            return [round(mean(p[0] for p in best)), round(mean(p[1] for p in best))]

        for start, paths in sorted(by_start.items(), key=lambda kv: -len(kv[1]))[:2]:
            pts = [usual_spot([p[i] for p in paths]) for i in range(4)]
            out.append({"start": start, "label": CAMP_NAME[start], "games": len(paths),
                        "share": round(100.0 * len(paths) / total), "pts": pts})
        return out

    def _jungle(self, rows):
        """One player's first clears."""
        js = [r for r in rows if r.get("jg")]
        if len(js) < 5:
            return None
        starts = defaultdict(list)
        for r in js:
            starts[r["jg"]["start"]].append(r)
        names = dict(CAMP_NAME, invade="Invade", elsewhere="Not at a camp")
        start_rows = [{"k": k, "label": names[k], "games": len(v), "share": round(100.0 * len(v) / len(js), 1),
                       "wr": pct_of(self._wins(v), len(v))}
                      for k, v in sorted(starts.items(), key=lambda kv: -len(kv[1]))]

        timed = [r for r in js if r["jg"]["clear"]]
        clear = None
        if len(timed) >= 5:
            kinds = defaultdict(list)
            for r in timed:
                kinds[r["jg"]["clear"]].append(r)
            everyone = [r for label in self.labels for r in self.friend_rows[label]
                        if r.get("jg") and r["jg"]["clear"] == "full"]
            ganks = kinds.get("gank", [])
            lanes = Counter(r["jg"]["gankLane"] for r in ganks if r["jg"]["gankLane"])
            clear = {
                "n": len(timed),
                "full": {"share": round(100.0 * len(kinds.get("full", [])) / len(timed), 1),
                         "time": rnd(mean(r["jg"]["l4"] for r in kinds.get("full", [])), 0),
                         "group": rnd(mean(r["jg"]["l4"] for r in everyone), 0),
                         "games": len(kinds.get("full", []))},
                "gank": {"share": round(100.0 * len(ganks) / len(timed), 1),
                         "time": rnd(mean(r["jg"]["l4"] for r in ganks), 0),
                         "ok": pct_of(sum(1 for r in ganks if r["jg"]["gankOk"]), len(ganks)),
                         "lane": lanes.most_common(1)[0][0] if lanes else None, "games": len(ganks)},
                "invade": {"share": round(100.0 * len(kinds.get("invade", [])) / len(timed), 1),
                           "games": len(kinds.get("invade", []))},
            }
        crabs = [r for r in js if r["jg"]["crab"] is not None]
        scuttle = None
        if len(crabs) >= 5:
            def bucket(n):
                pop = [r for r in crabs if min(int(r["jg"]["crab"]), 2) == n]
                return [round(100.0 * len(pop) / len(crabs), 1), pct_of(self._wins(pop), len(pop)), len(pop)]
            scuttle = {"n": len(crabs), "both": bucket(2), "one": bucket(1), "none": bucket(0)}
        champ = Counter(r["champ"] for r in js).most_common(1)[0][0]
        return {"games": len(js), "champ": champ, "routes": self._routes(js), "starts": start_rows,
                "clear": clear, "scuttle": scuttle}

    def _jungle_table(self):
        """Every friend who jungles, side by side."""
        out = []
        for label in self.labels:
            js = [r for r in self.friend_rows[label] if r["role"] == "JUNGLE" and r.get("jg")]
            if len(js) < 5:
                continue
            timed = [r for r in js if r["jg"]["clear"]]
            full = [r for r in timed if r["jg"]["clear"] == "full"]
            crabs = [r for r in js if r["jg"]["crab"] is not None]
            out.append({
                "label": label, "champ": Counter(r["champ"] for r in js).most_common(1)[0][0],
                "games": len(js), "wr": pct_of(self._wins(js), len(js)),
                "fullTime": rnd(mean(r["jg"]["l4"] for r in full), 0), "fullGames": len(full),
                "gank": pct_of(sum(1 for r in timed if r["jg"]["clear"] == "gank"), len(timed)),
                "both": pct_of(sum(1 for r in crabs if r["jg"]["crab"] >= 2), len(crabs)),
                "none": pct_of(sum(1 for r in crabs if r["jg"]["crab"] == 0), len(crabs)),
            })
        out.sort(key=lambda j: -j["games"])
        return out

    def _players(self):
        out = {}
        for f in self.friends:
            label = f["label"]
            mine = self.friend_rows[label]
            season = self.season[label]
            if not season and not mine:
                continue
            modes = Counter()
            mode_wins = Counter()
            positions = Counter()
            for m in season:
                queue = m.get("queue") or "Other"
                if queue == "Ranked Solo/Duo":
                    # Solo queue and duo queue are one queue to Riot. They are
                    # told apart by whether another tracked account was on the
                    # team, so a duo with someone the site does not follow
                    # counts as solo; the card says so.
                    side = self.season_games.get((m["matchId"], m.get("teamId")))
                    queue = "Ranked Duo" if side and len(side["friends"]) > 1 else "Ranked Solo"
                modes[queue] += 1
                mode_wins[queue] += 1 if m.get("win") else 0
                if m.get("position") in ROLES:
                    positions[m["position"]] += 1
            by_rank = defaultdict(lambda: [0, 0])
            for r in mine:
                if r["lobby"]:
                    c = by_rank[r["lobby"][0]]
                    c[0] += 1
                    c[1] += 1 if r["win"] else 0

            per_role = {}
            counts = Counter(r["role"] for r in mine if r["role"])
            # In map order, top to support, rather than by how much each is
            # played: the order is then the same for everyone and a support
            # main's Top games are always in the same place.
            for role in ROLES:
                n = counts.get(role, 0)
                if n < 3:
                    continue
                rows = [r for r in mine if r["role"] == role]
                tier = Counter(r["tier"] for r in rows if r["tier"] is not None).most_common(1)
                tier = tier[0][0] if tier else None
                ref_rows, ref_tier = self._ref_rows(role, tier)
                top_champ = Counter(r["champ"] for r in rows).most_common(1)[0][0]
                champ_rows = [r for r in rows if r["champ"] == top_champ]
                group = [r for r in self.group_rows if r["role"] == role]
                everyone = self._rows_at(role, None)
                axes = scoring.ROLE_METRICS[role]
                tiles = [{"k": s, "v": rnd(self.agg(rows, s), 4), "pc": rnd(self.agg_pc(rows, s), 0),
                          "ref": rnd(self.agg(ref_rows, s), 4)} for s in axes]
                lines = {}
                for t in self.tiers_with_baseline.get(role, []):
                    at = self._rows_at(role, t)
                    if len(at) >= TIER_LINE_MIN:
                        lines[str(t)] = [rnd(self.percentile(role, s, self.agg(at, s)), 0) for s in axes]
                wanted = list(axes) + [s for s in ROLE_TABLE[role] if s not in axes]
                compare = [{"k": s, "me": rnd(self.agg(rows, s), 4), "champ": rnd(self.agg(champ_rows, s), 4),
                            "group": rnd(self.agg(group, s), 4), "ref": rnd(self.agg(ref_rows, s), 4),
                            "all": rnd(self.agg(everyone, s), 4), "pc": rnd(self.agg_pc(rows, s), 0)}
                           for s in wanted]
                per_role[role] = {
                    "games": n, "wins": self._wins(rows), "tier": tier, "refTier": ref_tier,
                    "score": rnd(mean(r["score"] for r in rows), 1),
                    "tiles": tiles,
                    "radar": {"axes": axes, "me": [rnd(self.agg_pc(rows, s, "pa"), 0) for s in axes], "ranks": lines},
                    "heat": self._heat(rows),
                    "roam": self._roaming(rows, role, tier),
                    "jungle": self._jungle(rows) if role == "JUNGLE" else None,
                    "compare": {"champ": top_champ, "champGames": len(champ_rows), "rows": compare},
                }
            out[label] = {
                "games": len(season),
                # Which one to open on: the one they actually play.
                "main": counts.most_common(1)[0][0] if counts else None,
                "modes": [[q, n, mode_wins[q]] for q, n in modes.most_common()],
                "positions": [[r, n] for r, n in positions.most_common()],
                "byRank": [[t, v[0], v[1]] for t, v in sorted(by_rank.items())],
                "roles": per_role,
            }
        return out

    def _usual(self):
        """{label: {"Champ|ROLE": [games, [percentile per radar axis]]}}: what a
        normal game on that champion looks like, for "this game vs usual"."""
        groups = defaultdict(list)
        for r in self.group_rows:
            groups[(r["friend"], r["champ"], r["role"])].append(r)
        out = defaultdict(dict)
        for (label, champ, role), rows in groups.items():
            out[label][f"{champ}|{role}"] = [len(rows), [rnd(self.agg_pc(rows, s, "pa"), 0)
                                                        for s in scoring.ROLE_METRICS[role]]]
        return out

    # -- champions -------------------------------------------------------------

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

    def _gold_at(self, row, minute):
        g = self.games[row["game"]]["p"][row["pid"] - 1]["g"]
        return g[minute] if minute <= len(g) - 2 else None

    def _champions(self):
        by_key = defaultdict(list)
        for r in self.group_rows:
            by_key[(r["champ"], r["role"])].append(r)
        all_by_key = defaultdict(list)
        for role in ROLES:
            for r in self.role_rows[role]:
                all_by_key[(r["champ"], role)].append(r)

        out, index = {}, defaultdict(list)
        totals = defaultdict(lambda: [0, 0, Counter()])
        for (champ, role), rows in by_key.items():
            index[champ].append([role, len(rows)])
            t = totals[champ]
            t[0] += len(rows)
            t[1] += self._wins(rows)
            t[2].update(r["friend"] for r in rows)
            if len(rows) < 3:
                continue
            axes = scoring.ROLE_METRICS[role]
            everyone = all_by_key.get((champ, role), [])
            lobby = [r for r in everyone if not r["friend"]]

            per_friend = defaultdict(list)
            for r in rows:
                per_friend[r["friend"]].append(r)
            who = []
            for label, mine in sorted(per_friend.items(), key=lambda kv: -len(kv[1])):
                wins = self._wins(mine)
                who.append({"label": label, "games": len(mine), "wr": pct_of(wins, len(mine)),
                            "kda": rnd(self.agg(mine, "kda"), 1), "g15": rnd(self.agg(mine, "g15"), 0),
                            "score": self.pack_score(self.top_score(mine))})
            who.sort(key=lambda w: (-(w["score"]["score"] if w["score"] else -1), -w["games"]))
            order = sorted(who, key=lambda w: -w["games"])

            # Matchups: what the champion does against each opponent across
            # every stored game, then each friend beside it.
            cols = [w["label"] for w in order[:3]]
            overall = defaultdict(list)
            for r in everyone:
                if r["opp"]:
                    overall[r["opp"]].append(r)
            mine_by_opp = defaultdict(lambda: defaultdict(list))
            for r in rows:
                if r["opp"]:
                    mine_by_opp[r["opp"]][r["friend"]].append(r)
            matchups = []
            for opp, per in sorted(mine_by_opp.items(), key=lambda kv: -sum(len(v) for v in kv[1].values()))[:8]:
                pop = overall[opp]
                base = pct_of(self._wins(pop), len(pop))
                cells, best = {}, None
                for label in cols:
                    lst = per.get(label)
                    if not lst:
                        continue
                    wr = pct_of(self._wins(lst), len(lst))
                    cells[label] = [len(lst), wr, rnd(self.agg(lst, "g15"), 0)]
                    if len(lst) >= LOW_GAMES and base is not None:
                        gap = wr - base
                        if best is None or abs(gap) > abs(best[1]):
                            best = [label, round(gap)]
                matchups.append({"opp": opp, "all": [len(pop), base, rnd(self.agg(pop, "g15"), 0)],
                                 "per": cells, "best": best})

            top = order[0]["label"]
            top_rows = per_friend[top]
            lines = {}
            for t in self.tiers_with_baseline.get(role, []):
                at = [r for r in everyone if r["tier"] == t]
                if len(at) >= 20:
                    lines[str(t)] = [rnd(self.percentile(role, s, self.agg(at, s)), 0) for s in axes]

            by_rank = defaultdict(lambda: [0, 0, 0, 0])
            for r in everyone:
                if not r["lobby"]:
                    continue
                c = by_rank[r["lobby"][0]]
                if r["friend"]:
                    c[0] += 1
                    c[1] += 1 if r["win"] else 0
                else:
                    c[2] += 1
                    c[3] += 1 if r["win"] else 0

            # Gold against the usual for this champion in this role, minute
            # by minute, so three players' lines do not sit on top of each
            # other the way raw gold does.
            scoped = len(lobby) >= CALLOUT_GAMES
            base_rows = lobby if scoped else self._rows_at(role, None)
            usual = []
            for m in range(0, 26):
                vals = [v for v in (self._gold_at(r, m) for r in base_rows) if v is not None]
                usual.append(sum(vals) / len(vals) if len(vals) >= 10 else None)
            gold_players = []
            for w in order[:3]:
                mine = per_friend[w["label"]]
                if len(mine) < 3:
                    continue
                ys = []
                for m in range(0, 26):
                    vals = [v for v in (self._gold_at(r, m) for r in mine) if v is not None]
                    ys.append(round(sum(vals) / len(vals) - usual[m])
                              if len(vals) >= 2 and usual[m] is not None else None)
                gold_players.append({"label": w["label"], "y": ys})

            builds, skill = self._builds(rows)
            wins = self._wins(rows)
            out[f"{champ}|{role}"] = {
                "champ": champ, "role": role, "games": len(rows), "wr": pct_of(wins, len(rows)),
                "lobby": {"n": len(lobby), "wr": pct_of(self._wins(lobby), len(lobby)) if lobby else None},
                "scoped": scoped, "g15": rnd(self.agg(rows, "g15"), 0),
                "who": who, "cols": cols, "matchups": matchups,
                "radar": {"axes": axes, "who": top, "games": len(top_rows),
                          "me": [rnd(self.agg_pc(top_rows, s, "pa"), 0) for s in axes], "ranks": lines},
                "byRank": [[t, v[0], pct_of(v[1], v[0]), v[2], pct_of(v[3], v[2])]
                           for t, v in sorted(by_rank.items()) if v[0]],
                "gold": gold_players,
                "builds": builds, "skill": skill,
                "clear": self._routes(top_rows) if role == "JUNGLE" else None,
            }
        listing = []
        for c, roles in index.items():
            t = totals[c]
            listing.append({"champ": c, "roles": sorted(roles, key=lambda x: -x[1]), "games": t[0],
                            "wr": pct_of(t[1], t[0]), "most": t[2].most_common(1)[0][0]})
        listing.sort(key=lambda x: -x["games"])
        return {"list": listing, "detail": out}
