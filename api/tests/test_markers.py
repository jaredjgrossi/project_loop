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


# ---- the main turnaround, and spurs (decision 044) -----------------------------------------------------------------

def _north(points_m):
    """[lon, lat] for points given as meters north of a fixed spot, with east offsets for side trips."""
    lat0, lon0 = 40.78, -73.985
    kx = 111_320 * math.cos(math.radians(lat0))
    return [[lon0 + e / kx, lat0 + n / 110_574] for e, n in points_m]


def _path(*legs, step=10):
    """A route through (east, north) corners, a point every `step` meters."""
    out = []
    for (e0, n0), (e1, n1) in zip(legs, legs[1:]):
        d = math.hypot(e1 - e0, n1 - n0)
        k = max(int(d / step), 1)
        out += [(e0 + (e1 - e0) * i / k, n0 + (n1 - n0) * i / k) for i in range(k)]
    out.append(legs[-1])
    return _north(out)


# 4 km out and back north, with a 250 m dead-end spur east at 1 km out
SPUR_ROUTE = _path((0, 0), (0, 1000), (250, 1000), (0, 1000), (0, 4000), (0, 0))


def test_a_spur_is_not_the_turnaround():
    from api.markers import spurs, turnarounds
    (main,) = turnarounds(SPUR_ROUTE)
    assert main["along_m"] == pytest.approx(1500 + 3000, abs=40)  # the far end, after the spur's 500 m
    assert main["reach_m"] > 2000
    (spur,) = spurs(SPUR_ROUTE)
    assert spur["along_m"] == pytest.approx(1250, abs=40) and 150 <= spur["reach_m"] < 400


def test_only_the_main_turnaround_is_marked():
    from api.markers import marker_features
    turns = [f for f in marker_features(SPUR_ROUTE) if f["properties"]["feature"] == "turnaround"]
    assert len(turns) == 1 and turns[0]["properties"]["along_m"] == pytest.approx(4500, abs=40)


def test_a_plain_out_and_back_has_one_turnaround_and_no_spur():
    from api.markers import spurs, turnarounds
    route = _path((0, 0), (0, 3000), (0, 0))
    assert len(turnarounds(route)) == 1 and spurs(route) == []


def test_a_jog_at_the_start_is_not_a_spur():
    from api.markers import spurs
    route = _path((0, 0), (0, -80), (0, 3000), (0, 0))  # the start point sits mid-block: first a step the other way
    assert spurs(route) == []


def test_a_short_reversal_is_part_of_the_line():  # a ramp or a footbridge approach, under 150 m
    from api.markers import spurs, turnarounds
    route = _path((0, 0), (0, 1000), (80, 1000), (0, 1000), (0, 4000), (0, 0))
    assert spurs(route) == [] and len(turnarounds(route)) == 1


def test_point_along_interpolates_on_the_route_and_clamps_at_its_ends():  # decision 045: a spur's base
    from api.markers import point_along
    route = _path((0, 0), (0, 1000), (250, 1000))
    lon, lat = point_along(route, 1100)
    assert (lon - -73.985) * 111_320 * math.cos(math.radians(40.78)) == pytest.approx(100, abs=1)
    assert (lat - 40.78) * 110_574 == pytest.approx(1000, abs=1)
    assert point_along(route, -5) == pytest.approx(tuple(route[0]))
    assert point_along(route, 99_999) == pytest.approx(tuple(route[-1]))
