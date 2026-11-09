"""The parser's deterministic half (decision 028): given the extraction Claude should return for an eval case, does
build() pass that case? No Claude call, no database: places come from a small fake with public stand-ins.
The model's half is measured by `make eval-parse PARSER=api.parse:parse` (needs the API key and the places table)."""

import json
from types import SimpleNamespace

import pytest

from api.parse import TOOL, Context, build, extract
from api.places import PlaceMatch, pick_by_borough
from evals.parse.fixtures import build_request, load_cases, load_contexts
from evals.parse.grader import grade

CASES = {c["id"]: c for c in load_cases()}
CONTEXTS = load_contexts()
KIPS = (40.7438, -73.9799)


def pm(name, kind, borough, lat, lon, matched=None, at=None, distance_m=None):
    return PlaceMatch(name=name, kind=kind, borough=borough, lat=lat, lon=lon, matched=matched or name,
                      source="OpenStreetMap", at=at, distance_m=distance_m)


CENTRAL_PARK = pm("Central Park", "park", "Manhattan", 40.7826, -73.9656)
PLACES = {
    "penn station": [pm("New York Penn Station", "station", "Manhattan", 40.7502, -73.9928, matched="Penn Station")],
    "mccarren park": [pm("McCarren Park", "park", "Brooklyn", 40.7204, -73.9512)],
    "central park reservoir": [pm("Jacqueline Kennedy Onassis Reservoir", "water", "Manhattan", 40.7854, -73.9628,
                                  matched="Central Park Reservoir")],
    "central park south": [pm("Central Park South", "street", "Manhattan", 40.7660, -73.9760)],
    # Curated redirects (etl/curated/place_aliases.json): the runner's name finds the running path
    "west side highway": [pm("Hudson River Greenway", "path", "Manhattan", 40.7600, -74.0030)],
    "east river path": [pm("East River Greenway", "path", "Manhattan", 40.7400, -73.9720)],
    "1st ave & e 23rd st": [pm("1st Ave & E 23rd St", "crossing", "Manhattan", 40.7366, -73.9786)],
    "2nd ave": [pm("2nd Ave", "street", "Manhattan", 40.7450, -73.9770)],
    "prospect park": [pm("Prospect Park", "park", "Brooklyn", 40.6602, -73.9690)],
    "grand army plaza": [pm("Grand Army Plaza", "square", "Brooklyn", 40.6742, -73.9700),
                         pm("Grand Army Plaza", "square", "Manhattan", 40.7644, -73.9737)],
}
AT_CENTRAL_PARK = {"86th st": [pm("86th St", "street", "Manhattan", 40.7814, -73.9601, at="5th Ave"),
                               pm("86th St", "street", "Manhattan", 40.7854, -73.9697, at="Central Park West")]}


class FakePlaces:
    def lookup(self, name, near=None):
        if isinstance(near, PlaceMatch):
            return AT_CENTRAL_PARK.get(name.casefold(), [])
        return PLACES.get(name.casefold(), [])

    def pick(self, matches, ref_borough):
        return pick_by_borough(matches, ref_borough)

    def borough_at(self, lat, lon):
        return "Brooklyn" if lat < 40.70 else "Manhattan"

    def in_neighborhood(self, name, lat, lon):
        return name == "Kips Bay" and (lat, lon) == KIPS

    def park_around(self, match):
        return CENTRAL_PARK if "Reservoir" in match.matched else None

    def major_parks_near(self, lat, lon):
        return [pm("Prospect Park", "park", "Brooklyn", 40.6602, -73.9690, distance_m=150)] if lat < 40.70 else []

    def parks_near(self, lat, lon):
        return [pm("Bellevue South Park", "park", "Manhattan", 40.7410, -73.9772, distance_m=385),
                pm("Saint Vartan Park", "park", "Manhattan", 40.7451, -73.9748, distance_m=441)]

    def geocode(self, address, borough):
        known = {"11 madison ave": ["Manhattan", "Staten Island"], "120 broadway": ["Manhattan", "Brooklyn", "Queens"]}
        boroughs = known.get(address.casefold(), [])
        if borough in boroughs:
            return SimpleNamespace(lat=40.7415, lon=-73.9865, borough=borough), []
        return None, boroughs


def ext(**kw) -> dict:
    """An extraction with every field the strict schema requires."""
    base = {k: None for k in TOOL["input_schema"]["properties"]}
    base |= {"long_run": False, "workout": False, "via": [], "avoid": [], "amenities": [], "cant": [], "said": []}
    return base | kw


def place(kind, name=None, saved_id=None, outside_nyc=False):
    return {"kind": kind, "name": name, "saved_id": saved_id, "outside_nyc": outside_nyc}


def mi(value, unit="mi", max_value=None):
    return {"value": value, "unit": unit, "max_value": max_value}


IDEAL = {  # the extraction a correct model returns, per case
    "P01": ext(),
    "P04": ext(distance=mi(3), start=place("neighborhood", "Kips Bay")),
    "R05": ext(mode="exploring"),
    "R06": ext(mode="exploring"),
    "P05": ext(distance=mi(3), shape="loop_word"),
    "P09": ext(distance=mi(13), day={"kind": "today", "weekday": None, "date": None}),
    "P10": ext(distance=mi(3, max_value=4)),
    "P11": ext(minutes=45),
    "R04": ext(time={"kind": "in_minutes", "clock": None, "minutes": 30}, distance=mi(5), crowds="avoid"),
    "P14": ext(distance=mi(4), time={"kind": "tonight", "clock": None, "minutes": None}, cant=["lighting_safety"]),
    "P24": ext(time={"kind": "clock", "clock": "07:45", "minutes": None}, crowds="avoid"),
    "R01": ext(distance=mi(8), scenery="park_or_water", end=place("place", "McCarren Park"),
               day={"kind": "today", "weekday": None, "date": None}),
    "R02": ext(via=[{"name": "Central Park Reservoir", "kind": "place", "whole_way": False}],
               start=place("place", "86th St"), end=place("place", "Central Park South")),
    "R03": ext(distance=mi(3), via=[{"name": "West Side Highway", "kind": "place", "whole_way": False}]),
    "R10": ext(distance=mi(5), end=place("subjective", "the best italian spot")),
    "P15": ext(distance=mi(3), time={"kind": "lunch", "clock": None, "minutes": None},
               start=place("saved", "office", saved_id="office")),
    "P16": ext(distance=mi(5), start=place("place", "11 Madison Ave")),  # recorded as a place: code geocodes it
    "P17": ext(distance=mi(4), start=place("place", "1st Ave & E 23rd St")),
    "P18": ext(distance=mi(6), start=place("place", "Penn Station")),
    "P19": ext(distance=mi(5), start=place("place", "Hoboken PATH", outside_nyc=True)),
    "P20": ext(distance=mi(3), start=place("the_park", "the park")),
    "P46": ext(distance=mi(5), end=place("address", "120 Broadway")),
    "R07": ext(avoid=[{"name": "42nd St", "how": "along"}], crowds="avoid"),
    "P23": ext(distance=mi(6), avoid=[{"name": "1st Ave, E 25th–E 34th St", "how": "along"}]),
    "P25": ext(distance=mi(5), cant=["bike_lanes"]),
    "P27": ext(familiar="new", cant=["soft_avoid"]),
    "P28": ext(lights="waits"),
    "P29": ext(lights="zigzags", distance=mi(5)),
    "P31": ext(crowds="dont_mind", scenery="park_or_water"),
    "P32": ext(surface="paths", distance=mi(4)),
    "P33": ext(distance=mi(6), hills="avoid"),
    "P34": ext(distance=mi(6), amenities=[{"kind": "restroom", "at_mile": 3, "at_fraction": None}]),
    "P35": ext(distance=mi(8), amenities=[{"kind": "water", "at_mile": None, "at_fraction": 0.5}]),
    "P36": ext(mode="training", distance=mi(6), lights="waits"),
    "P38": ext(mode="training", distance=mi(5, "km"), lights="waits"),
    "R11": ext(mode="training", workout=True, hills="avoid", cant=["workout_segments"]),
    "R08": ext(familiar="new"),
    "R09": ext(long_run=True, day={"kind": "today", "weekday": None, "date": None},  # scenery follows the park
               via=[{"name": "the park", "kind": "the_park", "whole_way": False}]),
    "P39": ext(mode="exploring", distance=mi(7), cant=["bridges_in_general"]),
    "H01": ext(reuse={"kind": "weekday", "weekday": "tue", "date": None, "name_words": None, "longer": False,
                      "reverse": False}),
    "H02": ext(reuse={"kind": "usual", "weekday": None, "date": None, "name_words": None, "longer": True,
                      "reverse": False}),
    "H03": ext(reuse={"kind": "name", "weekday": None, "date": None, "name_words": "river", "longer": False,
                      "reverse": True}),
    "H04": ext(reuse={"kind": "last_week", "weekday": None, "date": None, "name_words": None, "longer": False,
                      "reverse": False}, avoid=[{"name": "E 34th St ferry landing", "how": "area"}]),
    "H05": ext(reuse={"kind": "usual", "weekday": None, "date": None, "name_words": None, "longer": False,
                      "reverse": False}),
    "P42": ext(shape="out_and_back", distance=mi(5)),
    "P44": ext(lights="waits", via=[{"name": "2nd Ave", "kind": "place", "whole_way": True}], cant=["whole_way"]),
    "P45": ext(distance=mi(5, "km"), time={"kind": "tonight", "clock": None, "minutes": None},
               second_run={"distance": mi(10), "day": {"kind": "weekday", "weekday": "sat", "date": None},
                           "time": None, "start": None}),
    "P47": ext(distance=mi(100), shape="loop_word"),
    "P48": ext(distance=mi(0.3), shape="loop_word"),
    "P49": ext(distance=mi(15), surface="paths",
               via=[{"name": "East River Path", "kind": "place", "whole_way": True}], cant=["whole_way"]),
    "P50": ext(start=place("place", "Grand Army Plaza"),
               via=[{"name": "Prospect Park", "kind": "place", "whole_way": False, "word": "Loop of"}]),
}


def said(*pairs):
    """Quotes as a correct model gives them: (chip, words) or (chip, words, item)."""
    return [{"chip": p[0], "words": p[1], "item": p[2] if len(p) > 2 else 0} for p in pairs]


QUOTES = {  # the runner's words behind each chip, per case (spans, 2026-11-09)
    "P01": [],
    "P04": said(("start", "kip bay"), ("distance", "3 mi")),
    "R05": said(("mode", "New to this area")),
    "R06": said(("mode", "New to this area")),
    "P05": said(("distance", "3 mi"), ("shape", "loop")),
    "P09": said(("distance", "13"), ("time", "today")),
    "P10": said(("distance", "3-4 miles")),
    "P11": said(("distance", "45 min")),
    "R04": said(("time", "in 30"), ("distance", "5 miles"), ("crowds", "low pedestrian areas")),
    "P14": said(("distance", "4 mi"), ("time", "tonight")),
    "P24": said(("time", "leaving 7:45"), ("crowds", "steer clear of schools at drop off")),
    "R01": said(("time", "Today"), ("distance", "8 miles"), ("scenery", "on the water"),
                ("end", "ending at McCarren Park")),
    "R02": said(("via", "Central park reservor", 1), ("start", "starting at 86th st"),
                ("end", "ending at central park south")),
    "R03": said(("via", "the west side highway", 1), ("distance", "3 easy miles")),
    "R10": said(("distance", "5 miles"), ("end", "the best italian spot")),
    "P15": said(("time", "lunch"), ("start", "from the office"), ("distance", "3mi")),
    "P16": said(("distance", "5 mi"), ("start", "11 madison ave")),
    "P17": said(("start", "1st and 23rd"), ("distance", "4 mi")),
    "P18": said(("distance", "6"), ("start", "penn station")),
    "P19": said(("distance", "5 mi"), ("start", "hoboken path")),
    "P20": said(("start", "the park"), ("distance", "3 mi")),
    "P46": said(("end", "120 broadway"), ("distance", "5 mi")),
    "R07": said(("crowds", "the chaos"), ("avoid", "42nd st", 1)),
    "P23": said(("distance", "6 miles"), ("avoid", "1st ave by the hospitals", 1)),
    "P25": said(("distance", "5mi")),
    "P27": said(("familiar", "something new")),
    "P28": said(("lights", "no lights if possible")),
    "P29": said(("lights", "i just zig zag"), ("distance", "5")),
    "P31": said(("crowds", "crowds dont bother me"), ("scenery", "water views")),
    "P32": said(("surface", "soft surface"), ("distance", "4")),
    "P33": said(("distance", "6mi"), ("hills", "flat")),
    "P34": said(("distance", "6"), ("amenity", "bathroom around mile 3", 1)),
    "P35": said(("distance", "8 miles"), ("amenity", "water halfway", 1)),
    "P36": said(("mode", "tempo"), ("distance", "6"), ("lights", "long stretches w no lights")),
    "P38": said(("distance", "5k"), ("mode", "race pace"), ("lights", "uninterrupted")),
    "R11": said(("mode", "workout"), ("hills", "avoid hills"), ("distance", "4xmile workout")),
    "R08": said(("familiar", "new from everything else I have tried")),
    "R09": said(("time", "today"), ("via", "the park", 1), ("distance", "Long run")),
    "P39": said(("distance", "7 miler"), ("mode", "showing a friend around")),
    "H01": said(("reuse", "same as Tuesday")),
    "H02": said(("reuse", "my usual"), ("distance", "longer")),
    "H03": said(("reuse", "the river one"), ("reverse", "other direction")),
    "H04": said(("reuse", "last week's route"), ("avoid", "the ferry part", 1)),
    "H05": said(("reuse", "my usual")),
    "P42": said(("shape", "out and back"), ("distance", "5mi")),
    "P44": said(("lights", "no lights"), ("via", "2nd ave the whole way", 1)),
    "P45": said(("distance", "5k"), ("time", "tonight")),
    "P47": said(("distance", "100 mile"), ("shape", "loop")),
    "P48": said(("distance", "0.3 mi"), ("shape", "loop")),
    "P49": said(("distance", "15 miles"), ("via", "the east river path", 1), ("surface", "staying on the east river path")),
    "P50": said(("via", "Loop of Prospect Park", 1), ("start", "from Grand Army Plaza")),
}
for _cid, _q in QUOTES.items():
    IDEAL[_cid]["said"] = _q


def test_every_case_has_an_ideal_extraction():
    assert set(IDEAL) == set(CASES)


@pytest.mark.parametrize("case_id", sorted(IDEAL))
def test_rules_pass_the_case_given_the_right_extraction(case_id):
    case = CASES[case_id]
    ctx = Context.from_request(build_request(case, CONTEXTS))
    out = build(IDEAL[case_id], ctx, FakePlaces())
    assert grade(case, out).reasons == []


def test_claude_never_receives_coordinates():
    ctx = Context.from_request(build_request(CASES["P01"], CONTEXTS))
    msg = ctx.for_claude("run")
    assert "40.7" not in msg and "73.9" not in msg and '"lat"' not in msg
    assert json.loads(msg)["location_known"] is True


def test_extract_logs_tokens_and_cost_but_no_location():
    logged = []
    block = SimpleNamespace(type="tool_use", name="record_request", input=ext(distance=mi(3)))
    usage = SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=3000,
                            cache_creation_input_tokens=0)
    calls = []

    class Client:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                calls.append(kw)
                return SimpleNamespace(content=[block], usage=usage, stop_reason="tool_use", _request_id="req_1")

    ctx = Context.from_request(build_request(CASES["P05"], CONTEXTS))
    got, stats = extract("3 mi loop", ctx, Client, log=logged.append)
    assert got["distance"]["value"] == 3
    assert stats["cost_usd"] == pytest.approx((1000 * 0.10 + 200 * 0.50 + 3000 * 0.01) / 1e6)
    assert logged and "location" not in json.dumps(logged[0]) and "40.74" not in json.dumps(logged[0])
    assert calls[0]["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert calls[0]["tool_choice"] == {"type": "auto"}


def test_tool_input_is_conformed_to_the_schema_and_sentinels_become_none():
    from api.parse import SchemaError, _clean, _conform

    raw = {"distance": {"value": 3, "unit": "mi"}, "mode": "none", "start": {"kind": "none"}, "extra": 1,
           "second_run": {"present": False}}
    got = _clean(_conform(raw, TOOL["input_schema"]))
    assert got["distance"] == {"value": 3, "unit": "mi", "max_value": None}
    assert got["mode"] is None and got["start"] is None and got["second_run"] is None and "extra" not in got
    assert got["via"] == [] and got["long_run"] is False and got["time"] is None
    with pytest.raises(SchemaError):
        _conform({"lights": "sometimes"}, TOOL["input_schema"])
    with pytest.raises(SchemaError):
        _conform({"distance": {"value": "three", "unit": "mi"}}, TOOL["input_schema"])


def test_an_unsaid_object_written_as_empty_is_not_said():
    from api.parse import _clean, _conform

    got = _clean(_conform({"distance": "", "time": 0, "start": "none"}, TOOL["input_schema"]))
    assert got["distance"] is None and got["time"] is None and got["start"] is None


def test_conform_tidies_formatting_slips_and_drops_unknown_choices():
    from api.parse import _conform

    dropped = []
    got = _conform({"mode": '"training"', "minutes": "45", "cant": ["bike_lanes", "made_up"], "distance": {
        "value": "3", "unit": "mi", "max_value": ""}}, TOOL["input_schema"], dropped=dropped)
    assert got["mode"] == "training" and got["minutes"] == 45.0 and got["cant"] == ["bike_lanes"]
    assert got["distance"]["value"] == 3.0 and got["distance"]["max_value"] == 0
    assert dropped == ["input.cant: 'made_up'"]


def test_a_malformed_tool_call_is_retried_once():
    from api.parse import parse

    good = ext(distance=mi(3), shape="loop_word", said=QUOTES["P05"]) | {"time": {"kind": "none", "clock": "", "minutes": 0},
                                                      "day": {"kind": "none", "weekday": "none", "date": ""}}
    bad = dict(good, shape="none</shape><parameter>")
    replies = [bad, good]
    logged = []
    usage = SimpleNamespace(input_tokens=10, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0)

    class Client:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                block = SimpleNamespace(type="tool_use", name="record_request", input=replies.pop(0))
                return SimpleNamespace(content=[block], usage=usage, stop_reason="tool_use", _request_id="r")

    out = parse(build_request(CASES["P05"], CONTEXTS), client=Client, places=FakePlaces(), log=logged.append)
    assert grade(CASES["P05"], out).passed and out["trace"]["stats"]["attempts"] == 2 and len(logged) == 2


@pytest.mark.parametrize("text, drop", [
    ("scenic 7 miler, showing a friend around, bridges would be cool", True),
    ("showing my cousin around, 5 mi", True),
    ("scenic run along the water", False),
    ("crowds dont bother me, just want water views", False),
    ("6 mi in the park", False),
])
def test_sightseeing_alone_never_sets_scenery(text, drop):
    from api.parse import scenery_from_sightseeing_only

    assert scenery_from_sightseeing_only(text) is drop


def test_scenic_scenery_is_dropped_in_build():
    case = CASES["P39"]
    ctx = Context.from_request(build_request(case, CONTEXTS))
    out = build(IDEAL["P39"] | {"scenery": "some"}, ctx, FakePlaces())
    assert "scenery" not in out["parsed"]["constraints"] and grade(case, out).passed



# ---- spans (2026-11-09) ------------------------------------------------------------------------------------------

def _built(case_id):
    ctx = Context.from_request(build_request(CASES[case_id], CONTEXTS))
    return build(IDEAL[case_id], ctx, FakePlaces())


@pytest.mark.parametrize("case_id,chip,words", [
    ("R01", "c_distance", "8 miles"), ("R01", "c_end", "ending at McCarren Park"), ("R01", "c_time", "Today"),
    ("P34", "c_amenity_1", "bathroom around mile 3"), ("R07", "c_avoid_1", "42nd st"), ("H03", "c_reverse",
                                                                                     "other direction")])
def test_a_said_chip_carries_the_runners_words_and_where_they_are(case_id, chip, words):
    out = _built(case_id)
    c = next(x for x in out["parsed"]["chips"] if x["id"] == chip)
    text = CASES[case_id]["text"]
    assert c["span"]["text"] == words and text[c["span"]["start"]:c["span"]["end"]] == words
    assert out["parsed"]["constraints"]["spans"][chip] == c["span"]


def test_defaults_presets_and_usual_values_have_no_span():
    out = _built("R01")
    for c in out["parsed"]["chips"]:
        assert (c["span"] is None) == (c["source"] != "said"), c


def test_words_the_request_doesnt_have_give_no_span_rather_than_a_guess():
    ctx = Context.from_request(build_request(CASES["P05"], CONTEXTS))
    e = dict(IDEAL["P05"], said=said(("distance", "three miles"), ("shape", "loop")))
    chips = {c["id"]: c for c in build(e, ctx, FakePlaces())["parsed"]["chips"]}
    assert chips["c_distance"]["span"] is None and chips["c_shape"]["span"]["text"] == "loop"


def test_park_scenery_from_a_via_park_takes_the_vias_words():
    out = _built("R02")
    chips = {c["id"]: c for c in out["parsed"]["chips"]}
    assert chips["c_scenery"]["span"] == chips["c_via_1"]["span"]
    assert chips["c_via_1"]["span"]["text"] == "Central park reservor"


def test_a_question_names_its_chip_and_a_chip_is_made_from_the_runners_words():
    out = _built("R02")  # "Which 86th St?": no start chip until it's answered
    q = out["parsed"]["question"]
    chip = next(c for c in out["parsed"]["chips"] if c["id"] == q["chip_id"])
    assert q["chip_id"] == "c_start" and chip["field"] == "start" and chip["text"] == "starting at 86th st"
    assert chip["span"]["text"] == "starting at 86th st" and chip["source"] == "said"


def test_a_question_with_nothing_said_about_it_has_no_chip():
    out = _built("R06")  # "what do you suggest": how far?
    assert out["parsed"]["question"]["chip_id"] is None


def test_a_question_about_an_existing_chip_names_it():
    out = _built("P47")  # "100 mile loop": did you mean 10?
    q = out["parsed"]["question"]
    assert q["chip_id"] == "c_distance"
    assert next(c for c in out["parsed"]["chips"] if c["id"] == "c_distance")["span"]["text"] == "100 mile"


def test_spans_survive_a_chip_edit():
    from api.parse import parsed_for_constraints
    out = _built("P36")
    ctx = Context.from_request(build_request(CASES["P36"], CONTEXTS))
    again = parsed_for_constraints(out["parsed"]["constraints"], ctx, None)
    assert [c["span"] for c in again["chips"]] == [c["span"] for c in out["parsed"]["chips"]]


def test_spans_count_from_the_text_as_sent_even_with_leading_spaces():
    req = build_request(CASES["P05"], CONTEXTS) | {"text": "  3 mi loop"}
    out = build(IDEAL["P05"], Context.from_request(req), FakePlaces())
    span = next(c for c in out["parsed"]["chips"] if c["id"] == "c_distance")["span"]
    assert span == {"text": "3 mi", "start": 2, "end": 6}



def test_a_quote_that_doesnt_fit_is_dropped_never_failing_the_parse():
    from api.parse import _conform
    raw = {"said": [{"chip": "day", "item": 0, "words": "Today"}, {"chip": "soft_avoid", "item": 0, "words": "x"},
                    {"chip": "distance", "item": "two", "words": "8 miles"}, {"chip": "end", "item": 0, "words": "x"}]}
    dropped = []
    out = _conform(raw, TOOL["input_schema"], dropped=dropped)
    assert [q["chip"] for q in out["said"]] == ["time", "end"]  # "day" read as the time chip
    assert len(dropped) == 2
