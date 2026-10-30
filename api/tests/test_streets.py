import pytest

from api.grid import estimate_grid_angle
from api.streets import segments_near

LAT, LON = 40.74, -73.98
M_LAT = 110_574


def north_line(dlon, dlat0, dlat1):
    """A due-north street starting dlon degrees east of the point."""
    return [[LON + dlon, LAT + dlat0], [LON + dlon, LAT + dlat1]]


def test_keeps_only_segments_within_the_radius():
    near = north_line(0.0, 0.0, 0.002)  # starts at the point, ~220 m long
    far = north_line(0.0, 0.05, 0.052)  # ~5.5 km north
    segs = segments_near([near, far], LAT, LON, radius_m=1000)
    assert len(segs) == 1
    assert segs[0][1] == pytest.approx(0.002 * M_LAT, rel=0.01)


def test_segment_is_judged_by_its_midpoint_not_its_whole_way():
    # A long way that passes through the circle contributes only its segments inside it.
    way = [[LON, LAT + k * 0.002] for k in range(0, 20)]  # ~4.2 km of 220 m segments heading north
    segs = segments_near([way], LAT, LON, radius_m=500)
    assert 2 <= len(segs) <= 5


def test_grid_is_recovered_from_nearby_ways():
    # Two perpendicular streets, a few blocks of each, in a grid rotated 29 degrees.
    import math

    def street(bearing, offset_m):
        b = math.radians(bearing)
        ox, oy = math.sin(b + math.pi / 2) * offset_m, math.cos(b + math.pi / 2) * offset_m
        pts = []
        for i in range(-5, 6):
            x, y = ox + math.sin(b) * i * 80, oy + math.cos(b) * i * 80
            pts.append([LON + x / (111_320 * math.cos(math.radians(LAT))), LAT + y / M_LAT])
        return pts

    ways = [street(29, k * 270) for k in range(-2, 3)] + [street(119, k * 80) for k in range(-3, 4)]
    est = estimate_grid_angle(segments_near(ways, LAT, LON, radius_m=1000))
    assert abs(est.angle_deg - 29) < 1
    assert est.strength > 0.95
