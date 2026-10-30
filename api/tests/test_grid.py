import math
import random

import pytest

from api.grid import GridEstimate, estimate_grid_angle, segments_from_linestring


def angular_gap(a, b):
    """Distance between two grid angles, which repeat every 90 degrees."""
    d = abs(a - b) % 90
    return min(d, 90 - d)


def grid_segments(angle, n=200, length=80.0):
    """A perfect street grid: segments at angle, angle+90, +180, +270."""
    return [((angle + 90 * (i % 4)) % 360, length) for i in range(n)]


def test_manhattan_style_grid():
    est = estimate_grid_angle(grid_segments(29))
    assert angular_gap(est.angle_deg, 29) < 0.5
    assert est.strength == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("angle", [0, 10, 45, 73, 89])
def test_recovers_any_rotation(angle):
    est = estimate_grid_angle(grid_segments(angle))
    assert angular_gap(est.angle_deg, angle) < 0.5
    assert 0 <= est.angle_deg < 90


def test_grid_straddling_the_wrap_point_is_still_one_grid():
    segs = [(1.0, 100), (89.0, 100), (181.0, 100), (269.0, 100)] * 20
    est = estimate_grid_angle(segs)
    assert angular_gap(est.angle_deg, 0) < 1.5
    assert est.strength > 0.99


def test_noisy_grid_still_finds_the_angle():
    rng = random.Random(1)
    segs = [((29 + 90 * rng.randrange(4) + rng.gauss(0, 4)) % 360, rng.uniform(40, 200)) for _ in range(500)]
    est = estimate_grid_angle(segs)
    assert angular_gap(est.angle_deg, 29) < 2
    assert est.strength > 0.8


def test_directionless_streets_have_no_grid():
    rng = random.Random(2)
    segs = [(rng.uniform(0, 360), rng.uniform(40, 200)) for _ in range(2000)]
    assert estimate_grid_angle(segs).strength < 0.15


def test_long_segments_outweigh_short_ones():
    # A few long avenues at 29 degrees against many short wiggles pointing elsewhere.
    segs = [(29, 1000)] * 5 + [(70, 10)] * 100
    assert angular_gap(estimate_grid_angle(segs).angle_deg, 29) < 5


def test_no_segments_means_no_grid():
    assert estimate_grid_angle([]) == GridEstimate(angle_deg=0.0, strength=0.0)


def test_segments_from_linestring_gives_bearing_and_meters():
    # 0.001 degrees of latitude is about 110.6 m, due north.
    segs = segments_from_linestring([[-73.98, 40.74], [-73.98, 40.741]])
    assert len(segs) == 1
    bearing, length = segs[0]
    assert bearing == pytest.approx(0, abs=0.01) or bearing == pytest.approx(360, abs=0.01)
    assert length == pytest.approx(110.57, rel=0.01)


def test_segments_from_linestring_east_and_skips_repeated_points():
    segs = segments_from_linestring([[-73.98, 40.74], [-73.98, 40.74], [-73.979, 40.74]])
    assert len(segs) == 1
    assert segs[0][0] == pytest.approx(90, abs=0.01)
    assert segs[0][1] == pytest.approx(111_320 * math.cos(math.radians(40.74)) * 0.001, rel=0.01)
