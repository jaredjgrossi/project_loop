"""Around or through (decision 035): Claude records the word, code sets the mode."""

import json

import pytest

from api.loops import CURATED, loop_named, loops, mode_for, word_mode


@pytest.mark.parametrize("word, mode", [
    ("around", "around"), ("Loop of", "around"), ("lap of", "around"), ("2 laps around", "around"),
    ("a loop around", "around"), ("circle", "around"), ("through", "through"), ("in", "through"),
    ("along", "through"), ("loop through", "through"), ("a loop in", "through"), ("", None), (None, None),
    ("past", "through"),
])
def test_the_word_sets_the_mode(word, mode):
    assert word_mode(word) == mode


def test_around_a_park_on_the_list_runs_its_loop():
    m = mode_for("loop of", "Prospect Park", "Prospect Park", "park")
    assert (m.mode, m.loop, m.cant) == ("around", "prospect_park_drive", None)
    assert m.name == "the Prospect Park drive loop"


def test_the_reservoir_named_on_its_own_is_its_track():
    m = mode_for(None, "Central park reservor", "Central Park Reservoir", "water")
    assert (m.mode, m.loop) == ("around", "reservoir")


def test_a_park_on_the_list_named_on_its_own_is_passed():
    assert mode_for(None, "Prospect Park", "Prospect Park", "park").mode == "through"  # "6 mi, Prospect Park"
    assert mode_for("in", "the park", "Prospect Park", "park").mode == "through"  # R09: "a few miles in the park"


def test_through_wins_over_the_list():
    assert mode_for("through", "the Reservoir", "Central Park Reservoir", "water").mode == "through"


def test_a_loop_s_own_name_means_its_lap():
    assert loop_named("the Prospect Park loop")["id"] == "prospect_park_drive"
    assert loop_named("Reservoir")["id"] == "reservoir"
    assert loop_named("Prospect Park") is None
    m = mode_for(None, "Central Park loop", "Central Park", "park")
    assert (m.mode, m.loop) == ("around", "central_park_drive")


def test_around_a_park_off_the_list_runs_its_outline():
    m = mode_for("around", "Tompkins Square Park", "Tompkins Square Park", "park")
    assert (m.mode, m.loop, m.name) == ("around", None, "Tompkins Square Park")


def test_a_lap_loop_can_t_run_is_said_and_passed():
    m = mode_for(None, "McCarren track", "McCarren Park", "park")
    assert (m.mode, m.cant, m.name) == ("through", "cant.lap_unrouted", "the McCarren Park track")


def test_around_a_street_is_said_and_passed():
    m = mode_for("around", "2nd Ave", "2nd Ave", "street")
    assert (m.mode, m.cant) == ("through", "cant.around_shape")


def test_every_curated_loop_has_a_length_a_source_and_a_direction():
    raw = json.loads(CURATED.read_text())["loops"]
    assert {lp["id"] for lp in raw} == {"reservoir", "central_park_drive", "prospect_park_drive", "mccarren_track"}
    for lp in loops():
        assert lp["published_mi"] > 0 and lp["source"].startswith("https://") and lp["direction"]
        assert lp["geometry"] is not None or lp["why_no_geometry"]
