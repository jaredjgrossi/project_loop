import math

import pytest

from api.markers import METERS_PER_MILE, marker_features, mile_points, turnarounds

LAT0, LON0 = 40.74, -73.98
KX = 111_320 * math.cos(math.radians(LAT0))
KY = 110_574


def line(points_m):
    return [[LON0 + x / KX, LAT0 + y / KY] for x, y in points_m]


def out_and_back(meters_out):
    return line([(x, 0) for x in range(0, meters_out + 1, 50)] + [(x, 0) for x in range(meters_out - 50, -1, -50)])


def test_mile_points_carry_their_distance_along_the_route():
    pts = mile_points(line([(x, 0) for x in range(0, 5001, 50)]))
    assert [p["mile"] for p in pts] == [1, 2, 3]
    assert [p["along_m"] for p in pts] == pytest.approx([METERS_PER_MILE * m for m in (1, 2, 3)])
    assert (pts[1]["lon"] - LON0) * KX == pytest.approx(2 * METERS_PER_MILE, abs=5)


def test_the_turnaround_is_halfway_along_an_out_and_back():
    (turn,) = turnarounds(out_and_back(2500))
    assert turn["along_m"] == pytest.approx(2500, abs=30)
    assert (turn["lon"] - LON0) * KX == pytest.approx(2500, abs=30)


def test_a_rectangle_has_no_turnaround():
    assert turnarounds(line([(0, 0), (1000, 0), (1000, 500), (0, 500), (0, 0)])) == []


def test_marker_features_are_points_with_distance_and_a_trust_label():
    feats = marker_features(out_and_back(2500))  # 5 km: miles 1-3 and one turnaround
    kinds = [f["properties"]["feature"] for f in feats]
    assert kinds == ["mile", "mile", "mile", "turnaround"]
    for f in feats:
        assert f["geometry"]["type"] == "Point"
        assert f["properties"]["status"] == "measured" and f["properties"]["source"]
    turn = feats[-1]["properties"]
    assert turn["along_mi"] == pytest.approx(2500 / METERS_PER_MILE, abs=0.02)
    assert feats[0]["properties"]["along_mi"] == 1.0
