import json
from datetime import UTC, datetime

import pytest

from etl.osm_parser import OSM_SOURCE_ID, parse_coastline, parse_park, parse_way
from etl.parsers import RowError

LOADED_AT = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
SOURCE_UPDATED = "2026-10-28T21:21:02Z"

# A real way from the NYC extract (Boerum Place, Brooklyn), tags trimmed.
BOERUM = {
    "type": "Feature",
    "id": "w5029221",
    "geometry": {
        "type": "LineString",
        "coordinates": [[-73.9892384, 40.6909958], [-73.9892231, 40.6910299], [-73.9891327, 40.6913611]],
    },
    "properties": {
        "highway": "primary",
        "name": "Boerum Place",
        "surface": "asphalt",
        "oneway": "yes",
        "tiger:county": "Kings, NY",
        "name:etymology:wikidata": "Q7518301",
    },
}


def parse(feature=BOERUM):
    return parse_way(feature, loaded_at=LOADED_AT, source_updated_at=SOURCE_UPDATED)


def test_way_fields_and_provenance():
    out = parse()
    assert out["way_id"] == 5029221
    assert out["highway"] == "primary"
    assert out["name"] == "Boerum Place"
    assert out["source_dataset_id"] == OSM_SOURCE_ID
    assert out["source_row_id"] == "w5029221"
    assert out["source_updated_at"] == SOURCE_UPDATED
    assert out["loaded_at"] == LOADED_AT


def test_only_useful_tags_are_kept():
    tags = json.loads(parse()["tags"])
    assert tags == {"highway": "primary", "name": "Boerum Place", "surface": "asphalt", "oneway": "yes"}


def test_geometry_is_ewkt_in_lon_lat_order():
    out = parse()
    assert out["geom_ewkt"] == (
        "SRID=4326;LINESTRING(-73.9892384 40.6909958,-73.9892231 40.6910299,-73.9891327 40.6913611)"
    )


def test_unnamed_way_is_fine():
    f = {**BOERUM, "properties": {"highway": "footway"}}
    assert parse(f)["name"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {**BOERUM, "geometry": {"type": "Point", "coordinates": [0, 0]}},
        {**BOERUM, "geometry": {"type": "LineString", "coordinates": [[-73.98, 40.74]]}},
        {**BOERUM, "id": None},
        {**BOERUM, "id": "n123"},  # a node, not a way
        {**BOERUM, "properties": {"name": "No highway tag"}},
    ],
)
def test_unusable_features_are_rejected(bad):
    with pytest.raises(RowError):
        parse(bad)


def test_crossing_tags_are_kept_for_signal_counts():
    f = {**BOERUM, "properties": {"highway": "footway", "footway": "crossing", "crossing": "traffic_signals",
                                  "crossing:signals": "yes", "crossing_ref": "zebra"}}
    tags = json.loads(parse(f)["tags"])
    assert tags == {"highway": "footway", "footway": "crossing", "crossing": "traffic_signals", "crossing:signals": "yes"}


def test_coastline_way_is_parsed_with_provenance():
    f = {"type": "Feature", "id": "w42", "geometry": BOERUM["geometry"], "properties": {"natural": "coastline"}}
    out = parse_coastline(f, loaded_at=LOADED_AT, source_updated_at=SOURCE_UPDATED)
    assert out["way_id"] == 42 and out["source_row_id"] == "w42"
    assert out["geom_ewkt"].startswith("SRID=4326;LINESTRING(-73.9892384 40.6909958")


def test_non_coastline_is_rejected():
    with pytest.raises(RowError):
        parse_coastline(BOERUM, loaded_at=LOADED_AT, source_updated_at=SOURCE_UPDATED)


PARK = {
    "type": "Feature", "id": "a10058222",
    "geometry": {"type": "MultiPolygon", "coordinates": [[[[-74.0, 40.70], [-73.99, 40.70], [-73.99, 40.71], [-74.0, 40.70]]]]},
    "properties": {"leisure": "park", "name": "Hudson River Park", "operator": "Hudson River Park Trust"},
}


def test_osm_park_area_is_parsed_with_provenance():
    out = parse_park(PARK, loaded_at=LOADED_AT, source_updated_at=SOURCE_UPDATED)
    assert out["area_id"] == 10058222 and out["source_row_id"] == "a10058222"
    assert out["name"] == "Hudson River Park" and out["leisure"] == "park"
    assert json.loads(out["geojson"])["type"] == "MultiPolygon"


@pytest.mark.parametrize("bad", [
    {**PARK, "properties": {"leisure": "playground"}},
    {**PARK, "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
    {**PARK, "id": "w12"},
])
def test_non_park_areas_are_rejected(bad):
    with pytest.raises(RowError):
        parse_park(bad, loaded_at=LOADED_AT, source_updated_at=SOURCE_UPDATED)
