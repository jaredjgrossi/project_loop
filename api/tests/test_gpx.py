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


# ---- a stored route as a GPX file, for the app's Share (full review 3.2) -------------------------------------------------


def _final():
    out_back = line([(x, 0) for x in range(0, 3001, 50)] + [(x, 0) for x in range(2950, -1, -50)])  # ~3.7 mi
    loop = line([(0, 0), (800, 0), (800, 800), (0, 800), (0, 0)])
    route = lambda i, kind, label, coords: {"id": f"r_ab12cd34.{i}", "rank": i, "kind": kind, "label": label,  # noqa: E731
                                            "score": 80, "geometry": {"type": "LineString", "coordinates": coords}}
    return {"event": "final", "route_id": "r_ab12cd34", "routes": [route(1, "out_and_back", "Out-and-back on Riverside Walk", out_back),
                                                                   route(2, "loop", "Loop on the street grid", loop)]}


def test_a_build_id_gives_the_first_route_and_a_route_id_gives_that_route():
    from api.gpx import stored_gpx
    first = stored_gpx(_final(), "r_ab12cd34")
    second = stored_gpx(_final(), "r_ab12cd34.2")
    assert first and second
    assert "Out-and-back on Riverside Walk" in first[1] and "Loop on the street grid" in second[1]
    assert first[0] == "loop-r_ab12cd34.1.gpx" and second[0] == "loop-r_ab12cd34.2.gpx"  # the file names the route


def test_an_unknown_route_has_no_gpx():
    from api.gpx import stored_gpx
    assert stored_gpx(_final(), "r_ab12cd34.9") is None
    assert stored_gpx({"routes": []}, "r_ab12cd34") is None


def test_the_file_is_valid_gpx_with_the_start_the_miles_and_the_turnaround():
    from api.gpx import stored_gpx
    root = ET.fromstring(stored_gpx(_final(), "r_ab12cd34.1")[1])
    names = [w.find("g:name", NS).text for w in root.findall("g:wpt", NS)]
    assert names[0] == "Start" and {"Mile 1", "Mile 2", "Mile 3", "Turnaround"} <= set(names)
    pts = root.findall(".//g:trkpt", NS)
    assert len(pts) > 100 and float(pts[0].get("lat")) == pytest.approx(LAT0, abs=1e-6)
    assert root.find("g:metadata/g:name", NS).text.startswith("Out-and-back on Riverside Walk")
    assert root.find(".//g:trkpt/g:ele", NS) is None  # elevation per point isn't stored: no invented numbers


def test_a_label_with_markup_is_escaped():
    from api.gpx import stored_gpx
    final = _final()
    final["routes"][0]["label"] = "Loop <on> Ben & Jerry's"
    root = ET.fromstring(stored_gpx(final, "r_ab12cd34")[1])  # still well-formed XML
    assert "Ben & Jerry's" in root.find("g:metadata/g:name", NS).text
