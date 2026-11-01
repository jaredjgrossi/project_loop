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
