"""Elevation along a route, with mile positions for the profile and scrubber (decision 014).

Heights come from GraphHopper's Skadi provider (public Terrain Tiles; in the US built from USGS elevation data). They
are labeled `estimate`: the tiles are a smoothed ground model at roughly 10-30 m resolution, and on a bridge they
give the ground or water below the deck, not the deck.

Gain and loss are read from the height every 0.1 mi (the profile's own step), counted once a rise or fall reaches
CLIMB_HYSTERESIS_M from the last turning point, in whole meters (decision 044). Summing every route point's height
counted tile noise as climbing: a Riverside out-and-back from W 71st St read 130.5 m on ground that spans 0-27 m;
read every 0.1 mi it is 62 m.
"""

import math

PROFILE_STEP_MI = 0.1
CLIMB_HYSTERESIS_M = 2.0  # a rise counts once the height has moved this much from the last turning point
GRADE_WINDOW_M = 100
SOURCE = "GraphHopper Skadi elevation (AWS Terrain Tiles; USGS data in the US)"
METERS_PER_MILE = 1609.344


STEP_M = PROFILE_STEP_MI * METERS_PER_MILE


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


def climb_and_descent(heights: list[float], hysteresis_m: float = CLIMB_HYSTERESIS_M) -> tuple[float, float]:
    """Total rise and fall over a list of heights, through a dead band `hysteresis_m` wide: the reading moves only
    when the height leaves the band, and then by what it left by, so wobbles smaller than the band aren't climbing
    and a real rise keeps all but a meter or two. It settles on the last height at the end, when that's a real
    change."""
    if not heights:
        return 0.0, 0.0
    band = hysteresis_m / 2
    gain = loss = 0.0
    level = heights[0]
    for h in [*heights[1:], None]:
        if h is None:  # settle at the finish, unless that's within the band (noise)
            if abs(heights[-1] - level) < band:
                break
            new = heights[-1]
        elif h > level + band:
            new = h - band
        elif h < level - band:
            new = h + band
        else:
            continue
        gain += max(new - level, 0.0)
        loss += max(level - new, 0.0)
        level = new
    return gain, loss


def elevation_profile(coords: list[list[float]], elevation: list[float] | None) -> dict:
    if not elevation or len(elevation) != len(coords):
        return {"status": "not_scored", "source": SOURCE, "profile": [], "gain_m": None, "loss_m": None,
                "min_m": None, "max_m": None, "max_grade_pct": None}
    kx = 111_320 * math.cos(math.radians(coords[0][1]))
    along = [0.0]
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        along.append(along[-1] + math.hypot((x1 - x0) * kx, (y1 - y0) * 110_574))

    gain, loss = climb_and_descent(heights_every_step(coords, elevation))

    def height_at(d: float) -> float:
        for i in range(1, len(along)):
            if along[i] >= d:
                span = along[i] - along[i - 1] or 1.0
                return elevation[i - 1] + (elevation[i] - elevation[i - 1]) * (d - along[i - 1]) / span
        return elevation[-1]

    total = along[-1]
    profile, mile = [], 0.0
    while mile * METERS_PER_MILE <= total + 1e-6:
        profile.append({"mile": round(mile, 1), "elevation_m": round(height_at(mile * METERS_PER_MILE), 1)})
        mile += PROFILE_STEP_MI
    max_grade = 0.0
    d = 0.0
    while d + GRADE_WINDOW_M <= total:
        max_grade = max(max_grade, abs(height_at(d + GRADE_WINDOW_M) - height_at(d)) / GRADE_WINDOW_M * 100)
        d += GRADE_WINDOW_M / 4
    return {
        "status": "estimate", "source": SOURCE, "profile": profile,
        "gain_m": round(gain), "loss_m": round(loss),
        "min_m": round(min(elevation), 1), "max_m": round(max(elevation), 1), "max_grade_pct": round(max_grade, 1),
    }
