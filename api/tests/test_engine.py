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
    lines, blocked = before_build(rc(end_place={"kind": "place", "name": "McCarren Park", "borough": "Brooklyn",
                                                "lat": 40.7204, "lon": -73.9512}), zones=[])
    assert [x["key"] for x in lines] == ["end_place"] and blocked
    lines, blocked = before_build(rc(hills="avoid"), zones=[])
    assert [x["key"] for x in lines] == ["hills"] and not blocked
    lines, blocked = before_build(rc(avoid_places=[{"name": "1st Ave", "how": "along"}]), zones=[])
    assert [x["key"] for x in lines] == ["avoid_along"] and blocked
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
                anchor_fn=None, feature_anchor_fn=[], ready_fn=lambda: True)
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
