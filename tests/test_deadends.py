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
    berk, _segs, _all = deadends.run(deadends.SNAP_M, quiet=True)
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
        berk, _s, _a = deadends.run(tol, quiet=True)
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
