"""Via-place route evals (Phase 3, step 9; decision 034), against the live stack (make up):  uv run pytest evals/routes

Each case runs the parser's rules on the extraction a correct model returns (no Claude call), with the real places
table and the case's answer, then the engine. Public stand-in contexts; the reviewer's own runs are off.
- R02: after "West side", 86th St at Central Park West, a full lap of the Reservoir track, to Central Park South
  (the Reservoir named on its own is its running loop, decision 035).
- R03: 3 mi on the West Side Highway from Kips Bay is too short: the engine asks, offering the shortest way through.
- R09: a long run in the park from Grand Army Plaza, after "6 mi": routes in Prospect Park.
- P49: 15 mi on the East River Greenway: routes along it, at the distance.
- P50: a loop of Prospect Park from Grand Army Plaza: a full lap of the drive, and the lap sets the distance.
"""

from functools import cache

import psycopg
import pytest

from api.constraints import RunConstraints
from api.engine import Engine, EngineQuestion, Start, end_for, start_for
from api.geometry import covered_share, line_length_m, passes_through
from api.parse import Context, DbPlaces, answer_overrides, build, resume
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
def parsed(case_id: str, answer: str | None = None):
    """The parse event's constraints and the request, after the case's answer when it asks."""
    req = build_request(CASES[case_id], CONTEXTS)
    ctx = Context.from_request(req)
    with psycopg.connect(database_url()) as conn:
        places = DbPlaces(conn)
        out = build(IDEAL[case_id], ctx, places)
        if answer is not None:
            settled = answer_overrides(out["trace"]["answer_map"], answer, None, ctx)
            out = resume(IDEAL[case_id], ctx, places, {**out["trace"]["answers"], **settled})
    assert out["parsed"]["question"] is None, out["parsed"]["question"]
    return RunConstraints.model_validate(out["parsed"]["constraints"]), req


@cache
def built(case_id: str, answer: str | None = None):
    rc, req = parsed(case_id, answer)
    saved = {p["id"]: p for p in req["profile"]["saved_places"]}
    start = start_for(rc, req["client"]["location"], saved)
    sent = []
    final = Engine(use_prior=False, anchor_fn=None).build(rc, start, sent.append, f"r_{case_id}",
                                                          end=end_for(rc, saved))
    return rc, final, sent


def passes_every_via(route: dict, rc: RunConstraints) -> bool:
    """Through each via, or a full lap of each around via's ring."""
    from api.engine import db_vias
    from api.via import LAP_SHARE, through_rules
    coords = route["geometry"]["coordinates"]
    return all(passes_through(coords, shape, tol) if share is None else covered_share(coords, shape, tol) >= LAP_SHARE
               for shape, tol, share in through_rules(db_vias(rc.via_places)))


def lap_m(rc: RunConstraints) -> float:
    from api.engine import db_vias
    return sum(line_length_m([list(c) for c in v.lap]) for v in db_vias(rc.via_places) if v.lap)


def test_r02_a_reservoir_lap_to_central_park_south_after_west_side():
    rc, final, _ = built("R02", "b")
    via = rc.via_places[0]
    assert via.name == "Central Park Reservoir" and rc.end_place.name == "Central Park South"
    assert (via.mode, via.loop) == ("around", "reservoir")
    assert final["routes"], "no route"
    assert all(r["kind"] == "a_to_b" for r in final["routes"])
    assert all(passes_every_via(r, rc) for r in final["routes"])  # 90% of the track, within 30 m
    lap = lap_m(rc)
    assert 2400 < lap < 2600  # the 1.58 mi track
    assert all(r["distance"]["value"] * 1609.344 > lap + 1000 for r in final["routes"])  # the lap, and to and from it
    assert final["notes"] == []  # no distance said: the lap and the shortest way there and on


def test_r03_the_greenway_is_too_far_for_3_mi_so_the_engine_asks():
    rc, req = parsed("R03")
    start = start_for(rc, req["client"]["location"], {})
    with pytest.raises(EngineQuestion) as asked:
        Engine(use_prior=False, anchor_fn=None).build(rc, start, lambda e: None, "r_R03")
    q = asked.value.question
    offered = asked.value.answer_map["options"]["a"]["distance"]
    assert q["from"] == "engine" and "Hudson River Greenway" in q["text"]
    assert 3.2 < offered < 6.0, offered


def test_r09_a_long_run_in_prospect_park_after_6_mi():
    rc, final, sent = built("R09", "a")
    assert rc.distance_mi == 6 and rc.via_places[0].name == "Prospect Park"
    assert final["routes"] and final["notes"] == [], final["notes"]
    assert all(passes_every_via(r, rc) for r in final["routes"])
    summary = final["route"]["features"][0]["properties"]["summary"]
    assert summary["park_pct"]["value"] >= 30, summary["park_pct"]  # "a few miles in the park"


def test_p49_fifteen_miles_on_the_east_river_greenway():
    rc, final, _ = built("P49")
    assert rc.distance_mi == 15 and rc.via_places[0].name == "East River Greenway"
    assert final["routes"] and final["notes"] == [], final["notes"]
    assert all(passes_every_via(r, rc) for r in final["routes"])


def test_p50_a_loop_of_prospect_park_from_grand_army_plaza():
    rc, final, _ = built("P50")
    via = rc.via_places[0]
    assert (via.name, via.mode, via.loop) == ("Prospect Park", "around", "prospect_park_drive")
    assert rc.distance_mi is None and rc.start_place.name == "Grand Army Plaza"
    assert final["routes"] and final["notes"] == [], final["notes"]
    assert all(passes_every_via(r, rc) for r in final["routes"])
    lap_mi = lap_m(rc) / 1609.344
    assert 3.3 < lap_mi < 3.7
    best = final["routes"][0]["distance"]["value"]
    assert lap_mi <= best < lap_mi + 1.0, best  # the lap plus a short way in from the plaza
