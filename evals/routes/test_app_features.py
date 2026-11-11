"""The iPhone app's features against the live stack (decision 043): make up, then  uv run pytest evals/routes

- A rating round-trip: "I ran it", then a rating, then a changed rating, in route_feedback (one row per install).
- "Run again": the stored route's own line, exactly, through the API with the real engine and saved_routes.
- A long street given alone, far off: "Where on Amsterdam Ave?" with crossings; a short one isn't asked about.
- The phone bug: W 71st St as the start of a run in "the park", from the Upper West Side, is found. There the
  park is Riverside Park, which W 71st St doesn't reach: the lookup for where the street meets it came back empty.
Past routes are evals/past_routes.py's fixture lines (public waypoints near the Kips Bay Library stand-in).
"""

import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.feedback import AppFeedback, PgFeedbackStore
from api.parse import Context, DbPlaces, build
from api.saved_routes import PgRouteStore
from api.tests.test_parse import CASES, CONTEXTS, ext, mi, place
from evals.parse.fixtures import build_request
from evals.past_routes import seed
from evals.routes.live import stack_problem
from etl.load import database_url

EVAL_INSTALL = "eval-0000-install-decision-043"  # the evals' own install id, never a phone's
UPPER_WEST_SIDE = (40.7800, -73.9800)  # Broadway at W 79th St, a public crossing: Riverside Park is the nearest


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)
    seed()


def test_a_rating_round_trip_and_a_later_change():
    store, routes = PgFeedbackStore(), PgRouteStore()
    final, constraints = routes.load_with_constraints("rt_a")
    store.save("rt_a", EVAL_INSTALL, AppFeedback(ran=True, ran_at="2026-11-10T07:30:00-05:00"), final, constraints)
    assert store.load("rt_a", EVAL_INSTALL)["rating"] is None
    store.save("rt_a", EVAL_INSTALL, AppFeedback(ran=True, rating="good"), final, constraints)
    got = store.save("rt_a", EVAL_INSTALL, AppFeedback(ran=True, rating="not_for_me", reasons=["crowded"],
                                                       note="eval"), final, constraints)
    assert got["updated"] is True
    row = store.load("rt_a", EVAL_INSTALL)
    assert row["rating"] == "not_for_me" and row["reasons"] == ["crowded"] and row["ran_at"] is not None
    with psycopg.connect(database_url()) as conn:
        n = conn.execute("SELECT count(*) FROM route_feedback WHERE route_id = 'rt_a' AND install_id = %s",
                         (EVAL_INSTALL,)).fetchone()[0]
    assert n == 1  # one row per install and route, updated in place


def test_run_again_returns_the_same_line():
    from api.server import create_app
    app = create_app(token="eval-token", warm=False)
    client = TestClient(app)
    req = build_request(CASES["P01"], CONTEXTS)
    body = {"v": 1, "route_id": "rt_a", "mode": "exact", "client": req["client"], "profile": req["profile"]}
    resp = client.post("/v1/runs", json=body, headers={"Authorization": "Bearer eval-token",
                                                         "X-Loop-Install": EVAL_INSTALL})
    evs = [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]
    assert [e["event"] for e in evs] == ["parsed", "final", "done"], evs
    stored = PgRouteStore().load("rt_a")["routes"][0]["geometry"]["coordinates"]
    got = evs[1]["routes"][0]["geometry"]["coordinates"]
    assert got == [c[:2] for c in stored]  # exactly the line that was run
    summary = evs[1]["route"]["features"][0]["properties"]["summary"]
    assert "crowds" in summary  # read for now (today's clock), scored or said why not


def _parsed(extraction, location):
    req = build_request(CASES["P01"], CONTEXTS)
    req["client"] = {**req["client"], "location": {"lat": location[0], "lon": location[1], "accuracy_m": 15}}
    with psycopg.connect(database_url()) as conn:
        return build(extraction, Context.from_request(req), DbPlaces(conn))["parsed"]


def test_w_71st_st_with_a_run_in_the_park_from_the_upper_west_side():  # the phone bug
    parsed = _parsed(ext(start=place("place", "W 71st St"), distance=mi(4),
                         via=[{"name": "the park", "kind": "the_park", "whole_way": False}]), UPPER_WEST_SIDE)
    assert parsed["question"] is None, parsed["question"]
    start = parsed["constraints"]["start_place"]
    assert start["name"] == "West 71st Street" and start["trust"] == "listed"
    assert parsed["constraints"]["via_places"][0]["name"] == "Riverside Park"  # the street doesn't reach it


def test_a_long_street_far_off_asks_where_on_it():
    parsed = _parsed(ext(end=place("place", "Amsterdam Ave"), distance=mi(5)), (40.7438, -73.9799))  # Kips Bay
    q = parsed["question"]
    assert q["text"] == "Where on Amsterdam Ave?" and 2 <= len(q["options"]) <= 4
    assert all("Amsterdam Ave" in o["text"] for o in q["options"])


def test_a_short_street_isnt_asked_about():
    parsed = _parsed(ext(start=place("place", "W 71st St"), distance=mi(4)), (40.7438, -73.9799))
    assert parsed["question"] is None
