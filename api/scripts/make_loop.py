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
import threading
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from etl.load import database_url

from api.constraints import (Lights, RunConstraints, describe, request_items, resolve_preferences, unsupported,
                             with_default_date)
from api.anchors import Anchors, corridor_anchors, park_anchors, water_anchors
from api.generate import TOLERANCE_PCT, Candidate, GenerationResult, generate_loops
from api.geocoding import GeocodeError, GeocodeResult, geocode
from api.grid import GridEstimate
from api.closures import Closure, load_closures, reach_m
from api.closures import custom_model as closures_model
from api.nogo import NoGoZone, custom_model
from api.nogo import resolve as resolve_zones
from api.elevation import elevation_profile
from api.lights import signal_penalty_model
from api.markers import marker_features
from api.summary import route_summary
from api.route_context import ContextScores, score_context
from api.segments import route_stretches_and_pieces
from api.routing import RoutingError, request_round_trip, request_route, route_to_geojson
from api.streets import grid_at

OUT_DIR = Path(__file__).resolve().parents[2] / "out"
NEW_YORK = ZoneInfo("America/New_York")
KIND_LABELS = {"loop": "loop", "out_and_back": "out-and-back", "lollipop": "lollipop"}
MIN_MILES, MAX_MILES = 0.5, 30.0


def output_path_for(address: str, miles: float) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", address.lower()).strip("-")
    return OUT_DIR / f"loop-{slug}-{miles:g}mi.geojson"


def current_grid(lat: float, lon: float) -> GridEstimate:
    with psycopg.connect(database_url()) as conn:
        return grid_at(conn, lat, lon)


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
        out.append(Anchors(entry=entry, directions=[sorted((p[:3] for p in pts), key=lambda p: p[2]) for pts in busiest],
                           placement="straight"))
    return out


def _on_own_connection(fetch: Callable) -> Callable:
    def run(lat: float, lon: float, radius_m: float) -> list[Anchors]:
        with psycopg.connect(database_url()) as conn:
            return fetch(conn, lat, lon, radius_m)

    return run


# One function per source, so the generator fetches them in parallel and starts routing the first to arrive.
DB_FEATURE_ANCHOR_SOURCES = [_on_own_connection(f) for f in (corridor_anchors, park_anchors, water_anchors)]


def db_stretches(coords: list[list[float]], elevation: list[float] | None, start=None) -> list[dict]:
    """Per-stretch GeoJSON features for a route (decision 014), with crowd levels for the start moment (016), then
    the route cut into pieces by kind (023)."""
    with psycopg.connect(database_url()) as conn:
        stretches, pieces = route_stretches_and_pieces(conn, coords, elevation, start)
    return stretches + pieces


def _merged(*models: dict | None) -> dict | None:
    """One GraphHopper custom model from several: priority rules concatenated, areas combined."""
    models = [m for m in models if m]
    if not models:
        return None
    out = {"priority": [r for m in models for r in m.get("priority", [])]}
    areas = [f for m in models for f in m.get("areas", {}).get("features", [])]
    if areas:
        out["areas"] = {"type": "FeatureCollection", "features": areas}
    return out


class _Reused:
    """A router function that sends each distinct request once and reuses the answer, a RoutingError included
    (decision 018: 6-14% of a generation's requests repeat an earlier one exactly, and GraphHopper answers them the
    same). Thread-safe: a request already in flight is waited for, not sent again. One per request's routers, so
    nothing is kept between requests."""

    def __init__(self, fn: partial, key: Callable = lambda *a: a):
        self.fn, self.key = fn, key
        self.keywords = fn.keywords  # the custom model, as on the plain partial
        self.lock = threading.Lock()
        self.done: dict = {}

    def __call__(self, *args):
        k = self.key(*args)
        with self.lock:
            slot = self.done.get(k)
            if slot is None:
                slot = self.done[k] = [threading.Event(), None, None]
                mine = True
            else:
                mine = False
        if mine:
            try:
                slot[1] = self.fn(*args)
            except RoutingError as exc:
                slot[2] = exc
            finally:
                slot[0].set()
        else:
            slot[0].wait()
        if slot[2] is not None:
            raise slot[2]
        return slot[1]


def _points_key(points, *rest):
    return (tuple(tuple(p) for p in points), *rest)


def routers(zones: list[NoGoZone], extra: dict | None = None) -> tuple[Callable, Callable]:
    """GraphHopper route and round-trip functions that route around the given no-go zones (plus any extra rules)."""
    model = _merged(custom_model(zones), extra)
    return (_Reused(partial(request_route, custom_model=model), _points_key),
            _Reused(partial(request_round_trip, custom_model=model)))


def routers_for(zones: list[NoGoZone], lights: Lights, closures=(), alongs=()) -> tuple[Callable, Callable, Callable]:
    """Route, round-trip and feature-area route functions for a runner: a signal penalty in every request when they
    wait at lights, none when they zig-zag (decision 015), around reported closures (decision 017), and off the
    streets they won't run along (decision 036)."""
    from api.along import custom_model as along_model
    extra = _merged(signal_penalty_model() if lights == Lights.WAITS else None, closures_model(closures),
                    along_model(alongs))
    route_fn, round_trip_fn = routers(zones, extra)
    return route_fn, round_trip_fn, area_router(zones, extra)


def db_closures(lat: float, lon: float, miles: float) -> list[Closure]:
    """The known closures a route of this length from this start could reach (decision 017)."""
    with psycopg.connect(database_url()) as conn:
        return load_closures(conn, lat, lon, reach_m(miles))


def context_for(lights: Lights, grid: GridEstimate, use_prior: bool = True, start=None) -> Callable:
    """A context scorer that also estimates the wait at lights for this runner and street grid (decision 015) and the
    crowds along the route from the start moment (decision 016). Scored in a worker process (decision 018)."""
    from api import scoring_pool

    def score(coords: list[list[float]]) -> ContextScores:
        return scoring_pool.score(coords, use_prior, lights, grid, start)

    return score


# Provisional (decision 012): off-feature edges cost twice as much, so an anchored route stays on the park, waterfront
# or corridor where that costs less than doubling the distance, and still reaches it through streets.
OFF_FEATURE_PRIORITY = 0.5
MAX_FEATURE_PARTS = 25


def area_router(zones: list[NoGoZone], extra: dict | None = None) -> Callable:
    """A GraphHopper route function for anchored routes: around the no-go zones, preferring the feature's area."""
    base = _merged(custom_model(zones), extra) or {"priority": []}
    base.setdefault("areas", {"type": "FeatureCollection", "features": []})

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

    reused = _Reused(partial(route), lambda points, area: (_points_key(points), id(area)))
    keep: dict = {}  # the areas seen, so an id in the memo can't be reused by another area during the request

    def route_once(points: list[tuple[float, float]], area: dict):
        keep[id(area)] = area
        return reused(points, area)

    return route_once


def route_file(c: Candidate, rank: int, lat: float, lon: float, label: str, miles: float, constraints: RunConstraints,
               best_of: int | None, stretch_fn: Callable | None) -> dict:
    """One route as the app reads it (the fixture's `route`): the line with its shape, elevation, request and summary,
    then mile markers and turnarounds, then stretches and pieces by kind (decisions 014, 020, 023)."""
    from api.naming import display_name
    name = display_name(c.kind, c.label)
    geojson = route_to_geojson(
        c.route, lat, lon, label, miles, c.shape.as_dict(), name=name,
        extra_properties={"rank": rank, "method": c.method, "kind": c.kind, "label": name, "plan": c.label,
                          "score": round(c.score),
                          "elevation": elevation_profile(c.route.coordinates, c.route.elevation),
                          "start_hour": constraints.start_hour, "request": request_items(constraints)},
    )
    markers = marker_features(c.route.coordinates)
    stretches = (stretch_fn(c.route.coordinates, c.route.elevation, constraints.start_moment())
                 if stretch_fn is not None else [])
    geojson["features"][0]["properties"]["summary"] = route_summary(
        c, stretches, markers, geojson["features"][0]["properties"]["elevation"], rank=rank, best_of=best_of)
    geojson["features"] += markers + stretches
    return geojson


def print_candidate(rank: int, c: Candidate) -> None:
    d = c.shape.as_dict()
    kind = KIND_LABELS[c.kind]
    print(f"\n#{rank}  {c.label}   score {c.score:.0f}/100 ({kind}; provisional weights)")
    print(f"    Distance:  {c.route.distance_m / 1609.344:.2f} mi  ({c.miss_pct:+.0f}% from the request)")
    print(f"    Turns:     {d['turns']}  ({d['turns_per_mile']} per mile)")
    print(f"    Straight:  longest run {d['longest_straight_m']} m; {d['pct_in_long_runs']}% of the route is on runs of 500 m or more")
    print(f"    Shape:     {d['retraced_pct']}% retraced, {d['mean_width_m']} m wide on average, compactness {d['compactness']} (square = 0.79)")
    if c.context is not None and c.context.wait_s is not None:
        credit = f"; zig-zag alternative at {c.context.wait_credited}" if c.context.wait_credited else ""
        print(f"    {'Wait at lights:':<23}{c.context.wait_s / 60:.1f} min at {c.context.wait_signals} signals{credit} "
              f"[estimate, not scored]")
    if c.ranking is not None:
        for dim in c.ranking.scored():
            if dim.key not in ("turns", "straight", "loop_shape", "retrace"):  # shown above
                print(f"    {dim.label + ':':<23}{dim.value} [{dim.status}]")
        print("    Not scored yet: " + ", ".join(dim.label + (f" ({dim.value})" if dim.value else "")
                                             for dim in c.ranking.not_scored()))


def run(
    address: str,
    miles: float,
    out: Path | None = None,
    top: int = 1,
    geocode_fn: Callable[[str], GeocodeResult] = geocode,
    grid_fn: Callable[[float, float], GridEstimate] = current_grid,
    generate_fn: Callable[..., GenerationResult] = generate_loops,
    shape: str | None = None,  # None: not stated, so the schema default ("any") applies and is shown as a default
    mode: str | None = None,
    avoid: list[str] | None = None,
    context_fn: Callable | None = None,
    anchor_fn: Callable | None = None,
    feature_anchor_fn: Callable | None = None,
    area_route_fn: Callable | None = None,
    start_time: str | None = None,
    context_factory: Callable | None = None,  # (lights, grid, start) -> context_fn; used when context_fn is not given
    lights: str | None = None,
    start_date: str | None = None,
    stretch_fn: Callable | None = None,  # (coords, elevation, start) -> stretch features (api/segments.py)
    pool_out: Path | None = None,
    closures_fn: Callable | None = None,  # (lat, lon, miles) -> known closures (decision 017)
    now_fn: Callable[[], datetime] = lambda: datetime.now(NEW_YORK).replace(tzinfo=None),  # for the default day
) -> int:
    if not MIN_MILES <= miles <= MAX_MILES:
        print(f"Distance must be between {MIN_MILES:g} and {MAX_MILES:g} miles.", file=sys.stderr)
        return 4
    stated = {"shape": shape, "mode": mode, "start_time": start_time, "start_date": start_date, "lights": lights}
    constraints = RunConstraints(start_address=address, distance_mi=miles, avoid_places=avoid or [],
                                 **{k: v for k, v in stated.items() if v is not None})
    constraints = with_default_date(constraints, now_fn())
    prefs = resolve_preferences(constraints).values
    print("Request:   " + "\n           ".join(describe(constraints)))
    later = unsupported(constraints)
    if later:  # product rule 3: say so, never build without them
        print(f"Can't build this yet: {', '.join(later)} (Phase 3).", file=sys.stderr)
        return 6
    zones, unknown = resolve_zones([a.name for a in constraints.avoid_places])
    for name in unknown:
        print(f"Avoid:     '{name}' isn't in the no-go list, so it was NOT applied.")

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
    closures = closures_fn(place.lat, place.lon, miles) if closures_fn else []
    if closures:
        print(f"Closures:  {len(closures)} known closures within reach; no route may pass through one")
    route_fn, round_trip_fn, lights_area_router = routers_for(zones, prefs["lights"], closures)

    try:
        result = generate_fn(
            place.lat, place.lon, miles, grid, route_fn=route_fn, round_trip_fn=round_trip_fn, top_n=top,
            shape=constraints.shape, prefs=prefs, avoid=zones, closures=closures,
            context_fn=context_fn or (context_factory(prefs["lights"], grid, constraints.start_moment())
                                      if context_factory else None),
            anchor_fn=anchor_fn, feature_anchor_fn=feature_anchor_fn,
            area_route_fn=area_route_fn or (lights_area_router if feature_anchor_fn else None),
        )
    except RoutingError as exc:
        print(f"Routing failed: {exc}", file=sys.stderr)
        return 3

    rejected = ", ".join(f"{n} {why}" for why, n in result.rejected.items())
    print(f"Tried:     {result.generated} candidates" + (f" (rejected: {rejected})" if rejected else "")
          + (f"; best of {result.best_of} distinct routes within the distance limit" if result.best_of else ""))
    tm = result.timing
    if tm.get("first_candidate_s") is not None:
        print(f"Timing:    first candidate {tm['first_candidate_s']:.2f} s, #1 arrived {tm['winner_arrived_s']:.2f} s, "
              f"all done {tm['total_s']:.2f} s")
    if pool_out is not None:
        pool_out.parent.mkdir(parents=True, exist_ok=True)
        pool_out.write_text(json.dumps({"request": constraints.model_dump(mode="json"), "timing": tm,
                                        "best_of": result.best_of, "pool": result.pool}))
        print(f"Pool:      {len(result.pool)} candidates with metric vectors -> {pool_out}")
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
        geojson = route_file(c, rank, place.lat, place.lon, place.label, miles, constraints, result.best_of, stretch_fn)
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
    ap.add_argument("--shape", choices=["loop", "out_and_back", "any"], help="route shape (default any)")
    ap.add_argument("--mode", choices=["training", "exploring"], help="preference preset")
    ap.add_argument("--avoid", action="append", default=[], help="a named no-go place (repeatable)")
    ap.add_argument("--start-time", help="departure time, HH:MM; with --start-date, sets the crowd band")
    ap.add_argument("--start-date", help="departure date, YYYY-MM-DD (weekday, Saturday or Sunday matters for crowds)")
    ap.add_argument("--lights", choices=["waits", "zigzags"], help="at a red light: wait, or zig-zag with the green")
    ap.add_argument("--pool", type=Path, help="also write every candidate with its metric vector to this JSON file")
    args = ap.parse_args(argv)
    return run(args.address, args.miles, out=args.out, top=args.top, geocode_fn=geocode, grid_fn=current_grid,
               generate_fn=generate_loops, shape=args.shape, mode=args.mode, avoid=args.avoid,
               anchor_fn=familiar_anchors, feature_anchor_fn=DB_FEATURE_ANCHOR_SOURCES, start_time=args.start_time,
               stretch_fn=db_stretches, closures_fn=db_closures, pool_out=args.pool, lights=args.lights, start_date=args.start_date,
               context_factory=lambda lights, grid, start: context_for(lights, grid, use_prior=True, start=start))


if __name__ == "__main__":
    sys.exit(main())
