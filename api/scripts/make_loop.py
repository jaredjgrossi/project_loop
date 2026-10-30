"""Make running loops from an NYC address.

    python -m api.scripts.make_loop "11 Madison Ave, Manhattan" 4

Geocodes the address, finds the local street grid, generates grid-aligned rectangle
loops (or GraphHopper round trips where there is no grid), ranks them by shape, prints
the real distance and shape numbers, and saves GeoJSON (open it at geojson.io).
"""

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path

import psycopg

from etl.load import database_url

from api.generate import TOLERANCE_PCT, Candidate, GenerationResult, generate_loops
from api.geocoding import GeocodeError, GeocodeResult, geocode
from api.grid import GridEstimate
from api.routing import RoutingError, request_round_trip, request_route, route_to_geojson
from api.streets import grid_at

OUT_DIR = Path(__file__).resolve().parents[2] / "out"
MIN_MILES, MAX_MILES = 0.5, 30.0


def output_path_for(address: str, miles: float) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    return OUT_DIR / f"loop-{slug}-{miles:g}mi.geojson"


def current_grid(lat: float, lon: float) -> GridEstimate:
    with psycopg.connect(database_url()) as conn:
        return grid_at(conn, lat, lon)


def print_candidate(rank: int, c: Candidate) -> None:
    d = c.shape.as_dict()
    print(f"\n#{rank}  {c.label}   shape score {c.score:.0f}/100")
    print(f"    Distance:  {c.route.distance_m / 1609.344:.2f} mi  ({c.miss_pct:+.0f}% from the request)")
    print(f"    Turns:     {d['turns']}  ({d['turns_per_mile']} per mile)")
    print(f"    Straight:  longest run {d['longest_straight_m']} m; {d['pct_in_long_runs']}% of the route is on runs of 500 m or more")
    print(f"    Shape:     {d['retraced_pct']}% retraced, {d['mean_width_m']} m wide on average, compactness {d['compactness']} (square = 0.79)")


def run(
    address: str,
    miles: float,
    out: Path | None = None,
    top: int = 1,
    geocode_fn: Callable[[str], GeocodeResult] = geocode,
    grid_fn: Callable[[float, float], GridEstimate] = current_grid,
    generate_fn: Callable[..., GenerationResult] = generate_loops,
) -> int:
    if not MIN_MILES <= miles <= MAX_MILES:
        print(f"Distance must be between {MIN_MILES:g} and {MAX_MILES:g} miles.", file=sys.stderr)
        return 4

    try:
        place = geocode_fn(address)
    except GeocodeError as exc:
        print(f"Couldn't use that address: {exc}", file=sys.stderr)
        return 2
    print(f"Start:     {place.label}  [{place.lat:.5f}, {place.lon:.5f}]")
    print(f"Requested: {miles:.2f} mi (target +/-{TOLERANCE_PCT:g}%)")

    try:
        grid = grid_fn(place.lat, place.lon)
    except psycopg.Error as exc:
        print(f"Could not read street data from Postgres ({exc}). Is it running and loaded? Try: make up", file=sys.stderr)
        return 3
    print(f"Grid:      street grid at {grid.angle_deg:.1f} degrees, strength {grid.strength:.2f}")

    try:
        result = generate_fn(
            place.lat, place.lon, miles, grid, route_fn=request_route, round_trip_fn=request_round_trip, top_n=top
        )
    except RoutingError as exc:
        print(f"Routing failed: {exc}", file=sys.stderr)
        return 3

    rejected = ", ".join(f"{n} {why}" for why, n in result.rejected.items())
    print(f"Tried:     {result.generated} candidates" + (f" (rejected: {rejected})" if rejected else ""))
    if result.note:
        print(f"Note:      {result.note}")
    if not result.candidates:
        print(result.note or "No loop could be generated.", file=sys.stderr)
        return 5

    base = out or output_path_for(address, miles)
    base.parent.mkdir(parents=True, exist_ok=True)
    saved = []
    for rank, c in enumerate(result.candidates, start=1):
        print_candidate(rank, c)
        path = base if len(result.candidates) == 1 else base.with_name(f"{base.stem}-rank{rank}{base.suffix}")
        geojson = route_to_geojson(
            c.route, place.lat, place.lon, place.label, miles, c.shape.as_dict(),
            extra_properties={"rank": rank, "method": c.method, "label": c.label, "shape_score": round(c.score)},
        )
        path.write_text(json.dumps(geojson))
        saved.append(path)

    print()
    for path in saved:
        print(f"Saved:     {path}")
    print("View it:   drag the file(s) onto https://geojson.io")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address", help='NYC street address with a number, e.g. "11 Madison Ave, Manhattan"')
    ap.add_argument("miles", type=float, help="target distance in miles")
    ap.add_argument("--top", type=int, default=1, help="how many loops to save, best first (default 1)")
    ap.add_argument("--out", type=Path, help="where to write the GeoJSON (default: out/)")
    args = ap.parse_args(argv)
    return run(args.address, args.miles, out=args.out, top=args.top, geocode_fn=geocode, grid_fn=current_grid,
               generate_fn=generate_loops)


if __name__ == "__main__":
    sys.exit(main())
