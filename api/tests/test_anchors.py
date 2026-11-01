import pytest

from api.anchors import group_into_directions

START = (40.74, -73.98)


def row(dist, bearing, weight=1.0, lat=None, lon=None):
    # Positions only need to be distinct for these tests; distance and bearing drive the grouping.
    return (lat if lat is not None else START[0] + dist / 1e6, lon if lon is not None else START[1] + bearing / 1e6,
            dist, weight, bearing)


def test_entry_is_the_nearest_point():
    a = group_into_directions([row(900, 10), row(300, 200), row(1500, 15)], radius_m=1000)
    assert a.entry == row(300, 200)[:2]


def test_points_are_grouped_by_direction_and_sorted_nearest_first():
    a = group_into_directions([row(1200, 10), row(800, 20), row(900, 100), row(300, 200)], radius_m=1000)
    by_first = {round(d[0][2]): [round(p[2]) for p in d] for d in a.directions}
    assert by_first[800] == [800, 1200]  # 10 and 20 degrees share the 0-45 sector
    assert by_first[900] == [900]


def test_points_too_close_to_be_a_turnaround_are_not_offered():
    a = group_into_directions([row(100, 10), row(150, 100), row(900, 200)], radius_m=1000)
    assert all(p[2] >= 200 for d in a.directions for p in d)


def test_busiest_direction_comes_first():
    rows = [row(800, 10, weight=1), row(900, 100, weight=5), row(950, 110, weight=5)]
    a = group_into_directions(rows, radius_m=1000)
    assert [round(p[2]) for p in a.directions[0]] == [900, 950]


def test_no_points_means_no_anchors():
    a = group_into_directions([], radius_m=1000)
    assert a.entry is None and a.directions == []


def test_source_and_name_are_carried():
    a = group_into_directions([row(800, 10)], radius_m=1000, source="park", name="Stuyvesant Square")
    assert (a.source, a.name) == ("park", "Stuyvesant Square")


@pytest.mark.parametrize("radius", [500, 2000])
def test_entry_farther_than_the_radius_is_still_reported(radius):
    # Reachability is decided by the caller (it filters features by distance); grouping never drops the entry.
    a = group_into_directions([row(1500, 10), row(1800, 20)], radius_m=radius)
    assert a.entry is not None
