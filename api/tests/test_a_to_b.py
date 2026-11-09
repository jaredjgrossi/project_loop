"""A-to-B routes (step 8, decision 032): the shortest-way check, then the direct route, detours through a waypoint, and
detours along a park, the waterfront or a corridor near either end. Routing is a fake: straight lines between the
points asked for, measured on the ground, so distances are easy to reason about."""

import math

import pytest

from api.anchors import Anchors
from api.a_to_b import ask_miles, ellipse_waypoint, generate_a_to_b, shorter_than_the_shortest_way
from api.grid import GridEstimate
from api.routing import Route
from api.units import meters_to_miles, miles_to_meters

KIPS = (40.7438, -73.9799)
EAST = (40.7438, -73.9400)  # 3.36 km due east
GRID = GridEstimate(angle_deg=29.0, strength=0.95)
M_LAT = 110_574


def meters(a, b):
    kx = 111_320 * math.cos(math.radians(a[0]))
    return math.hypot((b[1] - a[1]) * kx, (b[0] - a[0]) * M_LAT)


def straight_route(points, custom_model=None):
    """Straight lines, densified every ~50 m so shape metrics see real segments."""
    coords = []
    for a, b in zip(points, points[1:]):
        n = max(1, int(meters(a, b) // 50))
        coords += [[a[1] + (b[1] - a[1]) * k / n, a[0] + (b[0] - a[0]) * k / n] for k in range(n)]
    coords.append([points[-1][1], points[-1][0]])
    dist = sum(meters(a, b) for a, b in zip(points, points[1:]))
    return Route(distance_m=dist, time_s=dist / 1.4, coordinates=coords)


def area_route(points, area):
    return straight_route(points)


def run(miles, **kw):
    shortest = straight_route([KIPS, EAST])
    return generate_a_to_b(KIPS, EAST, miles, GRID, route_fn=straight_route, shortest=shortest, **kw)


def test_the_engine_asks_when_the_distance_is_shorter_than_the_shortest_way():
    shortest_m = miles_to_meters(4.23)
    assert shorter_than_the_shortest_way(3.0, 5, shortest_m)
    assert not shorter_than_the_shortest_way(4.1, 5, shortest_m)  # 4.1 mi + 5% reaches 4.23
    assert not shorter_than_the_shortest_way(None, 5, shortest_m)  # no distance: the shortest way it is
    assert ask_miles(shortest_m) == 4.3  # rounded up, so the answer is never shorter than the way there


def test_with_the_shortest_distance_the_direct_route_comes_back():
    shortest_mi = meters_to_miles(meters(KIPS, EAST))
    result = run(shortest_mi)
    assert result.candidates[0].method == "direct" and result.candidates[0].kind == "a_to_b"
    assert result.within_tolerance


def test_every_route_runs_from_the_start_to_the_end():
    result = run(4.0, top_n=10)
    assert result.candidates
    for c in result.candidates:
        first, last = c.route.coordinates[0], c.route.coordinates[-1]
        assert meters(KIPS, (first[1], first[0])) < 5 and meters(EAST, (last[1], last[0])) < 5
        assert c.kind == "a_to_b"


def test_a_longer_distance_is_met_with_detours():
    result = run(4.0, top_n=5)  # the direct way is 2.1 mi
    assert result.within_tolerance
    assert all(abs(c.miss_pct) <= 5 for c in result.candidates)
    assert {c.method for c in result.candidates} <= {"detour", "water_a_to_b", "park_a_to_b", "corridor_a_to_b"}


def test_the_ellipse_waypoint_keeps_the_straight_line_sum():
    """A waypoint on the ellipse with the start and end as foci: start-to-waypoint plus waypoint-to-end is 2a."""
    for angle in (45, 90, 135, 225, 270, 315):
        w = ellipse_waypoint(KIPS, EAST, total_m=6000, angle_deg=angle)
        assert meters(KIPS, w) + meters(w, EAST) == pytest.approx(6000, rel=0.01)


def waterfront_from_start():
    """A path running north from an entry 200 m east of the start: points every 100 m, with walking distance."""
    entry = (40.7438, -73.9775)
    pts = [(entry[0] + k * 100 / M_LAT, entry[1], meters(KIPS, (entry[0] + k * 100 / M_LAT, entry[1])), k * 100.0)
           for k in range(1, 40)]
    return Anchors(entry=entry, directions=[pts], source="water", name=None)


def test_a_detour_can_run_along_the_waterfront_near_the_start():
    result = run(4.0, top_n=10, feature_anchor_fn=[lambda lat, lon, r: [waterfront_from_start()]],
                 area_route_fn=area_route)
    water = [c for c in result.candidates if c.method == "water_a_to_b"]
    assert water, [c.label for c in result.candidates]
    assert water[0].label.startswith("along the waterfront")
    entry = waterfront_from_start().entry
    assert min(meters((lat, lon), entry) for lon, lat in water[0].route.coordinates) < 5


def test_a_route_that_doubles_back_is_rejected():
    def spur(points, custom_model=None):  # out 1 km north and back before heading east
        north = (KIPS[0] + 1000 / M_LAT, KIPS[1])
        return straight_route([KIPS, north, KIPS, EAST])
    result = generate_a_to_b(KIPS, EAST, 2.6, GRID, route_fn=spur, shortest=straight_route([KIPS, EAST]), top_n=10)
    assert result.rejected["retraced"] > 0
    assert result.candidates == []  # the direct way (2.1 mi) is too short for 2.6 mi, and every detour doubles back


def test_the_top_3_streams_and_each_candidate_is_reported():
    events, seen = [], []
    run(4.0, on_top3=events.append, on_candidate=lambda c, t: seen.append(c))
    assert events[0]["event"] == "top3" and events[-1]["event"] == "final"
    assert any(e["event"] == "provisional" for e in events)
    assert len(seen) >= 3


def test_no_loop_shape_score_on_an_a_to_b_route():
    c = run(4.0).candidates[0]
    keys = {d.key for d in c.ranking.dimensions}
    assert "loop_shape" not in keys and "retrace" not in keys and "turns" in keys


def test_the_direct_route_is_offered_only_when_it_fits():
    assert all(c.method != "direct" for c in run(4.0, top_n=20).candidates)  # 2.1 mi direct for 4 mi asked


def test_a_feature_that_cant_fit_the_distance_isnt_routed():
    calls = []

    def counting(points, area):
        calls.append(points)
        return straight_route(points)
    tiny = Anchors(entry=(40.7438, -73.9775), directions=[[(40.7447, -73.9775, 300.0, 100.0)]], source="park",
                   name="Tiny Park", area={"type": "Polygon", "coordinates": []})
    result = run(6.0, top_n=10, feature_anchor_fn=[lambda lat, lon, r: [tiny]], area_route_fn=counting)
    assert result.rejected["feature_too_short"] >= 1 and calls == []
