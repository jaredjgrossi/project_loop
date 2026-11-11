import math

import pytest

from api.generate import (
    MAX_RESCALES,
    MAX_RETRACED_PCT,
    MIN_COMPACTNESS,
    OUT_AND_BACK_MIN_RETRACED_PCT,
    Anchors,
    Candidate,
    generate_loops,
    rectangle_corners,
    route_similarity,
)
from api.grid import GridEstimate
from api.nogo import NoGoZone, touched
from api.route_context import ContextScores
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


# Scoring moved to api/ranking.py (decision 010); its tests are in test_ranking.py.


# --- similarity ----------------------------------------------------------------------


def line(points_latlon):
    return [[lon, lat] for lat, lon in points_latlon]


def test_a_route_that_shares_only_its_way_out_is_not_a_duplicate():
    out_back = line([START, (START[0] + 0.01, START[1]), START])
    loop = line([START, (START[0] + 0.01, START[1]), (START[0] + 0.01, START[1] + 0.01), START])
    assert route_similarity(out_back, loop) < 0.8


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
    # Round trips are tried everywhere (decision 012); in tests about other generators they just fail to route.
    raise RoutingError("no round trips in this test")


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


def diamond_round_trip(calls=None):
    def round_trip(lat, lon, distance_m, seed=0):
        if calls is not None:
            calls.append(seed)
        # A diamond: not a grid shape, just a valid loop of about the requested length.
        d = distance_m / 4 / 1.4142 / M_LAT
        pts = [(lat, lon), (lat + d, lon + d / 2), (lat, lon + d), (lat - d, lon + d / 2), (lat, lon)]
        dense = densify(pts)
        length = sum(meters(a, b) for a, b in zip(dense, dense[1:]))
        return Route(distance_m=length, time_s=1, coordinates=line(dense), seed=seed)

    return round_trip


def test_weak_grid_tries_both_methods_and_says_so():
    # Neither method wins everywhere on weak grids, so both are generated and the shape score decides.
    rt_calls, rect_calls = [], []
    result = generate_loops(
        *START, miles=2.0, grid=WEAK, route_fn=make_router(calls=rect_calls), round_trip_fn=diamond_round_trip(rt_calls), top_n=40
    )
    assert rect_calls and rt_calls
    assert {c.method for c in result.candidates} == {"rectangle", "round_trip"}
    assert "weak" in result.note.lower()


def test_round_trips_are_tried_on_a_strong_grid_too():
    rt_calls = []
    generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=diamond_round_trip(rt_calls))
    assert rt_calls


def test_round_trips_win_when_no_rectangle_reaches_the_target():
    rt_calls = []
    ok_round_trip = diamond_round_trip(rt_calls)

    def short_rectangles(points):
        r = make_router()(points)
        return Route(distance_m=miles_to_meters(2.0) * 0.5, time_s=r.time_s, coordinates=r.coordinates)  # always 50% short

    result = generate_loops(*START, miles=2.0, grid=STRONG, route_fn=short_rectangles, round_trip_fn=ok_round_trip)
    assert rt_calls
    assert any(c.method == "round_trip" and c.within_tolerance for c in result.candidates)


def test_thin_ribbon_loops_are_rejected():
    def ribbon_router(points):
        # Out along one street and back along another 100 m away: nothing retraced, but a ribbon.
        a = points[0]
        far = (a[0] + 2000 / M_LAT, a[1])
        side = (a[0] + 2000 / M_LAT, a[1] + 100 / kx(a[0]))
        back = (a[0], a[1] + 100 / kx(a[0]))
        dense = densify([a, far, side, back, a])
        length = sum(meters(p, q) for p, q in zip(dense, dense[1:]))
        return Route(distance_m=length, time_s=1, coordinates=line(dense))

    result = generate_loops(*START, miles=2.6, grid=STRONG, route_fn=ribbon_router, round_trip_fn=lambda *a, **k: ribbon_router([(a[0], a[1])]))
    assert result.rejected["too_thin"] > 0
    assert all(c.shape.compactness >= MIN_COMPACTNESS for c in result.candidates)


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


def test_out_and_backs_are_generated_when_the_shape_allows_them():
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="out_and_back", top_n=3)
    assert result.candidates
    for c in result.candidates:
        assert c.kind == "out_and_back" and c.method == "out_and_back"
        assert c.shape.retraced_pct >= OUT_AND_BACK_MIN_RETRACED_PCT
        assert abs(c.miss_pct) <= 5


def test_out_and_back_turnaround_is_half_the_distance_out():
    calls = []
    generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(calls=calls), round_trip_fn=no_round_trips,
                   shape="out_and_back")
    first = calls[0]
    assert len(first) == 3 and first[0] == first[2] == START
    assert meters(first[0], first[1]) == pytest.approx(miles_to_meters(2.0), rel=0.01)


def test_any_shape_offers_both_kinds_in_the_top_three():
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="any", top_n=3)
    assert {c.kind for c in result.candidates} == {"loop", "out_and_back"}


def test_loop_only_requests_never_get_an_out_and_back():
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            top_n=10)
    assert {c.kind for c in result.candidates} == {"loop"}


def test_a_route_out_and_back_must_actually_come_back_the_same_way():
    def loop_router(points):
        # Asked for start -> turnaround -> start, returns a triangle instead.
        a, t = points[0], points[1]
        side = (t[0], a[1])
        dense = densify([a, t, side, a])
        length = sum(meters(p, q) for p, q in zip(dense, dense[1:]))
        return Route(distance_m=length, time_s=1, coordinates=line(dense))

    result = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=loop_router, round_trip_fn=no_round_trips,
                            shape="out_and_back")
    assert result.rejected["not_out_and_back"] > 0
    assert not result.candidates or all(c.kind == "out_and_back" for c in result.candidates)


def test_routes_through_a_no_go_zone_are_rejected():
    # A zone covering the whole area north-east of the start: every rectangle with a + side enters it.
    lat, lon = START
    rings = [[[lon + 0.0005, lat + 0.0005], [lon + 0.1, lat + 0.0005], [lon + 0.1, lat + 0.1], [lon + 0.0005, lat + 0.1],
              [lon + 0.0005, lat + 0.0005]]]
    zone = NoGoZone(id="test_zone", name="Test", aliases=(), default=True, reason="", source="", rings=rings)
    result = generate_loops(*START, miles=4.0, grid=GridEstimate(angle_deg=0.0, strength=0.95), route_fn=make_router(),
                            round_trip_fn=no_round_trips, avoid=[zone], top_n=10)
    assert result.rejected["no_go_zone"] > 0
    assert all(not touched(c.route.coordinates, [zone]) for c in result.candidates)



def test_routes_that_pass_through_a_known_closure_are_rejected():
    # Decision 017. A closure covering the north-east quadrant: every rectangle with a + side runs inside it.
    from api.closures import Closure, passed

    lat, lon = START
    big = [[[lon + 0.0005, lat + 0.0005], [lon + 0.1, lat + 0.0005], [lon + 0.1, lat + 0.1], [lon + 0.0005, lat + 0.1],
            [lon + 0.0005, lat + 0.0005]]]
    closed = Closure(1, "corridor_gap", "Test link", "no path", "test", "listed", big, in_router=False)
    result = generate_loops(*START, miles=4.0, grid=GridEstimate(angle_deg=0.0, strength=0.95), route_fn=make_router(),
                            round_trip_fn=no_round_trips, closures=[closed], top_n=10)
    assert result.rejected["closure"] > 0
    assert result.candidates and not any(passed(c.route.coordinates, [closed]) for c in result.candidates)


def test_candidates_carry_a_labeled_ranking():
    c = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips).candidates[0]
    assert c.ranking is not None
    assert c.score == c.ranking.score
    assert {d.status for d in c.ranking.dimensions} <= {"measured", "estimate", "not_scored"}


def test_result_records_what_was_tried():
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips)
    assert result.generated >= 12
    assert result.grid == STRONG
    assert isinstance(result.candidates[0], Candidate)
    assert isinstance(shape_metrics(result.candidates[0].route.coordinates), ShapeMetrics)


def test_context_is_scored_for_every_candidate_when_provided():
    seen = []

    def context_fn(coords):
        seen.append(len(coords))
        return ContextScores(park_pct=0, waterfront_pct=0, park_or_water_pct=40, crossings_per_mile=5,
                             signals_per_mile=3, familiar_pct=None)

    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            context_fn=context_fn)
    assert seen
    by = {d.key: d for d in result.candidates[0].ranking.dimensions}
    assert by["park_water"].status == "measured" and by["signals"].status == "measured"


def corridor_north(entry_m=300, step_m=100, n=40):
    """A familiar corridor running north from a point 300 m east of the start."""
    lat, lon = START
    entry = (lat, lon + entry_m / kx(lat))
    pts = [(lat + k * step_m / M_LAT, entry[1], math.hypot(entry_m, k * step_m)) for k in range(1, n)]
    return Anchors(entry=entry, directions=[pts])


def test_familiar_out_and_backs_go_through_the_corridor_entry_and_turn_on_the_corridor():
    anchors = corridor_north()
    calls = []
    result = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(calls=calls),
                            round_trip_fn=no_round_trips, shape="out_and_back", anchor_fn=lambda *a: [anchors], top_n=40)
    familiar = [c for c in calls if len(c) == 5]  # plain out-and-backs send 3 points
    assert familiar
    corridor_points = {p[:2] for p in anchors.directions[0]}
    for c in familiar:
        assert c[0] == c[4] == START and c[1] == c[3] == anchors.entry
        assert c[2] in corridor_points  # rescaling picks another corridor point, never one off the corridor
    best = next(c for c in result.candidates if c.method == "familiar_out_and_back")
    assert abs(best.miss_pct) <= 5


def test_no_corridors_means_no_familiar_candidates():
    result = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="any", anchor_fn=lambda *a: [Anchors(entry=None, directions=[])], top_n=40)
    assert all(c.method != "familiar_out_and_back" for c in result.candidates)


# --- anchored routes from OSM features (decision 012) -------------------------------------------


def park_east(source="park", name="Test Park"):
    """A park 400 m east of the start, with path points spread north and south of its entry."""
    lat, lon = START
    entry = (lat, lon + 400 / kx(lat))
    pts = [(lat + k * 100 / M_LAT, entry[1] + 150 / kx(lat), math.hypot(550, k * 100)) for k in range(1, 30)]
    return Anchors(entry=entry, directions=[pts], source=source, name=name)


def test_feature_anchors_give_out_and_backs_and_loops_through_the_feature():
    anchors = park_east()
    calls = []
    result = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(calls=calls),
                            round_trip_fn=no_round_trips, shape="any", feature_anchor_fn=lambda *a: [anchors], top_n=60)
    out_back = [c for c in calls if len(c) == 5 and c[1] == c[3] == anchors.entry]
    loops = [c for c in calls if len(c) == 4 and c[1] == anchors.entry]
    assert out_back and loops
    methods = {c.method for c in result.candidates}
    assert "park_out_and_back" in methods
    assert any(m == "park_loop" for m in methods)
    assert any("through Test Park" in c.label for c in result.candidates)


def lollipop_router(points):
    """Goes out along the anchor's access path and loops back through it: out 500 m, around a 600 m loop, back."""
    a = points[0]
    stick = (a[0], a[1] + 500 / kx(a[0]))
    corner1 = (a[0] + 300 / M_LAT, stick[1])
    corner2 = (a[0] + 300 / M_LAT, stick[1] + 300 / kx(a[0]))
    corner3 = (a[0], stick[1] + 300 / kx(a[0]))
    dense = densify([a, stick, corner1, corner2, corner3, stick, a])
    length = sum(meters(p, q) for p, q in zip(dense, dense[1:]))
    return Route(distance_m=length, time_s=1, coordinates=line(dense))


def test_an_anchored_loop_that_comes_back_partly_the_same_way_is_a_lollipop():
    miles = lollipop_router([START]).distance_m / 1609.344
    result = generate_loops(*START, miles=miles, grid=STRONG, route_fn=lollipop_router, round_trip_fn=no_round_trips,
                            shape="any", feature_anchor_fn=lambda *a: [park_east()], top_n=60)
    lollipops = [c for c in result.candidates if c.kind == "lollipop"]
    assert lollipops
    keys = {d.key for d in lollipops[0].ranking.dimensions}
    assert "retrace" not in keys and "loop_shape" not in keys  # ranked like an out-and-back


def test_shape_filters_apply_to_anchored_routes():
    as_loop = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                             shape="loop", feature_anchor_fn=lambda *a: [park_east()], top_n=60)
    assert all(c.kind in ("loop", "lollipop") for c in as_loop.candidates)
    as_oab = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="out_and_back", feature_anchor_fn=lambda *a: [park_east()], top_n=60)
    assert {c.kind for c in as_oab.candidates} == {"out_and_back"}


def test_feature_anchors_are_used_without_the_runners_own_routes():
    # The OSM generators never need anchor_fn (the runner prior); they run on their own.
    result = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="any", feature_anchor_fn=lambda *a: [park_east(source="water", name="waterfront")],
                            anchor_fn=None, top_n=60)
    assert any(c.method.startswith("water_") for c in result.candidates)
    assert all(not c.method.startswith("familiar") for c in result.candidates)


def test_a_feature_too_small_for_the_distance_is_run_through_and_past():
    # A short corridor: points only up to ~600 m from the start. A 3 mi out-and-back must keep going past its end.
    lat, lon = START
    entry = (lat, lon + 300 / kx(lat))
    pts = [(lat + k * 100 / M_LAT, entry[1], math.hypot(300, k * 100)) for k in range(1, 6)]
    short = Anchors(entry=entry, directions=[pts], source="corridor", name="Short Path")
    calls = []
    result = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(calls=calls),
                            round_trip_fn=no_round_trips, shape="out_and_back", feature_anchor_fn=lambda *a: [short], top_n=60)
    through = [c for c in calls if pts[-1][:2] in c and len(c) == 7]  # start, entry, far, beyond, far, entry, start
    assert through
    best = next(c for c in result.candidates if c.method == "corridor_out_and_back")
    assert abs(best.miss_pct) <= 5
    assert "and beyond" in best.label


def test_anchored_routes_are_routed_with_a_preference_for_the_feature_area():
    area = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    anchors = Anchors(entry=park_east().entry, directions=park_east().directions, source="park", name="Test Park", area=area)
    seen = []

    def area_route_fn(points, feature_area):
        seen.append(feature_area)
        return make_router()(points)

    generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips, shape="any",
                   feature_anchor_fn=lambda *a: [anchors], area_route_fn=area_route_fn, top_n=60)
    assert seen and all(a == area for a in seen)


def test_without_an_area_router_anchored_routes_use_the_plain_router():
    calls = []
    generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(calls=calls), round_trip_fn=no_round_trips,
                   shape="any", feature_anchor_fn=lambda *a: [park_east()], top_n=60)
    assert any(len(c) == 5 and c[1] == park_east().entry for c in calls)


def test_a_turnaround_past_the_feature_that_is_off_the_map_falls_back_to_the_far_end():
    lat, lon = START
    entry = (lat, lon + 300 / kx(lat))
    pts = [(lat + k * 100 / M_LAT, entry[1], math.hypot(300, k * 100)) for k in range(1, 6)]
    short = Anchors(entry=entry, directions=[pts], source="water", name="waterfront")
    plain = make_router()
    calls = []

    def no_points_in_the_river(points):
        calls.append(points)
        if len(points) == 7:  # the "and beyond" request: start, entry, far end, beyond, far end, entry, start
            raise RoutingError("Cannot find point 3")
        return plain(points)

    result = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=no_points_in_the_river, round_trip_fn=no_round_trips,
                            shape="out_and_back", feature_anchor_fn=lambda *a: [short], top_n=60)
    fallback = [c for i, c in enumerate(calls) if len(c) == 5 and i > 0 and len(calls[i - 1]) == 7]
    assert fallback and all(c[2] == pts[-1][:2] for c in fallback)  # turned at the far end instead
    assert result.rejected["routing_failed"] == 0  # the candidate was kept, with its miss, not dropped


def test_turnarounds_are_picked_by_walking_distance_along_the_feature():
    # A U-shaped shore: points whose straight-line distance from the start shrinks again as you walk along it.
    lat, lon = START
    entry = (lat, lon + 200 / kx(lat))
    pts = []
    for along in range(100, 2401, 100):
        x, y = (along, 0) if along <= 1000 else ((1000, along - 1000) if along <= 1300 else (2300 - along, 300))
        p = (lat + y / M_LAT, entry[1] + x / kx(lat))
        pts.append((*p, meters(START, p), float(along)))
    shore = Anchors(entry=entry, directions=[pts], source="water", name="waterfront")
    calls = []
    generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(calls=calls), round_trip_fn=no_round_trips,
                   shape="out_and_back", feature_anchor_fn=lambda *a: [shore], top_n=60)
    first = next(c for c in calls if len(c) == 5 and c[1] == entry)
    turn = next(p for p in pts if p[:2] == first[2])
    access = 1.3 * meters(START, entry)
    # Out-and-back: access + along there and back should make 3 mi.
    assert turn[3] == pytest.approx(miles_to_meters(3.0) / 2 - access, abs=100)


def test_a_feature_too_short_one_way_is_run_both_ways_from_the_entry():
    # Waterfront 600 m each way from the entry, 300 m from the start: one branch tops out at 1.2 mi, both at 1.9 mi.
    lat, lon = START
    entry = (lat, lon + 300 / kx(lat))
    north = [(lat + k * 100 / M_LAT, entry[1], 0.0, float(k * 100)) for k in range(1, 7)]
    south = [(lat - k * 100 / M_LAT, entry[1], 0.0, float(k * 100)) for k in range(1, 7)]
    north = [(a, b, meters(START, (a, b)), d) for a, b, _, d in north]
    south = [(a, b, meters(START, (a, b)), d) for a, b, _, d in south]
    shore = Anchors(entry=entry, directions=[north, south], source="water", name="waterfront")
    calls = []
    result = generate_loops(*START, miles=1.7, grid=STRONG, route_fn=make_router(calls=calls), round_trip_fn=no_round_trips,
                            shape="out_and_back", feature_anchor_fn=lambda *a: [shore], top_n=60)
    both = [c for c in calls if len(c) == 7 and c[1] == c[3] == c[5] == entry]
    assert both  # start, entry, north turn, entry, south turn, entry, start
    best = next(c for c in result.candidates if "both ways" in c.label)
    assert abs(best.miss_pct) <= 5


# --- order, streaming, timing and the candidate pool (decision 014) ------------------------------------


def test_anchored_routes_are_generated_before_the_geometric_ones():
    order = []

    def recording_router(points):
        order.append("anchored" if len(points) in (5, 7) and points[1] == park_east().entry else "geometric")
        return make_router()(points)

    generate_loops(*START, miles=3.0, grid=STRONG, route_fn=recording_router, round_trip_fn=no_round_trips,
                   shape="any", feature_anchor_fn=lambda *a: [park_east()], workers=1)
    first_geometric = order.index("geometric")
    assert order[:first_geometric] and set(order[:first_geometric]) == {"anchored"}


def test_candidates_are_streamed_as_they_pass_the_rules():
    streamed = []
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            on_candidate=lambda c, s: streamed.append((c, s)))
    assert streamed and all(isinstance(c, Candidate) for c, _ in streamed)
    assert [s for _, s in streamed] == sorted(s for _, s in streamed)
    assert {id(c) for c in result.candidates} <= {id(c) for c, _ in streamed}


def test_timing_reports_first_candidate_winner_and_total():
    t = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips).timing
    assert 0 <= t["first_candidate_s"] <= t["winner_arrived_s"] <= t["total_s"]


def test_the_pool_holds_every_job_with_metric_vectors_and_reasons():
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="any", top_n=3)
    pool = result.pool
    assert len(pool) == result.generated
    chosen = [e for e in pool if e["status"] == "chosen"]
    assert len(chosen) == len(result.candidates)
    for e in pool:
        if e["status"] == "rejected":
            assert e["reason"]
        else:
            assert {"turns_per_mile", "retraced_pct", "distance_m", "miss_pct"} <= set(e["metrics"])
            assert all(d["status"] in ("measured", "estimate", "not_scored") for d in e["dimensions"])
    assert sum(e["status"] == "rejected" for e in pool) == sum(result.rejected.values())


def test_feature_anchor_sources_can_be_several_functions():
    result = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="any", feature_anchor_fn=[lambda *a: [park_east()],
                                                            lambda *a: [park_east(source="water", name="waterfront")]],
                            top_n=80)
    methods = {e["method"].split("_")[0] for e in result.pool}  # same geometry, so the copies dedupe in the top list
    assert {"park", "water"} <= methods


def test_a_job_that_crashes_is_recorded_and_never_hangs_generation():
    # Decision 015: an unexpected exception in a worker used to kill the thread and leave generation waiting forever.
    def broken_anchors(*a):
        raise ValueError("database went away")

    result = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="any", feature_anchor_fn=[broken_anchors], top_n=3)
    assert result.candidates  # the other jobs still ran
    assert result.rejected["error: ValueError"] == 1
    assert any(e["status"] == "rejected" and "database went away" in e["label"] for e in result.pool)


def test_a_crashing_candidate_job_is_recorded_too():
    calls = {"n": 0}
    good = make_router()

    def sometimes_broken(points):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyError("paths")
        return good(points)

    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=sometimes_broken, round_trip_fn=no_round_trips)
    assert result.rejected["error: KeyError"] == 1 and result.candidates


def test_metric_vector_keeps_the_crowd_band_text_and_labels_crowds_an_estimate():
    from api.route_context import ContextScores

    busy = ContextScores(park_pct=0, waterfront_pct=0, park_or_water_pct=40, crossings_per_mile=5, signals_per_mile=3,
                         familiar_pct=None, crowd_high_pct=12.34, crowd_medium_pct=20.0, crowd_low_pct=60.0,
                         crowd_not_scored_pct=7.66, crowd_band="weekday 4-7pm (a DOT count window)")
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="any", top_n=1, context_fn=lambda coords: busy)
    vec = result.candidates[0].metric_vector()
    assert vec["crowd_band"] == "weekday 4-7pm (a DOT count window)" and vec["crowd_high_pct"] == 12.3
    assert vec["crowd_status"] == "estimate"


def test_best_of_counts_distinct_routes_within_the_distance_limit():
    # Decision 020: "Best of N" counts routes that passed every rule within the limit, without duplicates.
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="any", top_n=3)
    in_limit = [e for e in result.pool if e["status"] in ("chosen", "ranked")]
    assert result.best_of is not None
    assert len(result.candidates) <= result.best_of <= len(in_limit)


def test_the_same_route_twice_counts_once_in_best_of():
    # Two anchor sources that return the same park give identical routes: one route to choose from, not two.
    one = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                         shape="any", feature_anchor_fn=[lambda *a: [park_east()]], top_n=80)
    two = generate_loops(*START, miles=3.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                         shape="any", feature_anchor_fn=[lambda *a: [park_east()],
                                                         lambda *a: [park_east(source="water", name="waterfront")]],
                         top_n=80)
    assert sum(e["status"] in ("chosen", "ranked") for e in two.pool) > sum(
        e["status"] in ("chosen", "ranked") for e in one.pool)
    assert two.best_of == one.best_of


def test_no_route_within_the_limit_has_no_best_of():
    base = make_router()

    def stubborn(points):  # always about 30% short, as in the tolerance test above
        r = base(points)
        return Route(distance_m=miles_to_meters(4.0) * 0.7, time_s=r.time_s, coordinates=r.coordinates)

    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=stubborn, round_trip_fn=no_round_trips, top_n=3)
    assert not result.within_tolerance and result.best_of is None


def test_outcomes_come_back_in_plan_order_whatever_order_they_finish_in():
    # Decision 018: score ties are broken by plan order, so the top 3 doesn't depend on which thread finished first.
    import time as _time

    from api.generate import Rejection, _run_prioritized

    def finishing_after(seconds, label):
        def job():
            _time.sleep(seconds)
            return Rejection("test", label, "x")
        return job

    def lookup():  # like an anchor lookup: returns further jobs, which finish in reverse order
        _time.sleep(0.01)
        return [(1, finishing_after(0.06, "b0")), (1, finishing_after(0.0, "b1"))]

    jobs = [(0, lookup), (1, finishing_after(0.04, "a")), (1, finishing_after(0.0, "c"))]
    for _ in range(3):
        labels = [o.label for o, _ in _run_prioritized(jobs, workers=4, on_candidate=None)]
        assert labels == ["b0", "b1", "a", "c"]


def test_the_tier_callback_fires_once_when_the_early_tiers_are_done():
    # Decision 018: the provisional top 3 is flagged once every job of priority <= tier_max has finished.
    import time as _time

    from api.generate import Rejection, _run_prioritized

    done = []

    def job(label, seconds):
        def run():
            _time.sleep(seconds)
            done.append(label)
            return Rejection("test", label, "x")
        return run

    fired = []
    jobs = [(0, lambda: [(1, job("anchored", 0.03))]), (4, job("rectangle", 0.15)), (5, job("round trip", 0.15))]
    _run_prioritized(jobs, workers=3, on_candidate=None, tier_max=2,
                     on_tier_done=lambda s: fired.append((s, list(done))))
    assert len(fired) == 1
    assert fired[0][1] == ["anchored"]  # the later tiers hadn't finished when the flag fired


def test_the_streamed_top3_ends_as_the_final_top3_and_is_sent_only_when_it_changes():
    events = []
    result = generate_loops(*START, miles=4.0, grid=STRONG, route_fn=make_router(), round_trip_fn=no_round_trips,
                            shape="any", top_n=3, on_top3=events.append)
    kinds = [e["event"] for e in events]
    assert kinds.count("provisional") == 1 and kinds[-1] == "final"
    assert [id(c) for c in events[-1]["candidates"]] == [id(c) for c in result.candidates]
    updates = [e for e in events if e["event"] == "top3"]
    assert all([id(c) for c in a["candidates"]] != [id(c) for c in b["candidates"]] for a, b in zip(updates, updates[1:]))
    assert result.timing["provisional_s"] is not None and result.timing["provisional_s"] <= result.timing["total_s"]
    assert result.timing["number1_changes_after_provisional"] >= 0
    assert [c.label for c in result.provisional] == [c.label for c in next(e for e in events if e["event"] == "provisional")["candidates"]]


def test_a_failing_stream_callback_raises_instead_of_hanging():
    """A callback that raises used to kill its worker thread, so the queue never drained and the build hung."""
    import threading

    from api.tests.test_a_to_b import GRID, KIPS, straight_route

    def boom(c, elapsed):
        raise KeyError("source")
    outcome = {}

    def run():
        try:
            generate_loops(KIPS[0], KIPS[1], 3.0, GRID, route_fn=straight_route, round_trip_fn=None, top_n=3,
                           on_candidate=boom)
        except KeyError as exc:
            outcome["raised"] = exc
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=60)
    assert not t.is_alive(), "the build hung"
    assert "raised" in outcome


# ---- spurs, honest kinds, loop as a hard rule (decision 044) -------------------------------------------------------

def test_a_route_padded_with_a_spur_is_rejected():
    from api.constraints import DEFAULTS
    from api.generate import Rejection, _evaluate, _Rules
    from api.routing import Route
    from api.tests.test_markers import SPUR_ROUTE
    from api.geometry import line_length_m
    route = Route(distance_m=line_length_m(SPUR_ROUTE), time_s=0, coordinates=SPUR_ROUTE)
    got = _evaluate("t", None, "t", route, _Rules(route.distance_m / 1609.344, DEFAULTS, ()),
                    allowed=("loop", "lollipop", "out_and_back"))
    assert isinstance(got, Rejection) and got.reason == "spur"


def test_mostly_retraced_is_an_out_and_back_and_loop_rules_it_out_but_keeps_it():
    from api.constraints import DEFAULTS
    from api.generate import Candidate, Rejection, SHAPE_KINDS, _evaluate, _Rules
    from api.routing import Route
    from api.geometry import line_length_m
    from api.tests.test_markers import _path
    # 1.6 km up a street, a 400 m square at the top, and back: about 80% retraced
    coords = _path((0, 0), (0, 1600), (200, 1600), (200, 1800), (0, 1800), (0, 1600), (0, 0))
    route = Route(distance_m=line_length_m(coords), time_s=0, coordinates=coords)
    rules = _Rules(route.distance_m / 1609.344, DEFAULTS, ())
    as_any = _evaluate("t", None, "t", route, rules, allowed=SHAPE_KINDS["any"])
    assert isinstance(as_any, Candidate) and as_any.kind == "out_and_back"
    as_loop = _evaluate("t", None, "t", route, rules, allowed=SHAPE_KINDS["loop"])
    assert isinstance(as_loop, Rejection) and as_loop.reason == "unwanted_out_and_back"
    assert as_loop.candidate is not None and as_loop.candidate.kind == "out_and_back"
    assert SHAPE_KINDS["loop"] == ("loop",)  # no lollipops either
