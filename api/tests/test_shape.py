"""Shape metrics, tested on hand-made shapes whose answers are known.

Shapes are built in meters (x east, y north) and converted to lon/lat, so the
expected numbers can be reasoned about without a map.
"""

import math

import pytest

from api.shape import ShapeMetrics, shape_metrics

LAT0, LON0 = 40.74, -73.98
M_PER_DEG_LAT = 110_574
M_PER_DEG_LON = 111_320 * math.cos(math.radians(LAT0))


def lonlat(points_m):
    return [[LON0 + x / M_PER_DEG_LON, LAT0 + y / M_PER_DEG_LAT] for x, y in points_m]


def densify(points_m, step=40.0):
    """Add intermediate vertices along straight segments, like real OSM geometry."""
    out = [points_m[0]]
    for (x0, y0), (x1, y1) in zip(points_m, points_m[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) // step))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1)]
    return out


def rect(w, h, start="corner"):
    corners = [(0, 0), (w, 0), (w, h), (0, h), (0, 0)]
    if start == "midside":
        corners = [(w / 2, 0), (w, 0), (w, h), (0, h), (0, 0), (w / 2, 0)]
    return densify(corners)


def staircase(steps=10, size=100):
    pts = [(0, 0)]
    for i in range(steps):
        x, y = pts[-1]
        pts += [(x + size, y), (x + size, y + size)]
    return densify(pts, step=25)


# --- turns -------------------------------------------------------------------


def test_square_loop_has_four_turns_wherever_it_starts():
    corner = shape_metrics(lonlat(rect(1000, 1000, "corner")))
    mid = shape_metrics(lonlat(rect(1000, 1000, "midside")))
    assert corner.turns == 4
    assert mid.turns == 4


def test_turns_per_mile_uses_route_length():
    m = shape_metrics(lonlat(rect(1000, 1000)))
    assert m.distance_miles == pytest.approx(4000 / 1609.344, rel=0.01)
    assert m.turns_per_mile == pytest.approx(4 / m.distance_miles)


def test_staircase_counts_every_corner():
    m = shape_metrics(lonlat(staircase(steps=10)))
    assert m.turns == 19  # 20 segments, 19 corners between them (open route, ends are not turns)


def test_straight_line_has_no_turns():
    m = shape_metrics(lonlat(densify([(0, 0), (3000, 0)])))
    assert m.turns == 0
    assert m.longest_straight_m == pytest.approx(3000, rel=0.01)


def test_gentle_curve_is_not_a_turn():
    # A quarter circle of radius 500 m: lots of small bends, none near 45 degrees.
    arc = [(500 * math.sin(t), 500 * (1 - math.cos(t))) for t in [i * (math.pi / 2) / 40 for i in range(41)]]
    assert shape_metrics(lonlat(arc)).turns == 0


def test_out_and_back_counts_the_u_turn():
    pts = densify([(0, 0), (1000, 0), (0, 0)])
    assert shape_metrics(lonlat(pts)).turns >= 1


# --- straight runs -------------------------------------------------------------


def test_square_is_all_long_straight_runs():
    m = shape_metrics(lonlat(rect(1000, 1000, "midside")))
    assert m.longest_straight_m == pytest.approx(1000, rel=0.02)  # the run that spans the start is not split
    assert m.pct_in_long_runs == pytest.approx(100, abs=1)


def test_staircase_has_no_long_runs():
    m = shape_metrics(lonlat(staircase()))
    assert m.longest_straight_m == pytest.approx(100, rel=0.05)
    assert m.pct_in_long_runs == 0


# --- retracing -----------------------------------------------------------------


def test_out_and_back_is_almost_entirely_retraced():
    m = shape_metrics(lonlat(densify([(0, 0), (1500, 0), (0, 0)])))
    assert m.retraced_pct > 90


def test_square_loop_retraces_nothing():
    assert shape_metrics(lonlat(rect(1000, 1000))).retraced_pct == pytest.approx(0, abs=2)


def test_nearby_segments_along_the_route_are_not_counted_as_retracing():
    # A short hairpin's two legs are 10 m apart, but never more than 130 m apart along the route.
    pts = densify([(0, 0), (60, 0), (60, 10), (0, 10)])
    assert shape_metrics(lonlat(pts)).retraced_pct == 0


# --- loop shape ----------------------------------------------------------------


def test_square_width_and_compactness():
    m = shape_metrics(lonlat(rect(1000, 1000)))
    assert m.mean_width_m == pytest.approx(500, rel=0.02)
    assert m.compactness == pytest.approx(math.pi / 4, abs=0.02)


def test_thin_ribbon_loop_is_flagged_by_width_and_compactness():
    # Out along one street, back along one 100 m away: nothing retraced, but a ribbon.
    m = shape_metrics(lonlat(rect(2000, 100)))
    assert m.retraced_pct == pytest.approx(0, abs=3)
    assert m.mean_width_m == pytest.approx(95, rel=0.1)
    assert m.compactness < 0.2


def test_open_route_has_no_width_or_compactness():
    m = shape_metrics(lonlat(staircase()))
    assert m.mean_width_m is None and m.compactness is None


# --- robustness ----------------------------------------------------------------


def test_returns_a_shapemetrics_and_serializes_to_plain_numbers():
    m = shape_metrics(lonlat(rect(1000, 1000)))
    assert isinstance(m, ShapeMetrics)
    d = m.as_dict()
    assert set(d) == {
        "distance_miles", "turns", "turns_per_mile", "longest_straight_m",
        "pct_in_long_runs", "retraced_pct", "mean_width_m", "compactness",
    }
    assert all(isinstance(v, (int, float)) or v is None for v in d.values())


@pytest.mark.parametrize("coords", [[], [[LON0, LAT0]], [[LON0, LAT0], [LON0, LAT0]]])
def test_degenerate_routes_are_rejected(coords):
    with pytest.raises(ValueError):
        shape_metrics(coords)
