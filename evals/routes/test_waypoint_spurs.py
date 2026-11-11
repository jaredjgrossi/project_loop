"""Kips Bay, 6 mi, lights: waits, against the live stack (make up). Decision 045.

The generator's waterfront entry, the shore point nearest the start, sits on the East River Esplanade 75 m south of
E 34th St, where the streets reach it. The route went there and back: a 150 m spur, which decision 044 rejected, and
the #1 became a street-grid rectangle at 8.7 lights a mile with 23% waterfront. With the waypoint moved to the
spur's base, the waterfront route is back.
"""

import pytest

from api.markers import reversals, spurs
from evals.routes.live import stack_problem, top_loops

E34_ENTRY = (40.7425, -73.9723)  # (lat, lon): the U-turn on the Esplanade, 75 m south of E 34th St


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


@pytest.fixture(scope="module")
def first():
    return top_loops("kips-bay", 6, 3, prefs=(("lights", "waits"),))[0]


def test_the_first_route_is_on_the_waterfront_again(first):
    v = first.metric_vector()
    assert first.kind == "out_and_back"
    assert v["waterfront_pct"] >= 45 and v["signals_per_mile"] <= 4, v
    assert first.within_tolerance


def test_no_spur_and_no_u_turn_at_the_entry(first):
    coords = first.route.coordinates
    assert spurs(coords) == []
    kx = 111_320 * 0.7568  # cos(40.74 degrees)
    near = [r for r in reversals(coords)
            if ((r["lat"] - E34_ENTRY[0]) * 110_574) ** 2 + ((r["lon"] - E34_ENTRY[1]) * kx) ** 2 <= 40 ** 2]
    assert near == []
