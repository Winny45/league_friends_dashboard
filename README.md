# League Friends Dashboard

A small local app that pulls your friends' League of Legends ranked stats,
season-long match history, and champion mastery from the **official Riot
Games API**, and renders it as a single-page dashboard you open in your
browser, organized into tabs (Overview, Rank progress, Duo synergy, Friends)
so it doesn't turn into one giant scroll — a leaderboard with week-over-week
trend arrows, fun auto-generated "highlights" (MVP performance, int alerts,
win streaks, busiest day, and more), a duo synergy table, and a card per
friend (pick who to view with the pill buttons) with rank, winrate, weekly
playtime, champion icons throughout, champion/role breakdowns, a "nemesis"
callout, and match history down to the date and time each game started.
Includes a dark mode toggle, a CSV export, and can update itself
automatically on a schedule (see "Auto-update"). Remake games
(early-surrendered, no stat impact) are detected and excluded from
everything automatically.

Note: op.gg/u.gg/League of Graphs don't offer a public API, and scraping
their pages directly breaks their terms of service and tends to get blocked.
Riot's own API is free, official, and gives the same underlying data (it's
what those sites are built on), so this app talks to Riot directly.

## What's in this folder

- `config.example.json` — template for your API key + friends list
- `fetch_data.py` — calls the Riot API and writes `data.json`
- `generate_dashboard.py` — turns `data.json` into `dashboard.html`
- `data.example.json` — **a fully synthetic sample dataset** (fictional
  players, fabricated matches) so you can see what the dashboard looks like
  before doing any setup:

  ```
  python3 generate_dashboard.py data.example.json demo.html
  ```

  Then open `demo.html`. Your own `data.json` and `dashboard.html` are
  git-ignored, since they contain real account data.
- `matches_cache.json` — created automatically after your first real run; a
  local cache of every match's stats already fetched, so a game already
  known never gets its full detail re-downloaded. Safe to delete if you
  ever want to force a full refetch (it'll just be slower next run).
- `scrape_log.json` — created automatically; remembers, per friend, every
  match id already seen and what `season_start` that covers. This is what
  makes a re-run fast: instead of re-listing a friend's entire season of
  match ids every time, it asks Riot "what's new since I last checked" and
  usually only needs one API call. It automatically falls back to a full
  re-list if you move `season_start` earlier (so there might be older games
  it's never seen). Safe to delete to force a full re-list; you won't lose
  any data since `matches_cache.json` still has the actual match stats.
- `rank_history.json` — created automatically; one rank snapshot per friend
  per day, going back as far as you've been running this tool. Powers the
  30-day rank progress chart. Don't delete this one unless you want to lose
  your rank history — it can't be rebuilt from Riot's API after the fact.
- `update_dashboard.bat` — double-click to refresh everything in one go
  (runs `fetch_data.py` then `generate_dashboard.py`). Also what the
  auto-update task below runs for you.
- `setup_auto_update.ps1` — one-time script that sets up Windows to run
  `update_dashboard.bat` automatically every day. See "Auto-update" below.
- `post_discord.py` — optional; posts a highlights summary to a Discord
  webhook. Runs automatically at the end of `fetch_data.py` if you set
  `discord_webhook_url` in `config.json`; can also be run by hand.

## 1. Get a free Riot API key

1. Go to https://developer.riotgames.com and log in with (or create) a Riot
   account.
2. Click **"Generate API Key"** on the developer dashboard — this gives you
   a **development key** for free, no application needed.
3. Copy the key (looks like `RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`).

**Important:** development keys expire every **24 hours**. You'll need to
grab a fresh one and paste it into `config.json` each day you want to
refresh your friends' stats. (If you want something permanent, Riot offers
a Personal API Key with higher limits and no expiry — same dashboard, look
for "Register Product" — but the dev key is enough to run this yourself.)

> **Keep your key and your friends' data out of git.** `config.json` holds
> your API key and everyone's real Riot IDs, and `data.json`,
> `dashboard.html`, `matches_cache.json`, `scrape_log.json` and
> `rank_history.json` are all built from real accounts (Riot IDs, puuids,
> full match history). All of them are listed in `.gitignore` — don't
> force-add them, and don't paste a real `config.json` into an issue or PR.

## 2. Set up your config

Copy the example config and edit it:

```
cp config.example.json config.json
```

Open `config.json` and fill in:

- `api_key` — the key from step 1
- `platform` / `routing` — for EUW use `"euw1"` / `"europe"` (already set).
- `site_url` — public URL of the deployed dashboard, e.g.
  `"https://your-site.vercel.app"`. Only used for the link-preview card:
  Open Graph requires absolute image URLs, so leaving this empty simply
  omits the share tags rather than emitting ones that will not resolve.
  Other regions:
  | Region | platform | routing |
  |---|---|---|
  | EUW | euw1 | europe |
  | EUNE | eun1 | europe |
  | NA | na1 | americas |
  | BR | br1 | americas |
  | LAN/LAS | la1/la2 | americas |
  | KR | kr | asia |
  | JP | jp1 | asia |
  | OCE | oc1 | sea |
- `friends` — each friend's **Riot ID**, i.e. the `Name#Tag` shown under
  their name in-game or on op.gg (not just their old summoner name — Riot
  IDs are required by the current API). Give each one a `label` (whatever
  you want to call them on the dashboard).
- `season_start` — the date (`"YYYY-MM-DD"`) to start pulling match history
  from, for the "games this season" / weekly playtime / busiest-day stats.
  Riot's API doesn't expose official season/split boundaries, so set this to
  whatever date you consider "the season" started (check the in-game client
  or a site like leagueoflegends.com for the current split's start date).
  If you leave it out, it defaults to the last 90 days.
- `max_season_matches` — **not a target, just a safety backstop** (default
  5000). By default `fetch_data.py` pulls *every* match since `season_start`
  for each friend, across every queue — if someone played 400 solo/duo games
  and 200 flex games this season, you get all 600, not a sample. This
  setting only exists to stop a runaway fetch if `season_start` is set
  absurdly far back; 5000 is well beyond what even a very active player
  racks up in one season, so you shouldn't need to touch it.
- `discord_webhook_url` — optional. Paste a Discord webhook URL here to
  have `fetch_data.py` automatically post a highlights summary to your
  server's channel at the end of every run. Leave it as `""` to skip this.
  See "Post updates to Discord" below for how to get a webhook URL.

### Patch notes

`patch_notes.json` drives the ✨ button in the header. Newest entry first:

```json
{ "date": "2026-08-28", "title": "Short headline",
  "items": [ { "type": "added", "text": "What a player can now do." } ] }
```

`type` is `added`, `fixed` or `improved`. The newest entry's `date` doubles as
the read marker for the unread dot, so a new entry needs a new date or
returning visitors will not see one. The file is optional — without it the
button is not rendered at all.


## 3. Run it

You need Python 3 (no extra packages required — it only uses the standard
library).

```
python3 fetch_data.py
python3 generate_dashboard.py
```

Then open `dashboard.html` in your browser (double-click it, or run
`open dashboard.html` / `xdg-open dashboard.html`).

Re-run both commands any time you want to refresh the stats (remembering
to refresh your `api_key` if it's been more than 24 hours), or use
`update_dashboard.bat` to run both in one double-click. See "Auto-update"
below to have this happen on its own.

## Auto-update (no more running it by hand)

`update_dashboard.bat` runs both scripts for you — double-click it any
time you want a manual refresh. To have Windows do that automatically on a
schedule instead:

1. Open this folder in File Explorer, right-click **`setup_auto_update.ps1`**,
   and choose **"Run with PowerShell"**.
   - If Windows says running scripts is disabled, open PowerShell normally
     (not as admin) and run this once: `Set-ExecutionPolicy -Scope
     CurrentUser RemoteSigned` — then try again.
2. It'll ask what time of day to refresh (default 9am). Type a time or just
   press Enter.
3. That's it — Windows Task Scheduler now runs `update_dashboard.bat` every
   day at that time, whether or not you're at your PC (as long as it's on).
   Just reopen `dashboard.html` (or refresh the tab) after that time to see
   the update.

**The catch: a free development API key expires every 24 hours**, so an
unattended scheduled run will start failing the day after you set it up
unless the key gets refreshed too. Two ways to handle this:

- **Best option — get a Personal API Key.** On the [Riot developer
  dashboard](https://developer.riotgames.com), look for "Register Product"
  and apply for a Personal API Key. It's still free, approval is usually
  quick, and it doesn't expire, so once it's in `config.json` the scheduled
  task just works indefinitely.
- **Or, keep using a dev key and refresh it yourself once a day** before
  the scheduled time — copy the new key from the developer portal into
  `config.json`. This defeats a lot of the point of automating it, so the
  Personal key is worth applying for if you want this to be truly hands-off.

To turn off auto-update later, open PowerShell and run:
`Unregister-ScheduledTask -TaskName 'LeagueFriendsDashboard-AutoUpdate' -Confirm:$false`
— or search "Task Scheduler" in the Start menu, find
`LeagueFriendsDashboard-AutoUpdate`, and delete it there.

## Post updates to Discord

To have highlights posted automatically to a Discord channel every time
`fetch_data.py` runs (including on the auto-update schedule):

1. In Discord, open the channel you want updates in -> **Edit Channel** ->
   **Integrations** -> **Webhooks** -> **New Webhook** -> **Copy Webhook URL**.
2. Paste that URL into `discord_webhook_url` in `config.json`.
3. That's it — the next `fetch_data.py` run (or `update_dashboard.bat`, or
   the scheduled task) posts a short summary: the current Solo/Duo leader
   and the top few highlights.

You can also run it by hand any time against the current `data.json`:
`python3 post_discord.py data.json <webhook-url>`.

## What it shows

- **Tabs** — the page is split into four tabs (Overview, Rank progress, Duo
  synergy, Friends) instead of one long scroll. Overview has the
  highlights, this-week summary, and leaderboard; Friends shows one
  friend's full card at a time, picked with the pill buttons at the top of
  that tab. Clicking a friend's name in the leaderboard jumps straight to
  their card in the Friends tab.
- **Champion icons** — shown next to champion names throughout (match
  tables, top champions, champion breakdown, the nemesis callout) using
  Riot's public Data Dragon CDN.
- **Rank tier icons** — the little tier emblem (the same crest shown
  in-client) shown next to rank text on the leaderboard, per-friend cards,
  and the rank chart's current-standings row and line labels. These come
  from Community Dragon, a well-established community-run mirror of
  League's game assets (Riot's own Data Dragon doesn't host rank emblems,
  only champion/item art) — unofficial, so if Riot ever changes the asset
  layout these could stop loading, but they'll just quietly go blank
  rather than break anything (see below).
  - Both champion and rank icons load directly from those CDNs — they're
    not downloaded or embedded — so `dashboard.html` needs an internet
    connection at the moment you *open* it (unrelated to whether
    `fetch_data.py` had one when it ran). If any icon can't load for any
    reason (no connection, an unusual champion name, a moved asset) it
    just quietly stays blank instead of showing a broken-image glyph, so
    nothing ever looks broken either way.
- **Rank progress chart** — a 30-day line chart comparing everyone's Ranked
  Solo/Duo standing over time, color-coded per friend, with hover tooltips,
  a table view, and LP gains/losses shown throughout: hovering a point (or
  opening the table) shows the LP change since the previous snapshot, and
  each line's end point shows its net change over the visible window —
  e.g. "+156 LP (30d)". A promotion or demotion shows as "Platinum I →
  Diamond IV" instead of a raw LP number, since LP resets on promotion and a
  naive subtraction across one would misreport a huge swing that didn't
  really happen. Above the chart, a row of **current standings** chips
  (rank icon + name + tier + LP, color-matched to each friend's line) gives
  an always-legible snapshot of where everyone stands right now — useful
  when several friends are close in rank and the chart itself gets busy
  with overlapping lines/labels. The chart also grows taller automatically
  as more friends are on it, so a bigger group gets more room for its
  labels instead of everything compressing into the same fixed height.
  **Important:** Riot's API only ever returns your *current*
  rank — there's no historical endpoint — so this chart (LP deltas
  included) is built from local snapshots this tool takes each time you run
  `fetch_data.py`. It starts empty (or as a single dot) and fills in day by
  day, so it's most useful if you run `fetch_data.py` regularly (e.g. once a
  day) rather than only when you feel like checking in. Snapshots are
  stored in `rank_history.json`.
  - **If LP/rank changes don't seem to be showing up:** this is almost
    always because there's only one snapshot on record so far — with a
    single data point there's nothing to compare against yet, so no delta
    can be shown (you'll see a banner on the chart saying tracking just
    started). A snapshot is taken every time you run `fetch_data.py`, once
    per day per friend, so the fix is simply running it regularly — which
    is exactly what "Auto-update" above sets up for you. Rank changes
    within the *same day* (e.g. climbing 3 games in an evening) won't show
    as separate points either, since it's one snapshot per friend per day,
    not per game.
  You can click a friend's name in the chart legend to show/hide just their
  line, which helps once the group gets big enough that the chart feels
  crowded.
- **This week at a glance** — a compact panel with the week's top
  highlight, who's played the most, and who's climbed the most LP in the
  last 7 days. Only appears once there's enough data to say something.
- **Leaderboard** — all friends ranked by Solo/Duo tier, division, and LP,
  with a 7-day trend arrow (▲/▼ and the LP or tier change) once there's
  enough rank history to compare against.
- **Duo synergy** — for any pair of friends who've been teammates in the
  same ranked game at least twice this season, their combined winrate
  playing together. Detected automatically from shared match IDs — no
  extra setup needed.
- **Highlights** — fun, auto-generated call-outs computed from everyone's
  games: MVP performance, a flawless "Untouchable" game, "Int alert" for a
  rough loss, farm/assist records, current win/loss streaks ("On a heater" /
  "Tilt patrol"), who's been most active this week, the single busiest day
  of the season, biggest hit in a single game ("Damage dealer"), fastest
  ("Speed run") and longest ("The long game") ranked matches, who's played
  the most ranked games this season ("Season grinder"), and a scrappy win
  despite a rough scoreline ("Comeback kid"). Each only appears if someone's
  actually done something notable for it.
- **Per-friend card** — Solo and Flex rank with winrate bars, a peak-rank
  note when this season's best beats the current rank, a "Fresh" badge for
  low LP in the current division, a win/loss "form" strip, a "nemesis"
  callout (the enemy champion that's beaten them most), top 3 champions by
  mastery, and season stat tiles for weekly playtime, busiest day, total
  games/hours, and champion pool size. Three expandable sections dig
  deeper: recent match detail (date/time, KDA, CS/min, queue, length),
  a full champion-by-champion winrate breakdown, and a role (lane)
  breakdown.
- **Export CSV** — the button in the top-right downloads every friend's
  season match history as a CSV, if you want to pivot or chart it yourself
  in a spreadsheet.
- **Remake filtering** — Riot flags any game that ended in an early
  surrender (someone didn't connect, game auto-ends around 3-5 min) as a
  remake with no stat impact. This tool detects that flag and excludes
  those games from every stat, chart, and highlight automatically — they
  never should have counted as a real win/loss and now they don't.

## Notes & limits

- **The first season pull takes a while, and scales with how much your
  friends actually play.** Getting season-long history means one Riot API
  call per match (there's no bulk endpoint) — `fetch_data.py` fetches
  *everything* since `season_start`, so a friend with 600 games this season
  costs 600 calls, not a truncated sample. Expect anywhere from several
  minutes to well over an hour on the first run, depending on how many
  friends you have and how much they've played. `fetch_data.py` prints
  progress as it goes so you can see it's working.
- **After that, it's fast — really fast.** It's not just that already-seen
  matches skip re-fetching (`matches_cache.json`); `scrape_log.json` means
  a re-run doesn't even re-*ask* Riot for a friend's whole season of match
  ids anymore, just "what's new since I last checked." A daily refresh
  with nobody having played usually costs one small API call per friend
  and finishes in a couple seconds; if they've played since, it only
  fetches those new games.
- Development API keys are rate-limited (~20 requests/second, 100 per 2
  minutes) — `fetch_data.py` paces its requests to stay under that
  automatically; that pacing is most of why the first pull is slow.
- If a first pull is taking too long, set `season_start` closer to today —
  that's the one setting that actually shrinks how much gets fetched.
- **Only ranked games count.** Match history, weekly playtime, busiest-day,
  and Highlights are all built from Ranked Solo/Duo and Ranked Flex only
  (plus the long-retired "Ranked 5s" team queue, included just in case any
  old data ever carries it). Normals, ARAM, Arena, etc. are filtered out by
  Riot's API itself before this tool ever sees them — they don't cost an
  API call and never show up anywhere in the dashboard.
- This project isn't endorsed by or affiliated with Riot Games.
