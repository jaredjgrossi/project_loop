"""Neighborhood areas: NYC's 2020 Neighborhood Tabulation Areas (NTAs), for ends in a neighborhood (decision 042).

    uv run python -m etl.load_neighborhoods [--refresh]

OSM has New York's neighborhoods as points ("Williamsburg" is a place=quarter node), which say where a neighborhood
is but not how far it reaches. The Department of City Planning's 2020 NTAs (NYC Open Data 9nt8-h7nd) give each one
its shape. A neighborhood the runner names is the NTA holding its OSM point (api.places.neighborhood_area).

Writes neighborhood_areas, rebuilt from scratch each run. The download is cached in etl/data/raw/ (Socrata JSON
plus a provenance sidecar); --refresh fetches it again.
"""

import json
import sys
from datetime import UTC, datetime

import psycopg

from etl.load import database_url
from etl.socrata import RAW_DIR, download, read_meta, read_rows

NTA_DATASET_ID = "9nt8-h7nd"
SOURCE = "NYC Department of City Planning, 2020 Neighborhood Tabulation Areas"

DDL = """
DROP TABLE IF EXISTS neighborhood_areas;
CREATE TABLE neighborhood_areas (
    nta2020            text PRIMARY KEY,
    name               text NOT NULL,
    borough            text NOT NULL,
    nta_type           text,              -- 0 residential; 5-9 parks, cemeteries, airports and other non-residential
    geom               geometry(MultiPolygon, 4326) NOT NULL,
    source             text NOT NULL,
    source_dataset_id  text NOT NULL,
    source_row_id      text NOT NULL,
    source_updated_at  timestamptz,
    loaded_at          timestamptz NOT NULL
);
CREATE INDEX ON neighborhood_areas USING gist (geom);
"""


def rows_for_db(raw: list[dict], updated_at: str | None, loaded_at: datetime) -> list[tuple]:
    out = []
    for r in raw:
        geom = r.get("the_geom")
        if not geom or not r.get("nta2020") or not r.get("ntaname"):
            continue
        out.append((r["nta2020"], r["ntaname"], r.get("boroname") or "", r.get("ntatype"), json.dumps(geom), SOURCE,
                    NTA_DATASET_ID, r.get(":id") or r["nta2020"], updated_at, loaded_at))
    return out


def main(argv: list[str]) -> int:
    if "--refresh" in argv or not (RAW_DIR / f"{NTA_DATASET_ID}.json").exists():
        print(f"Downloading {NTA_DATASET_ID} from NYC Open Data ...")
        download(NTA_DATASET_ID)
    raw, meta = read_rows(NTA_DATASET_ID), read_meta(NTA_DATASET_ID)
    rows = rows_for_db(raw, meta.get("data_updated_at"), datetime.now(UTC))
    with psycopg.connect(database_url()) as conn:
        conn.execute(DDL)
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO neighborhood_areas VALUES (%s, %s, %s, %s,
                   ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), %s, %s, %s, %s, %s)""", rows)
        n = conn.execute("SELECT count(*) FROM neighborhood_areas").fetchone()[0]
    print(f"neighborhood_areas  {n} NTAs  (data updated {meta.get('data_updated_at')})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
