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
from api.markers import spurs  # noqa: E402
from api.tests.test_parse import CASES, CONTEXTS, ext, mi, place  # noqa: E402
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


# --- 3. misreads (4.2) --------------------------------------------------------------------------------------------------

BROADWAY_79TH = {"lat": 40.7800, "lon": -73.9800, "accuracy_m": 15}  # a public crossing, a block from Central Park


def _inside_share(coords, name):
    """The share of a route's points inside a named park's outline."""
    import shapely
    from shapely.geometry import Point, shape
    with psycopg.connect(database_url()) as conn:
        gj = conn.execute("SELECT ST_AsGeoJSON(outline) FROM places WHERE name = %s AND kind = 'park' AND outline IS NOT "
                          "NULL ORDER BY area_ha DESC NULLS LAST LIMIT 1", (name,)).fetchone()[0]
    park = shape(json.loads(gj))
    return sum(park.contains(Point(c[0], c[1])) for c in coords) / len(coords)


def test_5_miles_in_central_park_routes_in_central_park():  # Q1: Haiku records "Central Park" as kind the_park
    client = _app(ext(distance=mi(5), via=[{"name": "Central Park", "kind": "the_park", "whole_way": False}]))
    body = _body(text="5 miles in Central Park")
    body["client"] = {**body["client"], "location": BROADWAY_79TH}
    evs = _post(client, body)
    parsed, final = evs[0], next(e for e in evs if e["event"] == "final")
    assert [v["name"] for v in parsed["constraints"]["via_places"]] == ["Central Park"]
    assert final["routes"], final["notes"]
    assert _inside_share(final["routes"][0]["geometry"]["coordinates"], "Central Park") >= 0.5


def test_a_lap_of_the_reservoir_builds_from_the_east_side():  # Q6: from E 86th & 2nd it gave "couldn't build a route"
    client = _app(ext(start=place("place", "86th St & 2nd Ave"),
                      via=[{"name": "the reservoir", "kind": "place", "whole_way": False, "word": "loop around"}]))
    evs = _post(client, _body(text="loop around the reservoir"))
    final = next(e for e in evs if e["event"] == "final")
    assert final["routes"], final["notes"]
    route = final["routes"][0]
    assert spurs(route["geometry"]["coordinates"]) == []
    assert 2.5 <= route["distance"]["value"] <= 4.5  # the way in, a 1 mi lap of the track, the way back


def test_10k_past_the_met_builds_and_passes_it():  # Q4: "Couldn't find Metropolitan Museum of Art", then an address loop
    from api.geometry import passes_through
    client = _app(ext(distance=mi(10, "km"), via=[{"name": "Metropolitan Museum of Art", "kind": "place",
                                                    "whole_way": False}]))
    evs = _post(client, _body(text="10k past the Met then home"))
    parsed, final = evs[0], next(e for e in evs if e["event"] == "final")
    assert parsed["question"] is None, parsed["question"]
    via = parsed["constraints"]["via_places"][0]
    assert via["name"] == "Metropolitan Museum of Art" and via["trust"] == "listed" and via["source"]
    assert final["routes"], final["notes"]
    met = {"type": "Point", "coordinates": [via["lon"], via["lat"]]}
    assert passes_through(final["routes"][0]["geometry"]["coordinates"], met, 150)


def test_a_restroom_stop_is_said_to_be_unsupported_never_dropped():  # Q7: shown as understood, then ignored
    client = _app(ext(distance=mi(3), amenities=[{"kind": "restroom", "at_mile": 3, "at_fraction": None}]))
    evs = _post(client, _body(text="3 miles, bathroom near mile 3"))
    parsed, final = evs[0], next(e for e in evs if e["event"] == "final")
    assert [c["field"] for c in parsed["chips"] if c["field"] == "amenity"]  # still understood and shown
    lines = [k for k in parsed["cant"] if k["gap"] == "later"]
    assert len(lines) == 1 and "restroom" in lines[0]["text"].lower()
    assert final["routes"]  # an honest line, and the run is still built


# --- 4. GPX for the app's Share ------------------------------------------------------------------------------------------


def test_a_built_route_downloads_as_gpx_through_the_stored_id():
    import xml.etree.ElementTree as ET
    client = _app(ext(distance=mi(3)))
    evs = _post(client, _body(text="3 miles"))
    final = next(e for e in evs if e["event"] == "final")
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    for route in final["routes"][:2]:  # every route of the build, by its own id
        got = client.get(f"/v1/routes/{route['id']}/gpx", headers=TOKEN)
        assert got.status_code == 200 and got.headers["content-type"].startswith("application/gpx+xml")
        root = ET.fromstring(got.text)
        assert len(root.findall(".//g:trkpt", ns)) == len(route["geometry"]["coordinates"])
        names = [w.find("g:name", ns).text for w in root.findall("g:wpt", ns)]
        assert names[0] == "Start" and "Mile 1" in names
    first = client.get(f"/v1/routes/{final['route_id']}/gpx", headers=TOKEN)  # the build id: the first route
    assert first.status_code == 200 and f"loop-{final['routes'][0]['id']}.gpx" in first.headers["content-disposition"]
