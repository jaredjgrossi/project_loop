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
    def __init__(self, fail=None, ask_once=None, routes=None):
        self.calls, self.fail, self.ask_once, self.routes = [], fail, ask_once, routes or []

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
                "routes": self.routes, "route": None, "pool_size": 12, "notes": []}


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
        found = self.load_with_constraints(route_id)
        return found[0] if found else None

    def load_with_constraints(self, route_id):
        row = self.rows.get(route_id.partition(".")[0])
        return (row["final"], row["constraints"]) if row else None


class FakeFeedbackStore:
    """route_feedback in a dict, one row per (route, install), as the unique index keeps it."""

    def __init__(self):
        self.rows = {}

    def save(self, route_id, install_id, fb, final, constraints):
        if not any(r.get("id") == route_id or f"{final.get('route_id')}.{r.get('rank')}" == route_id
                   for r in final.get("routes") or []):
            raise LookupError(route_id)
        updated = (route_id, install_id) in self.rows
        self.rows[(route_id, install_id)] = fb.model_dump(mode="json")
        return {"created_at": "2026-11-10T08:00:00+00:00", "updated_at": "2026-11-10T08:00:00+00:00",
                "updated": updated}


@contextmanager
def fake_places():
    yield FakePlaces()


def client_for(by_text=None, engine=None, store=None, parse_fn=None, route_store=None, feedback_store=None):
    parse_fn = parse_fn or fake_parse(by_text or {})
    app = create_app(token=TOKEN, parse_fn=parse_fn, places=fake_places, engine=engine or FakeEngine(),
                     route_store=FakeRouteStore() if route_store is None else route_store,
                     feedback_store=FakeFeedbackStore() if feedback_store is None else feedback_store,
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


def test_a_past_route_builds():  # step 11 (decision 038)
    eng = FakeEngine()
    c, _ = client_for({"same as Tuesday": IDEAL["H01"]}, engine=eng)
    evs = post(c, body("H01", text="same as Tuesday"))
    assert [e["event"] for e in evs][:2] == ["parsed", "top3"] and evs[-1]["event"] == "done"
    assert evs[0]["cant"] == [] and eng.calls[0][0].reuse_route_id == "rt_a"


def test_a_planned_run_is_built_for_its_day_and_sent_after_final():  # step 11, D6
    routes = FakeRouteStore()
    eng = FakeEngine(routes=[{"id": "x.1", "rank": 1, "distance": {"value": 10.02, "unit": "mi"}}])
    c, _ = client_for({"5k tonight and a 10 miler sat": IDEAL["P45"]}, engine=eng, route_store=routes)
    evs = post(c, body("P45", text="5k tonight and a 10 miler sat"))
    names = [e["event"] for e in evs]
    assert names[-3:] == ["final", "planned", "done"]
    planned = evs[-2]
    assert planned["date"] == "2026-11-07" and planned["summary"] == {"distance_mi": 10.02, "start_time": "07:00"}
    assert planned["route_id"] in routes.rows and planned["constraints"]["distance_mi"] == 10
    assert any(ch["field"] == "distance" for ch in planned["chips"])
    first, second = eng.calls
    assert first[0].planned is not None and second[0].start_date.isoformat() == "2026-11-07"
    assert second[1].label != first[1].label  # from home on Saturday, not from here tonight


def test_a_planned_run_that_cant_be_built_says_so_and_ends_the_stream():
    eng = FakeEngine()  # no routes
    c, _ = client_for({"5k tonight and a 10 miler sat": IDEAL["P45"]}, engine=eng)
    evs = post(c, body("P45", text="5k tonight and a 10 miler sat"))
    assert [e["event"] for e in evs][-2:] == ["planned", "done"]
    assert evs[-2]["route_id"] is None and evs[-2]["notes"][0]["key"] == "planned_not_built"


def test_an_along_avoid_builds():  # step 8b (decision 036)
    eng = FakeEngine()
    c, _ = client_for({"6 miles, avoid 1st ave by the hospitals": IDEAL["P23"]}, engine=eng)
    evs = post(c, body("P23", text="6 miles, avoid 1st ave by the hospitals"))
    assert [e["event"] for e in evs][:2] == ["parsed", "top3"] and evs[-1]["event"] == "done"
    assert evs[0]["cant"] == [] and len(eng.calls) == 1


def test_flat_is_built_with_no_cant_line():  # step 10 scores hills (decision 037)
    eng = FakeEngine()
    c, _ = client_for({"6 mi, flat": IDEAL["P33"]}, engine=eng)
    evs = post(c, body("P33", text="6 mi, flat"))
    assert evs[0]["cant"] == [] and evs[-1]["event"] == "done"
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
    c, _ = client_for({"exploring run": IDEAL["R06"]}, route_store=routes)
    post(c, body("R06", text="exploring run"))
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


# ---- shape edits reuse the pool (phone test round 2, decision 042) ---------------------------------------------------

class PoolEngine(FakeEngine):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.pool_calls = []

    def from_pool(self, rc, start, old_route_id, send, route_id):
        self.pool_calls.append((rc.shape, old_route_id))
        send({"event": "top3", "v": 1, "route_id": route_id, "elapsed_s": 0.0, "provisional": False, "routes": []})
        return {"event": "final", "v": 1, "route_id": route_id, "elapsed_s": 0.0, "provisional": False,
                "routes": [], "route": None, "pool_size": 3, "notes": [], "timing": {"from_pool": old_route_id}}


def _first_build(c):
    evs = post(c, body("P05", text="3 mile loop"))
    return next(e for e in evs if e["event"] == "parsed"), next(e for e in evs if e["event"] == "final")


def test_a_shape_only_edit_comes_from_the_pool_without_building():
    eng = PoolEngine()
    c, _ = client_for({"3 mile loop": IDEAL["P05"]}, engine=eng)
    parsed, final = _first_build(c)
    edited = {**parsed["constraints"], "shape": "out_and_back"}
    evs = post(c, body("P05", constraints=edited, route_id=final["route_id"]))
    assert [e["event"] for e in evs] == ["parsed", "top3", "final", "done"]
    assert eng.pool_calls == [("out_and_back", final["route_id"])] and len(eng.calls) == 1  # no second build
    assert evs[2]["timing"] == {"from_pool": final["route_id"]}


def test_an_edit_that_changes_more_than_the_shape_builds_again():
    eng = PoolEngine()
    c, _ = client_for({"3 mile loop": IDEAL["P05"]}, engine=eng)
    parsed, final = _first_build(c)
    edited = {**parsed["constraints"], "shape": "out_and_back", "distance_mi": 4.0}
    post(c, body("P05", constraints=edited, route_id=final["route_id"]))
    assert eng.pool_calls == [] and len(eng.calls) == 2


def test_a_shape_edit_without_the_route_id_builds_again_and_honors_the_shape():
    eng = PoolEngine()
    c, _ = client_for({"3 mile loop": IDEAL["P05"]}, engine=eng)
    parsed, _ = _first_build(c)
    post(c, body("P05", constraints={**parsed["constraints"], "shape": "out_and_back"}))
    assert eng.pool_calls == [] and eng.calls[-1][0].shape == "out_and_back"


def test_the_usual_shape_comes_from_the_profile():
    eng = FakeEngine()
    c, _ = client_for({"5k": IDEAL["P01"]}, engine=eng)
    b = body("P01", text="5k")
    b["profile"] = {**b["profile"], "usual_shape": "loop"}
    parsed = post(c, b)[0]
    assert parsed["constraints"]["shape"] == "loop" and eng.calls[0][0].shape == "loop"



# ---- the app's features: install id, feedback, stored routes, run again, route type (decision 043) ------------------

INSTALL = {"X-Loop-Install": "3f9c2b1e-7a4d-4e8b-9c1a-2b3c4d5e6f70"}
ROUTE = {"id": "r_old00001.1", "rank": 1, "kind": "loop", "label": "a loop", "score": 80,
         "distance": {"value": 3.0, "unit": "mi"},
         "geometry": {"type": "LineString", "coordinates": [[-73.9799, 40.7438], [-73.9750, 40.7438],
                                                            [-73.9750, 40.7470], [-73.9799, 40.7438]]}}


def stored_client(**kw):
    routes = FakeRouteStore()
    routes.save("r_old00001", {"v": 1, "kind": "text"}, {"use_my_location": True, "distance_mi": 3.0},
                {"event": "final", "v": 1, "route_id": "r_old00001", "routes": [ROUTE], "route": None})
    feedbacks = FakeFeedbackStore()
    c, _ = client_for(route_store=routes, feedback_store=feedbacks, **kw)
    return c, routes, feedbacks


def test_a_stored_route_is_fetched_by_its_own_id_with_its_line():
    c, _, _ = stored_client()
    got = c.get("/v1/routes/r_old00001.1", headers=AUTH)
    assert got.status_code == 200 and got.json()["routes"][0]["geometry"] == ROUTE["geometry"]
    assert c.get("/v1/routes/r_nothere.1", headers=AUTH).status_code == 404


def test_a_rating_round_trip_and_a_later_change():
    c, _, feedbacks = stored_client()
    first = c.post("/v1/routes/r_old00001.1/feedback", headers=AUTH | INSTALL,
                   json={"ran": True, "ran_at": "2026-11-10T07:30:00-05:00", "rating": None})
    assert first.status_code == 200 and first.json()["updated"] is False
    again = c.post("/v1/routes/r_old00001.1/feedback", headers=AUTH | INSTALL,
                   json={"ran": True, "rating": "not_for_me", "reasons": ["crowded", "lights"], "note": "busy at 7"})
    assert again.status_code == 200 and again.json()["updated"] is True
    row = feedbacks.rows[("r_old00001.1", INSTALL["X-Loop-Install"])]
    assert row["rating"] == "not_for_me" and row["reasons"] == ["crowded", "lights"]


@pytest.mark.parametrize("payload, status", [
    ({"ran": False, "rating": "good"}, 422),  # a rating needs the run
    ({"ran": True, "rating": "great"}, 422),  # a verdict, not wording
    ({"ran": True, "rating": "good", "reasons": ["too hilly"]}, 422),  # reasons are keys
])
def test_feedback_is_checked(payload, status):
    c, _, _ = stored_client()
    assert c.post("/v1/routes/r_old00001.1/feedback", headers=AUTH | INSTALL, json=payload).status_code == status


def test_feedback_needs_the_install_id_and_a_known_route():
    c, _, _ = stored_client()
    body_ = {"ran": True, "rating": "good"}
    assert c.post("/v1/routes/r_old00001.1/feedback", headers=AUTH, json=body_).status_code == 400
    assert c.post("/v1/routes/r_old00001.1/feedback", headers=AUTH | {"X-Loop-Install": "bad id!"},
                  json=body_).status_code == 400
    assert c.post("/v1/routes/r_nothere.1/feedback", headers=AUTH | INSTALL, json=body_).status_code == 404
    assert c.post("/v1/routes/r_old00001.1/feedback", json=body_, headers=INSTALL).status_code == 401


def test_the_install_id_is_stored_with_a_build():
    routes = FakeRouteStore()
    c, _ = client_for({"5k": IDEAL["P01"]}, route_store=routes)
    resp = c.post("/v1/runs", json=body("P01", text="5k"), headers=AUTH | INSTALL)
    final = next(e for e in events(resp) if e["event"] == "final")
    assert routes.rows[final["route_id"]]["request"]["install_id"] == INSTALL["X-Loop-Install"]


class PriorEngine(FakeEngine):
    """Records which install each engine call was made for (full review 6.3: the prior is the reviewer's only)."""

    def __init__(self):
        super().__init__()
        self.installs = []

    def for_install(self, install):
        self.installs.append(install)
        return self


def test_every_build_is_made_for_the_installs_own_engine():
    eng = PriorEngine()
    c, _ = client_for({"5k": IDEAL["P01"]}, engine=eng)
    c.post("/v1/runs", json=body("P01", text="5k"), headers=AUTH | INSTALL)
    c.post("/v1/runs", json=body("P01", text="5k"), headers=AUTH)  # no install id: the engine decides, as for a guest
    assert eng.installs == [INSTALL["X-Loop-Install"], None]


class AgainEngine(FakeEngine):
    def run_again(self, rc, past, route_id):
        self.calls.append((rc, past))
        entry = dict(ROUTE, id=f"{route_id}.1", geometry={"type": "LineString", "coordinates": [list(c) for c in past.coords]})
        return {"event": "final", "v": 1, "route_id": route_id, "routes": [entry], "route": None, "notes": [],
                "timing": {"run_again": past.id}}


def test_run_again_returns_the_same_line_read_for_now():
    eng = AgainEngine()
    c, routes, _ = stored_client(engine=eng)
    evs = post(c, body("P01", route_id="r_old00001.1", mode="exact"))
    assert [e["event"] for e in evs] == ["parsed", "final", "done"]
    assert evs[1]["routes"][0]["geometry"] == ROUTE["geometry"]  # exactly the stored line
    rc, past = eng.calls[0]
    assert rc.start_time == "06:40" and rc.start_date.isoformat() == "2026-11-03"  # the request's own clock: now
    assert evs[1]["route_id"] in routes.rows


def test_run_again_of_an_unknown_route_says_so():
    c, _, _ = stored_client(engine=AgainEngine())
    evs = post(c, body("P01", route_id="r_nothere.1", mode="exact"))
    assert [e.get("code") for e in evs] == ["route_not_found"]


@pytest.mark.parametrize("extra", [{"mode": "exact"}, {"mode": "exact", "route_id": "r_x.1", "text": "5k"}])
def test_run_again_takes_the_route_id_alone(extra):
    c, _, _ = stored_client(engine=AgainEngine())
    assert [e.get("code") for e in post(c, body("P01", **extra))] == ["bad_request"]


def test_the_apps_route_type_reaches_the_parse():
    eng = FakeEngine()
    c, _ = client_for({"3 mile loop": IDEAL["P05"]}, engine=eng)
    evs = post(c, body("P05", text="3 mile loop", shape="out_and_back"))
    assert evs[0]["constraints"]["shape"] == "out_and_back" and eng.calls[0][0].shape == "out_and_back"


def test_one_way_without_an_end_asks_where_to_end():
    c, _ = client_for({"5k": IDEAL["P01"]})
    evs = post(c, body("P01", text="5k", shape="one_way"))
    assert [e["event"] for e in evs] == ["parsed", "done"]
    assert evs[0]["question"]["about"] == "end" and evs[0]["question"]["text"] == "Where do you want to end?"


def test_a_stored_route_is_a_gpx_file_for_share():
    c, _, _ = stored_client()
    got = c.get("/v1/routes/r_old00001.1/gpx", headers=AUTH)
    assert got.status_code == 200 and got.headers["content-type"].startswith("application/gpx+xml")
    assert got.headers["content-disposition"] == 'attachment; filename="loop-r_old00001.1.gpx"'
    assert got.text.startswith("<?xml") and "<trkpt" in got.text
    assert c.get("/v1/routes/r_old00001/gpx", headers=AUTH).status_code == 200  # a build id: its first route


def test_gpx_for_an_unknown_route_is_404_and_needs_the_token():
    c, _, _ = stored_client()
    assert c.get("/v1/routes/r_nothere.1/gpx", headers=AUTH).status_code == 404
    assert c.get("/v1/routes/r_old00001.1/gpx").status_code == 401
    assert c.get("/v1/routes/r_old00001.9/gpx", headers=AUTH).status_code == 404  # a route the build didn't have
