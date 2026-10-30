"""Row parsing, pinned against real rows from the three NYC Open Data datasets."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from etl.parsers import (
    FOUNTAINS_DATASET_ID,
    PARKS_DATASET_ID,
    RESTROOMS_DATASET_ID,
    RowError,
    parse_fountain,
    parse_park,
    parse_restroom,
)

FIXTURES = Path(__file__).parent / "fixtures"
LOADED_AT = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


FOUNTAINS = load("fountains")
RESTROOMS = load("restrooms")
PARKS = load("parks")


def test_dataset_ids_are_the_documented_ones():
    assert (PARKS_DATASET_ID, FOUNTAINS_DATASET_ID, RESTROOMS_DATASET_ID) == ("enfh-gkve", "qnv7-p7a2", "i7jb-7jku")


# --- provenance on every row ---------------------------------------------------


@pytest.mark.parametrize(
    "parse, row, dataset_id",
    [
        (parse_park, PARKS["inland"], "enfh-gkve"),
        (parse_fountain, FOUNTAINS["outdoor_open"], "qnv7-p7a2"),
        (parse_restroom, RESTROOMS["operational_park"], "i7jb-7jku"),
    ],
)
def test_every_row_carries_source_and_load_date(parse, row, dataset_id):
    out = parse(row, LOADED_AT)
    assert out["source_dataset_id"] == dataset_id
    assert out["loaded_at"] == LOADED_AT
    assert out["source_row_id"] == row[":id"]
    assert out["source_updated_at"] == row[":updated_at"]
    assert json.loads(out["raw"]) == row  # nothing is lost


# --- parks ---------------------------------------------------------------------


def test_park_fields():
    out = parse_park(PARKS["waterfront"], LOADED_AT)
    assert out["source_key"] == "Q028A"
    assert out["name"] == "Tribute Park"
    assert out["borough"] == "Queens"
    assert out["acres"] == pytest.approx(0.83)
    assert out["waterfront"] is True
    assert json.loads(out["geom_geojson"])["type"] == "MultiPolygon"


def test_park_waterfront_false_and_unknown_are_different():
    assert parse_park(PARKS["inland"], LOADED_AT)["waterfront"] is False
    assert parse_park(PARKS["waterfront_null"], LOADED_AT)["waterfront"] is None


def test_park_acquisition_date_is_a_date():
    row = dict(PARKS["inland"], acquisitiondate="1934-07-12T00:00:00.000")
    assert parse_park(row, LOADED_AT)["acquisition_date"] == date(1934, 7, 12)


def test_park_without_geometry_is_rejected():
    row = {k: v for k, v in PARKS["inland"].items() if k != "multipolygon"}
    with pytest.raises(RowError):
        parse_park(row, LOADED_AT)


# --- fountains -----------------------------------------------------------------


def test_outdoor_fountain_is_usable():
    out = parse_fountain(FOUNTAINS["outdoor_open"], LOADED_AT)
    assert out["usable"] is True and out["skip_reason"] is None
    assert out["source_key"] == FOUNTAINS["outdoor_open"]["system"]
    assert out["borough"] in {"Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"}
    assert json.loads(out["geom_geojson"])["type"] == "Point"


def test_unknown_position_is_kept_not_guessed_away():
    out = parse_fountain(FOUNTAINS["null_position"], LOADED_AT)
    assert out["position"] is None
    assert out["usable"] is True


def test_bottle_filler_is_usable():
    assert parse_fountain(FOUNTAINS["bottle_filler"], LOADED_AT)["usable"] is True


def test_indoor_fountain_is_skipped_with_reason():
    out = parse_fountain(FOUNTAINS["indoor"], LOADED_AT)
    assert (out["usable"], out["skip_reason"]) == (False, "indoor")


def test_indoor_position_wins_even_if_type_looks_fine():
    out = parse_fountain(FOUNTAINS["indoor_position_outdoor_type"], LOADED_AT)
    assert (out["usable"], out["skip_reason"]) == (False, "indoor")


def test_sink_is_not_a_drinking_fountain():
    out = parse_fountain(FOUNTAINS["food_prep_sink"], LOADED_AT)
    assert out["usable"] is False
    assert out["skip_reason"] in {"indoor", "sink_or_cooler"}


def test_dog_fountain_is_skipped():
    out = parse_fountain(FOUNTAINS["dog"], LOADED_AT)
    assert (out["usable"], out["skip_reason"]) == (False, "dog_only")


def test_skipped_rows_are_still_returned_so_the_rule_can_change_without_a_refetch():
    # parse never drops rows; it labels them. The loader stores all of them.
    for row in FOUNTAINS.values():
        parse_fountain(row, LOADED_AT)


def test_unknown_borough_code_is_rejected():
    with pytest.raises(RowError):
        parse_fountain(dict(FOUNTAINS["outdoor_open"], borough="Z"), LOADED_AT)


# --- restrooms -----------------------------------------------------------------


def test_restroom_keeps_status_and_open_schedule_as_given():
    out = parse_restroom(RESTROOMS["operational_park"], LOADED_AT)
    assert out["status"] == "Operational"
    assert out["open_schedule"] == "Year Round"
    assert out["hours_of_operation"] == "8am-4pm, Open later seasonally"
    assert out["lat"] == pytest.approx(40.85438)
    assert json.loads(out["geom_geojson"])["coordinates"] == pytest.approx([out["lon"], out["lat"]])


def test_restroom_not_operational_is_kept_with_null_schedule():
    out = parse_restroom(RESTROOMS["not_operational"], LOADED_AT)
    assert out["status"] == "Not Operational"
    assert out["open_schedule"] is None


def test_restroom_multiline_hours_are_stored_verbatim():
    out = parse_restroom(RESTROOMS["multiline_hours"], LOADED_AT)
    assert "\n" in out["hours_of_operation"]


def test_restroom_missing_hours_stay_missing():
    assert parse_restroom(RESTROOMS["no_hours"], LOADED_AT)["hours_of_operation"] is None


def test_restroom_website_url_object_is_flattened():
    row = dict(RESTROOMS["operational_park"], website={"url": "https://example.org/x"})
    assert parse_restroom(row, LOADED_AT)["website"] == "https://example.org/x"


def test_restroom_coordinates_outside_nyc_are_rejected():
    row = dict(RESTROOMS["operational_park"], latitude="0", longitude="0", location_1=None)
    with pytest.raises(RowError):
        parse_restroom(row, LOADED_AT)


def test_restroom_missing_coordinates_are_rejected():
    row = {k: v for k, v in RESTROOMS["operational_park"].items() if k not in ("latitude", "longitude", "location_1")}
    with pytest.raises(RowError):
        parse_restroom(row, LOADED_AT)
