"""Make one running loop from an NYC address.

    python -m api.scripts.make_loop "11 Madison Ave, Manhattan" 4

Geocodes the address, asks GraphHopper for a round-trip foot route of about that
many miles, prints the real distance, and saves GeoJSON (open it at geojson.io).
"""

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path

from api.geocoding import GeocodeError, GeocodeResult, geocode
from api.routing import Route, RoutingError, request_round_trip, route_to_geojson
from api.units import meters_to_miles, miles_to_meters, percent_off

OUT_DIR = Path(__file__).resolve().parents[2] / "out"
TARGET_TOLERANCE_PERCENT = 5.0
MIN_MILES, MAX_MILES = 0.5, 30.0


def output_path_for(address: str, miles: float, seed: int) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    return OUT_DIR / f"loop-{slug}-{miles:g}mi-seed{seed}.geojson"


def run(
    address: str,
    miles: float,
    seed: int = 0,
    out: Path | None = None,
    geocode_fn: Callable[[str], GeocodeResult] = geocode,
    route_fn: Callable[..., Route] = request_round_trip,
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

    try:
        route = route_fn(place.lat, place.lon, miles_to_meters(miles), seed)
    except RoutingError as exc:
        print(f"Routing failed: {exc}", file=sys.stderr)
        return 3

    actual = meters_to_miles(route.distance_m)
    miss = percent_off(miles, actual)
    print(f"Requested: {miles:.2f} mi")
    print(f"Actual:    {actual:.2f} mi  ({miss:+.0f}%)")
    if abs(miss) > TARGET_TOLERANCE_PERCENT:
        print(
            f"           That is outside the +/-{TARGET_TOLERANCE_PERCENT:g}% target. GraphHopper's round trips are "
            f"approximate; try --seed 1, 2, ... for a different loop. Automatic tuning is planned for Phase 2."
        )

    out = out or output_path_for(address, miles, seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    geojson = route_to_geojson(route, place.lat, place.lon, place.label, miles)
    out.write_text(json.dumps(geojson))
    print(f"Saved:     {out}")
    print("View it:   drag that file onto https://geojson.io")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address", help='NYC street address with a number, e.g. "11 Madison Ave, Manhattan"')
    ap.add_argument("miles", type=float, help="target distance in miles")
    ap.add_argument("--seed", type=int, default=0, help="GraphHopper round-trip seed; each gives a different loop")
    ap.add_argument("--out", type=Path, help="where to write the GeoJSON (default: out/)")
    args = ap.parse_args(argv)
    return run(args.address, args.miles, seed=args.seed, out=args.out, geocode_fn=geocode, route_fn=request_round_trip)


if __name__ == "__main__":
    sys.exit(main())
