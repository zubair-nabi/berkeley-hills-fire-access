# Berkeley hills fire access

A map of the things that decide how fast you can get out of the Berkeley hills, and
how fast a fire engine can get in: which streets have one way out, which are too
narrow for an engine to pass a car coming down, the Hill Fire Zones, landslide and
fault zones, chipper drop areas, and the fire stations.

Type an address, get the answer for that address.

**Unofficial.** Berkeley Fire Department is the authority on all of this. If anything
here disagrees with them, they are right. This page draws no evacuation route and
never will.

## What it is

One self-contained HTML file. No server, no build step at request time, no tracking,
no network calls except the map tiles and the City's own ArcGIS server. Open it from
a USB stick if you like. It prints.

## Why

The City commissioned two studies from KLD Engineering in early 2024:

- **Access Impaired Neighborhood Analysis**, under SB 99
- **Evacuation Route Safety, Capacity, and Viability Analysis**, under AB 747

Both are careful pieces of work and both are published as figures inside PDFs. None
of it is in the City's open data portal, which carries 66 datasets and not one on
evacuation, access impairment, fire zones, or hazards. So a resident who wants to
know about their own street has to read a report and squint at a map.

The inputs are all public. This computes the per-address answer from them.

## What "one way out" means here

Not "a street with one end". That is a different thing and it is the wrong thing.

The network is built as a graph and searched for **articulation points**: junctions
that everything behind them has to pass through. Whatever sits behind one is a
single-exit area, and the junction is its exit.

Counting streets with one end gets it wrong in both directions:

- **It over-counts.** One cul-de-sac digitised as three stubs counts three times.
  Arcade Ln did exactly that.
- **It under-counts, which is worse.** A cul-de-sac with a turning circle is a loop
  and has no loose end at all. And a whole neighbourhood can hang off a single
  junction without one street in it looking like a dead end. That is the SB 99
  access-impaired case, the reason this page exists, and a loose-end count cannot
  see it.

Berkeley has **138 single-exit areas** holding **24.1 km of street**. The largest is
Panoramic Way: 4.5 km of road across 40 segments, reaching the rest of the city
through one junction. A loose-end count scored it zero.

## Data

Everything comes from layers the City of Berkeley publishes openly, via
`gis.cityofberkeley.info/arcgis/rest/services`.

| Layer | Source | Count |
| --- | --- | --- |
| Street network | `Planning/Accela/3` | 6,971 segments, regional |
| Single-exit areas | derived, see below | 138 |
| Narrow streets | City's published narrow-streets list | 882 segments |
| Hill Fire Zones 2 and 3 | `Planning` | 3 polygons |
| CalFire severity zones | State FRAP, via the City | |
| Landslide and Alquist-Priolo fault zones | State, via the City | |
| Chipper areas | Fire Department | 8 areas |
| Fire stations | Fire Department | 7 |
| Building footprints | fetched per neighbourhood on search | |
| Address points | 62,090 published points | |

The street layer is a routable network, not just geometry. It carries jurisdiction
per segment (`MUNILEFT`/`MUNIRIGHT`), grade separation (`F_ZLEV`/`T_ZLEV`), road
class, one-way direction and pavement width. The derivation uses all of those
instead of guessing at them geometrically.

Snapshot in `build/streets_raw.json.gz`, harvested 2026-08-16.

## How the derivation works, and what went wrong three times

Each of these shipped. Each is now a test.

**The network was filtered to Berkeley before the graph was built.** The layer is
regional. Cutting it to Berkeley first severed every street at the city line, so
Shattuck, Solano, Marin and Peralta all came out as cul-de-sacs. The graph is now
built on the whole region and Berkeley is selected from the *results*.
Guarded by `test_graph_is_regional`.

**Segments were dropped by name keyword.** A filter removing names containing PATH,
TRAIL, STEPS or WALK also removed Walker St and Fountain Walk. Fountain Walk is a
`MAJOR` road forming the south portal of the Northbrae Tunnel, so dropping it severed
the tunnel and made Solano Ave single-exit. Drivability now comes from `ROADCLASS`
alone, which already classes the real footpaths as `PEDESTRIAN`.
Guarded by `test_real_roads_named_like_paths_are_kept`.

**Loose ends were counted as dead ends.** Replaced with articulation-point analysis,
described above. Guarded by `test_panoramic_way_is_found`.

Three repairs run before the analysis:

- **Portal repair.** Keying nodes by z-level is what stops an overpass reading as a
  junction, but it also severs a tunnel wherever the data omits the transition
  segment. At a true overpass both levels carry through traffic; at a broken portal
  the severed side has degree 1. Only the latter is merged.
- **Gap bridging.** The centreline has holes at rail crossings and divided roadways.
  Two loose ends of the same street within 90 m are two sides of one hole. University
  Ave produced four false areas of 85 to 89 m before this.
- **Missing-junction join.** A loose end within 22 m of another street's node is an
  unrecorded junction, not a cul-de-sac head.

### The test that matters most

The previous derivation's answer moved between 29 and 77 depending on how the
validator was tuned. An answer that moves with an arbitrary parameter is not a
measurement, and that instability was the only reliable signal that it was wrong.

The current one is checked for exactly that. Across snap tolerances from 1 m to 8 m
the count stays at 137 or 138. `test_count_is_stable_across_snap_tolerance` fails the
build if the spread exceeds 10%.

```
snap  1.0 m   areas 301   Berkeley 137
snap  2.0 m   areas 302   Berkeley 138
snap  4.0 m   areas 302   Berkeley 138
snap  8.0 m   areas 300   Berkeley 137
```

### By council district

| District | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Areas | 19 | 18 | 1 | 2 | 15 | **49** | 9 | 25 |
| Street behind them | 2.7 km | 4.6 km | 0.0 km | 0.3 km | 1.4 km | 6.1 km | 1.7 km | **7.3 km** |

Two different answers depending on what you count. District 6 has the most areas.
District 8 has the most road behind them, because Panoramic Way's 4.5 km sits there
and one large area outweighs a dozen short cul-de-sacs. Quoting only the count would
be the more flattering number for the hills and the less true one.

Run `python3 build/districts.py` to regenerate. An area is assigned to the district
holding most of its street length rather than the one holding its exit junction,
because exits often sit on the boundary road between two districts, which is exactly
where an arbitrary choice would flip the count. The Redistricting layer's
`CouncilMember` field is out of date, so only district numbers are used.

### Known limits

- **Nothing is checked on the ground.** A gate, bollard or private drive can add a
  way out the map cannot see.
- **Straight-line distance is not drive time.** SB 99's access-impaired definition
  depends on a five-minute drive-time service area, which is a harder calculation.
- **Buildings are drawn at a uniform height** because the City's footprint layer
  carries none. Terrain is exaggerated 1.5x so slope reads.
- **Only the street layer has a harvest script.** The other layers in
  `build/data.json` predate it and cannot yet be refreshed from source.

## Build

`index.html` is generated. Edit `build/template.html`, not `index.html`.

```
python3 build/harvest_streets.py   # only to refresh from the City, writes streets_raw.json
python3 build/deadends.py          # derive single-exit areas -> deadends.json
python3 build/deadends.py --sweep  # the stability check, by hand
python3 build/build.py             # assemble index.html
python3 build/districts.py         # regenerate the council district table
python3 -m pytest tests/           # 24 tests
```

CI runs the tests on every push and fails if `deadends.json` or `index.html` are
stale with respect to their inputs. It reads the committed snapshot and never calls
the City's server, so a refresh is always a deliberate, reviewable commit.

## Licence

Code MIT. The underlying data is the City of Berkeley's and carries its own terms.
