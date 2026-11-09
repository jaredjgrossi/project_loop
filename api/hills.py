"""Hills (Phase 3, step 10; decision 037): how much a route climbs, from its elevation every 0.1 mi.

GraphHopper returns a height for every route point (decision 014). The height is read every 0.1 mi along the route,
and the climb is the sum of the rises between those readings, counted once a rise reaches STEP_HYSTERESIS_M from
the last turning point, so tile noise on flat ground isn't counted. The steepest 0.1 mi is the largest rise or fall
between two readings.

Only a runner who asks for flat ("flat", "no hills") gets the `hills` dimension in the ranking. "Don't mind" adds
nothing, so every other ranking stays as it was.
"""

import math
from dataclasses import dataclass

from api.elevation import METERS_PER_MILE, PROFILE_STEP_MI

STEP_M = PROFILE_STEP_MI * METERS_PER_MILE
STEP_HYSTERESIS_M = 1.0


@dataclass(frozen=True)
class HillMetrics:
    climb_m: float
    climb_m_per_mi: float
    steepest_pct: float  # the steepest 0.1 mi, up or down
    readings: int


def heights_every_step(coords: list[list[float]], elevation: list[float], step_m: float = STEP_M) -> list[float]:
    """The route's height every `step_m` along it, from the start, plus the height at the end."""
    kx = 111_320 * math.cos(math.radians(coords[0][1]))
    along = [0.0]
    for (x0, y0, *_), (x1, y1, *_) in zip(coords, coords[1:]):
        along.append(along[-1] + math.hypot((x1 - x0) * kx, (y1 - y0) * 110_574))
    out, i, d = [], 1, 0.0
    while d <= along[-1]:
        while i < len(along) - 1 and along[i] < d:
            i += 1
        span = along[i] - along[i - 1] or 1.0
        t = min(max((d - along[i - 1]) / span, 0.0), 1.0)
        out.append(elevation[i - 1] + (elevation[i] - elevation[i - 1]) * t)
        d += step_m
    if along[-1] - (d - step_m) > 1.0:
        out.append(elevation[-1])
    return out


def hill_metrics(coords: list[list[float]], elevation: list[float] | None) -> HillMetrics | None:
    """None when the route has no elevation (the dimension is then not scored, never zero)."""
    if not elevation or len(elevation) != len(coords) or len(coords) < 2:
        return None
    hs = heights_every_step(coords, elevation)
    climb, ref = 0.0, hs[0]
    for h in hs[1:]:
        if h - ref >= STEP_HYSTERESIS_M:
            climb += h - ref
            ref = h
        elif ref - h >= STEP_HYSTERESIS_M:
            ref = h
    steepest = max((abs(b - a) / STEP_M * 100 for a, b in zip(hs, hs[1:])), default=0.0)
    kx = 111_320 * math.cos(math.radians(coords[0][1]))
    length = sum(math.hypot((x1 - x0) * kx, (y1 - y0) * 110_574)
                 for (x0, y0, *_), (x1, y1, *_) in zip(coords, coords[1:]))
    miles = max(length / METERS_PER_MILE, 0.1)
    return HillMetrics(round(climb, 1), round(climb / miles, 1), round(steepest, 1), len(hs))
