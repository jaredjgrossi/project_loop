"""Make running routes from an NYC address.

    python -m api.scripts.make_loop "11 Madison Ave, Manhattan" 4 [--shape loop|out_and_back|any] [--mode training]

Shows the parsed request, geocodes the address, finds the local street grid, generates loops (grid-aligned
rectangles, round trips where the grid is weak) and out-and-backs, routes around no-go zones, ranks them against the
runner's preferences, prints the real distance and scored fields, and saves GeoJSON (open it at geojson.io).
"""

import argparse
import json
import re
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

import psycopg

from etl.load import database_url

from api.constraints import RunConstraints, describe, resolve_preferences
from api.anchors import Anchors, feature_anchors
from api.generate import TOLERANCE_PCT, Candidate, GenerationResult, generate_loops
from api.geocoding import GeocodeError, GeocodeResult, geocode
from api.grid import GridEstimate
from api.nogo import NoGoZone, custom_model
from api.nogo import resolve as resolve_zones
from api.route_context import ContextScores, score_context
from api.routing import RoutingError, request_round_trip, request_route, route_to_geojson
from api.streets import grid_at

OUT_DIR = Path(__file__).resolve().parents[2] / "out"
KIND_LABELS = {"loop": "loop", "out_and_back": "out-and-back", "lollipop": "lollipop"}
MIN_MILES, MAX_MILES = 0.5, 30.0


def output_path_for(address: str, miles: float) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    return OUT_DIR / f"loop-{slug}-{miles:g}mi.geojson"


def current_grid(lat: float, lon: float) -> GridEstimate:
    with psycopg.connect(database_url()) as conn:
        return grid_at(conn, lat, lon)


def db_context(coords: list[list[float]]) -> ContextScores:
    """Park/water share, signals and familiarity for a route, from PostGIS. One connection per call: the generator
    scores candidates on several threads."""
    with psycopg.connect(database_url()) as conn:
        return score_context(conn, coords)


def db_context_without_prior(coords: list[list[float]]) -> ContextScores:
    """As db_context, but ignoring the runner's own runs."""
    with psycopg.connect(database_url()) as conn:
        return score_context(conn, coords, use_prior=False)


ANCHOR_SQL = """
WITH here AS (SELECT ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography AS g),
used AS (
    SELECT p.runs, ST_LineInterpolatePoint(w.geom, 0.5) AS mid FROM runner_prior p JOIN osm_ways w USING (way_id)
    WHERE p.runs >= GREATEST(2, %(share)s * p.total_runs)
)
SELECT ST_Y(mid), ST_X(mid), runs, ST_Distance(mid::geography, here.g), degrees(ST_Azimuth(here.g, mid::geography))
FROM used, here
WHERE ST_DWithin(mid::geography, here.g, %(far)s)
"""
ANCHOR_SECTOR_DEG = 45
# Provisional (decision 011). The strong tier is the runner's main corridors; the broad tier reaches further where
# runs vary more (from the Kips Bay review start the strong corridor stopped 1.5 km out). Both are tried; the ranking picks.
ANCHOR_TIERS = (0.10, 0.025)  # share of the runner's runs that used a way


def familiar_anchors(lat: float, lon: float, radius_m: float) -> list[Anchors]:
    """Points on the ways the runner uses (runner_prior), per tier: the nearest one as the entry, and the rest grouped
    into 45-degree directions, the busiest directions first."""
    with psycopg.connect(database_url()) as conn:
        if not conn.execute("SELECT to_regclass('runner_prior') IS NOT NULL").fetchone()[0]:
            return []
        tiers = [conn.execute(ANCHOR_SQL, {"lat": lat, "lon": lon, "far": 1.5 * radius_m, "share": share}).fetchall()
                 for share in ANCHOR_TIERS]
    out = []
    for rows in tiers:
        if not rows:
            continue
        nearest = min(rows, key=lambda r: r[3])
        entry = (nearest[0], nearest[1]) if nearest[3] <= 0.5 * radius_m else None
        sectors: dict[int, list] = {}
        for a_lat, a_lon, runs, dist, bearing in rows:
            if dist >= 0.4 * radius_m:
                sectors.setdefault(int(bearing // ANCHOR_SECTOR_DEG), []).append((a_lat, a_lon, dist, runs))
        busiest = sorted(sectors.values(), key=lambda pts: -sum(p[3] for p in pts))
        out.append(Anchors(entry=entry, directions=[sorted((p[:3] for p in pts), key=lambda p: p[2]) for pts in busiest]))
    return out


def db_feature_anchors(lat: float, lon: float, radius_m: float) -> list[Anchors]:
    """Parks, waterfront and catalog corridors within reach, from OSM in PostGIS (decision 012)."""
    with psycopg.connect(database_url()) as conn:
        return feature_anchors(conn, lat, lon, radius_m)


def routers(zones: list[NoGoZone]) -> tuple[Callable, Callable]:
    """GraphHopper route and round-trip functions that route around the given no-go zones."""
    model = custom_model(zones)
    return partial(request_route, custom_model=model), partial(request_round_trip, custom_model=model)


# Provisional (decision 012): off-feature edges cost twice as much, so an anchored route stays on the park, waterfront
# or corridor where that costs less than doubling the distance, and still reaches it through streets.
OFF_FEATURE_PRIORITY = 0.5
MAX_FEATURE_PARTS = 25


def area_router(zones: list[NoGoZone]) -> Callable:
    """A GraphHopper route function for anchored routes: around the no-go zones, preferring the feature's area."""
    base = custom_model(zones) or {"priority": [], "areas": {"type": "FeatureCollection", "features": []}}

    def route(points: list[tuple[float, float]], area: dict):
        # GraphHopper areas must be single polygons, so a multipolygon becomes one area per part (largest first).
        rings = [area["coordinates"]] if area["type"] == "Polygon" else area["coordinates"]
        parts = sorted(rings, key=lambda poly: -len(poly[0]))[:MAX_FEATURE_PARTS]
        ids = [f"feature_{i}" for i in range(len(parts))]
        model = {
            "priority": [*base["priority"],
                         {"if": " && ".join(f"!in_{i}" for i in ids), "multiply_by": str(OFF_FEATURE_PRIORITY)}],
            "areas": {"type": "FeatureCollection", "features": [
                *base["areas"]["features"],
                *({"type": "Feature", "id": i, "properties": {}, "geometry": {"type": "Polygon", "coordinates": poly}}
                  for i, poly in zip(ids, parts))]},
        }
        return request_route(points, custom_model=model)

    return route


def print_candidate(rank: int, c: Candidate) -> None:
    d = c.shape.as_dict()
    kind = KIND_LABELS[c.kind]
    print(f"\n#{rank}  {c.label}   score {c.score:.0f}/100 ({kind}; provisional weights)")
    print(f"    Distance:  {c.route.distance_m / 1609.344:.2f} mi  ({c.miss_pct:+.0f}% from the request)")
    print(f"    Turns:     {d['turns']}  ({d['turns_per_mile']} per mile)")
    print(f"    Straight:  longest run {d['longest_straight_m']} m; {d['pct_in_long_runs']}% of the route is on runs of 500 m or more")
    print(f"    Shape:     {d['retraced_pct']}% retraced, {d['mean_width_m']} m wide on average, compactness {d['compactness']} (square = 0.79)")
    if c.ranking is not None:
        for dim in c.ranking.scored():
            if dim.key not in ("turns", "straight", "loop_shape", "retrace"):  # shown above
                print(f"    {dim.label + ':':<23}{dim.value} [{dim.status}]")
        print("    Not scored yet: " + ", ".join(dim.label for dim in c.ranking.not_scored()))


def run(
    address: str,
    miles: float,
    out: Path | None = None,
    top: int = 1,
    geocode_fn: Callable[[str], GeocodeResult] = geocode,
    grid_fn: Callable[[float, float], GridEstimate] = current_grid,
    generate_fn: Callable[..., GenerationResult] = generate_loops,
    shape: str = "any",
    mode: str | None = None,
    avoid: list[str] | None = None,
    context_fn: Callable | None = None,
    anchor_fn: Callable | None = None,
    feature_anchor_fn: Callable | None = None,
    area_route_fn: Callable | None = None,
) -> int:
    if not MIN_MILES <= miles <= MAX_MILES:
        print(f"Distance must be between {MIN_MILES:g} and {MAX_MILES:g} miles.", file=sys.stderr)
        return 4
    constraints = RunConstraints(start_address=address, distance_mi=miles, shape=shape, mode=mode,
                                 avoid_places=avoid or [])
    print("Request:   " + "\n           ".join(describe(constraints)))
    zones, unknown = resolve_zones(constraints.avoid_places)
    for name in unknown:
        print(f"Avoid:     '{name}' isn't in the no-go list, so it was NOT applied.")
    route_fn, round_trip_fn = routers(zones)

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
            place.lat, place.lon, miles, grid, route_fn=route_fn, round_trip_fn=round_trip_fn, top_n=top,
            shape=constraints.shape, prefs=resolve_preferences(constraints).values, avoid=zones,
            context_fn=context_fn, anchor_fn=anchor_fn, feature_anchor_fn=feature_anchor_fn,
            area_route_fn=area_route_fn or (area_router(zones) if feature_anchor_fn else None),
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
            extra_properties={"rank": rank, "method": c.method, "kind": c.kind, "label": c.label, "score": round(c.score)},
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
    ap.add_argument("--shape", choices=["loop", "out_and_back", "any"], default="any", help="route shape (default any)")
    ap.add_argument("--mode", choices=["training", "exploring"], help="preference preset")
    ap.add_argument("--avoid", action="append", default=[], help="a named no-go place (repeatable)")
    args = ap.parse_args(argv)
    return run(args.address, args.miles, out=args.out, top=args.top, geocode_fn=geocode, grid_fn=current_grid,
               generate_fn=generate_loops, shape=args.shape, mode=args.mode, avoid=args.avoid,
               context_fn=db_context, anchor_fn=familiar_anchors, feature_anchor_fn=db_feature_anchors)


if __name__ == "__main__":
    sys.exit(main())
