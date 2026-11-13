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
    id, q, t0, dur, patch, win, remake
    p[10]   one per participant, in participantId order
    kills   [t, x, y, killer, victim, assist...]
    mon     [t, code, killer, team, assist...]
    bld     [t, losingTeam, code, lane]
Times are whole seconds from game start. Positions are map units // 64, which
keeps every coordinate under 256 and is finer than anything drawn from them.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

STORE_VERSION = 1
STORE_DIR = Path("games")
SKIP_FILE = "_skip.json"
POS_SCALE = 64

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
    skills = [[] for _ in range(10)]
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
            elif typ == "ITEM_UNDO":
                # An undone purchase never happened as far as a build goes.
                pid, before = int(e.get("participantId", 0)), int(e.get("beforeId", 0))
                if 1 <= pid <= 10 and before and not e.get("afterId"):
                    lst = bought[pid - 1]
                    for j in range(len(lst) - 1, -1, -1):
                        if lst[j] == before:
                            del lst[j]
                            break
            elif typ == "SKILL_LEVEL_UP" and e.get("levelUpType") == "NORMAL":
                pid = int(e.get("participantId", 0))
                if 1 <= pid <= 10 and len(skills[pid - 1]) < 18:
                    skills[pid - 1].append(_SKILL_LETTER.get(e.get("skillSlot"), "?"))

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
            "sk": "".join(skills[i]),
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
        self.dirty = set()
        self.skip_dirty = False

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

    def mark_skipped(self, match_id, reason):
        self.skip[match_id] = reason
        self.skip_dirty = True

    def save(self):
        if not (self.dirty or self.skip_dirty):
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
        self.dirty.clear()
        self.skip_dirty = False


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
            match = client.get_match(mid)
            timeline = client.get_timeline(mid) if match else None
        except RuntimeError as e:
            # One game that will not download is not worth the rest. A rejected
            # key is different: every later call would fail the same way.
            if " 401 " in str(e) or " 403 " in str(e):
                log(f"  ! key rejected while fetching games; stopping ({e})")
                break
            log(f"  ! {mid}: {e}")
            continue
        if not match or not timeline:
            # Riot stops serving timelines after about a year. Asking again
            # every hour forever would spend the budget on games that will
            # never arrive.
            store.mark_skipped(mid, "no match" if not match else "no timeline")
        else:
            rec = reduce_game(match, timeline)
            if rec and rec.get("id"):
                store.put(rec)
                stored += 1
            else:
                store.mark_skipped(mid, "not a ten-player rift game")
        if (n + 1) % save_every == 0:
            store.save()
            log(f"    ...{stored} games stored, {len(todo) - n - 1} to go")
    store.save()
    remaining = len([m for m in todo if m not in store and m not in store.skip])
    return stored, remaining


def _main(argv):
    """python game_store.py [--budget SECONDS] [--polite] [--oldest-first]

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
    stored, remaining = backfill(client, store, ordered, budget, wait=wait,
                                 log=lambda s: print(s, flush=True))
    print(f"Stored {stored}; {remaining} still to fetch.", flush=True)


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
