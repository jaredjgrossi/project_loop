"""Answering a question (step 5, decision 029): the answer settles what the question asked, and the rules run again
on the same extraction, with no second Claude call. Also the chip-edit path, which rebuilds chips from constraints."""

import pytest

from api.parse import Context, answer_overrides, build, parsed_for_constraints, read_miles, resume
from api.tests.test_parse import CASES, CONTEXTS, IDEAL, FakePlaces, ext, mi, place
from evals.parse.fixtures import build_request


def asked(case_id: str, extraction: dict | None = None, request: dict | None = None):
    ctx = Context.from_request(request or build_request(CASES[case_id], CONTEXTS))
    out = build(extraction or IDEAL[case_id], ctx, FakePlaces())
    assert out["parsed"]["question"] is not None
    return out, ctx


def answer(out, ctx, option_id=None, text=None, extraction=None, case_id=None):
    settled = answer_overrides(out["trace"]["answer_map"], option_id, text, ctx)
    assert settled is not None
    return resume(extraction or IDEAL[case_id], ctx, FakePlaces(), {**out["trace"]["answers"], **settled})


def test_the_answer_map_stays_on_the_server():
    out, _ = asked("R06")
    assert "_answer" not in out["parsed"]["question"]
    assert set(out["trace"]["answer_map"]["options"]) == {o["id"] for o in out["parsed"]["question"]["options"]}


def test_tapping_a_distance_option_sets_it_as_said():
    out, ctx = asked("R06")
    after = answer(out, ctx, option_id="a", case_id="R06")
    p = after["parsed"]
    assert p["question"] is None
    assert p["constraints"]["distance_mi"] == 3
    chip = next(c for c in p["chips"] if c["field"] == "distance")
    assert chip["source"] == "said" and chip["text"] == "3 mi"
    assert after["parsed"]["parse_id"] != out["parsed"]["parse_id"]


@pytest.mark.parametrize("typed,miles", [("4", 4), ("4 miles", 4), ("about 6 mi", 6), ("8k", 4.97), ("5.5", 5.5)])
def test_a_typed_distance_is_read_by_code(typed, miles):
    out, ctx = asked("P11")  # "45 minutes": how many miles is that for you?
    after = answer(out, ctx, text=typed, case_id="P11")
    assert after["parsed"]["question"] is None
    assert after["parsed"]["constraints"]["distance_mi"] == miles


def test_a_typed_answer_code_cant_read_asks_the_same_question_again():
    out, ctx = asked("P11")
    after = answer(out, ctx, text="not sure, whatever feels good", case_id="P11")
    assert after["parsed"]["question"]["text"] == out["parsed"]["question"]["text"]


@pytest.mark.parametrize("text,miles", [("6", 6.0), ("6 mi", 6.0), ("10 km", 6.21), ("run 7 miles", 7.0),
                                        ("", None), ("six", None), ("3 or 4", None)])
def test_read_miles(text, miles):
    assert read_miles(text) == miles


def test_an_option_that_isnt_the_questions_is_refused():
    out, ctx = asked("R06")
    assert answer_overrides(out["trace"]["answer_map"], "z", None, ctx) is None


def test_picking_a_side_of_the_park_settles_the_start():
    out, ctx = asked("R02")  # "Which 86th St?" East side (5th Ave) / West side (Central Park West)
    assert [o["text"] for o in out["parsed"]["question"]["options"]] == ["East side (5th Ave)",
                                                                         "West side (Central Park West)"]
    after = answer(out, ctx, option_id="b", case_id="R02")
    start = after["trace"]["sources"]
    assert start["start_place"] == "said"
    # R02 asks nothing else: the end sets the length. Its via waits on step 8, which the server says.
    assert after["parsed"]["question"] is None
    assert after["parsed"]["constraints"]["start_place"]["lat"] == pytest.approx(40.7854)


def test_a_typed_place_replaces_the_one_that_was_asked_about():
    out, ctx = asked("P19")  # Hoboken PATH: outside NYC, where should it start?
    after = answer(out, ctx, text="Penn Station", case_id="P19")
    sp = after["parsed"]["constraints"]["start_place"]
    assert after["parsed"]["question"] is None and sp["name"] == "Penn Station"


def test_picking_a_park():
    from api.parse import resume
    from api.tests.test_parse import CloseParks
    ctx = Context.from_request(build_request(CASES["P20"], CONTEXTS))
    out = build(IDEAL["P20"], ctx, CloseParks())  # two parks about as far: which park?
    settled = answer_overrides(out["trace"]["answer_map"], "a", None, ctx)
    after = resume(IDEAL["P20"], ctx, CloseParks(), {**out["trace"]["answers"], **settled})
    assert after["parsed"]["constraints"]["start_place"]["name"] == "East River Esplanade"


def test_the_typo_question_takes_its_option():
    out, ctx = asked("P47")  # 100 mi: did you mean 10?
    after = answer(out, ctx, option_id="a", case_id="P47")
    assert after["parsed"]["constraints"]["distance_mi"] == 10


def test_an_address_in_several_boroughs_takes_the_borough_tapped_or_typed():
    req = build_request(CASES["R06"], CONTEXTS)  # the new runner at Union Square
    req["client"]["location"] = None
    e = ext(distance=mi(3), start=place("address", "120 Broadway"))
    out, ctx = asked("R06", extraction=e, request=req)
    q = out["parsed"]["question"]
    assert [o["text"] for o in q["options"]] == ["Manhattan", "Brooklyn", "Queens"]
    tapped = answer(out, ctx, option_id="b", extraction=e)
    assert tapped["parsed"]["constraints"]["start_place"]["borough"] == "Brooklyn"
    typed = answer(out, ctx, text="queens", extraction=e)
    assert typed["parsed"]["constraints"]["start_place"]["borough"] == "Queens"


def test_answers_accumulate_across_questions():
    req = build_request(CASES["R06"], CONTEXTS)
    req["client"]["location"] = None
    e = ext(start=place("address", "120 Broadway"))  # no distance, no usual distance: two questions
    out, ctx = asked("R06", extraction=e, request=req)
    assert out["parsed"]["question"]["about"] == "start"
    second = answer(out, ctx, option_id="a", extraction=e)
    assert second["parsed"]["question"]["about"] == "distance"
    third = answer(second, ctx, option_id="b", extraction=e)
    c = third["parsed"]["constraints"]
    assert third["parsed"]["question"] is None and c["distance_mi"] == 5 and c["start_place"]["borough"] == "Manhattan"


def test_longer_is_the_past_distance_plus_the_answer():  # step 11
    out, ctx = asked("H02")  # "my usual, but longer": how much longer?
    after = answer(out, ctx, option_id="a", case_id="H02")
    assert after["parsed"]["question"] is None
    c = after["parsed"]["constraints"]
    assert c["reuse_route_id"] == "rt_a" and c["distance_mi"] == 4.0  # rt_a is 3.0 mi, plus 1


def _option_for(out, route_id):
    opts = out["trace"]["answer_map"]["options"]
    return next(k for k, v in opts.items() if v.get("reuse") == route_id)


def test_the_ferry_part_is_matched_along_the_routes_it_could_mean():  # H04, step 11 (decision 038)
    out, ctx = asked("H04")  # last week: rt_a (East River esplanade, past the E 34th St landing) or rt_c (Gramercy)
    (avoid,) = out["parsed"]["constraints"]["avoid_places"]
    assert avoid["name"] == "E 34th St ferry landing" and avoid["place"]["lat"] == 40.7439
    chip = next(c for c in out["parsed"]["chips"] if c["id"] == "c_avoid_1") if out["parsed"]["chips"] else None
    assert chip is None or chip["span"]["text"] == "the ferry part"
    after = answer(out, ctx, option_id=_option_for(out, "rt_a"), case_id="H04")
    assert after["parsed"]["question"] is None
    assert [a["name"] for a in after["parsed"]["constraints"]["avoid_places"]] == ["E 34th St ferry landing"]


def test_a_route_with_no_ferry_keeps_the_words_and_the_engine_says_it_cant():
    out, ctx = asked("H04")
    after = answer(out, ctx, option_id=_option_for(out, "rt_c"), case_id="H04")  # the Gramercy rectangle
    assert after["parsed"]["constraints"]["avoid_places"] == [{"name": "ferry"}]  # "area" is the default


@pytest.mark.parametrize("case_id", ["P36", "P38", "R04", "P10", "P34", "P24", "P35", "R01"])
def test_chips_rebuilt_from_constraints_match_the_parse(case_id):
    """A chip edit sends constraints back; with no edit, the chips come back the same, sources included."""
    ctx = Context.from_request(build_request(CASES[case_id], CONTEXTS))
    out = build(IDEAL[case_id], ctx, FakePlaces())
    again = parsed_for_constraints(out["parsed"]["constraints"], ctx, None)
    strip = [{k: c[k] for k in ("id", "field", "text", "source")} for c in out["parsed"]["chips"]]
    assert [{k: c[k] for k in ("id", "field", "text", "source")} for c in again["chips"]] == strip
    assert again["notes"] == out["parsed"]["notes"] and again["question"] is None


def test_an_edited_chip_reads_as_said():
    ctx = Context.from_request(build_request(CASES["P36"], CONTEXTS))
    c = build(IDEAL["P36"], ctx, FakePlaces())["parsed"]["constraints"] | {"distance_mi": 8}
    again = parsed_for_constraints(c, ctx, None)
    assert next(x for x in again["chips"] if x["field"] == "distance")["text"] == "8 mi"


def test_a_utc_clock_is_read_in_the_runners_time_zone():
    """Swift's ISO8601DateFormatter sends UTC ("Z") by default; 11:40Z on Nov 3 is 06:40 in New York."""
    req = build_request(CASES["P36"], CONTEXTS)
    local = Context.from_request(req).now
    req["client"] = req["client"] | {"now": "2026-11-03T11:40:00Z"}
    assert Context.from_request(req).now == local


@pytest.mark.parametrize("case_id,reach", [("P36", 5070), ("P38", 2630), ("P10", 3220), ("R01", None), ("R06", None)])
def test_parsed_says_how_far_the_run_can_reach(case_id, reach):
    """reach_m: half the longest the run may be (the distance plus its tolerance), in meters, to 10 m. 6 mi at 5%:
    6 x 1.05 / 2 x 1609 = 5069 m. 5 km is 3.11 mi: 2628 m. "3-4 miles" reaches 4 mi / 2: 3219 m. Null with no
    distance yet (R06 asks) or when the run ends somewhere else (R01)."""
    ctx = Context.from_request(build_request(CASES[case_id], CONTEXTS))
    out = build(IDEAL[case_id], ctx, FakePlaces())
    assert out["parsed"]["reach_m"] == reach
    if reach is not None:
        again = parsed_for_constraints(out["parsed"]["constraints"], ctx, None)
        assert again["reach_m"] == reach
