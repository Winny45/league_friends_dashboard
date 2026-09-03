# Running the hourly update on GitHub instead of a PC

`.github/workflows/publish.yml` fetches from Riot, rebuilds the page and
publishes it, once an hour, with nothing running on anybody's machine. It
needs five secrets and one private repo before it will work.

## 1. A key that does not expire

A **development** key from developer.riotgames.com dies 24 hours after it is
issued, so an unattended schedule fails every day regardless of where it runs.
Apply for a **Personal API Key** on the same site: free, granted on request,
and it does not expire. Nothing below matters without one.

## 2. A private repo for the rank history

`rank_history.json` is the only irreplaceable file in this project. Riot does
not expose past ranks, so every snapshot in it was taken by a run of
`fetch_data.py`, and losing it resets the entire Rank progress tab. It also
names your friends, so it cannot live in this repo, which is public.

Make a new **private** repo, then seed it with the two files a rehearsal has
already prepared in `.state/`:

- `rank_history.json`
- `config.json` with `"api_key": ""` (the key comes from a secret, not a file)

## 3. A Vercel token

Create one at vercel.com/account/tokens. A **project-scoped** token (they
start `vcp_`) is enough and is the better choice: it can deploy this project
and nothing else. It cannot read `/v2/user` or list teams, so do not be
alarmed if a token checker written against those endpoints calls it invalid.

The same token is what `update_and_publish.ps1` reads from `config.json` as
`vercel_token`, so one token covers both the local task and this workflow.
Without it the CLI falls back to its saved interactive login, which expires
and then blocks forever on a device-code prompt that no scheduled run can
answer.

The org and project ids are in the static folder's `.vercel/project.json`:

```bash
cat ../league_dashboard_static/.vercel/project.json
```

## 4. The secrets

In this repo, under Settings, Secrets and variables, Actions:

| secret | value |
|---|---|
| `RIOT_API_KEY` | your Personal API Key |
| `STATE_REPO` | `yourname/your-private-state-repo` |
| `STATE_REPO_SSH_KEY` | the private half of an SSH deploy key with write access on that repo (see below) |
| `VERCEL_TOKEN` | the token from step 3 |
| `VERCEL_ORG_ID` | `orgId` from `project.json` |
| `VERCEL_PROJECT_ID` | `projectId` from `project.json` |

### Why a deploy key and not a token

A personal access token belongs to the account, and unless it is a
fine-grained one scoped by hand it can reach every repo the account owns. An
SSH deploy key is attached to one repository:

```bash
ssh-keygen -t ed25519 -N "" -C "league-dashboard-actions" -f state_key
gh repo deploy-key add state_key.pub --repo <you>/<state repo>     --title "GitHub Actions hourly publish" --allow-write
gh secret set STATE_REPO_SSH_KEY --repo <you>/league_friends_dashboard < state_key
rm state_key state_key.pub
```

Revoking it is deleting that one key, and it can write to nothing else.

## 5. Run it once by hand

Actions tab, "Publish dashboard", "Run workflow". Watch it go green before
trusting the schedule.

## 6. An external trigger, because GitHub's cron is not dependable

GitHub's scheduler is a queue, not a clock, and on this repo it has been far
worse than late. An hourly schedule produced three runs in eight hours. A
fifteen-minute one produced none in an hour, with the workflow active and the
cron correct on the default branch. It is best-effort and there is no setting
that changes that.

The fix is to have something else ask. Any cron service that can make an HTTP
request will do; cron-job.org is free and enough.

**The request** (verified against the live repo, which answers `204 No
Content` and starts a run):

```
POST https://api.github.com/repos/<you>/league_friends_dashboard/actions/workflows/publish.yml/dispatches

Accept:               application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
Authorization:        Bearer <your token>
Content-Type:         application/json

{"ref":"main"}
```

Every 15 minutes. Note there is no `force` in that body on purpose: the gate
then applies, so three pings in four cost about twenty seconds each and
change nothing, and the fourth publishes.

**The token.** A fine-grained personal access token, and scope it down,
because it is going to sit in somebody else's web form:

- Repository access: **only** `league_friends_dashboard`
- Permissions: **Actions: Read and write**, nothing else
- Expiry: as long as you are offered, or none

That token can start this one workflow in this one repo. It cannot read your
code, your other repositories, or your account.

**Check it worked.** The Actions tab should show runs appearing every 15
minutes, most of them finishing in under half a minute with the publish job
skipped. If they are all doing full publishes, the gate is not being reached
and something is passing `force`.

## Things worth knowing

**The schedule is approximate.** GitHub's cron is a queue, not a clock. Runs
commonly land 5 to 20 minutes late and can be dropped entirely when the
service is busy. If you need it to fire at exactly :00, this is the wrong
host and the Windows task was better at it.

**GitHub disables scheduled workflows after 60 days with no pushes** to the
repo. A commit of any kind resets that clock.

**Two kinds of state, kept apart on purpose.** `rank_history.json` is
irreplaceable and tiny, so it is committed to the private repo with real
history. `matches_cache.json`, `scrape_log.json` and `champions_cache.json`
total about 1.4MB, change every hour, and can all be rebuilt by fetching
again, so they live in the Actions cache: committing them hourly would add
gigabytes a year to a history nobody will read. If that cache is ever evicted
the next run is slow and nothing is lost.

**Nothing fetched is ever committed here.** `data.json`, `dashboard.html` and
`og.png` exist only inside the runner and go straight to Vercel. The one step
that commits names its single file explicitly rather than using `git add -A`.

**The Windows task is disabled, not deleted.** Leaving both running is worse
than it sounds: they keep separate rank histories, the task writing the local
`rank_history.json` and the workflow writing the state repo's. They would
drift apart and then take turns overwriting the published page with their own
version of the past.

```powershell
Enable-ScheduledTask  -TaskName "LeagueFriendsDashboard-AutoUpdate"   # back to the PC
Disable-ScheduledTask -TaskName "LeagueFriendsDashboard-AutoUpdate"   # back to Actions
```

If you do switch back, copy `rank_history.json` out of the state repo first,
or the local copy resumes from wherever it left off and the gap is permanent:
Riot cannot tell you what rank anybody was last Tuesday.
