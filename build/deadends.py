#!/usr/bin/env python3
"""Derive single-exit areas from the street network.

    python3 build/deadends.py [--sweep]

Reads build/streets_raw.json, writes build/deadends.json.

WHAT IS BEING COMPUTED, AND WHY IT IS NOT "DEAD ENDS"

The page's claim is "everyone on your street leaves the same way you do". That is
not the same as a street with one end, and counting degree-1 nodes gets it wrong
in both directions.

It over-counts. A cul-de-sac drawn with a turning circle is a loop, so it has no
degree-1 node at all and goes missing. One physical cul-de-sac digitised as three
stubs counts three times; Arcade Ln did exactly that.

It under-counts. A whole neighbourhood hanging off a single junction has no
degree-1 node anywhere, yet every resident in it leaves through that one point.
That is the SB 99 access-impaired case and the reason the page exists, and the
degree-1 test cannot see it.

So the network is analysed for ARTICULATION POINTS: nodes whose removal
disconnects part of the graph. Everything behind one is a single-exit area, and
the exit is the articulation point. A turning circle is a cycle hanging off one
articulation point, so it is found. Three stubs of one cul-de-sac sit inside one
area, so it is counted once. And an area is reported with how much street length
and how many blocks sit behind it, which is a far more useful number than a count
of streets.

GRADE SEPARATION

Two segments crossing at different z-levels are a bridge over a road, not a
junction. Snapping them together invents a route that does not exist and would
merge areas that are genuinely separate, so the z-level is part of the node key.

JURISDICTION

The graph is built from the whole regional layer and filtered to Berkeley only at
the end. Building it from Berkeley-only segments severs every street at the city
line and manufactures cul-de-sacs out of Shattuck, Solano and Marin.
"""

import argparse
import collections
import gzip
import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

LAT = 37.87
MX = 111320 * math.cos(math.radians(LAT))
MY = 110574

# Endpoints closer than this are treated as the same junction. Swept in --sweep;
# the reported area count must not be sensitive to it.
SNAP_M = 4.0

# Two loose ends of the same street closer than this are the two sides of one
# hole in the centreline rather than two cul-de-sacs. Also swept.
GAP_M = 90.0

# A loose end lying this close to another street's node is a junction the data
# forgot to record, not a cul-de-sac head. Upper Marin Ave stops just short of
# Grizzly Peak Blvd without joining it.
JOIN_M = 22.0

# Drivability comes from ROADCLASS and nothing else. An earlier version also
# dropped any name containing PATH, TRAIL, STEPS or WALK, which was worse than
# useless: the City already classes the real footpaths as PEDESTRIAN, while the
# keyword list threw away Walker St and Fountain Walk. Fountain Walk is the
# MAJOR road forming the south portal of the Northbrae Tunnel, so dropping it
# severed the tunnel and reported Solano Ave as a single-exit area.

# Kept in the graph, because leaving Berkeley by freeway is a real route, but
# never reported as a neighbourhood. A freeway also runs off the edge of the
# extract, which makes it look single-exit when it is only unfinished.
TRUNK = ("HIGHWAY", "RAMP")


def load_segments():
    # The gzipped snapshot is what is committed; 14 MB of JSON compresses to 4.5.
    # The plain file is used when present so a fresh harvest can be tested without
    # a recompress step.
    plain = HERE / "streets_raw.json"
    if plain.exists():
        raw = json.loads(plain.read_text())["features"]
    else:
        with gzip.open(HERE / "streets_raw.json.gz", "rt") as fh:
            raw = json.load(fh)["features"]
    segs = []
    for f in raw:
        g = f.get("geometry") or {}
        a = f["attributes"]
        name = (a.get("FULLNAME") or "").strip().upper()
        cls = (a.get("ROADCLASS") or "").strip()
        if cls == "PEDESTRIAN":
            continue
        if not name:
            continue
        for path in g.get("paths", []):
            if len(path) < 2:
                continue
            segs.append({
                "name": name,
                "cls": cls,
                "block": (a.get("block_addr") or "").strip(),
                "muni": {(a.get("MUNILEFT") or "").strip(),
                         (a.get("MUNIRIGHT") or "").strip()},
                "zf": a.get("F_ZLEV") or 0,
                "zt": a.get("T_ZLEV") or 0,
                "pts": path,
            })
    return segs


def build_graph(segs, snap_m):
    """Snap endpoints onto a grid so coincident junctions share a node.

    The grid cell is the snap distance. Two endpoints in the same cell collapse;
    endpoints in adjacent cells are also merged when they are genuinely within
    the distance, which stops a junction landing on a cell edge from splitting.
    """
    cell = snap_m
    reps = {}

    def key(pt, z):
        return (int(round(pt[0] * MX / cell)), int(round(pt[1] * MY / cell)), z)

    def node(pt, z):
        k = key(pt, z)
        if k in reps:
            return reps[k]
        # adopt a neighbouring cell's node if one is genuinely within snap_m
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nk = (k[0] + dx, k[1] + dy, z)
                if nk in reps:
                    ox, oy = reps[nk][1]
                    if math.hypot((pt[0] - ox) * MX, (pt[1] - oy) * MY) <= snap_m:
                        reps[k] = reps[nk]
                        return reps[k]
        reps[k] = (len(reps), (pt[0], pt[1]))
        return reps[k]

    adj = collections.defaultdict(set)
    edges = []
    for s in segs:
        a = node(s["pts"][0], s["zf"])[0]
        b = node(s["pts"][-1], s["zt"])[0]
        if a == b:
            continue
        adj[a].add(b)
        adj[b].add(a)
        edges.append((a, b, s))

    # Portal repair. Keying by z-level is what stops an overpass being read as a
    # junction, but it also severs a tunnel or underpass wherever the data omits
    # the transition segment. The Northbrae Tunnel has a -1 to 0 segment at its
    # north portal and none at its south, so Solano Ave came out as a single-exit
    # area, which it plainly is not.
    #
    # The two cases are distinguishable. At a true overpass both levels carry
    # through traffic, so every node there has degree 2 or more. At a portal the
    # severed side has nowhere to go, so it has degree 1. Merge only those.
    by_loc = collections.defaultdict(list)
    for (gx, gy, _z), (n, _xy) in reps.items():
        by_loc[(gx, gy)].append(n)

    remap = {}
    for nodes in by_loc.values():
        if len(nodes) < 2:
            continue
        stubs = [n for n in nodes if len(adj[n]) == 1]
        others = [n for n in nodes if len(adj[n]) > 1]
        if not stubs or not others:
            continue
        for n in stubs:
            remap[n] = others[0]

    if remap:
        def r(n):
            return remap.get(n, n)
        adj2 = collections.defaultdict(set)
        for a, bs in adj.items():
            for b in bs:
                if r(a) != r(b):
                    adj2[r(a)].add(r(b))
                    adj2[r(b)].add(r(a))
        adj = adj2
        edges = [(r(a), r(b), s) for a, b, s in edges if r(a) != r(b)]

    pos = {n: xy for (n, xy) in reps.values()}

    # Gap bridging. The centreline has holes: at a rail crossing, across a
    # divided roadway, wherever the City does not own the pavement. Each hole
    # leaves two loose ends facing each other and the analysis reads the stub
    # between them as a place with one way out. University Ave produced four
    # such stubs of 85-89 m, Cedar St and Hilgard Ave a pair each.
    #
    # Two loose ends carrying the SAME STREET NAME within GAP_M of each other
    # are the two sides of one hole, so join them. A real cul-de-sac has no
    # same-named partner sitting just beyond its head, so it is untouched.
    stub_of = {}
    for a, b, s in edges:
        for n in (a, b):
            if len(adj[n]) == 1:
                stub_of.setdefault(n, s["name"])

    by_name = collections.defaultdict(list)
    for n, nm in stub_of.items():
        by_name[nm].append(n)

    bridged = 0
    for nm, nodes in by_name.items():
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                u, v = nodes[i], nodes[j]
                if v in adj[u]:
                    continue
                ux, uy = pos[u]
                vx, vy = pos[v]
                if math.hypot((ux - vx) * MX, (uy - vy) * MY) <= GAP_M:
                    adj[u].add(v)
                    adj[v].add(u)
                    edges.append((u, v, {"name": nm, "cls": "GAP", "block": "",
                                         "muni": set(), "zf": 0, "zt": 0,
                                         "pts": [[ux, uy], [vx, vy]]}))
                    bridged += 1

    # Missing-junction repair, after name-based bridging catches the rest. A
    # cul-de-sac head does not sit on top of another street; a loose end that
    # does is an unrecorded junction.
    loose = [n for n in adj if len(adj[n]) == 1]
    cell = JOIN_M
    grid = collections.defaultdict(list)
    for n, (x, y) in pos.items():
        grid[(int(x * MX // cell), int(y * MY // cell))].append(n)
    for n in loose:
        if len(adj[n]) != 1:
            continue
        x, y = pos[n]
        gx, gy = int(x * MX // cell), int(y * MY // cell)
        for i in (gx - 1, gx, gx + 1):
            for j in (gy - 1, gy, gy + 1):
                for m in grid.get((i, j), ()):
                    if m == n or m in adj[n] or len(adj[m]) < 2:
                        continue
                    ox, oy = pos[m]
                    if math.hypot((x - ox) * MX, (y - oy) * MY) <= JOIN_M:
                        adj[n].add(m)
                        adj[m].add(n)
                        edges.append((n, m, {"name": "", "cls": "GAP", "block": "",
                                             "muni": set(), "zf": 0, "zt": 0,
                                             "pts": [[x, y], [ox, oy]]}))
                        break

    return adj, edges, pos


def articulation_points(adj):
    """Hopcroft-Tarjan, iterative so a long street cannot blow the stack."""
    disc, low, parent = {}, {}, {}
    arts, timer = set(), [0]
    for root in list(adj):
        if root in disc:
            continue
        stack = [(root, iter(adj[root]))]
        disc[root] = low[root] = timer[0]
        timer[0] += 1
        parent[root] = None
        root_children = 0
        while stack:
            v, it = stack[-1]
            advanced = False
            for w in it:
                if w not in disc:
                    parent[w] = v
                    disc[w] = low[w] = timer[0]
                    timer[0] += 1
                    if v == root:
                        root_children += 1
                    stack.append((w, iter(adj[w])))
                    advanced = True
                    break
                if w != parent[v]:
                    low[v] = min(low[v], disc[w])
            if not advanced:
                stack.pop()
                if stack:
                    u = stack[-1][0]
                    low[u] = min(low[u], low[v])
                    if parent[u] is not None and low[v] >= disc[u]:
                        arts.add(u)
        if root_children > 1:
            arts.add(root)
    return arts


def simplify(pts, tol_m=3.0):
    """Douglas-Peucker. The page inlines this geometry, so every vertex is bytes
    the reader downloads; 3 m is well below what is visible at any usable zoom."""
    if len(pts) < 3:
        return [[round(p[0], 5), round(p[1], 5)] for p in pts]

    def keep(lo, hi, marks):
        ax, ay = pts[lo][0] * MX, pts[lo][1] * MY
        bx, by = pts[hi][0] * MX, pts[hi][1] * MY
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        worst, wi = -1.0, -1
        for i in range(lo + 1, hi):
            px, py = pts[i][0] * MX, pts[i][1] * MY
            t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > worst:
                worst, wi = d, i
        if worst > tol_m:
            marks.add(wi)
            keep(lo, wi, marks)
            keep(wi, hi, marks)

    marks = {0, len(pts) - 1}
    keep(0, len(pts) - 1, marks)
    return [[round(pts[i][0], 5), round(pts[i][1], 5)] for i in sorted(marks)]


def seg_len(pts):
    return sum(math.hypot((pts[i + 1][0] - pts[i][0]) * MX,
                          (pts[i + 1][1] - pts[i][1]) * MY)
               for i in range(len(pts) - 1))


def single_exit_areas(adj, edges, pos, min_core):
    """For each articulation point, the components it cuts off from the core."""
    inc = collections.defaultdict(list)
    for a, b, s in edges:
        inc[a].append((b, s))
        inc[b].append((a, s))

    arts = articulation_points(adj)
    areas = []
    for v in arts:
        seen = {v}
        comps = []
        for start in adj[v]:
            if start in seen:
                continue
            comp, q = set(), [start]
            seen.add(start)
            while q:
                n = q.pop()
                comp.add(n)
                for m in adj[n]:
                    if m not in seen:
                        seen.add(m)
                        q.append(m)
            comps.append(comp)
        if len(comps) < 2:
            continue
        core = max(comps, key=len)
        if len(core) < min_core:
            continue
        for comp in comps:
            if comp is core:
                continue
            segs, names = [], collections.Counter()
            for n in comp:
                for m, s in inc[n]:
                    if m in comp or m == v:
                        segs.append(s)
            uniq = list({id(s): s for s in segs}.values())
            # A freeway is not a neighbourhood, and an area whose story depends on
            # one is an artifact of the extract ending rather than a finding.
            if any(s["cls"] in TRUNK for s in uniq):
                continue
            # An arterial alone behind a single exit is a hole in the centreline,
            # not a cul-de-sac. Arterials do not terminate. Shattuck Ave produced
            # a 72 m fragment where it becomes Adeline St and the name changes.
            real = [s for s in uniq if s["cls"] != "GAP"]
            if len(real) == 1 and real[0]["cls"] == "MAJOR":
                continue
            for s in uniq:
                if s["name"]:            # synthetic bridge edges carry no name
                    names[s["name"]] += 1
            areas.append({
                "exit": pos[v],
                "nodes": len(comp),
                "metres": round(sum(seg_len(s["pts"]) for s in uniq)),
                "segments": len(uniq),
                "names": [n for n, _ in names.most_common()],
                "muni": sorted({m for s in uniq for m in s["muni"] if m}),
                "blocks": sorted({s["block"] for s in uniq if s["block"]}),
                "cls": sorted({s["cls"] for s in uniq if s["cls"]}),
                "paths": [simplify(s["pts"]) for s in uniq],
                "_members": comp,
            })
    # keep only maximal areas: drop any that sits wholly inside another
    areas.sort(key=lambda a: -a["nodes"])
    kept = []
    for a in areas:
        if not any(a["_members"] <= b["_members"] for b in kept):
            kept.append(a)
    for a in kept:
        del a["_members"]
    return kept, arts


def run(snap_m, min_core=200, quiet=False):
    segs = load_segments()
    adj, edges, pos = build_graph(segs, snap_m)
    areas, arts = single_exit_areas(adj, edges, pos, min_core)
    berk = [a for a in areas if "Berkeley" in a["muni"]]
    if not quiet:
        print(f"snap {snap_m:>4.1f} m   nodes {len(adj):>5}   edges {len(edges):>5}   "
              f"articulation pts {len(arts):>4}   areas {len(areas):>4}   "
              f"Berkeley {len(berk):>4}")
    return berk, segs, areas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true",
                    help="vary the snap tolerance; the count must be stable")
    args = ap.parse_args()

    if args.sweep:
        print("Acceptance test: the Berkeley area count must not move with tolerance.\n")
        for t in (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 20.0):
            run(t)
        return 0

    berk, segs, areas = run(SNAP_M)
    berk.sort(key=lambda a: -a["metres"])
    out = HERE / "deadends.json"
    out.write_text(json.dumps(berk, separators=(",", ":")))
    print(f"\nwrote {out.name}: {len(berk)} Berkeley single-exit areas")
    print(f"  total street length behind a single exit: "
          f"{sum(a['metres'] for a in berk) / 1000:.1f} km")
    print("\n  largest:")
    for a in berk[:12]:
        print(f"    {a['metres']:>6} m  {a['segments']:>3} seg  {', '.join(a['names'][:3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
