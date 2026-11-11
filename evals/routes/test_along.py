"""Along-avoid route evals (Phase 3, step 8b; decision 036), against the live stack (make up):  uv run pytest evals/routes

Each case runs the parser's rules on the extraction a correct model returns (no Claude call), with the real places
table, then the engine. Public stand-in contexts; the reviewer's own runs are off.
- R07: the usual 3.1 mi from Kips Bay, avoiding the chaos of 42nd St: no route runs along 42nd St (crossing is fine).
- P23: 6 mi from Kips Bay, avoiding 1st Ave by the hospitals (E 25th–E 34th St): no route runs along that stretch.
"""

from functools import cache

import psycopg
import pytest

from api.along import ALONG_MAX_M, db_alongs, longest_run_inside_m
from api.constraints import RunConstraints
from api.engine import Engine, start_for
from api.parse import Context, DbPlaces, build
from api.tests.test_parse import CASES, CONTEXTS, IDEAL
from evals.parse.fixtures import build_request
from evals.routes.live import stack_problem
from etl.load import database_url


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


@cache
def built(case_id: str):
    req = build_request(CASES[case_id], CONTEXTS)
    with psycopg.connect(database_url()) as conn:
        out = build(IDEAL[case_id], Context.from_request(req), DbPlaces(conn))
    assert out["parsed"]["question"] is None, out["parsed"]["question"]
    rc = RunConstraints.model_validate(out["parsed"]["constraints"])
    start = start_for(rc, req["client"]["location"], {})
    final = Engine(use_prior=False, anchor_fn=None).build(rc, start, lambda e: None, f"r_{case_id}")
    with psycopg.connect(database_url()) as conn:
        alongs, lost = db_alongs([a.name for a in rc.avoid_places if a.how == "along"], (start.lat, start.lon), conn)
    assert lost == []
    return rc, final, alongs


def longest_along(route: dict, along) -> float:
    return longest_run_inside_m(route["geometry"]["coordinates"], along)


def test_r07_no_route_runs_along_42nd_st():
    rc, final, (street,) = built("R07")
    assert rc.distance_mi == 3.1 and street.name == "42nd St"
    assert final["routes"] and final["notes"] == [], final["notes"]
    assert all(longest_along(r, street) < ALONG_MAX_M for r in final["routes"])


def test_p23_no_route_runs_along_1st_ave_by_the_hospitals():
    rc, final, (stretch,) = built("P23")
    assert rc.distance_mi == 6 and stretch.name.startswith("1st Ave, E 2")
    assert final["routes"] and final["notes"] == [], final["notes"]
    assert all(longest_along(r, stretch) < ALONG_MAX_M for r in final["routes"])
