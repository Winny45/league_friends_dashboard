#!/usr/bin/env python3
"""
fetch_data.py — pulls ranked stats, season-long match history, and champion
mastery for a list of friends from the official Riot Games API, and writes
the result to data.json for the dashboard generator to render.

Usage:
    python3 fetch_data.py [config.json]

Requires a free developer API key from https://developer.riotgames.com
(see README.md for how to get one — dev keys expire every 24h and need
re-pasting into config.json).

Season-long history is expensive to pull (one API call per match), so match
details are cached on disk in matches_cache.json — re-running this script
only fetches games that weren't already cached, so a daily refresh after the
first big pull is fast.
"""
import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta

# Riot IDs can contain characters outside the Windows console's default
# codepage (e.g. Turkish dotless-i in some display names) — without this,
# print() crashes with UnicodeEncodeError before the friend is ever fetched.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

# Riot's numeric queueId -> friendly name.
QUEUE_ID_NAMES = {
    420: "Ranked Solo/Duo",
    440: "Ranked Flex",
    42: "Ranked 5s",  # legacy pre-2016 "Team Ranked 5x5" queue; kept in case old data ever carries it
    400: "Normal Draft",
    430: "Normal Blind",
    450: "ARAM",
    900: "ARURF",
    1700: "Arena",
}

# Only these queues count toward match history, weekly playtime, busiest-day,
# and highlights — normals/ARAM/Arena/etc. are fetched by nothing here at
# all (filtered server-side via Riot's own `queue` param, so non-ranked
# games never cost an API call in the first place).
RANKED_QUEUE_IDS = [420, 440, 42]
RANKED_QUEUE_NAMES = {QUEUE_ID_NAMES[qid] for qid in RANKED_QUEUE_IDS}

MATCH_CACHE_PATH = Path("matches_cache.json")
SCRAPE_LOG_PATH = Path("scrape_log.json")
RANK_HISTORY_PATH = Path("rank_history.json")
RANK_HISTORY_KEEP_DAYS = 400  # trim anything older than this so the file doesn't grow forever

# Kept in sync with the identically-named constants/logic in
# generate_dashboard.py's tier_score() — duplicated here (rather than
# imported) so fetch_data.py has no dependency on the dashboard renderer.
# Used only to find each friend's highest-ever recorded snapshot ("peak
# rank") across all of rank_history.json, not just the last 30 days.
_TIER_ORDER = [
    "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
    "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
]
_RANK_SCORE = {"IV": 0, "III": 1, "II": 2, "I": 3}
_APEX_TIERS = {"MASTER", "GRANDMASTER", "CHALLENGER"}


def _tier_score(entry):
    if not entry or not entry.get("tier"):
        return -1
    tier = entry["tier"]
    ti = _TIER_ORDER.index(tier) if tier in _TIER_ORDER else -1
    rank_component = 4 if tier in _APEX_TIERS else _RANK_SCORE.get(entry.get("rank"), 0)
    lp = entry.get("leaguePoints", 0) or 0
    return ti * 1000 + rank_component * 200 + lp


def compute_peaks(rank_history):
    """Highest-ever snapshot per (friend, queue) across all recorded rank
    history — 'peak rank since tracking began'. Not the same as an
    all-time peak (Riot doesn't expose one), just the best we've observed
    ourselves."""
    peaks = {}
    for h in rank_history:
        key = (h["label"], h["queue"])
        cand = {"tier": h.get("tier"), "rank": h.get("rank"), "leaguePoints": h.get("leaguePoints", 0)}
        if key not in peaks or _tier_score(cand) > _tier_score(peaks[key]):
            peaks[key] = cand
    return peaks


class RiotClient:
    def __init__(self, api_key, platform, routing, pause=1.3):
        self.api_key = api_key
        self.platform = platform  # e.g. euw1  (summoner/league/mastery host)
        self.routing = routing    # e.g. europe (account/match host)
        self.pause = pause        # seconds between calls to stay under dev-key rate limits

    def _get(self, host, path):
        url = f"https://{host}.api.riotgames.com{path}"
        # Riot's API sits behind Cloudflare, which blocks requests that look
        # like a bare bot client (no User-Agent, etc.) with a Cloudflare
        # "error code: 1010" page even though the request itself is fine.
        # Sending browser-like headers avoids that.
        headers = {
            "X-Riot-Token": self.api_key,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Charset": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://developer.riotgames.com",
        }
        req = urllib.request.Request(url, headers=headers)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    time.sleep(self.pause)
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retry_after = int(e.headers.get("Retry-After", "5"))
                    print(f"  rate limited, waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                if e.code == 404:
                    return None
                raise RuntimeError(
                    f"Riot API error {e.code} on {path}: {e.read().decode('utf-8', 'ignore')}"
                )
        raise RuntimeError(f"Failed after retries: {path}")

    def get_account_by_riot_id(self, game_name, tag_line):
        return self._get(self.routing, f"/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(game_name)}/{urllib.parse.quote(tag_line)}")

    def get_summoner_by_puuid(self, puuid):
        return self._get(self.platform, f"/lol/summoner/v4/summoners/by-puuid/{puuid}")

    def get_league_entries_by_puuid(self, puuid):
        return self._get(self.platform, f"/lol/league/v4/entries/by-puuid/{puuid}") or []

    def get_mastery_top_by_puuid(self, puuid, count=5):
        return self._get(self.platform, f"/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count={count}") or []

    def get_match_ids_page(self, puuid, start, count, start_time=None, queue=None):
        q = f"start={start}&count={count}"
        if start_time is not None:
            q += f"&startTime={int(start_time)}"
        if queue is not None:
            q += f"&queue={int(queue)}"
        return self._get(self.routing, f"/lol/match/v5/matches/by-puuid/{puuid}/ids?{q}") or []

    def get_match(self, match_id):
        return self._get(self.routing, f"/lol/match/v5/matches/{match_id}")


def sync_new_match_ids_for_queue(client, puuid, start_time_epoch, queue_id, known_set, full_resync, budget_left):
    """Get just the *new* match ids (newest-first) for one ranked queue since
    start_time_epoch, without re-listing games we already know about.

    Riot's by-puuid ids endpoint returns newest-first, so once a page's ids
    start overlapping with `known_set` (built from a previous run's scrape
    log, across all ranked queues), everything after that point is already
    known — we can stop paginating right there instead of walking the whole
    season again. That's the "only fetch new games" behavior: a daily
    re-run typically needs at most one short page per queue (or none, if
    nobody's played since last time).

    `full_resync` forces a complete re-list from page 0 with no early stop —
    used the first time we see a puuid, or when season_start has moved
    earlier than what the log was built with (so there may be older games
    we've never listed). `budget_left` is an emergency backstop on total
    matches, not a target.
    """
    new_ids = []
    page = 0
    while True:
        batch = client.get_match_ids_page(puuid, start=page * 100, count=100,
                                           start_time=start_time_epoch, queue=queue_id)
        if not batch:
            break
        hit_known = False
        for mid in batch:
            if not full_resync and mid in known_set:
                hit_known = True
                break
            new_ids.append(mid)
        if hit_known:
            break
        if len(batch) < 100:
            break  # last page — Riot has nothing more for this queue/period
        page += 1
        if len(new_ids) >= budget_left:
            print(f"    ! hit the match safety cap for queue {queue_id} — raise max_season_matches "
                  f"in config.json if you actually expect more games than that")
            break
    return new_ids


def extract_match_entry(m, puuid, match_id):
    info = m.get("info", {})
    participants = info.get("participants", [])
    participant = next((p for p in participants if p.get("puuid") == puuid), None)
    if not participant:
        return None

    # Remakes: Riot ends a game early (before ~3-5 min) with no stat impact
    # when someone doesn't connect, and flags every participant's row with
    # gameEndedInEarlySurrender = true. These should never count as a real
    # win/loss/game played, so callers filter matches with "remake": True
    # out of season_matches (they're still recorded in the match cache and
    # scrape log so they're not re-fetched every run, just excluded from
    # every stat).
    is_remake = bool(participant.get("gameEndedInEarlySurrender", False))

    kills, deaths, assists = participant.get("kills", 0), participant.get("deaths", 0), participant.get("assists", 0)
    kda = (kills + assists) / max(deaths, 1)
    cs = participant.get("totalMinionsKilled", 0) + participant.get("neutralMinionsKilled", 0)
    duration_min = max(info.get("gameDuration", 0) / 60.0, 1)
    # gameStartTimestamp is when the game actually started; gameCreation is
    # when the lobby was created (a bit earlier). Prefer the former.
    start_ms = info.get("gameStartTimestamp") or info.get("gameCreation", 0)
    start_dt = datetime.fromtimestamp(start_ms / 1000.0) if start_ms else None

    team_id = participant.get("teamId")
    position = participant.get("teamPosition") or None
    # "Nemesis" opponent: whoever played the same role on the enemy team.
    # teamPosition is only populated for Solo/Duo & Flex (the ranked queues
    # this tool cares about), so this is usually reliable there; it can be
    # blank in some edge cases (e.g. autofill oddities), in which case we
    # just leave it unset rather than guess.
    opponent_champion = None
    if position:
        opponent = next(
            (p for p in participants if p.get("teamPosition") == position and p.get("teamId") != team_id),
            None,
        )
        if opponent:
            opponent_champion = opponent.get("championName")

    return {
        "matchId": match_id,
        "remake": is_remake,
        "champion": participant.get("championName", "Unknown"),
        "win": bool(participant.get("win", False)),
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kda": round(kda, 2),
        "csPerMin": round(cs / duration_min, 1),
        "damageDealt": participant.get("totalDamageDealtToChampions", 0),
        "queue": QUEUE_ID_NAMES.get(info.get("queueId"), f"Queue {info.get('queueId')}"),
        "gameStartMs": start_ms,
        "gameStart": start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else None,
        "dateKey": start_dt.strftime("%Y-%m-%d") if start_dt else None,
        "durationMin": round(duration_min, 1),
        "teamId": team_id,
        "position": position,
        "opponentChampion": opponent_champion,
    }


def summarize_friend(client: RiotClient, label: str, riot_id: str, match_count: int,
                      season_start_epoch: float, season_start_key: str, max_season_matches: int,
                      match_cache: dict, scrape_log: dict):
    if "#" not in riot_id:
        raise ValueError(f"Riot ID for '{label}' must look like Name#Tag, got {riot_id!r}")
    game_name, tag_line = riot_id.split("#", 1)

    print(f"Fetching {label} ({riot_id})...")
    account = client.get_account_by_riot_id(game_name, tag_line)
    if not account:
        print(f"  ! could not find account for {riot_id} — skipping")
        return None
    puuid = account["puuid"]

    summoner = client.get_summoner_by_puuid(puuid) or {}
    league_entries = client.get_league_entries_by_puuid(puuid)
    mastery = client.get_mastery_top_by_puuid(puuid, count=5)

    solo = next((e for e in league_entries if e.get("queueType") == "RANKED_SOLO_5x5"), None)
    flex = next((e for e in league_entries if e.get("queueType") == "RANKED_FLEX_SR"), None)

    log_entry = scrape_log.get(puuid, {})
    known_ids = log_entry.get("matchIds", [])
    logged_season_start = log_entry.get("seasonStart")
    # Full re-list only when we've never scraped this puuid, or season_start
    # moved earlier than what the log covers (so there may be older games
    # we've never listed). Otherwise this is an incremental "what's new"
    # pass that typically costs at most one short page per ranked queue.
    full_resync = not known_ids or logged_season_start is None or season_start_key < logged_season_start
    if full_resync:
        print(f"  full match list scrape (first time seeing this account, or season_start moved earlier)")

    known_set = set(known_ids)
    new_ids = []
    for queue_id in RANKED_QUEUE_IDS:
        budget_left = max_season_matches - len(known_ids) - len(new_ids)
        if budget_left <= 0:
            break
        new_ids.extend(sync_new_match_ids_for_queue(
            client, puuid, season_start_epoch, queue_id, known_set, full_resync, budget_left,
        ))
    match_ids = new_ids if full_resync else new_ids + known_ids
    new_id_count = len(new_ids) if not full_resync else None

    season_matches = []
    new_fetches = 0
    cache_hits = 0
    remake_count = 0
    kept_ids = []
    for mid in match_ids:
        cache_key = f"{mid}|{puuid}"
        cached = match_cache.get(cache_key)
        if cached:
            entry = cached
            cache_hits += 1
        else:
            m = client.get_match(mid)
            if not m:
                continue
            entry = extract_match_entry(m, puuid, mid)
            if not entry:
                continue
            match_cache[cache_key] = entry
            new_fetches += 1
            if new_fetches % 20 == 0:
                print(f"    ...{new_fetches} new matches fetched so far")
        # Ranked-only, belt-and-suspenders: the id listing above is already
        # queue-filtered server-side, but this also drops any stale
        # normals/ARAM ids left over in an old scrape_log from before this
        # filter existed, so the log self-cleans over the next couple runs.
        if entry.get("queue") not in RANKED_QUEUE_NAMES:
            continue
        # Mark as processed either way so a remake never gets re-listed and
        # re-checked on every future run, but keep it out of season_matches
        # (and therefore every stat, highlight, and chart) entirely.
        kept_ids.append(mid)
        if entry.get("remake"):
            remake_count += 1
            continue
        season_matches.append(entry)

    scrape_log[puuid] = {"label": label, "riotId": riot_id, "seasonStart": season_start_key, "matchIds": kept_ids}

    # Trim to season_start in case season_start was tightened (moved later)
    # since the log was built — matchIds can carry older entries that are
    # no longer in-window even though we know about them.
    season_start_ms = season_start_epoch * 1000
    season_matches = [e for e in season_matches if (e.get("gameStartMs") or 0) >= season_start_ms]
    # Merging per-queue listings means matches aren't guaranteed newest-first
    # overall anymore (each queue is newest-first on its own) — restore
    # chronological order before this becomes recentMatches/seasonMatches.
    season_matches.sort(key=lambda e: e.get("gameStartMs") or 0, reverse=True)

    scrape_note = f"{new_id_count} new since last run" if new_id_count is not None else "full scrape"
    remake_note = f", {remake_count} remake(s) excluded" if remake_count else ""
    print(f"  {len(season_matches)} ranked matches this season "
          f"({scrape_note}; {new_fetches} match detail(s) freshly fetched, "
          f"{cache_hits} from the match detail cache{remake_note})")

    return {
        "label": label,
        "riotId": riot_id,
        "puuid": puuid,
        "summonerLevel": summoner.get("summonerLevel"),
        "ranked": {
            "solo": _entry_summary(solo),
            "flex": _entry_summary(flex),
        },
        "mastery": [
            {
                "championId": m.get("championId"),
                "championName": m.get("championName") or get_champion_id_to_name_map().get(str(m.get("championId")), f"Champion {m.get('championId')}"),
                "level": m.get("championLevel"),
                "points": m.get("championPoints"),
            }
            for m in mastery
        ],
        # seasonMatches: everything since season_start (up to the cap) — used
        # for weekly playtime / busiest-day / game-start-time stats.
        "seasonMatches": season_matches,
        # recentMatches: the newest `match_count` of those — used for the
        # per-friend detail table and the fun "highlights" awards.
        "recentMatches": season_matches[:match_count],
    }


_CHAMP_MAP_CACHE = None


def get_champion_data():
    """Champion mastery only returns a numeric championId, not a name, so we
    resolve names (and champion icon slugs, for the dashboard's champion
    icons) from Riot's public Data Dragon static data — no API key needed.
    Cached on disk for 24h so we don't re-fetch every run.

    Returns {"version": "14.20.1", "byKey": {"103": "Ahri", ...},
    "byName": {"Ahri": "Ahri", "Wukong": "MonkeyKing", ...}}. byName maps a
    champion's *display* name to its Data Dragon *slug* — these differ for
    a handful of champions (Wukong -> MonkeyKing, Renata Glasc -> Renata,
    Nunu & Willump -> Nunu, Bel'Veth -> Belveth, etc.), and the slug is what
    the icon CDN URL needs, so this map is what makes icons actually
    resolve instead of 404ing on those edge cases."""
    global _CHAMP_MAP_CACHE
    if _CHAMP_MAP_CACHE is not None:
        return _CHAMP_MAP_CACHE

    cache_path = Path("champions_cache.json")
    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < 86400:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and "byName" in cached:
                _CHAMP_MAP_CACHE = cached
                return _CHAMP_MAP_CACHE
        except Exception:
            pass  # fall through and re-fetch (also covers the old byKey-only cache format)

    try:
        with urllib.request.urlopen(
            "https://ddragon.leagueoflegends.com/api/versions.json", timeout=10
        ) as resp:
            latest_version = json.loads(resp.read().decode("utf-8"))[0]
        with urllib.request.urlopen(
            f"https://ddragon.leagueoflegends.com/cdn/{latest_version}/data/en_US/champion.json",
            timeout=10,
        ) as resp:
            champ_data = json.loads(resp.read().decode("utf-8"))["data"]
        result = {
            "version": latest_version,
            "byKey": {str(v["key"]): v["name"] for v in champ_data.values()},
            "byName": {v["name"]: v["id"] for v in champ_data.values()},
        }
        cache_path.write_text(json.dumps(result), encoding="utf-8")
        _CHAMP_MAP_CACHE = result
    except Exception as e:
        print(f"  ! could not fetch champion data ({e}); mastery will show IDs and icons will be skipped")
        _CHAMP_MAP_CACHE = {"version": None, "byKey": {}, "byName": {}}
    return _CHAMP_MAP_CACHE


def get_champion_id_to_name_map():
    return get_champion_data()["byKey"]


def _entry_summary(entry):
    if not entry:
        return None
    wins, losses = entry.get("wins", 0), entry.get("losses", 0)
    total = wins + losses
    return {
        "tier": entry.get("tier"),
        "rank": entry.get("rank"),
        "leaguePoints": entry.get("leaguePoints"),
        "wins": wins,
        "losses": losses,
        "winrate": round(100 * wins / total, 1) if total else None,
        "hotStreak": entry.get("hotStreak", False),
    }


def load_match_cache():
    if MATCH_CACHE_PATH.exists():
        try:
            return json.loads(MATCH_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_match_cache(cache):
    MATCH_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def load_scrape_log():
    """The scrape log remembers, per Riot account, every match id we've
    already listed and what season_start that covers. It's what lets a
    re-run skip re-listing a friend's whole season and only ask Riot 'what's
    new since last time' — the matches_cache above avoids re-fetching match
    *details*, this avoids re-*listing* match ids in the first place."""
    if SCRAPE_LOG_PATH.exists():
        try:
            return json.loads(SCRAPE_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_scrape_log(log):
    SCRAPE_LOG_PATH.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def load_rank_history():
    """Riot's API only ever returns *current* rank — there's no historical
    endpoint — so the only way to chart rank over time is to snapshot it
    ourselves on every run and build up history locally. This means the
    "last 30 days" chart starts empty and fills in as you keep running
    fetch_data.py (ideally daily); it can't show rank changes from before
    you started running this tool."""
    if RANK_HISTORY_PATH.exists():
        try:
            return json.loads(RANK_HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def record_rank_snapshots(history, results, today_key):
    """Upsert one snapshot per (friend, queue) per day — re-running multiple
    times in a day overwrites today's snapshot rather than duplicating it."""
    by_key = {(h["label"], h["queue"], h["date"]): h for h in history}
    for r in results:
        for queue_key, entry in (("solo", r["ranked"].get("solo")), ("flex", r["ranked"].get("flex"))):
            if not entry or not entry.get("tier"):
                continue
            snap = {
                "date": today_key,
                "label": r["label"],
                "queue": queue_key,
                "tier": entry["tier"],
                "rank": entry.get("rank"),
                "leaguePoints": entry.get("leaguePoints", 0),
            }
            by_key[(r["label"], queue_key, today_key)] = snap
    merged = list(by_key.values())
    cutoff = (datetime.now() - timedelta(days=RANK_HISTORY_KEEP_DAYS)).strftime("%Y-%m-%d")
    merged = [h for h in merged if h["date"] >= cutoff]
    merged.sort(key=lambda h: (h["date"], h["label"], h["queue"]))
    return merged


def save_rank_history(history):
    RANK_HISTORY_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    config_path = Path(sys.argv[1] if len(sys.argv) > 1 else "config.json")
    if not config_path.exists():
        print(f"Config file not found: {config_path}\n"
              f"Copy config.example.json to config.json and fill in your API key + friends.")
        sys.exit(1)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    client = RiotClient(config["api_key"], config["platform"], config["routing"])
    match_count = config.get("match_count", 10)
    # This is a safety backstop, not a target — get_all_match_ids_since()
    # fetches every match since season_start regardless, up to this many.
    # 5000 is far beyond what even a very active player racks up across
    # solo/flex/normals/ARAM in one season; raise it in config.json only if
    # you have reason to expect more than that.
    max_season_matches = config.get("max_season_matches", 5000)

    season_start = config.get("season_start")
    if season_start:
        season_start_epoch = datetime.strptime(season_start, "%Y-%m-%d").timestamp()
        season_start_key = season_start
    else:
        # Riot's match API doesn't expose season boundaries, so without an
        # explicit season_start in config.json we fall back to 90 days back.
        # Set "season_start": "YYYY-MM-DD" in config.json to match the actual
        # season/split start date if you want true season-to-date stats.
        season_start_epoch = (datetime.now() - timedelta(days=90)).timestamp()
        season_start_key = datetime.fromtimestamp(season_start_epoch).strftime("%Y-%m-%d")
        print(f"No 'season_start' set in config.json — defaulting to the last 90 days "
              f"(since {season_start_key}). "
              f"Add \"season_start\": \"YYYY-MM-DD\" to config.json for true season-to-date stats.\n")

    match_cache = load_match_cache()
    scrape_log = load_scrape_log()

    results = []
    for friend in config["friends"]:
        try:
            summary = summarize_friend(
                client, friend["label"], friend["riot_id"], match_count,
                season_start_epoch, season_start_key, max_season_matches,
                match_cache, scrape_log,
            )
            if summary:
                results.append(summary)
        except Exception as e:
            print(f"  ! error fetching {friend.get('label')}: {e}")
        finally:
            # Save incrementally so a crash/interrupt partway through a big
            # first-time season pull doesn't lose already-fetched matches.
            save_match_cache(match_cache)
            save_scrape_log(scrape_log)

    today_key = datetime.now().strftime("%Y-%m-%d")
    rank_history = load_rank_history()
    rank_history = record_rank_snapshots(rank_history, results, today_key)
    save_rank_history(rank_history)
    tracking_since = min((h["date"] for h in rank_history), default=today_key)
    chart_cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    rank_history_30d = [h for h in rank_history if h["date"] >= chart_cutoff]

    # Peak rank uses the *full* history (not just the 30-day chart window)
    # so it reflects the best ever observed since tracking started, even if
    # that was months ago.
    peaks = compute_peaks(rank_history)
    for r in results:
        r["peakRank"] = {
            "solo": peaks.get((r["label"], "solo")),
            "flex": peaks.get((r["label"], "flex")),
        }

    # Champion icons: the dashboard builds icon URLs itself from a Data
    # Dragon CDN pattern, so all it needs from us is the patch version and
    # a display-name -> Data Dragon slug map (see get_champion_data() for
    # why the slug isn't just the name with spaces stripped).
    champ_data = get_champion_data()

    out = {
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "platform": config["platform"],
        "seasonStart": datetime.fromtimestamp(season_start_epoch).strftime("%Y-%m-%d"),
        "friends": results,
        "rankHistory": rank_history_30d,
        "rankTrackingSince": tracking_since,
        "ddragonVersion": champ_data.get("version"),
        "championIconMap": champ_data.get("byName", {}),
    }
    Path("data.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote data.json with {len(results)} friend(s). "
          f"Rank tracking has {len(rank_history)} snapshot(s) since {tracking_since}.")

    webhook_url = config.get("discord_webhook_url")
    if webhook_url:
        try:
            import post_discord
            post_discord.post(webhook_url, out)
            print("Posted highlights to Discord.")
        except Exception as e:
            print(f"  ! could not post to Discord ({e}) — check discord_webhook_url in config.json")


if __name__ == "__main__":
    main()
