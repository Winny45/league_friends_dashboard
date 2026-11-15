"""Roles and classes, Time patterns, Duos and stacks, Game flow, Records.

Methods of Analysis; see analysis_views.py for why they live apart from it.
"""

from collections import Counter, defaultdict

from analysis_util import (LANE_ZONE, LANING_END, ROLE_TABLE, ROLES, STATS, mean, monster_letter,
                           pct_of, rnd, uk_time, zone_of)
from analysis_views import BLANK_GAMES, CALLOUT_GAMES, LOW_GAMES
from champion_classes import CLASSES

SESSION_GAP_MS = 60 * 60 * 1000     # a new session starts after an hour with no game
SESSION_BUCKETS = 20                # game 1 .. game 19, then 20 and beyond
DAY_STARTS = 5                      # 5am: the hour a night's games stop belonging to the day before
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _day_label(ms):
    return uk_time(ms).strftime("%a %d %b").replace(" 0", " ")


class GroupViews:

    # -- roles and classes -----------------------------------------------------

    def _role_view(self, role, cls=None):
        def keep(r):
            return r["role"] == role and (cls is None or r["cls"] == cls)
        cols = ROLE_TABLE[role] + ["kda"]
        lobby = [r for r in self.lobby_rows[role] if cls is None or r["cls"] == cls]
        # What a cell is coloured against. With a class picked it is the
        # lobby's players of that class, so an enchanter is not marked down
        # for healing less than... nobody, and more than every tank.
        base = {s: sorted(r[s] for r in lobby if r.get(s) is not None) for s in cols}

        def line(pop, coloured):
            vals = {}
            for s in cols:
                pc = None
                if coloured:
                    pc = mean(self.pct_in(base[s], r.get(s), STATS[s][2]) for r in pop)
                vals[s] = [rnd(self.agg(pop, s), 4), rnd(pc, 0)]
            wins = self._wins(pop)
            return {"games": len(pop), "wr": pct_of(wins, len(pop)), "vals": vals}

        rows = []
        for label in self.labels:
            mine = [r for r in self.friend_rows[label] if keep(r)]
            if mine:
                rows.append(dict(line(mine, True), label=label))
        rows.sort(key=lambda r: -r["games"])
        group = [r for r in self.group_rows if keep(r)]
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
        group = self.group_rows

        def wr(pop):
            return pct_of(self._wins(pop), len(pop))

        ench = [r for r in group if r["role"] == "UTILITY" and r["cls"] == "Enchanter"]
        ench_l = [r for r in self.lobby_rows["UTILITY"] if r["cls"] == "Enchanter"]
        if len(ench) >= CALLOUT_GAMES and len(ench_l) >= CALLOUT_GAMES:
            a, b = self.agg(ench, "hs"), self.agg(ench_l, "hs")
            if a and b:
                d = round(100.0 * (a - b) / b)
                notes.append(["✨", f"Enchanter supports average {abs(d)}% {'more' if d >= 0 else 'less'} "
                                    f"heal + shield than lobby enchanters ({len(ench)} games)"])
        ass = [r for r in group if r["role"] == "MIDDLE" and r["cls"] == "Assassin"]
        if len(ass) >= CALLOUT_GAMES:
            ahead = [r for r in ass if (self.sides[(r["game"], r["team"])]["lead15"] or 0) >= 2000]
            g15 = self.agg(ass, "g15")
            msg = f"Assassins in mid: {wr(ass)}% winrate over {len(ass)} games"
            if g15 is not None:
                msg += f", gold diff @15 {g15:+.0f}"
            if len(ahead) >= LOW_GAMES:
                lost = sum(1 for r in ahead if not r["win"])
                msg += f", and {round(100.0 * lost / len(ahead))}% of 2k+ team leads at 15 still lost"
            notes.append(["🗡️", msg])
        adc = [r for r in group if r["role"] == "BOTTOM" and r["cls"] == "Marksman"]
        with_w, without = [], []
        for r in adc:
            sup = self._teammate(r, "UTILITY")
            if sup:
                (with_w if sup["cls"] == "Warden" else without).append(r)
        if len(with_w) >= CALLOUT_GAMES and len(without) >= CALLOUT_GAMES:
            d = self.agg(without, "deaths") - self.agg(with_w, "deaths")
            notes.append(["🎯", f"Marksmen die {abs(d):.1f} {'fewer' if d >= 0 else 'more'} times a game "
                                f"with a Warden support ({len(with_w)} games)"])
        van = [r for r in group if r["cls"] == "Vanguard"]
        if len(van) >= CALLOUT_GAMES:
            first = [r for r in van if self.objectives.get(r["game"])
                     and self.objectives[r["game"]][0]["team"] == r["team"]]
            if len(first) >= CALLOUT_GAMES:
                notes.append(["🛡️", f"Group Vanguards win {wr(first)}% when their team takes the first "
                                    f"objective ({len(first)} games), {wr(van)}% overall"])
        best = None
        for cls in CLASSES:
            mine = [r for r in group if r["cls"] == cls and r["score"] is not None]
            if len(mine) >= CALLOUT_GAMES:
                a = mean(r["score"] for r in mine)
                if best is None or a > best[0]:
                    best = (a, cls, len(mine))
        if best:
            notes.append(["📈", f"{best[1]}s are what this group plays best for its rank: an average "
                                f"game score of {best[0]:.0f} over {best[2]} games"])
        return notes

    def _roles(self):
        views = {}
        for role in ROLES:
            classes = Counter(r["cls"] for r in self.group_rows if r["role"] == role)
            per = {"All": self._role_view(role)}
            for cls, n in classes.most_common():
                if n >= BLANK_GAMES:
                    per[cls] = self._role_view(role, cls)
            views[role] = {"cols": ROLE_TABLE[role], "views": per,
                           "classes": [[c, n] for c, n in classes.most_common() if n >= BLANK_GAMES]}
        obj = [{"role": role,
                "group": rnd(self.agg([r for r in self.group_rows if r["role"] == role], "objp"), 3),
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
        if hour < DAY_STARTS:
            day = (day - 1) % 7
        return day, hour

    @staticmethod
    def _hour_label(h):
        return f"{(h % 12) or 12}{'am' if h < 12 else 'pm'}"

    def _time_view(self, entries):
        """entries: (start ms, won, team lead at 15 or None)."""
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
        order = list(range(DAY_STARTS, 24)) + list(range(0, DAY_STARTS))   # a day, in the order it happens

        def window(day_set, start_idx):
            g = w = 0
            for d in day_set:
                for h in order[start_idx:start_idx + 3]:
                    g += cells[d][h][0]
                    w += cells[d][h][1]
            return g, w

        # A best or worst slot needs thirty games behind it, the same floor
        # as every other "best" on the site. One player's thirteen games in a
        # slot is a good evening, not a pattern.
        candidates = []
        for i in range(len(order) - 2):
            span = f"{self._hour_label(order[i])}–{self._hour_label((order[i + 2] + 1) % 24)}"
            g, w = window(range(7), i)
            if g >= CALLOUT_GAMES:
                candidates.append((w / g, g, "Any day " + span))
            for d in range(7):
                g, w = window([d], i)
                if g >= CALLOUT_GAMES:
                    candidates.append((w / g, g, f"{DAYS[d]} {span}"))
        tiles = {}
        if len(candidates) >= 2:
            best, worst = max(candidates), min(candidates)
            tiles["best"] = {"label": best[2], "wr": round(100 * best[0], 1), "games": best[1]}
            tiles["worst"] = {"label": worst[2], "wr": round(100 * worst[0], 1), "games": worst[1]}
        busiest = max(((cells[d][h][0], d, h) for d in range(7) for h in range(24)), default=None)
        if busiest and busiest[0]:
            tiles["busiest"] = {"label": f"{DAYS[busiest[1]]} {self._hour_label(busiest[2])}",
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
        the next one. A sitting ends when an hour passes with no game.

        Each bucket is [games, wins, lane gold diff @15 summed, games that had
        one, deaths summed].
        """
        by_number = [[0, 0, 0.0, 0, 0] for _ in range(SESSION_BUCKETS)]
        after = {"win": [0, 0], "l1": [0, 0], "l2": [0, 0], "l3": [0, 0]}
        per_label, reached = {}, {}
        for f in self.friends:
            if f["label"] not in labels:
                continue
            mine = [[0, 0] for _ in range(7)]
            lengths = []
            games = sorted(self.season[f["label"]], key=lambda m: m.get("gameStartMs") or 0)
            prev_end, number, streak = None, 0, 0
            for m in games:
                t0 = m.get("gameStartMs") or 0
                if prev_end is None or t0 - prev_end > SESSION_GAP_MS:
                    if number:
                        lengths.append(number)
                    number, streak = 0, None
                number += 1
                win = bool(m.get("win"))
                row = self.row_of.get((f["label"], m["matchId"]))
                bucket = by_number[min(number, SESSION_BUCKETS) - 1]
                bucket[0] += 1
                bucket[1] += 1 if win else 0
                bucket[4] += m.get("deaths", 0)
                if row and row["g15"] is not None:
                    bucket[2] += row["g15"]
                    bucket[3] += 1
                idx = min(number, 7) - 1
                mine[idx][0] += 1
                mine[idx][1] += 1 if win else 0
                if streak is not None:
                    key = "win" if streak == 0 else "l1" if streak == 1 else "l2" if streak == 2 else "l3"
                    after[key][0] += 1
                    after[key][1] += 1 if win else 0
                streak = 0 if win else (streak or 0) + 1
                prev_end = t0 + int((m.get("durationMin") or 0) * 60_000)
            if number:
                lengths.append(number)
            per_label[f["label"]] = mine
            reached[f["label"]] = sum(1 for n in lengths if n >= 5)
        return by_number, after, per_label, reached

    def _time(self):
        def entries(pred):
            return [(s["t0"], s["win"], (self.sides.get((s["id"], s["team"])) or {}).get("lead15"))
                    for s in self.season_games.values() if pred(s)]
        views = {"All": self._time_view(entries(lambda s: True))}
        for label in self.labels:
            views[label] = self._time_view(
                entries(lambda s, label=label: any(f["label"] == label for f in s["friends"])))

        def pack(by_number, after):
            return {"byNumber": [[b[0], b[1], (round(b[2] / b[3]) if b[3] >= 8 else None),
                                  (round(b[4] / b[0], 1) if b[0] else None)] for b in by_number],
                    "after": after}
        by_number, after, per_label, reached = self._sessions(set(self.labels))
        sessions = {"All": pack(by_number, after)}
        for label in self.labels:
            bn, af, _pl, _r = self._sessions({label})
            sessions[label] = pack(bn, af)

        # Who fades. One rule for everybody: ten sittings that got as far as
        # a fifth game, or no line at all. A line through three or four thin
        # points says "+37 by game 7" about somebody who has played eight
        # such games, and leaves out somebody else for the same reason
        # without saying so.
        fade, hidden = [], []
        for label in self.labels:
            buckets = per_label.get(label, [])
            if reached.get(label, 0) < LOW_GAMES:
                if sum(b[0] for b in buckets):
                    hidden.append([label, reached.get(label, 0)])
                continue
            pts = [(i, 100.0 * b[1] / b[0], b[0]) for i, b in enumerate(buckets) if b[0] >= LOW_GAMES]
            # Weighted least squares through winrate against game number, so
            # one unlucky seventh game cannot draw the line by itself.
            sw = sum(p[2] for p in pts)
            mx = sum(p[0] * p[2] for p in pts) / sw
            my = sum(p[1] * p[2] for p in pts) / sw
            var = sum(p[2] * (p[0] - mx) ** 2 for p in pts)
            slope = sum(p[2] * (p[0] - mx) * (p[1] - my) for p in pts) / var if var else 0.0
            fade.append({"label": label, "delta": round(slope * 6), "sessions": reached[label],
                         "pts": [(round(100.0 * b[1] / b[0], 1) if b[0] >= LOW_GAMES else None) for b in buckets]})
        steadiest = min(fade, key=lambda f: abs(f["delta"]))["label"] if fade else None
        return {"views": views, "sessions": sessions, "fade": fade, "fadeHidden": hidden,
                "steadiest": steadiest, "dayStarts": DAY_STARTS}

    # -- duos and stacks -------------------------------------------------------

    def _partners(self):
        """A friend's champion with each teammate's champion, friend or not.

        For each friend's most played champions, every other role on their
        team: who was in it, how often, and how the game went against how
        that friend's champion usually goes.
        """
        out = {}
        for label in self.labels:
            rows = [r for r in self.friend_rows[label] if r["role"]]
            picks = Counter((r["champ"], r["role"]) for r in rows)
            entries = []
            for (champ, role), n in picks.most_common(4):
                if n < 15:
                    continue
                mine = [r for r in rows if r["champ"] == champ and r["role"] == role]
                usual = pct_of(self._wins(mine), len(mine))
                bot = role in ("BOTTOM", "UTILITY")
                per_role = {}
                for other in ROLES:
                    if other == role:
                        continue
                    groups, classes = defaultdict(list), defaultdict(list)
                    for r in mine:
                        mate = self._teammate(r, other)
                        if mate:
                            groups[(mate["champ"], mate["friend"])].append(r)
                            classes[mate["cls"]].append(r)
                    lane = bot and other in ("BOTTOM", "UTILITY")
                    partners = []
                    for (c, by), lst in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:12]:
                        if len(lst) < 3:
                            continue
                        wr = pct_of(self._wins(lst), len(lst))
                        partners.append([c, by, len(lst), wr, round(wr - usual, 1),
                                         rnd(mean(r["botg15"] for r in lst), 0) if lane else None])
                    by_class = [[cls, len(lst), pct_of(self._wins(lst), len(lst))]
                                for cls, lst in sorted(classes.items(), key=lambda kv: -len(kv[1]))
                                if len(lst) >= BLANK_GAMES]
                    if partners:
                        per_role[other] = {"partners": partners, "classes": by_class[:6]}
                if per_role:
                    entries.append({"champ": champ, "role": role, "games": n, "wr": usual, "with": per_role})
            if entries:
                out[label] = entries
        return out

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
        # Why a stack size can be empty. A "four" is four tracked accounts,
        # and when the same untracked player is the fifth in most of them it
        # is really a five with somebody the site does not follow.
        fours = [s for s in self.sides.values() if len(s["friends"]) == 4]
        fifth = Counter()
        for s in fours:
            for r in self.by_game[s["id"]]:
                if r["team"] == s["team"] and not r["friend"]:
                    fifth[r["name"]] += 1
        stack_note = {"fours": len(fours), "sameFifth": fifth.most_common(1)[0][1] if fifth else 0,
                      "trios": stacks["All"][2][0]}

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
                ra = self.row_of.get((adc["label"], s["id"]))
                if ra and ra["botg15"] is not None:
                    b["lane"].append(ra["botg15"])

        cp = []
        for (la, ca, lb, cb), (g, w) in champ_pairs.items():
            if g < BLANK_GAMES:
                continue
            usual = mean([rate(on_champ[(la, ca)]), rate(on_champ[(lb, cb)])])
            wr = 100.0 * w / g
            cp.append({"a": [la, ca], "b": [lb, cb], "games": g, "wr": round(wr, 1),
                       "vs": rnd(wr - usual, 1) if usual is not None else None})
        cp.sort(key=lambda p: -p["games"])
        # The lane figure for a pair, beside what that ADC's lane usually
        # does, so "-600 at 15" can be told apart from "plays a late champion
        # and is always -600 at 15".
        adc_usual = {}
        for label in self.labels:
            vals = [r["botg15"] for r in self.friend_rows[label] if r["role"] == "BOTTOM" and r["botg15"] is not None]
            if len(vals) >= LOW_GAMES:
                adc_usual[label] = round(mean(vals))
        bl = [{"adc": [k[0], k[1]], "sup": [k[2], k[3]], "games": v["g"], "wr": pct_of(v["w"], v["g"]),
               "lane": rnd(mean(v["lane"]), 0), "laneGames": len(v["lane"]), "usual": adc_usual.get(k[0])}
              for k, v in bot.items() if v["g"] >= 3]
        bl.sort(key=lambda p: -p["games"])
        everyone = [r["botg15"] for r in self.role_rows["BOTTOM"] if r["botg15"] is not None]
        return {
            "matrix": matrix, "queues": ["All"] + queues, "stacks": stacks, "stackNote": stack_note,
            "rolePairs": {f"{a}|{b}": [pct_of(v[1], v[0]), v[0]] for (a, b), v in role_pairs.items()},
            "champPairs": cp[:14], "botPairs": bl[:10],
            "botCheck": {"all": round(mean(everyone)) if everyone else None, "n": len(everyone)},
            "partners": self._partners(),
        }

    # -- game flow -------------------------------------------------------------

    def _turning_point(self, side, after_minute, team):
        """The first baron the given team took after a minute, if any."""
        for o in self.objectives.get(side["id"], []):
            if o["code"] == "BARON_NASHOR" and o["team"] == team and o["t"] > after_minute * 60:
                return {"t": o["t"], "stolen": o["stolen"]}
        return None

    def _flow_story(self, side, comeback):
        rows = [r for r in self.by_game[side["id"]] if r["team"] == side["team"] and r["friend"]]
        extreme = side["lo"] if comeback else side["hi"]
        team = side["team"] if comeback else 300 - side["team"]
        scalers = sorted(side["champs"], key=lambda c: -self.scaling.get(c, 0.0))[:2]
        return {
            "id": side["id"], "team": side["team"], "t0": side["t0"], "dur": side["dur"], "lead": side["lead"],
            "friends": [[r["friend"], r["champ"]] for r in rows],
            "from": side["min"] if comeback else side["max"],
            "chance": {"p": round(100 * extreme[0]), "minute": extreme[1]} if extreme else None,
            "baron": self._turning_point(side, extreme[1], team) if extreme else None,
            "scalers": scalers if side["gap"] > 0 else [],
            "objs": [[o["t"], monster_letter(o["code"]), 1 if o["team"] == side["team"] else 0,
                      1 if o["stolen"] else 0, o["code"]] for o in self.objectives.get(side["id"], [])],
        }

    def _flow(self):
        mine = [s for s in self.sides.values() if s["friends"]]
        with15 = [s for s in mine if s["lead15"] is not None]
        everyone15 = [s for s in self.sides.values() if s["lead15"] is not None]
        comebacks = [s for s in mine if s["comeback"]]
        throws = [s for s in mine if s["throw"]]
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
            if len(p15) < BLANK_GAMES:
                continue
            up = [s for s in p15 if s["lead15"] >= 2000]
            expected = sum(self.win_chance(s["lead15"], 15, s["gap"]) or 0.5 for s in p15)
            players.append({
                "label": label, "games": len(p15), "ahead": len(up),
                "conv": wr(up) if len(up) >= BLANK_GAMES else None,
                "throws": sum(1 for s in ps if s["throw"]),
                "comebacks": sum(1 for s in ps if s["comeback"]),
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
            if len(vals) >= LOW_GAMES:
                role = Counter(r["role"] for r in led).most_common(1)[0][0]
                spill.append({"label": label, "role": role, "v": round(mean(vals)), "games": len(vals)})
        spill.sort(key=lambda s: -s["v"])
        base_vals = [v for v in (others(r) for r in self.rows
                                 if r["g15"] is not None and r["g15"] >= 1000) if v is not None]

        big_c = min(comebacks, key=lambda s: s["lo"][0]) if comebacks else None
        big_t = max(throws, key=lambda s: s["hi"][0]) if throws else None
        b2 = self.slopes2.get(15) or (None, None)
        b2_20 = self.slopes2.get(20) or (None, None)
        known = [(s, c) for c, s in self.scaling.items() if self.scaling_games.get(c, 0) >= CALLOUT_GAMES]
        known.sort()
        return {
            "tiles": {"comebacks": len(comebacks), "throws": len(throws),
                      "conv": wr(ahead), "convN": len(ahead), "convLobby": wr(ahead_all),
                      "ahead15": pct_of(sum(1 for s in with15 if s["lead15"] > 0), len(with15)),
                      "games": len(with15), "modelGames": self.model_games},
            "curve": {"b15": rnd(self.slopes.get(15), 4), "b20": rnd(self.slopes.get(20), 4),
                      "se15": rnd(self.slope_se.get(15), 4), "dots": buckets(15),
                      "s15": [rnd(b2[0], 4), rnd(b2[1], 4)], "s20": [rnd(b2_20[0], 4), rnd(b2_20[1], 4)],
                      "gap": round(self.gap_typical, 4)},
            "slopes": {str(m): round(b, 4) for m, b in self.slopes.items()},
            "slopes2": {str(m): [round(b, 4), round(d, 4)] for m, (b, d) in self.slopes2.items()},
            "late": [[c, round(100 * s, 1), self.scaling_games[c]] for s, c in known[-6:][::-1]],
            "early": [[c, round(100 * s, 1), self.scaling_games[c]] for s, c in known[:6]],
            "players": players, "spill": spill,
            "spillBase": round(mean(base_vals)) if base_vals else None,
            "comeback": self._flow_story(big_c, True) if big_c else None,
            "throw": self._flow_story(big_t, False) if big_t else None,
        }

    # -- records ---------------------------------------------------------------

    def _records(self):
        """Game records: the superlatives that need the minute-by-minute data.

        Each is {icon, title, text, who, game?, how?}. `text` is HTML built
        here from numbers and from labels this site chose, never from a
        Riot ID. A record that names a best or worst needs thirty games
        behind it, like every other on the site.
        """
        out = []

        def add(icon, title, text, who=None, game=None, how=None):
            out.append({"icon": icon, "title": title, "text": text, "who": who, "game": game, "how": how})

        def b(v):
            return f"<b>{v}</b>"

        def gold(v):
            a = abs(v)
            s = f"{a / 1000:.1f}k" if a >= 1000 else str(round(a))
            return ("+" if v > 0 else "−" if v < 0 else "") + s

        def mmss(t):
            return f"{int(t) // 60}:{int(t) % 60:02d}"

        mine = [s for s in self.sides.values() if s["friends"]]
        name = self.champ_name

        def side_who(s):
            rows = [r for r in self.by_game[s["id"]] if r["team"] == s["team"] and r["friend"]]
            return rows[0]["friend"], ", ".join(f"{r['friend']} ({name(r['champ'])})" for r in rows)

        comebacks = [s for s in mine if s["comeback"]]
        throws = [s for s in mine if s["throw"]]
        if comebacks:
            s = min(comebacks, key=lambda s: s["lo"][0])
            who, names = side_who(s)
            add("🔄", "Biggest comeback",
                f"{names} won from {b(gold(s['min']))} gold on {_day_label(s['t0'])}. "
                f"Lowest win chance: {round(100 * s['lo'][0])}%.", who, [s["id"], s["team"]])
        if throws:
            s = max(throws, key=lambda s: s["hi"][0])
            who, names = side_who(s)
            add("🫠", "Biggest throw",
                f"{names} lost from {b(gold(s['max']))} on {_day_label(s['t0'])}. "
                f"Highest win chance: {round(100 * s['hi'][0])}%.", who, [s["id"], s["team"]])

        def table(pairs, unit=""):
            """A small ranked list for 'how this was worked out'."""
            return [[label, value, games] for value, label, games in pairs] + ([unit] if unit else [])

        steals = Counter()
        barons = Counter()
        robbed = Counter()
        for label in self.labels:
            for r in self.friend_rows[label]:
                steals[label] += r["stolen"]
                robbed[label] += sum(x["stolen"] for x in self.by_game[r["game"]] if x["team"] != r["team"])
                if r["stolen"]:
                    barons[label] += sum(1 for o in self.objectives.get(r["game"], [])
                                         if o["stolen"] and o["killer"] == r["pid"] and o["code"] == "BARON_NASHOR")
        if steals and max(steals.values()) > 0:
            label, n = steals.most_common(1)[0]
            extra = f", including {barons[label]} Baron{'s' if barons[label] != 1 else ''}" if barons[label] else ""
            add("🦹", "Thief", f"{label} has stolen {b(n)} objective{'s' if n != 1 else ''} this season{extra}.", label,
                how=[[l, v, len(self.friend_rows[l])] for l, v in steals.most_common() if v])
        if robbed and max(robbed.values()) > 0:
            label, n = robbed.most_common(1)[0]
            add("😭", "Robbed", f"{label}'s teams have had {b(n)} objectives stolen from them.", label,
                how=[[l, v, len(self.friend_rows[l])] for l, v in robbed.most_common() if v])

        hogs = []
        for label in self.labels:
            rows = [r for r in self.friend_rows[label] if r["role"]]
            v = self.agg(rows, "objp")
            if len(rows) >= CALLOUT_GAMES and v is not None:
                hogs.append((round(100 * v), label, len(rows)))
        if hogs:
            hogs.sort(reverse=True)
            v, label, n = hogs[0]
            add("🐉", "Objective hog",
                f"{label} took part in {b(str(v) + '%')} of their team's dragons, grubs, heralds and Barons.", label,
                how=[[l, f"{x}%", g] for x, l, g in hogs])
        most = max(((len([o for o in self.objectives.get(s["id"], []) if o["team"] == s["team"]]), s)
                    for s in mine), key=lambda t: t[0], default=None)
        if most and most[0]:
            who, names = side_who(most[1])
            add("🏹", "Clean sweep", f"{names}: {b(most[0])} objectives in one game, on {_day_label(most[1]['t0'])}.",
                who, [most[1]["id"], most[1]["team"]])

        first = None
        for label in self.labels:
            for r in self.friend_rows[label]:
                p = self.games[r["game"]]["p"][r["pid"] - 1]
                for item, t in zip(p.get("buy", []), p.get("bt", [])):
                    if self._completed(item):
                        if first is None or t < first[0]:
                            first = (t, r, item)
                        break
        if first:
            t, r, item = first
            item_name = (self.items.get(str(item)) or {}).get("name", "their first item")
            add("⚡", "Fastest first item",
                f"{r['friend']} finished {item_name} on {name(r['champ'])} at {b(mmss(t))} on {_day_label(r['t0'])}.",
                r["friend"], [r["game"], r["team"]])

        roamers = []
        for label in self.labels:
            laners = [r for r in self.friend_rows[label] if LANE_ZONE.get(r["role"])]
            if len(laners) >= CALLOUT_GAMES and sum(r["tk_n"] for r in laners) >= 50:
                role = Counter(r["role"] for r in laners).most_common(1)[0][0]
                roamers.append((round(100 * self.agg(laners, "roam")), label, len(laners), LANE_ZONE[role]))
        if roamers:
            roamers.sort(reverse=True)
            v, label, n, lane = roamers[0]
            add("🧭", "Roam king", f"{label} gets {b(str(v) + '%')} of laning-phase takedowns away from {lane} lane.",
                label, how=[[l, f"{x}%", g] for x, l, g, _ in roamers])

        far = None
        opposite = {"top": "bot", "bot": "top"}
        for label in self.labels:
            for r in self.friend_rows[label]:
                want = opposite.get(LANE_ZONE.get(r["role"]))
                if not want:
                    continue
                for ev in self.games[r["game"]].get("kills", []):
                    if ev[0] >= LANING_END:
                        break
                    if ev[0] < 180:
                        continue        # a level-one brawl is not a roam
                    if r["pid"] in [ev[3]] + ev[5:] and zone_of(ev[1], ev[2], r["team"]) == want:
                        if far is None or ev[0] < far[0]:
                            far = (ev[0], r, want, "kill" if ev[3] == r["pid"] else "assist")
                        break
        if far:
            t, r, lane, kind = far
            article = "an" if kind == "assist" else "a"
            add("🏃", "Furthest roam",
                f"{r['friend']} got {article} {kind} in {b(lane + ' lane at ' + mmss(t))} as {name(r['champ'])}.",
                r["friend"], [r["game"], r["team"]])

        late = [s for s in self.season_games.values() if 1 <= uk_time(s["t0"]).hour < 5]
        if len(late) >= CALLOUT_GAMES:
            wr = round(100.0 * sum(1 for s in late if s["win"]) / len(late))
            add("🌙", "Night owl",
                f"Group winrate after 1am: {b(str(wr) + '%')} over {len(late)} games." + (" Go to bed." if wr < 48 else ""))

        tilt = []
        for label in self.labels:
            games = sorted(self.season[label], key=lambda m: m.get("gameStartMs") or 0)
            prev_end, streak, n, w = None, 0, 0, 0
            for m in games:
                t0 = m.get("gameStartMs") or 0
                if prev_end is None or t0 - prev_end > SESSION_GAP_MS:
                    streak = 0
                if streak >= 2:
                    n += 1
                    w += 1 if m.get("win") else 0
                streak = 0 if m.get("win") else streak + 1
                prev_end = t0 + int((m.get("durationMin") or 0) * 60_000)
            if n >= CALLOUT_GAMES:
                tilt.append((round(100.0 * w / n), label, n))
        if tilt:
            tilt.sort(reverse=True)
            v, label, n = tilt[0]
            add("🔥", "Tilt-proof", f"{label} wins {b(str(v) + '%')} of games after losing two in a row.", label,
                how=[[l, f"{x}%", g] for x, l, g in tilt])

        cb = Counter(f for s in comebacks for f in s["friends"])
        th = Counter(f for s in throws for f in s["friends"])
        played = Counter(f for s in mine for f in s["friends"])
        if cb:
            label, n = cb.most_common(1)[0]
            add("📈", "Comeback specialist", f"{label} has {b(n)} comebacks from 5k+ behind, the most in the group.",
                label, how=[[l, v, played[l]] for l, v in cb.most_common()])
        if th:
            label, n = th.most_common(1)[0]
            add("💸", "Gold leak", f"{label}'s teams lost {b(n)} games after being 5k+ ahead.", label,
                how=[[l, v, played[l]] for l, v in th.most_common()])

        pentas = Counter()
        for label in self.labels:
            pentas[label] = sum(r["penta"] for r in self.friend_rows[label])
        if pentas and max(pentas.values()) > 0:
            label, n = pentas.most_common(1)[0]
            add("🖐️", "Pentakill", f"{label} has {b(n)} pentakill{'s' if n != 1 else ''} this season.", label,
                how=[[l, v, len(self.friend_rows[l])] for l, v in pentas.most_common() if v])
        return {"season": self.highlights, "game": out}
