"""Hills (Phase 3, step 10; decision 037): how much a route climbs, from its elevation every 0.1 mi.

GraphHopper returns a height for every route point (decision 014). The height is read every 0.1 mi along the route,
and the climb is the sum of the rises between those readings, counted once a rise reaches CLIMB_HYSTERESIS_M (2 m)
from the last turning point, so tile noise on flat ground isn't counted: the same reading as the route's climb
(api/elevation.py; decision 044 raised it from 1 m). The steepest 0.1 mi is the largest rise or fall
between two readings.

Only a runner who asks for flat ("flat", "no hills") gets the `hills` dimension in the ranking. "Don't mind" adds
nothing, so every other ranking stays as it was.
"""

import math
from dataclasses import dataclass

from api.elevation import METERS_PER_MILE, STEP_M, climb_and_descent, heights_every_step


@dataclass(frozen=True)
class HillMetrics:
    climb_m: float
    climb_m_per_mi: float
    steepest_pct: float  # the steepest 0.1 mi, up or down
    readings: int


def hill_metrics(coords: list[list[float]], elevation: list[float] | None) -> HillMetrics | None:
    """None when the route has no elevation (the dimension is then not scored, never zero)."""
    if not elevation or len(elevation) != len(coords) or len(coords) < 2:
        return None
    hs = heights_every_step(coords, elevation)
    climb, _ = climb_and_descent(hs)  # the same reading as the route's climb (decision 044)
    steepest = max((abs(b - a) / STEP_M * 100 for a, b in zip(hs, hs[1:])), default=0.0)
    kx = 111_320 * math.cos(math.radians(coords[0][1]))
    length = sum(math.hypot((x1 - x0) * kx, (y1 - y0) * 110_574)
                 for (x0, y0, *_), (x1, y1, *_) in zip(coords, coords[1:]))
    miles = max(length / METERS_PER_MILE, 0.1)
    return HillMetrics(round(climb, 1), round(climb / miles, 1), round(steepest, 1), len(hs))
