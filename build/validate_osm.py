#!/usr/bin/env python3
"""Check the single-exit areas against OpenStreetMap, an independent survey.

    python3 build/validate_osm.py [-v]

The stability sweep in deadends.py proves the answer does not depend on its own
tuning. That is necessary and nowhere near sufficient: a derivation can be
perfectly stable and perfectly wrong. This is the other half. It takes each area
this project computed from the City's centreline and asks a different dataset,
surveyed by different people, whether that area really has one way out.

METHOD

Our areas are tested inside OSM's topology rather than by re-deriving areas from
OSM and comparing the two lists. Comparing derivations does not work: OSM splits
ways at different places, so the same physical cul-de-sac lands its articulation
point somewhere else and a naive comparison scores it a miss. Early attempts that
way reported 12 to 38 percent agreement, all of it measurement error.

So: project each area's geometry onto OSM, collect the OSM nodes it covers, and
count the places where an edge leaves that set. One place means confirmed.

WHAT COUNTS AS A WAY OUT

Public roads only. Service roads, driveways, parking aisles and fire tracks are
excluded. This is a judgement and it changes the answer a great deal, so it is
stated rather than buried: including service roads and tracks drops confirmation
from 93 percent to 41 percent. The case for excluding them is that this page is
read by a resident with a car during an evacuation, for whom a gated fire trail
is not a way out, and that the City's own street layer has no driveway class, so
excluding them keeps both datasets to the same definition.

TWO CORRECTIONS THAT ARE NOT FUDGES

Both were found by inspecting disagreements rather than by tuning for a number.

  Same-street crossings are ignored. Where our simplified geometry stops short of
  OSM's, the rest of the SAME street looks like the outside world. Panoramic Way
  showed three exits, two of which led to Panoramic Place and Dwight Place, which
  are inside the area. That is our coverage falling short, not a way out.

  One intersection is one exit. A junction digitised as several nodes was counted
  several times. Grayson St showed two exits 36 m apart, both onto Seventh St;
  Codornices Rd two 33 m apart, both onto Euclid Ave. Nodes within 60 m, or
  within 150 m and leading onto the same street, are one junction.
"""

import argparse
import collections
import gzip
import json
import math
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
LAT = 37.87
MX = 111320 * math.cos(math.radians(LAT))
MY = 110574

PUBLIC = {"motorway", "motorway_link", "trunk", "trunk_link", "primary",
          "primary_link", "secondary", "secondary_link", "tertiary",
          "tertiary_link", "unclassified", "residential", "living_street", "road"}

SUFFIX = {"STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "DRIVE": "DR",
          "COURT": "CT", "LANE": "LN", "PLACE": "PL", "CIRCLE": "CIR",
          "TERRACE": "TER", "BOULEVARD": "BLVD"}

COVER_M = 25.0     # how far from our centreline an OSM node still counts as ours
JUNCTION_M = 60.0  # nodes this close are one intersection
SAME_ST_M = 150.0  # further apart, but onto the same street, still one intersection


def norm(name):
    """Berkeley writes OAKRIDGE RD, OSM writes Oak Ridge Road. Spaces are dropped
    so the two agree, which one earlier version did not do and scored a false
    disagreement on Oakridge Rd."""
    words = re.sub(r"[^A-Za-z0-9 ]", " ", name).upper().split()
    return "".join(SUFFIX.get(w, w) for w in words)


def load_osm():
    with gzip.open(HERE / "osm_roads.json.gz", "rt") as fh:
        ways = json.load(fh)["elements"]
    adj = collections.defaultdict(set)
    pos, street = {}, collections.defaultdict(set)
    for w in ways:
        t = w.get("tags", {})
        if t.get("highway") not in PUBLIC or t.get("access") in ("private", "no"):
            continue
        name = norm(t.get("name") or "")
        for nid, p in zip(w["nodes"], w["geometry"]):
            pos[nid] = (p["lon"] * MX, p["lat"] * MY)
            if name:
                street[nid].add(name)
        for a, b in zip(w["nodes"], w["nodes"][1:]):
            adj[a].add(b)
            adj[b].add(a)
    return adj, pos, street


def exits_for(area, adj, pos, street, lookup):
    ours = {norm(n) for n in area["names"] if n}
    inside = set()
    for path in area["paths"]:
        for i in range(len(path) - 1):
            ax, ay = path[i][0] * MX, path[i][1] * MY
            bx, by = path[i + 1][0] * MX, path[i + 1][1] * MY
            steps = max(2, int(math.hypot(bx - ax, by - ay) // 10) + 1)
            for k in range(steps + 1):
                t = k / steps
                inside.update(lookup(ax + (bx - ax) * t, ay + (by - ay) * t, COVER_M))
    if len(inside) < 3:
        return None

    crossings = []
    for n in inside:
        out = set()
        for m in adj[n]:
            if m in inside or (street[m] & ours):
                continue
            out |= (street[m] or {"?"})
        if out:
            crossings.append((pos[n], out))

    clusters = []
    for (x, y), out in sorted(crossings):
        for c in clusters:
            d = math.hypot(x - c[0][0], y - c[0][1])
            if d <= JUNCTION_M or (d <= SAME_ST_M and (out & c[1])):
                c[1] |= out
                break
        else:
            clusters.append([(x, y), set(out)])
    return clusters


def run(verbose=False):
    areas = json.loads((HERE / "deadends.json").read_text())
    adj, pos, street = load_osm()

    cell = 60.0
    grid = collections.defaultdict(list)
    for n, (x, y) in pos.items():
        grid[(int(x // cell), int(y // cell))].append(n)

    def lookup(px, py, r):
        found, rr = [], int(r // cell) + 1
        cx, cy = int(px // cell), int(py // cell)
        for i in range(cx - rr, cx + rr + 1):
            for j in range(cy - rr, cy + rr + 1):
                for n in grid.get((i, j), ()):
                    x, y = pos[n]
                    if math.hypot(x - px, y - py) <= r:
                        found.append(n)
        return found

    tally = collections.Counter()
    disputed = []
    marks = {}
    for a in areas:
        key = f"{a['exit'][0]:.5f},{a['exit'][1]:.5f}"
        clusters = exits_for(a, adj, pos, street, lookup)
        if clusters is None:
            tally["uncheckable"] += 1
            marks[key] = {"v": "none"}
            continue
        k = len(clusters)
        if k == 1:
            tally["confirmed"] += 1
            marks[key] = {"v": "ok"}
        elif k == 0:
            tally["isolated"] += 1
            marks[key] = {"v": "none"}
        else:
            tally["disputed"] += 1
            outs = [sorted(c[1])[:2] for c in clusters]
            marks[key] = {"v": "disputed", "n": k}
            disputed.append((a["metres"], ", ".join(a["names"][:2]), outs))

    (HERE / "verdicts.json").write_text(json.dumps(marks, separators=(",", ":")))
    checkable = tally["confirmed"] + tally["disputed"]
    rate = tally["confirmed"] / checkable if checkable else 0.0
    print(f"{len(areas)} areas checked against OpenStreetMap public roads")
    print(f"   confirmed single exit  {tally['confirmed']:>4}")
    print(f"   disputed by OSM        {tally['disputed']:>4}")
    print(f"   isolated in OSM        {tally['isolated']:>4}")
    print(f"   not covered by OSM     {tally['uncheckable']:>4}   "
          f"(campus, marina and other roads OSM classes as service)")
    print(f"\n   {rate:.0%} of the {checkable} checkable areas confirmed")
    if verbose:
        print("\ndisputed:")
        for m, n, outs in sorted(disputed, reverse=True):
            print(f"   {m:>5} m  {n:<28} -> {outs}")
    return rate, tally, disputed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    rate, _tally, _d = run(args.verbose)
    return 0 if rate >= 0.90 else 1


if __name__ == "__main__":
    raise SystemExit(main())
