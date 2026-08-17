# Berkeley hills fire access

A map of the things that decide how fast you can get out of the Berkeley hills, and
how fast a fire engine can get in: dead-end streets, streets too narrow for an engine
to pass a car coming down, the Hill Fire Zones, landslide and fault zones, chipper
drop areas, and the fire stations.

Type an address, get the answer for that address.

**Unofficial.** Berkeley Fire Department is the authority on all of this. If anything
here disagrees with them, they are right. This page draws no evacuation route and
never will.

## What it is

One self-contained HTML file. No server, no build step at request time, no tracking,
no network calls except the map tiles and the City's own ArcGIS server. Open it from
a USB stick if you like. It prints.

## Status: not ready to publish

The dead-end layer, which is the whole point of the page, still contains false
positives beyond the boundary artifacts described below. University Ave appears six
times. California St, Cedar St, Virginia St, Hilgard Ave, Northside Ave, West St and
North St are all still flagged, and none of them is a dead end.

The likely cause is the snapping tolerance in the graph build. Where the City splits a
centreline at an intersection, a bridge, or a one-way pair and the two endpoints do not
land within tolerance, they never share a node and both sides read as degree 1. That is
testable by sweeping the tolerance, which needs the harvest script that was not kept.

An attempt to measure the error rate against OpenStreetMap was abandoned because the
test was not stable: across reasonable choices of the exclusion radius, the acceptance
cone, and whether `highway=service` is excluded, the count of genuine dead ends moved
between 29 and 77 out of the same 156. That is a heuristic, not a measurement, and no
number from it appears anywhere in this repo or on the page.

Do not enable GitHub Pages or circulate the link until the dead-end count stops moving.
Putting a dead-end sign on a through street is the one failure that would cost this
page its standing with the Fire Department, and it contradicts the page's own footer.

Everything else holds: the boundary correction is deterministic geometry rather than a
tuned heuristic, and the rest of the layers come straight from the City.

## Why

The City commissioned two studies from KLD Engineering in early 2024:

- **Access Impaired Neighborhood Analysis**, under SB 99
- **Evacuation Route Safety, Capacity, and Viability Analysis**, under AB 747

Both are careful pieces of work and both are published as figures inside PDFs. None
of it is in the City's open data portal, which carries 66 datasets and not one on
evacuation, access impairment, fire zones, or hazards. So a resident who wants to
know about their own street has to read a report and squint at a map.

The inputs are all public. This computes the per-address answer from them.

## Data

Everything comes from layers the City of Berkeley publishes openly, via
`gis.cityofberkeley.info/arcgis/rest/services`.

| Layer | Source | Count |
| --- | --- | --- |
| Street centrelines | `Public/Streets` | 6,971 segments |
| Dead ends | derived, see below | 156 named roads |
| City boundary | `Public/Portal_Planning/8` | 1 polygon |
| Narrow streets | City's published narrow-streets list | 882 segments |
| Hill Fire Zones 2 and 3 | `Planning` | 3 polygons |
| CalFire severity zones | State FRAP, via the City | |
| Landslide and Alquist-Priolo fault zones | State, via the City | |
| Chipper areas | Fire Department | 8 areas |
| Fire stations | Fire Department | 7 |
| Building footprints | fetched per neighbourhood on search | |
| Address points | 62,090 published points | |

Data snapshot in `build/data.json` was harvested 2026-08-16.

### How dead ends are worked out

The street network is built as a graph from the centreline segments, endpoints snapped
to a tolerance so that segments meeting at a junction share a node. Any node with
degree 1 is a termination. Terminations are then filtered to named roads, which drops
driveways, service spurs, and paper streets.

That gives 253 raw terminations. 97 of them are then dropped as boundary artifacts,
leaving **156**, of which **82** are in Hill Fire Zone 2 or 3.

### Why 97 terminations are thrown away

The centreline layer is clipped at the city boundary. A street that carries on into
Albany or Oakland therefore appears to stop, the degree-1 test sees a termination, and
it gets called a dead end. Shattuck Ave, Solano Ave, Marin Ave and Peralta Ave all came
up this way. None of them is a dead end.

The distribution makes the cause unambiguous. 59 terminations fall outside the
boundary; 53 of those sit within 25 m of the line and 52 within 1 m. Only one (Rugby
Ave, 145 m) is properly inside another jurisdiction. A further 38 sit *inside* the
boundary but under 25 m from it, which is the same artifact landing a metre on the
Berkeley side: Ninth St, Second St, Alcatraz Ave, Roanoke Rd. So the test is distance
to the line, not inside versus outside, and both conditions are applied.

Three of the 97 fell in a hill fire zone, where wrongly dropping a real cul-de-sac would
actually cost a resident something, so each was checked against OpenStreetMap, which is
not clipped at the city line:

- **Ajax Ln** is `highway=path` in OSM, not a road, and runs through to Ajax Place at both ends.
- **Chabolyn Ter** terminates at a three-way junction; the streets it joins are Oakland's.
- **Vicente Rd** continues a further 319 m past the point Berkeley's data stops.

All three connect or continue exactly where Berkeley's data ends, so nothing genuine is
lost. A termination on the edge of a clipped dataset carries no information in either
direction, and publishing "we cannot tell" as a dead-end marker would be the guesswork
this page says it does not do.

The clip runs on every build, in `build/build.py`, against `build/city_boundary.json`.
`build/data.json` is the untouched harvest, so the rule can be inspected and argued with
rather than being baked invisibly into the data.

### By council district

Of the 156:

| District | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dead ends | 28 | 24 | 2 | 4 | 15 | **52** | 9 | 22 |

District 6, the hills, has more than any other. Note that the Redistricting layer's
`CouncilMember` field is out of date, so this uses district numbers only.

### Known limits

These matter and are not hidden in the page either.

- **A termination is not always a cul-de-sac.** Where the centreline data splits a
  turning circle into several stubs, one physical dead end can be counted more than
  once. Arcade Ln is the clearest case.
- **A dead end here has not been checked on the ground** and may have a barrier or a
  path that opens in an emergency.
- **Straight-line distance is not drive time.** The station distance shown is
  as-the-crow-flies. SB 99's definition of an access impaired neighbourhood depends on
  a five-minute drive-time service area, which is a different and harder calculation.
- **Buildings are drawn at a uniform height** because the City's footprint layer
  carries none. Terrain is exaggerated 1.5x so slope reads.
- The harvest script that produced `build/data.json` was not kept. The endpoints above
  are enough to reproduce it, but it needs rewriting before the data can be refreshed.

## Build

`index.html` is generated. Edit `build/template.html`, not `index.html`.

```
python3 build/build.py
```

The template carries a `/*__DATA__*/ null` placeholder; the build substitutes
`build/data.json` into it and writes `index.html`.

## Licence

Code MIT. The underlying data is the City of Berkeley's and carries its own terms.
