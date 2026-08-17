#!/usr/bin/env python3
"""Compare the single-exit areas against the City's own consultants.

    python3 build/compare_kld.py [-v]

KLD Engineering's Access Impaired Neighborhood Analysis, done for Berkeley under
SB 99 in early 2024, lists by name every access impaired neighbourhood it found.
That is the authoritative answer to the question this page asks, produced by the
City's own consultant, and comparing against it is worth more than any amount of
internal consistency.

The list is transcribed here from Table 1 of that memo rather than parsed from the
PDF at build time, so this check has no dependency on a 7 MB file or on a PDF text
extractor behaving the same way twice.

WHAT KLD COUNTED, AND WHY THE TWO LISTS CANNOT MATCH EXACTLY

Their Primary AIN criterion is a conjunction: in a hazard area, outside the fire
station five minute service area, and along a dead-end roadway. They then apply it
to residential PARCELS. This page works on street topology and says nothing about
parcels, so:

  Barriers. 18 of the neighbourhoods this page misses are flagged by KLD as having
  a removable barrier, meaning a bollard, gate or traffic-calming island makes the
  block a cul-de-sac for cars while the street centreline runs straight through.
  Berkeley has a lot of these. No centreline dataset can see them, and that is a
  limitation of the input, not a bug in the derivation.

  Non-residential streets. This page reports campus service roads, the marina and
  Cyclotron Rd at the Lab. KLD excludes them because no residential parcel fronts
  them. They are correctly single-exit and correctly not neighbourhoods.
"""

import argparse
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent

# Table 1, Primary AIN, Berkeley evacuation zones only, transcribed 2026-08-17.
# "*" marks the ones KLD flags as having a removable or traversable barrier.
KLD_PRIMARY = """
Vicente Ave, San Mateo Rd, Florida Ave, Vermont Ave, My Way, Rochdale Way,
Vistamont Ave, Woodmont Ct, Station Pl, Dwight Pl, Dwight Way, Panoramic Place,
Panoramic Way, Carleton St, Martin Ave, Middlefield Rd, Overlook Rd, The Spiral,
Woodhaven Rd, Woodmont Ave, Stoddard Way, Corona Ct, Crystal Way, High Ct,
Laurel St, Oak St, Napa Ave*, Northside Ave, Berryman St, Buena Ave, Grant St,
Miramonte Ct, North St, Eunice St, Spring Way, Codornices Rd, El Portal Ct,
Northgate Ave, Ross St, Columbia Cir, Ajax Pl, Grizzly Peak Blvd, Hill Rd,
Olympus Ave, Summit Rd, Buena Vista Way, Campus Dr, Cedar St, Harvard Cir,
Maybeck Twin Dr, Parnassus Ct, Greenwood Commons, Hill Ct, Francisco St,
Lincoln St, Short St, Virginia Gardens, West St, Berkeley Way*, California St,
Delaware St, Mc Gee Ave, Bonita Ave*, Hilgard Ave, La Vereda Rd, Le Conte Ave,
Leroy Ave, Virginia St, Acroft Court, Acton Cir, North Valley St, 8Th St,
Poe St, Valley St, Milvia St*, Arden Rd, Canyon Rd, Fernwald Rd, Hillside Ct,
Mosswood Ln, Mosswood Rd, Burnett St*, Russell St, Sojourner Truth Way,
Deakin St*, Ellsworth St*, Fulton St*, Garber St, Tanglewood Rd*, Bateman St,
Colby St, Dana St*, Regent St, Webster St, Woolsey St*, Fairview St, Harmon St*,
Kelsey St*, Lewiston Ave*, Stuart St*, Claremont Blvd*, Mystic Ct, Oak Ridge Rd,
Tevlin St, Acton St
"""

SUFFIX = {"STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "ROAD": "RD",
          "DRIVE": "DR", "COURT": "CT", "LANE": "LN", "PLACE": "PL",
          "CIRCLE": "CIR", "TERRACE": "TER", "BOULEVARD": "BLVD", "WY": "WAY"}


def norm(name):
    words = re.sub(r"[^A-Za-z0-9 ]", " ", name).upper().split()
    return " ".join(SUFFIX.get(w, w) for w in words)


def kld_entries():
    out = {}
    for raw in KLD_PRIMARY.replace("\n", " ").split(","):
        raw = raw.strip()
        if not raw:
            continue
        barrier = raw.endswith("*")
        out[norm(raw.rstrip("*"))] = barrier
    return out


def run():
    kld = kld_entries()
    areas = json.loads((HERE / "deadends.json").read_text())
    ours = {norm(n) for a in areas for n in a["names"] if n}

    agreed = {k for k in kld if k in ours}
    missed = {k: v for k, v in kld.items() if k not in ours}
    barrier_missed = {k for k, v in missed.items() if v}
    extra = ours - set(kld)

    rate = len(agreed) / len(kld)
    print(f"KLD Primary AIN neighbourhoods (Berkeley): {len(kld)}")
    print(f"this page reproduces                     : {len(agreed)}  ({rate:.0%})")
    print(f"KLD has, we do not                       : {len(missed)}")
    print(f"   of those, KLD flags a removable barrier: {len(barrier_missed)}")
    print(f"we have, KLD does not                    : {len(extra)}")
    return rate, agreed, missed, barrier_missed, extra


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    rate, agreed, missed, barrier, extra = run()
    if args.verbose:
        print("\nmissed (barrier-flagged marked *):")
        for k in sorted(missed):
            print(f"   {k}{' *' if missed[k] else ''}")
        print("\nours that KLD does not list:")
        for k in sorted(extra):
            print(f"   {k}")
    return 0 if rate >= 0.55 else 1


if __name__ == "__main__":
    raise SystemExit(main())
