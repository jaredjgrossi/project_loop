"""Elevation along a route, with mile positions for the profile and scrubber (decision 014).

Heights come from GraphHopper's Skadi provider (public Terrain Tiles; in the US built from USGS elevation data). They
are labeled `estimate`: the tiles are a smoothed ground model at roughly 10-30 m resolution, and on a bridge they
give the ground or water below the deck, not the deck. Gain and loss use a hysteresis threshold so tile noise isn't
counted as climbing.
"""

import math

PROFILE_STEP_MI = 0.1
HYSTERESIS_M = 1.5  # climbing counts once the height has moved this much from the last turning point
GRADE_WINDOW_M = 100
SOURCE = "GraphHopper Skadi elevation (AWS Terrain Tiles; USGS data in the US)"
METERS_PER_MILE = 1609.344


def elevation_profile(coords: list[list[float]], elevation: list[float] | None) -> dict:
    if not elevation or len(elevation) != len(coords):
        return {"status": "not_scored", "source": SOURCE, "profile": [], "gain_m": None, "loss_m": None,
                "min_m": None, "max_m": None, "max_grade_pct": None}
    kx = 111_320 * math.cos(math.radians(coords[0][1]))
    along = [0.0]
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        along.append(along[-1] + math.hypot((x1 - x0) * kx, (y1 - y0) * 110_574))

    gain = loss = 0.0
    ref = elevation[0]
    for e in elevation[1:]:
        if e - ref >= HYSTERESIS_M:
            gain += e - ref
            ref = e
        elif ref - e >= HYSTERESIS_M:
            loss += ref - e
            ref = e

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
        "gain_m": round(gain, 1), "loss_m": round(loss, 1),
        "min_m": round(min(elevation), 1), "max_m": round(max(elevation), 1), "max_grade_pct": round(max_grade, 1),
    }
