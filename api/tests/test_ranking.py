import pytest

from api.constraints import DEFAULTS, PRESETS, Lights, Mode
from api.ranking import NOT_YET_SCORED, rank, weights_for
from api.route_context import ContextScores
from api.shape import ShapeMetrics


def metrics(**kw):
    base = dict(
        distance_miles=4.0, turns=8, turns_per_mile=2.0, longest_straight_m=1500, pct_in_long_runs=90.0,
        retraced_pct=0.0, mean_width_m=500.0, compactness=0.6,
    )
    return ShapeMetrics(**{**base, **kw})


def out_and_back(**kw):
    return metrics(**{"retraced_pct": 95.0, "mean_width_m": None, "compactness": None, **kw})


def test_score_is_bounded():
    r = rank("loop", metrics(), DEFAULTS)
    assert 0 <= r.score <= 100
    worst = rank("loop", metrics(turns_per_mile=40, pct_in_long_runs=0, retraced_pct=60, compactness=0.0), DEFAULTS)
    best = rank("loop", metrics(turns_per_mile=1, pct_in_long_runs=100, retraced_pct=0, compactness=0.8), DEFAULTS)
    assert worst.score == pytest.approx(0, abs=1)
    assert best.score == pytest.approx(100, abs=1)


def test_every_dimension_is_labeled():
    for kind, m in (("loop", metrics()), ("out_and_back", out_and_back())):
        for d in rank(kind, m, DEFAULTS).dimensions:
            assert d.status in ("measured", "estimate", "not_scored")
            if d.status == "not_scored":
                assert d.fit is None and d.weight == 0
            else:
                assert 0 <= d.fit <= 1 and d.weight > 0 and d.value


def test_dimensions_without_data_are_listed_as_not_scored_not_dropped():
    keys = {d.key for d in rank("loop", metrics(), DEFAULTS).not_scored()}
    assert set(NOT_YET_SCORED) <= keys


def test_out_and_back_is_not_penalized_for_retracing_or_shape():
    keys = {d.key for d in rank("out_and_back", out_and_back(), DEFAULTS).scored()}
    assert "retrace" not in keys and "loop_shape" not in keys
    # Same turns and straight runs: the out-and-back is not marked down for being an out-and-back.
    loop = rank("loop", metrics(compactness=0.8, retraced_pct=0, pct_in_long_runs=90), DEFAULTS)
    oab = rank("out_and_back", out_and_back(pct_in_long_runs=90), DEFAULTS)
    assert oab.score == pytest.approx(loop.score, abs=10)


def test_loops_still_lose_points_for_retracing():
    assert rank("loop", metrics(retraced_pct=12), DEFAULTS).score < rank("loop", metrics(retraced_pct=0), DEFAULTS).score


def test_fewer_turns_scores_higher():
    s = [rank("loop", metrics(turns_per_mile=t), DEFAULTS).score for t in (2, 6, 13)]
    assert s[0] > s[1] > s[2]


def test_preferences_change_the_weights():
    fewer = weights_for({**DEFAULTS, "turns": "fewer"})
    dont = weights_for({**DEFAULTS, "turns": "dont_mind"})
    assert fewer["turns"] > dont["turns"]
    waits = weights_for({**DEFAULTS, "lights": Lights.WAITS})
    zig = weights_for({**DEFAULTS, "lights": Lights.ZIGZAGS})
    assert waits["straight"] > zig["straight"]


def test_a_turny_route_costs_a_training_runner_more_than_an_exploring_one():
    turny = metrics(turns_per_mile=8, pct_in_long_runs=20)
    straight = metrics(turns_per_mile=1.5, pct_in_long_runs=95)
    gap_training = rank("loop", straight, PRESETS[Mode.TRAINING]).score - rank("loop", turny, PRESETS[Mode.TRAINING]).score
    gap_exploring = rank("loop", straight, PRESETS[Mode.EXPLORING]).score - rank("loop", turny, PRESETS[Mode.EXPLORING]).score
    assert gap_training > gap_exploring > 0


def test_weights_are_marked_provisional():
    assert all(d.provisional for d in rank("loop", metrics(), DEFAULTS).scored())


# --- context dimensions (decision 011) ---------------------------------------------------


def ctx(**kw):
    base = dict(park_pct=0.0, waterfront_pct=0.0, park_or_water_pct=0.0, crossings_per_mile=8.0,
                signals_per_mile=8.0, familiar_pct=None)
    return ContextScores(**{**base, **kw})


def test_without_context_park_signals_and_familiar_are_not_scored():
    keys = {d.key for d in rank("loop", metrics(), DEFAULTS).not_scored()}
    assert {"park_water", "signals", "familiar"} <= keys


def test_with_context_they_are_measured():
    r = rank("loop", metrics(), DEFAULTS, ctx(park_or_water_pct=50, familiar_pct=20))
    by = {d.key: d for d in r.dimensions}
    for k in ("park_water", "signals", "familiar"):
        assert by[k].status == "measured" and by[k].weight > 0


def test_no_runs_on_file_leaves_familiar_not_scored_even_with_context():
    by = {d.key: d for d in rank("loop", metrics(), DEFAULTS, ctx()).dimensions}
    assert by["familiar"].status == "not_scored"


def test_park_and_water_raise_the_score_and_signals_lower_it():
    base = rank("loop", metrics(), DEFAULTS, ctx()).score
    assert rank("loop", metrics(), DEFAULTS, ctx(park_or_water_pct=70)).score > base
    assert rank("loop", metrics(), DEFAULTS, ctx(signals_per_mile=18)).score < base


def test_familiar_can_be_turned_up_or_reversed():
    known, unknown = ctx(familiar_pct=90), ctx(familiar_pct=5)
    favor = {**DEFAULTS, "familiar": "favor"}
    new = {**DEFAULTS, "familiar": "new"}
    assert rank("loop", metrics(), favor, known).score > rank("loop", metrics(), favor, unknown).score
    assert rank("loop", metrics(), new, known).score < rank("loop", metrics(), new, unknown).score
    assert weights_for(favor)["familiar"] > weights_for(DEFAULTS)["familiar"]


def test_signals_cost_a_runner_who_waits_more_than_a_zigzagger():
    assert weights_for({**DEFAULTS, "lights": Lights.WAITS})["signals"] > weights_for(DEFAULTS)["signals"]


def test_an_open_loop_has_no_loop_shape_dimension():
    # Trimmed routes (real or generated) are open, so compactness is unknown: leave it out rather than score it 0.
    keys = {d.key for d in rank("loop", metrics(compactness=None, mean_width_m=None), DEFAULTS).dimensions}
    assert "loop_shape" not in keys


def test_crowds_are_not_scored_without_a_band_at_the_start():
    for c in (ctx(), ctx(crowd_high_pct=0, crowd_medium_pct=0, crowd_low_pct=0, crowd_not_scored_pct=100,
                     crowd_reason="no count data on Sundays")):
        by = {d.key: d for d in rank("loop", metrics(), DEFAULTS, c).dimensions}
        assert by["crowds"].status == "not_scored" and by["crowds"].weight == 0
    assert by["crowds"].value == "no count data on Sundays"


def pm(**kw):
    return ctx(crowd_band="weekday 4-7pm (a DOT count window)", crowd_start_band="weekday_pm", **kw)


def test_crowds_are_an_estimate_and_busy_routes_score_lower():
    quiet = pm(crowd_high_pct=0, crowd_medium_pct=10, crowd_low_pct=80, crowd_not_scored_pct=10)
    busy = pm(crowd_high_pct=60, crowd_medium_pct=20, crowd_low_pct=10, crowd_not_scored_pct=10)
    by = {d.key: d for d in rank("loop", metrics(), DEFAULTS, busy).dimensions}
    assert by["crowds"].status == "estimate" and "busy" in by["crowds"].value
    assert rank("loop", metrics(), DEFAULTS, quiet).score > rank("loop", metrics(), DEFAULTS, busy).score


def test_distance_without_crowd_data_is_neutral_and_only_busy_distance_costs():
    # Decision 016: a mostly-path route keeps the crowds weight, so a street route can't win just by being scorable,
    # and no-data distance costs nothing, so a path route doesn't lose to a street route that is no less crowded.
    paths = pm(crowd_high_pct=0, crowd_medium_pct=0, crowd_low_pct=20, crowd_not_scored_pct=80)
    quiet_street = pm(crowd_high_pct=0, crowd_medium_pct=0, crowd_low_pct=100, crowd_not_scored_pct=0)
    busy_street = pm(crowd_high_pct=40, crowd_medium_pct=30, crowd_low_pct=30, crowd_not_scored_pct=0)
    dim = lambda c: {d.key: d for d in rank("loop", metrics(), DEFAULTS, c).dimensions}["crowds"]
    assert dim(paths).weight == dim(quiet_street).weight > 0
    assert dim(paths).fit == dim(quiet_street).fit == 1.0
    assert dim(busy_street).fit == pytest.approx(0.6)
    assert "neither quiet nor busy" in dim(paths).value


def test_avoiding_crowds_weighs_them_more_and_other_weights_are_unchanged():
    avoid, some = weights_for({**DEFAULTS, "crowds": "avoid"}), weights_for({**DEFAULTS, "crowds": "some"})
    assert avoid["crowds"] > some["crowds"] > weights_for({**DEFAULTS, "crowds": "dont_mind"})["crowds"]
    assert {k: v for k, v in avoid.items() if k != "crowds"} == {k: v for k, v in some.items() if k != "crowds"}
