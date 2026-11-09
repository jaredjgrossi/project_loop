from api.geometry import line_touches_polygon, point_in_ring

# A 100 x 100 square (lon/lat units don't matter to the predicate).
SQUARE = [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]


def test_point_inside_and_outside():
    assert point_in_ring(50, 50, SQUARE)
    assert not point_in_ring(150, 50, SQUARE)
    assert not point_in_ring(-1, -1, SQUARE)


def test_line_entirely_outside_does_not_touch():
    assert not line_touches_polygon([[-50, -50], [-10, 200]], [SQUARE])


def test_line_with_a_vertex_inside_touches():
    assert line_touches_polygon([[-50, 50], [50, 50]], [SQUARE])


def test_line_crossing_through_without_a_vertex_inside_touches():
    # Both ends outside; the segment cuts straight across. A vertex-only check would miss this.
    assert line_touches_polygon([[-50, 50], [150, 50]], [SQUARE])


def test_line_wholly_inside_touches():
    assert line_touches_polygon([[10, 10], [90, 90]], [SQUARE])


def test_hole_is_not_part_of_the_polygon():
    hole = [[40, 40], [60, 40], [60, 60], [40, 60], [40, 40]]
    assert not line_touches_polygon([[45, 45], [55, 55]], [SQUARE, hole])
    assert line_touches_polygon([[10, 10], [55, 55]], [SQUARE, hole])


def test_line_running_along_outside_near_an_edge_does_not_touch():
    assert not line_touches_polygon([[-0.5, -10], [-0.5, 110]], [SQUARE])


# ---- outlines for the candidates event (step 7b, decision 031) ----------------------------------------------------

import math

from api.geometry import OUTLINE_MAX_POINTS, outline


def _circle(n: int, lat=40.7438, lon=-73.9799, r=0.008):
    pts = [[round(lon + r * math.cos(2 * math.pi * i / n), 6), round(lat + r * math.sin(2 * math.pi * i / n), 6)]
           for i in range(n)]
    return pts + [pts[0]]


def test_a_long_route_is_cut_to_at_most_40_points_and_keeps_its_ends():
    coords = _circle(600)
    out = outline(coords)
    assert 20 <= len(out) <= OUTLINE_MAX_POINTS
    assert out[0] == [round(c, 5) for c in coords[0]] and out[-1] == out[0]  # a loop still closes


def test_the_outline_stays_near_the_route():
    coords = _circle(600)
    out = outline(coords)
    for lon, lat in out:  # every kept point is on the circle, within about 1 m of rounding
        assert abs(math.hypot(lon - -73.9799, lat - 40.7438) - 0.008) < 2e-5


def test_corners_survive():
    square = [[-73.98, 40.74], [-73.97, 40.74], [-73.97, 40.75], [-73.98, 40.75], [-73.98, 40.74]]
    dense = [[a[0] + (b[0] - a[0]) * t / 50, a[1] + (b[1] - a[1]) * t / 50]
             for a, b in zip(square, square[1:]) for t in range(50)] + [square[-1]]
    out = outline(dense)
    for corner in square:
        assert [round(corner[0], 5), round(corner[1], 5)] in out


def test_a_short_route_is_kept_whole_and_rounded():
    coords = [[-73.979912345, 40.743812345, 12.0], [-73.97, 40.75, 13.0]]  # elevation is dropped
    assert outline(coords) == [[-73.97991, 40.74381], [-73.97, 40.75]]


# ---- passing through a via (step 9, decision 034) -----------------------------------------------------------------

from api.geometry import passes_through

M_LAT = 110_574
KX = 111_320 * math.cos(math.radians(40.7438))


def _east(m, lat=40.7438, lon=-73.9799):
    return [lon + m / KX, lat]


def test_a_route_passes_a_point_within_the_tolerance():
    route = [_east(0), _east(1000)]
    near = {"type": "Point", "coordinates": [-73.9799 + 500 / KX, 40.7438 + 100 / M_LAT]}  # 100 m off the line
    far = {"type": "Point", "coordinates": [-73.9799 + 500 / KX, 40.7438 + 300 / M_LAT]}
    assert passes_through(route, near, 150) and not passes_through(route, far, 150)


def test_a_route_touching_a_park_passes_it():
    ring = [[-73.975, 40.746], [-73.970, 40.746], [-73.970, 40.750], [-73.975, 40.750], [-73.975, 40.746]]
    park = {"type": "Polygon", "coordinates": [ring]}
    inside = [[-73.9799, 40.748], [-73.972, 40.748]]
    beside = [[-73.9799, 40.7458], [-73.972, 40.7458]]  # 22 m south of the edge
    away = [[-73.9799, 40.744], [-73.972, 40.744]]  # 220 m south
    assert passes_through(inside, park, 30) and passes_through(beside, park, 30) and not passes_through(away, park, 30)


def test_a_route_along_part_of_a_path_passes_it():
    path = {"type": "MultiLineString", "coordinates": [[_east(2000), _east(3000)], [_east(5000), _east(6000)]]}
    assert passes_through([_east(0), _east(2500)], path, 60)
    assert not passes_through([[-73.9799, 40.70], [-73.97, 40.70]], path, 60)
