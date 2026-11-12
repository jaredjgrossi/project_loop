"""Curated landmarks into the places table:  python -m etl.load_landmarks  (also run by make places)

Decision 047 (full review 4.2, Q4 and Q5). The places extract loads named nodes and a few kinds of area. A New Yorker's
landmarks are mostly building outlines and relations (the Met, the Empire State Building, Yankee Stadium), so "10k past
the Met then home" came back "Couldn't find Metropolitan Museum of Art". etl/curated/landmarks.json lists them, each with a
position taken from its OSM outline; they load as kind `landmark`, trust `listed`, source named on every row.

Run on its own it replaces the landmark rows and refreshes the normalized names, without rebuilding the table.
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from etl.load import database_url

LANDMARKS = Path(__file__).resolve().parent / "curated" / "landmarks.json"
BOROUGHS = ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island")
SOURCE = "Loop curated landmarks (position from OpenStreetMap)"
DATASET = "loop:landmarks"


def read_landmarks() -> list[dict]:
    return json.loads(LANDMARKS.read_text())["landmarks"]


def landmark_rows(landmarks: list[dict]) -> list[dict]:
    """The places rows for the curated landmarks."""
    return [{"name": l["name"], "kind": "landmark", "category": l["what"], "borough": l["borough"],
             "aliases": l["aliases"], "lat": l["lat"], "lon": l["lon"], "source": SOURCE, "source_dataset_id": DATASET,
             "source_row_id": "landmark/" + re.sub(r"[^a-z0-9]+", "-", l["name"].casefold()).strip("-")}
            for l in landmarks]


def load_landmarks(conn, loaded_at) -> int:
    """Replace the landmark rows. Needs the places table."""
    conn.execute("DELETE FROM places WHERE source_dataset_id = %s", (DATASET,))
    rows = landmark_rows(read_landmarks())
    for r in rows:
        conn.execute(
            """INSERT INTO places (name, kind, category, borough, aliases, geom, source, source_dataset_id,
                                   source_row_id, loaded_at)
               VALUES (%(name)s, %(kind)s, %(category)s, %(borough)s, %(aliases)s,
                       ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326), %(source)s, %(source_dataset_id)s,
                       %(source_row_id)s, %(loaded_at)s)""", r | {"loaded_at": loaded_at})
    return len(rows)


def main() -> int:
    from etl.load_places import fill_names
    with psycopg.connect(database_url()) as conn, conn.transaction():
        n = load_landmarks(conn, datetime.now(UTC))
        fill_names(conn)
    print(f"landmarks {n} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
