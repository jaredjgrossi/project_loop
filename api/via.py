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

A via's mode (decision 035): `through` passes it, as above; `around` runs a full lap of its ring (a known running
loop from running_loops, or the place's outline). A lap is a run of waypoints on the ring, every LAP_STEP_M, from the
point nearest the way in and back to it, so the lap counts toward the distance; a route must run along LAP_SHARE of
the ring, within LAP_TOLERANCE_M.
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
LAP_STEP_M = 200.0
LAP_TOLERANCE_M = 30.0
LAP_SHARE = 0.9
LAP_CORNER_DEG = 45.0


@dataclass(frozen=True)
class Via:
    lat: float
    lon: float
    name: str
    shape: dict  # GeoJSON, [lon, lat]: the place's outline, line or point
    lap: tuple | None = None  # around (decision 035): the ring's [lon, lat] coordinates, in the running direction

    @property
    def point(self) -> tuple[float, float]:
        return self.lat, self.lon

    @property
    def mode(self) -> str:
        return "through" if self.lap is None else "around"

    def stops(self, came_from: tuple[float, float]) -> list[tuple[float, float]]:
        """The waypoints that pass this via, coming from `came_from`: its point, or a full lap of its ring."""
        return [self.point] if self.lap is None else lap_points(self.lap, came_from)


def lap_points(ring: Sequence, came_from: tuple[float, float], step_m: float = LAP_STEP_M) -> list:
    """(lat, lon) waypoints for one full lap of a closed [lon, lat] ring, in the ring's direction: from the point on
    it nearest `came_from`, back to that point. Between them, a point every `step_m` along the ring and at every
    corner sharper than LAP_CORNER_DEG, so the router can't cut across."""
    import numpy as np
    import shapely
    from shapely.geometry import LineString, Point

    lon0, lat0 = ring[0][:2]
    origin, scale = np.array([lon0, lat0]), np.array([111_320 * math.cos(math.radians(lat0)), 110_574])
    line = shapely.transform(LineString([c[:2] for c in ring]), lambda xy: (xy - origin) * scale)
    xy = np.array(line.coords)
    total = line.length
    entry = line.project(Point((np.array([came_from[1], came_from[0]]) - origin) * scale))
    along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])  # each vertex's distance along
    corners = []
    for i in range(1, len(xy) - 1):  # the closing vertex is the first one: check it against both neighbors
        a, b = xy[i] - xy[i - 1], xy[i + 1] - xy[i]
        if _turn_deg(a, b) > LAP_CORNER_DEG:
            corners.append(along[i])
    if _turn_deg(xy[-1] - xy[-2], xy[1] - xy[0]) > LAP_CORNER_DEG:
        corners.append(0.0)
    ahead = sorted({round((d - entry) % total, 3) for d in corners} - {0.0, round(total, 3)})
    stops, last = [0.0], 0.0
    for d in [*ahead, total]:  # a point every step_m, and every corner
        while d - last > step_m * 1.5:
            last += step_m
            stops.append(last)
        if d < total:
            stops.append(d)
            last = d
    stops.append(total)
    out = []
    for d in stops:
        p = line.interpolate((entry + d) % total)
        out.append((p.y / scale[1] + lat0, p.x / scale[0] + lon0))
    return out


def _turn_deg(a, b) -> float:
    na, nb = math.hypot(*a), math.hypot(*b)
    if na == 0 or nb == 0:
        return 0.0
    cos = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (na * nb)))
    return math.degrees(math.acos(cos))


def tolerance(shape: dict) -> float:
    return TOLERANCE_M.get(shape.get("type"), 60.0)


def through_rules(vias: Sequence[Via]) -> list[tuple[dict, float, float | None]]:
    """The hard rule for each via: (shape, meters, None) to pass it, or (ring, meters, share) to run its lap."""
    return [(v.shape, tolerance(v.shape), None) if v.lap is None
            else ({"type": "LineString", "coordinates": [list(c) for c in v.lap]}, LAP_TOLERANCE_M, LAP_SHARE)
            for v in vias]


def tour(start: tuple[float, float], vias: Sequence[Via], end: tuple[float, float] | None = None) -> list:
    """The points of the shortest way through the vias (a lap for each around via): back to the start, or on to the
    end."""
    points = [start]
    for v in vias:
        points += v.stops(points[-1])
    return [*points, end or start]


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
    names = " and ".join(("with a lap of " if v.lap else "through ") + v.name for v in vias)
    pts = tour(start, vias)[1:-1]
    target_m = miles_to_meters(miles)
    factor = street_factor(shortest, tour(start, vias))
    extra_m = max(target_m - shortest.distance_m, 0.0)
    loops = shape in ("loop", "any")
    back = shape in ("out_and_back", "any") and all(v.lap is None for v in vias)  # a lap isn't run twice

    def make(rules: _Rules) -> list[tuple[int, Callable]]:
        jobs = []

        def shortest_job():
            return _evaluate("via_shortest", None, f"the shortest way {names}", shortest, rules,
                             allowed=SHAPE_KINDS[shape])

        def loop_job(angle: float, close_after: bool):
            side = "left" if angle < 180 else "right"
            label = f"a loop {names}, {side}, {angle:.0f} degrees{'' if close_after else ', other way round'}"

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
            label = f"out-and-back {names}"
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
