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


def test_every_phase3_field_builds_with_no_cant_line():
    assert before_build(rc(reuse_route_id="rt_a"), zones=[]) == ([], False)  # step 11 rebuilds past routes
    via = rc(via_places=[{"kind": "place", "name": "McCarren Park", "borough": "Brooklyn", "lat": 40.7204,
                          "lon": -73.9512}])
    assert before_build(via, zones=[]) == ([], False)  # step 9 builds it
    a_to_b = rc(end_place={"kind": "place", "name": "McCarren Park", "borough": "Brooklyn", "lat": 40.7204,
                           "lon": -73.9512})
    assert before_build(a_to_b, zones=[]) == ([], False)  # step 8 builds it
    assert before_build(rc(hills="avoid"), zones=[]) == ([], False)  # step 10 scores hills
    assert before_build(rc(planned={"use_my_location": True, "distance_mi": 3, "start_date": "2026-11-12"}),
                        zones=[]) == ([], False)  # step 11 builds the planned run too
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
    assert [r["label"] for r in sent[1]["routes"]] == ["Loop", "Loop"]  # named from the kind (decision 044)
    assert final["event"] == "final" and final["pool_size"] == 17 and final["notes"] == []
    assert final["pool"] == {"candidates": 20, "best_of": 17}  # as the fixture's pool, so the app reads it unchanged
    assert [r["label"] for r in final["routes"]] == ["Loop", "Loop"]
    props = final["route"]["features"][0]["properties"]
    assert props["rank"] == 1 and props["label"] == "Loop" and props["plan"] == "first" and props["name"] == "Loop"
    assert "summary" in props and "request" in props


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
    assert final["route"]["features"][0]["properties"]["label"] == "One way, the shortest way"
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


# ---- past routes and the ferry part (step 11, decision 038) --------------------------------------------------------

import math  # noqa: E402

from api.geometry import covered_share  # noqa: E402
from api.past_routes import PastRoute  # noqa: E402

SQUARE_M = 600  # a past loop: a 600 m square from Kips Bay, east, north, west, south (counterclockwise)
KX = 111_320 * math.cos(math.radians(KIPS_POINT[0]))


def square_route(side=SQUARE_M):
    lat, lon = KIPS_POINT
    pts = [(0, 0), (side, 0), (side, side), (0, side), (0, 0)]
    return PastRoute("r_old.1", tuple((lon + e / KX, lat + n / M_LAT) for e, n in pts))


def past_engine(past=square_route(), **kw) -> Engine:
    from api.generate import generate_loops
    return engine(generate_loops, routers_fn=lambda zones, lights, closures: (straight_route, None, area_route),
                  past_route_fn=lambda rid: past if rid == past.id else None, **kw)


def test_a_past_route_is_rebuilt_from_its_own_start():
    final = past_engine().build(rc(distance_mi=None, reuse_route_id="r_old.1"), Start(40.75, -73.99, "here"),
                                lambda e: None, "r_p")
    route = final["routes"][0]["geometry"]["coordinates"]
    line = {"type": "LineString", "coordinates": [list(c) for c in square_route().coords]}
    assert covered_share(route, line, 30) >= 0.9
    assert abs(route[0][1] - KIPS_POINT[0]) < 1e-4 and abs(route[0][0] - KIPS_POINT[1]) < 1e-4
    assert abs(final["routes"][0]["distance"]["value"] - 4 * SQUARE_M / 1609.344) < 0.05


def test_the_other_direction_runs_it_backwards():
    fwd = past_engine().build(rc(distance_mi=None, reuse_route_id="r_old.1"), Start(*KIPS_POINT, "x"),
                              lambda e: None, "r_f")["routes"][0]["geometry"]["coordinates"]
    back = past_engine().build(rc(distance_mi=None, reuse_route_id="r_old.1", reverse=True), Start(*KIPS_POINT, "x"),
                               lambda e: None, "r_b")["routes"][0]["geometry"]["coordinates"]
    def first_step(line):  # the first point that isn't the start (the router repeats waypoints)
        return next(c for c in line if abs(c[0] - line[0][0]) + abs(c[1] - line[0][1]) > 1e-6)
    f, b = first_step(fwd), first_step(back)
    assert f[0] > fwd[0][0] and abs(f[1] - fwd[0][1]) < 1e-6  # east first
    assert b[1] > back[0][1] and abs(b[0] - back[0][0]) < 1e-6  # north first


def test_longer_keeps_the_route_and_adds_distance():
    final = past_engine().build(rc(distance_mi=2.5, reuse_route_id="r_old.1"), Start(*KIPS_POINT, "x"),
                                lambda e: None, "r_l")
    line = {"type": "LineString", "coordinates": [list(c) for c in square_route().coords]}
    assert final["routes"] and final["notes"] == []
    for r in final["routes"]:
        assert covered_share(r["geometry"]["coordinates"], line, 30) >= 0.9
        assert abs(r["distance"]["value"] - 2.5) <= 0.2


def test_a_past_route_with_no_line_on_file_is_said():
    final = past_engine().build(rc(distance_mi=None, reuse_route_id="r_gone.1"), Start(*KIPS_POINT, "x"),
                                lambda e: None, "r_g")
    assert final["routes"] == [] and final["notes"][0]["key"] == "past_route_not_found"


def test_an_avoid_with_coordinates_is_a_no_go_circle():
    from api.engine import PIER_RADIUS_M, place_zone
    from api.constraints import AvoidPlace
    pier = AvoidPlace(name="E 34th St ferry landing", how="area",
                      place={"kind": "place", "name": "E 34th St ferry landing", "borough": "Manhattan",
                             "lat": 40.7439, "lon": -73.9707, "source": "NYC Ferry GTFS", "trust": "listed"})
    z = place_zone(pier, 1)
    ring = z.rings[0]
    assert z.id == "avoid_1" and len(ring) == 17 and ring[0] == ring[-1]
    kx = 111_320 * math.cos(math.radians(40.7439))
    assert all(abs(math.hypot((x + 73.9707) * kx, (y - 40.7439) * M_LAT) - PIER_RADIUS_M) < 1 for x, y in ring)
    lines, blocked = before_build(rc(avoid_places=[pier.model_dump()]), zones=[])
    assert lines == [] and not blocked  # not "can't avoid": it has coordinates


# ---- shape edits from the pool; ends in a neighborhood (phone test round 2, decision 042) ---------------------------

def pool_engine(**kw) -> Engine:
    from api.generate import generate_loops
    return engine(generate_loops, routers_fn=lambda zones, lights, closures: (straight_route, None, area_route), **kw)


def test_a_shape_edit_takes_the_best_of_the_new_kind_from_the_pool():
    e = pool_engine()
    first = e.build(rc(distance_mi=3.0), Start(*KIPS_POINT, "x"), lambda ev: None, "r_any")
    assert {r["kind"] for r in first["routes"]} >= {"out_and_back"}
    sent = []
    again = e.from_pool(rc(distance_mi=3.0, shape="out_and_back"), Start(*KIPS_POINT, "x"), "r_any", sent.append,
                        "r_edit")
    assert again is not None and again["timing"] == {"from_pool": "r_any"}
    assert {r["kind"] for r in again["routes"]} == {"out_and_back"} and again["routes"][0]["id"] == "r_edit.1"
    assert [ev["event"] for ev in sent] == ["top3"]
    assert again["route"] is not None


def test_a_shape_edit_with_no_route_of_that_kind_says_rebuild():
    e = pool_engine()
    e.build(rc(distance_mi=3.0, shape="loop"), Start(*KIPS_POINT, "x"), lambda ev: None, "r_loops")
    assert e.from_pool(rc(distance_mi=3.0, shape="out_and_back"), Start(*KIPS_POINT, "x"), "r_loops",
                       lambda ev: None, "r_e") is None  # a loop-only build has no out-and-backs: build again
    assert e.from_pool(rc(distance_mi=3.0, shape="loop"), Start(*KIPS_POINT, "x"), "r_gone", lambda ev: None,
                       "r_e") is None


def test_an_end_in_a_neighborhood_finishes_where_the_way_in_is_deep_enough():
    from api.engine import area_end
    from api.tests.test_via import square
    hood_point = (EAST[0], EAST[1])
    whole = square(hood_point, 600)  # a 1.2 km square area around the neighborhood's point
    inner = square(hood_point, 300)  # ... and 300 m inside its edge
    end = area_end(KIPS_POINT, hood_point, (whole, inner), straight_route)
    # on the straight way in from the west, the first point 300 m inside is the inner square's west edge
    assert end != hood_point
    assert abs(end[0] - hood_point[0]) < 1e-3
    assert end[1] < hood_point[1]
    inside = (hood_point[0], hood_point[1] - 0.001)
    assert area_end(inside, hood_point, (whole, inner), straight_route) == hood_point  # starts inside: its point


def test_an_a_to_b_run_to_a_neighborhood_uses_its_area():
    from api.tests.test_via import square
    hood = {"kind": "place", "name": "Williamsburg", "borough": "Brooklyn", "lat": EAST[0], "lon": EAST[1],
            "area": "neighborhood"}
    final = a_to_b_engine(area_fn=lambda p: (square(p, 600), square(p, 300))).build(
        rc(distance_mi=None, end_place=hood), Start(*KIPS_POINT, "x"), lambda e: None, "r_w", end=EAST)
    last = final["routes"][0]["geometry"]["coordinates"][-1]
    assert last[0] < EAST[1] - 0.001  # finished on the way in, short of the neighborhood's point


def test_run_again_keeps_the_stored_line_exactly():  # decision 043
    past = square_route()
    e = past_engine()
    final = e.run_again(rc(distance_mi=1.5, start_time="07:10", start_date="2026-11-11"), past, "r_again")
    (r,) = final["routes"]
    assert r["geometry"]["coordinates"] == [list(c) for c in past.coords]  # no routing: the same line
    assert r["id"] == "r_again.1" and final["timing"] == {"run_again": past.id}
    assert final["route"] is not None and abs(r["distance"]["value"] - 4 * SQUARE_M / 1609.344) < 0.01


# ---- loop as a hard rule, and honest names (decision 044) ----------------------------------------------------------

def test_loop_with_no_loop_shows_the_best_other_kind_and_says_so():
    import dataclasses
    from collections import Counter
    from api.generate import GenerationResult
    out_and_back = dataclasses.replace(candidate(label="out-and-back on Riverside Walk, heading 19 degrees"),
                                       kind="out_and_back")

    def no_loops(lat, lon, miles, grid, route_fn, round_trip_fn, top_n=3, **kw):
        return GenerationResult(candidates=[], within_tolerance=False, grid=grid, generated=20,
                                rejected=Counter({"unwanted_out_and_back": 1}), fallback=[out_and_back])
    final = engine(no_loops).build(rc(shape="loop"), Start(*KIPS_POINT, "x"), lambda e: None, "r_nl")
    assert [r["kind"] for r in final["routes"]] == ["out_and_back"]
    assert final["routes"][0]["label"] == "Out-and-back on Riverside Walk"
    assert final["notes"][0]["key"] == "no_good_loop"
    assert final["notes"][0]["text"] == "No good loop from here; showing the best out-and-back"


def test_with_loops_the_fallback_is_never_used():
    from collections import Counter
    from api.generate import GenerationResult

    def loops(lat, lon, miles, grid, route_fn, round_trip_fn, top_n=3, **kw):
        return GenerationResult(candidates=[candidate()], within_tolerance=True, grid=grid, generated=20,
                                rejected=Counter(), fallback=[candidate(label="other")])
    final = engine(loops).build(rc(shape="loop"), Start(*KIPS_POINT, "x"), lambda e: None, "r_l")
    assert final["notes"] == [] and final["routes"][0]["label"] == "Loop on the street grid"


def test_a_shape_edit_after_a_via_build_reads_candidates_not_vias():  # full review 7.2: `passed` was rebound
    from api.generate import Candidate
    eng = via_engine()
    start = Start(*KIPS_POINT, "x")
    eng.build(rc(distance_mi=5.0, via_places=[via_ref(FAR_NORTH)], shape="any"), start, lambda e: None, "r_v3")
    pool = eng.pools["r_v3"]
    assert pool and all(isinstance(c, Candidate) for c in pool)  # never Via objects
    final = eng.from_pool(rc(distance_mi=5.0, via_places=[via_ref(FAR_NORTH)], shape="loop"), start, "r_v3",
                          lambda e: None, "r_v4")  # the edit the review saw fail with engine_unavailable
    assert final is not None and final["routes"] and all(r["kind"] == "loop" for r in final["routes"])


def test_the_via_features_never_see_candidates():  # the same rebinding fed candidates to features_on_vias
    from api.generate import Candidate
    seen = []

    def spy_source(lat, lon, radius):
        return []

    def features_on_vias_spy(source, vias):
        seen.append(vias)  # a reference to the live list: read later, on a worker thread
        return lambda lat, lon, radius_m: []

    import api.engine as engine_module
    original = engine_module.features_on_vias
    engine_module.features_on_vias = features_on_vias_spy
    try:
        eng = via_engine(feature_anchor_fn=[spy_source])
        eng.build(rc(distance_mi=5.0, via_places=[via_ref(FAR_NORTH)]), Start(*KIPS_POINT, "x"), lambda e: None, "r_v5")
    finally:
        engine_module.features_on_vias = original
    assert seen and all(isinstance(v, Via) for v in seen[0]) and not any(isinstance(v, Candidate) for v in seen[0])


# ---- amenities: said, so never silently dropped (full review 4.2, Q7) ------------------------------------------------


def test_a_restroom_stop_gets_a_cant_line_and_the_route_is_still_built():
    lines, blocked = before_build(rc(amenities=[{"kind": "restroom", "at_mile": 3, "within_mi": 0.5}]), zones=[])
    assert [x["key"] for x in lines] == ["amenities"] and lines[0]["gap"] == "later"
    assert "restroom" in lines[0]["text"].lower() and "water" in lines[0]["text"].lower()
    assert not blocked  # an honest line, not a refusal: the run is built without the stop


def test_a_water_stop_gets_the_same_line_once_however_many_stops():
    two = [{"kind": "water", "at_mile": 1, "within_mi": 0.5}, {"kind": "restroom", "at_mile": 4, "within_mi": 0.5}]
    lines, _ = before_build(rc(amenities=two), zones=[])
    assert [x["key"] for x in lines] == ["amenities"]


def test_no_amenity_no_line():
    assert before_build(rc(), zones=[]) == ([], False)


def test_a_lap_starts_where_the_way_in_meets_the_ring():  # full review 4.2, Q6: the Reservoir from the east
    corner = (LAP_AT[0] - 300 / M_LAT, LAP_AT[1] - 300 / KX)  # the ring's south-west corner: the only way in
    calls = []

    def way_in_through_the_corner(points, custom_model=None):
        calls.append(list(points))
        if len(points) > 3:  # the start, the lap, the start: the way in goes through the corner first
            points = [points[0], corner, *points[1:]]
        return straight_route(points)

    eng = engine(generate_loops_for_tests(), routers_fn=lambda z, l, c: (way_in_through_the_corner, None, area_route),
                 vias_fn=lambda refs: [lap_via(LAP_AT, 300, "Test Loop") for _ in refs])
    final = eng.build(rc(distance_mi=None, via_places=[lap_ref()]), Start(*KIPS_POINT, "x"), lambda e: None, "r_l3")
    assert final["routes"]
    last_tour = [c for c in calls if len(c) > 6][-1]  # the shortest way, routed again with the entry set
    first_lap_point = last_tour[1]
    assert abs(first_lap_point[0] - corner[0]) * M_LAT < 5 and abs(first_lap_point[1] - corner[1]) * KX < 5


def generate_loops_for_tests():
    from api.generate import generate_loops
    return generate_loops
