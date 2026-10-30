"""Turn osmium's GeoJSON export of OSM highway ways into insert-ready dicts."""

import json
from datetime import datetime

from etl.parsers import RowError

OSM_SOURCE_ID = "osm:geofabrik-new-york"

# Tags later phases use for scoring and routing checks; the rest of OSM's tags are dropped.
KEPT_TAGS = (
    "highway", "name", "ref", "surface", "foot", "bicycle", "access", "oneway",
    "bridge", "tunnel", "footway", "cycleway", "sidewalk", "lit",
)


def parse_way(feature: dict, loaded_at: datetime, source_updated_at: str | None) -> dict:
    way_id_text = feature.get("id")
    if not isinstance(way_id_text, str) or not way_id_text.startswith("w") or not way_id_text[1:].isdigit():
        raise RowError(f"not a way id: {way_id_text!r}")
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if geometry.get("type") != "LineString" or len(coords) < 2:
        raise RowError("not a line")
    props = feature.get("properties") or {}
    if "highway" not in props:
        raise RowError("no highway tag")

    tags = {k: props[k] for k in KEPT_TAGS if k in props}
    wkt = ",".join(f"{lon} {lat}" for lon, lat in (c[:2] for c in coords))
    return {
        "way_id": int(way_id_text[1:]),
        "source_dataset_id": OSM_SOURCE_ID,
        "source_row_id": way_id_text,
        "source_updated_at": source_updated_at,
        "loaded_at": loaded_at,
        "highway": props["highway"],
        "name": props.get("name"),
        "tags": json.dumps(tags),
        "geom_ewkt": f"SRID=4326;LINESTRING({wkt})",
    }
