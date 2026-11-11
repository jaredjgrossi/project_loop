import math

import pytest

from api.elevation import elevation_profile

LAT0, LON0 = 40.74, -73.98
KX = 111_320 * math.cos(math.radians(LAT0))
KY = 110_574


def line(points_m):
    return [[LON0 + x / KX, LAT0 + y / KY] for x, y in points_m]


def test_flat_route_has_no_gain_and_a_mile_by_mile_profile():
    coords = line([(x, 0) for x in range(0, 3300, 100)])  # ~2 mi
    p = elevation_profile(coords, [10.0] * len(coords))
    assert p["gain_m"] == 0 and p["loss_m"] == 0
    assert p["status"] == "estimate" and p["source"]
    assert p["profile"][0] == {"mile": 0.0, "elevation_m": 10.0}
    assert [pt["mile"] for pt in p["profile"]][:3] == [0.0, 0.1, 0.2]


def test_a_hill_counts_gain_and_loss_and_the_grade():
    coords = line([(x, 0) for x in range(0, 1001, 50)])
    ele = [x / 1000 * 40 if x <= 500 else (1000 - x) / 1000 * 40 for x in range(0, 1001, 50)]  # up 20 m, down 20 m
    p = elevation_profile(coords, ele)
    assert p["gain_m"] == pytest.approx(20, abs=2)  # read every 0.1 mi through a 2 m band (decision 044)
    assert p["loss_m"] == pytest.approx(20, abs=2)
    assert isinstance(p["gain_m"], int)  # whole meters
    assert p["max_grade_pct"] == pytest.approx(4, abs=0.5)
    assert p["max_m"] == pytest.approx(20, abs=0.5)


def test_noise_under_the_threshold_is_not_counted_as_climbing():
    coords = line([(x, 0) for x in range(0, 2001, 20)])
    ele = [10 + (0.4 if i % 2 else -0.4) for i in range(len(coords))]  # +/- 0.4 m jitter
    assert elevation_profile(coords, ele)["gain_m"] < 2


def test_no_elevation_means_not_scored():
    p = elevation_profile(line([(0, 0), (1000, 0)]), None)
    assert p["status"] == "not_scored" and p["profile"] == []


def test_noise_on_every_point_is_not_summed_as_climbing():  # decision 044: 130.5 m read for a ~53 m route
    import random
    rng = random.Random(7)
    coords = line([(x, 0) for x in range(0, 8000, 20)])  # 5 mi, a point every 20 m
    flat_with_noise = [10 + rng.uniform(-1.5, 1.5) for _ in coords]
    assert elevation_profile(coords, flat_with_noise)["gain_m"] <= 2
    rolling = [10 + 8 * math.sin(i / 60) + rng.uniform(-1.5, 1.5) for i in range(len(coords))]  # real hills plus noise
    p = elevation_profile(coords, rolling)
    true_gain = sum(max(b - a, 0) for a, b in zip([10 + 8 * math.sin(i / 60) for i in range(len(coords))][::8],
                                                   [10 + 8 * math.sin(i / 60) for i in range(len(coords))][8::8]))
    assert abs(p["gain_m"] - true_gain) <= 0.15 * true_gain + 3
