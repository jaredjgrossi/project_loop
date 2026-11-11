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

import bisect
import itertools
import math
import queue
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field

from api.anchors import Anchors
from api.constraints import DEFAULTS
from api.grid import MIN_GRID_STRENGTH, GridEstimate
from api.closures import Closure, passed
from api.along import runs_along
from api.markers import spurs
from api.hills import hill_metrics
from api.geometry import covered_share, passes_through
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
# Most of it retraced: an out-and-back, whatever made it (phone test, 2026-11-11, decision 044; was 70, which left
# a route 67% retraced, with a small loop at the far end, called a loop).
OUT_AND_BACK_MIN_RETRACED_PCT = 50.0
A_TO_B_MAX_RETRACED_PCT = 25.0  # step 8, provisional: more than this and an A-to-B route doubles back

RouteFn = Callable[[list[tuple[float, float]]], Route]  # (lat, lon) points -> route
RoundTripFn = Callable[..., Route]  # (lat, lon, distance_m, seed) -> route
ContextFn = Callable[[list[list[float]]], ContextScores]  # [lon, lat] route -> park, signals, familiarity
AnchorFn = Callable[[float, float, float], list[Anchors]]  # (lat, lon, radius_m) -> anchor sets
AreaRouteFn = Callable[[list[tuple[float, float]], dict], Route]  # (lat, lon) points, GeoJSON area -> route
# Per anchor set; other sources get DEFAULT_ANCHOR_DIRECTIONS. The waterfront set spans the whole shore within reach,
# so it gets more: ranked by point count, the top straight-line directions can all be across the river (cutting the
# straight-line set to 3 lost the Kips Bay 6 mi winner; decision 014).
MAX_ANCHOR_DIRECTIONS = {("familiar", "along"): 4, ("familiar", "straight"): 4, ("water", "along"): 4,
                         ("water", "straight"): 8}
DEFAULT_ANCHOR_DIRECTIONS = 2
SHAPE_KINDS = {  # which route kinds each RunConstraints.shape accepts; a lollipop starts and ends as a loop does
    "loop": ("loop",),  # a hard rule (decision 044): a lollipop is mostly retraced, so it isn't a loop
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
    context: ContextScores | None = None

    def metric_vector(self) -> dict:
        """Every measured number for this candidate, flat, for the candidate pool and the UI (decision 014)."""
        vec = {"distance_m": round(self.route.distance_m), "miss_pct": round(self.miss_pct, 1), **self.shape.as_dict()}
        if self.context is not None:
            vec.update({k: (round(v, 1) if isinstance(v, (int, float)) else v) for k, v in asdict(self.context).items()})
            if self.context.wait_s is not None:
                vec["wait_status"] = "estimate"  # expected wait at lights (decision 015)
            if self.context.crowd_not_scored_pct is not None:
                vec["crowd_status"] = "estimate"  # crowd shares (decision 016)
        return vec


@dataclass(frozen=True)
class Rejection:
    """A job that produced no candidate: routing failed, or a hard rule rejected the route."""

    method: str
    label: str
    reason: str
    candidate: "Candidate | None" = None  # a route of a kind the shape rules out: kept for the "no good loop" note


@dataclass
class GenerationResult:
    candidates: list[Candidate]  # best first
    within_tolerance: bool  # whether the best candidate meets the distance tolerance
    grid: GridEstimate
    generated: int  # candidates attempted
    rejected: Counter = field(default_factory=Counter)  # reason -> count
    note: str | None = None
    pool: list[dict] = field(default_factory=list)  # every job's outcome with its metric vector (decision 014)
    timing: dict = field(default_factory=dict)  # seconds: first candidate, when the winner arrived, total
    # "Best of N" (decision 020): distinct routes that passed every hard rule within the distance limit, with
    # duplicates dropped by the same rule as the top 3. None when no route came within the limit.
    best_of: int | None = None
    provisional: list[Candidate] = field(default_factory=list)  # the top N when flagged provisional (decision 018)
    # Decision 044: the best routes of the kinds the shape ruled out, for a "no good loop from here" answer.
    fallback: list[Candidate] = field(default_factory=list)


# --- geometry ------------------------------------------------------------------------


def _meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0])), (a[0] - b[0]) * M_PER_DEG_LAT)


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
    closures: tuple[Closure, ...] = ()
    # step 9: (GeoJSON shape, meters, None) the route must pass, each one; decision 035: (ring, meters, share) a lap
    # it must run along
    through: tuple[tuple[dict, float, float | None], ...] = ()
    along: tuple = ()  # step 8b: streets (along.Along) a route may cross but not run along
    spurs_ok: bool = False  # decision 044: a past route rebuilt or run again keeps the spurs the runner ran


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
    method: str, kind: Kind | None, label: str, route: Route, rules: _Rules,
    allowed: tuple[str, ...] = (),
) -> Candidate | Rejection:
    """kind=None: classify by geometry (anchored loops), keeping only the kinds in `allowed`."""
    if touched(route.coordinates, list(rules.avoid)):
        return Rejection(method, label, "no_go_zone")
    if passed(route.coordinates, rules.closures):  # decision 017: a hard rule, like a no-go zone
        return Rejection(method, label, "closure")
    if rules.along and runs_along(route.coordinates, rules.along):  # step 8b (decision 036)
        return Rejection(method, label, "runs_along")
    for shape, tol, share in rules.through:  # step 9: through or along every via place; 035: a lap of each ring
        if share is None and not passes_through(route.coordinates, shape, tol):
            return Rejection(method, label, "misses_via")
        if share is not None and covered_share(route.coordinates, shape, tol) < share:
            return Rejection(method, label, "misses_lap")
    try:
        shape = shape_metrics(route.coordinates)
    except ValueError:
        return Rejection(method, label, "degenerate")
    if not rules.spurs_ok and spurs(route.coordinates):  # decision 044: no padding with a quick out-and-back
        return Rejection(method, label, "spur")
    unwanted = False
    if kind is None:
        kind = _classify(shape)
        if kind is None:
            return Rejection(method, label, "too_thin")
        unwanted = kind not in allowed
    elif kind == "out_and_back":
        if shape.retraced_pct < OUT_AND_BACK_MIN_RETRACED_PCT:
            return Rejection(method, label, "not_out_and_back")
    elif kind == "a_to_b":  # step 8: a detour that doubles back on itself isn't a way there
        if shape.retraced_pct > A_TO_B_MAX_RETRACED_PCT:
            return Rejection(method, label, "retraced")
    elif kind == "loop":
        if shape.compactness is None:
            return Rejection(method, label, "not_a_loop")
        if shape.retraced_pct > MAX_RETRACED_PCT:
            return Rejection(method, label, "retraced")
        if shape.compactness < MIN_COMPACTNESS:
            return Rejection(method, label, "too_thin")
    miss = percent_off(rules.miles, meters_to_miles(route.distance_m))
    context = rules.context_fn(route.coordinates) if rules.context_fn else None
    hills = hill_metrics(route.coordinates, route.elevation) if rules.prefs.get("hills") == "avoid" else None
    ranking = rank(kind, shape, rules.prefs, context, hills)
    c = Candidate(method, label, route, shape, ranking.score, miss, abs(miss) <= TOLERANCE_PCT, kind, ranking, context)
    return Rejection(method, label, f"unwanted_{kind}", candidate=c) if unwanted else c


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


def _select(candidates: list[Candidate], top_n: int, shape: str) -> list[Candidate]:
    """The top N from candidates in plan order: within tolerance by score (ties in plan order), duplicates dropped, and
    the best of each kind offered for "any"; with none within tolerance, the nearest by distance."""
    in_tolerance = sorted((c for c in candidates if c.within_tolerance), key=lambda c: -c.score)
    if not in_tolerance:
        return _dedupe(sorted(candidates, key=lambda c: abs(c.miss_pct)), top_n)
    chosen = _dedupe(in_tolerance, top_n)
    return _offer_both_kinds(chosen, in_tolerance) if shape == "any" else chosen


def select_from_pool(candidates: list[Candidate], top_n: int, shape: str) -> tuple[list[Candidate], int | None]:
    """A shape-only edit (phone test, 2026-11-10): the top N of the kinds `shape` accepts, from a finished build's
    candidates, and how many distinct ones that was ("Best of N"). Nothing when none of those kinds came within the
    distance limit: then the caller builds again."""
    kinds = SHAPE_KINDS[shape]
    fitting = sorted((c for c in candidates if c.kind in kinds and c.within_tolerance), key=lambda c: -c.score)
    if not fitting:
        return [], None
    return _select(fitting, top_n, shape), len(_dedupe(fitting, len(fitting)))


PRIORITY = {"anchors": 0, "anchored": 1, "anchored_straight": 2, "out_and_back": 3, "rectangle": 4, "round_trip": 5}
# The top 3 is flagged provisional once every anchor lookup and anchored job (along the feature and straight-line) has
# finished: anchored routes are #1 at most review starts (decision 014). Later tiers keep streaming in (decision 018).
PROVISIONAL_AFTER = PRIORITY["anchored_straight"]


class _TopStream:
    """The current top N as candidates arrive, in plan order, so the last one sent equals the final top N."""

    def __init__(self, top_n: int, shape: str, send: Callable[[dict], None] | None):
        self.top_n, self.shape, self.send = top_n, shape, send
        self.lock = threading.Lock()
        self.items: list[tuple[tuple, int, Candidate]] = []
        self.seq = itertools.count()
        self.shown: list[Candidate] = []
        self.provisional: list[Candidate] | None = None
        self.provisional_s: float | None = None
        self.changes_after = 0  # times #1 changed after the provisional flag

    def _emit(self, event: str, elapsed: float, cands: list[Candidate]) -> None:
        if self.send is not None:
            self.send({"event": event, "elapsed_s": round(elapsed, 3), "provisional": self.provisional is not None,
                       "candidates": list(cands)})

    def add(self, c: Candidate, elapsed: float, key: tuple) -> None:
        with self.lock:
            bisect.insort(self.items, (key, next(self.seq), c))
            top = _select([x[2] for x in self.items], self.top_n, self.shape)
            if [id(x) for x in top] == [id(x) for x in self.shown]:
                return
            if self.provisional is not None and top and (not self.shown or top[0] is not self.shown[0]):
                self.changes_after += 1
            self.shown = top
            self._emit("top3", elapsed, top)

    def flag(self, elapsed: float) -> None:
        with self.lock:
            if self.provisional is None:
                self.provisional, self.provisional_s = list(self.shown), elapsed
                self._emit("provisional", elapsed, self.shown)


def _run_prioritized(jobs: list[tuple[int, Callable]], workers: int,
                     on_candidate: Callable[[Candidate, float, tuple], None] | None,
                     tier_max: int | None = None,
                     on_tier_done: Callable[[float], None] | None = None) -> list[tuple[object, float]]:
    """Run jobs on `workers` threads, lowest priority number first. A job returns a Candidate, a Rejection, or a list
    of further (priority, job) pairs to schedule (an anchor lookup returns the routes built from its anchors).
    Returns every outcome with the seconds since the start at which it arrived, in plan order: top-level jobs in the
    order given, an anchor lookup's jobs in the order it returned them, whatever order they finished in. Score ties are
    then broken by plan order, not by which thread finished first (decision 018). Calls on_candidate(candidate,
    seconds, plan key) as each Candidate arrives, so a caller can stream them, and on_tier_done(seconds) once when no
    job of priority tier_max or lower is queued or running."""
    t0 = time.perf_counter()
    tasks: queue.PriorityQueue = queue.PriorityQueue()
    order = itertools.count()
    lock = threading.Lock()
    pending = [0]
    all_done = threading.Event()
    outcomes: list[tuple[tuple, object, float]] = []
    by_tier: Counter = Counter()
    tier_fired = [tier_max is None or on_tier_done is None]
    callback_errors: list[Exception] = []

    def put(priority: int, key: tuple, job: Callable) -> None:
        with lock:
            pending[0] += 1
            by_tier[priority] += 1
        tasks.put((priority, next(order), key, job))

    def worker() -> None:
        while True:
            priority, _, key, job = tasks.get()
            if job is None:
                return
            try:
                try:
                    result = job()
                except RoutingError as exc:  # an anchor lookup or router failing outright
                    result = Rejection("job", str(exc)[:80], "routing_failed")
                except Exception as exc:  # anything else is recorded, never left to kill the thread (decision 015)
                    result = Rejection("job", f"{type(exc).__name__}: {exc}"[:120], f"error: {type(exc).__name__}")
                if isinstance(result, list):
                    for i, (p, j) in enumerate(result):
                        put(p, (*key, i), j)
                else:
                    elapsed = time.perf_counter() - t0
                    with lock:
                        outcomes.append((key, result, elapsed))
                    if on_candidate is not None and isinstance(result, Candidate):
                        try:
                            on_candidate(result, elapsed, key)
                        except Exception as exc:  # a streaming callback failing: kept for the caller, and the
                            with lock:            # thread lives on, so the queue still drains (a dead worker hung
                                callback_errors.append(exc)  # the build, 2026-11-09)

            finally:
                fire = False
                with lock:
                    pending[0] -= 1
                    by_tier[priority] -= 1
                    if not tier_fired[0] and sum(n for p, n in by_tier.items() if p <= tier_max) == 0:
                        tier_fired[0] = fire = True
                    if pending[0] == 0:
                        all_done.set()
                if fire:
                    try:
                        on_tier_done(time.perf_counter() - t0)
                    except Exception as exc:
                        with lock:
                            callback_errors.append(exc)

    if not jobs:
        return []
    for i, (p, j) in enumerate(jobs):
        put(p, (i,), j)
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, workers))]
    for th in threads:
        th.start()
    all_done.wait()
    for _ in threads:
        tasks.put((math.inf, next(order), (), None))
    for th in threads:
        th.join()
    if callback_errors:
        raise callback_errors[0]
    return [(result, elapsed) for _, result, elapsed in sorted(outcomes, key=lambda o: o[0])]


def _pool_entry(outcome, elapsed: float, chosen: bool) -> dict:
    """One job's outcome for the candidate pool (decision 014): JSON-ready, with the metric vector if it produced a
    route that passed the hard rules."""
    if isinstance(outcome, Rejection):
        return {"method": outcome.method, "label": outcome.label, "status": "rejected", "reason": outcome.reason,
                "elapsed_s": round(elapsed, 3)}
    c = outcome
    return {
        "method": c.method, "label": c.label, "kind": c.kind,
        "status": "chosen" if chosen else ("ranked" if c.within_tolerance else "out_of_tolerance"),
        "elapsed_s": round(elapsed, 3), "score": round(c.score, 1), "metrics": c.metric_vector(),
        "dimensions": [] if c.ranking is None else [
            {"key": d.key, "label": d.label, "status": d.status, "value": d.value,
             "fit": None if d.fit is None else round(d.fit, 3), "weight": d.weight} for d in c.ranking.dimensions],
    }


def generate_loops(
    lat: float,
    lon: float,
    miles: float,
    grid: GridEstimate,
    route_fn: RouteFn,
    round_trip_fn: RoundTripFn,
    top_n: int = 3,
    workers: int = 6,  # decision 018: with context scored in worker processes, 6 threads beat 4 and 8
    shape: str = "loop",  # RunConstraints.shape: "loop", "out_and_back" or "any"
    prefs: dict | None = None,  # resolved preferences; neutral defaults when None
    avoid: list[NoGoZone] | tuple[NoGoZone, ...] = (),
    closures: list[Closure] | tuple[Closure, ...] = (),  # known closures near the start (decision 017)
    context_fn: ContextFn | None = None,  # scores park/water, signals, familiarity; those stay not_scored without it
    anchor_fn: AnchorFn | None = None,  # optional: points on the runner's own corridors (familiar routes)
    # Parks, waterfront and catalog corridors from OSM, for every runner: one function, or one per source so they
    # are fetched in parallel.
    feature_anchor_fn: AnchorFn | Sequence[AnchorFn] | None = None,
    area_route_fn: AreaRouteFn | None = None,  # routes anchored candidates preferring the feature's area, if given
    on_candidate: Callable[[Candidate, float], None] | None = None,  # streaming: each candidate as it passes the rules
    # Streaming the top N (decision 018): {"event": "top3" | "provisional" | "final", "elapsed_s", "provisional",
    # "candidates"}. "top3" whenever it changes, "provisional" once the anchored tiers are done, "final" at the end.
    on_top3: Callable[[dict], None] | None = None,
    # Step 9 (via places): only the anchored jobs (the features the vias are on), plus jobs built from the rules by
    # extra_jobs, and every route must pass each `through` shape.
    only_anchored: bool = False,
    extra_jobs: Callable[["_Rules"], list[tuple[int, Callable]]] | None = None,
    through: Sequence[tuple[dict, float, float | None]] = (),
    along: Sequence = (),  # step 8b: streets not to run along (along.Along)
    spurs_ok: bool = False,  # decision 044: following a past route
) -> GenerationResult:
    target_m = miles_to_meters(miles)
    start = (lat, lon)
    rules = _Rules(miles, prefs or DEFAULTS, tuple(avoid), context_fn, tuple(closures), tuple(through), tuple(along),
                   spurs_ok)
    notes: list[str] = []

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
                return Rejection("rectangle", spec.label, "routing_failed")
            return _evaluate("rectangle", "loop", spec.label, route, rules)

        return job

    def round_trip_job(seed: int) -> Callable[[], Candidate | None]:
        def job():
            try:
                route = _fit(lambda scale: round_trip_fn(lat, lon, target_m * scale, seed), target_m)
            except RoutingError:
                return Rejection("round_trip", f"round trip, seed {seed}", "routing_failed")
            return _evaluate("round_trip", "loop", f"round trip, seed {seed}", route, rules)

        return job

    def out_and_back_job(heading: float) -> Callable[[], Candidate | None]:
        bearing = (grid.angle_deg + heading) % 360

        def job():
            def make_route(scale: float) -> Route:
                return route_fn([start, _offset(*start, bearing, target_m / 2 * scale), start])

            label = f"out-and-back, heading {bearing:.0f} degrees"
            try:
                route = _fit(make_route, target_m)
            except RoutingError:
                return Rejection("out_and_back", label, "routing_failed")
            return _evaluate("out_and_back", "out_and_back", label, route, rules)

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

        along = len(far) > 3 and far[3] is not None  # walking distances along the feature (decision 014)
        tail = next((p for p in reversed(points) if along and far[3] - p[3] >= 150), points[0])
        tail_bearing = math.degrees(math.atan2((far[1] - tail[1]) * math.cos(math.radians(lat)), far[0] - tail[0])) % 360
        access = 1.3 * _meters(start, entry) if entry is not None else 0.0  # streets to the entry, estimated

        def length_if(p, scale: float) -> float:
            """Estimated total length with a turnaround at p, against the scaled target."""
            back = p[3] + access if out_and_back else 1.3 * p[2]  # same way back, or straight-ish home from p
            return access + p[3] + back - target_m * scale

        def job():
            def make_route(scale: float) -> Route:
                via = [entry] if entry is not None else []
                if along:
                    # Turnaround by walking distance along the feature, so bends, bridges and gaps don't throw it off.
                    best = min(points, key=lambda p: abs(length_if(p, scale)))
                    past_end = best is far and length_if(far, scale) < -0.02 * target_m * scale
                    turn = best[:2]
                else:
                    want = radius * scale
                    past_end = want > far[2] * 1.02
                    turn = min(points, key=lambda p: abs(p[2] - want))[:2]
                if not past_end:
                    # Rescaling picks another anchor point rather than sliding the turnaround off the feature.
                    out = [p for p in via if p != turn] + [turn]
                else:
                    # The feature is too small for the distance: run through it to its far end and keep going the
                    # same way to a turnaround that fits (decision 012).
                    if along:
                        # Keep going the way the path was heading at its end, for half the shortfall (there and back).
                        beyond_pt = _offset(*far[:2], tail_bearing, abs(length_if(far, scale)) / 2)
                    else:
                        beyond_pt = _offset(*start, bearing, radius * scale)
                    out = [p for p in via if p != far[:2]] + [far[:2], beyond_pt]
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
                return Rejection(f"{anchors.source}_{'out_and_back' if out_and_back else 'loop'}", where, "routing_failed")
            beyond = " and beyond" if id(route) in beyond_ids else ""
            if out_and_back:
                return _evaluate(f"{anchors.source}_out_and_back", "out_and_back",
                                 f"out-and-back {where}{beyond}, heading {bearing:.0f} degrees", route, rules)
            return _evaluate(f"{anchors.source}_loop", None, f"loop {where}{beyond}, heading {bearing:.0f} degrees",
                             route, rules, allowed=SHAPE_KINDS[shape])

        return job

    def both_ways_job(anchors: Anchors) -> Callable[[], Candidate | None]:
        """Reach the feature, run one branch to a turnaround, back past the entry along the other branch to a second
        turnaround, back to the entry and home. For features too short one way (decision 014): from Kips Bay the
        waterfront runs 1.9 km south and 0.7 km north between gaps, and neither branch alone makes 4 mi."""
        entry, (one, two) = anchors.entry, anchors.directions[:2]
        router = (lambda pts: area_route_fn(pts, anchors.area)) if area_route_fn and anchors.area else route_fn
        access = 1.3 * _meters(start, entry)
        where = {"water": "on the waterfront", "corridor": f"on {anchors.name}", "park": f"through {anchors.name}"}.get(
            anchors.source, anchors.name or anchors.source)

        def job():
            def make_route(scale: float) -> Route:
                need = max(0.0, (target_m * scale - 2 * access) / 2)  # walking distance along the feature, each way
                a = min(one[-1][3], need / 2)
                b = min(two[-1][3], need - a)
                a = min(one[-1][3], need - b)  # if the second branch is short, take more of the first
                pa = min(one, key=lambda p: abs(p[3] - a))[:2]
                pb = min(two, key=lambda p: abs(p[3] - b))[:2]
                return router([start, entry, pa, entry, pb, entry, start])

            try:
                route = _fit(make_route, target_m)
            except RoutingError:
                return Rejection(f"{anchors.source}_out_and_back", f"out-and-back both ways {where}", "routing_failed")
            return _evaluate(f"{anchors.source}_out_and_back", "out_and_back", f"out-and-back both ways {where}",
                             route, rules)

        return job

    def anchored_jobs(sets: list[Anchors], radius: float) -> list[Callable[[], Candidate | None]]:
        jobs = []
        for anchors in sets:
            two_branches = [d for d in anchors.directions if d][:2]
            if (shape in ("out_and_back", "any") and anchors.entry is not None and len(two_branches) == 2
                    and all(len(d[-1]) > 3 for d in two_branches)):
                jobs.append(both_ways_job(Anchors(anchors.entry, two_branches, anchors.source, anchors.name, anchors.area)))
            limit = MAX_ANCHOR_DIRECTIONS.get((anchors.source, anchors.placement), DEFAULT_ANCHOR_DIRECTIONS)
            for pts in [p for p in anchors.directions if p][:limit]:
                if shape in ("out_and_back", "any"):
                    jobs.append(anchored_job(anchors, pts, radius, out_and_back=True))
                if shape in ("loop", "any") and anchors.entry is not None:
                    jobs.append(anchored_job(anchors, pts, radius, out_and_back=False))
        return jobs

    # Generation order (decision 014): anchor lookups first, then the job types most likely to win, so the first
    # candidate arrives early and is usually the eventual #1. Measured across the review starts after decision 012,
    # anchored routes were #1 at 11 of 15 starts, rectangles at 4.
    radius = target_m / 2 / 1.25  # turnaround roughly half the distance out, ~25% for streets not running straight
    jobs: list[tuple[int, Callable]] = []
    sources = [] if feature_anchor_fn is None else (
        list(feature_anchor_fn) if isinstance(feature_anchor_fn, (list, tuple)) else [feature_anchor_fn])
    if anchor_fn is not None:
        sources.append(anchor_fn)
    for fetch in sources:
        jobs.append((PRIORITY["anchors"], lambda fetch=fetch: [
            (PRIORITY["anchored" if a.placement == "along" else "anchored_straight"], j)
            for a in fetch(lat, lon, radius) for j in anchored_jobs([a], radius)]))
    if extra_jobs is not None:
        jobs += extra_jobs(rules)
    if shape in ("out_and_back", "any") and not only_anchored:
        jobs += [(PRIORITY["out_and_back"], out_and_back_job(h)) for h in OUT_AND_BACK_HEADINGS]
    if shape in ("loop", "any") and not only_anchored:
        # Rectangles are always tried: they route along real streets, so even a mixed grid can give a good loop.
        # Round trips are tried everywhere too (decision 012): the one generator not tied to the grid.
        jobs += [(PRIORITY["rectangle"], rectangle_job(s)) for s in _rectangle_specs()]
        jobs += [(PRIORITY["round_trip"], round_trip_job(seed)) for seed in FALLBACK_SEEDS]
        if grid.strength < MIN_GRID_STRENGTH:
            notes.append(
                f"The street grid here is weak (strength {grid.strength:.2f}), so rectangles are less dependable."
            )
    return run_and_finish(jobs, workers, top_n, shape, miles, grid, notes, on_candidate, on_top3)


def run_and_finish(jobs: list[tuple[int, Callable]], workers: int, top_n: int, shape: str, miles: float,
                   grid: GridEstimate, notes: list[str], on_candidate=None, on_top3=None) -> GenerationResult:
    """Run the jobs, stream the top N as they arrive, then pick the top N and build the result: shared by loops and
    A-to-B routes (step 8). `shape` picks which kinds are offered ("any" offers the best of each kind)."""
    stream = _TopStream(top_n, shape, on_top3)

    def arrived_candidate(c: Candidate, elapsed: float, key: tuple) -> None:
        stream.add(c, elapsed, key)
        if on_candidate is not None:
            on_candidate(c, elapsed)

    outcomes = _run_prioritized(jobs, workers, arrived_candidate, tier_max=PROVISIONAL_AFTER, on_tier_done=stream.flag)
    candidates = [c for c, _ in outcomes if isinstance(c, Candidate)]
    rejected = Counter(r.reason for r, _ in outcomes if isinstance(r, Rejection))
    generated = len(outcomes)

    in_tolerance = sorted((c for c in candidates if c.within_tolerance), key=lambda c: -c.score)
    best_of = len(_dedupe(in_tolerance, len(in_tolerance))) if in_tolerance else None
    chosen = _select(candidates, top_n, shape)
    if not in_tolerance:
        if chosen:
            notes.append(
                f"No loop came within {TOLERANCE_PCT:g}% of {miles:g} mi. The nearest is "
                f"{abs(chosen[0].miss_pct):.0f}% {'short' if chosen[0].miss_pct < 0 else 'long'}."
            )
        else:
            notes.append("No valid loop could be generated from this start point.")

    arrived = {id(c): s for c, s in outcomes}
    first_ok = min((s for c, s in outcomes if isinstance(c, Candidate) and c.within_tolerance), default=None)
    timing = {
        "first_candidate_s": first_ok,
        "first_any_s": min((s for c, s in outcomes if isinstance(c, Candidate)), default=None),
        "winner_arrived_s": arrived[id(chosen[0])] if chosen else None,
        "total_s": max((s for _, s in outcomes), default=0.0),
        "provisional_s": stream.provisional_s,
        "number1_changes_after_provisional": stream.changes_after,
    }
    stream._emit("final", timing["total_s"], chosen)
    chosen_ids = {id(c) for c in chosen}
    return GenerationResult(
        candidates=chosen,
        within_tolerance=bool(chosen) and chosen[0].within_tolerance,
        grid=grid,
        generated=generated,
        rejected=rejected,
        note=" ".join(notes) or None,
        pool=[_pool_entry(o, s, id(o) in chosen_ids) for o, s in outcomes],
        timing=timing,
        best_of=best_of,
        provisional=stream.provisional or [],
        fallback=_select([r.candidate for r, _ in outcomes if isinstance(r, Rejection) and r.candidate], top_n, "any"),
    )
