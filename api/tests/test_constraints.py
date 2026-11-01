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
