"""Turn the map drawing into the lookup table the statistics use.

    python tools/build_rift_zones.py

Reads analysis_assets/map/rift-zones.svg, where every area of Summoner's Rift
is its own <path> with an id, and writes rift_zones.py: one character per
64-unit square of the map saying which area it is in. The page draws the same
paths, so a takedown counted as "top river" is one that is drawn on the top
river. Run it again only if the drawing changes.

Needs Pillow and numpy, which the build itself does not: the output is
committed so that publishing never depends on either.
"""
import re
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "analysis_assets" / "map" / "rift-zones.svg"
OUT = ROOT / "rift_zones.py"
S = 1200                      # the drawing's own viewBox
# Where the drawing sits in game coordinates. The same figures the page uses
# to place it, so the two cannot disagree; see MAP in a1_core.js.
X0, X1, Y0, Y1 = -120, 14870, -120, 14980
CELL = 64                     # game_store.POS_SCALE
SIZE = 233                    # stored coordinates run 0..232

# path id -> code. Lower case is jungle and river, upper case lanes, digits bases.
CODES = {
    "toplane": "T", "midlane": "M", "botlane": "B",
    "topriver": "u", "botriver": "l",
    "bluejungle": "j", "redjungle": "k",
    "blue_baselight": "1", "blue_basemid": "1", "blue_basedark": "1", "bluecircle": "1",
    "red_baselight": "2", "red_basemid": "2", "red_basedark": "2", "redcircle": "2",
    "basepath": "p",          # split into j / k by side below
}


def subpaths(d):
    """Each closed outline of a potrace path as a list of points, curves
    flattened. The files only use absolute M, L, C and Z."""
    out, cur = [], []
    pos = (0.0, 0.0)
    for cmd, args in re.findall(r"([MLCZ])([^MLCZ]*)", d):
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", args)]
        if cmd == "M":
            if cur:
                out.append(cur)
            pos = (nums[0], nums[1])
            cur = [pos]
        elif cmd == "L":
            for i in range(0, len(nums), 2):
                pos = (nums[i], nums[i + 1])
                cur.append(pos)
        elif cmd == "C":
            for i in range(0, len(nums), 6):
                p0, p1, p2, p3 = pos, (nums[i], nums[i + 1]), (nums[i + 2], nums[i + 3]), (nums[i + 4], nums[i + 5])
                for k in range(1, 9):
                    t = k / 8.0
                    a = (1 - t) ** 3
                    b = 3 * t * (1 - t) ** 2
                    c = 3 * t * t * (1 - t)
                    e = t ** 3
                    cur.append((a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0],
                                a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1]))
                pos = p3
        elif cmd == "Z":
            if cur:
                out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [sp for sp in out if len(sp) >= 3]


def mask_of(d):
    """Even-odd fill, which is what the files ask for: holes are outlines
    drawn inside outlines."""
    m = np.zeros((S, S), dtype=bool)
    for sp in subpaths(d):
        im = Image.new("1", (S, S), 0)
        ImageDraw.Draw(im).polygon(sp, fill=1)
        m ^= np.asarray(im, dtype=bool)
    return m


def main():
    svg = SVG.read_text(encoding="utf-8")
    label = np.full((S, S), ".", dtype="<U1")
    # Later ids win where shapes overlap, so bases are painted over lanes.
    order = ["bluejungle", "redjungle", "topriver", "botriver", "toplane", "botlane", "midlane", "basepath",
             "blue_basedark", "blue_basemid", "blue_baselight", "red_basedark", "red_basemid", "red_baselight",
             "bluecircle", "redcircle"]
    for pid in order:
        m = re.search(r'<path[^>]*id="%s"[^>]*\sd="([^"]+)"' % pid, svg) or \
            re.search(r'<path[^>]*\sd="([^"]+)"[^>]*id="%s"' % pid, svg)
        if not m:
            sys.exit(f"no path with id {pid}")
        label[mask_of(m.group(1))] = CODES[pid]
    vv, uu = np.mgrid[0:S, 0:S]
    path = label == "p"
    # The curved path outside each base counts as that side's jungle. Blue's
    # half is below the river, which runs from the top left to the bottom right.
    label[path & (vv > uu)] = "j"
    label[path & (vv <= uu)] = "k"

    grid = [["."] * SIZE for _ in range(SIZE)]
    for yq in range(SIZE):
        for xq in range(SIZE):
            x, y = xq * CELL + CELL / 2, yq * CELL + CELL / 2
            u = int((x - X0) / (X1 - X0) * S)
            v = int((Y1 - y) / (Y1 - Y0) * S)
            if 0 <= u < S and 0 <= v < S:
                grid[yq][xq] = str(label[v, u])
    # Walls belong to nobody in the drawing, but people are recorded inside
    # them all the time: mid-dash, or a few units off through rounding. Each
    # empty square takes the area of the nearest square that has one.
    walls = sum(row.count(".") for row in grid)
    queue = deque((x, y) for y in range(SIZE) for x in range(SIZE) if grid[y][x] != ".")
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < SIZE and 0 <= ny < SIZE and grid[ny][nx] == ".":
                grid[ny][nx] = grid[y][x]
                queue.append((nx, ny))
    rows = ["".join(r) for r in grid]
    body = ",\n".join(f'    "{r}"' for r in rows)
    OUT.write_text(f'''"""Which area of the map a stored position is in.

GENERATED by tools/build_rift_zones.py from analysis_assets/map/rift-zones.svg.
Do not edit by hand: change the drawing and run the tool again.

GRID[y][x] for stored coordinates (map units // 64), y counted from the
bottom of the map as Riot counts it.
    T M B   top, mid and bot lane
    u l     the river above and below mid (baron side, dragon side)
    j k     blue team's jungle, red team's jungle
    1 2     blue base, red base
"""

SIZE = {SIZE}

GRID = (
{body},
)

_NAME = {{"T": "top", "M": "mid", "B": "bot", "u": "river_top", "l": "river_bot",
         "j": "jungle_blue", "k": "jungle_red", "1": "base_blue", "2": "base_red"}}


def raw_zone(xq, yq):
    """The area as drawn: one of top, mid, bot, river_top, river_bot,
    jungle_blue, jungle_red, base_blue, base_red."""
    x = 0 if xq < 0 else SIZE - 1 if xq >= SIZE else int(xq)
    y = 0 if yq < 0 else SIZE - 1 if yq >= SIZE else int(yq)
    return _NAME[GRID[y][x]]
''', encoding="utf-8", newline="\n")
    print(f"wrote {OUT.name}: {SIZE}x{SIZE}, {walls} squares were walls and took a neighbour's area")


if __name__ == "__main__":
    main()
