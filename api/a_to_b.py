"""Routes from a start to an end somewhere else (Phase 3, step 8; decision 032).

First the shortest way, by the same router as everything else: around the no-go zones and closures, with the
runner's lights setting. If the requested distance is shorter than that (beyond the tolerance), the engine asks
rather than quietly running long (rule 3); with no distance, the shortest way is the target. Then the candidates:
- the direct route, the shortest way itself;
- detours through one waypoint on an ellipse with the start and end as foci, sized so the route fits the distance,
  on both sides of the straight line;
- detours along a park, the waterfront or a catalog corridor (the same OSM anchors loops use, decision 012): out to
  a feature near the start, along it, then on to the end; or to the far end of a feature near the end, along it to
  its entry, then in. Routed preferring the feature's area, as anchored loops are.
Each is rescaled to the distance, checked by the same hard rules (no-go zones, closures, and no doubling back) and
ranked like an out-and-back: turns, straight runs, park and water, lights, familiarity and crowds; no loop shape.

Pure orchestration, as api/generate.py: routing and anchors are injected.
"""

import math
from collections.abc import Callable, Sequence

from api.anchors import Anchors
from api.constraints import DEFAULTS
from api.generate import (PRIORITY, AnchorFn, AreaRouteFn, Candidate, ContextFn, GenerationResult, Rejection, RouteFn,
                          _evaluate, _fit, _meters, _offset, _Rules, run_and_finish, without_waypoint_spurs)
from api.grid import GridEstimate
from api.closures import Closure
from api.nogo import NoGoZone
from api.routing import Route, RoutingError
from api.units import meters_to_miles, miles_to_meters

ELLIPSE_ANGLES = (45, 90, 135, 225, 270, 315)  # degrees around the centre from the start-to-end axis; not on the axis
STREET_FACTOR_RANGE = (1.05, 1.6)  # routed / straight-line, from the shortest way; clamped
STREET_FACTOR = 1.3  # for legs whose street factor isn't known
MAX_DIRECTIONS_PER_SET = 3
FEATURE_FIT_PCT = 15.0  # a feature whose best estimate misses the distance by more than this isn't routed (step 8)
KIND = "a_to_b"


def shorter_than_the_shortest_way(miles: float | None, tolerance_pct: float, shortest_m: float) -> bool:
    """Rule 3: a requested distance that can't reach the end, even at its tolerance, is asked about, never stretched.
    Compared at the precision the question quotes, so an accepted answer is never asked about again (issue #50)."""
    return miles is not None and ask_miles(shortest_m) > miles * (1 + tolerance_pct / 100)


def ask_miles(shortest_m: float) -> float:
    """The distance the engine offers: the shortest way as the card will show it, to 0.01 mi (decision 061). Not
    rounded up to a tenth: "takes at least 4.3 mi" came back as a 4.22 mi card (issue #50)."""
    return round(meters_to_miles(shortest_m), 2)


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.degrees(math.atan2((b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0])) % 360


def ellipse_waypoint(start: tuple[float, float], end: tuple[float, float], total_m: float,
                     angle_deg: float) -> tuple[float, float]:
    """A point W with |start W| + |W end| = total_m (straight lines): on the ellipse with the start and end as foci,
    at `angle_deg` around its centre from the start-to-end axis."""
    c = _meters(start, end) / 2
    a = max(total_m / 2, c * 1.0001)
    b = math.sqrt(max(a * a - c * c, 0.0))
    t = math.radians(angle_deg)
    x, y = a * math.cos(t), b * math.sin(t)  # along the axis, across it
    centre = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
    axis = _bearing(start, end)
    along = _offset(*centre, axis, x)
    return _offset(*along, (axis + 90) % 360, y)


def generate_a_to_b(
    start: tuple[float, float],
    end: tuple[float, float],
    miles: float,
    grid: GridEstimate,
    route_fn: RouteFn,
    shortest: Route,
    top_n: int = 3,
    workers: int = 6,
    prefs: dict | None = None,
    avoid: Sequence[NoGoZone] = (),
    closures: Sequence[Closure] = (),
    context_fn: ContextFn | None = None,
    anchor_fn: AnchorFn | None = None,  # the runner's own ways, near the start
    feature_anchor_fn: AnchorFn | Sequence[AnchorFn] | None = None,  # parks, waterfront, corridors
    area_route_fn: AreaRouteFn | None = None,
    on_candidate: Callable[[Candidate, float], None] | None = None,
    on_top3: Callable[[dict], None] | None = None,
    vias: Sequence[tuple[float, float]] = (),  # step 9: places to pass on the way, in order
    through: Sequence[tuple[dict, float, float | None]] = (),  # their rules (via.through_rules): pass or lap each
    along: Sequence = (),  # step 8b: streets not to run along (along.Along)
    spurs_ok: bool = False,  # decision 044: following a past route
) -> GenerationResult:
    target_m = miles_to_meters(miles)
    rules = _Rules(miles, prefs or DEFAULTS, tuple(avoid), context_fn, tuple(closures), tuple(through), tuple(along),
                   spurs_ok)
    if not spurs_ok:  # decision 045: a spur at one of our own waypoints moves the waypoint to the spur's base
        route_fn = without_waypoint_spurs(route_fn)
        if area_route_fn is not None:
            area_route_fn = without_waypoint_spurs(area_route_fn)
    legs = [start, *vias, end]
    last = legs[-2]  # the detour goes between the last via (or the start) and the end
    straight = max(sum(_meters(a, b) for a, b in zip(legs, legs[1:])), 1.0)
    factor = min(max(shortest.distance_m / straight, STREET_FACTOR_RANGE[0]), STREET_FACTOR_RANGE[1])
    extra_m = max(target_m - shortest.distance_m, 0.0)  # what the detour has to add, routed
    notes: list[str] = []

    def direct_job():
        label = "the shortest way" if not vias else "the shortest way through the places you named"
        return _evaluate("direct", KIND, label, shortest, rules)

    def detour_job(angle: float):
        label = f"a detour {'left' if angle < 180 else 'right'} of the straight way, {angle:.0f} degrees"

        def job():
            def make_route(scale: float) -> Route:
                total = _meters(last, end) + extra_m * scale / factor  # straight-line sum through the waypoint
                return route_fn([start, *vias, ellipse_waypoint(last, end, total, angle), end])

            if extra_m < 0.05 * target_m:
                return Rejection("detour", label, "no_room")  # the direct route already fits
            try:
                route = _fit(make_route, target_m)
            except RoutingError:
                return Rejection("detour", label, "routing_failed")
            return _evaluate("detour", KIND, label, route, rules)

        return job

    def anchored_job(anchors: Anchors, points: list[tuple], at_start: bool):
        """From a feature near the start: start, entry, a point along it, end. Near the end: start, a point along
        it, its entry, end. The point along the feature is picked so the estimate fits the distance."""
        where = {"familiar": "along a route you run", "park": f"through {anchors.name}",
                 "water": "along the waterfront", "corridor": f"along {anchors.name}"}.get(
            anchors.source, anchors.name or anchors.source)
        label = f"{where} {'from the start' if at_start else 'to the end'}"
        method = f"{anchors.source}_a_to_b"
        entry = anchors.entry
        router = (lambda pts: area_route_fn(pts, anchors.area)) if area_route_fn and anchors.area else route_fn

        def estimate(p) -> float:
            along = p[3] if len(p) > 3 and p[3] is not None else _meters(entry, p[:2]) * STREET_FACTOR
            if at_start:
                return STREET_FACTOR * _meters(start, entry) + along + factor * _meters(p[:2], end)
            return factor * _meters(start, p[:2]) + along + STREET_FACTOR * _meters(entry, end)

        def job():
            best = min(points, key=lambda q: abs(estimate(q) - target_m))
            if abs(estimate(best) - target_m) > FEATURE_FIT_PCT / 100 * target_m:
                return Rejection(method, label, "feature_too_short")  # a small park can't absorb the extra miles

            def make_route(scale: float) -> Route:
                p = min(points, key=lambda q: abs(estimate(q) - target_m * scale))[:2]
                pts = [start, entry, p, end] if at_start else [start, p, entry, end]
                return router([q for i, q in enumerate(pts) if i == 0 or q != pts[i - 1]])

            try:
                route = _fit(make_route, target_m)
            except RoutingError:
                return Rejection(method, label, "routing_failed")
            return _evaluate(method, KIND, label, route, rules)

        return job

    def lookup(fetch: AnchorFn, at_start: bool):
        """An anchor lookup around one end; returns the jobs built from what it finds."""
        def job():
            centre = start if at_start else end
            radius = max(extra_m / 2, 400.0) + 200.0  # the detour's reach from that end
            out = []
            for anchors in fetch(*centre, radius):
                if anchors.entry is None:
                    continue
                tier = PRIORITY["anchored" if anchors.placement == "along" else "anchored_straight"]
                for pts in [d for d in anchors.directions if d][:MAX_DIRECTIONS_PER_SET]:
                    out.append((tier, anchored_job(anchors, pts, at_start)))
            return out
        return job

    sources = [] if feature_anchor_fn is None else (
        list(feature_anchor_fn) if isinstance(feature_anchor_fn, (list, tuple)) else [feature_anchor_fn])
    jobs: list[tuple[int, Callable]] = []
    if abs(shortest.distance_m - target_m) <= 0.05 * target_m:  # the shortest way fits (or no distance was given)
        jobs.append((PRIORITY["anchors"], direct_job))
    if extra_m > 0.05 * target_m and not vias:  # with vias, only waypoint detours pass them
        for fetch in sources:
            jobs.append((PRIORITY["anchors"], lookup(fetch, at_start=True)))
            jobs.append((PRIORITY["anchors"], lookup(fetch, at_start=False)))
        if anchor_fn is not None:
            jobs.append((PRIORITY["anchors"], lookup(anchor_fn, at_start=True)))
    if extra_m > 0.05 * target_m:
        # Ellipse detours fit any distance, so they run with the first anchored tier: a route that fits arrives
        # early while the waterfront and park detours are still routing.
        jobs += [(PRIORITY["anchored"], detour_job(a)) for a in ELLIPSE_ANGLES]
    return run_and_finish(jobs, workers, top_n, KIND, miles, grid, notes, on_candidate, on_top3)
