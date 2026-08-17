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
