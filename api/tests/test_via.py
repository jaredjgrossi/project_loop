"""Routes through or along named places (step 9, decision 034), on the straight-line fake router of the A-to-B
tests: every route passes every via, loops and out-and-backs fit the distance, and only features on a via anchor."""

import math

import pytest

from api.anchors import Anchors
from api.generate import generate_loops
from api.tests.test_a_to_b import GRID, KIPS, M_LAT, meters, straight_route
from api.via import Via, features_on_vias, through_rules, tour, via_jobs

KX = 111_320 * math.cos(math.radians(KIPS[0]))
NORTH = (KIPS[0] + 1200 / M_LAT, KIPS[1])  # 1.2 km north of the start


def point_via(at=NORTH, name="Test Station"):
    return Via(at[0], at[1], name, {"type": "Point", "coordinates": [at[1], at[0]]})


def square(centre, half_m):
    lat, lon = centre
    dy, dx = half_m / M_LAT, half_m / KX
    ring = [[lon - dx, lat - dy], [lon + dx, lat - dy], [lon + dx, lat + dy], [lon - dx, lat + dy], [lon - dx, lat - dy]]
    return {"type": "Polygon", "coordinates": [ring]}


def run(vias, miles, shape="any", feature_anchor_fn=None, **kw):
    shortest = straight_route(tour(KIPS, vias))
    return generate_loops(KIPS[0], KIPS[1], miles, GRID, route_fn=straight_route, round_trip_fn=None, top_n=10,
                          shape=shape, only_anchored=True, through=through_rules(vias),
                          extra_jobs=via_jobs(KIPS, vias, miles, straight_route, shortest, shape),
                          feature_anchor_fn=feature_anchor_fn, **kw)


def passes(route, via, tol):
    return min(meters(via.point, (lat, lon)) for lon, lat in route.coordinates) <= tol


def test_every_route_passes_the_via_and_fits_the_distance():
    v = point_via()
    result = run([v], 4.0)
    assert result.candidates and result.within_tolerance
    for c in result.candidates:
        assert passes(c.route, v, 150) and abs(c.miss_pct) <= 5


def test_loops_and_an_out_and_back_through_the_via():
    kinds = {c.kind for c in run([point_via()], 4.0).candidates}
    assert "out_and_back" in kinds and kinds & {"loop", "lollipop"}


def test_a_shape_said_keeps_only_that_kind():
    assert {c.kind for c in run([point_via()], 4.0, shape="out_and_back").candidates} == {"out_and_back"}


def test_two_vias_in_order():
    a, b = point_via(NORTH, "A"), point_via((KIPS[0], KIPS[1] + 1200 / KX), "B")
    for c in run([a, b], 5.0).candidates:
        assert passes(c.route, a, 150) and passes(c.route, b, 150)


def test_a_route_that_misses_the_via_is_rejected():
    v = point_via()
    shortest = straight_route(tour(KIPS, [v]))

    def elsewhere(points, custom_model=None):  # ignores the via and runs east instead
        return straight_route([KIPS, (KIPS[0], KIPS[1] + 3000 / KX), KIPS])
    result = generate_loops(KIPS[0], KIPS[1], 4.0, GRID, route_fn=elsewhere, round_trip_fn=None, top_n=10,
                            only_anchored=True, through=through_rules([v]),
                            extra_jobs=via_jobs(KIPS, [v], 4.0, elsewhere, shortest, "any"))
    assert result.candidates == [] and result.rejected["misses_via"] > 0


def test_only_features_on_a_via_anchor_the_routes():
    park = Via(NORTH[0], NORTH[1], "Test Park", square(NORTH, 300))
    on_park = Anchors(entry=(NORTH[0] - 300 / M_LAT, NORTH[1]), directions=[[(NORTH[0], NORTH[1], 1200.0, 300.0)]],
                      source="park", name="Test Park", area=square(NORTH, 300))
    elsewhere = Anchors(entry=(KIPS[0], KIPS[1] + 500 / KX), directions=[[(KIPS[0], KIPS[1] + 900 / KX, 900.0, 400.0)]],
                        source="water", name=None, area=square((KIPS[0], KIPS[1] + 900 / KX), 200))
    kept = features_on_vias(lambda lat, lon, r: [on_park, elsewhere], [park])(*KIPS, 3000)
    assert kept == [on_park]


def test_a_park_via_is_passed_by_touching_its_outline():
    park = Via(NORTH[0], NORTH[1], "Test Park", square(NORTH, 300))
    (shape, tol, share), = through_rules([park])
    assert tol == 30 and share is None and shape["type"] == "Polygon"
    result = run([park], 4.0)
    assert result.candidates


# ---- around: a full lap (decision 035) -----------------------------------------------------------------------------

from api.geometry import covered_share  # noqa: E402
from api.via import LAP_SHARE, lap_points  # noqa: E402


def ring(centre=NORTH, half_m=300):
    """A square ring, counterclockwise, as a lap's [lon, lat] coordinates."""
    return tuple(tuple(c) for c in square(centre, half_m)["coordinates"][0])


def lap_via(centre=NORTH, half_m=300, name="Test Loop"):
    return Via(centre[0], centre[1], name, square(centre, half_m), ring(centre, half_m))


def test_lap_points_run_the_whole_ring_from_the_nearest_point_and_back():
    r = ring()
    pts = lap_points(r, KIPS)  # coming from the south
    assert pts[0] == pytest.approx(pts[-1])
    assert pts[0][0] == pytest.approx(NORTH[0] - 300 / M_LAT, abs=1e-6)  # entered on the south side
    line = {"type": "LineString", "coordinates": [list(c) for c in r]}
    assert covered_share([[lon, lat] for lat, lon in pts], line, 1.0) == pytest.approx(1.0)
    # in the ring's direction: from the south side, east first (counterclockwise)
    assert pts[1][1] > pts[0][1]


def test_tour_runs_a_lap_for_an_around_via():
    v = lap_via()
    t = tour(KIPS, [v])
    assert t[0] == KIPS and t[-1] == KIPS and len(t) > 6
    assert v.mode == "around" and point_via().mode == "through"


def test_the_lap_rule_is_the_ring_and_a_share():
    (shape, tol, share), = through_rules([lap_via()])
    assert shape["type"] == "LineString" and tol == 30 and share == LAP_SHARE


def test_every_route_runs_the_whole_lap_and_fits_the_distance():
    v = lap_via()
    lap_m = 2400  # 4 x 600 m
    result = run([v], 4.0)
    assert result.candidates
    line = through_rules([v])[0][0]
    for c in result.candidates:
        assert covered_share(c.route.coordinates, line, 30) >= LAP_SHARE and abs(c.miss_pct) <= 5
        assert c.route.distance_m > lap_m
    assert "out_and_back" not in {c.kind for c in result.candidates}  # a lap isn't run twice


def test_a_route_that_only_touches_the_ring_is_rejected():
    v = lap_via()
    shortest = straight_route(tour(KIPS, [v]))

    def touch(points, custom_model=None):  # to the ring's south side and back, never round it
        return straight_route([KIPS, (NORTH[0] - 300 / M_LAT, NORTH[1]), KIPS])
    result = generate_loops(KIPS[0], KIPS[1], 4.0, GRID, route_fn=touch, round_trip_fn=None, top_n=10,
                            only_anchored=True, through=through_rules([v]),
                            extra_jobs=via_jobs(KIPS, [v], 4.0, touch, shortest, "any"))
    assert result.candidates == [] and result.rejected["misses_lap"] > 0


def test_a_lap_skips_a_spot_it_must_miss():  # step 11: "skip the ferry part" of a past route
    import dataclasses
    from api.geometry import line_length_m
    from api.via import _meters
    v = lap_via()
    corner = (NORTH[0] + 300 / M_LAT, NORTH[1] + 300 / KX)  # the ring's north-east corner
    skipped = dataclasses.replace(v, skip=((corner[0], corner[1], 100.0),))
    assert all(_meters(p, corner) > 100 for p in skipped.stops(KIPS)[1:-1])
    full = line_length_m([list(c) for c in v.lap])
    ring = skipped.ring()
    parts = ring["coordinates"] if ring["type"] == "MultiLineString" else [ring["coordinates"]]
    left = sum(line_length_m(p) for p in parts)
    assert left == pytest.approx(full - 200, abs=5)  # 100 m each way from the corner
