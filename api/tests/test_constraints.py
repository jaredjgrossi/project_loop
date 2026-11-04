import pytest
from pydantic import ValidationError

from api.constraints import (
    PRESETS,
    AmenityRequest,
    Lights,
    Mode,
    RunConstraints,
    describe,
    resolve_preferences,
)


def test_minimal_request_is_valid():
    c = RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=6)
    assert c.shape == "any"  # unstated shape offers loops and out-and-backs
    assert c.tolerance_pct == 5


def test_start_is_required():
    with pytest.raises(ValidationError, match="start"):
        RunConstraints(distance_mi=4)


def test_my_location_counts_as_a_start():
    assert RunConstraints(use_my_location=True, distance_mi=4).use_my_location


def test_address_and_my_location_together_are_ambiguous():
    with pytest.raises(ValidationError, match="start"):
        RunConstraints(start_address="11 Madison Ave, Manhattan", use_my_location=True, distance_mi=4)


@pytest.mark.parametrize("miles", [0, 0.4, 31, -2])
def test_distance_out_of_range_rejected(miles):
    with pytest.raises(ValidationError):
        RunConstraints(start_address="11 Madison Ave, Manhattan", distance_mi=miles)


def test_unknown_fields_rejected():
    # The parse step must not smuggle in fields the scorer doesn't know about.
    with pytest.raises(ValidationError):
        RunConstraints(start_address="11 Madison Ave, Manhattan", distance_mi=4, route_geometry=[[0, 0]])


def test_amenity_beyond_the_run_rejected():
    with pytest.raises(ValidationError, match="mile"):
        RunConstraints(
            start_address="11 Madison Ave, Manhattan", distance_mi=4,
            amenities=[AmenityRequest(kind="restroom", at_mile=5)],
        )


def test_amenity_within_the_run_ok():
    c = RunConstraints(
        start_address="11 Madison Ave, Manhattan", distance_mi=6, amenities=[AmenityRequest(kind="restroom", at_mile=3)]
    )
    assert c.amenities[0].within_mi == 0.5


def test_no_mode_and_no_preferences_resolves_to_neutral_defaults():
    p = resolve_preferences(RunConstraints(start_address="11 Madison Ave, Manhattan", distance_mi=4))
    assert p.values["lights"] == Lights.ZIGZAGS
    assert all(src == "default" for src in p.sources.values())


def test_mode_preset_fills_unstated_preferences():
    p = resolve_preferences(RunConstraints(start_address="11 Madison Ave, Manhattan", distance_mi=4, mode=Mode.TRAINING))
    assert p.values == PRESETS[Mode.TRAINING]
    assert set(p.sources.values()) == {"preset"}


def test_stated_preference_beats_the_preset():
    c = RunConstraints(start_address="11 Madison Ave, Manhattan", distance_mi=4, mode=Mode.TRAINING, lights=Lights.ZIGZAGS)
    p = resolve_preferences(c)
    assert p.values["lights"] == Lights.ZIGZAGS
    assert p.sources["lights"] == "stated"
    assert p.sources["crowds"] == "preset"


def test_training_and_exploring_differ_where_discovery_says_they_do():
    t, e = PRESETS[Mode.TRAINING], PRESETS[Mode.EXPLORING]
    assert t["crowds"] == "avoid" and e["crowds"] == "dont_mind"
    assert t["scenery"] != e["scenery"]


def test_describe_shows_every_field_and_where_preferences_came_from():
    c = RunConstraints(
        start_address="446 3rd Ave, 10016", distance_mi=6, mode=Mode.TRAINING, lights=Lights.WAITS,
        avoid_places=["Times Square"], amenities=[AmenityRequest(kind="water", at_mile=3)],
    )
    text = "\n".join(describe(c))
    for expected in ["446 3rd Ave, 10016", "6 mi", "Shape: any", "Training", "waits for the light (you said)",
                     "avoid (Training preset)", "Times Square", "water near mile 3"]:
        assert expected in text


def test_start_hour_comes_from_start_time_and_is_shown():
    c = RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3, start_time="06:45")
    assert c.start_hour == 6
    assert any("06:45" in line and "hour 6" in line for line in describe(c))
    assert RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3).start_hour is None


@pytest.mark.parametrize("bad", ["24:00", "6:45", "06:60", "noon"])
def test_start_time_must_be_hh_mm(bad):
    with pytest.raises(ValidationError):
        RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3, start_time=bad)


def test_start_date_and_time_give_the_start_moment():
    from datetime import date, datetime

    c = RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3, start_time="18:00", start_date=date(2026, 11, 3))
    assert c.start_moment() == datetime(2026, 11, 3, 18, 0)
    assert any("Tuesday" in line for line in describe(c))
    assert RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3).start_moment() is None


def _origins(c):
    from api.constraints import request_items

    return {i["key"]: i["origin"] for i in request_items(c)}


def test_start_distance_shape_mode_and_time_say_where_they_came_from():
    # Decision 020: every field, not only the preferences, is labeled you said / preset / default.
    bare = _origins(RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3))
    assert bare["start"] == bare["distance"] == "you said"
    assert bare["shape"] == bare["mode"] == bare["start_time"] == bare["tolerance"] == "default"
    full = _origins(RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3, shape="any", mode=Mode.TRAINING,
                                   start_time="07:00"))
    assert full["shape"] == full["mode"] == full["start_time"] == "you said"  # "any" said out loud is not a default
    assert full["lights"] == "Training preset"


def test_describe_lines_carry_the_origin():
    lines = describe(RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3))
    assert "Shape: any (default)" in lines and "Distance: 3 mi (you said)" in lines
    assert "Start time: not set, so crowds are not scored (default)" in lines


def test_a_time_without_a_day_means_the_next_time_it_comes_round():
    from datetime import date, datetime

    from api.constraints import with_default_date

    c = RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3, start_time="07:00")
    morning = with_default_date(c, datetime(2026, 11, 3, 6, 30))  # a Tuesday, before 7
    assert morning.start_date == date(2026, 11, 3)
    assert with_default_date(c, datetime(2026, 11, 3, 7, 30)).start_date == date(2026, 11, 4)  # already past: tomorrow
    assert _origins(morning)["start_date"] == "default" and _origins(morning)["start_time"] == "you said"
    assert _origins(morning)["shape"] == "default"  # the copy keeps what was and wasn't said
    assert morning.start_moment() == datetime(2026, 11, 3, 7, 0)


def test_a_stated_day_or_no_time_is_left_alone():
    from datetime import date, datetime

    from api.constraints import with_default_date

    dated = RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3, start_time="07:00",
                           start_date=date(2026, 11, 7))
    assert with_default_date(dated, datetime(2026, 11, 3, 6, 0)) is dated
    assert _origins(dated)["start_date"] == "you said"
    untimed = RunConstraints(start_address="446 3rd Ave, 10016", distance_mi=3)
    assert with_default_date(untimed, datetime(2026, 11, 3, 6, 0)).start_date is None
