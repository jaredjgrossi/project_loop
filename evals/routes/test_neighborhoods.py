"""An end in a neighborhood (phone test round 2, 2026-11-10; decision 042), against the live stack (make up).

"3 miles to Williamsburg" from the Kips Bay Library stand-in: the parse asks nothing (Williamsburg is one place).
The way there goes over the bridge, longer than 3 mi, so the engine asks (rule 3), offering the way into
Williamsburg's area (its 2020 NTA), shorter than the way to its middle. At that distance the route finishes a few
hundred meters inside the area.
"""

import psycopg
import pytest

from api.constraints import RunConstraints
from api.engine import AREA_DEPTH_M, Engine, EngineQuestion, end_for, start_for
from api.parse import Context, DbPlaces, build
from api.tests.test_parse import CASES, CONTEXTS, ext, mi, place
from evals.parse.fixtures import build_request
from evals.routes.live import stack_problem
from etl.load import database_url


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


def parsed_williamsburg(miles: float):
    req = {**build_request(CASES["P01"], CONTEXTS), "text": f"{miles:g} miles to Williamsburg"}
    extraction = ext(distance=mi(miles), end=place("neighborhood", "Williamsburg"))
    with psycopg.connect(database_url()) as conn:
        out = build(extraction, Context.from_request(req), DbPlaces(conn))
    assert out["parsed"]["question"] is None, out["parsed"]["question"]  # no "Which Williamsburg?"
    rc = RunConstraints.model_validate(out["parsed"]["constraints"])
    assert rc.end_place.area == "neighborhood"
    return rc, start_for(rc, req["client"]["location"], {})


def test_three_miles_to_williamsburg_asks_for_the_way_into_it_not_to_its_middle():
    rc, start = parsed_williamsburg(3)
    with pytest.raises(EngineQuestion) as into:
        Engine(use_prior=False, anchor_fn=None).build(rc, start, lambda e: None, "r_w3", end=end_for(rc, {}))
    with pytest.raises(EngineQuestion) as middle:  # the old way: to the neighborhood's point
        Engine(use_prior=False, anchor_fn=None, area_fn=lambda p: None).build(
            rc, start, lambda e: None, "r_w3b", end=end_for(rc, {}))
    offered = into.value.answer_map["options"]["a"]["distance"]
    assert offered < middle.value.answer_map["options"]["a"]["distance"]
    assert 3 < offered < 6, offered  # Kips Bay to Williamsburg is over the bridge


def test_at_the_offered_distance_it_finishes_inside_williamsburg():
    rc, start = parsed_williamsburg(3)
    with pytest.raises(EngineQuestion) as asked:
        Engine(use_prior=False, anchor_fn=None).build(rc, start, lambda e: None, "r_w", end=end_for(rc, {}))
    miles = asked.value.answer_map["options"]["a"]["distance"]
    rc = rc.model_copy(update={"distance_mi": miles})
    final = Engine(use_prior=False, anchor_fn=None).build(rc, start, lambda e: None, "r_w2", end=end_for(rc, {}))
    assert final["routes"], final["notes"]
    with psycopg.connect(database_url()) as conn:
        for r in final["routes"]:
            lon, lat = r["geometry"]["coordinates"][-1][:2]
            inside, depth = conn.execute(
                """SELECT ST_Intersects(geom, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)),
                          ST_Distance(ST_Boundary(geom)::geography, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)::geography)
                   FROM neighborhood_areas WHERE name = 'Williamsburg'""", {"lon": lon, "lat": lat}).fetchone()
            assert inside and depth >= AREA_DEPTH_M - 60, depth  # GraphHopper snaps the end to the nearest street
