"""The reason a route is a good fit, in one line, from its measured fields (UI review: "park-aware reason").
Code writes it from numbers it already has; the LLM never does."""

import pytest

from api.reason import route_reason


def reason(**kw):
    base = dict(waterfront_pct=0.0, park_pct=0.0, park_name=None, lights=10, climb_m=30.0, miles=3.0)
    return route_reason(**(base | kw))


def test_a_waterfront_route_says_so_with_its_lights_and_that_it_is_flat():
    r = reason(waterfront_pct=60.4, lights=12, climb_m=8.5)
    assert r["text"] == "60% on the waterfront, 12 lights, flat"
    assert [p["key"] for p in r["parts"]] == ["water", "lights", "flat"]


def test_a_park_route_names_the_park_and_doesnt_call_it_a_waterfront():
    r = reason(park_pct=82.0, park_name="Central Park", waterfront_pct=4.0, lights=3)
    assert r["text"].startswith("82% through Central Park, 3 lights")
    assert "waterfront" not in r["text"]  # 4% by the water isn't a waterfront route


def test_mostly_park_with_no_single_park_named_says_parks():
    assert reason(park_pct=55.0, park_name=None)["text"].startswith("55% in parks")


def test_a_park_and_the_water_both_count_when_both_are_big():
    r = reason(park_pct=45.0, park_name="Prospect Park", waterfront_pct=25.0)
    assert [p["key"] for p in r["parts"]][:2] == ["park", "water"]


def test_no_lights_is_said_plainly():
    assert "No lights" in reason(lights=0)["text"]


def test_one_light_is_singular():
    assert "1 light," in reason(lights=1)["text"] + ","


def test_a_hilly_route_says_how_much_it_climbs():
    r = reason(climb_m=120.0, miles=3.0)
    assert "120 m of climb" in r["text"] and r["status"] == "estimate"  # the climb is an estimate (decision 037)


def test_a_middling_climb_isnt_mentioned():
    assert "climb" not in reason(climb_m=60.0, miles=3.0)["text"] and "Flat" not in reason(climb_m=60.0)["text"]


def test_at_most_three_parts():
    assert len(reason(park_pct=60, park_name="Central Park", waterfront_pct=30, lights=2, climb_m=1)["parts"]) == 3


def test_what_isnt_scored_isnt_mentioned():
    r = reason(lights=None, climb_m=None, waterfront_pct=70.0)
    assert r["text"] == "70% on the waterfront"


def test_a_route_with_nothing_notable_has_no_reason():
    r = reason(lights=None, climb_m=None)
    assert r["text"] is None and r["parts"] == []


@pytest.mark.parametrize("key", ["status", "source"])
def test_the_reason_carries_a_trust_label_and_a_source(key):
    assert reason(waterfront_pct=60.0)[key]
