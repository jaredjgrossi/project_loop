"""A-to-B route evals (Phase 3, step 8; decision 032), against the live stack (make up):  uv run pytest evals/routes

- Kips Bay Library (public stand-in) to McCarren Park at 8 mi: routes within the distance tolerance that start at
  the start, end at the park, and where #1 has some park or waterfront (R01 asks for park or water).
- The same end at 2 mi is shorter than the shortest way, so the engine asks, offering the shortest way rounded up.
- No distance: the shortest way.
The reviewer's own runs are off (no familiarity score, no anchors on their ways), so nothing personal goes in.
"""

import math
from functools import cache

import pytest

from api.constraints import RunConstraints
from api.engine import Engine, EngineQuestion, Start
from api.places import lookup
from evals.routes.live import load_starts, stack_problem


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


def meters(a, b):
    kx = 111_320 * math.cos(math.radians(a[0]))
    return math.hypot((b[1] - a[1]) * kx, (b[0] - a[0]) * 110_574)


@cache
def mccarren():
    m = lookup("McCarren Park")[0]
    return m.lat, m.lon


def start():
    s = load_starts()["kips-bay"]
    return Start(s["lat"], s["lon"], "Kips Bay Library (public stand-in)")


def constraints(**kw) -> RunConstraints:
    lat, lon = mccarren()
    end = {"kind": "place", "name": "McCarren Park", "borough": "Brooklyn", "lat": lat, "lon": lon}
    return RunConstraints(use_my_location=True, end_place=end, **kw)


@cache
def build(miles: float | None, scenery: str | None = None):
    sent = []
    kw = {"distance_mi": miles} if miles is not None else {}
    if scenery:
        kw["scenery"] = scenery
    final = Engine(use_prior=False, anchor_fn=None).build(constraints(**kw), start(), sent.append, "r_eval", end=mccarren())
    return final, sent


def test_kips_bay_to_mccarren_park_at_8_mi():
    final, sent = build(8.0, "park_or_water")
    assert final["routes"], "no route"
    assert final["notes"] == [], final["notes"]  # within the tolerance
    s = start()
    for r in final["routes"]:
        assert r["kind"] == "a_to_b"
        assert abs(r["distance"]["value"] - 8.0) <= 0.4, (r["label"], r["distance"]["value"])
        first, last = r["geometry"]["coordinates"][0], r["geometry"]["coordinates"][-1]
        assert meters((s.lat, s.lon), (first[1], first[0])) < 150, "doesn't start at the start"
        assert meters(mccarren(), (last[1], last[0])) < 400, "doesn't end at the park"
    summary = final["route"]["features"][0]["properties"]["summary"]
    assert summary["park_pct"]["value"] + summary["waterfront_pct"]["value"] > 0, "no park or water on #1"
    assert any(e["event"] == "top3" for e in sent) and any(e["event"] == "candidates" for e in sent)


def test_an_end_too_far_for_the_distance_asks():
    with pytest.raises(EngineQuestion) as asked:
        Engine(use_prior=False, anchor_fn=None).build(constraints(distance_mi=2.0), start(), lambda e: None, "r_eval", end=mccarren())
    q = asked.value.question
    offered = asked.value.answer_map["options"]["a"]["distance"]
    assert q["from"] == "engine" and q["about"] == "distance"
    assert 3.0 < offered < 6.0, offered  # Kips Bay to McCarren is about 4 mi on foot


def test_no_distance_means_the_shortest_way():
    final, _ = build(None)
    assert final["routes"][0]["label"] == "the shortest way"
    assert final["notes"] == []
