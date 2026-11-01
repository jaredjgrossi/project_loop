"""Regression checks for the corridor catalog (decisions 012, 014): rebuild with `make corridors`, then
`uv run pytest evals/`. Needs Postgres with the catalog built."""

import psycopg
import pytest

from etl.load import database_url

COUNT_RANGE = (130, 200)  # 160 on the 2026-10-28 OSM snapshot
EAST_MIDTOWN_GAP = {"lon": -73.96390, "lat": 40.75485, "within_m": 300, "gap_m": (650, 770)}  # 709 m when found
STREETLIKE = r"\m(street|avenue|road|boulevard|place|lane)\M$"  # a stretch name must not be a bare street name


@pytest.fixture(scope="module")
def conn():
    try:
        c = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"Postgres not reachable ({exc}). Try: make up")
    if not c.execute("SELECT to_regclass('corridors') IS NOT NULL").fetchone()[0]:
        pytest.skip("corridor catalog not built. Run: make corridors")
    yield c
    c.close()


def test_corridor_count_stays_in_range(conn):
    (n,) = conn.execute("SELECT count(*) FROM corridors").fetchone()
    assert COUNT_RANGE[0] <= n <= COUNT_RANGE[1], f"{n} corridors; expected {COUNT_RANGE[0]}-{COUNT_RANGE[1]}"


def test_the_east_midtown_greenway_gap_is_found(conn):
    g = EAST_MIDTOWN_GAP
    rows = conn.execute(
        """SELECT round(gap_m) FROM corridor_gaps WHERE kind = 'internal'
           AND ST_DWithin(ST_Centroid(geom)::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)""",
        (g["lon"], g["lat"], g["within_m"]),
    ).fetchall()
    assert any(g["gap_m"][0] <= r[0] <= g["gap_m"][1] for r in rows), f"internal gaps found there: {rows}"


def test_no_corridor_is_named_like_a_street(conn):
    bad = conn.execute("SELECT name FROM corridors WHERE name ~* %s", (STREETLIKE,)).fetchall()
    assert not bad, f"street-like corridor names: {[b[0] for b in bad]}"


def test_every_corridor_has_a_name_and_a_name_source(conn):
    (n,) = conn.execute(
        "SELECT count(*) FROM corridors WHERE coalesce(name, '') = '' OR name_source NOT IN ('way', 'park', 'none')"
    ).fetchone()
    assert n == 0
