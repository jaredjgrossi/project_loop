"""Hills (step 10, decision 037): climb from the elevation every 0.1 mi, scored only for a runner who asks for flat."""

import math

import pytest

from api.constraints import DEFAULTS
from api.hills import STEP_M, hill_metrics, heights_every_step
from api.ranking import HILLS_FLAT_M_PER_MI, HILLS_WEIGHT, rank
from api.shape import shape_metrics

LAT0, LON0 = 40.74, -73.98
M_LAT = 110_574


def north(meters: float, step: float = 10.0) -> list[list[float]]:
    """A straight line north, a point every `step` meters."""
    return [[LON0, LAT0 + d / M_LAT] for d in [i * step for i in range(int(meters / step) + 1)]]


MILE = 1609.344


def test_flat_ground_has_no_climb():
    coords = north(MILE)
    h = hill_metrics(coords, [10.0] * len(coords))
    assert h.climb_m == 0 and h.steepest_pct == 0 and h.readings == 11  # every 0.1 mi, both ends


def test_a_steady_hill_counts_its_rise():
    coords = north(MILE)
    elevation = [i * 30 / (len(coords) - 1) for i in range(len(coords))]  # 30 m up over a mile
    h = hill_metrics(coords, elevation)
    assert h.climb_m == pytest.approx(30, abs=0.5) and h.climb_m_per_mi == pytest.approx(30, abs=0.5)
    assert h.steepest_pct == pytest.approx(30 / MILE * 100, abs=0.1)


def test_tile_noise_on_flat_ground_isnt_climbing():
    coords = north(MILE)
    noise = [10 + 0.4 * math.sin(i) for i in range(len(coords))]
    assert hill_metrics(coords, noise).climb_m == 0


def test_down_and_up_counts_only_the_ups():
    coords = north(2 * MILE)
    n = len(coords) - 1
    elevation = [20 - 20 * i / (n / 2) if i <= n / 2 else 20 * (i - n / 2) / (n / 2) for i in range(n + 1)]
    assert hill_metrics(coords, elevation).climb_m == pytest.approx(20, abs=0.5)


def test_no_elevation_is_not_scored_rather_than_flat():
    coords = north(MILE)
    assert hill_metrics(coords, None) is None and hill_metrics(coords, [1.0]) is None


def test_readings_every_tenth_of_a_mile():
    coords = north(MILE)
    hs = heights_every_step(coords, [i * 1.0 for i in range(len(coords))])
    assert hs[1] == pytest.approx(STEP_M / 10, abs=0.01)


def _rank(prefs, hills):
    coords = [[LON0, LAT0], [LON0 + 0.01, LAT0], [LON0 + 0.01, LAT0 + 0.01], [LON0, LAT0 + 0.01], [LON0, LAT0]]
    return rank("loop", shape_metrics(coords), prefs, None, hills)


def test_hills_count_only_when_the_runner_asks_for_flat():
    from api.hills import HillMetrics
    steep = HillMetrics(100, 25, 8, 50)
    assert all(d.key != "hills" for d in _rank(DEFAULTS, steep).dimensions)  # "don't mind": nothing changes
    flat_prefs = DEFAULTS | {"hills": "avoid"}
    flat = HillMetrics(10, HILLS_FLAT_M_PER_MI, 1, 50)
    dim = next(d for d in _rank(flat_prefs, steep).dimensions if d.key == "hills")
    assert dim.status == "estimate" and dim.fit == 0 and dim.weight == HILLS_WEIGHT
    assert "25 m of climb per mile" in dim.value
    assert _rank(flat_prefs, flat).score > _rank(flat_prefs, steep).score
    missing = next(d for d in _rank(flat_prefs, None).dimensions if d.key == "hills")
    assert missing.status == "not_scored" and missing.weight == 0
