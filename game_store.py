"""The per-game store: everything about a match that is not about one friend.

fetch_data.py keeps one small row per friend per match, which is all the
original dashboard needed. The analysis pages need the other nine players as
well (a support's vision score means nothing without the other supports to
hold it against) and they need what happened *during* the game, which only
the timeline endpoint has: gold by minute, where people stood, who took which
dragon.

A raw match is about 80 KB and a raw timeline about 750 KB. Kept whole, one
season for this group would be three gigabytes, so each game is reduced on
arrival to roughly 9 KB of the fields something actually reads, and the raw
responses are thrown away.

Layout on disk
    games/2026-11.json      {"v": 1, "games": {matchId: record}}
    games/_skip.json        {matchId: reason}   ids not worth asking for again

One shard per calendar month (UTC, by game start) rather than one file,
because the store lives on a branch that is rewritten every run: a month that
has finished never changes again, so its blob is never uploaded twice.

Record shape (see reduce_game for the authority)
    id, q, t0, dur, patch, win, remake, pv
    p[10]   one per participant, in participantId order
    kills   [t, x, y, killer, victim, assist...]
    mon     [t, code, killer, team, assist...]
    bld     [t, losingTeam, code, lane]
    rk      [[solo, flex] x 10], each 0 (unranked) or [tier, division, lp];
            None for a player whose lookup failed. rkt is when it was read.
Times are whole seconds from game start. Positions are map units // 64, which
keeps every coordinate under 256 and is finer than anything drawn from them.

"pv" is the version of the record itself. A record is whatever reduce_game
kept on the day the game was fetched, and the raw responses are gone, so a
field added later can only reach an old game by asking Riot for it again.
upgrade() does that, within the same kind of time budget as everything else.

Ranks are the one thing here that is not a fact about the game. Riot only
ever says what somebody's rank is now, so "rank at the time" means "rank when
this game was collected", which for a game picked up within the hour is close
enough. Games stored before ranks were kept get today's rank, once, and are
never refreshed: a number that kept moving would rescore the whole season
every time somebody was promoted.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

STORE_VERSION = 1
RECORD_VERSION = 2
STORE_DIR = Path("games")
SKIP_FILE = "_skip.json"
RANK_FILE = "_ranks.json"
POS_SCALE = 64

TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND",
         "MASTER", "GRANDMASTER", "CHALLENGER"]
_DIVISION = {"I": 1, "II": 2, "III": 3, "IV": 4}
# A rank read this recently is reused for a game that has just been played.
# Long enough that a duo partner met five times in an evening is asked about
# once, short enough to still be "the rank they played at".
RANK_FRESH_SECONDS = 12 * 3600
# A game older than this gets whatever rank is on file, however old. It is a
# stand-in either way; see the module docstring.
RANK_LIVE_WINDOW_MS = 48 * 3600 * 1000

# Bought constantly and say nothing about a build: potions, wards, trinkets,
# elixirs. Dropped on arrival so the purchase list is the build and not noise.
_NOT_A_BUILD_ITEM = {
    2003, 2010, 2031, 2033, 2055, 2138, 2139, 2140, 2150, 2151, 2152,
    3340, 3363, 3364, 3330, 2052, 2403, 2419, 2420, 2421, 2422, 2423, 2424,
}

_SKILL_LETTER = {1: "Q", 2: "W", 3: "E", 4: "R"}


def _q(v):
    """A map coordinate, quantised."""
    return max(0, min(255, int(v) // POS_SCALE))


def reduce_game(match, timeline):
    """One compact record from a match-v5 response and its timeline.

    Returns None for anything that is not an ordinary ten-player Summoner's
    Rift game, so the caller can note it as skipped.
    """
    info = (match or {}).get("info") or {}
    parts = sorted(info.get("participants") or [], key=lambda p: p.get("participantId", 0))
    if info.get("mapId") != 11 or len(parts) != 10:
        return None
    frames = ((timeline or {}).get("info") or {}).get("frames") or []
    if not frames:
        return None

    win_team = next((t.get("teamId") for t in info.get("teams") or [] if t.get("win")), None)
    remake = any(p.get("gameEndedInEarlySurrender") for p in parts)

    gold = [[] for _ in range(10)]
    xy = [[] for _ in range(10)]
    xp_at, cs_at = {}, {}
    for minute, fr in enumerate(frames):
        pf = fr.get("participantFrames") or {}
        for i in range(10):
            f = pf.get(str(i + 1)) or {}
            gold[i].append(int(f.get("totalGold", 0)))
            pos = f.get("position") or {}
            xy[i].extend((_q(pos.get("x", 0)), _q(pos.get("y", 0))))
            # The last frame is the end of the game, not a whole minute, so it
            # must not be mistaken for "at 10" in a game that ended at 9:40.
            if minute in (10, 15) and minute < len(frames) - 1:
                xp_at.setdefault(minute, {})[i] = int(f.get("xp", 0))
                cs_at.setdefault(minute, {})[i] = (int(f.get("minionsKilled", 0))
                                                   + int(f.get("jungleMinionsKilled", 0)))

    kills, mon, bld = [], [], []
    bought = [[] for _ in range(10)]
    bought_at = [[] for _ in range(10)]
    skills = [[] for _ in range(10)]
    level4 = [None] * 10
    for fr in frames:
        for e in fr.get("events") or []:
            typ = e.get("type")
            t = int(e.get("timestamp", 0)) // 1000
            if typ == "CHAMPION_KILL":
                pos = e.get("position") or {}
                kills.append([t, _q(pos.get("x", 0)), _q(pos.get("y", 0)),
                              int(e.get("killerId", 0)), int(e.get("victimId", 0))]
                             + [int(a) for a in e.get("assistingParticipantIds") or []])
            elif typ == "ELITE_MONSTER_KILL":
                code = e.get("monsterType") or "?"
                if e.get("monsterSubType"):
                    code += ":" + e["monsterSubType"]
                mon.append([t, code, int(e.get("killerId", 0)), int(e.get("killerTeamId", 0))]
                           + [int(a) for a in e.get("assistingParticipantIds") or []])
            elif typ == "BUILDING_KILL":
                code = "I" if e.get("buildingType") == "INHIBITOR_BUILDING" else \
                    "T" + (e.get("towerType") or "?")[:1]
                bld.append([t, int(e.get("teamId", 0)), code, (e.get("laneType") or "")[:3]])
            elif typ == "ITEM_PURCHASED":
                pid, item = int(e.get("participantId", 0)), int(e.get("itemId", 0))
                if 1 <= pid <= 10 and item not in _NOT_A_BUILD_ITEM:
                    bought[pid - 1].append(item)
                    bought_at[pid - 1].append(t)
            elif typ == "ITEM_UNDO":
                # An undone purchase never happened as far as a build goes.
                pid, before = int(e.get("participantId", 0)), int(e.get("beforeId", 0))
                if 1 <= pid <= 10 and before and not e.get("afterId"):
                    lst = bought[pid - 1]
                    for j in range(len(lst) - 1, -1, -1):
                        if lst[j] == before:
                            del lst[j]
                            del bought_at[pid - 1][j]
                            break
            elif typ == "SKILL_LEVEL_UP" and e.get("levelUpType") == "NORMAL":
                pid = int(e.get("participantId", 0))
                if 1 <= pid <= 10 and len(skills[pid - 1]) < 18:
                    skills[pid - 1].append(_SKILL_LETTER.get(e.get("skillSlot"), "?"))
            elif typ == "LEVEL_UP" and e.get("level") == 4:
                # The end of a jungler's first clear, to the second. The
                # minute samples cannot say this: 2:40 and 3:20 both read as
                # "level 4 by the four-minute frame".
                pid = int(e.get("participantId", 0))
                if 1 <= pid <= 10 and level4[pid - 1] is None:
                    level4[pid - 1] = t

    players = []
    for i, p in enumerate(parts):
        ch = p.get("challenges") or {}
        name = p.get("riotIdGameName") or p.get("summonerName") or ""
        tag = p.get("riotIdTagline") or ""
        players.append({
            "pu": p.get("puuid"),
            "n": f"{name}#{tag}" if tag else name,
            "c": p.get("championName") or "Unknown",
            "t": p.get("teamId"),
            "r": p.get("teamPosition") or "",
            "k": p.get("kills", 0), "d": p.get("deaths", 0), "a": p.get("assists", 0),
            "cs": p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0),
            "gold": p.get("goldEarned", 0),
            "dmg": p.get("totalDamageDealtToChampions", 0),
            "taken": p.get("totalDamageTaken", 0),
            "vis": p.get("visionScore", 0),
            "lvl": p.get("champLevel", 0),
            "heal": p.get("totalHealsOnTeammates", 0),
            "shield": p.get("totalDamageShieldedOnTeammates", 0),
            "cc": p.get("timeCCingOthers", 0),
            "objDmg": p.get("damageDealtToObjectives", 0),
            "stolen": p.get("objectivesStolen", 0),
            "wards": p.get("wardsPlaced", 0),
            "ctrl": p.get("detectorWardsPlaced", 0),
            "wk": p.get("wardsKilled", 0),
            "solo": int(ch.get("soloKills", 0) or 0),
            "plates": int(ch.get("turretPlatesTaken", 0) or 0),
            "dead": p.get("totalTimeSpentDead", 0),
            "items": [p.get(f"item{j}", 0) for j in range(6) if p.get(f"item{j}", 0)],
            "buy": bought[i],
            "bt": bought_at[i],
            "sk": "".join(skills[i]),
            "l4": level4[i],
            # Buildings only. damageDealtToObjectives counts towers and epic
            # monsters together, which is why it could not tell a split
            # pusher from a jungler.
            "tur": p.get("damageDealtToTurrets", 0),
            "epic": p.get("damageDealtToEpicMonsters",
                          max(0, p.get("damageDealtToObjectives", 0) - p.get("damageDealtToBuildings", 0))),
            "mit": p.get("damageSelfMitigated", 0),
            "th": p.get("totalHeal", 0),
            "ejg": int(round(ch.get("enemyJungleMonsterKills", 0) or 0)),
            "immob": int(ch.get("enemyChampionImmobilizations", 0) or 0),
            "skh": int(ch.get("skillshotsHit", 0) or 0),
            "crab0": ch.get("initialCrabCount"),
            "crab": ch.get("scuttleCrabKills"),
            "multi": int(ch.get("multikills", 0) or 0),
            "penta": p.get("pentaKills", 0),
            "g": gold[i],
            "xy": xy[i],
            "x10": xp_at.get(10, {}).get(i), "x15": xp_at.get(15, {}).get(i),
            "c10": cs_at.get(10, {}).get(i), "c15": cs_at.get(15, {}).get(i),
        })

    return {
        "id": (match.get("metadata") or {}).get("matchId"),
        "q": info.get("queueId"),
        "t0": info.get("gameStartTimestamp") or info.get("gameCreation", 0),
        "dur": int(info.get("gameDuration", 0)),
        "patch": ".".join(str(info.get("gameVersion", "")).split(".")[:2]),
        "win": win_team,
        "remake": bool(remake),
        "pv": RECORD_VERSION,
        "p": players,
        "kills": kills,
        "mon": mon,
        "bld": bld,
    }


def shard_name(start_ms):
    return datetime.fromtimestamp((start_ms or 0) / 1000.0, tz=timezone.utc).strftime("%Y-%m")


class GameStore:
    """Every stored game, loaded whole. A season is about 30 MB of JSON."""

    def __init__(self, root=STORE_DIR):
        self.root = Path(root)
        self.shards = {}      # shard name -> {matchId: record}
        self.where = {}       # matchId -> shard name
        self.skip = {}        # matchId -> reason
        self.ranks = {}       # puuid -> [solo, flex, read at (epoch seconds)]
        self.dirty = set()
        self.skip_dirty = False
        self.ranks_dirty = False

    def load(self):
        if not self.root.is_dir():
            return self
        for path in sorted(self.root.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                # A shard cut short by a killed run is a few hundred games to
                # fetch again, not a reason to stop publishing.
                print(f"  ! could not read {path} ({e}); it will be rebuilt")
                continue
            if path.name == SKIP_FILE:
                self.skip = doc if isinstance(doc, dict) else {}
                continue
            if path.name == RANK_FILE:
                self.ranks = doc if isinstance(doc, dict) else {}
                continue
            if doc.get("v") != STORE_VERSION:
                print(f"  ! {path.name} is store version {doc.get('v')}, wanted {STORE_VERSION}; ignoring it")
                continue
            games = doc.get("games") or {}
            self.shards[path.stem] = games
            for mid in games:
                self.where[mid] = path.stem
        return self

    def __len__(self):
        return len(self.where)

    def __contains__(self, match_id):
        return match_id in self.where

    def get(self, match_id):
        shard = self.where.get(match_id)
        return self.shards[shard].get(match_id) if shard else None

    def games(self):
        for games in self.shards.values():
            yield from games.values()

    def put(self, rec):
        shard = shard_name(rec.get("t0"))
        self.shards.setdefault(shard, {})[rec["id"]] = rec
        self.where[rec["id"]] = shard
        self.dirty.add(shard)

    def touch(self, match_id):
        """A record was changed in place and its shard needs writing."""
        self.dirty.add(self.where[match_id])

    def mark_skipped(self, match_id, reason):
        self.skip[match_id] = reason
        self.skip_dirty = True

    def save(self):
        if not (self.dirty or self.skip_dirty or self.ranks_dirty):
            return
        self.root.mkdir(parents=True, exist_ok=True)
        for shard in sorted(self.dirty):
            doc = {"v": STORE_VERSION, "games": self.shards[shard]}
            tmp = self.root / f"{shard}.json.tmp"
            # Written beside the real file and moved over it, so a run killed
            # mid-write leaves the previous shard rather than half of a new one.
            tmp.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.root / f"{shard}.json")
        if self.skip_dirty:
            (self.root / SKIP_FILE).write_text(json.dumps(self.skip, indent=0), encoding="utf-8")
        if self.ranks_dirty:
            tmp = self.root / (RANK_FILE + ".tmp")
            tmp.write_text(json.dumps(self.ranks, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self.root / RANK_FILE)
        self.dirty.clear()
        self.skip_dirty = False
        self.ranks_dirty = False


class _KeyRejected(RuntimeError):
    """Every later call would fail the same way, so the caller should stop."""


def _fetch_record(client, mid):
    """(record, None), or (None, why it is not worth asking for again).

    One game that will not download raises RuntimeError and is skipped for
    this run only. A rejected key raises _KeyRejected.
    """
    try:
        match = client.get_match(mid)
        timeline = client.get_timeline(mid) if match else None
    except RuntimeError as e:
        if " 401 " in str(e) or " 403 " in str(e):
            raise _KeyRejected(str(e))
        raise
    if not match or not timeline:
        return None, "no match" if not match else "no timeline"
    rec = reduce_game(match, timeline)
    if rec and rec.get("id"):
        return rec, None
    return None, "not a ten-player rift game"


def backfill(client, store, match_ids, budget_seconds, wait=None, save_every=25, log=print):
    """Fetch and store games this store does not hold yet, newest first.

    Stops when the time budget is spent, so an ordinary hourly run spends a
    few minutes here and a whole season fills in over a day of runs without
    any one of them being a special occasion. Returns (stored, remaining).

    match_ids must already be newest first. `wait` is called before each game
    and may sleep; the local backfill uses it to stay out of the scheduled
    run's way at the top of the hour.
    """
    todo = [m for m in match_ids if m not in store and m not in store.skip]
    if not todo or budget_seconds <= 0:
        return 0, len(todo)
    started = time.monotonic()
    stored = 0
    for n, mid in enumerate(todo):
        if time.monotonic() - started > budget_seconds:
            break
        if wait:
            wait()
        try:
            rec, why = _fetch_record(client, mid)
        except _KeyRejected as e:
            log(f"  ! key rejected while fetching games; stopping ({e})")
            break
        except RuntimeError as e:
            log(f"  ! {mid}: {e}")
            continue
        if rec:
            store.put(rec)
            stored += 1
        else:
            # Riot stops serving timelines after about a year. Asking again
            # every hour forever would spend the budget on games that will
            # never arrive.
            store.mark_skipped(mid, why)
        if (n + 1) % save_every == 0:
            store.save()
            log(f"    ...{stored} games stored, {len(todo) - n - 1} to go")
    store.save()
    remaining = len([m for m in todo if m not in store and m not in store.skip])
    return stored, remaining


def upgrade(client, store, budget_seconds, wait=None, save_every=25, oldest_first=False, log=print):
    """Fetch again every game stored before the current record version.

    Newest first by default, because the games people open are recent ones.
    A game Riot no longer serves keeps its old record: fewer fields is better
    than no game. Returns (upgraded, remaining).
    """
    todo = [g["id"] for g in store.games() if g.get("pv", 1) < RECORD_VERSION and not g.get("pvx")]
    todo.sort(key=lambda m: store.get(m).get("t0") or 0, reverse=not oldest_first)
    if not todo or budget_seconds <= 0:
        return 0, len(todo)
    started = time.monotonic()
    done = 0
    for n, mid in enumerate(todo):
        if time.monotonic() - started > budget_seconds:
            break
        if wait:
            wait()
        old = store.get(mid)
        try:
            rec, why = _fetch_record(client, mid)
        except _KeyRejected as e:
            log(f"  ! key rejected while upgrading games; stopping ({e})")
            break
        except RuntimeError as e:
            log(f"  ! {mid}: {e}")
            continue
        if rec:
            for keep in ("rk", "rkt"):
                if keep in old:
                    rec[keep] = old[keep]
            store.put(rec)
            done += 1
        else:
            # Marked so it is not asked for every hour for the rest of time.
            old["pvx"] = why
            store.touch(mid)
        if (n + 1) % save_every == 0:
            store.save()
            log(f"    ...{done} games upgraded, {len(todo) - n - 1} to go")
    store.save()
    left = sum(1 for g in store.games() if g.get("pv", 1) < RECORD_VERSION and not g.get("pvx"))
    return done, left


def rank_pair(entries):
    """[solo, flex] from a league-v4 response: 0 for unranked in that queue,
    otherwise [tier index, division 1 to 4, LP]."""
    out = [0, 0]
    for e in entries or []:
        slot = {"RANKED_SOLO_5x5": 0, "RANKED_FLEX_SR": 1}.get(e.get("queueType"))
        if slot is None or e.get("tier") not in TIERS:
            continue
        out[slot] = [TIERS.index(e["tier"]), _DIVISION.get(e.get("rank"), 1), int(e.get("leaguePoints", 0))]
    return out


def fill_ranks(client, store, budget_seconds, wait=None, save_every=20, oldest_first=False, log=print):
    """Give every stored game a rank for each of its ten players.

    Up to ten calls a game, fewer when somebody has been looked up before.
    Returns (games filled, games remaining, lookups made).
    """
    todo = [g["id"] for g in store.games() if "rk" not in g]
    todo.sort(key=lambda m: store.get(m).get("t0") or 0, reverse=not oldest_first)
    if not todo or budget_seconds <= 0:
        return 0, len(todo), 0
    started = time.monotonic()
    filled = lookups = 0
    stop = False
    for n, mid in enumerate(todo):
        if stop or time.monotonic() - started > budget_seconds:
            break
        g = store.get(mid)
        now = time.time()
        live = now * 1000 - (g.get("t0") or 0) < RANK_LIVE_WINDOW_MS
        out = []
        for p in g["p"]:
            pu = p.get("pu")
            held = store.ranks.get(pu) if pu else None
            if held and (not live or now - held[2] < RANK_FRESH_SECONDS):
                out.append([held[0], held[1]])
                continue
            if not pu:
                out.append(None)
                continue
            if wait:
                wait()
            try:
                pair = rank_pair(client.get_league_entries_by_puuid(pu))
            except RuntimeError as e:
                if " 401 " in str(e) or " 403 " in str(e):
                    log(f"  ! key rejected while reading ranks; stopping ({e})")
                    stop = True
                    break
                # One player who cannot be read is filled in from the others
                # when the game is scored. Not worth losing the game over.
                out.append(None)
                continue
            lookups += 1
            store.ranks[pu] = [pair[0], pair[1], int(now)]
            store.ranks_dirty = True
            out.append(pair)
        if stop:
            break
        g["rk"], g["rkt"] = out, int(now * 1000)
        store.touch(mid)
        filled += 1
        if (n + 1) % save_every == 0:
            store.save()
            log(f"    ...{filled} games ranked ({lookups} lookups), {len(todo) - n - 1} to go")
    store.save()
    return filled, sum(1 for g in store.games() if "rk" not in g), lookups


def _main(argv):
    """python game_store.py [--budget SECONDS] [--polite] [--oldest-first]
                            [--upgrade] [--ranks] [--pause SECONDS]

    --upgrade re-fetches games stored before the current record version, and
    --ranks reads a rank for every player in every game that has none. Both
    run after the ordinary fill, in that order, inside the same budget.

    Fills the store from the ids in scrape_log.json using the key in
    config.json. --polite idles around the top of each hour, when the
    scheduled publish makes its own calls on the same rate limit.
    --oldest-first works from the far end of the season, so a local fill and
    the scheduled one, which goes newest first, meet in the middle instead of
    both fetching the same games.
    """
    import fetch_data
    budget = 10 ** 9
    polite = "--polite" in argv
    if "--budget" in argv:
        budget = float(argv[argv.index("--budget") + 1])
    cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
    client = fetch_data.RiotClient(cfg["api_key"], cfg.get("platform", "euw1"),
                                   cfg.get("routing", "europe"))
    if "--pause" in argv:
        # Seconds between calls. The default is gentle enough to share a key
        # with the scheduled run without ever being told to slow down; a long
        # local fill can go nearer the limit and let Riot's own replies pace it.
        client.pause = float(argv[argv.index("--pause") + 1])
    log = json.loads(Path("scrape_log.json").read_text(encoding="utf-8"))
    wanted = {f["label"] for f in cfg.get("friends", [])}
    ids = set()
    for entry in log.values():
        if isinstance(entry, dict) and entry.get("label") in wanted:
            ids.update(entry.get("matchIds") or [])
    ordered = sorted(ids, key=lambda m: int(m.split("_")[-1]),
                     reverse="--oldest-first" not in argv)

    def wait():
        while polite and (datetime.now().minute >= 58 or datetime.now().minute < 5):
            time.sleep(20)

    store = GameStore().load()
    print(f"{len(store)} games held, {len(store.skip)} skipped, {len(ordered)} wanted", flush=True)
    say = lambda s: print(s, flush=True)
    began = time.monotonic()
    left = lambda: budget - (time.monotonic() - began)
    stored, remaining = backfill(client, store, ordered, budget, wait=wait, log=say)
    print(f"Stored {stored}; {remaining} still to fetch.", flush=True)
    oldest = "--oldest-first" in argv
    if "--upgrade" in argv:
        done, remaining = upgrade(client, store, left(), wait=wait, oldest_first=oldest, log=say)
        print(f"Upgraded {done}; {remaining} still on an old record.", flush=True)
    if "--ranks" in argv:
        filled, remaining, lookups = fill_ranks(client, store, left(), wait=wait, oldest_first=oldest, log=say)
        print(f"Ranked {filled} games with {lookups} lookups; {remaining} still without.", flush=True)


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
