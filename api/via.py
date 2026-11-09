"""Routes through or along named places (Phase 3, step 9; decision 034).

A via place is a park, a body of water, a path or street, or a point (a station, a crossing). Each is matched by its
shape from the places table, and a route must pass every one: within 30 m of a park or water outline, 60 m of a path
or street, 150 m of a point. That is a hard rule on every candidate, like a no-go zone, checked in
`generate._evaluate`.

Candidates for a run that comes back to the start (the loop generator, with `only_anchored`):
- the corridor-anchored routes of decisions 012 and 014, but only on features that overlap a via: "a few miles in
  the park" runs along the park's paths, "on the west side highway" along the greenway;
- loops through the vias in order, closed by a waypoint on an ellipse on either side, sized to the distance;
- an out-and-back through them to a turnaround beyond the last.
For a run that ends somewhere else, `a_to_b.generate_a_to_b` takes the vias. Too far for the distance: the engine
asks (engine.py), as for an end that's too far.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from api.a_to_b import STREET_FACTOR_RANGE, ellipse_waypoint
from api.generate import (PRIORITY, SHAPE_KINDS, Rejection, Route, RouteFn, _evaluate, _fit, _meters, _offset, _Rules)
from api.geometry import shapes_within
from api.routing import RoutingError
from api.units import miles_to_meters

TOLERANCE_M = {"Polygon": 30.0, "MultiPolygon": 30.0, "LineString": 60.0, "MultiLineString": 60.0, "Point": 150.0,
               "MultiPoint": 150.0, "GeometryCollection": 60.0}
ANGLES = (45, 90, 135, 225, 270, 315)


@dataclass(frozen=True)
class Via:
    lat: float
    lon: float
    name: str
    shape: dict  # GeoJSON, [lon, lat]: the place's outline, line or point

    @property
    def point(self) -> tuple[float, float]:
        return self.lat, self.lon


def tolerance(shape: dict) -> float:
    return TOLERANCE_M.get(shape.get("type"), 60.0)


def through_rules(vias: Sequence[Via]) -> list[tuple[dict, float]]:
    return [(v.shape, tolerance(v.shape)) for v in vias]


def tour(start: tuple[float, float], vias: Sequence[Via], end: tuple[float, float] | None = None) -> list:
    """The points of the shortest way through the vias: back to the start, or on to the end."""
    return [start, *(v.point for v in vias), end or start]


def straight_length(points: Sequence[tuple[float, float]]) -> float:
    return sum(_meters(a, b) for a, b in zip(points, points[1:]))


def street_factor(shortest: Route, points: Sequence[tuple[float, float]]) -> float:
    straight = max(straight_length(points), 1.0)
    return min(max(shortest.distance_m / straight, STREET_FACTOR_RANGE[0]), STREET_FACTOR_RANGE[1])


def features_on_vias(fetch: Callable, vias: Sequence[Via]) -> Callable:
    """An anchor source that keeps only the features (parks, waterfront, corridors) overlapping a via, so the
    corridor-anchored generators run on the place the runner named."""
    def run(lat: float, lon: float, radius_m: float):
        return [a for a in fetch(lat, lon, radius_m)
                if a.area and any(shapes_within(a.area, v.shape, tolerance(v.shape)) for v in vias)]
    return run


def via_jobs(start: tuple[float, float], vias: Sequence[Via], miles: float, route_fn: RouteFn, shortest: Route,
             shape: str) -> Callable[[_Rules], list[tuple[int, Callable]]]:
    """Jobs for a run through the vias and back to the start, built from the generator's rules."""
    names = " and ".join(v.name for v in vias)
    pts = [v.point for v in vias]
    target_m = miles_to_meters(miles)
    factor = street_factor(shortest, tour(start, vias))
    extra_m = max(target_m - shortest.distance_m, 0.0)
    loops, back = shape in ("loop", "any"), shape in ("out_and_back", "any")

    def make(rules: _Rules) -> list[tuple[int, Callable]]:
        jobs = []

        def shortest_job():
            return _evaluate("via_shortest", None, f"the shortest way through {names}", shortest, rules,
                             allowed=SHAPE_KINDS[shape])

        def loop_job(angle: float, close_after: bool):
            side = "left" if angle < 180 else "right"
            label = f"a loop through {names}, {side}, {angle:.0f} degrees{'' if close_after else ', other way round'}"

            def job():
                a, b = (pts[-1], start) if close_after else (start, pts[0])

                def make_route(scale: float) -> Route:
                    w = ellipse_waypoint(a, b, _meters(a, b) + extra_m * scale / factor, angle)
                    return route_fn([start, *pts, w, start] if close_after else [start, w, *pts, start])

                try:
                    route = _fit(make_route, target_m)
                except RoutingError:
                    return Rejection("via_loop", label, "routing_failed")
                return _evaluate("via_loop", None, label, route, rules, allowed=SHAPE_KINDS[shape])

            return job

        def out_and_back_job():
            label = f"out-and-back through {names}"
            bearing = math.degrees(math.atan2((pts[-1][1] - start[1]) * math.cos(math.radians(start[0])),
                                              pts[-1][0] - start[0])) % 360

            def job():
                def make_route(scale: float) -> Route:
                    turn = _offset(*pts[-1], bearing, extra_m * scale / 2 / factor)
                    return route_fn([start, *pts, turn, *reversed(pts), start])

                try:
                    route = _fit(make_route, target_m)
                except RoutingError:
                    return Rejection("via_out_and_back", label, "routing_failed")
                return _evaluate("via_out_and_back", "out_and_back", label, route, rules)

            return job

        if abs(shortest.distance_m - target_m) <= 0.05 * target_m:
            jobs.append((PRIORITY["anchors"], shortest_job))
        if extra_m > 0.05 * target_m:
            if loops:
                jobs += [(PRIORITY["anchored"], loop_job(a, close)) for a in ANGLES for close in (True, False)]
            if back:
                jobs.append((PRIORITY["anchored"], out_and_back_job()))
        return jobs

    return make
