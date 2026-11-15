"""Union the game store with whatever is on the cache branch right now.

    python ci/merge_games.py <checkout> <local games dir> <out games dir>

The publish job clones the cache branch when it starts and force-pushes its
own snapshot when it finishes. Anything that reached the branch in between
was therefore thrown away: a second machine filling the store, or a run that
overlapped this one. Both sides then spent their next hour re-fetching games
the other already had.

This re-reads the branch at save time and keeps the better of the two records
for every game, so the two accumulate instead of taking turns to win. It is
deliberately forgiving: a branch that cannot be read at all leaves the local
store exactly as it is, because losing an hour of fetching is better than
failing a publish over it.

"Better" is only ever more of the same game, never a different one:
    - the higher record version wins (see game_store.RECORD_VERSION)
    - a rank reading is carried across to whichever side lacks one
so the result is at least as complete as either input.
"""

import json
import subprocess
import sys
from pathlib import Path


def read_ref(checkout, path):
    """One file from the tip of the branch, or None if it is not there."""
    try:
        out = subprocess.run(["git", "show", f"FETCH_HEAD:{path}"], cwd=checkout,
                             capture_output=True, text=True, encoding="utf-8")
        if out.returncode:
            return None
        return json.loads(out.stdout)
    except (OSError, ValueError):
        return None


def better(a, b):
    """The record to keep out of two for the same game."""
    if a is None:
        return b
    if b is None:
        return a
    keep, other = (a, b) if a.get("pv", 1) >= b.get("pv", 1) else (b, a)
    if "rk" not in keep and "rk" in other:
        keep = dict(keep)
        keep["rk"] = other["rk"]
        keep["rkt"] = other.get("rkt")
    return keep


def merge_shard(mine, theirs):
    a = (mine or {}).get("games") or {}
    b = (theirs or {}).get("games") or {}
    games = {k: better(a.get(k), b.get(k)) for k in sorted(set(a) | set(b))}
    return {"v": 1, "games": games}, len(games), sum(1 for g in games.values() if g.get("pv", 1) >= 2), \
        sum(1 for g in games.values() if "rk" in g)


def main(checkout, local_dir, out_dir):
    checkout, local_dir, out_dir = Path(checkout), Path(local_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Fetch without checking out: the branch is an orphan commit each time, so
    # there is nothing to merge in the git sense, only files to read.
    fetched = subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", "cache"],
                             cwd=checkout, capture_output=True, text=True)
    if fetched.returncode:
        print(f"  ! could not re-read the cache branch ({fetched.stderr.strip()[:120]}); "
              f"saving this run's store as it is.")

    names = sorted({p.name for p in local_dir.glob("*.json")} |
                   {p.name for p in (checkout / "games").glob("*.json")})
    total = v2 = ranked = added = 0
    for name in names:
        mine = None
        if (local_dir / name).exists():
            try:
                mine = json.loads((local_dir / name).read_text(encoding="utf-8"))
            except ValueError:
                print(f"  ! {name} in this run's store is unreadable; taking the branch's copy.")
        theirs = None if fetched.returncode else read_ref(checkout, f"games/{name}")
        if name == "_skip.json":
            merged = dict(theirs or {})
            merged.update(mine or {})
        elif name == "_ranks.json":
            merged = dict(theirs or {})
            for pu, row in (mine or {}).items():
                if pu not in merged or merged[pu][2] < row[2]:
                    merged[pu] = row
        else:
            before = len((mine or {}).get("games") or {})
            merged, n, got_v2, got_rk = merge_shard(mine, theirs)
            total += n
            v2 += got_v2
            ranked += got_rk
            added += n - before
        (out_dir / name).write_text(json.dumps(merged, separators=(",", ":"), ensure_ascii=False),
                                    encoding="utf-8")
    print(f"Game store merged with the branch: {total} games, {v2} on the current record, "
          f"{ranked} with ranks ({added} picked up from the branch).")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
