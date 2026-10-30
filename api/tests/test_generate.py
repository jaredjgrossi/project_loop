import math

import pytest

from api.generate import (
    MAX_RESCALES,
    MAX_RETRACED_PCT,
    Candidate,
    generate_loops,
    rectangle_corners,
    route_similarity,
    shape_score,
)
from api.grid import GridEstimate
from api.routing import Route, RoutingError
from api.shape import ShapeMetrics, shape_metrics
from api.units import miles_to_meters

START = (40.7415, -73.9865)
STRONG = GridEstimate(angle_deg=29.0, strength=0.95)
WEAK = GridEstimate(angle_deg=0.0, strength=0.2)
M_LAT = 110_574


def kx(lat):
    return 111_320 * math.cos(math.radians(lat))


def to_xy(p, origin=START):
    return ((p[1] - origin[1]) * kx(origin[0]), (p[0] - origin[0]) * M_LAT)


def bearing(a, b):
    (x0, y0), (x1, y1) = to_xy(a), to_xy(b)
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360


def meters(a, b):
    (x0, y0), (x1, y1) = to_xy(a), to_xy(b)
    return math.hypot(x1 - x0, y1 - y0)


# --- rectangle geometry ------------------------------------------------------------


def test_rectangle_has_right_angles_and_requested_sides_along_the_grid():
    pts = rectangle_corners(START, 29.0, len_a=1500, len_b=600, sign_a=1, sign_b=1)
    assert len(pts) == 5 and pts[0] == pts[-1] == START
    assert meters(pts[0], pts[1]) == pytest.approx(1500, rel=0.01)
    assert meters(pts[1], pts[2]) == pytest.approx(600, rel=0.01)
    assert bearing(pts[0], pts[1]) == pytest.approx(29, abs=0.5)
    assert bearing(pts[1], pts[2]) == pytest.approx(119, abs=0.5)
    assert bearing(pts[3], pts[2]) == pytest.approx(29, abs=0.5)  # opposite sides are parallel


def test_signs_flip_the_direction_of_each_side():
    pts = rectangle_corners(START, 29.0, 1000, 500, sign_a=-1, sign_b=-1)
    assert bearing(pts[0], pts[1]) == pytest.approx(209, abs=0.5)
    assert bearing(pts[1], pts[2]) == pytest.approx(299, abs=0.5)


def test_four_sign_combinations_give_four_different_rectangles():
    corners = {
        rectangle_corners(START, 29.0, 1000, 500, sa, sb)[2]
        for sa in (1, -1)
        for sb in (1, -1)
    }
    assert len(corners) == 4


# --- scoring -------------------------------------------------------------------------


def metrics(**kw):
    base = dict(
        distance_miles=4.0, turns=8, turns_per_mile=2.0, longest_straight_m=1500, pct_in_long_runs=90.0,
        retraced_pct=0.0, mean_width_m=500.0, compactness=0.6,
    )
    return ShapeMetrics(**{**base, **kw})


def test_score_is_bounded():
    assert 0 <= shape_score(metrics()) <= 100
    worst = metrics(turns_per_mile=40, pct_in_long_runs=0, retraced_pct=60, compactness=0.0)
    assert shape_score(worst) == pytest.approx(0, abs=1)
    best = metrics(turns_per_mile=1, pct_in_long_runs=100, retraced_pct=0, compactness=0.8)
    assert shape_score(best) == pytest.approx(100, abs=1)


def test_fewer_turns_scores_higher():
    assert shape_score(metrics(turns_per_mile=2)) > shape_score(metrics(turns_per_mile=6)) > shape_score(metrics(turns_per_mile=13))


def test_a_ribbon_scores_below_a_compact_loop_with_the_same_turns():
    assert shape_score(metrics(compactness=0.2)) < shape_score(metrics(compactness=0.65))


def test_retracing_lowers_the_score():
    assert shape_score(metrics(retraced_pct=20)) < shape_score(metrics(retraced_pct=0))


def test_open_route_without_compactness_still_scores():
    assert 0 <= shape_score(metrics(compactness=None, mean_width_m=None)) <= 100


# --- similarity ----------------------------------------------------------------------


def line(points_latlon):
    return [[lon, lat] for lat, lon in points_latlon]


def test_identical_routes_are_fully_similar_and_distant_ones_are_not():
    a = rectangle_corners(START, 29, 1000, 500, 1, 1)
    far = rectangle_corners((START[0] + 0.1, START[1]), 29, 1000, 500, 1, 1)
    assert route_similarity(line(a), line(a)) == pytest.approx(1.0)
    assert route_similarity(line(a), line(far)) == pytest.approx(0.0)


# --- a fake router: follows the waypoints, with a detour factor ----------------------------


def densify(points_latlon, step_m=40):
    out = [points_latlon[0]]
    for a, b in zip(points_latlon, points_latlon[1:]):
        n = max(1, int(meters(a, b) // step_m))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(1, n + 1)]
    return out


def make_router(detour=1.0, calls=None):
    def route_fn(points):
        if calls is not None:
            calls.append(points)
        dense = densify(list(points))
        length = sum(meters(a, b) for a, b in zip(dense, dense[1:])) * detour
        return Route(distance_m=length, time_s=length / 1.4, coordinates=line(dense))

    return route_fn


def no_round_trips(*a, **k):
    raise AssertionError("round_trip should not be needed here")


# --- generation ----------------------------------------------------------------------


def test_rectangles_are_rescaled_until_the_distance_is_within_tolerance():
    # The router adds a 20% detour, so the first attempt is long and must be shrunk.
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(detour=1.2), round_trip_fn=no_round_trips)
    assert result.within_tolerance
    best = result.candidates[0]
    assert abs(best.miss_pct) <= 5
    assert best.method == "rectangle"


def test_distance_rescaling_is_bounded():
    calls = []
    generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(detour=1.2, calls=calls), round_trip_fn=no_round_trips)
    rectangle_specs = 4 + 8 + 8  # 1:1 has no transposed form; 1.5:1 and 2.5:1 have both
    assert len(calls) <= rectangle_specs * (MAX_RESCALES + 1)


def test_returns_top_n_distinct_loops_best_score_first():
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips, top_n=3)
    cands = result.candidates
    assert 1 <= len(cands) <= 3
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            assert route_similarity(a.route.coordinates, b.route.coordinates) < 0.8


def test_candidates_report_their_shape():
    c = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips).candidates[0]
    assert c.shape.turns_per_mile < 3  # a rectangle
    assert c.shape.compactness > 0.4
    assert c.score > 60


def test_out_and_back_routes_are_rejected_as_retraced():
    def retracing_router(points):
        # Ignore the rectangle: go straight out and back along one line.
        a, b = points[0], (points[0][0] + 0.02, points[0][1])
        dense = densify([a, b, a])
        length = sum(meters(p, q) for p, q in zip(dense, dense[1:]))
        return Route(distance_m=length, time_s=1, coordinates=line(dense))

    result = generate_loops(*START, miles=2.0, grid=STRONG, route_fn=retracing_router, round_trip_fn=lambda *a, **k: retracing_router([(a[0], a[1])]))
    assert not result.candidates or all(c.shape.retraced_pct <= MAX_RETRACED_PCT for c in result.candidates)
    assert result.rejected["retraced"] > 0


def test_routing_errors_drop_that_candidate_but_not_the_run():
    state = {"n": 0}
    good = make_router()

    def flaky(points):
        state["n"] += 1
        if state["n"] % 2:
            raise RoutingError("Cannot find point 1")
        return good(points)

    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=flaky, round_trip_fn=no_round_trips)
    assert result.rejected["routing_failed"] > 0
    assert result.candidates


def test_weak_grid_skips_rectangles_and_uses_round_trips():
    def must_not_run(points):
        raise AssertionError("rectangles need a street grid")

    def round_trip(lat, lon, distance_m, seed=0):
        # A diamond: not a grid shape, just a valid loop of about the requested length.
        side = distance_m / 4 / 1.0
        d = side / 1.4142 / M_LAT
        pts = [(lat, lon), (lat + d, lon + d / 2), (lat, lon + d), (lat - d, lon + d / 2), (lat, lon)]
        dense = densify(pts)
        length = sum(meters(a, b) for a, b in zip(dense, dense[1:]))
        return Route(distance_m=length, time_s=1, coordinates=line(dense), seed=seed)

    result = generate_loops(*START, miles=2.0, grid=WEAK, route_fn=must_not_run, round_trip_fn=round_trip)
    assert result.candidates
    assert {c.method for c in result.candidates} == {"round_trip"}
    assert "grid" in result.note.lower()


def test_when_nothing_meets_the_tolerance_the_nearest_is_returned_and_flagged():
    # The router returns routes that are always about 30% too short, whatever the corners say.
    base = make_router()

    def stubborn(points):
        r = base(points)
        return Route(distance_m=r.distance_m * 0.0 + miles_to_meters(4.0) * 0.7, time_s=r.time_s, coordinates=r.coordinates)

    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=stubborn, round_trip_fn=lambda *a, **k: stubborn([(a[0], a[1]), (a[0] + 0.01, a[1])]))
    assert not result.within_tolerance
    best = result.candidates[0]
    assert best.miss_pct == pytest.approx(-30, abs=1)
    assert "nearest" in result.note.lower()


def test_result_records_what_was_tried():
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips)
    assert result.generated >= 12
    assert result.grid == STRONG
    assert isinstance(result.candidates[0], Candidate)
    assert isinstance(shape_metrics(result.candidates[0].route.coordinates), ShapeMetrics)
