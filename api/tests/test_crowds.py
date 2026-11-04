from datetime import datetime

import pytest

from api.crowds import BANDS, band_for, counter_level, sample_times, summarize

TUE, SAT, SUN = datetime(2026, 11, 3), datetime(2026, 11, 7), datetime(2026, 11, 8)


@pytest.mark.parametrize("hour,band", [(7, "weekday_am"), (8, "weekday_am"), (9, "weekday_midday"), (15, "weekday_midday"),
                                       (16, "weekday_pm"), (18, "weekday_pm"), (19, "weekday_pm")])
def test_weekday_hours_map_to_dot_bands(hour, band):
    assert band_for(TUE.replace(hour=hour))[0] == band


@pytest.mark.parametrize("when,reason", [(TUE.replace(hour=6), "before 7am"), (TUE.replace(hour=20), "after 8pm"),
                                         (SUN.replace(hour=12), "Sundays"), (SAT.replace(hour=9), "Saturday")])
def test_hours_without_count_data_are_not_scored_never_quiet(when, reason):
    band, why = band_for(when)
    assert band is None and reason in why


def test_saturday_midday_has_its_own_band():
    assert band_for(SAT.replace(hour=12, minute=30))[0] == "saturday_midday"


def test_no_start_time_means_no_band():
    band, why = band_for(None)
    assert band is None and "start time" in why


def test_sample_times_advance_at_the_assumed_pace():
    times = sample_times(TUE.replace(hour=18, minute=50), [0, 1609.344, 3218.688], pace_min_per_mi=10)
    assert [t.strftime("%H:%M") for t in times] == ["18:50", "19:00", "19:10"]


def test_counter_levels_use_the_street_count_thresholds():
    th = {"medium": 300.0, "high": 900.0}
    assert counter_level(50, th) == "low" and counter_level(400, th) == "medium" and counter_level(1200, th) == "high"


def test_summary_is_shares_of_distance_and_counts_no_data_separately():
    s = summarize(["high"] * 2 + ["low"] * 6 + [None] * 2)
    assert (s["high_pct"], s["medium_pct"], s["low_pct"], s["not_scored_pct"]) == (20.0, 0.0, 60.0, 20.0)


def test_empty_route_summary_is_all_not_scored():
    assert summarize([])["not_scored_pct"] == 100.0


def test_a_stretch_takes_its_most_common_scored_level_as_an_estimate():
    from api.crowds import stretch_crowd

    pm = ("weekday 4-7pm (a DOT count window)", "weekday_pm")
    levels = [("high", *pm)] * 6 + [("low", *pm)] * 3 + [(None, "no crowd data for paths", None)]
    c = stretch_crowd(levels)
    assert c["value"] == "high" and c["status"] == "estimate" and c["high_pct"] == 60.0
    assert c["band"] == "weekday 4-7pm (a DOT count window)"


def test_a_stretch_mostly_without_data_is_not_scored_with_the_reason():
    from api.crowds import stretch_crowd

    levels = [(None, "no crowd data for paths", None)] * 7 + [("low", "weekday 7-9am (a DOT count window)", "weekday_am")] * 3
    c = stretch_crowd(levels)
    assert c["value"] is None and c["status"] == "not_scored" and c["basis"] == "no crowd data for paths"
    assert stretch_crowd([])["status"] == "not_scored"


def test_counter_stretches_name_the_counter_as_their_basis():
    from api.crowds import stretch_crowd

    c = stretch_crowd([("medium", "DOT automated pedestrian counter X: 120 people/hour", "counter")] * 4)
    assert c["value"] == "medium" and c["band"] == "DOT automated pedestrian counter (hourly)"


# --- decision 022: scheduled pulses on paths --------------------------------------------------


def test_a_path_sample_inside_a_pulse_window_is_high_and_names_the_cause():
    from datetime import datetime

    from api.crowds import pulse_level
    from api.pulses import Window

    w = {7: [Window(datetime(2026, 11, 4, 7, 58), datetime(2026, 11, 4, 8, 8), "SeaStreak arrival 08:00 at East 35th St")]}
    assert pulse_level(7, False, datetime(2026, 11, 4, 8, 3), w) == ("high", "SeaStreak arrival 08:00 at East 35th St", "pulse")
    assert pulse_level(7, False, datetime(2026, 11, 4, 8, 20), w) is None  # outside the window: stays not scored
    assert pulse_level(8, False, datetime(2026, 11, 4, 8, 3), w) is None  # another way
    assert pulse_level(7, True, datetime(2026, 11, 4, 8, 3), w) is None  # sidewalks keep decision 016's level
    assert pulse_level(7, False, None, w) is None  # no start time


def test_pulse_stretches_and_summaries_say_scheduled_pulse():
    from api.crowds import PULSE_LABEL, band_labels, stretch_crowd

    s = stretch_crowd([("high", "school arrival at X", "pulse")] * 3)
    assert s["value"] == "high" and s["band"] == PULSE_LABEL and s["basis"] == "school arrival at X"
    assert band_labels({"weekday_am", "pulse", "counter"}) == f"{BANDS['weekday_am'][2]}, {PULSE_LABEL}"
