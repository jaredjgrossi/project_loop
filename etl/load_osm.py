"""Load OSM street and path geometry into PostGIS:  python -m etl.load_osm

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
from etl.osm_parser import parse_way
from etl.parsers import RowError

ROOT = Path(__file__).resolve().parent.parent
NYC_PBF = ROOT / "routing" / "data" / "nyc.osm.pbf"
STATE_PBF = ROOT / "routing" / "data" / "new-york-latest.osm.pbf"
WORK_DIR = ROOT / "etl" / "data" / "raw"

COLUMNS = [
    "way_id", "source_dataset_id", "source_row_id", "source_updated_at", "loaded_at",
    "highway", "name", "tags", "geom_ewkt",
]


def export_highways(pbf: Path) -> Path:
    """Highway ways as GeoJSON lines with OSM ids, via osmium."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    filtered, out = WORK_DIR / "osm_highways.osm.pbf", WORK_DIR / "osm_highways.geojsonseq"
    subprocess.run(["osmium", "tags-filter", "--overwrite", "-o", str(filtered), str(pbf), "w/highway"], check=True)
    subprocess.run(
        ["osmium", "export", "--overwrite", "-f", "geojsonseq", "--add-unique-id=type_id",
         "--geometry-types=linestring", "-o", str(out), str(filtered)],
        check=True,
    )
    return out


def snapshot_time() -> str | None:
    """When Geofabrik took the snapshot, from the state extract's header."""
    if not STATE_PBF.exists():
        return None
    result = subprocess.run(
        ["osmium", "fileinfo", "-g", "header.option.osmosis_replication_timestamp", str(STATE_PBF)],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or None


def read_ways(path: Path, loaded_at: datetime, source_updated_at: str | None):
    rejected: Counter = Counter()
    rows = []
    with path.open() as fh:
        for line in fh:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            try:
                rows.append(parse_way(json.loads(line), loaded_at, source_updated_at))
            except RowError as exc:
                rejected[str(exc)] += 1
    return rows, rejected


def main() -> int:
    if shutil.which("osmium") is None:
        print("osmium not found. Install it with:  brew install osmium-tool", file=sys.stderr)
        return 1
    if not NYC_PBF.exists():
        print(f"{NYC_PBF} not found. Build it first:  python -m routing.prepare_osm", file=sys.stderr)
        return 1

    loaded_at = datetime.now(UTC)
    print("Exporting highway ways with osmium ...")
    rows, rejected = read_ways(export_highways(NYC_PBF), loaded_at, snapshot_time())

    with psycopg.connect(database_url(), autocommit=True) as conn:
        create_schema(conn)
        with conn.transaction():
            conn.execute("TRUNCATE osm_ways")
            with conn.cursor() as cur:
                cols = ", ".join(c if c != "geom_ewkt" else "geom" for c in COLUMNS)
                with cur.copy(f"COPY osm_ways ({cols}) FROM STDIN") as copy:
                    for row in rows:
                        copy.write_row([row[c] for c in COLUMNS])
        counts = conn.execute("SELECT highway, count(*) FROM osm_ways GROUP BY 1 ORDER BY 2 DESC LIMIT 6").fetchall()
    print(f"osm_ways             {len(rows):6d} rows  (source osm:geofabrik-new-york, snapshot {rows[0]['source_updated_at']})")
    print("  most common:", ", ".join(f"{h} {n}" for h, n in counts))
    for reason, n in rejected.items():
        print(f"  {n:6d} REJECTED: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
