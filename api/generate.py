"""Generate running-loop candidates and pick the best (decision 008).

Candidates are grid-aligned rectangles routed through their four corners, because
a loop whose sides follow the street grid has long straight runs and few turns.
Each rectangle is rescaled until its routed distance is close to the request. Where
there is no street grid, GraphHopper round trips are used instead, with the same
rescaling and the same filtering. Every candidate is scored on its shape; if none
reaches the distance tolerance, the nearest ones are returned and the miss is stated
(product rule 3).

Pure orchestration: routing is injected, so this module needs no network or database.
"""

import math
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from api.grid import MIN_GRID_STRENGTH, GridEstimate
from api.routing import Route, RoutingError
from api.shape import ShapeMetrics, shape_metrics
from api.units import meters_to_miles, miles_to_meters, percent_off

TOLERANCE_PCT = 5.0
RESCALE_STOP_PCT = 2.5  # stop rescaling once this close, leaving margin inside the tolerance
MAX_RESCALES = 3
MAX_RETRACED_PCT = 15.0  # more retracing than this is an out-and-back, not a loop
MIN_COMPACTNESS = 0.15  # thinner than this is a ribbon: out along one street, back along the next
DUPLICATE_SIMILARITY = 0.8
ASPECTS = (1.0, 1.5, 2.5)  # long side : short side
FALLBACK_SEEDS = range(8)

RouteFn = Callable[[list[tuple[float, float]]], Route]  # (lat, lon) points -> route
RoundTripFn = Callable[..., Route]  # (lat, lon, distance_m, seed) -> route

M_PER_DEG_LAT = 110_574


@dataclass(frozen=True)
class Candidate:
    method: str  # "rectangle" or "round_trip"
    label: str
    route: Route
    shape: ShapeMetrics
    score: float  # shape score, 0 to 100
    miss_pct: float  # signed distance miss against the request
    within_tolerance: bool


@dataclass
class GenerationResult:
    candidates: list[Candidate]  # best first
    within_tolerance: bool  # whether the best candidate meets the distance tolerance
    grid: GridEstimate
    generated: int  # candidates attempted
    rejected: Counter = field(default_factory=Counter)  # reason -> count
    note: str | None = None


# --- geometry ------------------------------------------------------------------------


def _offset(lat: float, lon: float, bearing_deg: float, meters: float) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    return (
        lat + meters * math.cos(b) / M_PER_DEG_LAT,
        lon + meters * math.sin(b) / (111_320 * math.cos(math.radians(lat))),
    )


def rectangle_corners(
    start: tuple[float, float], grid_angle: float, len_a: float, len_b: float, sign_a: int, sign_b: int
) -> list[tuple[float, float]]:
    """A closed rectangle with a corner at start, side A along the grid angle and side B across it."""
    bearing_a = (grid_angle + (0 if sign_a > 0 else 180)) % 360
    bearing_b = (grid_angle + (90 if sign_b > 0 else 270)) % 360
    p1 = _offset(*start, bearing_a, len_a)
    p2 = _offset(*p1, bearing_b, len_b)
    p3 = _offset(*start, bearing_b, len_b)
    return [start, p1, p2, p3, start]


def route_similarity(a: list[list[float]], b: list[list[float]], near_m: float = 40.0) -> float:
    """0 to 1: the larger share of either route that lies within near_m of the other."""
    lat0 = a[0][1]
    kx = 111_320 * math.cos(math.radians(lat0))

    def samples(coords):
        pts = [((lon + 73.98) * kx, (lat - lat0) * M_PER_DEG_LAT) for lon, lat in (c[:2] for c in coords)]
        out = []
        for p, q in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(q[0] - p[0], q[1] - p[1]) // 20))
            out += [(p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n) for k in range(n)]
        return out + [pts[-1]]

    def share_near(src, dst):
        grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
        for x, y in dst:
            grid.setdefault((int(x // near_m), int(y // near_m)), []).append((x, y))
        hits = 0
        for x, y in src:
            cx, cy = int(x // near_m), int(y // near_m)
            if any(
                math.hypot(x - ox, y - oy) <= near_m
                for gx in (cx - 1, cx, cx + 1)
                for gy in (cy - 1, cy, cy + 1)
                for ox, oy in grid.get((gx, gy), ())
            ):
                hits += 1
        return hits / len(src)

    sa, sb = samples(a), samples(b)
    return max(share_near(sa, sb), share_near(sb, sa))


# --- scoring -------------------------------------------------------------------------


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def shape_score(m: ShapeMetrics) -> float:
    """0 to 100. Fewer turns, longer straight runs, a compact shape and no retracing score higher.

    The weights (turns 40, straight runs 25, compactness 25, retracing 10) are a first
    judgment, to be tuned with the "I ran it" ratings.
    """
    f_turns = _clamp(1 - (m.turns_per_mile - 1) / 9)  # 1 turn per mile is ideal, 10 or more is worst
    f_straight = _clamp(m.pct_in_long_runs / 100)
    f_compact = _clamp((m.compactness or 0.0) / 0.7)  # a square is 0.79
    f_retrace = 1 - _clamp(m.retraced_pct / MAX_RETRACED_PCT)
    return 100 * (0.40 * f_turns + 0.25 * f_straight + 0.25 * f_compact + 0.10 * f_retrace)


# --- generation ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Spec:
    aspect: float
    sign_a: int
    sign_b: int
    transpose: bool

    @property
    def label(self) -> str:
        t = " (short side along grid)" if self.transpose else ""
        return f"rectangle {self.aspect:g}:1{t}, {'+' if self.sign_a > 0 else '-'}{'+' if self.sign_b > 0 else '-'}"


def _rectangle_specs() -> list[_Spec]:
    return [
        _Spec(aspect, sa, sb, transpose)
        for aspect in ASPECTS
        for transpose in ((False,) if aspect == 1.0 else (False, True))
        for sa in (1, -1)
        for sb in (1, -1)
    ]


def _fit(make_route: Callable[[float], Route], target_m: float) -> Route:
    """Route at scale 1, then rescale by requested/actual until close enough; keep the closest."""
    scale, best, best_miss = 1.0, None, math.inf
    for _ in range(MAX_RESCALES + 1):
        try:
            route = make_route(scale)
        except RoutingError:
            if best is None:
                raise
            break
        miss = abs(percent_off(target_m, route.distance_m))
        if miss < best_miss:
            best, best_miss = route, miss
        if miss <= RESCALE_STOP_PCT or route.distance_m <= 0:
            break
        scale *= target_m / route.distance_m
    return best


def _evaluate(method: str, label: str, route: Route, miles: float, rejected: Counter) -> Candidate | None:
    try:
        shape = shape_metrics(route.coordinates)
    except ValueError:
        rejected["degenerate"] += 1
        return None
    if shape.compactness is None:
        rejected["not_a_loop"] += 1
        return None
    if shape.retraced_pct > MAX_RETRACED_PCT:
        rejected["retraced"] += 1
        return None
    if shape.compactness < MIN_COMPACTNESS:
        rejected["too_thin"] += 1
        return None
    miss = percent_off(miles, meters_to_miles(route.distance_m))
    return Candidate(method, label, route, shape, shape_score(shape), miss, abs(miss) <= TOLERANCE_PCT)


def _dedupe(ranked: list[Candidate], limit: int) -> list[Candidate]:
    chosen: list[Candidate] = []
    for c in ranked:
        if all(route_similarity(c.route.coordinates, k.route.coordinates) < DUPLICATE_SIMILARITY for k in chosen):
            chosen.append(c)
        if len(chosen) == limit:
            break
    return chosen


def generate_loops(
    lat: float,
    lon: float,
    miles: float,
    grid: GridEstimate,
    route_fn: RouteFn,
    round_trip_fn: RoundTripFn,
    top_n: int = 3,
    workers: int = 4,
) -> GenerationResult:
    target_m = miles_to_meters(miles)
    start = (lat, lon)
    rejected: Counter = Counter()
    candidates: list[Candidate] = []
    generated = 0
    notes: list[str] = []

    def run_all(jobs: list[Callable[[], Candidate | None]]) -> None:
        nonlocal generated
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for outcome in pool.map(lambda job: job(), jobs):
                generated += 1
                if outcome is not None:
                    candidates.append(outcome)

    def rectangle_job(spec: _Spec) -> Callable[[], Candidate | None]:
        def job():
            def make_route(scale: float) -> Route:
                half = target_m / 2 * scale
                long_side = half * spec.aspect / (1 + spec.aspect)
                len_a, len_b = (half - long_side, long_side) if spec.transpose else (long_side, half - long_side)
                return route_fn(rectangle_corners(start, grid.angle_deg, len_a, len_b, spec.sign_a, spec.sign_b))

            try:
                route = _fit(make_route, target_m)
            except RoutingError:
                rejected["routing_failed"] += 1
                return None
            return _evaluate("rectangle", spec.label, route, miles, rejected)

        return job

    def round_trip_job(seed: int) -> Callable[[], Candidate | None]:
        def job():
            try:
                route = _fit(lambda scale: round_trip_fn(lat, lon, target_m * scale, seed), target_m)
            except RoutingError:
                rejected["routing_failed"] += 1
                return None
            return _evaluate("round_trip", f"round trip, seed {seed}", route, miles, rejected)

        return job

    # Rectangles are always tried: they route along real streets, so even a mixed grid can give a good
    # loop. Where the grid is weak neither method wins everywhere (measured in decision 008), so round
    # trips are generated too and the shape score decides.
    run_all([rectangle_job(s) for s in _rectangle_specs()])
    grid_is_weak = grid.strength < MIN_GRID_STRENGTH
    if grid_is_weak:
        notes.append(
            f"The street grid here is weak (strength {grid.strength:.2f}), so rectangles are less dependable; "
            "also tried GraphHopper round trips and kept whichever scored best."
        )
    if grid_is_weak or not any(c.within_tolerance for c in candidates):
        if not grid_is_weak:
            notes.append("No rectangle reached the distance target; added GraphHopper round trips.")
        run_all([round_trip_job(seed) for seed in FALLBACK_SEEDS])

    in_tolerance = sorted((c for c in candidates if c.within_tolerance), key=lambda c: -c.score)
    if in_tolerance:
        chosen = _dedupe(in_tolerance, top_n)
    else:
        chosen = _dedupe(sorted(candidates, key=lambda c: abs(c.miss_pct)), top_n)
        if chosen:
            notes.append(
                f"No loop came within {TOLERANCE_PCT:g}% of {miles:g} mi. The nearest is "
                f"{abs(chosen[0].miss_pct):.0f}% {'short' if chosen[0].miss_pct < 0 else 'long'}."
            )
        else:
            notes.append("No valid loop could be generated from this start point.")

    return GenerationResult(
        candidates=chosen,
        within_tolerance=bool(chosen) and chosen[0].within_tolerance,
        grid=grid,
        generated=generated,
        rejected=rejected,
        note=" ".join(notes) or None,
    )
