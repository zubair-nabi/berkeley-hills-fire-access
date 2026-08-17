#!/usr/bin/env python3
"""Fetch every non-street layer the page uses, and write build/data.json.

    python3 build/harvest_layers.py

Until now data.json was an undocumented snapshot with no way to reproduce or
refresh it. That is a slow-motion failure for a page whose whole claim is that
its numbers come from the City: the fire zones, hazard zones, chipper areas and
station list would drift out of date silently, and nobody could tell when.

Street geometry is harvested separately by harvest_streets.py, which pulls the
full regional network. The display subset written here is that same network
clipped to Berkeley, because the map only needs to draw the city.

Layer choices worth recording:

  Fire zones come from Land_Use_Planning/6, which carries PLN_HILL_ZONE and so
  distinguishes zone 2 from zone 3. Several other services publish a Fire
  Districts layer without that attribute.

  Narrow streets come from Land_Use_Planning/55, the City's own published list.
  The street network also carries PAV_WIDTH_RD, but the published list is the
  one the City's evacuation study refers to, so it is the one to cite.

  CalFire severity zones come from Accela/32 filtered to HAZ_CLASS containing
  "Very High". The layer includes moderate and high classes that the page does
  not claim anything about.
"""

import json
import math
import pathlib
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
BASE = "https://gis.cityofberkeley.info/arcgis/rest/services"

LAT = 37.87
MX = 111320 * math.cos(math.radians(LAT))
MY = 110574


# Berkeley plus a margin. The landslide and fault layers are regional: fetched
# whole they return 953 and 7 polygons covering the East Bay, which is a megabyte
# of geometry the reader downloads to answer a question about one address.
BERKELEY_BBOX = "-122.335,37.835,-122.225,37.912"


def _get(url):
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
            print(f"    retry {attempt + 1} after {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return {}


def fetch(layer, where="1=1", fields="*", geometry=True, clip=False):
    """Paged. Every one of these layers caps a single response at 1000 or 2000
    rows and says nothing when it truncates; the narrow-streets list came back
    as exactly 1000 of 882 expected before this existed."""
    base = {"where": where, "outFields": fields, "f": "json",
            "returnGeometry": "true" if geometry else "false", "outSR": "4326"}
    if clip:
        base.update({"geometry": BERKELEY_BBOX, "geometryType": "esriGeometryEnvelope",
                     "inSR": "4326", "spatialRel": "esriSpatialRelIntersects"})

    count = _get(f"{BASE}/{layer}/query?" +
                 urllib.parse.urlencode({**base, "returnCountOnly": "true"})).get("count", 0)
    feats, offset, page = [], 0, 500
    while offset < count:
        body = _get(f"{BASE}/{layer}/query?" + urllib.parse.urlencode(
            {**base, "resultOffset": str(offset), "resultRecordCount": str(page),
             "orderByFields": "OBJECTID"}))
        got = body.get("features", [])
        if not got:
            break
        feats.extend(got)
        offset += len(got)
    if count and len(feats) != count:
        print(f"    warning: {layer} returned {len(feats)} of {count}", file=sys.stderr)
    return feats


def rings(f):
    return f.get("geometry", {}).get("rings", [])


def simplify(pts, tol_m=4.0):
    """Douglas-Peucker. Every vertex here is bytes the reader downloads."""
    if len(pts) < 3:
        return [[round(p[0], 5), round(p[1], 5)] for p in pts]

    def walk(lo, hi, marks):
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
            walk(lo, wi, marks)
            walk(wi, hi, marks)

    marks = {0, len(pts) - 1}
    sys.setrecursionlimit(10000)
    walk(0, len(pts) - 1, marks)
    return [[round(pts[i][0], 5), round(pts[i][1], 5)] for i in sorted(marks)]


def poly(feats, attrs):
    out = []
    for f in feats:
        r = rings(f)
        if not r:
            continue
        out.append({"a": {k: f["attributes"].get(k) for k in attrs},
                    "r": [simplify(ring) for ring in r]})
    return out


def main() -> int:
    data = {}

    print("fire zones (Hill Zones 1, 2, 3)")
    # All three zones, including zone 1. The page needs it to tell a resident
    # outside the hills that they are in zone 1 rather than in no mapped zone at
    # all, which are different statements. Filtering to 2 and 3 broke that.
    fz = fetch("Planning/Land_Use_Planning/MapServer/6", fields="PLN_HILL_ZONE")
    data["fireZones"] = poly(fz, ["PLN_HILL_ZONE"])
    zones = sorted(z["a"]["PLN_HILL_ZONE"] for z in data["fireZones"])
    print(f"    {len(data['fireZones'])} polygons, zones {zones}")

    print("hazards")
    ls = fetch("Planning/Land_Use_Planning/MapServer/11", fields="OBJECTID", clip=True)
    fa = fetch("Planning/Land_Use_Planning/MapServer/13", fields="OBJECTID", clip=True)
    vh = fetch("Planning/Accela/MapServer/32", fields="HAZ_CLASS,HAZ_CODE", clip=True)
    vh = [f for f in vh if "VERY HIGH" in (f["attributes"].get("HAZ_CLASS") or "").upper()]
    data["hazards"] = {"landslide": poly(ls, ["OBJECTID"]),
                       "fault": poly(fa, ["OBJECTID"]),
                       "calfireVHFHSZ": poly(vh, ["HAZ_CLASS"])}
    print(f"    landslide {len(data['hazards']['landslide'])}, "
          f"fault {len(data['hazards']['fault'])}, "
          f"very high severity {len(data['hazards']['calfireVHFHSZ'])}")

    # Portal_CommSvcs/2, not PublicSafety/0. The latter is named "Fire Stations"
    # and holds exactly one record, Fire Administration on McKinley Ave, which is
    # an office rather than a station. Harvesting it silently reduced the page
    # from seven stations to one.
    print("fire stations")
    st = fetch("Public/Portal_CommSvcs/MapServer/2", fields="TITLE,ADDRESS,DESCRIPTIO")
    data["stations"] = sorted(
        ({"name": (f["attributes"].get("TITLE") or "").strip(),
          "addr": (f["attributes"].get("ADDRESS") or "").strip(),
          "x": round(f["geometry"]["x"], 5), "y": round(f["geometry"]["y"], 5)}
         for f in st if f.get("geometry")),
        key=lambda s: s["name"])
    print(f"    {len(data['stations'])}")

    print("chipper areas")
    ch = fetch("Parks/FireFuel_Chipper_Areas/MapServer/0", fields="OBJECTID,Number")
    data["chipper"] = poly(ch, ["OBJECTID", "Number"])
    print(f"    {len(data['chipper'])}")

    # Regional, like the street network, so it needs the same jurisdiction
    # filter. Unfiltered it brings in Caldecott Ln, 54th St and the Emeryville
    # waterfront, none of which this page speaks for.
    print("narrow streets")
    nr = fetch("Planning/Land_Use_Planning/MapServer/55",
               fields="FULLNAME,MUNILEFT,MUNIRIGHT")
    data["narrow"] = [
        {"s": (f["attributes"].get("FULLNAME") or "").strip().upper(), "p": simplify(p)}
        for f in nr
        if "Berkeley" in ((f["attributes"].get("MUNILEFT") or "").strip(),
                          (f["attributes"].get("MUNIRIGHT") or "").strip())
        for p in f.get("geometry", {}).get("paths", []) if len(p) >= 2]
    print(f"    {len(data['narrow'])} segments in Berkeley of {len(nr)} regional")

    print("street geometry for display")
    raw_path = HERE / "streets_raw.json"
    if raw_path.exists():
        raw = json.loads(raw_path.read_text())["features"]
    else:
        import gzip
        with gzip.open(HERE / "streets_raw.json.gz", "rt") as fh:
            raw = json.load(fh)["features"]
    streets = []
    for f in raw:
        a = f["attributes"]
        if "Berkeley" not in ((a.get("MUNILEFT") or ""), (a.get("MUNIRIGHT") or "")):
            continue
        name = (a.get("FULLNAME") or "").strip().upper()
        if not name:
            continue
        for p in f.get("geometry", {}).get("paths", []):
            if len(p) >= 2:
                # OBJECTID travels with the segment so build.py can join the
                # drive times onto it without matching on geometry.
                streets.append({"s": name, "i": a.get("OBJECTID"), "p": simplify(p)})
    data["streets"] = streets
    print(f"    {len(streets)} segments in Berkeley")

    old = json.loads((HERE / "data.json").read_text())
    data["meta"] = {"generated": time.strftime("%Y-%m-%d"),
                    "segments": old["meta"]["segments"]}

    out = HERE / "data.json"
    out.write_text(json.dumps(data, separators=(",", ":")))
    print(f"\nwrote {out.name}  {out.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
