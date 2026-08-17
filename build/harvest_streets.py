#!/usr/bin/env python3
"""Fetch the full street centreline network from the City's ArcGIS server.

    python3 build/harvest_streets.py

Writes build/streets_raw.json.

Fetch the WHOLE layer, including Oakland, Albany and Kensington. This matters more
than it looks. The layer is regional, and an earlier version of this project
filtered it to Berkeley before building the street graph. Every street that
crosses the city line then lost its far half, the graph saw a loose end, and the
degree-1 test called it a dead end. Shattuck, Solano, Marin and Peralta all came
out as cul-de-sacs. Filter to Berkeley at the END, on the results, never on the
network the results are computed from.

The fields fetched are the ones the derivation needs:

  FULLNAME, block_addr   naming and the block label shown to the user
  MUNILEFT, MUNIRIGHT    jurisdiction per segment, so Berkeley can be selected
                         without a geometric guess against a boundary polygon
  F_ZLEV, T_ZLEV         grade separation. Two segments crossing at different
                         z-levels are an overpass, not a junction, and joining
                         them would invent a route that does not exist
  ROADCLASS, MTFCC       classification, used to drop paths and trails
  ONEWAYDIR              one-way pairs, which produce parallel centrelines
  PAV_WIDTH_RD           pavement width, the narrow-street measure at source
"""

import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
URL = ("https://gis.cityofberkeley.info/arcgis/rest/services"
       "/Planning/Accela/MapServer/3/query")
FIELDS = ("OBJECTID,FULLNAME,block_addr,MUNILEFT,MUNIRIGHT,F_ZLEV,T_ZLEV,"
          "ROADCLASS,MTFCC,ONEWAYDIR,PAV_WIDTH_RD")
PAGE = 1000


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
        except Exception as exc:                      # noqa: BLE001
            if attempt == 3:
                raise
            print(f"  retry {attempt + 1} after {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def main() -> int:
    total = fetch({"where": "1=1", "returnCountOnly": "true", "f": "json"})["count"]
    print(f"layer reports {total} segments")

    feats, offset = [], 0
    while offset < total:
        body = fetch({
            "where": "1=1", "outFields": FIELDS, "returnGeometry": "true",
            "outSR": "4326", "f": "json",
            "resultOffset": str(offset), "resultRecordCount": str(PAGE),
            "orderByFields": "OBJECTID",
        })
        got = body.get("features", [])
        if not got:
            break
        feats.extend(got)
        offset += len(got)
        print(f"  {offset}/{total}")

    if len(feats) != total:
        print(f"warning: fetched {len(feats)}, layer reported {total}", file=sys.stderr)

    out = HERE / "streets_raw.json"
    out.write_text(json.dumps({"features": feats}, separators=(",", ":")))
    print(f"wrote {out.name}  {out.stat().st_size:,} bytes  {len(feats)} segments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
