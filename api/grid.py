"""Estimate the local street-grid angle from street segment bearings.

Manhattan's avenues run about 29 degrees east of north; the grid in other
neighborhoods differs, and some have no grid at all. A grid repeats every 90
degrees, so bearings are multiplied by 4 and averaged as vectors (a circular
mean): perpendicular streets reinforce each other and opposite directions of the
same street agree. The length of that average vector is the grid's strength, from
0 (streets point every which way) to 1 (a perfect grid).
"""

import math
from dataclasses import dataclass

# A start with a weaker grid than this should not get rectangle candidates.
MIN_GRID_STRENGTH = 0.45


@dataclass(frozen=True)
class GridEstimate:
    angle_deg: float  # bearing of one grid axis, in [0, 90)
    strength: float  # 0 to 1


def estimate_grid_angle(segments: list[tuple[float, float]]) -> GridEstimate:
    """segments: (bearing in degrees clockwise from north, length in meters)."""
    total = sum(length for _, length in segments)
    if total <= 0:
        return GridEstimate(angle_deg=0.0, strength=0.0)
    x = sum(length * math.cos(math.radians(4 * bearing)) for bearing, length in segments)
    y = sum(length * math.sin(math.radians(4 * bearing)) for bearing, length in segments)
    angle = (math.degrees(math.atan2(y, x)) / 4) % 90
    if angle >= 90:  # a tiny negative angle rounds up to exactly 90 under float modulo
        angle = 0.0
    return GridEstimate(angle_deg=angle, strength=math.hypot(x, y) / total)


def segments_from_linestring(coords: list[list[float]]) -> list[tuple[float, float]]:
    """Split a [lon, lat] polyline into (bearing, meters) segments, skipping repeated points."""
    out = []
    for (lon0, lat0), (lon1, lat1) in zip((c[:2] for c in coords), (c[:2] for c in coords[1:])):
        lat_mid = math.radians((lat0 + lat1) / 2)
        dx = (lon1 - lon0) * 111_320 * math.cos(lat_mid)
        dy = (lat1 - lat0) * 110_574
        length = math.hypot(dx, dy)
        if length > 0:
            out.append((math.degrees(math.atan2(dx, dy)) % 360, length))
    return out
