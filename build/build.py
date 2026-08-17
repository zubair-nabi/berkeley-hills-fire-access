#!/usr/bin/env python3
"""Assemble index.html from the template and the harvested layer data.

The tool ships as one self-contained file so it can be served from GitHub Pages
with no build step at request time, opened from a USB stick, or printed. That
means the map data is inlined rather than fetched, which is why this script
exists: template.html carries a `/*__DATA__*/ null` placeholder and this
substitutes the data into it.

    python3 build/build.py

data.json is the raw harvest and is never modified. The clip below is applied on
every build so the rule stays visible in code rather than baked invisibly into a
data file someone would later have to reverse-engineer.
"""

import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PLACEHOLDER = "/*__DATA__*/ null"

# Metres per degree at Berkeley's latitude. The city spans about 6 km, so a local
# planar approximation is accurate to well under a metre and avoids a geodesic
# dependency for what is only ever a proximity test.
LAT = 37.87
MX = 111320 * math.cos(math.radians(LAT))
MY = 110574

# How close to the city line a termination has to be before it is treated as an
# artifact of the data being clipped there rather than a real dead end.
BOUNDARY_M = 25


def point_in_polygon(x, y, rings):
    """Even-odd ray cast across every ring, so holes subtract correctly."""
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
            if (y1 > y) != (y2 > y):
                if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                    inside = not inside
    return inside


def distance_to_boundary(x, y, rings):
    """Metres from a point to the nearest edge of the boundary polygon."""
    px, py = x * MX, y * MY
    best = float("inf")
    for ring in rings:
        n = len(ring)
        for i in range(n):
            ax, ay = ring[i][0] * MX, ring[i][1] * MY
            bx, by = ring[(i + 1) % n][0] * MX, ring[(i + 1) % n][1] * MY
            dx, dy = bx - ax, by - ay
            length = dx * dx + dy * dy
            t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
            best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def clip_dead_ends(data, boundary):
    """Drop terminations that fall outside the city limits.

    The City's street centreline layer is clipped at the city boundary, so any
    street continuing into Albany or Oakland appears to terminate there and the
    degree-1 test calls it a dead end. Shattuck, Solano and Marin all showed up
    this way, which is obviously wrong: they are through streets that run off
    the edge of the dataset.

    The distribution makes the cause unambiguous. Of the 59 terminations outside
    the boundary, 53 sit within 25 m of the line and 52 within 1 m. The three
    that fell in a hill fire zone (Ajax Ln, Chabolyn Ter, Vicente Rd) were each
    checked against OpenStreetMap, which is not clipped at the city line, and
    all three connect or continue at exactly the point Berkeley's data stops.

    So none of these are findings. A termination on the edge of a clipped
    dataset tells us nothing either way, and publishing "we cannot tell" as a
    dead-end marker is the guesswork this page promises it is not doing.

    The test is distance to the line, not inside-versus-outside. An earlier
    version used point-in-polygon and kept 38 terminations that were inside the
    boundary by under a metre: Ninth St, Second St, Alcatraz Ave, Roanoke Rd.
    Those are the same clipping artifact landing a metre on the Berkeley side.

    Both tests are needed. Distance alone re-admits the handful that sit properly
    inside another jurisdiction (Rugby Ave, 145 m out); inside-outside alone keeps
    the ones a metre on the Berkeley side of the line.
    """
    kept, dropped = [], []
    for r in data["deadEnds"]:
        x, y = r["x"], r["y"]
        artifact = (not point_in_polygon(x, y, boundary)
                    or distance_to_boundary(x, y, boundary) < BOUNDARY_M)
        (dropped if artifact else kept).append(r)

    data["deadEnds"] = kept
    data["meta"]["berkeleyNamedRoadDeadEnds"] = len(kept)
    data["meta"]["inHillZone2or3"] = sum(1 for r in kept if r.get("z") in (2, 3))
    data["meta"]["boundaryTerminationsDropped"] = len(dropped)
    return dropped


def main() -> int:
    template = (HERE / "template.html").read_text()

    if PLACEHOLDER not in template:
        print(f"error: {PLACEHOLDER!r} not found in template.html", file=sys.stderr)
        return 1

    # Parsed rather than pasted blind. A truncated data.json would otherwise
    # produce a page that loads, renders the fallback diagram, and looks merely
    # disappointing instead of broken.
    data = json.loads((HERE / "data.json").read_text())
    boundary = json.loads((HERE / "city_boundary.json").read_text())
    boundary = boundary["features"][0]["geometry"]["rings"]

    raw = len(data["deadEnds"])
    dropped = clip_dead_ends(data, boundary)

    out = template.replace(PLACEHOLDER, json.dumps(data, separators=(",", ":")))
    (ROOT / "index.html").write_text(out)

    print(f"dead ends  {raw} harvested  ->  {len(data['deadEnds'])} inside city limits "
          f"({len(dropped)} boundary terminations dropped)")
    print(f"           {data['meta']['inHillZone2or3']} in hill fire zone 2 or 3")
    print(f"wrote index.html  {len(out):,} bytes")
    for k, v in sorted((k, len(v)) for k, v in data.items() if isinstance(v, list)):
        print(f"  {k:<12} {v:>6,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
