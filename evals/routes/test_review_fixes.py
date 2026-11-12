"""Fixes from the full product review (docs: decision 046, 047), against the live stack (make up).

Each test is a request the review reproduced. The starts are public stand-ins (evals/routes/starts.json).
"""

from functools import cache

import pytest

from api.constraints import RunConstraints
from api.engine import Engine, Start
from evals.routes.live import load_starts, stack_problem

OWNER = "owner-install-0001"
GUEST = "tester-install-0002"


@pytest.fixture(scope="module", autouse=True)
def live_stack():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)


# --- 1. the Apple Health prior is the owner's only ---------------------------------------------------------------


@cache
def williamsburg_flat(install: str | None):
    """The review's request: 8 flat miles from Williamsburg, built for one install."""
    s = load_starts()["williamsburg"]
    rc = RunConstraints(use_my_location=True, distance_mi=8.0, hills="avoid")
    eng = Engine(prior_installs=frozenset({OWNER})).for_install(install)
    return eng.build(rc, Start(s["lat"], s["lon"], "Williamsburg"), lambda e: None, f"r_prior_{install}")


def test_another_install_gets_no_route_you_run():
    for install in (GUEST, None):
        final = williamsburg_flat(install)
        assert final["routes"]
        assert not [r["label"] for r in final["routes"] if "route you run" in r["label"]], install


def test_the_owners_install_still_gets_the_prior():
    labels = [r["label"] for r in williamsburg_flat(OWNER)["routes"]]
    assert any("route you run" in label for label in labels), labels


# --- 2. a route-type edit after a "through X" request (7.2) -------------------------------------------------------

import json  # noqa: E402

import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.parse import Context, DbPlaces, build as parse_build  # noqa: E402
from api.tests.test_parse import CASES, CONTEXTS, ext, mi  # noqa: E402
from evals.parse.fixtures import build_request  # noqa: E402
from etl.load import database_url  # noqa: E402

TOKEN = {"Authorization": "Bearer eval-token", "X-Loop-Install": GUEST}
KIPS_BAY = {"lat": 40.74384, "lon": -73.97994, "accuracy_m": 15}  # Kips Bay Library, a public stand-in


def _app(extraction):
    """The real server, engine and database, with the parse standing in for Claude (no API cost)."""
    from api.server import create_app

    def parse_fn(raw):
        with psycopg.connect(database_url()) as conn:
            return parse_build(extraction, Context.from_request(raw), DbPlaces(conn))

    return TestClient(create_app(token="eval-token", parse_fn=parse_fn, warm=False))


def _post(client, payload):
    resp = client.post("/v1/runs", json=payload, headers=TOKEN)
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


def _body(**kw):
    req = build_request(CASES["P01"], CONTEXTS)
    return {"v": 1, "client": {**req["client"], "location": KIPS_BAY}, "profile": req["profile"],
            "recent_routes": req["recent_routes"], **kw}


def test_a_route_type_edit_after_a_through_request_answers_from_the_pool():
    client = _app(ext(distance=mi(5), via=[{"name": "East River Esplanade", "kind": "place", "whole_way": False}]))
    first = _post(client, _body(text="5 miles along the East River Esplanade"))
    parsed, final = first[0], next(e for e in first if e["event"] == "final")
    assert final["routes"], first
    kind = final["routes"][0]["kind"]
    shape = {"loop": "loop", "out_and_back": "out_and_back"}.get(kind, "out_and_back")
    edited = _post(client, _body(constraints={**parsed["constraints"], "shape": shape}, route_id=final["route_id"]))
    assert not [e for e in edited if e["event"] == "error"], edited  # the review saw engine_unavailable in 0.02 s
    assert next(e for e in edited if e["event"] == "final")["routes"]
