"""Turn osmium's GeoJSON export of OSM highway ways into insert-ready dicts."""

import json
from datetime import datetime

from etl.parsers import RowError

OSM_SOURCE_ID = "osm:geofabrik-new-york"

# Tags later phases use for scoring and routing checks; the rest of OSM's tags are dropped.
KEPT_TAGS = (
    "highway", "name", "ref", "surface", "foot", "bicycle", "access", "oneway",
    "bridge", "tunnel", "footway", "cycleway", "sidewalk", "lit",
    "crossing", "crossing:signals",  # signalized crossings per mile (decision 011)
)


def _line(feature: dict) -> tuple[str, int, str]:
    """(way id text, way id, EWKT) for a linestring way, or RowError."""
    way_id_text = feature.get("id")
    if not isinstance(way_id_text, str) or not way_id_text.startswith("w") or not way_id_text[1:].isdigit():
        raise RowError(f"not a way id: {way_id_text!r}")
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if geometry.get("type") != "LineString" or len(coords) < 2:
        raise RowError("not a line")
    wkt = ",".join(f"{lon} {lat}" for lon, lat in (c[:2] for c in coords))
    return way_id_text, int(way_id_text[1:]), f"SRID=4326;LINESTRING({wkt})"


def parse_way(feature: dict, loaded_at: datetime, source_updated_at: str | None) -> dict:
    way_id_text, way_id, ewkt = _line(feature)
    props = feature.get("properties") or {}
    if "highway" not in props:
        raise RowError("no highway tag")

    tags = {k: props[k] for k in KEPT_TAGS if k in props}
    return {
        "way_id": way_id,
        "source_dataset_id": OSM_SOURCE_ID,
        "source_row_id": way_id_text,
        "source_updated_at": source_updated_at,
        "loaded_at": loaded_at,
        "highway": props["highway"],
        "name": props.get("name"),
        "tags": json.dumps(tags),
        "geom_ewkt": ewkt,
    }


def parse_coastline(feature: dict, loaded_at: datetime, source_updated_at: str | None) -> dict:
    """A natural=coastline way, for waterfront share (Parks Properties misses Hudson River Park; decision 004)."""
    way_id_text, way_id, ewkt = _line(feature)
    if (feature.get("properties") or {}).get("natural") != "coastline":
        raise RowError("not a coastline way")
    return {
        "way_id": way_id,
        "source_dataset_id": OSM_SOURCE_ID,
        "source_row_id": way_id_text,
        "source_updated_at": source_updated_at,
        "loaded_at": loaded_at,
        "geom_ewkt": ewkt,
    }


PARK_LEISURE = ("park", "nature_reserve")


def parse_park(feature: dict, loaded_at: datetime, source_updated_at: str | None) -> dict:
    """An OSM park area (leisure=park or nature_reserve), for park anchors (decision 012). Unlike Parks Properties it
    includes Hudson River Park, Brooklyn Bridge Park and Governors Island."""
    area_id_text = feature.get("id")
    if not isinstance(area_id_text, str) or not area_id_text.startswith("a") or not area_id_text[1:].isdigit():
        raise RowError(f"not an area id: {area_id_text!r}")
    geometry = feature.get("geometry") or {}
    if geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise RowError("not a polygon")
    props = feature.get("properties") or {}
    if props.get("leisure") not in PARK_LEISURE:
        raise RowError("not a park")
    return {
        "area_id": int(area_id_text[1:]),
        "source_dataset_id": OSM_SOURCE_ID,
        "source_row_id": area_id_text,
        "source_updated_at": source_updated_at,
        "loaded_at": loaded_at,
        "name": props.get("name"),
        "leisure": props["leisure"],
        "geojson": json.dumps(geometry),
    }
