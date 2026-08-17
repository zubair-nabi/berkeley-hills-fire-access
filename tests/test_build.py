"""Tests for the page build itself.

These are cheap and they guard the failures that made the page look broken to a
reader rather than wrong to an analyst: a placeholder left unsubstituted, a data
file that parses but is empty, a stat quoted in prose that no longer matches the
data behind it.
"""

import json
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


@pytest.fixture(scope="module")
def built():
    r = subprocess.run([sys.executable, str(BUILD / "build.py")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, f"build failed:\n{r.stdout}\n{r.stderr}"
    return (ROOT / "index.html").read_text()


def test_placeholder_is_substituted(built):
    assert "/*__DATA__*/ null" not in built, "the data placeholder survived the build"
    assert "__DATA__" not in built


def test_page_carries_data(built):
    m = re.search(r"const DATA\s*=\s*(\{.*?\});", built, re.S)
    assert m, "no DATA object found in the built page"
    data = json.loads(m.group(1))
    for key in ("fireZones", "stations", "streets", "narrow", "chipper", "meta"):
        assert data.get(key), f"{key} is missing or empty in the built page"


def test_no_em_dashes(built):
    """A house style rule, and the kind of thing that silently creeps back."""
    assert "—" not in built
    for doc in ("README.md",):
        assert "—" not in (ROOT / doc).read_text(), f"em dash in {doc}"


def test_prose_figures_match_the_data(built):
    """The footer quotes counts. They are interpolated from meta, but a hardcoded
    number creeping into the copy is exactly how the page came to claim 253."""
    m = re.search(r"const DATA\s*=\s*(\{.*?\});", built, re.S)
    meta = json.loads(m.group(1))["meta"]
    stale = [n for n in ("253", "194", "156") if f">{n} " in built or f" {n} across" in built]
    assert not stale, (
        f"superseded dead-end figures {stale} appear literally in the page; "
        f"meta now says {meta.get('singleExitAreas', meta.get('berkeleyNamedRoadDeadEnds'))}")


def test_readme_district_table_is_current():
    """districts.py is the source of truth; the README is a copy of its output.

    The table sat stale for a commit after the derivation changed, quoting counts
    from a superseded method. A copy that can drift silently is worse than no copy.
    """
    import subprocess
    r = subprocess.run([sys.executable, str(BUILD / "districts.py")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    row = next((l for l in r.stdout.splitlines() if l.startswith("| Areas |")), None)
    assert row, f"districts.py printed no Areas row:\n{r.stdout}"
    readme = (ROOT / "README.md").read_text()
    assert row.strip() in readme.replace("**", ""), (
        f"README district table is stale.\n  expected: {row.strip()}")


def test_readme_quotes_the_current_count():
    """The README is the audit trail. If it disagrees with the derivation, the
    audit trail is wrong, which is worse than having none."""
    dj = BUILD / "deadends.json"
    if not dj.exists():
        pytest.skip("run build/deadends.py first")
    n = len(json.loads(dj.read_text()))
    readme = (ROOT / "README.md").read_text()
    assert f"{n} single-exit areas" in readme, (
        f"README does not state the current count of {n} single-exit areas")
    assert str(n) in readme, (
        f"README does not mention the current count of {n} single-exit areas")


# --- the layer snapshot ------------------------------------------------------
#
# Every assertion here is a bug harvest_layers.py shipped on its first run, and
# every one was silent: the page still built, still rendered, still answered.
# It just answered wrong.

@pytest.fixture(scope="module")
def data():
    return json.loads((BUILD / "data.json").read_text())


def test_all_three_fire_zones_present(data):
    """Zone 1 matters. Without it the page cannot distinguish "you are in zone 1,
    outside the hill inspection zones" from "you are in no mapped zone", which
    are different statements. A filter to zones 2 and 3 dropped it."""
    zones = sorted(z["a"]["PLN_HILL_ZONE"] for z in data["fireZones"])
    assert zones == [1, 2, 3], f"expected hill zones 1, 2 and 3, got {zones}"


def test_seven_fire_stations(data):
    """Police/PublicSafety/0 is called "Fire Stations" and holds one record, an
    administrative office. Harvesting it cut the page from seven stations to one
    and nothing complained."""
    assert len(data["stations"]) == 7, f"expected 7 stations, got {len(data['stations'])}"
    for s in data["stations"]:
        assert s["name"] and s["addr"], f"station missing name or address: {s}"
        assert -122.35 < s["x"] < -122.20 and 37.83 < s["y"] < 37.92


def test_layers_are_berkeley_only(data):
    """The narrow-streets layer is regional. Unfiltered it brings in Caldecott
    Ln, 54th St and the Emeryville waterfront."""
    names = {s["s"] for s in data["narrow"]}
    for foreign in ("CALDECOTT LN", "54TH ST", "59TH ST"):
        assert foreign not in names, f"{foreign} is not in Berkeley"


def test_no_layer_hit_a_page_limit(data):
    """ArcGIS caps a response at 1000 or 2000 rows and says nothing when it
    truncates. The narrow-streets list came back as exactly 1000 before the
    harvester paged."""
    for key, n in (("narrow", len(data["narrow"])), ("streets", len(data["streets"]))):
        assert n not in (1000, 2000), (
            f"{key} has exactly {n} rows, which is an ArcGIS page limit, "
            f"so the harvest was probably truncated")


def test_hazard_layers_are_populated(data):
    h = data["hazards"]
    assert len(h["landslide"]) > 20, "landslide zones look empty"
    assert len(h["fault"]) >= 1, "Alquist-Priolo zones look empty"
    assert len(h["calfireVHFHSZ"]) >= 1, "CalFire very high severity zone missing"


def test_distances_read_as_metres_below_a_kilometre(built):
    """49 m rendered as "0.05 km" because the formatter always divided by 1000."""
    assert "function km(m)" in built
    assert 'm>=1000 ? (m/1000).toFixed(1)+" km" : m+" m"' in built
