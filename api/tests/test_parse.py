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
    base |= {"long_run": False, "workout": False, "via": [], "avoid": [], "amenities": [], "cant": []}
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
}


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

    good = ext(distance=mi(3), shape="loop_word") | {"time": {"kind": "none", "clock": "", "minutes": 0},
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
