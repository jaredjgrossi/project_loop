"""The outline of the five boroughs the iOS app bundles (decision 056): small, valid, and right about known places."""

import json

import pytest
from shapely.geometry import Point, Polygon, shape

from etl.export_coverage import OUT, SOURCE, outline

INSIDE = {  # public places, lat/lon, one or more in every borough and at the edges of the city
    "Kips Bay": (40.7420, -73.9780),
    "Central Park": (40.7829, -73.9654),
    "Inwood Hill Park": (40.8690, -73.9250),
    "Prospect Park": (40.6602, -73.9690),
    "Flushing Meadows": (40.7466, -73.8448),
    "Pelham Bay Park": (40.8700, -73.8100),
    "Staten Island Ferry, St. George": (40.6437, -74.0737),
    "Tottenville, Staten Island": (40.5090, -74.2487),
    "JFK Airport": (40.6413, -73.7781),
    "Far Rockaway": (40.6050, -73.7550),
    "Governors Island": (40.6895, -74.0168),
    "Battery Park": (40.7033, -74.0170),
}
OUTSIDE = {
    "Hoboken PATH": (40.7359, -74.0276),
    "Liberty State Park, Jersey City": (40.7106, -74.0546),
    "Newark": (40.7357, -74.1724),
    "Yonkers": (40.9312, -73.8988),
    "Mount Vernon": (40.9126, -73.8370),
    "Great Neck": (40.8007, -73.7285),
    "Hempstead": (40.7062, -73.6187),
    "Tampa": (27.9506, -82.4572),
    "Eiffel Tower": (48.8584, 2.2945),
}


@pytest.fixture(scope="module")
def collection():
    return json.loads(OUT.read_text())


def test_it_is_a_small_valid_geojson_feature_collection(collection):
    assert collection["type"] == "FeatureCollection" and len(collection["features"]) == 1
    f = collection["features"][0]
    assert f["type"] == "Feature" and f["geometry"]["type"] == "MultiPolygon"
    assert f["properties"]["name"] == "New York City"
    assert OUT.stat().st_size < 6_000  # "a few KB"
    assert shape(f["geometry"]).is_valid


def test_coordinates_are_lon_lat_inside_the_city(collection):
    for poly in collection["features"][0]["geometry"]["coordinates"]:
        for ring in poly:
            for lon, lat in ring:
                assert -74.3 < lon < -73.6 and 40.4 < lat < 41.0


def test_rings_are_closed_and_wound_as_geojson_asks(collection):
    for poly in collection["features"][0]["geometry"]["coordinates"]:
        outer = Polygon(poly[0])
        assert poly[0][0] == poly[0][-1] and outer.exterior.is_ccw


@pytest.mark.parametrize("name", sorted(INSIDE))
def test_a_place_in_the_boroughs_is_inside(collection, name):
    lat, lon = INSIDE[name]
    assert shape(collection["features"][0]["geometry"]).contains(Point(lon, lat))


@pytest.mark.parametrize("name", sorted(OUTSIDE))
def test_a_place_outside_the_boroughs_is_outside(collection, name):
    lat, lon = OUTSIDE[name]
    assert not shape(collection["features"][0]["geometry"]).contains(Point(lon, lat))


def test_the_outline_contains_everything_it_simplified():
    ragged = Polygon([(0, 0), (1, 0.0002), (2, 0), (2.0003, 1), (2, 2), (1, 1.9997), (0, 2), (0.0004, 1)])
    out = outline(ragged, 0.001)
    assert out.contains(ragged) and len(out.geoms[0].exterior.coords) < len(ragged.exterior.coords) + 4


@pytest.mark.skipif(not SOURCE.exists(), reason="routing/data/nyc_boundary.geojson isn't built (routing.prepare_osm)")
def test_the_committed_outline_covers_the_whole_routing_boundary(collection):
    source = shape(json.loads(SOURCE.read_text()))
    assert source.difference(shape(collection["features"][0]["geometry"])).area / source.area < 1e-6
