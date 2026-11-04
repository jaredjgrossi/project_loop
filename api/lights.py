"""The lights preference (decision 015): a router penalty for runners who wait at lights, and an expected wait at
lights for both kinds of runner, labeled `estimate`.

Runners who wait: signalized crosswalks are made SIGNAL_PRIORITY times as attractive in GraphHopper's per-request
custom model (the router test in decision 015 halved signals for ~15% more distance without pushing routes into the
roadway). Runners who zig-zag: no router penalty; at a red they take the other direction when a same-length staircase
exists, so they only wait where no such alternative exists.

Assumptions behind the estimate (all provisional; stated in decision 015):
- A signal cycle of CYCLE_S seconds, with pedestrian DON'T WALK (including the flashing phase) for RED_FRACTION of
  it. A runner arriving at a random moment waits RED_FRACTION^2 * CYCLE_S / 2 on average (WAIT_PER_SIGNAL_S).
- Zig-zag credit: in a street grid (grid strength at or above MIN_GRID_STRENGTH), a same-length alternative exists
  at a signal when the route over the next LOOKAHEAD_M runs monotonically (its length within MONOTONE_SLACK of the
  grid-aligned L1 distance) and still needs at least one block (BLOCK_M) along both grid axes. Taking the green
  direction then costs no distance. The runner still waits when both directions are red (ALL_RED_FRACTION, the
  clearance interval), so a credited signal costs ALL_RED_WAIT_S.
- Only signalized crosswalks the route walks (OSM crossing=traffic_signals) count. Crossings on road centerlines
  have no crosswalk way and are missed (decision 009).
"""

import math

from api.constraints import Lights
from api.route_context import CROSSING_COVERED, CROSSING_NEAR_M, Crossing, _Frame, _samples, any_cell

SIGNAL_PRIORITY = 0.2
CYCLE_S = 90.0
RED_FRACTION = 0.6
WAIT_PER_SIGNAL_S = RED_FRACTION ** 2 * CYCLE_S / 2  # 16.2 s
ALL_RED_FRACTION = 0.05
ALL_RED_WAIT_S = ALL_RED_FRACTION ** 2 * CYCLE_S / 2  # ~0.1 s
LOOKAHEAD_M = 400.0
BLOCK_M = 80.0
MONOTONE_SLACK = 0.15
METERS_PER_MILE = 1609.344


def signal_penalty_model() -> dict:
    """The per-request custom-model rule for runners who wait at lights."""
    return {"priority": [{"if": "crossing == TRAFFIC_SIGNALS", "multiply_by": str(SIGNAL_PRIORITY)}]}


def signal_positions(coords, crossings: list[Crossing]) -> list[float]:
    """Meters along the route of each signalized crosswalk the route walks, in order."""
    frame = _Frame(coords[0][1])
    pts = _samples(coords, frame, step=5.0)
    along = [0.0]
    for a, b in zip(pts, pts[1:]):
        along.append(along[-1] + math.dist(a, b))
    cell = CROSSING_NEAR_M
    grid: dict[tuple[int, int], list[int]] = {}
    for k, (x, y) in enumerate(pts):
        grid.setdefault((int(x // cell), int(y // cell)), []).append(k)

    def nearest(p):
        cx, cy = int(p[0] // cell), int(p[1] // cell)
        best, best_d = None, CROSSING_NEAR_M
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for k in grid.get((gx, gy), ()):
                    d = math.dist(pts[k], p)
                    if d <= best_d:
                        best, best_d = k, d
        return best

    out = []
    for c in crossings:
        if not c.signals:
            continue
        # nearest() looks one cell around each point: a crosswalk with no route sample within two cells of its box
        # (one for that, one for rounding at cell edges) can't be walked, so skip sampling it (decision 018).
        if not any_cell(grid, [frame.xy(p) for p in c.coords], cell, pad=2):
            continue
        cpts = _samples(c.coords, frame, step=1.0)
        hits = [k for k in (nearest(p) for p in cpts) if k is not None]
        if len(hits) / len(cpts) >= CROSSING_COVERED:
            hits.sort()
            out.append(along[hits[len(hits) // 2]])
    return sorted(out)


def _staircase_ahead(pts, along, at: float, grid_deg: float) -> bool:
    """Whether a same-length grid staircase exists from `at` over the next LOOKAHEAD_M of the route."""
    i = next((k for k, d in enumerate(along) if d >= at), len(pts) - 1)
    j = next((k for k, d in enumerate(along) if d >= at + LOOKAHEAD_M), None)
    if j is None or j <= i:
        return False
    a = math.radians(grid_deg)
    dx, dy = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
    du = dx * math.sin(a) + dy * math.cos(a)  # along the grid
    dv = dx * math.cos(a) - dy * math.sin(a)  # across it
    l1 = abs(du) + abs(dv)
    walked = along[j] - along[i]
    return abs(du) >= BLOCK_M and abs(dv) >= BLOCK_M and walked <= (1 + MONOTONE_SLACK) * l1


def expected_wait(coords, crossings: list[Crossing], grid_deg: float, grid_strong: bool, lights: Lights) -> dict:
    """Expected seconds waiting at lights over the route for this kind of runner. An `estimate`."""
    lights = Lights(lights)  # callers may pass the plain string ("waits") from a preferences dict
    positions = signal_positions(coords, crossings)
    credited = 0
    if lights == Lights.ZIGZAGS and grid_strong and positions:
        frame = _Frame(coords[0][1])
        pts = _samples(coords, frame, step=5.0)
        along = [0.0]
        for p, q in zip(pts, pts[1:]):
            along.append(along[-1] + math.dist(p, q))
        credited = sum(_staircase_ahead(pts, along, s, grid_deg) for s in positions)
    seconds = (len(positions) - credited) * WAIT_PER_SIGNAL_S + credited * ALL_RED_WAIT_S
    frame = _Frame(coords[0][1])
    xy = [frame.xy(c) for c in coords]
    miles = sum(math.dist(a, b) for a, b in zip(xy, xy[1:])) / METERS_PER_MILE
    return {
        "status": "estimate", "lights": lights.value, "signals": len(positions), "credited": credited,
        "seconds": round(seconds, 1), "per_mile_s": round(seconds / miles, 1) if miles else None,
        "assumptions": (f"{CYCLE_S:g} s cycle, DON'T WALK {RED_FRACTION:.0%} of it ({WAIT_PER_SIGNAL_S:.1f} s average "
                        f"wait per signal); zig-zag credit where a same-length staircase exists over the next "
                        f"{LOOKAHEAD_M:g} m in a street grid"),
    }
