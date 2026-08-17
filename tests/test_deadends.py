"""Tests for the single-exit area derivation.

Every test here is a bug that actually shipped. The derivation has been wrong
three times, and each time the fault was invisible in the output because a wrong
answer and a right answer look identical when both are just a number. What
distinguished them was cheap to check and nobody was checking it.

  1. The network was filtered to Berkeley before the graph was built, so every
     street crossing the city line lost its far half and read as a cul-de-sac.
     Caught by: test_graph_is_regional, test_through_streets_are_not_areas.

  2. Segments were dropped by name keyword, which threw away Walker St for
     containing "walk" and Fountain Walk for the same reason. Fountain Walk is
     the south portal of the Northbrae Tunnel, so Solano Ave became single-exit.
     Caught by: test_real_roads_named_like_paths_are_kept.

  3. Degree-1 counting was used as a proxy for "one way out". It cannot see a
     neighbourhood hanging off a single junction, which is the case the page
     exists for.
     Caught by: test_panoramic_way_is_found.

And the meta-lesson, which is the most important test here: the old derivation's
answer moved between 29 and 77 depending on how it was tuned. An answer that
moves with an arbitrary parameter is not a measurement.
     Caught by: test_count_is_stable_across_snap_tolerance.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "build"))

import deadends  # noqa: E402


@pytest.fixture(scope="module")
def segments():
    return deadends.load_segments()


@pytest.fixture(scope="module")
def areas():
    berk, _segs, _all, _info = deadends.run(deadends.SNAP_M, quiet=True)
    return berk


def names_of(areas):
    return {n for a in areas for n in a["names"]}


def primary_names(areas):
    return {a["names"][0] for a in areas if a["names"]}


# --- the graph must be built on the whole region -----------------------------

def test_graph_is_regional(segments):
    """Filtering to Berkeley before building the graph is the original bug.

    It severs every street at the city line. Guard the property directly: the
    loaded network must contain other jurisdictions.
    """
    munis = {m for s in segments for m in s["muni"] if m}
    assert "Berkeley" in munis
    assert {"Oakland", "Albany"} <= munis, (
        f"network looks pre-filtered to Berkeley, found only {sorted(munis)}")


def test_results_are_berkeley_only(areas):
    for a in areas:
        assert "Berkeley" in a["muni"]


# --- known-good and known-bad cases ------------------------------------------

# These carry traffic straight through Berkeley. Any of them appearing as the
# principal street of a single-exit area means the network has been severed.
#
# Cedar St and Hilgard Ave are deliberately NOT on this list. Both were on it
# when it was first written, on the assumption that a named through street could
# not be a cul-de-sac. Both genuinely terminate at La Loma Ave in the hills, and
# OpenStreetMap has a degree-1 node 47 m and 40 m from the respective exits. The
# test was wrong, not the derivation. Check before adding a street here.
THROUGH_STREETS = [
    "SHATTUCK AVE", "SOLANO AVE", "PERALTA AVE",
    "UNIVERSITY AVE", "SAN PABLO AVE", "ASHBY AVE", "TELEGRAPH AVE",
    "NORTHBRAE TUNNEL", "SACRAMENTO ST", "GILMAN ST",
]

# Marin Ave was on this list too, and was carried for a while as a known-bad
# xfail on the theory that a 126 m hole in the centreline had severed it. That
# was wrong, and wrong because the check was made in the wrong place: OSM was
# queried around the area's EXIT node, over 100 m from the loose end, where
# Marin naturally shows degree 2 and 3. Queried at the loose end itself, OSM has
# Marin Avenue terminating at a degree-1 node 223 m out and joining an unnamed
# service road that dead-ends after 219 m. Upper Marin Ave really does have one
# way out. Check at the feature, not near it.



@pytest.mark.parametrize("street", THROUGH_STREETS)
def test_through_streets_are_not_areas(areas, street):
    assert street not in primary_names(areas), (
        f"{street} reported as a single-exit area; the network is severed "
        f"somewhere along it")


def test_panoramic_way_is_found(areas):
    """The case degree-1 counting could never see.

    Panoramic Way serves a large hill neighbourhood through one junction. There
    is no degree-1 node anywhere in it, so the old derivation missed it entirely
    while reporting Shattuck Ave as a dead end.
    """
    hits = [a for a in areas if "PANORAMIC WAY" in a["names"]]
    assert hits, "Panoramic Way is not reported as a single-exit area"
    biggest = max(hits, key=lambda a: a["metres"])
    assert biggest["metres"] > 3000, (
        f"Panoramic Way area is only {biggest['metres']} m, expected over 3 km")


def test_real_roads_named_like_paths_are_kept(segments):
    """Walker St and Fountain Walk are roads, not footpaths.

    A name-keyword filter dropped both. Fountain Walk is the transition segment
    at the south portal of the Northbrae Tunnel, so losing it severed the tunnel.
    """
    names = {s["name"] for s in segments}
    for road in ("WALKER ST", "FOUNTAIN WALK"):
        assert road in names, f"{road} was dropped from the drivable network"


def test_pedestrian_ways_are_excluded(segments):
    assert all(s["cls"] != "PEDESTRIAN" for s in segments)
    names = {s["name"] for s in segments}
    assert "ROSE WALK" not in names, "Rose Walk is a footpath and should be excluded"


def test_no_freeway_areas(areas):
    """A freeway runs off the edge of the extract, which makes it look
    single-exit when it is only unfinished. It is also not a neighbourhood."""
    for a in areas:
        for n in a["names"]:
            assert "FWY" not in n and "HWY" not in n and "I80" not in n, (
                f"freeway {n} reported as a single-exit area")


# --- the property that actually distinguishes a measurement from a guess -----

def test_count_is_stable_across_snap_tolerance():
    """The snapping tolerance is arbitrary. The answer must not depend on it.

    The previous derivation failed exactly here: its count moved between 29 and
    77 across reasonable settings, which meant it was reporting the tuning and
    not the city.
    """
    counts = {}
    for tol in (1.0, 2.0, 3.0, 4.0, 6.0, 8.0):
        berk, _s, _a, _i = deadends.run(tol, quiet=True)
        counts[tol] = len(berk)

    lo, hi = min(counts.values()), max(counts.values())
    spread = (hi - lo) / hi
    assert spread < 0.10, (
        f"area count moves {lo} to {hi} ({spread:.0%}) across snap tolerances "
        f"1-8 m; the derivation is reporting its tuning, not the network: {counts}")


def test_areas_have_geometry_and_an_exit(areas):
    for a in areas:
        assert a["paths"], f"{a['names'][:1]} has no geometry"
        assert len(a["exit"]) == 2
        assert -123 < a["exit"][0] < -122, "exit longitude is not in Berkeley"
        assert 37 < a["exit"][1] < 38, "exit latitude is not in Berkeley"
        assert a["metres"] > 0


# --- independent replication -------------------------------------------------

def test_confirmed_against_openstreetmap():
    """Stability says the answer does not depend on its own tuning. It says
    nothing about whether the answer is right. This asks a dataset surveyed by
    different people whether these areas really have one way out.

    93% of checkable areas confirm. The floor is set at 90% so a regression that
    quietly re-severs the network fails here even if the count stays stable,
    which is exactly what the old derivation did.
    """
    import validate_osm
    rate, tally, disputed = validate_osm.run()
    assert rate >= 0.90, (
        f"only {rate:.0%} of checkable areas confirmed by OSM "
        f"({tally['disputed']} disputed): {[d[1] for d in disputed][:8]}")


def test_panoramic_way_confirmed_by_osm():
    """The flagship finding, checked in the other dataset.

    It reported three exits until the validator stopped counting the same street
    as the outside world; two of the three led to Panoramic Place and Dwight
    Place, both inside the area.
    """
    import json as _json
    import pathlib as _pathlib
    import validate_osm
    areas = _json.loads((_pathlib.Path(validate_osm.HERE) / "deadends.json").read_text())
    area = max((a for a in areas if "PANORAMIC WAY" in a["names"]),
               key=lambda a: a["metres"])
    adj, pos, street = validate_osm.load_osm()

    import collections as _c
    import math as _m
    cell = 60.0
    grid = _c.defaultdict(list)
    for n, (x, y) in pos.items():
        grid[(int(x // cell), int(y // cell))].append(n)

    def lookup(px, py, r):
        found, rr = [], int(r // cell) + 1
        cx, cy = int(px // cell), int(py // cell)
        for i in range(cx - rr, cx + rr + 1):
            for j in range(cy - rr, cy + rr + 1):
                for n in grid.get((i, j), ()):
                    x, y = pos[n]
                    if _m.hypot(x - px, y - py) <= r:
                        found.append(n)
        return found

    clusters = validate_osm.exits_for(area, adj, pos, street, lookup)
    assert clusters is not None, "Panoramic Way has no OSM coverage"
    assert len(clusters) == 1, (
        f"OSM says Panoramic Way has {len(clusters)} exits: "
        f"{[sorted(c[1])[:2] for c in clusters]}")


def test_agrees_with_the_city_consultants():
    """The strongest check available: KLD Engineering's SB 99 study, done for the
    City, names every access impaired neighbourhood it found.

    Exact agreement is impossible by construction. KLD works on residential
    parcels and counts blocks closed by removable bollards and diverters, which no
    street centreline records; this page works on street topology and also reports
    campus and marina roads that front no homes. 61% overlap with 16 of the misses
    explained by barriers is the honest ceiling for centreline data. The floor is
    set at 55% so a regression that severs or merges the network shows up here
    against real ground truth rather than against another computation.
    """
    import compare_kld
    rate, agreed, missed, barrier, extra = compare_kld.run()
    assert rate >= 0.55, (
        f"only {rate:.0%} of KLD's access impaired neighbourhoods reproduced; "
        f"missing {sorted(missed)[:10]}")


def test_panoramic_and_the_hill_courts_match_kld():
    """Spot checks on the ones that matter most: the largest area on the page and
    the classic hill cul-de-sacs."""
    import compare_kld
    _rate, agreed, _m, _b, _e = compare_kld.run()
    for street in ("PANORAMIC WAY", "CORONA CT", "EL PORTAL CT", "PARNASSUS CT",
                   "HILL CT", "HIGH CT", "SUMMIT RD", "CAMPUS DR"):
        assert street in agreed, f"{street} is in KLD's list but not in ours"


# --- traffic barriers --------------------------------------------------------

def test_traffic_circles_are_not_treated_as_closures():
    """The layer holds 147 records: 87 diverters and 60 traffic circles. A
    roundabout calms traffic, it does not stop you driving through, and counting
    the circles would sever 60 junctions that are wide open."""
    import json as _json
    import pathlib as _pathlib
    bars = _json.loads((_pathlib.Path(deadends.HERE) / "barriers.json").read_text())
    assert len(bars) == 87, f"expected 87 diverters, got {len(bars)}"
    assert all("circle" not in (b.get("cat") or "").lower() for b in bars)


def test_only_mid_block_closures_are_cut():
    """48 of the 55 full diverters sit at junctions, where a diagonal barrier
    partitions the legs into two pairs and this data cannot say which pair.
    ROTATION is empty on all 87 records. Cutting on a guess would invent
    single-exit areas, so those are recorded and drawn but never modelled."""
    _b, _s, _a, info = deadends.run(deadends.SNAP_M, quiet=True)
    assert info["cut"] == 7, f"expected 7 mid-block cuts, got {info['cut']}"
    assert info["unmodelled"] == 48, (
        f"expected 48 junction diverters left unmodelled, got {info['unmodelled']}")


def test_barriers_add_a_real_area_and_remove_none():
    """The acceptance test for the whole barrier idea, in both directions.

    Agreement with the City's consultants must go UP, and no area may appear that
    they do not list. Both rising would mean we had over-severed, which is the
    error this project exists to avoid. In practice the mid-block cuts recover
    exactly one neighbourhood, Laurel St, and lose nothing.
    """
    import compare_kld
    before, _s, _a, _i = deadends.run(deadends.SNAP_M, quiet=True, barriers=False)
    after, _s2, _a2, _i2 = deadends.run(deadends.SNAP_M, quiet=True, barriers=True)
    nb = {compare_kld.norm(n) for a in before for n in a["names"] if n}
    na = {compare_kld.norm(n) for a in after for n in a["names"] if n}
    kld = set(compare_kld.kld_entries())

    assert not (nb - na), f"barriers removed areas: {sorted(nb - na)}"
    gained = na - nb
    assert gained, "barriers changed nothing at all"
    assert gained <= kld, (
        f"barriers invented areas the City's study does not list: {sorted(gained - kld)}")
