#!/usr/bin/env python3
"""Assemble index.html from the template and the harvested layer data.

    python3 build/build.py

The tool ships as one self-contained file so it can be served from GitHub Pages
with no build step at request time, opened from a USB stick, or printed. That
means the map data is inlined rather than fetched, which is why this script
exists: template.html carries a `/*__DATA__*/ null` placeholder and this
substitutes the data into it.

Inputs:
  data.json      the layer snapshot (fire zones, hazards, stations, narrow
                 streets, chipper areas, display street geometry)
  deadends.json  single-exit areas, produced by deadends.py

An earlier version of this script carried a boundary clip, because the street
data had been filtered to Berkeley before the graph was built and every street
crossing the city line came out as a cul-de-sac. The clip was a patch over that.
deadends.py now builds on the whole regional network and selects Berkeley from
the results, so the fault is gone at source and the patch with it.
"""

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PLACEHOLDER = "/*__DATA__*/ null"


def main() -> int:
    template = (HERE / "template.html").read_text()
    if PLACEHOLDER not in template:
        print(f"error: {PLACEHOLDER!r} not found in template.html", file=sys.stderr)
        return 1

    # Parsed rather than pasted blind. A truncated data file would otherwise
    # produce a page that loads, renders the fallback diagram, and looks merely
    # disappointing instead of broken.
    data = json.loads((HERE / "data.json").read_text())

    deadends_path = HERE / "deadends.json"
    if not deadends_path.exists():
        print("error: build/deadends.json missing, run build/deadends.py first",
              file=sys.stderr)
        return 1
    areas = json.loads(deadends_path.read_text())

    # Stamp each area with what the independent OSM check made of it. Shipping
    # the confirmations while leaving the disagreements in a README would be
    # publishing the convenient half of the result: a resident on Middlefield Rd
    # would be told they have one way out with no hint another survey disagrees.
    verdicts_path = HERE / "verdicts.json"
    if not verdicts_path.exists():
        print("error: build/verdicts.json missing, run build/validate_osm.py first",
              file=sys.stderr)
        return 1
    verdicts = json.loads(verdicts_path.read_text())
    for a in areas:
        v = verdicts.get(f"{a['exit'][0]:.5f},{a['exit'][1]:.5f}", {"v": "none"})
        a["v"] = v["v"]
        if v["v"] == "disputed":
            a["vn"] = v["n"]
    counts = {k: sum(1 for a in areas if a["v"] == k) for k in ("ok", "disputed", "none")}

    data.pop("deadEnds", None)
    data["areas"] = areas
    # Drive time from the nearest station, joined onto the display streets. The
    # page reported a straight line while its own footer cited a five minute
    # DRIVE TIME standard; on a hill those differ by a lot, because a station
    # 400 m away across a canyon is a several minute drive around it.
    dt_path = HERE / "drivetime.json"
    if not dt_path.exists():
        print("error: build/drivetime.json missing, run build/drivetime.py first",
              file=sys.stderr)
        return 1
    dt = json.loads(dt_path.read_text())
    seg = dt["seg"]
    timed = 0
    for st in data["streets"]:
        v = seg.get(str(st.get("i")))
        if v:
            st["t"], st["k"] = v[0], v[1]
            timed += 1
        st.pop("i", None)
    # The City's traffic diverters. Drawn whether or not the analysis could use
    # them: 48 of them it cannot, and a resident who sees a diverter at their own
    # corner knows exactly what it does, which is knowledge this page lacks.
    bp = HERE / "barriers_placed.json"
    if not bp.exists():
        print("error: build/barriers_placed.json missing, run build/deadends.py first",
              file=sys.stderr)
        return 1
    data["barriers"] = json.loads(bp.read_text())
    data["meta"]["barriersCut"] = sum(1 for b in data["barriers"] if b["effect"] == "cut")
    data["meta"]["barriersUnmodelled"] = sum(
        1 for b in data["barriers"] if b["effect"] == "unmodelled")

    data["meta"]["sb99Minutes"] = dt["sb99Minutes"]
    data["meta"]["streetsTimed"] = timed

    data["meta"]["osmConfirmed"] = counts["ok"]
    data["meta"]["osmDisputed"] = counts["disputed"]
    data["meta"]["singleExitAreas"] = len(areas)
    data["meta"]["metresBehindSingleExit"] = sum(a["metres"] for a in areas)
    data["meta"].pop("berkeleyNamedRoadDeadEnds", None)
    data["meta"].pop("inHillZone2or3", None)
    data["meta"].pop("boundaryTerminationsDropped", None)

    out = template.replace(PLACEHOLDER, json.dumps(data, separators=(",", ":")))
    (ROOT / "index.html").write_text(out)

    print(f"single-exit areas {len(areas)}, "
          f"{data['meta']['metresBehindSingleExit'] / 1000:.1f} km behind them")
    print(f"  OSM verdicts: {counts['ok']} confirmed, {counts['disputed']} disputed, "
          f"{counts['none']} not checkable")
    print(f"  drive times on {timed} of {len(data['streets'])} display segments")
    print(f"  barriers {len(data['barriers'])}: "
          f"{data['meta']['barriersCut']} cut, "
          f"{data['meta']['barriersUnmodelled']} at junctions not modelled")
    print(f"wrote index.html  {len(out):,} bytes")
    for k, v in sorted((k, len(v)) for k, v in data.items() if isinstance(v, list)):
        print(f"  {k:<12} {v:>6,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
