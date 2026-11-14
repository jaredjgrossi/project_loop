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
    "w 71st st": [pm("West 71st Street", "street", "Manhattan", 40.7766, -73.9800)],
    "71st st & columbus ave": [pm("Columbus Ave & W 71st St", "crossing", "Manhattan", 40.7772, -73.9790)],
    "2nd ave": [pm("2nd Ave", "street", "Manhattan", 40.7450, -73.9770)],
    "prospect park": [pm("Prospect Park", "park", "Brooklyn", 40.6602, -73.9690)],
    "central park": [pm("Central Park", "park", "Manhattan", 40.7826, -73.9656)],
    "metropolitan museum of art": [pm("Metropolitan Museum of Art", "landmark", "Manhattan", 40.7794, -73.9634)],
    "washington square park": [pm("Washington Square Park", "park", "Manhattan", 40.7308, -73.9973)],
    "riverside park": [pm("Riverside Park", "park", "Manhattan", 40.8010, -73.9720)],
    "fort greene park": [pm("Fort Greene Park", "park", "Brooklyn", 40.6906, -73.9744)],
    "grand army plaza": [pm("Grand Army Plaza", "square", "Brooklyn", 40.6742, -73.9700),
                         pm("Grand Army Plaza", "square", "Manhattan", 40.7644, -73.9737)],
}
AT_CENTRAL_PARK = {"86th st": [pm("86th St", "street", "Manhattan", 40.7814, -73.9601, at="5th Ave"),
                               pm("86th St", "street", "Manhattan", 40.7854, -73.9697, at="Central Park West")]}


# Past routes on file (step 11): rt_a runs the East River esplanade past the E 34th St ferry landing; rt_c is a
# Gramercy street rectangle, nowhere near a ferry.
E34_LANDING = (40.7439, -73.9707)
PAST_LINES = {
    "rt_a": ((-73.9799, 40.7438), (-73.9712, 40.7398), (-73.9707, 40.7439), (-73.9690, 40.7480),
             (-73.9707, 40.7439), (-73.9712, 40.7398), (-73.9799, 40.7438)),
    "rt_c": ((-73.9799, 40.7438), (-73.9850, 40.7380), (-73.9880, 40.7395), (-73.9830, 40.7455), (-73.9799, 40.7438)),
}


class FakePlaces:
    def past_route(self, route_id):
        from api.past_routes import PastRoute
        line = PAST_LINES.get(route_id)
        return PastRoute(route_id, line) if line else None

    def street_crossings(self, street, near):
        return []

    def ferry_landings_along(self, coords):
        near = any(abs(lat - E34_LANDING[0]) * 110_574 < 100 and abs(lon - E34_LANDING[1]) * 84_300 < 100
                   for lon, lat in coords)
        return [{"name": "E 34th St ferry landing", "how": "area",
                 "place": {"kind": "place", "name": "E 34th St ferry landing", "borough": "Manhattan",
                           "lat": E34_LANDING[0], "lon": E34_LANDING[1], "source": "NYC Ferry GTFS",
                           "trust": "listed"}}] if near else []

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
        # Runnable places only, nearest first (phone test, 2026-11-09): a long waterfront path, then a major park
        return [pm("East River Esplanade", "path", "Manhattan", 40.7449, -73.9705, distance_m=657),
                pm("Central Park", "park", "Manhattan", 40.7826, -73.9656, distance_m=2900)]

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
                      "reverse": False}, avoid=[{"name": "ferry", "how": "area"}]),  # code finds the landing
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
    "P51": ext(start=place("place", "W 71st St")),
    "P52": ext(start=place("place", "W 71st St"), distance=mi(4)),
    "P53": ext(start=place("place", "71st St & Columbus Ave"), distance=mi(5, "km")),
    "P54": ext(distance=mi(5), via=[{"name": "Central Park", "kind": "place", "whole_way": False}]),
    "P55": ext(distance=mi(4), via=[{"name": "Prospect Park", "kind": "place", "whole_way": False, "word": "around"}]),
    "P56": ext(distance=mi(3), via=[{"name": "Washington Square Park", "kind": "place", "whole_way": False}]),
    "P57": ext(distance=mi(5, "km"), via=[{"name": "Riverside Park", "kind": "place", "whole_way": False}]),
    "P58": ext(distance=mi(4), via=[{"name": "Fort Greene Park", "kind": "place", "whole_way": False,
                                       "word": "around"}]),
    "P59": ext(distance=mi(10, "km"), end=place("saved", "home", saved_id="home"),
               via=[{"name": "Metropolitan Museum of Art", "kind": "place", "whole_way": False}]),
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
    "P54": said(("distance", "5 miles"), ("via", "Central Park", 1)),
    "P55": said(("distance", "4 miles"), ("via", "around Prospect Park", 1)),
    "P56": said(("distance", "3 miles"), ("via", "Washington Square Park", 1)),
    "P57": said(("distance", "5k"), ("via", "Riverside Park", 1)),
    "P58": said(("distance", "4 mi"), ("via", "around Fort Greene Park", 1)),
    "P59": said(("distance", "10k"), ("via", "the Met", 1), ("end", "then home")),
    "P51": said(("start", "west 71st st")),
    "P52": said(("start", "W. 71st Street"), ("distance", "4 mi")),
    "P53": said(("start", "71st and Columbus"), ("distance", "5k")),
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


def test_a_sparse_tool_input_reads_as_the_full_one():  # step 5b: the model leaves unsaid fields out
    from api.parse import TOOL, _conform
    sparse = {"distance": {"value": 5, "unit": "mi"}, "via": [{"name": "Prospect Park", "kind": "place"}],
              "said": [{"chip": "distance", "words": "5 miles"}]}
    full = _conform(sparse, TOOL["input_schema"])
    assert full["distance"] == {"value": 5, "unit": "mi", "max_value": 0}
    assert full["time"]["kind"] == "none" and full["start"]["kind"] == "none" and full["avoid"] == []
    assert full["via"] == [{"name": "Prospect Park", "kind": "place", "whole_way": False, "word": ""}]
    assert full["said"] == [{"chip": "distance", "item": 0, "words": "5 miles"}]
    assert TOOL["input_schema"]["required"] == []


class CloseParks(FakePlaces):
    """Two runnable places about as far: no clear winner, so "Which park?" asks."""
    def parks_near(self, lat, lon):
        return [pm("East River Esplanade", "path", "Manhattan", 40.7449, -73.9705, distance_m=657),
                pm("John V. Lindsay East River Park", "park", "Manhattan", 40.7180, -73.9750, distance_m=980)]


def test_which_park_offers_runnable_places_nearest_first_with_their_distance():  # phone test 2026-11-09
    ctx = Context.from_request(build_request(CASES["P20"], CONTEXTS))
    q = build(IDEAL["P20"], ctx, CloseParks())["parsed"]["question"]
    assert q["text"] == "Which park?"
    assert [o["text"] for o in q["options"]] == ["East River Esplanade · 0.4 mi",
                                                  "John V. Lindsay East River Park · 0.6 mi"]


def test_one_park_that_clearly_wins_is_taken_without_asking():  # decision 043
    out = _built("P20")  # the esplanade at 0.4 mi, Central Park at 1.8: the nearer clearly wins
    assert out["parsed"]["question"] is None
    assert out["parsed"]["constraints"]["start_place"]["name"] == "East River Esplanade"


def test_a_park_a_run_goes_to_must_fit_the_distance():
    from api.parse import _Build, _runnable_parks
    near, far = (pm("Near Park", "park", "Manhattan", 40.75, -73.98, distance_m=900),
                 pm("Far Park", "park", "Manhattan", 40.78, -73.97, distance_m=1100))
    b = _Build(Context.from_request(build_request(CASES["R09"], CONTEXTS)), FakePlaces())
    b.run_miles = 2.0  # 0.45 of 2 mi is about 1450 m: both fit, neither clearly wins
    assert _runnable_parks(b, [near, far], reach=True) == ([near, far], None)
    b.run_miles = 2.4  # still both
    assert _runnable_parks(b, [near, far], reach=True)[1] is None
    b.run_miles = 1.4  # about 1010 m: only the near one fits, so it wins
    assert _runnable_parks(b, [near, far], reach=True) == ([near], near)


def test_the_usual_shape_applies_when_none_is_said():  # profile.usual_shape (phone test, 2026-11-10)
    req = build_request(CASES["P01"], CONTEXTS)
    req["profile"] = {**req["profile"], "usual_shape": "out_and_back"}
    out = build(IDEAL["P01"], Context.from_request(req), FakePlaces())
    c = out["parsed"]["constraints"]
    assert c["shape"] == "out_and_back" and c["sources"]["shape"] == "usual"
    chip = next(ch for ch in out["parsed"]["chips"] if ch["field"] == "shape")
    assert chip["text"] == "Out and back" and chip["source"] == "usual" and chip["span"] is None


def test_a_said_shape_beats_the_usual_one():
    req = build_request(CASES["P05"], CONTEXTS)  # "3 mile loop": the plain word loop is said, and means any
    req["profile"] = {**req["profile"], "usual_shape": "out_and_back"}
    out = build(IDEAL["P05"], Context.from_request(req), FakePlaces())
    assert out["parsed"]["constraints"]["shape"] == "any"


# ---- the app's route type and favorites (decision 043) -------------------------------------------------------------

def _with(case_id, **fields):
    req = build_request(CASES[case_id], CONTEXTS)
    for k, v in fields.items():
        req[k] = v
    return Context.from_request(req)


def test_the_apps_route_type_beats_the_words():
    out = build(IDEAL["P05"], _with("P05", shape="out_and_back"), FakePlaces())  # "3 mile loop"
    c = out["parsed"]["constraints"]
    chip = next(ch for ch in out["parsed"]["chips"] if ch["field"] == "shape")
    assert c["shape"] == "out_and_back" and "shape" not in c.get("sources", {})  # said: not listed as filled in
    assert (chip["text"], chip["source"]) == ("Out and back", "said")


def test_one_way_without_an_end_asks_where_to_end():
    out = build(IDEAL["P01"], _with("P01", shape="one_way"), FakePlaces())
    q = out["parsed"]["question"]
    assert (q["about"], q["from"], q["text"]) == ("end", "parser", "Where do you want to end?")


def test_one_way_with_an_end_builds_and_the_chip_says_one_way():
    out = build(IDEAL["R01"], _with("R01", shape="one_way"), FakePlaces())  # ends at McCarren Park
    assert out["parsed"]["question"] is None
    assert next(ch["text"] for ch in out["parsed"]["chips"] if ch["field"] == "shape") == "One way"


def test_one_way_end_answered_by_name():
    from api.parse import answer_overrides, resume
    ctx = _with("P01", shape="one_way")
    out = build(IDEAL["P01"], ctx, FakePlaces())
    settled = answer_overrides(out["trace"]["answer_map"], None, "McCarren Park", ctx)
    after = resume(IDEAL["P01"], ctx, FakePlaces(), {**out["trace"]["answers"], **settled})
    assert after["parsed"]["question"] is None
    assert after["parsed"]["constraints"]["end_place"]["name"] == "McCarren Park"


def test_a_usual_one_way_asks_for_the_end_too():
    req = build_request(CASES["P01"], CONTEXTS)
    req["profile"] = {**req["profile"], "usual_shape": "one_way"}
    assert build(IDEAL["P01"], Context.from_request(req), FakePlaces())["parsed"]["question"]["about"] == "end"


FAVORITES = [  # the eval contexts' recent routes, with rt_b saved as a favorite and renamed by the runner
    {"id": "rt_a", "date": "2026-10-27", "name": "East River esplanade out-and-back", "distance_mi": 3.0,
     "ran_count": 2},
    {"id": "rt_c", "date": "2026-10-29", "name": "Gramercy street rectangle", "distance_mi": 3.1, "ran_count": 1},
    {"id": "rt_b", "date": "2026-11-02", "name": "the Stuy loop", "distance_mi": 4.0, "saved": True,
     "ran_count": 7},
]


def test_a_renamed_favorite_is_found_by_its_name():
    ext_ = ext(reuse={"kind": "name", "weekday": None, "date": None, "name_words": "stuy loop", "longer": False,
                      "reverse": False})
    out = build(ext_, _with("H01", recent_routes=FAVORITES), FakePlaces())
    assert out["parsed"]["constraints"]["reuse_route_id"] == "rt_b"


def test_my_usual_is_the_most_run_by_ran_count():
    out = build(IDEAL["H05"], _with("H05", recent_routes=FAVORITES), FakePlaces())
    assert out["parsed"]["constraints"]["reuse_route_id"] == "rt_b"


def test_claude_sees_favorites_and_ran_counts_but_no_lines():
    seen = json.loads(_with("H05", recent_routes=FAVORITES).for_claude("my usual"))
    assert seen["recent_routes"][2] == {"id": "rt_b", "date": "2026-11-02", "weekday": "Mon", "name": "the Stuy loop",
                                        "distance_mi": 4.0, "times_run": 7, "saved": True}


# ---- named parks recorded as the_park (full review 4.2, Q1 and Q2) ----------------------------------------------------


def _park_build(**kw):
    ctx = Context.from_request(build_request(CASES["P01"], CONTEXTS))
    return build(ext(**kw), ctx, FakePlaces())


@pytest.mark.parametrize("name", ["Central Park", "central park"])
def test_a_named_park_recorded_as_the_park_is_still_that_park(name):
    out = _park_build(distance=mi(5), via=[{"name": name, "kind": "the_park", "whole_way": False}])
    assert out["parsed"]["question"] is None
    assert [v["name"] for v in out["parsed"]["constraints"]["via_places"]] == ["Central Park"]


def test_a_named_park_as_the_start_is_looked_up_by_name():
    out = _park_build(distance=mi(4), start=place("the_park", "Riverside Park"))
    assert out["parsed"]["constraints"]["start_place"]["name"] == "Riverside Park"


@pytest.mark.parametrize("name", ["the park", "a park", "park", "a nearby park", "the closest park", "my local park"])
def test_a_generic_park_is_still_the_nearest_runnable_place(name):
    out = _park_build(distance=mi(3), via=[{"name": name, "kind": "the_park", "whole_way": False}])
    assert [v["name"] for v in out["parsed"]["constraints"]["via_places"]] == ["East River Esplanade"]


def test_a_named_park_that_isnt_found_asks_instead_of_taking_the_nearest():
    out = _park_build(distance=mi(5), via=[{"name": "Nowhere Park", "kind": "the_park", "whole_way": False}])
    assert out["parsed"]["question"]["about"] == "via"  # "Couldn't find Nowhere Park", never a silent substitute


# ---- a request outside the area Loop covers is an error, not a question ----------------------------------------


def outside(role="start", name="Tampa", **kw):
    spec = place("place", name, outside_nyc=True)
    return ext(distance=mi(5), **{role: spec}, **kw)


def built(extraction, case_id="P19"):
    return build(extraction, Context.from_request(build_request(CASES[case_id], CONTEXTS)), FakePlaces())


@pytest.mark.parametrize("role", ["start", "end"])
def test_a_place_outside_the_area_is_an_out_of_area_error_naming_the_place(role):
    out = built(outside(role))
    assert out["error"] == "out_of_area" and out["place"] == "Tampa" and out["covers"] == "New York City"
    assert out["text"] == "Loop only covers New York City, and Tampa is outside it."
    assert "parsed" not in out


def test_the_place_is_the_one_the_runner_named_not_a_guess():
    out = built(outside(name="  Jersey City  "))
    assert out["place"] == "Jersey City"


def test_an_outside_place_with_no_name_is_still_an_error_without_a_place():
    out = built(outside(name=None))
    assert out["error"] == "out_of_area" and out["place"] is None and out["covers"] == "New York City"
    assert out["text"] == "That's outside the area Loop covers, which is New York City."


def test_a_place_inside_the_area_is_not_an_error():
    e = ext(distance=mi(5), start=place("place", "Penn Station"))
    assert "error" not in built(e)


def test_the_grader_passes_an_out_of_area_error_where_the_case_expects_one():
    case = CASES["P19"]
    assert case["expect"]["outcome"] == "ERROR"
    assert grade(case, built(IDEAL["P19"])).reasons == []
    assert grade(case, built(outside(name="Tampa"))).reasons != []  # the wrong place
    assert grade(case, {"error": "parse_failed", "text": "x"}).reasons != []  # the wrong error
