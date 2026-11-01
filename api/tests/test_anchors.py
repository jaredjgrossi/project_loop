import pytest

from api.anchors import along_feature

# --- walking distance along the feature (decision 014) ------------------------------------------

LAT0, LON0 = 40.74, -73.98
KX = 111_320 * 0.7581  # meters per degree of longitude at 40.74
KY = 110_574


def ll(points_m):
    return [[LON0 + x / KX, LAT0 + y / KY] for x, y in points_m]


def test_along_distances_follow_the_path_not_the_straight_line():
    # A U-shaped shore: out 1 km east, 300 m north, back 1 km west. Its far end is only 300 m from its start in a
    # straight line, but 2.3 km along it.
    shore = ll([(0, 0)] + [(x, 0) for x in range(100, 1001, 100)] + [(1000, 150), (1000, 300)]
               + [(x, 300) for x in range(900, -1, -100)])
    a = along_feature([shore], start=(LAT0, LON0 - 200 / KX), radius_m=2000, source="water", name="waterfront")
    far = max((p for d in a.directions for p in d), key=lambda p: p[3])
    assert far[3] == pytest.approx(2300, rel=0.05)
    assert far[2] < 400  # straight-line distance from the start stays small


def test_a_disconnected_piece_across_the_water_is_not_offered():
    near = ll([(0, 0), (500, 0), (1000, 0)])
    across = ll([(0, 900), (1000, 900)])  # the other bank: no path joins it
    a = along_feature([near, across], start=(LAT0, LON0), radius_m=2000, source="water", name="waterfront")
    assert all(p[1] < LAT0 + 100 / KY for d in a.directions for p in d)


def test_each_branch_out_of_the_entry_is_a_direction():
    # The entry is in the middle of a path: one direction each way.
    path = ll([(-1000, 0), (-500, 0), (0, 0), (500, 0), (1000, 0)])
    a = along_feature([path], start=(LAT0 - 50 / KY, LON0), radius_m=2000, source="corridor", name="Test Greenway")
    assert len(a.directions) == 2
    assert a.entry == pytest.approx((LAT0, LON0), abs=1e-6)


def test_points_carry_straight_line_and_along_distances_and_are_sorted_by_along():
    path = ll([(x, 0) for x in range(0, 3001, 50)])
    a = along_feature([path], start=(LAT0, LON0), radius_m=2000, source="corridor", name="Test Greenway")
    pts = a.directions[0]
    assert all(len(p) == 4 for p in pts)
    assert [p[3] for p in pts] == sorted(p[3] for p in pts)
    assert pts[-1][3] == pytest.approx(3000, rel=0.05)


def test_no_lines_means_no_anchors():
    a = along_feature([], start=(LAT0, LON0), radius_m=2000, source="park", name="Nothing")
    assert a.entry is None and a.directions == []


def test_paths_that_nearly_meet_are_joined():
    # Two waterfront paths that end 10 m apart (in OSM they meet through a short connector that isn't in the set).
    a = ll([(0, 0), (500, 0), (1000, 0)])
    b = ll([(1010, 0), (1500, 0), (2000, 0)])
    anchors = along_feature([a, b], start=(LAT0, LON0), radius_m=2000, source="water", name="waterfront")
    assert max(p[3] for d in anchors.directions for p in d) == pytest.approx(2000, rel=0.05)


def test_a_dead_end_joins_the_middle_of_another_path():
    # A T-junction without a shared vertex: the stem ends 8 m short of the bar.
    bar = ll([(-1000, 500), (0, 500), (1000, 500)])
    stem = ll([(0, 0), (0, 250), (0, 492)])
    anchors = along_feature([stem, bar], start=(LAT0, LON0), radius_m=2000, source="park", name="Test Park")
    assert max(p[3] for d in anchors.directions for p in d) > 1400  # up the stem and along the bar


def test_real_gaps_stay_gaps():
    a = ll([(0, 0), (1000, 0)])
    b = ll([(1700, 0), (3000, 0)])  # 700 m away: the East Midtown Greenway gap is about this
    anchors = along_feature([a, b], start=(LAT0, LON0), radius_m=2000, source="water", name="waterfront")
    assert max(p[3] for d in anchors.directions for p in d) == pytest.approx(1000, rel=0.05)


def test_a_straight_line_set_covers_every_piece_of_the_feature():
    # The along set stops at a gap; the straight-line set still offers the piece past it.
    from api.anchors import straight_line_anchors

    a = ll([(0, 0), (1000, 0)])
    b = ll([(1700, 0), (3000, 0)])
    s = straight_line_anchors([a, b], start=(LAT0, LON0), radius_m=2000, source="water", name="waterfront")
    pts = [p for d in s.directions for p in d]
    assert all(len(p) == 3 for p in pts)  # no along distance: placed by straight-line distance
    assert max(p[2] for p in pts) > 2500
    assert s.entry == pytest.approx((LAT0, LON0), abs=1e-5)
