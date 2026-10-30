"""Load parsed NYC Open Data rows into PostGIS."""

import os
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from etl.parsers import (
    FOUNTAINS_DATASET_ID,
    PARKS_DATASET_ID,
    RESTROOMS_DATASET_ID,
    RowError,
    parse_fountain,
    parse_park,
    parse_restroom,
)

SCHEMA_PATH = Path(__file__).parent / "sql" / "schema.sql"
DEFAULT_DATABASE_URL = "postgresql://loop:loop@localhost:5432/loop"


@dataclass(frozen=True)
class TableSpec:
    table: str
    dataset_id: str
    parse: Callable[[dict, datetime], dict]
    # Runs after the insert, in the same transaction.
    post_sql: str | None = None


# Some source polygons have self-intersecting rings, which break area/overlap math.
# Record which ones, then repair them.
REPAIR_PARK_GEOMETRY = '''
    UPDATE parks SET
        geom_was_invalid = NOT ST_IsValid(geom),
        geom = ST_Multi(ST_CollectionExtract(ST_MakeValid(geom), 3))
'''

TABLES = [
    TableSpec("parks", PARKS_DATASET_ID, parse_park, post_sql=REPAIR_PARK_GEOMETRY),
    TableSpec("drinking_fountains", FOUNTAINS_DATASET_ID, parse_fountain),
    TableSpec("public_restrooms", RESTROOMS_DATASET_ID, parse_restroom),
]


@dataclass
class LoadReport:
    table: str
    dataset_id: str
    loaded: int = 0
    rejected: Counter = field(default_factory=Counter)  # reason -> count
    skipped: Counter = field(default_factory=Counter)  # fountains: reason -> count
    repaired: int = 0  # parks: polygons that needed ST_MakeValid


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def parse_rows(spec: TableSpec, raw_rows: list[dict], loaded_at: datetime) -> tuple[list[dict], LoadReport]:
    report = LoadReport(spec.table, spec.dataset_id)
    parsed = []
    for row in raw_rows:
        try:
            out = spec.parse(row, loaded_at)
        except RowError as exc:
            report.rejected[str(exc)] += 1
            continue
        if out.get("skip_reason"):
            report.skipped[out["skip_reason"]] += 1
        parsed.append(out)
    report.loaded = len(parsed)
    return parsed, report


def create_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text())


def replace_table(conn: psycopg.Connection, table: str, rows: list[dict]) -> None:
    """Swap a table's contents in the caller's transaction (idempotent reload)."""
    conn.execute(f"TRUNCATE {table} RESTART IDENTITY")
    if not rows:
        return
    columns = [c for c in rows[0] if c != "geom_geojson"]
    placeholders = [f"%({c})s::jsonb" if c == "raw" else f"%({c})s" for c in columns]
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}, geom) "
        f"VALUES ({', '.join(placeholders)}, ST_SetSRID(ST_GeomFromGeoJSON(%(geom_geojson)s), 4326))"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def load_table(conn: psycopg.Connection, spec: TableSpec, raw_rows: list[dict]) -> LoadReport:
    loaded_at = datetime.now(UTC)
    rows, report = parse_rows(spec, raw_rows, loaded_at)
    with conn.transaction():
        replace_table(conn, spec.table, rows)
        if spec.post_sql:
            conn.execute(spec.post_sql)
        if spec.table == "parks":
            report.repaired = conn.execute("SELECT count(*) FROM parks WHERE geom_was_invalid").fetchone()[0]
    return report
