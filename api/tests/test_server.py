"""The API (step 5, decision 029): the token, the three request paths, the event order, pending questions and the
thread bridge. The parser's rules run for real on the eval cases' ideal extractions with fake places; the engine is
a fake that sends from other threads, as the generator does."""

import json
import threading
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from api.parse import Context, build
from api.pending import PENDING_TTL_S, PendingStore
from api.server import create_app
from api.tests.test_parse import CASES, CONTEXTS, IDEAL, FakePlaces, ext, mi
from evals.parse.fixtures import build_request

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class FakeEngine:
    def __init__(self, fail=None, ask_once=None):
        self.calls, self.fail, self.ask_once = [], fail, ask_once

    def build(self, rc, start, send, route_id, end=None):
        self.calls.append((rc, start))
        self.ends = getattr(self, "ends", []) + [end]
        if self.fail:
            raise self.fail
        if self.ask_once and len(self.calls) == 1:
            raise self.ask_once
        for ev in ("top3", "top3", "provisional"):
            t = threading.Thread(target=send, args=({"event": ev, "v": 1, "route_id": route_id, "elapsed_s": 0.5,
                                                     "provisional": ev == "provisional", "routes": []},))
            t.start()
            t.join()
        return {"event": "final", "v": 1, "route_id": route_id, "elapsed_s": 1.0, "provisional": False,
                "routes": [], "route": None, "pool_size": 12, "notes": []}


def fake_parse(by_text: dict):
    """parse() with the real rules: the eval case's ideal extraction stands in for Claude's."""
    calls = []

    def parse_fn(raw):
        calls.append(raw["text"])
        e = by_text.get(raw["text"])
        if e is None:
            return {"error": "parse_failed", "text": "x"}
        out = build(e, Context.from_request(raw), FakePlaces())
        out["trace"]["extraction"] = e
        return out

    parse_fn.calls = calls
    return parse_fn


class FakeRouteStore:
    """saved_routes in a dict: it outlives an app, as Postgres outlives a server restart."""

    def __init__(self):
        self.rows = {}

    def save(self, route_id, request, constraints, final):
        self.rows[route_id] = {"request": request, "constraints": constraints, "final": final}
        return True

    def load(self, route_id):
        row = self.rows.get(route_id)
        return row["final"] if row else None


@contextmanager
def fake_places():
    yield FakePlaces()


def client_for(by_text=None, engine=None, store=None, parse_fn=None, route_store=None):
    parse_fn = parse_fn or fake_parse(by_text or {})
    app = create_app(token=TOKEN, parse_fn=parse_fn, places=fake_places, engine=engine or FakeEngine(),
                     route_store=FakeRouteStore() if route_store is None else route_store,
                     store=PendingStore() if store is None else store, health_fn=lambda: {"engine": True, "database": True,
                                                                       "parser": True}, warm=False)
    return TestClient(app), parse_fn


def body(case_id="P36", **kw):
    req = build_request(CASES[case_id], CONTEXTS)
    return {"v": 1, **{k: req[k] for k in ("client", "profile", "recent_routes")}, **kw}


def events(resp) -> list[dict]:
    """The SSE stream as (event, data) pairs; checks each data's event matches its SSE event line."""
    out, name = [], None
    for line in resp.text.splitlines():
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            data = json.loads(line.removeprefix("data: "))
            assert data["event"] == name
            out.append(data)
    return out


def post(client, payload):
    resp = client.post("/v1/runs", json=payload, headers=AUTH)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    return events(resp)


def test_health_is_open_and_says_whats_ready():
    c, _ = client_for()
    r = c.get("/v1/health")
    assert r.status_code == 200 and r.json() == {"v": 1, "ok": True, "engine": True, "database": True, "parser": True}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope"}, {"Authorization": TOKEN + "x"}])
def test_everything_else_needs_the_loop_token(headers):
    c, parse_fn = client_for({"6 mi": IDEAL["P36"]})
    assert c.post("/v1/runs", json=body(text="6 mi"), headers=headers).status_code == 401
    assert c.get("/v1/routes/r_1", headers=headers).status_code == 401
    assert parse_fn.calls == []


def test_the_server_wont_start_without_a_token(monkeypatch):
    monkeypatch.delenv("LOOP_TOKEN", raising=False)
    monkeypatch.setattr("api.env.load_env", lambda: None)
    with pytest.raises(RuntimeError, match="LOOP_TOKEN"):
        create_app(parse_fn=lambda r: {}, places=fake_places, engine=FakeEngine(), warm=False)


def test_a_typed_request_streams_parsed_then_routes_then_done():
    c, _ = client_for({"training run, 6 mi, I wait at lights": IDEAL["P36"]})
    evs = post(c, body(text="training run, 6 mi, I wait at lights"))
    assert [e["event"] for e in evs] == ["parsed", "top3", "top3", "provisional", "final", "done"]
    parsed, final = evs[0], evs[4]
    assert parsed["question"] is None and parsed["constraints"]["distance_mi"] == 6
    assert "trace" not in parsed
    assert len({e["route_id"] for e in evs[1:5]}) == 1
    got = c.get(f"/v1/routes/{final['route_id']}", headers=AUTH)
    assert got.status_code == 200 and got.json() == final
    assert c.get("/v1/routes/r_nope", headers=AUTH).status_code == 404


def test_a_question_ends_the_stream_and_the_answer_resumes_without_claude():
    eng = FakeEngine()
    c, parse_fn = client_for({"exploring run": IDEAL["R06"]}, engine=eng)
    first = post(c, body("R06", text="exploring run"))
    assert [e["event"] for e in first] == ["parsed", "done"]
    q = first[0]["question"]
    assert q["about"] == "distance" and "_answer" not in q and eng.calls == []
    second = post(c, body("R06", answer={"parse_id": first[0]["parse_id"], "question_id": q["id"], "option_id": "b"}))
    assert [e["event"] for e in second] == ["parsed", "top3", "top3", "provisional", "final", "done"]
    assert second[0]["constraints"]["distance_mi"] == 5 and second[0]["parse_id"] != first[0]["parse_id"]
    assert parse_fn.calls == ["exploring run"]  # one Claude call in all
    # The answer is used once
    again = post(c, body("R06", answer={"parse_id": first[0]["parse_id"], "question_id": q["id"], "option_id": "b"}))
    assert [e.get("code") for e in again] == ["expired"]


def test_a_typed_answer():
    c, _ = client_for({"45 minutes": IDEAL["P11"]})
    first = post(c, body("P11", text="45 minutes"))
    pid, qid = first[0]["parse_id"], first[0]["question"]["id"]
    second = post(c, body("P11", answer={"parse_id": pid, "question_id": qid, "text": "about 5 miles"}))
    assert second[0]["constraints"]["distance_mi"] == 5 and second[-1]["event"] == "done"


def test_an_unreadable_answer_asks_again_with_a_new_parse_id():
    c, _ = client_for({"45 minutes": IDEAL["P11"]})
    first = post(c, body("P11", text="45 minutes"))
    pid, qid = first[0]["parse_id"], first[0]["question"]["id"]
    second = post(c, body("P11", answer={"parse_id": pid, "question_id": qid, "text": "dunno"}))
    assert [e["event"] for e in second] == ["parsed", "done"]
    assert second[0]["question"]["text"] == first[0]["question"]["text"] and second[0]["parse_id"] != pid


def test_after_15_minutes_the_answer_is_expired():
    now = [1000.0]
    store = PendingStore(clock=lambda: now[0])
    c, _ = client_for({"exploring run": IDEAL["R06"]}, store=store)
    first = post(c, body("R06", text="exploring run"))
    now[0] += PENDING_TTL_S + 1
    evs = post(c, body("R06", answer={"parse_id": first[0]["parse_id"], "question_id": "q_1", "option_id": "a"}))
    assert evs == [{"event": "error", "v": 1, "code": "expired",
                    "text": "That question timed out, so the request is being sent again."}]


@pytest.mark.parametrize("answer", [{"question_id": "q_9", "option_id": "a"}, {"question_id": "q_1", "option_id": "z"}])
def test_an_answer_that_doesnt_fit_the_question_is_a_bad_request(answer):
    c, _ = client_for({"exploring run": IDEAL["R06"]})
    first = post(c, body("R06", text="exploring run"))
    evs = post(c, body("R06", answer={"parse_id": first[0]["parse_id"], **answer}))
    assert [e.get("code") for e in evs] == ["bad_request"]


@pytest.mark.parametrize("payload", [
    {"v": 1, "text": "6 mi"},  # no client
    {"v": 2, "text": "6 mi", "client": {"now": "2026-11-03T06:40:00-05:00"}},
    {"v": 1, "text": "6 mi", "constraints": {}, "client": {"now": "2026-11-03T06:40:00-05:00"}},
    {"v": 1, "text": "   ", "client": {"now": "2026-11-03T06:40:00-05:00"}},
    {"v": 1, "text": "x" * 501, "client": {"now": "2026-11-03T06:40:00-05:00"}},
    {"v": 1, "text": "6 mi", "client": {"now": "6:40 this morning"}},
])
def test_a_malformed_request_is_a_bad_request_event(payload):
    c, parse_fn = client_for({"6 mi": IDEAL["P36"]})
    assert [e.get("code") for e in post(c, payload)] == ["bad_request"]
    assert parse_fn.calls == []


def test_a_body_that_isnt_json_is_a_bad_request():
    c, _ = client_for()
    resp = c.post("/v1/runs", content=b"{not json", headers=AUTH | {"content-type": "application/json"})
    assert [e.get("code") for e in events(resp)] == ["bad_request"]


def test_a_parse_failure_is_an_error_event():
    c, _ = client_for({})
    assert [e.get("code") for e in post(c, body(text="??"))] == ["parse_failed"]


def test_a_chip_edit_sends_constraints_and_skips_claude():
    c, parse_fn = client_for({"training run, 6 mi, I wait at lights": IDEAL["P36"]})
    parsed = post(c, body(text="training run, 6 mi, I wait at lights"))[0]
    edited = parsed["constraints"] | {"distance_mi": 8}
    evs = post(c, body(constraints=edited))
    assert [e["event"] for e in evs] == ["parsed", "top3", "top3", "provisional", "final", "done"]
    assert next(x for x in evs[0]["chips"] if x["field"] == "distance")["text"] == "8 mi"
    assert parse_fn.calls == ["training run, 6 mi, I wait at lights"]


def test_bad_constraints_are_a_bad_request():
    c, _ = client_for()
    assert [e.get("code") for e in post(c, body(constraints={"distance_mi": -3}))] == ["bad_request"]


def test_what_the_engine_cant_build_yet_is_a_cant_line_and_no_routes():
    eng = FakeEngine()
    c, _ = client_for({"6 miles, avoid 1st ave by the hospitals": IDEAL["P23"]}, engine=eng)
    evs = post(c, body("P23", text="6 miles, avoid 1st ave by the hospitals"))
    assert [e["event"] for e in evs] == ["parsed", "done"]
    assert [x["gap"] for x in evs[0]["cant"]] == ["later"] and "along a street" in evs[0]["cant"][0]["text"]
    assert eng.calls == []


def test_hills_are_built_with_a_cant_line():
    eng = FakeEngine()
    c, _ = client_for({"6 mi, flat": IDEAL["P33"]}, engine=eng)
    evs = post(c, body("P33", text="6 mi, flat"))
    assert evs[0]["cant"][-1]["text"].startswith("Can't score hills yet") and evs[-1]["event"] == "done"
    assert len(eng.calls) == 1


def test_the_engine_down_is_an_error_after_the_parse():
    from api.engine import EngineUnavailable
    c, _ = client_for({"6 mi": IDEAL["P36"]}, engine=FakeEngine(fail=EngineUnavailable("down")))
    evs = post(c, body(text="6 mi"))
    assert [e["event"] for e in evs] == ["parsed", "error"] and evs[1]["code"] == "engine_unavailable"


def test_an_engine_bug_still_ends_the_stream():
    c, _ = client_for({"6 mi": IDEAL["P36"]}, engine=FakeEngine(fail=KeyError("oops")))
    assert [e.get("code") for e in post(c, body(text="6 mi"))][-1] == "engine_unavailable"


def test_the_start_is_the_phones_location_from_the_request():
    eng = FakeEngine()
    c, _ = client_for({"5 mi": ext(distance=mi(5))}, engine=eng)
    post(c, body("P36", text="5 mi"))
    rc, start = eng.calls[0]
    assert rc.use_my_location and (start.lat, start.lon) == (40.7438, -73.9799)


def test_a_build_is_stored_and_served_after_a_restart():
    routes = FakeRouteStore()
    c, _ = client_for({"training run, 6 mi, I wait at lights": IDEAL["P36"]}, route_store=routes)
    final = post(c, body(text="training run, 6 mi, I wait at lights"))[-2]
    restarted, _ = client_for(route_store=routes)  # a new app: nothing in memory
    got = restarted.get(f"/v1/routes/{final['route_id']}", headers=AUTH)
    assert got.status_code == 200 and got.json() == final


def test_the_stored_row_keeps_no_text_and_no_location():
    routes = FakeRouteStore()
    e = dict(IDEAL["P36"], said=[{"chip": "distance", "item": 0, "words": "6 mi"}])
    c, _ = client_for({"6 mi, my knee is sore": e}, route_store=routes)
    evs = post(c, body(text="6 mi, my knee is sore"))
    row = routes.rows[evs[-2]["route_id"]]
    assert row["request"]["kind"] == "text" and row["request"]["parse_id"] == evs[0]["parse_id"]
    assert row["constraints"] == {k: v for k, v in evs[0]["constraints"].items() if k != "spans"}
    assert "spans" in evs[0]["constraints"] and "spans" not in row["constraints"]  # the runner's words stay out
    flat = repr(row["request"]) + repr(row["constraints"])
    assert "knee" not in flat and "40.7438" not in flat


def test_answers_and_chip_edits_are_stored_with_their_kind():
    routes = FakeRouteStore()
    c, _ = client_for({"exploring run": IDEAL["R06"]}, route_store=routes)
    first = post(c, body("R06", text="exploring run"))
    second = post(c, body("R06", answer={"parse_id": first[0]["parse_id"], "question_id": "q_1", "option_id": "a"}))
    third = post(c, body("R06", constraints=second[0]["constraints"] | {"distance_mi": 4}))
    kinds = {routes.rows[e[-2]["route_id"]]["request"]["kind"] for e in (second, third)}
    assert kinds == {"answer", "constraints"}


def test_a_question_or_a_blocked_build_stores_nothing():
    routes = FakeRouteStore()
    c, _ = client_for({"exploring run": IDEAL["R06"], "avoid 1st ave": IDEAL["P23"]}, route_store=routes)
    post(c, body("R06", text="exploring run"))
    post(c, body("P23", text="avoid 1st ave"))
    assert routes.rows == {}


def test_an_a_to_b_run_gets_its_end_and_builds():
    eng = FakeEngine()
    c, _ = client_for({"8 mi to McCarren Park": IDEAL["R01"]}, engine=eng)
    evs = post(c, body("R01", text="8 mi to McCarren Park"))
    assert [e["event"] for e in evs][:2] == ["parsed", "top3"] and evs[-1]["event"] == "done"
    assert evs[0]["cant"] == [] and evs[0]["reach_m"] is None
    assert eng.ends == [(40.7204, -73.9512)]  # McCarren Park's coordinates, from the places table


def test_the_engine_asks_and_the_answer_builds_at_the_new_distance():
    from api.engine import shortest_way_question
    from api.units import miles_to_meters
    eng = FakeEngine(ask_once=shortest_way_question(miles_to_meters(4.23)))
    c, parse_fn = client_for({"3 mi to McCarren Park": ext(distance=mi(3), end=IDEAL["R01"]["end"])}, engine=eng)
    first = post(c, body("R01", text="3 mi to McCarren Park"))
    assert [e["event"] for e in first] == ["parsed", "question", "done"]
    q = first[1]
    assert q["from"] == "engine" and q["about"] == "distance" and q["parse_id"] != first[0]["parse_id"]
    assert q["text"] == "The shortest way there is 4.3 mi. Make it 4.3 mi?"
    assert [o["text"] for o in q["options"]] == ["4.3 mi"] and "_answer" not in q
    second = post(c, body("R01", answer={"parse_id": q["parse_id"], "question_id": q["id"], "option_id": "a"}))
    assert [e["event"] for e in second][0] == "parsed" and second[-1]["event"] == "done"
    assert second[0]["constraints"]["distance_mi"] == 4.3
    assert next(x for x in second[0]["chips"] if x["field"] == "distance")["source"] == "said"
    assert len(eng.calls) == 2 and parse_fn.calls == ["3 mi to McCarren Park"]  # no second Claude call


def test_an_engine_question_on_a_chip_edit_edits_the_constraints():
    from api.engine import shortest_way_question
    from api.units import miles_to_meters
    eng = FakeEngine()
    c, _ = client_for({"8 mi to McCarren Park": IDEAL["R01"]}, engine=eng)
    parsed = post(c, body("R01", text="8 mi to McCarren Park"))[0]
    eng.ask_once, eng.calls = shortest_way_question(miles_to_meters(4.23)), []
    first = post(c, body("R01", constraints=parsed["constraints"] | {"distance_mi": 2}))
    q = first[1]
    assert q["event"] == "question"
    second = post(c, body("R01", answer={"parse_id": q["parse_id"], "question_id": "q_1", "text": "5 miles"}))
    assert second[0]["constraints"]["distance_mi"] == 5 and second[-1]["event"] == "done"
