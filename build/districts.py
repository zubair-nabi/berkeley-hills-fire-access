#!/usr/bin/env python3
"""Break the single-exit areas down by council district.

    python3 build/districts.py            print the markdown table
    python3 build/districts.py --harvest  refetch the district boundaries first

Writes nothing by default. The table is pasted into the README, and
tests/test_build.py checks the README still agrees with what this prints, so a
stale table fails the build instead of quietly misinforming.

An area is assigned to the district holding most of its street length, not to the
district holding its exit junction. The exit is a single point and often sits on
the boundary road between two districts, which is exactly where an arbitrary
choice would flip the count.

The Redistricting layer carries a CouncilMember field. It is out of date, still
naming members who have left office, so only district numbers are used here.
"""

import argparse
import collections
import json
import math
import pathlib
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
LAYER = ("https://gis.cityofberkeley.info/arcgis/rest/services"
         "/Commission/RedistrictingCommission/MapServer/1/query")

LAT = 37.87
MX = 111320 * math.cos(math.radians(LAT))
MY = 110574


def harvest():
    params = {"where": "1=1", "outFields": "District", "returnGeometry": "true",
              "outSR": "4326", "f": "json"}
    url = LAYER + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "berkeley-hills-fire-access/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = json.load(r)
    if "error" in body:
        raise RuntimeError(body["error"])
    out = HERE / "council_districts.json"
    out.write_text(json.dumps(body, separators=(",", ":")))
    print(f"wrote {out.name}: {len(body['features'])} districts")


def point_in_polygon(x, y, rings):
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


def seg_len(a, b):
    return math.hypot((a[0] - b[0]) * MX, (a[1] - b[1]) * MY)


def tally():
    areas = json.loads((HERE / "deadends.json").read_text())
    feats = json.loads((HERE / "council_districts.json").read_text())["features"]
    districts = {f["attributes"]["District"]: f["geometry"]["rings"] for f in feats}

    counts = collections.Counter()
    metres = collections.Counter()
    for a in areas:
        # length-weighted vote, one vote per segment midpoint
        votes = collections.Counter()
        for path in a["paths"]:
            for i in range(len(path) - 1):
                mid = ((path[i][0] + path[i + 1][0]) / 2,
                       (path[i][1] + path[i + 1][1]) / 2)
                w = seg_len(path[i], path[i + 1])
                for num, rings in districts.items():
                    if point_in_polygon(mid[0], mid[1], rings):
                        votes[num] += w
                        break
        if not votes:
            counts["none"] += 1
            continue
        win = votes.most_common(1)[0][0]
        counts[win] += 1
        metres[win] += a["metres"]
    return counts, metres, len(areas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--harvest", action="store_true")
    args = ap.parse_args()
    if args.harvest:
        harvest()

    counts, metres, total = tally()
    nums = sorted(n for n in counts if isinstance(n, int))

    print(f"{total} single-exit areas by council district\n")
    print("| District | " + " | ".join(str(n) for n in nums) + " |")
    print("| --- |" + " --- |" * len(nums))
    print("| Areas | " + " | ".join(str(counts[n]) for n in nums) + " |")
    print("| Street behind them | "
          + " | ".join(f"{metres[n] / 1000:.1f} km" for n in nums) + " |")
    if counts.get("none"):
        print(f"\n{counts['none']} area(s) fell outside every district polygon.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
