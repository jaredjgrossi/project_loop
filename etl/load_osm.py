"""Load OSM street and path geometry, and the coastline, into PostGIS:  python -m etl.load_osm

Reads routing/data/nyc.osm.pbf (build it with `python -m routing.prepare_osm`).
Needs osmium (brew install osmium-tool).
"""

import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from etl.load import create_schema, database_url
from etl.osm_parser import parse_coastline, parse_park, parse_way
from etl.parsers import RowError

ROOT = Path(__file__).resolve().parent.parent
NYC_PBF = ROOT / "routing" / "data" / "nyc.osm.pbf"
STATE_PBF = ROOT / "routing" / "data" / "new-york-latest.osm.pbf"
WORK_DIR = ROOT / "etl" / "data" / "raw"

COLUMNS = [
    "way_id", "source_dataset_id", "source_row_id", "source_updated_at", "loaded_at",
    "highway", "name", "tags", "geom_ewkt",
]
COASTLINE_COLUMNS = ["way_id", "source_dataset_id", "source_row_id", "source_updated_at", "loaded_at", "geom_ewkt"]


def export_ways(pbf: Path, osm_filter: str, name: str, geometry_types: str = "linestring") -> Path:
    """Features matching an osmium tags-filter expression, as GeoJSON lines with OSM ids."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    filtered, out = WORK_DIR / f"{name}.osm.pbf", WORK_DIR / f"{name}.geojsonseq"
    subprocess.run(["osmium", "tags-filter", "--overwrite", "-o", str(filtered), str(pbf), osm_filter], check=True)
    subprocess.run(
        ["osmium", "export", "--overwrite", "-f", "geojsonseq", "--add-unique-id=type_id",
         f"--geometry-types={geometry_types}", "-o", str(out), str(filtered)],
        check=True,
    )
    return out


def load_parks(conn, rows: list[dict]) -> None:
    """Polygons arrive as GeoJSON; PostGIS builds, repairs (some OSM multipolygons self-intersect) and casts them."""
    with conn.transaction():
        conn.execute("TRUNCATE osm_parks")
        conn.execute("CREATE TEMP TABLE parks_in (LIKE osm_parks INCLUDING DEFAULTS, geojson text) ON COMMIT DROP")
        conn.execute("ALTER TABLE parks_in ALTER COLUMN geom DROP NOT NULL")
        cols = ["area_id", "source_dataset_id", "source_row_id", "source_updated_at", "loaded_at", "name", "leisure", "geojson"]
        with conn.cursor().copy(f"COPY parks_in ({', '.join(cols)}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row([row[c] for c in cols])
        conn.execute(
            """INSERT INTO osm_parks (area_id, source_dataset_id, source_row_id, source_updated_at, loaded_at, name, leisure, geom)
               SELECT area_id, source_dataset_id, source_row_id, source_updated_at, loaded_at, name, leisure,
                      ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(geojson), 4326)), 3))
               FROM parks_in"""
        )


def export_highways(pbf: Path) -> Path:
    return export_ways(pbf, "w/highway", "osm_highways")


def snapshot_time() -> str | None:
    """When Geofabrik took the snapshot, from the state extract's header."""
    if not STATE_PBF.exists():
        return None
    result = subprocess.run(
        ["osmium", "fileinfo", "-g", "header.option.osmosis_replication_timestamp", str(STATE_PBF)],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or None


def read_ways(path: Path, loaded_at: datetime, source_updated_at: str | None, parse=parse_way):
    rejected: Counter = Counter()
    rows = []
    with path.open() as fh:
        for line in fh:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            try:
                rows.append(parse(json.loads(line), loaded_at, source_updated_at))
            except RowError as exc:
                rejected[str(exc)] += 1
    return rows, rejected


def load_rows(conn, table: str, columns: list[str], rows: list[dict]) -> None:
    """Truncate and reload in one transaction, so a re-run is safe."""
    with conn.transaction():
        conn.execute(f"TRUNCATE {table}")
        with conn.cursor() as cur:
            cols = ", ".join(c if c != "geom_ewkt" else "geom" for c in columns)
            with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row([row[c] for c in columns])


def main() -> int:
    if shutil.which("osmium") is None:
        print("osmium not found. Install it with:  brew install osmium-tool", file=sys.stderr)
        return 1
    if not NYC_PBF.exists():
        print(f"{NYC_PBF} not found. Build it first:  python -m routing.prepare_osm", file=sys.stderr)
        return 1

    loaded_at = datetime.now(UTC)
    print("Exporting highway ways with osmium ...")
    snapshot = snapshot_time()
    rows, rejected = read_ways(export_highways(NYC_PBF), loaded_at, snapshot)
    print("Exporting coastline ways with osmium ...")
    coast, coast_rejected = read_ways(
        export_ways(NYC_PBF, "w/natural=coastline", "osm_coastline"), loaded_at, snapshot, parse=parse_coastline
    )
    print("Exporting park areas with osmium ...")
    parks, parks_rejected = read_ways(
        export_ways(NYC_PBF, "a/leisure=park,nature_reserve", "osm_parks", geometry_types="polygon"),
        loaded_at, snapshot, parse=parse_park,
    )

    with psycopg.connect(database_url(), autocommit=True) as conn:
        create_schema(conn)
        load_rows(conn, "osm_ways", COLUMNS, rows)
        load_rows(conn, "osm_coastline", COASTLINE_COLUMNS, coast)
        load_parks(conn, parks)
        counts = conn.execute("SELECT highway, count(*) FROM osm_ways GROUP BY 1 ORDER BY 2 DESC LIMIT 6").fetchall()
    print(f"osm_ways             {len(rows):6d} rows  (source osm:geofabrik-new-york, snapshot {rows[0]['source_updated_at']})")
    print("  most common:", ", ".join(f"{h} {n}" for h, n in counts))
    for reason, n in rejected.items():
        print(f"  {n:6d} REJECTED: {reason}")
    print(f"osm_coastline        {len(coast):6d} rows")
    for reason, n in coast_rejected.items():
        print(f"  {n:6d} REJECTED: {reason}")
    print(f"osm_parks            {len(parks):6d} rows")
    for reason, n in parks_rejected.items():
        print(f"  {n:6d} REJECTED: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
