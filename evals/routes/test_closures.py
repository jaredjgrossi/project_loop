"""Known closures (decision 017): no generated route at any review start passes through one, and none enters a
curated closure at all.

Needs the live stack and the closures built (`make corridors`):  uv run pytest evals/

The route check is PostGIS's own intersection length against every applied closure in the city, so neither the
generator's sampled length nor its reach filter is being trusted to check itself.
"""

import json
from datetime import date

import psycopg
import pytest

from api.closures import CURATED_FILE, PASS_THROUGH_M, REPORT_BUFFER_M, Closure, parse_curated, passes_through
from etl.build_closures import WALKABLE
from etl.load import database_url
from evals.routes.live import load_starts, stack_problem, top_loops

EAST_MIDTOWN_GAP = {"lon": -73.96390, "lat": 40.75485, "within_m": 300}  # the 709 m gap (decision 012)
TOP = 3
# Real paths that earlier drafts of 017 closed, because a gap's line lay along them. They must stay open.
STAYS_OPEN = {
    "Queensboro Bridge outer roadway (foot=designated, access=no)": (-73.95208, 40.75583),
    "Hudson River Park Esplanade near Christopher St": (-74.01076, 40.73222),
    "Brooklyn Bridge Park Greenway at Old Fulton St": (-73.99441, 40.70333),
    "Willets Point Blvd at Flushing Bay": (-73.84393, 40.75879),
}
ROWS = [(sid, mi) for sid, s in load_starts().items() for mi in s["miles"]]

INSIDE = """
SELECT c.id, c.name, ST_Length(ST_Intersection(r.g, c.geom)::geography)
FROM closures c, (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326) AS g) r
WHERE c.applied AND ST_Intersects(r.g, c.geom)
"""


@pytest.fixture(scope="module")
def conn():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)
    c = psycopg.connect(database_url())
    if not c.execute("SELECT to_regclass('closures') IS NOT NULL").fetchone()[0] or \
            not c.execute("SELECT count(*) FROM closures WHERE applied").fetchone()[0]:
        pytest.skip("closures not built. Run: make corridors")
    yield c
    c.close()


def through(conn, coords) -> list[str]:
    rows = conn.execute(INSIDE, (json.dumps({"type": "LineString", "coordinates": coords}),)).fetchall()
    return [f"{name} (#{cid}, {m:.0f} m inside)" for cid, name, m in rows if m >= PASS_THROUGH_M]


def test_the_east_midtown_greenway_gap_is_an_applied_closure(conn):
    g = EAST_MIDTOWN_GAP
    rows = conn.execute(
        """SELECT c.applied, c.trust, c.source FROM closures c JOIN corridor_gaps g ON g.id = c.corridor_gap_id
           WHERE c.kind = 'corridor_gap' AND g.kind = 'internal' AND g.gap_m BETWEEN 650 AND 770
             AND ST_DWithin(ST_Centroid(g.geom)::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)""",
        (g["lon"], g["lat"], g["within_m"])).fetchall()
    assert rows and rows[0][0], f"East Midtown Greenway gap closure: {rows}"
    assert rows[0][1] == "listed" and rows[0][2].startswith("Loop corridor catalog gap")


def test_no_applied_catalog_closure_lies_on_walkable_ways(conn):
    # Summed in any direction, so stricter than the build's along-the-link test.
    rows = conn.execute(f"""
        SELECT c.name, round(sum(ST_Length(ST_Intersection(w.geom, c.geom)::geography)))
        FROM closures c JOIN osm_ways w ON ST_Intersects(w.geom, c.geom) AND {WALKABLE}
        WHERE c.applied AND c.kind = 'corridor_gap' GROUP BY c.name""").fetchall()
    assert all(m < PASS_THROUGH_M for _, m in rows), rows


@pytest.mark.parametrize("place", sorted(STAYS_OPEN))
def test_real_paths_stay_open(conn, place):
    lon, lat = STAYS_OPEN[place]
    rows = conn.execute(
        """SELECT name FROM closures WHERE applied
           AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 20)""", (lon, lat)).fetchall()
    assert not rows, f"{place} is inside closure {rows}"


def test_the_missing_link_is_closed_and_the_detour_around_it_is_open(conn):
    link, detour = conn.execute(
        """SELECT ST_AsGeoJSON(ST_MakeLine(ST_StartPoint(g.geom), ST_EndPoint(g.geom))), ST_AsGeoJSON(g.geom)
           FROM closures c JOIN corridor_gaps g ON g.id = c.corridor_gap_id
           WHERE c.applied AND g.kind = 'internal' AND g.gap_m BETWEEN 650 AND 770""").fetchone()
    assert through(conn, json.loads(link)["coordinates"]), "a route along the missing link should be through it"
    assert not through(conn, json.loads(detour)["coordinates"]), "the streets around the gap must stay open"


@pytest.mark.parametrize("lights", ["zigzags", "waits"])
@pytest.mark.parametrize(("start_id", "miles"), ROWS, ids=[f"{s}-{m:g}mi" for s, m in ROWS])
def test_no_generated_route_passes_through_a_known_closure(conn, start_id, miles, lights):
    candidates = top_loops(start_id, miles, TOP, prefs=(("lights", lights),))
    assert candidates, f"no route from {start_id} at {miles:g} mi"
    offenders = {rank: hit for rank, c in enumerate(candidates, 1) if (hit := through(conn, c.route.coordinates))}
    assert not offenders, f"{start_id} {miles:g} mi: {offenders}"


def test_a_confirmed_report_reroutes_the_route_it_was_reported_on(conn):
    # As if a runner reported the middle of the Upper East Side 3 mi #1 (on Bobby Wagner Walk) closed and a reviewer
    # confirmed it: the closure is that stretch buffered like a confirmed report, given to the router and the rules.
    before = top_loops("upper-east-side", 3, TOP)[0]
    (area,) = conn.execute(
        f"""SELECT ST_AsGeoJSON(ST_Transform(ST_Buffer(ST_Transform(ST_LineSubstring(
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 0.25, 0.4), 2263), {REPORT_BUFFER_M} * 3.28084), 4326))""",
        (json.dumps({"type": "LineString", "coordinates": before.route.coordinates}),)).fetchone()
    reported = Closure(999_999, "report", "test report", "closed or blocked", "eval", "listed",
                       json.loads(area)["coordinates"], in_router=True)
    assert passes_through(before.route.coordinates, reported)
    after = top_loops("upper-east-side", 3, TOP, extra_closures=(reported,))
    assert after, "no route once the stretch is closed"
    assert not any(passes_through(c.route.coordinates, reported) for c in after)


# --- curated closures --------------------------------------------------------------------

ENTERS_M = 1.0  # "enters": more than a meter of the route inside the closed area, not just touching its edge


def test_every_curated_closure_is_loaded_as_applied_with_its_sources_and_dates(conn):
    entries = parse_curated(json.loads(CURATED_FILE.read_text()))
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT curated_id, applied, in_router, trust, source, checked_on, review_by FROM closures WHERE kind = 'curated'")}
    assert set(rows) == {e.id for e in entries}, "closures table out of date with the curated file. Run: make closures"
    for e in entries:
        applied, in_router, trust, source, checked, review = rows[e.id]
        assert applied and in_router and trust == e.trust and (checked, review) == (e.checked_on, e.review_by)
        assert all(s in source for s in e.sources)


def test_no_curated_closure_is_past_its_review_by_date():
    overdue = [f"{e.id} (review by {e.review_by})" for e in parse_curated(json.loads(CURATED_FILE.read_text()))
               if e.review_by < date.today()]
    assert not overdue, f"check the sources again and update checked_on and review_by: {overdue}"


@pytest.mark.parametrize("lights", ["zigzags", "waits"])
@pytest.mark.parametrize(("start_id", "miles"), ROWS, ids=[f"{s}-{m:g}mi" for s, m in ROWS])
def test_no_generated_route_enters_a_curated_closure(conn, start_id, miles, lights):
    candidates = top_loops(start_id, miles, TOP, prefs=(("lights", lights),))
    offenders = {}
    for rank, c in enumerate(candidates, 1):
        rows = conn.execute(INSIDE.replace("WHERE c.applied", "WHERE c.applied AND c.kind = 'curated'"),
                            (json.dumps({"type": "LineString", "coordinates": c.route.coordinates}),)).fetchall()
        if hit := [f"{name} ({m:.0f} m inside)" for _, name, m in rows if m > ENTERS_M]:
            offenders[rank] = hit
    assert not offenders, f"{start_id} {miles:g} mi: {offenders}"
