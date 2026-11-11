"""Past-route and planned-run route evals (Phase 3, step 11; decision 038), against the live stack (make up).

    uv run pytest evals/routes

Each case runs the parser's rules on the extraction a correct model returns (no Claude call), with the real places
table and the case's answer, then the engine. The past routes are evals/past_routes.py's fixture lines (public
waypoints near the Kips Bay Library stand-in), seeded into saved_routes first.
- H01 "same as Tuesday": rt_a rebuilt for now, the same line at the same distance.
- H02 "my usual but longer", after "+1 mi": rt_a, 1 mi longer, still along it.
- H03 "the river one, other direction": rt_a run the other way.
- H04 "last week's route but skip the ferry part", after picking rt_a: along rt_a, never within the pier's circle.
- H05 "my usual": rt_a, the most-run route.
- P45 "5k tonight and a 10 miler sat": the first run now; the second built for Saturday from home.
"""

from functools import cache

import psycopg
import pytest

from api.constraints import RunConstraints
from api.engine import PIER_RADIUS_M, Engine, start_for
from api.geometry import covered_share
from api.parse import Context, DbPlaces, answer_overrides, build, resume
from api.tests.test_parse import CASES, CONTEXTS, IDEAL
from evals.parse.fixtures import build_request
from evals.past_routes import seed
from evals.routes.live import stack_problem
from etl.load import database_url

E34_LANDING = (40.743912, -73.970731)  # NYC Ferry's East 34th Street landing (pulse_sources)


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)
    seed()


def _answer_for(out: dict, wanted: str | None) -> str | None:
    """The option id that picks `wanted` (a route id), or the first option."""
    if wanted is None:
        return "a"
    opts = out["trace"]["answer_map"]["options"]
    return next(k for k, v in opts.items() if v.get("reuse") == wanted)


@cache
def parsed(case_id: str, pick: str | None = None, answered: bool = False):
    req = build_request(CASES[case_id], CONTEXTS)
    ctx = Context.from_request(req)
    with psycopg.connect(database_url()) as conn:
        places = DbPlaces(conn)
        out = build(IDEAL[case_id], ctx, places)
        if answered:
            settled = answer_overrides(out["trace"]["answer_map"], _answer_for(out, pick), None, ctx)
            out = resume(IDEAL[case_id], ctx, places, {**out["trace"]["answers"], **settled})
    assert out["parsed"]["question"] is None, out["parsed"]["question"]
    return RunConstraints.model_validate(out["parsed"]["constraints"]), req, out["parsed"]


@cache
def built(case_id: str, pick: str | None = None, answered: bool = False):
    rc, req, p = parsed(case_id, pick, answered)
    saved = {s["id"]: s for s in req["profile"]["saved_places"]}
    start = start_for(rc, req["client"]["location"], saved)
    final = Engine(use_prior=False, anchor_fn=None).build(rc, start, lambda e: None, f"r_{case_id}")
    return rc, final, p


def rt_a_line() -> dict:
    with psycopg.connect(database_url()) as conn:
        return {"type": "LineString", "coordinates": [list(c) for c in DbPlaces(conn).past_route("rt_a").coords]}


def runs_along_rt_a(route: dict, share: float = 0.9) -> bool:
    return covered_share(route["geometry"]["coordinates"], rt_a_line(), 30) >= share


def test_h01_same_as_tuesday_is_rt_a_rebuilt_for_now():
    rc, final, _ = built("H01")
    assert rc.reuse_route_id == "rt_a"
    assert final["routes"] and final["notes"] == [], final["notes"]
    assert all(runs_along_rt_a(r) for r in final["routes"])
    assert abs(final["routes"][0]["distance"]["value"] - 3.0) <= 0.15


def test_h02_my_usual_but_one_mile_longer():
    rc, final, _ = built("H02", answered=True)
    assert rc.reuse_route_id == "rt_a" and rc.distance_mi == 4.0
    assert final["routes"] and final["notes"] == [], final["notes"]
    assert all(runs_along_rt_a(r) for r in final["routes"])
    assert all(abs(r["distance"]["value"] - 4.0) <= 0.2 for r in final["routes"])


def test_h03_the_river_one_the_other_direction():
    rc, final, _ = built("H03")
    assert rc.reuse_route_id == "rt_a" and rc.reverse
    assert final["routes"] and all(runs_along_rt_a(r) for r in final["routes"])


def test_h04_skips_the_ferry_part_of_last_weeks_route():
    rc, final, p = built("H04", pick="rt_a", answered=True)
    assert [a.name for a in rc.avoid_places] == ["E 34th St ferry landing"]
    assert p["cant"] == []
    assert final["routes"], final["notes"]
    import math
    kx = 111_320 * math.cos(math.radians(E34_LANDING[0]))
    for r in final["routes"]:
        nearest = min(math.hypot((lon - E34_LANDING[1]) * kx, (lat - E34_LANDING[0]) * 110_574)
                      for lon, lat in r["geometry"]["coordinates"])
        assert nearest > PIER_RADIUS_M - 5, nearest  # never through the pier's circle
        assert runs_along_rt_a(r, share=0.6)  # still the esplanade route, less the part by the landing


def test_h05_my_usual_is_the_most_run_route():
    rc, final, _ = built("H05")
    assert rc.reuse_route_id == "rt_a"
    assert final["routes"] and all(runs_along_rt_a(r) for r in final["routes"])


def test_p45_tonight_now_and_saturday_from_home():
    rc, final, _ = built("P45")
    assert final["routes"] and abs(final["routes"][0]["distance"]["value"] - 3.11) <= 0.16
    req = build_request(CASES["P45"], CONTEXTS)
    saved = {s["id"]: s for s in req["profile"]["saved_places"]}
    p = rc.planned
    assert p.start_date.isoformat() == "2026-11-07" and p.start_time == "07:00"
    start = start_for(p, req["client"]["location"], saved)
    second = Engine(use_prior=False, anchor_fn=None).build(p, start, lambda e: None, "r_P45_sat")
    assert second["routes"] and abs(second["routes"][0]["distance"]["value"] - 10) <= 0.5
    first_point = second["routes"][0]["geometry"]["coordinates"][0]
    assert abs(first_point[1] - saved["home"]["lat"]) < 0.002 and abs(first_point[0] - saved["home"]["lon"]) < 0.002
