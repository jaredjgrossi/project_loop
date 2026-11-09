"""The drive ring of a curated running loop (decision 035), on made-up projected lines."""

import pytest
from shapely.geometry import LineString

from etl.build_running_loops import curated, drive_ring


def test_the_ring_is_the_outside_of_the_drives_with_small_gaps_joined():
    west = LineString([(0, 0), (0, 1000)])
    north = LineString([(0, 1000), (400, 1000)])
    east = LineString([(400, 1000), (400, 3)])  # stops 3 ft short of the south drive
    south = LineString([(400, 0), (0, 0)])
    cross = LineString([(0, 500), (400, 500)])  # a cross drive: inside the loop, not part of it
    ring = drive_ring([west, north, east, south, cross], gap=10)
    assert ring is not None and ring.length == pytest.approx(2800, abs=5)


def test_a_gap_wider_than_the_join_leaves_no_ring():
    lines = [LineString([(0, 0), (0, 1000)]), LineString([(0, 1000), (400, 1000)]),
             LineString([(400, 1000), (400, 100)]), LineString([(400, 0), (0, 0)])]
    assert drive_ring(lines, gap=10) is None


def test_each_curated_loop_says_how_its_ring_is_found():
    for lp in curated():
        g = lp["geometry"]
        assert g is None or g["from"] in ("osm_way", "drive_ring")
