"""Share-of-route and crossing counts on hand-made geometry (meters converted to lon/lat)."""

import math

import pytest

from api.route_context import (
    Crossing,
    crossing_counts,
    familiar_share,
    park_or_water_share,
    park_share,
    waterfront_share,
)

LAT0, LON0 = 40.74, -73.98
KY = 110_574
KX = 111_320 * math.cos(math.radians(LAT0))


def ll(points_m):
    return [[LON0 + x / KX, LAT0 + y / KY] for x, y in points_m]


STRAIGHT = ll([(0, 0), (1000, 0)])  # 1 km east


def test_park_share_is_the_share_of_the_route_inside_a_park():
    park = [ll([(250, -50), (750, -50), (750, 50), (250, 50), (250, -50)])]
    assert park_share(STRAIGHT, [park]) == pytest.approx(50, abs=1.5)


def test_park_share_with_no_parks_is_zero():
    assert park_share(STRAIGHT, []) == 0


def test_overlapping_parks_are_not_double_counted():
    a = [ll([(0, -50), (600, -50), (600, 50), (0, 50), (0, -50)])]
    b = [ll([(400, -50), (1000, -50), (1000, 50), (400, 50), (400, -50)])]
    assert park_share(STRAIGHT, [a, b]) == pytest.approx(100, abs=1)


def test_waterfront_share_counts_route_within_the_distance_of_the_shore():
    shore = [ll([(0, 40), (500, 40)])]  # 40 m north of the first half, then nothing
    # Within 60 m up to x = 500 + sqrt(60^2 - 40^2) = 545 m, past the shoreline's end.
    assert waterfront_share(STRAIGHT, shore, within_m=60) == pytest.approx(54.5, abs=1)
    assert waterfront_share(STRAIGHT, shore, within_m=30) == 0


def test_a_crossing_the_route_walks_along_is_counted_and_one_it_passes_is_not():
    on_route = Crossing(way_id=1, signals=True, coords=ll([(300, 0), (320, 0)]))  # route uses the crosswalk
    signal_beside = Crossing(way_id=2, signals=True, coords=ll([(500, 10), (500, 30)]))  # perpendicular, not walked
    unsignalized = Crossing(way_id=3, signals=False, coords=ll([(700, 0), (715, 0)]))
    count, signals = crossing_counts(STRAIGHT, [on_route, signal_beside, unsignalized])
    assert count == 2
    assert signals == 1


def test_a_crossing_only_touched_at_one_end_is_not_counted():
    # The route turns at the corner where a crosswalk starts but doesn't cross the street.
    corner = Crossing(way_id=4, signals=True, coords=ll([(1000, 0), (1000, 20)]))
    assert crossing_counts(STRAIGHT, [corner]) == (0, 0)


def test_park_or_water_counts_each_stretch_once():
    park = [ll([(0, -50), (600, -50), (600, 50), (0, 50), (0, -50)])]
    shore = [ll([(400, 30), (800, 30)])]  # overlaps the park from 400 to 600 m
    # Park 0-600, water from 400 - 50 (60 m radius, 30 m off) to 800 + 52: union is 0-852 m of 1000.
    assert park_or_water_share(STRAIGHT, [park], shore) == pytest.approx(85, abs=2)


def test_familiar_share_is_the_route_on_ways_already_run():
    run_before = [ll([(0, 3), (300, 3)])]
    assert familiar_share(STRAIGHT, run_before) == pytest.approx(30.8, abs=1.5)
    assert familiar_share(STRAIGHT, []) == 0
