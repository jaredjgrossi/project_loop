"""Place lookups against the loaded places table (Phase 3, step 2; decision 026). Build it with `make places`,
then `uv run pytest evals/places`. Needs Postgres with the table loaded; skips otherwise (decision 019)."""

import psycopg
import pytest

from api.places import lookup, major_parks_near
from etl.load import database_url

KIPS_BAY = (40.7438, -73.9799)  # Kips Bay Library, the public stand-in
GRAND_ARMY_PLAZA = (40.6742, -73.9700)
BEDFORD_AV = (40.7172, -73.9567)  # the L at Bedford Av, Williamsburg


@pytest.fixture(scope="module")
def conn():
    try:
        c = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"Postgres not reachable ({exc}). Try: make up")
    if not c.execute("SELECT to_regclass('places') IS NOT NULL").fetchone()[0]:
        pytest.skip("places table not built. Run: make places")
    yield c
    c.close()


def one(conn, name, **kw):
    found = lookup(name, conn=conn, **kw)
    assert len(found) == 1, [(m.name, m.kind, m.borough) for m in found]
    return found[0]


def test_penn_station(conn):
    m = one(conn, "Penn Station")
    assert (m.kind, m.borough) == ("station", "Manhattan")
    assert m.name == "New York Penn Station" and m.trust == "listed" and m.source == "OpenStreetMap"


def test_mccarren_park(conn):
    m = one(conn, "McCarren Park")
    assert (m.name, m.kind, m.borough) == ("McCarren Park", "park", "Brooklyn")


def test_central_park_reservoir_by_its_everyday_name(conn):
    m = one(conn, "Central Park Reservoir")
    assert (m.name, m.kind, m.matched) == ("Jacqueline Kennedy Onassis Reservoir", "water", "Central Park Reservoir")


def test_central_park_south(conn):
    m = one(conn, "Central Park South")
    assert (m.kind, m.borough) == ("street", "Manhattan")


def test_86th_st_at_central_park_is_two_places(conn):
    park = one(conn, "Central Park")
    found = lookup("86th St", near=park, conn=conn)
    assert len(found) == 2, [(m.name, m.at) for m in found]
    east, west = sorted(found, key=lambda m: -m.lon)
    assert east.at == "5th Ave" and west.at == "Central Park West"
    assert {m.borough for m in found} == {"Manhattan"}


def test_86th_st_alone_is_several(conn):
    assert len({m.borough for m in lookup("86th St", conn=conn)}) >= 2


def test_crossing_1st_ave_and_e_23rd_st(conn):
    m = one(conn, "1st Ave & E 23rd St")
    assert (m.kind, m.borough) == ("crossing", "Manhattan")
    assert m.name == "1st Ave & E 23rd St"
    assert abs(m.lat - 40.7368) < 0.001 and abs(m.lon + 73.9785) < 0.001


def test_42nd_st_is_several_boroughs_and_the_nearest_is_manhattan(conn):
    every = lookup("42nd St", conn=conn)
    assert len({m.borough for m in every}) >= 2
    near = lookup("42nd St", near=KIPS_BAY, conn=conn)
    assert near[0].borough == "Manhattan" and near[0].distance_m < 1500
    assert [m.distance_m for m in near] == sorted(m.distance_m for m in near)
    close = lookup("42nd St", near=KIPS_BAY, near_m=3000, conn=conn)
    assert len(close) == 1 and close[0].name == "42nd St"  # East and West 42nd Street are one street


def test_e_42nd_st_is_only_the_east_side_in_both_boroughs_that_have_one(conn):
    found = lookup("E 42nd St", conn=conn)
    assert sorted(m.borough for m in found) == ["Brooklyn", "Manhattan"]  # East Flatbush has one too
    nearest = lookup("E 42nd St", near=KIPS_BAY, conn=conn)[0]
    assert (nearest.name, nearest.borough) == ("E 42nd St", "Manhattan") and nearest.lon > -73.982


def test_hudson_river_greenway(conn):
    m = one(conn, "Hudson River Greenway")
    assert (m.kind, m.borough) == ("path", "Manhattan")


def test_prospect_park_is_the_park_not_the_station(conn):
    m = one(conn, "Prospect Park")
    assert (m.kind, m.borough) == ("park", "Brooklyn")


@pytest.mark.parametrize("name", ["Hoboken", "Hoboken PATH", "Jersey City"])
def test_new_jersey_finds_nothing(conn, name):
    assert lookup(name, conn=conn) == []


def test_the_park_from_kips_bay_is_none(conn):
    assert major_parks_near(*KIPS_BAY, conn=conn) == []


def test_the_park_from_grand_army_plaza_is_prospect_park(conn):
    assert major_parks_near(*GRAND_ARMY_PLAZA, conn=conn)[0].name == "Prospect Park"


def test_the_park_from_bedford_av_is_mccarren(conn):
    assert major_parks_near(*BEDFORD_AV, conn=conn)[0].name == "McCarren Park"


def test_every_row_keeps_source_and_load_time(conn):
    (bad,) = conn.execute(
        """SELECT count(*) FROM places WHERE source IS NULL OR source_dataset_id IS NULL OR source_row_id IS NULL
           OR loaded_at IS NULL OR trust <> 'listed' OR borough IS NULL""").fetchone()
    assert bad == 0


def test_row_counts_by_kind(conn):
    counts = dict(conn.execute("SELECT kind, count(*) FROM places GROUP BY kind").fetchall())
    for kind in ("station", "subway_station", "park", "square", "water", "bridge", "street", "path", "crossing",
                 "amenity", "shop"):
        assert counts.get(kind, 0) > 0, kind
