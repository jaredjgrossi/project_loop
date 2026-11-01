"""Generate route candidates and rank them (decisions 008 to 012).

Candidate generators, none of which decides the answer on its own:
- grid-aligned rectangles routed through their four corners (long straight runs, few turns);
- GraphHopper round trips, everywhere (decision 012; they used to be added only where the grid was weak);
- out-and-backs: out along a heading to a turnaround at half the distance and back the same way. A first-class
  type, not a penalized loop: most of the reviewer's real runs are out-and-backs;
- anchored routes (decision 012): out to a park, the waterfront or a catalog corridor (api/anchors.py, from OSM, for
  every runner), through its nearest point, to a turnaround on it picked to fit the distance, and back the same way
  (out-and-back) or by the shortest way (loop, or lollipop: out, around and back, which is how most real runs look);
- the same, along ways the runner already runs (decision 011), only when that optional source is given.
Each is rescaled until its routed distance is close to the request. Hard rules reject candidates (no-go zones,
ribbons, an out-and-back that doesn't come back the same way); the rest are ranked against the runner's preferences
by api/ranking.py. If none reaches the distance tolerance, the nearest ones are returned and the miss is stated
(product rule 3).

Pure orchestration: routing is injected, so this module needs no network or database.
"""

import math
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from api.anchors import Anchors
from api.constraints import DEFAULTS
from api.grid import MIN_GRID_STRENGTH, GridEstimate
from api.nogo import NoGoZone, touched
from api.ranking import Kind, Ranking, rank
from api.route_context import ContextScores
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
OUT_AND_BACK_HEADINGS = (0, 90, 180, 270, 45, 135, 225, 315)  # degrees from the grid angle; along the grid first
OUT_AND_BACK_MIN_RETRACED_PCT = 70.0  # less than this and the way back isn't the way out

RouteFn = Callable[[list[tuple[float, float]]], Route]  # (lat, lon) points -> route
RoundTripFn = Callable[..., Route]  # (lat, lon, distance_m, seed) -> route
ContextFn = Callable[[list[list[float]]], ContextScores]  # [lon, lat] route -> park, signals, familiarity
AnchorFn = Callable[[float, float, float], list[Anchors]]  # (lat, lon, radius_m) -> anchor sets
AreaRouteFn = Callable[[list[tuple[float, float]], dict], Route]  # (lat, lon) points, GeoJSON area -> route
# Per anchor set; other sources get DEFAULT_ANCHOR_DIRECTIONS. The waterfront set spans the whole shore within reach,
# so every direction is tried: ranked by point count, the top two can both be across the river.
MAX_ANCHOR_DIRECTIONS = {"familiar": 4, "water": 8}
DEFAULT_ANCHOR_DIRECTIONS = 2
SHAPE_KINDS = {  # which route kinds each RunConstraints.shape accepts; a lollipop starts and ends as a loop does
    "loop": ("loop", "lollipop"),
    "out_and_back": ("out_and_back",),
    "any": ("loop", "lollipop", "out_and_back"),
}

M_PER_DEG_LAT = 110_574


@dataclass(frozen=True)
class Candidate:
    method: str  # "rectangle", "round_trip" or "out_and_back"
    label: str
    route: Route
    shape: ShapeMetrics
    score: float  # combined ranking score, 0 to 100 (provisional weights)
    miss_pct: float  # signed distance miss against the request
    within_tolerance: bool
    kind: Kind = "loop"
    ranking: Ranking | None = None


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
    """0 to 1: the smaller share of either route that lies within near_m of the other, so two routes are
    duplicates only when each mostly runs on the other. (It was the larger share until decision 012, which counted
    a loop as a copy of the out-and-back it shares its way out with.)"""
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
    return min(share_near(sa, sb), share_near(sb, sa))


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


@dataclass(frozen=True)
class _Rules:
    miles: float
    prefs: dict
    avoid: tuple[NoGoZone, ...]
    context_fn: ContextFn | None = None


def _classify(shape: ShapeMetrics) -> Kind | None:
    """What a route that was free to come back any way turned out to be; None for a ribbon."""
    if shape.retraced_pct >= OUT_AND_BACK_MIN_RETRACED_PCT:
        return "out_and_back"
    if shape.retraced_pct > MAX_RETRACED_PCT:
        return "lollipop"
    if shape.compactness is None or shape.compactness < MIN_COMPACTNESS:
        return None
    return "loop"


def _evaluate(
    method: str, kind: Kind | None, label: str, route: Route, rules: _Rules, rejected: Counter,
    allowed: tuple[str, ...] = (),
) -> Candidate | None:
    """kind=None: classify by geometry (anchored loops), keeping only the kinds in `allowed`."""
    if touched(route.coordinates, list(rules.avoid)):
        rejected["no_go_zone"] += 1
        return None
    try:
        shape = shape_metrics(route.coordinates)
    except ValueError:
        rejected["degenerate"] += 1
        return None
    if kind is None:
        kind = _classify(shape)
        if kind is None:
            rejected["too_thin"] += 1
            return None
        if kind not in allowed:
            rejected[f"unwanted_{kind}"] += 1
            return None
    elif kind == "out_and_back":
        if shape.retraced_pct < OUT_AND_BACK_MIN_RETRACED_PCT:
            rejected["not_out_and_back"] += 1
            return None
    elif kind == "loop":
        if shape.compactness is None:
            rejected["not_a_loop"] += 1
            return None
        if shape.retraced_pct > MAX_RETRACED_PCT:
            rejected["retraced"] += 1
            return None
        if shape.compactness < MIN_COMPACTNESS:
            rejected["too_thin"] += 1
            return None
    miss = percent_off(rules.miles, meters_to_miles(route.distance_m))
    context = rules.context_fn(route.coordinates) if rules.context_fn else None
    ranking = rank(kind, shape, rules.prefs, context)
    return Candidate(method, label, route, shape, ranking.score, miss, abs(miss) <= TOLERANCE_PCT, kind, ranking)


def _dedupe(ranked: list[Candidate], limit: int) -> list[Candidate]:
    chosen: list[Candidate] = []
    for c in ranked:
        if all(route_similarity(c.route.coordinates, k.route.coordinates) < DUPLICATE_SIMILARITY for k in chosen):
            chosen.append(c)
        if len(chosen) == limit:
            break
    return chosen


def _offer_both_kinds(chosen: list[Candidate], ranked: list[Candidate]) -> list[Candidate]:
    """When either shape is fine, make sure the options include the best of each kind, if there is one."""
    if len(chosen) < 2:
        return chosen
    for kind in ("loop", "out_and_back"):
        if not any(c.kind == kind for c in chosen):
            best = next((c for c in ranked if c.kind == kind), None)
            if best is not None:
                chosen = chosen[:-1] + [best]
    return sorted(chosen, key=lambda c: -c.score)


def generate_loops(
    lat: float,
    lon: float,
    miles: float,
    grid: GridEstimate,
    route_fn: RouteFn,
    round_trip_fn: RoundTripFn,
    top_n: int = 3,
    workers: int = 4,
    shape: str = "loop",  # RunConstraints.shape: "loop", "out_and_back" or "any"
    prefs: dict | None = None,  # resolved preferences; neutral defaults when None
    avoid: list[NoGoZone] | tuple[NoGoZone, ...] = (),
    context_fn: ContextFn | None = None,  # scores park/water, signals, familiarity; those stay not_scored without it
    anchor_fn: AnchorFn | None = None,  # optional: points on the runner's own corridors (familiar routes)
    feature_anchor_fn: AnchorFn | None = None,  # parks, waterfront and catalog corridors from OSM, for every runner
    area_route_fn: AreaRouteFn | None = None,  # routes anchored candidates preferring the feature's area, if given
) -> GenerationResult:
    target_m = miles_to_meters(miles)
    start = (lat, lon)
    rules = _Rules(miles, prefs or DEFAULTS, tuple(avoid), context_fn)
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
            return _evaluate("rectangle", "loop", spec.label, route, rules, rejected)

        return job

    def round_trip_job(seed: int) -> Callable[[], Candidate | None]:
        def job():
            try:
                route = _fit(lambda scale: round_trip_fn(lat, lon, target_m * scale, seed), target_m)
            except RoutingError:
                rejected["routing_failed"] += 1
                return None
            return _evaluate("round_trip", "loop", f"round trip, seed {seed}", route, rules, rejected)

        return job

    def out_and_back_job(heading: float) -> Callable[[], Candidate | None]:
        bearing = (grid.angle_deg + heading) % 360

        def job():
            def make_route(scale: float) -> Route:
                return route_fn([start, _offset(*start, bearing, target_m / 2 * scale), start])

            try:
                route = _fit(make_route, target_m)
            except RoutingError:
                rejected["routing_failed"] += 1
                return None
            label = f"out-and-back, heading {bearing:.0f} degrees"
            return _evaluate("out_and_back", "out_and_back", label, route, rules, rejected)

        return job

    def anchored_job(anchors: Anchors, points: list[tuple[float, float, float]], radius: float,
                     out_and_back: bool) -> Callable[[], Candidate | None]:
        entry = anchors.entry
        where = {"familiar": "on a route you run", "park": f"through {anchors.name}", "water": "on the waterfront",
                 "corridor": f"on {anchors.name}"}.get(anchors.source, anchors.name or anchors.source)

        far = points[-1]
        bearing = math.degrees(math.atan2((far[1] - lon) * math.cos(math.radians(lat)), far[0] - lat)) % 360
        beyond_ids: set[int] = set()  # routes that went past the feature's far end
        # Prefer staying on the feature (decision 012): otherwise the shortest way to a far turnaround runs inland and
        # the route only touches the water or the park at its tip.
        router = (lambda pts: area_route_fn(pts, anchors.area)) if area_route_fn and anchors.area else route_fn

        def job():
            def make_route(scale: float) -> Route:
                want = radius * scale
                via = [entry] if entry is not None else []
                past_end = want > far[2] * 1.02
                if not past_end:
                    # Rescaling picks another anchor point rather than sliding the turnaround off the feature.
                    turn = min(points, key=lambda p: abs(p[2] - want))[:2]
                    out = [p for p in via if p != turn] + [turn]
                else:
                    # The feature is too small for the distance: run through it to its far end and keep going the
                    # same way to a turnaround that fits (decision 012).
                    out = [p for p in via if p != far[:2]] + [far[:2], _offset(*start, bearing, want)]
                back = out[-2::-1] if out_and_back else []
                try:
                    route = router([start, *out, *back, start])
                except RoutingError:
                    if not past_end:
                        raise
                    # The turnaround past the end is off the map (in the river, say): turn at the far end instead.
                    out = out[:-1]
                    back = out[-2::-1] if out_and_back else []
                    return router([start, *out, *back, start])
                if past_end:
                    beyond_ids.add(id(route))
                return route

            try:
                route = _fit(make_route, target_m)
            except RoutingError:
                rejected["routing_failed"] += 1
                return None
            beyond = " and beyond" if id(route) in beyond_ids else ""
            if out_and_back:
                return _evaluate(f"{anchors.source}_out_and_back", "out_and_back",
                                 f"out-and-back {where}{beyond}, heading {bearing:.0f} degrees", route, rules, rejected)
            return _evaluate(f"{anchors.source}_loop", None, f"loop {where}{beyond}, heading {bearing:.0f} degrees",
                             route, rules, rejected, allowed=SHAPE_KINDS[shape])

        return job

    def anchored_jobs(sets: list[Anchors], radius: float) -> list[Callable[[], Candidate | None]]:
        jobs = []
        for anchors in sets:
            limit = MAX_ANCHOR_DIRECTIONS.get(anchors.source, DEFAULT_ANCHOR_DIRECTIONS)
            for pts in [p for p in anchors.directions if p][:limit]:
                if shape in ("out_and_back", "any"):
                    jobs.append(anchored_job(anchors, pts, radius, out_and_back=True))
                if shape in ("loop", "any") and anchors.entry is not None:
                    jobs.append(anchored_job(anchors, pts, radius, out_and_back=False))
        return jobs

    if shape in ("loop", "any"):
        # Rectangles are always tried: they route along real streets, so even a mixed grid can give a good loop.
        # Round trips are tried everywhere too (decision 012): on a strong grid they lose on shape, but they are the
        # one generator not tied to the grid, and the ranking decides.
        run_all([rectangle_job(s) for s in _rectangle_specs()])
        if grid.strength < MIN_GRID_STRENGTH:
            notes.append(
                f"The street grid here is weak (strength {grid.strength:.2f}), so rectangles are less dependable."
            )
        run_all([round_trip_job(seed) for seed in FALLBACK_SEEDS])
    if shape in ("out_and_back", "any"):
        run_all([out_and_back_job(h) for h in OUT_AND_BACK_HEADINGS])
    # Turnaround roughly half the distance out, allowing ~25% for streets not running straight there.
    radius = target_m / 2 / 1.25
    if feature_anchor_fn is not None:
        run_all(anchored_jobs(feature_anchor_fn(lat, lon, radius), radius))
    if anchor_fn is not None:
        run_all(anchored_jobs(anchor_fn(lat, lon, radius), radius))

    in_tolerance = sorted((c for c in candidates if c.within_tolerance), key=lambda c: -c.score)
    if in_tolerance:
        chosen = _dedupe(in_tolerance, top_n)
        if shape == "any":
            chosen = _offer_both_kinds(chosen, in_tolerance)
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
