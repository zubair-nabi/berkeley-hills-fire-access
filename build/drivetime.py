#!/usr/bin/env python3
"""Drive time from the nearest fire station, along the streets.

    python3 build/drivetime.py

Reads build/streets_raw.json.gz and build/data.json, writes build/drivetime.json.

WHY THIS EXISTS

The page reported distance to the nearest station as a straight line, then
explained in its own footer that SB 99 defines an access impaired neighbourhood
by a FIVE MINUTE DRIVE-TIME SERVICE AREA. Showing one number while citing a
standard built on a different one is the largest gap between what this page
displays and what it means. On a hill the two diverge badly: a station 400 m away
across a canyon can be a five minute drive around it.

The City's street layer carries FT_MINUTES and TF_MINUTES, free-flow travel time
per direction, so this is computable rather than aspirational.

METHOD

Multi-source Dijkstra outward from all seven stations at once over the directed
network, which yields for every node both its travel time and which station
reaches it first. The graph is the one deadends.py builds, repairs included, so
the routing and the single-exit analysis cannot disagree about what connects.

FREE FLOW, AND WHAT THAT DOES AND DOES NOT MODEL

FT_MINUTES is derived from segment length and posted speed, so it assumes clear
roads. That is the right assumption for an engine responding uphill and the wrong
one for residents evacuating downhill, where congestion IS the problem the KLD
studies are about. This number is engine response, and the page says so.

ONE-WAY STREETS

Respected, which makes the times conservative. California vehicle code 21055 lets
an authorised emergency vehicle disregard one-way restrictions, so a real engine
may do better than this says. Being pessimistic about response time is the safe
direction for a number a resident might plan around.
"""

import collections
import heapq
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import deadends as D  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent

# SB 99's threshold. An address outside this is what the statute is about.
SB99_MINUTES = 5.0

# Fallback speed where the layer carries no travel time, in km/h. 40 is the
# 25 mph posted on most Berkeley streets and the median implied by the segments
# that do carry a time.
FALLBACK_KMH = 40.0


def seg_minutes(s):
    """Travel time for one segment, in minutes, with the layer's own value first.

    720 of 6,971 segments carry no FT_MINUTES, and the synthetic edges added by
    the gap and portal repairs carry none by construction. Falling back to length
    over speed keeps those passable instead of silently severing the network,
    which would inflate every drive time behind them.
    """
    for key in ("ft", "tf"):
        v = s.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    metres = s.get("meters")
    if not isinstance(metres, (int, float)) or metres <= 0:
        metres = sum(math.hypot((s["pts"][i + 1][0] - s["pts"][i][0]) * D.MX,
                                (s["pts"][i + 1][1] - s["pts"][i][1]) * D.MY)
                     for i in range(len(s["pts"]) - 1))
    speed = s.get("speed")
    kmh = float(speed) * 1.60934 if isinstance(speed, (int, float)) and speed > 1 else FALLBACK_KMH
    return (metres / 1000.0) / kmh * 60.0


def directed(edges):
    """Adjacency honouring ONEWAYDIR. FT allows from-to only, TF to-from only."""
    adj = collections.defaultdict(list)
    for a, b, s in edges:
        cost = seg_minutes(s)
        one = (s.get("oneway") or "").strip().upper()
        if one != "TF":
            adj[a].append((b, cost))
        if one != "FT":
            adj[b].append((a, cost))
    return adj


def nearest_node(pos, x, y):
    """build_graph stores node positions as raw lon/lat, so both sides of the
    comparison have to be projected. Projecting only the station put every one of
    them 11,500 km from the network and produced a plausible-looking set of drive
    times that were entirely wrong."""
    px, py = x * D.MX, y * D.MY
    best, bn = float("inf"), None
    for n, (lon, lat) in pos.items():
        nx, ny = lon * D.MX, lat * D.MY
        d = (nx - px) ** 2 + (ny - py) ** 2
        if d < best:
            best, bn = d, n
    return bn, math.sqrt(best)


def main() -> int:
    segs = D.load_segments()
    adj_u, edges, pos = D.build_graph(segs, D.SNAP_M)
    adj = directed(edges)

    stations = json.loads((HERE / "data.json").read_text())["stations"]
    sources = []
    for i, st in enumerate(stations):
        n, off = nearest_node(pos, st["x"], st["y"])
        sources.append((n, i))
        print(f"  {st['name']:<16} snapped to the network {off:5.0f} m away")

    dist = {}
    which = {}
    heap = []
    for n, i in sources:
        if n is None:
            continue
        if dist.get(n, float("inf")) > 0:
            dist[n], which[n] = 0.0, i
            heapq.heappush(heap, (0.0, n, i))

    while heap:
        d, n, src = heapq.heappop(heap)
        if d > dist.get(n, float("inf")):
            continue
        for m, w in adj.get(n, ()):
            nd = d + w
            if nd < dist.get(m, float("inf")):
                dist[m], which[m] = nd, src
                heapq.heappush(heap, (nd, m, src))

    # Per segment, the better of its two endpoints: whichever end you approach
    # from, that is when an engine reaches the street.
    out = {}
    for a, b, s in edges:
        oid = s.get("oid")
        if oid is None:
            continue
        # Berkeley only. The graph is regional so that routes are real, but a
        # Berkeley reader has no use for a drive time in the Oakland hills, and
        # carrying them made the summary read as a 36 minute worst case.
        if "Berkeley" not in (s.get("muni") or set()):
            continue
        best, src = float("inf"), None
        for n in (a, b):
            if n in dist and dist[n] < best:
                best, src = dist[n], which[n]
        if src is None:
            continue
        prev = out.get(oid)
        if prev is None or best < prev[0]:
            out[oid] = [round(best, 2), src]

    reached = len(out)
    within = sum(1 for v in out.values() if v[0] <= SB99_MINUTES)
    unreached = sum(1 for n in pos if n not in dist)

    (HERE / "drivetime.json").write_text(json.dumps(
        {"sb99Minutes": SB99_MINUTES, "seg": out}, separators=(",", ":")))

    print(f"\n{reached} segments reachable, {unreached} nodes unreachable")
    print(f"{within} of {reached} ({100 * within / reached:.0f}%) within "
          f"{SB99_MINUTES:g} minutes of a station")
    times = sorted(v[0] for v in out.values())
    if times:
        print(f"median {times[len(times)//2]:.1f} min, "
              f"90th percentile {times[int(.9*len(times))]:.1f} min, "
              f"max {times[-1]:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
