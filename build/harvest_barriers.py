#!/usr/bin/env python3
"""Fetch the City's traffic barrier inventory.

    python3 build/harvest_barriers.py

Writes build/barriers.json.

WHY THIS LAYER MATTERS

The street centreline records where roads run, not where they are closed. Berkeley
has a lot of diverters, and a block closed by one is a cul-de-sac for a car while
the centreline runs straight through it. That is the single largest reason this
project reproduced only 61 percent of the City consultants' access impaired
neighbourhood list: 16 of the ones it missed are flagged by KLD as closed by a
removable barrier. Dana St, Fulton St, Ellsworth St, Milvia St and Russell St are
all that case, and one of the diverters in this layer sits at California and
Russell.

WHAT IS IN IT, AND WHAT IS NOT

147 records, of which 87 are diverters and 60 are traffic circles. The circles are
dropped: a roundabout calms traffic, it does not stop you driving through. Of the
87, category tells you how completely each one closes the street.

ROTATION, CONDITION and INSTALLDATE are empty on all 87, so there is no way to
know which diagonal a barrier runs along. That turns out not to matter, because
every diagonal diverter has the same topological effect regardless of orientation:
no through movement, all turns still legal. See deadends.py.

The fire_number field is the useful one. The Fire Department numbers these, which
is consistent with them being inventoried for removal in an emergency, and it is
how the page can tell a resident that a second way out exists if someone opens it.
"""

import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
URL = ("https://gis.cityofberkeley.info/arcgis/rest/services"
       "/Police/PublicSafety/MapServer/23/query")

# Everything that closes a street. Traffic circles are excluded by this filter,
# which is deliberate and is the single most important line in this script.
WHERE = "FURNTYPE='Traffic Diverter'"


def fetch(params):
    url = URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "berkeley-hills-fire-access/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = json.load(r)
            if "error" in body:
                raise RuntimeError(body["error"])
            return body
        except Exception as exc:                       # noqa: BLE001
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1} after {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return {}


def main() -> int:
    total = fetch({"where": WHERE, "returnCountOnly": "true", "f": "json"})["count"]
    body = fetch({"where": WHERE, "outFields": "OBJECTID,category,fire_number,STATUS",
                  "returnGeometry": "true", "outSR": "4326", "f": "json"})
    feats = body.get("features", [])
    if len(feats) != total:
        print(f"warning: fetched {len(feats)} of {total}", file=sys.stderr)

    out = []
    for f in feats:
        g = f.get("geometry")
        if not g:
            continue
        a = f["attributes"]
        cat = (a.get("category") or "").strip().lower()
        out.append({
            "x": round(g["x"], 6), "y": round(g["y"], 6),
            "cat": cat or "unknown",
            "fire": a.get("fire_number"),
            "status": (a.get("STATUS") or "").strip(),
        })

    counts = {}
    for b in out:
        counts[b["cat"]] = counts.get(b["cat"], 0) + 1

    path = HERE / "barriers.json"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {path.name}: {len(out)} traffic diverters (traffic circles excluded)")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<32} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
