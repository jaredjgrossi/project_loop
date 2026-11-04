"""Write the main-screen fixture for the app: the Kips Bay Library stand-in, 3 mi, 7:00, Training.

    python -m api.scripts.ui_fixture [--out out/fixtures]

Runs make_loop with the review page's settings (the reviewer's runs off, so nothing personal goes in) and writes
`kips3-ui.json`: the request, the #1 route's full GeoJSON (summary, markers, stretches and pieces by kind), the top 3
outlines with labeled distances, and pool stats. Also `kips3-ui.gpx`, the #1 with mile and turnaround waypoints.
The start is a public library standing in for the reviewer's home area (decision 011); the output is git-ignored.
"""

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

START_ID = "kips-bay"
MILES = 3
SETTINGS = "3 mi, 7:00, Training preset; generated without the reviewer's runs, as the review page is"


def top3_entry(rank: int, fc: dict) -> dict:
    """One route of the top 3 as the app draws it: its outline and its summary distance, with unit, trust label and
    source, the same object the #1's summary carries."""
    route = fc["features"][0]
    p = route["properties"]
    return {"rank": rank, "kind": p["kind"], "label": p["label"], "score": p["score"],
            "distance": p["summary"]["distance"], "geometry": route["geometry"]}


def build_fixture(ranks: list[dict], pool: dict, commit: str, generated_at: str) -> dict:
    first = ranks[0]
    return {
        "about": {"generated_at": generated_at, "commit": commit,
                  "start": "Kips Bay Library, a public stand-in for the reviewer's home area (decision 011)",
                  "settings": SETTINGS},
        "request": first["features"][0]["properties"]["request"],
        "route": first,
        "top3": [top3_entry(r, fc) for r, fc in enumerate(ranks, 1)],
        "pool": {"candidates": len(pool["pool"]), "best_of": pool["best_of"],
                 "statuses": dict(Counter(e["status"] for e in pool["pool"])), "timing": pool["timing"]},
    }


def main(argv: list[str] | None = None) -> int:
    from api.geocoding import GeocodeResult
    from api.gpx import route_to_gpx
    from api.markers import mile_points, turnarounds
    from api.scripts import make_loop as ml
    from evals.routes.live import load_starts

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("out/fixtures"))
    args = ap.parse_args(argv)

    st = load_starts()[START_ID]
    place = GeocodeResult(lat=st["lat"], lon=st["lon"], label="Kips Bay Library (public stand-in)",
                          borough="Manhattan", postalcode="", housenumber="", street="", source="stored",
                          source_id=START_ID, match_type="stored", confidence=1.0)
    tmp = Path(tempfile.mkdtemp())
    code = ml.run(st["address"], MILES, out=tmp / "route.geojson", top=3, geocode_fn=lambda q: place,
                  mode="training", start_time="07:00", feature_anchor_fn=ml.DB_FEATURE_ANCHOR_SOURCES,
                  stretch_fn=ml.db_stretches, closures_fn=ml.db_closures, pool_out=tmp / "pool.json",
                  context_factory=lambda lights, grid, start: ml.context_for(lights, grid, use_prior=False,
                                                                             start=start))
    if code != 0:
        return code
    ranks = [json.loads((tmp / f"route-rank{r}.geojson").read_text()) for r in (1, 2, 3)]
    pool = json.loads((tmp / "pool.json").read_text())
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    fixture = build_fixture(ranks, pool, commit, datetime.now().isoformat(timespec="minutes"))

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "kips3-ui.json").write_text(json.dumps(fixture, indent=1))
    first = ranks[0]["features"][0]
    coords = first["geometry"]["coordinates"]
    wpts = ([(m["lat"], m["lon"], f"Mile {m['mile']}") for m in mile_points(coords)]
            + [(t["lat"], t["lon"], "Turnaround") for t in turnarounds(coords)])
    (args.out / "kips3-ui.gpx").write_text(
        route_to_gpx(f"Loop Kips Bay 3 mi: {first['properties']['label']}", coords, None, wpts))
    print("wrote", args.out / "kips3-ui.json", "and", args.out / "kips3-ui.gpx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
