"""Turn raw NYC Open Data rows into insert-ready dicts.

Every parsed row carries source_dataset_id, source_row_id, source_updated_at,
loaded_at, and the untouched source row (`raw`). Parsing labels rows but never
drops them; a row that can't be used (no geometry, outside NYC) raises RowError
so the loader can report it.
"""

import json
from datetime import date, datetime

PARKS_DATASET_ID = "enfh-gkve"  # Parks Properties
FOUNTAINS_DATASET_ID = "qnv7-p7a2"  # NYC Parks Drinking Fountains
RESTROOMS_DATASET_ID = "i7jb-7jku"  # Public Restrooms

BOROUGHS = {"M": "Manhattan", "B": "Brooklyn", "Q": "Queens", "X": "Bronx", "R": "Staten Island"}

NYC_LAT_RANGE = (40.45, 40.95)
NYC_LON_RANGE = (-74.30, -73.65)

# Fountain `fountainty` values that are not something a runner drinks from.
SINK_OR_COOLER_TYPES = {
    "Food Prep Sink",
    "Slop Sink",
    "Bathroom Sink",
    "Water Cooler",
    "Drinking Fountain Sink Combination",
}


class RowError(ValueError):
    """The row can't be loaded (missing or implausible geometry, unknown code)."""


def _provenance(row: dict, dataset_id: str, loaded_at: datetime) -> dict:
    return {
        "source_dataset_id": dataset_id,
        "source_row_id": row.get(":id"),
        "source_updated_at": row.get(":updated_at"),
        "loaded_at": loaded_at,
        "raw": json.dumps(row),
    }


def _text(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _borough(code) -> str | None:
    if code is None:
        return None
    try:
        return BOROUGHS[str(code).strip().upper()]
    except KeyError:
        raise RowError(f"unknown borough code {code!r}") from None


def _geojson(geometry, expected_type: str) -> str:
    if not isinstance(geometry, dict) or geometry.get("type") != expected_type or not geometry.get("coordinates"):
        raise RowError(f"missing or non-{expected_type} geometry")
    return json.dumps({"type": geometry["type"], "coordinates": geometry["coordinates"]})


def _in_nyc(lat: float, lon: float) -> bool:
    return NYC_LAT_RANGE[0] <= lat <= NYC_LAT_RANGE[1] and NYC_LON_RANGE[0] <= lon <= NYC_LON_RANGE[1]


def _point(geometry) -> tuple[float, float, str]:
    """lon, lat, GeoJSON for a Socrata point, checked to be inside NYC."""
    geom_json = _geojson(geometry, "Point")
    lon, lat = geometry["coordinates"][:2]
    if not _in_nyc(lat, lon):
        raise RowError(f"point ({lat}, {lon}) is outside NYC")
    return lon, lat, geom_json


def parse_park(row: dict, loaded_at: datetime) -> dict:
    acquired = _text(row.get("acquisitiondate"))
    return {
        **_provenance(row, PARKS_DATASET_ID, loaded_at),
        "source_key": _text(row.get("gispropnum")),
        "name": _text(row.get("signname")) or _text(row.get("name311")),
        "borough": _borough(row.get("borough")),
        "typecategory": _text(row.get("typecategory")),
        "subcategory": _text(row.get("subcategory")),
        "park_class": _text(row.get("class")),
        "jurisdiction": _text(row.get("jurisdiction")),
        "address": _text(row.get("address")),
        "acres": _float(row.get("acres")),
        "waterfront": row["waterfront"] if isinstance(row.get("waterfront"), bool) else None,
        "acquisition_date": date.fromisoformat(acquired[:10]) if acquired else None,
        "geom_geojson": _geojson(row.get("multipolygon"), "MultiPolygon"),
    }


def _fountain_skip_reason(row: dict) -> str | None:
    fountain_type = _text(row.get("fountainty"))
    position = _text(row.get("position")) or ""
    if "Indoor" in position or fountain_type == "Indoor Drinking Fountain":
        return "indoor"
    if fountain_type in SINK_OR_COOLER_TYPES:
        return "sink_or_cooler"
    if fountain_type == "Dog Fountain":
        return "dog_only"
    return None


def parse_fountain(row: dict, loaded_at: datetime) -> dict:
    _, _, geom_json = _point(row.get("the_geom"))
    skip_reason = _fountain_skip_reason(row)
    return {
        **_provenance(row, FOUNTAINS_DATASET_ID, loaded_at),
        "source_key": _text(row.get("system")),
        "fountain_type": _text(row.get("fountainty")),
        "position": _text(row.get("position")),
        "borough": _borough(row.get("borough")),
        "park_id": _text(row.get("gispropnum")),
        "property_name": _text(row.get("propertyna")),
        "description": _text(row.get("decription")),  # sic: the source column is misspelled
        "feature_status": _text(row.get("featuresta")),
        "usable": skip_reason is None,
        "skip_reason": skip_reason,
        "geom_geojson": geom_json,
    }


def parse_restroom(row: dict, loaded_at: datetime) -> dict:
    lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
    if lat is None or lon is None:
        raise RowError("missing latitude/longitude")
    if not _in_nyc(lat, lon):
        raise RowError(f"point ({lat}, {lon}) is outside NYC")
    website = row.get("website")
    if isinstance(website, dict):
        website = website.get("url")
    return {
        **_provenance(row, RESTROOMS_DATASET_ID, loaded_at),
        "facility_name": _text(row.get("facility_name")),
        "location_type": _text(row.get("location_type")),
        "operator": _text(row.get("operator")),
        "status": _text(row.get("status")),
        "open_schedule": _text(row.get("open")),
        "hours_of_operation": _text(row.get("hours_of_operation")),
        "accessibility": _text(row.get("accessibility")),
        "restroom_type": _text(row.get("restroom_type")),
        "changing_stations": _text(row.get("changing_stations")),
        "additional_notes": _text(row.get("additional_notes")),
        "website": _text(website),
        "lat": lat,
        "lon": lon,
        "geom_geojson": json.dumps({"type": "Point", "coordinates": [lon, lat]}),
    }
