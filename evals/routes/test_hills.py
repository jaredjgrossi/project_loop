"""Hills route evals (Phase 3, step 10; decision 037), against the live stack (make up):  uv run pytest evals/routes

Parse cases run the parser's rules on the extraction a correct model returns (no Claude call), with the real places
table and the case's answer, then the engine. Public stand-in starts; the reviewer's own runs are off.
- P33: "6 mi, flat" from Kips Bay: built with hills scored (an estimate, like climb), no can't-do line.
- R11: a training workout, flat, after "How far?" is answered: built, hills scored, the workout line kept.
- Fort Tryon Park (a hilly public start), 5 mi: asking for flat changes #1, to a route that climbs less.
"""

from functools import cache

import psycopg
import pytest

from api.constraints import RunConstraints
from api.engine import Engine, Start, start_for
from api.generate import generate_loops
from api.hills import hill_metrics
from api.parse import Context, DbPlaces, answer_overrides, build, resume
from api.tests.test_parse import CASES, CONTEXTS, IDEAL
from evals.parse.fixtures import build_request
from evals.routes.live import stack_problem
from etl.load import database_url

FORT_TRYON_PARK = (40.8610, -73.9330)


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


def build_with_candidates(rc: RunConstraints, start: Start) -> tuple[dict, dict]:
    """The final payload, and each top-3 route's hill metrics (from the candidate behind it)."""
    got = []

    def generate(*a, on_candidate=None, **kw):
        def keep(c, t):
            got.append(c)
            if on_candidate:
                on_candidate(c, t)
        return generate_loops(*a, on_candidate=keep, **kw)
    final = Engine(use_prior=False, anchor_fn=None, generate_fn=generate).build(rc, start, lambda e: None, "r_hills")
    climbs = {}
    for r in final["routes"]:
        c = next(c for c in got if c.route.coordinates == r["geometry"]["coordinates"])
        climbs[r["rank"]] = hill_metrics(c.route.coordinates, c.route.elevation)
    return final, climbs


@cache
def parsed_case(case_id: str, answer: str | None = None):
    req = build_request(CASES[case_id], CONTEXTS)
    ctx = Context.from_request(req)
    with psycopg.connect(database_url()) as conn:
        places = DbPlaces(conn)
        out = build(IDEAL[case_id], ctx, places)
        if answer is not None:
            settled = answer_overrides(out["trace"]["answer_map"], answer, None, ctx)
            out = resume(IDEAL[case_id], ctx, places, {**out["trace"]["answers"], **settled})
    assert out["parsed"]["question"] is None, out["parsed"]["question"]
    rc = RunConstraints.model_validate(out["parsed"]["constraints"])
    return rc, start_for(rc, req["client"]["location"], {}), out["parsed"]


def hills_field(final: dict) -> dict:
    return final["route"]["features"][0]["properties"]["summary"]["hills"]


def test_p33_flat_from_kips_bay_is_scored():
    rc, start, parsed = parsed_case("P33")
    assert rc.hills == "avoid" and parsed["cant"] == []
    final, climbs = build_with_candidates(rc, start)
    assert final["routes"] and final["notes"] == []
    assert hills_field(final)["status"] == "estimate" and hills_field(final)["unit"] == "m/mi"
    assert all(h is not None for h in climbs.values())


def test_r11_a_flat_workout_after_its_answer():
    rc, start, parsed = parsed_case("R11", "a")
    assert rc.hills == "avoid" and rc.distance_mi is not None
    assert [k["gap"] for k in parsed["cant"]] == ["G8"]  # workout segments: still a can't-do line
    final, _ = build_with_candidates(rc, start)
    assert final["routes"] and hills_field(final)["status"] == "estimate"


def test_flat_changes_number_one_on_a_hilly_start():
    start = Start(*FORT_TRYON_PARK, "Fort Tryon Park")
    hilly, hilly_climbs = build_with_candidates(RunConstraints(use_my_location=True, distance_mi=5.0), start)
    flat, flat_climbs = build_with_candidates(RunConstraints(use_my_location=True, distance_mi=5.0, hills="avoid"), start)
    assert hilly["routes"][0]["geometry"] != flat["routes"][0]["geometry"], "flat didn't change #1"
    assert flat_climbs[1].climb_m_per_mi < hilly_climbs[1].climb_m_per_mi
