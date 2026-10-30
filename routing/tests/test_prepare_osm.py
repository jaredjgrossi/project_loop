import pytest

from routing.prepare_osm import merge_boroughs


def square(x, y):
    return [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]]


def feature(*polygons):
    return {"type": "Feature", "properties": {}, "geometry": {"type": "MultiPolygon", "coordinates": list(polygons)}}


def test_merges_all_boroughs_into_one_multipolygon():
    features = [feature(square(0, 0), square(2, 0)), feature(square(0, 2))] + [feature(square(5, 5))] * 3
    merged = merge_boroughs({"type": "FeatureCollection", "features": features})
    assert merged["type"] == "MultiPolygon"
    assert len(merged["coordinates"]) == 2 + 1 + 3


def test_accepts_plain_polygons_too():
    polygon = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": square(0, 0)}}
    fc = {"type": "FeatureCollection", "features": [polygon] * 5}
    assert len(merge_boroughs(fc)["coordinates"]) == 5


def test_refuses_to_clip_to_an_incomplete_boundary():
    fc = {"type": "FeatureCollection", "features": [feature(square(0, 0))] * 4}
    with pytest.raises(ValueError, match="five"):
        merge_boroughs(fc)


def test_refuses_unexpected_geometry():
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0, 0]}}] * 5}
    with pytest.raises(ValueError):
        merge_boroughs(fc)
