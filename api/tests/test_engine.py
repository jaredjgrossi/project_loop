"""The engine behind the API (step 5, decision 029): starts, can't-do lines, and the streamed payloads."""

import threading
from collections import Counter

import pytest

from api.constraints import RunConstraints
from api.copy import render
from api.engine import BadStart, Engine, EngineUnavailable, Start, before_build, distance_notes, entry, start_for
from api.generate import GenerationResult
from api.nogo import NoGoZone
from api.tests.test_make_loop import GRID, candidate

KIPS = {"lat": 40.7438, "lon": -73.9799}


def rc(**kw) -> RunConstraints:
    base = {"use_my_location": True, "distance_mi": 4.0}
    return RunConstraints(**(base | kw))


def test_the_start_comes_from_the_phone_a_place_or_the_profile():
    assert start_for(rc(), KIPS, {}) == Start(40.7438, -73.9799, render("request.start.my_location"))
    with pytest.raises(BadStart):
        start_for(rc(), None, {})
    place = {"kind": "place", "name": "Penn Station", "borough": "Manhattan", "lat": 40.7502, "lon": -73.9928}
    s = start_for(rc(use_my_location=False, start_place=place), None, {})
    assert (s.lat, s.lon) == (40.7502, -73.9928) and "Penn Station" in s.label
    saved = rc(use_my_location=False, start_place={"kind": "saved", "id": "home"})
    s = start_for(saved, None, {"home": {"id": "home", "label": "Home", "lat": 40.7438, "lon": -73.9799}})
    assert (s.lat, s.lon) == (40.7438, -73.9799)
    with pytest.raises(BadStart):
        start_for(saved, None, {})


def test_what_the_engine_cant_build_yet_is_said_and_blocks_only_when_it_must():
    lines, blocked = before_build(rc(reuse_route_id="rt_a"), zones=[])
    assert [x["key"] for x in lines] == ["reuse_route_id"] and blocked
    via = rc(via_places=[{"kind": "place", "name": "McCarren Park", "borough": "Brooklyn", "lat": 40.7204,
                          "lon": -73.9512}])
    assert before_build(via, zones=[]) == ([], False)  # step 9 builds it
    a_to_b = rc(end_place={"kind": "place", "name": "McCarren Park", "borough": "Brooklyn", "lat": 40.7204,
                           "lon": -73.9512})
    assert before_build(a_to_b, zones=[]) == ([], False)  # step 8 builds it
    assert before_build(rc(hills="avoid"), zones=[]) == ([], False)  # step 10 scores hills
    lines, blocked = before_build(rc(planned={"use_my_location": True, "distance_mi": 3,
                                              "start_date": "2026-11-12"}), zones=[])
    assert [x["key"] for x in lines] == ["planned"] and not blocked
    assert before_build(rc(avoid_places=[{"name": "1st Ave", "how": "along"}]), zones=[]) == ([], False)  # step 8b
    assert before_build(rc(), zones=[]) == ([], False)


def test_an_avoid_that_isnt_on_the_no_go_list_is_named():
    zone = NoGoZone(id="times_square", name="Times Square", aliases=("times sq",), default=False, reason="crowds",
                    source="test", rings=[])
    lines, blocked = before_build(rc(avoid_places=["Times Square", "Grand Central"]), zones=[zone])
    assert [x["text"] for x in lines] == ["Can't avoid Grand Central yet: it isn't on the list of places Loop can avoid"]
    assert not blocked


def test_a_miss_says_the_nearest_route_and_how_far_off():
    notes = distance_notes(rc(), [candidate(miles_actual=3.0)], within=False)
    assert notes[0]["key"] == "distance_off" and "3.0 mi, 25% short" in notes[0]["text"]
    assert distance_notes(rc(), [candidate()], within=True) == []
    assert distance_notes(rc(), [], within=False)[0]["key"] == "no_route"


def test_an_entry_is_the_fixtures_top3_shape():
    e = entry(2, candidate(label="second"))
    assert set(e) == {"id", "rank", "kind", "label", "score", "distance", "geometry"}
    assert e["rank"] == 2 and e["distance"]["unit"] == "mi" and e["distance"]["status"] == "measured"
    assert e["geometry"]["type"] == "LineString"


def fake_generate(cands, threads=True):
    """Calls on_top3 from worker threads, as the real generator does, then returns the result."""
    def generate_fn(lat, lon, miles, grid, route_fn, round_trip_fn, top_n=3, on_top3=None, **kw):
        def emit(event, top, elapsed):
            on_top3({"event": event, "elapsed_s": elapsed, "provisional": event != "top3", "candidates": top})
        steps = [("top3", cands[:1], 0.4), ("top3", cands[:2], 0.6), ("provisional", cands[:2], 0.9)]
        for event, top, elapsed in steps:
            if threads:
                t = threading.Thread(target=emit, args=(event, top, elapsed))
                t.start()
                t.join()
            else:
                emit(event, top, elapsed)
        on_top3({"event": "final", "elapsed_s": 1.2, "provisional": True, "candidates": cands[:top_n]})
        return GenerationResult(candidates=cands[:top_n], within_tolerance=True, grid=grid, generated=20,
                                rejected=Counter(), best_of=17)
    return generate_fn


def engine(generate_fn, **kw) -> Engine:
    base = dict(generate_fn=generate_fn, grid_fn=lambda lat, lon: GRID, closures_fn=None, stretch_fn=None,
                anchor_fn=None, feature_anchor_fn=[], ready_fn=lambda: True,
                context_for_fn=lambda *a, **kw: None)  # no Postgres in unit tests (decision 019): context not scored
    return Engine(**(base | kw))


def test_build_streams_top3_and_provisional_then_returns_final():
    sent = []
    cands = [candidate(label="first", score=90), candidate(label="second", score=80)]
    final = engine(fake_generate(cands)).build(rc(), Start(40.7438, -73.9799, "My location"), sent.append, "r_1")
    assert [e["event"] for e in sent] == ["top3", "top3", "provisional"]
    assert all(e["route_id"] == "r_1" and e["v"] == 1 for e in sent)
    assert [r["label"] for r in sent[1]["routes"]] == ["first", "second"]
    assert final["event"] == "final" and final["pool_size"] == 17 and final["notes"] == []
    assert final["pool"] == {"candidates": 20, "best_of": 17}  # as the fixture's pool, so the app reads it unchanged
    assert [r["label"] for r in final["routes"]] == ["first", "second"]
    props = final["route"]["features"][0]["properties"]
    assert props["rank"] == 1 and props["label"] == "first" and "summary" in props and "request" in props


def test_the_engine_down_is_engine_unavailable():
    with pytest.raises(EngineUnavailable):
        engine(fake_generate([]), ready_fn=lambda: False).build(rc(), Start(40.7, -73.9, "x"), print, "r_1")


def test_a_route_keeps_its_id_across_events():
    sent = []
    first, second = candidate(label="first", score=90), candidate(label="second", score=80)
    final = engine(fake_generate([first, second])).build(rc(), Start(40.7, -73.9, "x"), sent.append, "r_9")
    ids = [[r["id"] for r in e["routes"]] for e in sent] + [[r["id"] for r in final["routes"]]]
    assert ids == [["r_9.1"], ["r_9.1", "r_9.2"], ["r_9.1", "r_9.2"], ["r_9.1", "r_9.2"]]


def fake_generate_with_candidates(cands):
    """As fake_generate, and each candidate also arrives through on_candidate, from a worker thread."""
    inner = fake_generate(cands)

    def generate_fn(lat, lon, miles, grid, route_fn, round_trip_fn, top_n=3, on_candidate=None, **kw):
        for i, c in enumerate(cands):
            t = threading.Thread(target=on_candidate, args=(c, 0.1 * (i + 1)))
            t.start()
            t.join()
        return inner(lat, lon, miles, grid, route_fn, round_trip_fn, top_n=top_n, **kw)

    return generate_fn


def test_each_candidate_streams_as_a_light_outline_with_its_route_id():
    sent = []
    cands = [candidate(label="first", score=90), candidate(label="second", score=80)]
    engine(fake_generate_with_candidates(cands)).build(rc(), Start(40.7, -73.9, "x"), sent.append, "r_5")
    outs = [e for e in sent if e["event"] == "candidates"]
    assert [e["candidates"][0]["id"] for e in outs] == ["r_5.1", "r_5.2"]
    one = outs[0]
    assert set(one) == {"event", "v", "route_id", "elapsed_s", "candidates"} and one["route_id"] == "r_5"
    c = one["candidates"][0]
    assert set(c) == {"id", "kind", "points"} and c["kind"] == cands[0].kind
    assert c["points"][0] == [round(x, 5) for x in cands[0].route.coordinates[0][:2]]
    top3 = next(e for e in sent if e["event"] == "top3")
    assert top3["routes"][0]["id"] == "r_5.1"  # the same id when it reaches the top 3



# ---- A to B (step 8) -----------------------------------------------------------------------------------------------

from api.engine import EngineQuestion  # noqa: E402
from api.tests.test_a_to_b import EAST, area_route, straight_route  # noqa: E402
from api.tests.test_a_to_b import KIPS as KIPS_POINT  # noqa: E402


def a_to_b_engine(**kw) -> Engine:
    return engine(fake_generate([]), routers_fn=lambda zones, lights, closures: (straight_route, None, area_route), **kw)


def test_a_distance_shorter_than_the_shortest_way_asks_before_anything_streams():
    sent = []
    with pytest.raises(EngineQuestion) as asked:
        a_to_b_engine().build(rc(distance_mi=1.0), Start(*KIPS_POINT, "x"), sent.append, "r_1", end=EAST)
    q = asked.value.question
    assert sent == [] and q["from"] == "engine" and q["options"][0]["text"] == "2.1 mi"
    assert asked.value.answer_map["options"]["a"] == {"distance": 2.1}


def test_an_a_to_b_run_with_no_distance_is_the_shortest_way():
    sent = []
    final = a_to_b_engine().build(rc(distance_mi=None, end_place={"kind": "place", "name": "East", "borough": "Manhattan",
                                                                  "lat": EAST[0], "lon": EAST[1]}),
                                  Start(*KIPS_POINT, "x"), sent.append, "r_2", end=EAST)
    assert final["routes"][0]["kind"] == "a_to_b" and final["notes"] == []
    assert final["route"]["features"][0]["properties"]["label"] == "the shortest way"
    assert any(e["event"] == "top3" for e in sent)


def test_an_a_to_b_run_at_a_longer_distance_detours_to_fit():
    final = a_to_b_engine().build(rc(distance_mi=4.0), Start(*KIPS_POINT, "x"), lambda e: None, "r_3", end=EAST)
    assert final["routes"] and all(abs(r["distance"]["value"] - 4.0) <= 0.2 for r in final["routes"])
    assert final["notes"] == []



# ---- via places (step 9) -------------------------------------------------------------------------------------------

from api.engine import via_far_question  # noqa: E402
from api.via import Via  # noqa: E402
from api.tests.test_a_to_b import M_LAT  # noqa: E402

FAR_NORTH = (KIPS_POINT[0] + 3000 / M_LAT, KIPS_POINT[1])


def via_ref(at, name="Test Station"):
    return {"kind": "place", "name": name, "borough": "Manhattan", "lat": at[0], "lon": at[1]}


def via_engine(**kw) -> Engine:
    from api.generate import generate_loops
    return engine(generate_loops, routers_fn=lambda zones, lights, closures: (straight_route, None, area_route),
                  vias_fn=lambda refs: [Via(r.lat, r.lon, r.name, {"type": "Point", "coordinates": [r.lon, r.lat]})
                                        for r in refs], **kw)


def test_a_via_too_far_for_the_distance_asks_with_its_name():
    with pytest.raises(EngineQuestion) as asked:
        via_engine().build(rc(distance_mi=2.0, via_places=[via_ref(FAR_NORTH)]), Start(*KIPS_POINT, "x"),
                           lambda e: None, "r_v")
    q = asked.value.question
    assert q["text"].startswith("Going through Test Station takes at least 3.8 mi")
    assert asked.value.answer_map["options"]["a"] == {"distance": 3.8}


def test_a_loop_through_a_via_passes_it():
    final = via_engine().build(rc(distance_mi=5.0, via_places=[via_ref(FAR_NORTH)]), Start(*KIPS_POINT, "x"),
                               lambda e: None, "r_v2")
    assert final["routes"] and final["notes"] == []
    for r in final["routes"]:
        lat_min = min(abs(lat - FAR_NORTH[0]) * M_LAT for lon, lat in r["geometry"]["coordinates"])
        assert lat_min < 150


def test_via_far_question_names_two_places():
    two = [Via(0, 0, "A", {}), Via(0, 0, "B", {})]
    assert via_far_question(two, 6000).question["text"].startswith("Going through A and B takes at least 3.8 mi")


# ---- around: a lap (decision 035) ----------------------------------------------------------------------------------

from api.tests.test_via import lap_via  # noqa: E402

LAP_AT = (KIPS_POINT[0] + 1500 / M_LAT, KIPS_POINT[1])


def lap_engine(**kw) -> Engine:
    from api.generate import generate_loops
    return engine(generate_loops, routers_fn=lambda zones, lights, closures: (straight_route, None, area_route),
                  vias_fn=lambda refs: [lap_via(LAP_AT, 300, "Test Loop") for _ in refs], **kw)


def lap_ref():
    return via_ref(LAP_AT, "Test Park") | {"mode": "around"}


def test_a_lap_too_long_for_the_distance_asks():
    with pytest.raises(EngineQuestion) as asked:
        lap_engine().build(rc(distance_mi=2.0, via_places=[lap_ref()]), Start(*KIPS_POINT, "x"), lambda e: None, "r_l")
    q = asked.value.question
    assert q["text"].startswith("A lap of Test Loop and the way there takes at least")
    assert asked.value.answer_map["options"]["a"]["distance"] > 2.0


def test_a_lap_with_no_distance_is_the_lap_and_the_way_there():
    final = lap_engine().build(rc(distance_mi=None, via_places=[lap_ref()]), Start(*KIPS_POINT, "x"),
                               lambda e: None, "r_l2")
    assert final["routes"] and final["notes"] == []
    d = final["routes"][0]["distance"]["value"]
    assert d >= (2 * 1200 + 2400) / 1609.344 * 0.95  # there (1.2 km), a 2.4 km lap, back
