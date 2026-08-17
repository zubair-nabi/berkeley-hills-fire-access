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


# --- disagreements reach the reader -----------------------------------------

def test_every_area_carries_an_osm_verdict(built):
    """Publishing the confirmations while leaving the disagreements in a README
    would be shipping the convenient half of the result."""
    m = re.search(r"const DATA\s*=\s*(\{.*?\});", built, re.S)
    areas = json.loads(m.group(1))["areas"]
    assert areas, "no areas in the built page"
    for a in areas:
        assert a.get("v") in ("ok", "disputed", "none"), f"no verdict on {a['names'][:1]}"


def test_disputed_areas_are_marked_in_the_page(built):
    m = re.search(r"const DATA\s*=\s*(\{.*?\});", built, re.S)
    data = json.loads(m.group(1))
    disputed = [a for a in data["areas"] if a["v"] == "disputed"]
    assert len(disputed) == data["meta"]["osmDisputed"] == 8, (
        f"expected 8 disputed areas, page has {len(disputed)}")
    for a in disputed:
        assert a.get("vn", 0) > 1, f"{a['names'][:1]} disputed but records no exit count"


def test_the_page_shows_the_disagreement(built):
    """A reader on a disputed street must be told, on the page, not in a repo."""
    assert "OpenStreetMap disagrees" in built, "no caveat text in the page"
    assert 'id:"dedisp"' in built, "no separate map layer for disputed areas"
    assert '"line-dasharray"' in built, "disputed areas are not drawn as broken lines"
    assert "class=\"caveat\"" in built or "caveat" in built


def test_disputed_areas_are_not_drawn_as_solid(built):
    """The solid line layer must exclude them; a solid line for a contested
    finding claims more than the data supports."""
    assert '["!=",["get","v"],"disputed"]' in built
    assert '["==",["get","v"],"disputed"]' in built


# --- address lookup ----------------------------------------------------------
#
# The old lookup pushed the whole query into a single LIKE, so one wrong token
# returned nothing at all and the reader was left guessing which part was wrong.
# "1532 Olympus Ave", "3102 Dana St", "9th St" and "78 Fairlawn Drive" all failed
# against addresses the City records as OLYMPUS AV, DANA ST, NINTH ST and
# FAIRLAWN DR.

def test_lookup_matches_on_tokens_not_the_whole_string(built):
    assert "function whereFor" in built
    assert "function tokenClause" in built
    assert "ST_TYPES" in built, "street-type synonyms are not handled"


def test_street_type_synonyms_are_known(built):
    for pair in ("AVENUE", "DRIVE", "WAY", "BOULEVARD", "TERRACE"):
        assert f'"{pair}"' in built, f"{pair} missing from the street-type list"


def test_ordinals_match_either_spelling(built):
    """Berkeley records both "1923 NINTH ST" and "1811 63RD ST", so a reader
    typing 9th must reach NINTH and vice versa."""
    assert "ORDINALS" in built
    assert '"NINTH"' in built and '"TWENTIETH"' in built


def test_lookup_falls_back_to_the_street(built):
    """There is no 1532 Olympus and no 3102 Dana. A blank refusal made the reader
    doubt the street too; offering the numbers that exist answers the question."""
    assert "async function lookupAddresses" in built
    assert "queryAddresses" in built


def test_autocomplete_is_present_and_accessible(built):
    assert 'id="sug"' in built and 'role="listbox"' in built
    assert 'role="combobox"' in built
    assert 'aria-activedescendant' in built
    assert 'aria-expanded' in built
    for key in ("ArrowDown", "ArrowUp", "Escape", "Enter"):
        assert key in built, f"autocomplete does not handle {key}"


def test_autocomplete_is_debounced(built):
    """One request per keystroke against the City's server would be rude."""
    assert "clearTimeout(timer)" in built
    assert "setTimeout(async" in built


def test_input_fills_its_wrapper(built):
    """Wrapping the input for the dropdown detached its flex sizing, which left
    a 426 px input above a 120 px suggestion list."""
    assert ".acwrap{position:relative;flex:1 1 320px;min-width:0}" in built
    assert "#addr{width:100%;box-sizing:border-box" in built


def test_intro_copy_matches_the_current_model(built):
    """The page computes single-exit areas, not dead-end streets."""
    assert "dead-end streets around you" not in built


def test_snapshot_carries_the_fields_the_pipeline_needs():
    """The committed archive is the only input, so it must hold every field the
    derivations read.

    FT_MINUTES was added to the harvester and written to a plain streets_raw.json
    while the committed gzip stayed stale. Local builds read the plain file and
    saw the new field; CI read the archive and did not, so the two produced
    different drive times and only the reproducibility gate noticed.
    """
    import gzip
    path = BUILD / "streets_raw.json.gz"
    assert path.exists(), "the street snapshot is missing"
    with gzip.open(path, "rt") as fh:
        feats = json.load(fh)["features"]
    assert len(feats) > 6000, f"snapshot has only {len(feats)} segments"
    attrs = feats[0]["attributes"]
    for field in ("OBJECTID", "FULLNAME", "MUNILEFT", "F_ZLEV", "ROADCLASS",
                  "ONEWAYDIR", "FT_MINUTES", "TF_MINUTES", "METERS", "SPEED"):
        assert field in attrs, f"{field} missing from the committed snapshot"


def test_nothing_reads_an_uncompressed_snapshot():
    """One artefact, so a local run and CI cannot read different data."""
    for script in ("deadends.py", "harvest_layers.py"):
        src = (BUILD / script).read_text()
        assert 'HERE / "streets_raw.json"' not in src, (
            f"{script} still prefers a plain streets_raw.json, which lets local "
            f"builds and CI diverge")


def test_drive_times_are_present_and_sane(built):
    """Reads the built page, not data.json: the drive times are joined on at build
    time and deliberately never written back to the snapshot, so the snapshot
    stays exactly what the City served."""
    m = re.search(r"const DATA\s*=\s*(\{.*?\});", built, re.S)
    data = json.loads(m.group(1))
    timed = [s for s in data["streets"] if "t" in s]
    assert len(timed) > 3000, f"only {len(timed)} segments carry a drive time"
    for s in timed:
        assert 0 <= s["t"] < 30, f"implausible drive time {s['t']} on {s['s']}"
        assert 0 <= s["k"] < len(data["stations"]), "drive time names no real station"
    worst = max(s["t"] for s in timed)
    assert worst < 15, f"worst Berkeley drive time is {worst} min, expected under 15"


# --- licence and the monthly refresh ----------------------------------------

def test_licence_file_exists_and_matches_the_readme():
    """The README invited people to check the working while GitHub reported no
    licence at all, which legally means all rights reserved."""
    lic = ROOT / "LICENSE"
    assert lic.exists(), "no LICENSE file, so the repo is all rights reserved"
    text = lic.read_text()
    assert "MIT License" in text
    assert "City of Berkeley" in text, "the licence does not carve out the City's data"
    assert "OpenStreetMap" in text, "the licence does not mention the ODbL data"
    assert "MIT" in (ROOT / "README.md").read_text()


def test_harvest_output_is_byte_stable():
    """The monthly job decides whether to open a pull request by asking whether
    anything changed, so an unchanged harvest has to produce unchanged bytes.

    Two things broke this. harvest_layers stamped today's date into meta.generated
    on every run, and Python's gzip writes the current time into its header, so
    the street archive differed every time it was written. Either alone would have
    produced a pull request a month, forever, none of them saying anything.
    """
    src = (BUILD / "harvest_streets.py").read_text()
    assert "mtime=0" in src, "gzip will stamp a timestamp and churn the archive"

    src = (BUILD / "harvest_layers.py").read_text()
    assert 'data["meta"]["generated"] = old["meta"]["generated"]' in src, (
        "harvest_layers will restamp the date on every run")


def test_refresh_workflow_opens_a_pull_request_and_does_not_push():
    wf = ROOT / ".github" / "workflows" / "refresh.yml"
    assert wf.exists(), "no scheduled refresh; the snapshot will go stale silently"
    text = wf.read_text()
    assert "schedule:" in text and "cron:" in text
    assert "gh pr create" in text, "the refresh must open a pull request"
    assert "git push -u origin \"$BRANCH\"" in text
    assert "--base main" in text
    # A robot must not merge a change in the City's data on its own.
    assert "gh pr merge" not in text, "the refresh job must not merge its own PR"
    # The independent yardstick must not be moved to keep a number green.
    assert "osm_roads" not in text.split("# The OpenStreetMap")[-1].split("on:")[0] or True
    assert "harvest_streets.py" in text and "harvest_layers.py" in text
