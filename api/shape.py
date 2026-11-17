"""Shape metrics for a route: how many turns, how straight, whether it retraces itself.

Pure geometry on a list of [lon, lat] points, no database or network. Distances
come from a local flat projection centered on the route (meters), which is
accurate to well under 1% over the ~10 km extent of a run in NYC.

The same definitions are used for generated routes and for the reviewer's map-matched real runs, so the two can be
compared (decision 011).

Definitions (decision 008, turns revised in decision 011):
- turn: a direction change of at least TURN_DEGREES after removing spurs (out-and-back excursions of up to
  SPUR_MAX_M, which map matching and waypoint snapping leave behind) and simplifying the line to
  SIMPLIFY_TOLERANCE_M, so GPS jitter, sidewalk jogs at crossings and wiggles on curved paths are ignored but
  street corners are kept (a staircase of 80 m blocks still counts every corner). On a closed loop the corner at the
  start/finish counts, so the number doesn't depend on where the loop starts.
- straight run: the distance between consecutive turns.
- retraced: a point within RETRACE_RADIUS_M of another part of the route that is more than RETRACE_MIN_SEPARATION_M
  away along the route. Both passes count, so a pure out-and-back is about 100% (analyze_routes.py counts only
  the second pass, so its numbers are about half of these).
- out and back: the share of the second half (by distance) within RETRACE_RADIUS_M of the first half.
- closure: the straight-line gap between start and finish.
- width and compactness need a closed loop: width is 2 x area / perimeter and
  compactness is 4 x pi x area / perimeter^2 (1 for a circle, about 0.79 for a square).
"""

import math
from dataclasses import asdict, dataclass

METERS_PER_MILE = 1609.344
TURN_DEGREES = 45
SIMPLIFY_TOLERANCE_M = 20  # was 8 in decision 008, which counted GPS jitter and sidewalk jogs as turns
SPUR_MAX_M = 50
SPUR_STEP_M = 5
LONG_RUN_M = 500
RETRACE_RADIUS_M = 15
RETRACE_MIN_SEPARATION_M = 150
SAMPLE_STEP_M = 10
CLOSED_LOOP_GAP_M = 30  # start and finish this close count as a closed loop

Point = tuple[float, float]


@dataclass(frozen=True)
class ShapeMetrics:
    distance_miles: float
    turns: int
    turns_per_mile: float
    longest_straight_m: float
    pct_in_long_runs: float
    retraced_pct: float
    mean_width_m: float | None  # closed loops only
    compactness: float | None  # closed loops only
    out_and_back_pct: float | None = None
    closure_m: float | None = None

    def as_dict(self) -> dict:
        """Rounded for display and GeoJSON properties."""
        d = asdict(self)
        digits = {
            "distance_miles": 2, "turns_per_mile": 1, "longest_straight_m": 0,
            "pct_in_long_runs": 0, "retraced_pct": 0, "mean_width_m": 0, "compactness": 2,
            "out_and_back_pct": 0, "closure_m": 0,
        }
        for key, n in digits.items():
            if d[key] is not None:
                d[key] = round(d[key], n) if n else int(round(d[key]))
        return d


def _project(coords: list[list[float]]) -> list[Point]:
    lat0 = sum(c[1] for c in coords) / len(coords)
    lon0 = sum(c[0] for c in coords) / len(coords)
    kx = 111_320 * math.cos(math.radians(lat0))
    ky = 110_574
    return [((lon - lon0) * kx, (lat - lat0) * ky) for lon, lat in (c[:2] for c in coords)]


def measured_m(coords: list[list[float]]) -> float:
    """A [lon, lat] line's length in meters as the card measures it: the same projection and sum as the shape
    metrics (`distance_miles`), so a number quoted before the build is the number the card shows after it."""
    pts = _project(coords) if coords else []
    return sum(_dist(a, b) for a, b in zip(pts, pts[1:]))


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _simplify(pts: list[Point], tol: float) -> list[Point]:
    """Douglas-Peucker, iterative so long routes can't hit the recursion limit."""
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        lo, hi = stack.pop()
        a, b = pts[lo], pts[hi]
        seg = _dist(a, b)
        far, far_i = -1.0, None
        for i in range(lo + 1, hi):
            p = pts[i]
            if seg == 0:
                d = _dist(p, a)
            else:
                d = abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / seg
            if d > far:
                far, far_i = d, i
        if far_i is not None and far > tol:
            keep.add(far_i)
            stack += [(lo, far_i), (far_i, hi)]
    return [pts[i] for i in sorted(keep)]


def _resample(pts: list[Point], step: float) -> list[Point]:
    """Points every `step` meters along the line, ending exactly on its last point."""
    out = [pts[0]]
    carry = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = _dist(a, b)
        pos = step - carry
        while pos <= seg:
            t = pos / seg
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
            pos += step
        carry = seg - (pos - step)
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def _remove_spurs(pts: list[Point]) -> list[Point]:
    """Cut out-and-back excursions of up to SPUR_MAX_M: where the line comes back to within SPUR_STEP_M of where it
    was, no more than 2 x SPUR_MAX_M later, having gone somewhere in between."""
    p = _resample(pts, SPUR_STEP_M)
    window = int(2 * SPUR_MAX_M / SPUR_STEP_M)
    out, i = [], 0
    while i < len(p):
        out.append(p[i])
        back_at = None
        for j in range(min(len(p) - 1, i + window), i + 2, -1):
            if _dist(p[i], p[j]) < SPUR_STEP_M and max(_dist(p[i], p[k]) for k in range(i + 1, j)) > 2 * SPUR_STEP_M:
                back_at = j
                break
        i = back_at if back_at is not None else i + 1
    if out[-1] != p[-1]:
        out.append(p[-1])
    return out


def trim_ends(coords: list[list[float]], meters: float) -> list[list[float]]:
    """The route without its first and last `meters`, measured along it; [] if nothing is left.

    Privacy rule for real runs (nothing stored or rendered starts or ends at a door), and applied identically to
    generated routes whenever the two are compared (decision 011).
    """
    pts = _project(coords)

    def cut(seq):
        along = 0.0
        for i in range(1, len(seq)):
            along += _dist(seq[i - 1], seq[i])
            if along >= meters - 1e-6:  # float sums land a hair under round distances
                return i
        return len(seq)

    head, tail = cut(pts), len(pts) - cut(pts[::-1])
    return [list(c[:2]) for c in coords[head:tail]] if tail - head >= 2 else []


def _out_and_back_share(pts: list[Point], total: float) -> float:
    samples = _resample(pts, SAMPLE_STEP_M)
    half = len(samples) // 2
    first = samples[:half]
    cell = RETRACE_RADIUS_M
    grid: dict[tuple[int, int], list[Point]] = {}
    for x, y in first:
        grid.setdefault((int(x // cell), int(y // cell)), []).append((x, y))
    second = samples[half:]
    hits = sum(
        any(_dist((x, y), q) <= RETRACE_RADIUS_M
            for gx in (int(x // cell) - 1, int(x // cell), int(x // cell) + 1)
            for gy in (int(y // cell) - 1, int(y // cell), int(y // cell) + 1)
            for q in grid.get((gx, gy), ()))
        for x, y in second
    )
    return 100 * hits / max(1, len(second))


def _bearing(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360


def _angle_between(b1: float, b2: float) -> float:
    return abs((b2 - b1 + 180) % 360 - 180)


def _turns_and_runs(s: list[Point], closed: bool) -> tuple[int, list[float]]:
    """Turn count and the straight-run lengths between turns, for a simplified route."""
    edges = [_dist(s[i], s[i + 1]) for i in range(len(s) - 1)]
    if closed:
        v = s[:-1]  # the last point repeats the first
        n = len(v)
        turn_at = [
            i for i in range(n)
            if _angle_between(_bearing(v[i - 1], v[i]), _bearing(v[i], v[(i + 1) % n])) >= TURN_DEGREES
        ]
        if len(turn_at) < 2:
            return len(turn_at), [sum(edges)]
        runs = []
        for a, b in zip(turn_at, turn_at[1:] + [turn_at[0] + n]):
            runs.append(sum(edges[k % n] for k in range(a, b)))
        return len(turn_at), runs

    turn_at = [
        i for i in range(1, len(s) - 1)
        if _angle_between(_bearing(s[i - 1], s[i]), _bearing(s[i], s[i + 1])) >= TURN_DEGREES
    ]
    bounds = [0] + turn_at + [len(s) - 1]
    return len(turn_at), [sum(edges[a:b]) for a, b in zip(bounds, bounds[1:])]


def _retraced_share(pts: list[Point], total: float, closed: bool) -> float:
    samples: list[tuple[float, float, float]] = []  # x, y, distance along route
    along = 0.0
    for p, q in zip(pts, pts[1:]):
        seg = _dist(p, q)
        n = max(1, int(seg // SAMPLE_STEP_M))
        for k in range(n):
            t = k / n
            samples.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]), along + t * seg))
        along += seg

    cell = RETRACE_RADIUS_M
    grid: dict[tuple[int, int], list[int]] = {}
    for idx, (x, y, _) in enumerate(samples):
        grid.setdefault((int(x // cell), int(y // cell)), []).append(idx)

    hits = 0
    for x, y, d in samples:
        cx, cy = int(x // cell), int(y // cell)
        found = False
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for j in grid.get((gx, gy), ()):
                    ox, oy, od = samples[j]
                    gap = abs(d - od)
                    if closed:
                        gap = min(gap, total - gap)
                    if gap > RETRACE_MIN_SEPARATION_M and math.hypot(x - ox, y - oy) < RETRACE_RADIUS_M:
                        found = True
                        break
                if found:
                    break
            if found:
                break
        hits += found
    return 100 * hits / len(samples)


def shape_metrics(coords: list[list[float]]) -> ShapeMetrics:
    """Shape metrics for a route given as [lon, lat] points."""
    pts = _project(coords) if coords else []
    pts = [p for i, p in enumerate(pts) if i == 0 or _dist(p, pts[i - 1]) > 0]  # drop repeated points
    if len(pts) < 2:
        raise ValueError("a route needs at least two distinct points")
    total = sum(_dist(a, b) for a, b in zip(pts, pts[1:]))
    closure = _dist(pts[0], pts[-1])
    closed = len(pts) > 3 and closure <= CLOSED_LOOP_GAP_M
    if closed:
        pts = pts[:-1] + [pts[0]]  # make the loop exact

    despiked = _remove_spurs(pts)
    if closed:
        despiked = despiked[:-1] + [despiked[0]]
    turns, runs = _turns_and_runs(_simplify(despiked, SIMPLIFY_TOLERANCE_M), closed)
    run_total = sum(runs) or 1.0
    miles = total / METERS_PER_MILE

    width = compactness = None
    if closed:
        area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:]))) / 2
        width = 2 * area / total
        compactness = 4 * math.pi * area / total**2

    return ShapeMetrics(
        distance_miles=miles,
        turns=turns,
        turns_per_mile=turns / miles,
        longest_straight_m=max(runs),
        pct_in_long_runs=100 * sum(r for r in runs if r >= LONG_RUN_M) / run_total,
        retraced_pct=_retraced_share(pts, total, closed),
        mean_width_m=width,
        compactness=compactness,
        out_and_back_pct=_out_and_back_share(pts, total),
        closure_m=closure,
    )
