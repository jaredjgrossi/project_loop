import math
import xml.etree.ElementTree as ET

import pytest

from api.gpx import mile_markers, route_to_gpx, turnaround_points

LAT0, LON0 = 40.74, -73.98
KX = 111_320 * math.cos(math.radians(LAT0))
KY = 110_574
NS = {"g": "http://www.topografix.com/GPX/1/1"}


def line(points_m):
    return [[LON0 + x / KX, LAT0 + y / KY] for x, y in points_m]


def test_mile_markers_fall_every_mile_along_the_route():
    coords = line([(x, 0) for x in range(0, 5001, 50)])  # ~3.1 mi straight east
    marks = mile_markers(coords)
    assert [m[2] for m in marks] == ["Mile 1", "Mile 2", "Mile 3"]
    assert (marks[0][1] - LON0) * KX == pytest.approx(1609.344, abs=5)


def test_turnarounds_are_where_the_route_reverses():
    out_back = line([(x, 0) for x in range(0, 2001, 50)] + [(x, 0) for x in range(1950, -1, -50)])
    turns = turnaround_points(out_back)
    assert len(turns) == 1
    assert (turns[0][1] - LON0) * KX == pytest.approx(2000, abs=30)


def test_a_rectangle_has_no_turnarounds():
    rect = line([(0, 0), (1000, 0), (1000, 500), (0, 500), (0, 0)])
    assert turnaround_points(rect) == []


def test_gpx_has_the_track_with_elevation_and_named_waypoints():
    coords = line([(0, 0), (1000, 0), (2000, 0)])
    xml = route_to_gpx("Test run", coords, [10.0, 11.0, 12.5], [(LAT0, LON0 + 1000 / KX, "Turnaround")])
    root = ET.fromstring(xml)
    pts = root.findall(".//g:trkpt", NS)
    assert len(pts) == 3 and pts[2].find("g:ele", NS).text == "12.5"
    assert float(pts[0].get("lat")) == pytest.approx(LAT0) and float(pts[0].get("lon")) == pytest.approx(LON0)
    assert [w.find("g:name", NS).text for w in root.findall("g:wpt", NS)] == ["Turnaround"]
    assert root.find(".//g:trk/g:name", NS).text == "Test run"


def test_gpx_without_elevation_has_no_ele():
    xml = route_to_gpx("Flat", line([(0, 0), (500, 0)]), None, [])
    assert "<ele>" not in xml
