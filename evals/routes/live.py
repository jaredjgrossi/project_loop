"""Shared helpers for the route evals and the review renderer: run the real generator against the live stack.

Needs `make up` (Postgres with the OSM streets loaded, and GraphHopper). Starts use stored coordinates, so no
geocoding call is made.
"""

import json
from functools import cache
from pathlib import Path

import httpx
import psycopg

from api.constraints import DEFAULTS
from api.generate import Candidate, generate_loops
from api.nogo import resolve as resolve_zones
from api.routing import graphhopper_url
from api.scripts.make_loop import (
    DB_FEATURE_ANCHOR_SOURCES,
    context_for,
    current_grid,
    db_closures,
    familiar_anchors,
    routers_for,
)
from etl.load import database_url

HERE = Path(__file__).resolve().parent


def load_starts() -> dict[str, dict]:
    return {s["id"]: s for s in json.loads((HERE / "starts.json").read_text())["starts"]}


def load_rejected() -> list[dict]:
    return json.loads((HERE / "rejected_routes.json").read_text())["cases"]


def stack_problem() -> str | None:
    """Why the live stack can't be used, or None when it can."""
    try:
        httpx.get(f"{graphhopper_url()}/health", timeout=3).raise_for_status()
    except httpx.HTTPError as exc:
        return f"GraphHopper not reachable at {graphhopper_url()} ({exc}). Try: make up"
    try:
        with psycopg.connect(database_url(), connect_timeout=3) as conn:
            conn.execute("SELECT 1 FROM osm_ways LIMIT 1")
    except psycopg.Error as exc:
        return f"Postgres not usable ({exc}). Try: make up"
    return None


@cache
def top_loops(
    start_id: str, miles: float, top: int, shape: str = "any", prefs: tuple = (), use_prior: bool = True,
    when=None, extra_closures: tuple = (),
) -> tuple[Candidate, ...]:
    """What a runner gets from this start with nothing but a distance stated: default zones, neutral preferences
    (override some with prefs, as (name, value) pairs). Context is always scored. use_prior=False ignores the
    reviewer's own runs entirely: no "matches routes you run" score and no placement along their corridors. when (the
    start datetime) sets the crowd band (decision 016); without it crowds are not scored. Known closures within reach
    always apply (decision 017); extra_closures adds more, as for a confirmed report."""
    start = load_starts()[start_id]
    grid = current_grid(start["lat"], start["lon"])
    zones, _ = resolve_zones([])
    full_prefs = {**DEFAULTS, **dict(prefs)}
    closures = [*db_closures(start["lat"], start["lon"], miles), *extra_closures]
    route_fn, round_trip_fn, area_route_fn = routers_for(zones, full_prefs["lights"], closures)
    result = generate_loops(
        start["lat"], start["lon"], miles, grid, route_fn=route_fn, round_trip_fn=round_trip_fn, top_n=top,
        shape=shape, prefs=full_prefs, avoid=zones, closures=closures,
        context_fn=context_for(full_prefs["lights"], grid, use_prior=use_prior, start=when),
        anchor_fn=familiar_anchors if use_prior else None,
        feature_anchor_fn=DB_FEATURE_ANCHOR_SOURCES,  # from OSM, for every runner: on in both settings
        area_route_fn=area_route_fn,
    )
    return tuple(result.candidates)


def closest_approach_m(coordinates: list[list[float]], area: dict) -> float:
    """Distance in meters from the route to the polygon; 0 when the route touches or enters it."""
    with psycopg.connect(database_url()) as conn:
        (feet,) = conn.execute(
            "SELECT ST_Distance(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2263),"
            " ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2263))",
            (json.dumps({"type": "LineString", "coordinates": coordinates}), json.dumps(area)),
        ).fetchone()
    return feet * 0.3048


def rule_violations(start_id: str, miles: float, candidates: tuple[Candidate, ...]) -> list[tuple[int, dict]]:
    """(rank, rejected case) for every top candidate that breaks a rule from rejected_routes.json."""
    out = []
    for case in load_rejected():
        if case["start"] != start_id or miles not in case["miles"]:
            continue
        rule = case["rule"]
        for rank, c in enumerate(candidates[: case["top"]], start=1):
            if rule["type"] == "avoid_area" and closest_approach_m(c.route.coordinates, rule["area"]) == 0:
                out.append((rank, case))
    return out
