"""Scheduled crowd pulses on paths (decision 022). Needs the live stack and `make pulses`:  uv run pytest evals/

The morning moment is SeaStreak's published 08:00 arrival at East 35th St on a school day (Wednesday 2026-11-04);
mid-morning (10:30) is outside every window.
"""

from datetime import datetime

import psycopg
import pytest

from api.crowds import route_crowds
from etl.load import database_url
from evals.routes.live import stack_problem, top_loops

SCHOOL_DAY_8AM = datetime(2026, 11, 4, 8, 0)
MID_MORNING = datetime(2026, 11, 4, 10, 30)
ELECTION_DAY_8AM = datetime(2026, 11, 3, 8, 0)  # DOE: school in session remotely, so no school pulses
SIMPLE, BOTH_WAYS = "out-and-back on the waterfront", "out-and-back both ways on the waterfront"


@pytest.fixture(scope="module")
def conn():
    problem = stack_problem()
    if problem:
        pytest.skip(problem)
    c = psycopg.connect(database_url())
    if not c.execute("SELECT to_regclass('pulse_ways') IS NOT NULL").fetchone()[0]:
        pytest.skip("pulse sources not loaded. Run: make pulses")
    yield c
    c.close()


def causes(conn, candidate, when) -> set[str]:
    levels = route_crowds(conn, candidate.route.coordinates, when)["levels"]
    return {basis.split(" (")[0] for lv, basis, band in levels if band == "pulse"}


def kips_bay_3(when):
    """The two waterfront out-and-backs these tests are about, from the first 20 candidates, not the top 3: whether
    "both ways" ranks in the top 3 depends on the day's crowds (election day pushes it to 4th), and this eval is about
    what the pulses do to each route, not their rank (stale after decision 045, full review 'What I ran')."""
    pool = top_loops("kips-bay", 3, 20, use_prior=False, when=when)
    by = {}
    for c in pool:  # the best of each name: the pool is sorted best first
        by.setdefault(c.label.split(", heading")[0], c)
    assert SIMPLE in by and BOTH_WAYS in by, [c.label for c in pool]
    return by[SIMPLE], by[BOTH_WAYS]


def test_the_kips_bay_sources_are_loaded(conn):
    names = {r[0] for r in conn.execute(
        """SELECT DISTINCT s.name FROM pulse_sources s JOIN pulse_ways w ON w.source_id = s.id
           WHERE ST_DWithin(s.geom::geography, ST_SetSRID(ST_MakePoint(-73.972, 40.740), 4326)::geography, 700)""")}
    assert {"United Nations International School", "East 34th Street", "East 35th St"} <= names


ACROSS_A_STREET = ("The River School", "Brearley School", "M.S. 224 Manhattan East School for Arts & Academic",
                   "School of Cooperative Technical Education", "P.S. 146 Ann M. Short", "P.S. 158 Bayard Taylor")


def test_schools_across_a_street_from_the_path_do_not_pulse(conn):
    # Their students never enter the path (the reviewer, 2026-11-03): The River School is across the FDR from the
    # East River esplanade; the Upper East Side schools that made Bobby Wagner Walk 82% busy are across the FDR or East
    # End Avenue. Brearley keeps 13 m of entrance steps and connectors at E 83rd St, with no street between.
    (n,) = conn.execute("""SELECT count(w.way_id) FROM pulse_sources s LEFT JOIN pulse_ways w ON w.source_id = s.id
                           WHERE s.name = 'The River School'""").fetchone()
    assert n == 0, f"The River School pulses {n} path ways"
    for miles in (3, 4, 6):
        for c in top_loops("upper-east-side", miles, 3, use_prior=False, when=SCHOOL_DAY_8AM):
            met = {f for f in causes(conn, c, SCHOOL_DAY_8AM) if any(name in f for name in ACROSS_A_STREET)}
            assert not met, (miles, c.label, met)


def test_at_8am_on_a_school_day_both_waterfront_routes_meet_the_ferry_and_school_pulses(conn):
    for c in kips_bay_3(SCHOOL_DAY_8AM):
        found = causes(conn, c, SCHOOL_DAY_8AM)
        assert any("arrival" in f and ("East 34th" in f or "East 35th" in f) for f in found), (c.label, found)
        assert any(f.startswith("school arrival") for f in found), (c.label, found)


def test_both_ways_scores_worse_than_the_simple_out_and_back_at_8am(conn):
    simple, both = kips_bay_3(SCHOOL_DAY_8AM)
    assert both.context.crowd_high_pct > simple.context.crowd_high_pct
    crowds = lambda c: next(d for d in c.ranking.dimensions if d.key == "crowds")
    assert crowds(both).fit < crowds(simple).fit and both.score < simple.score


def test_mid_morning_is_outside_every_window(conn):
    for c in top_loops("kips-bay", 3, 3, use_prior=False, when=MID_MORNING):
        assert not causes(conn, c, MID_MORNING), c.label


def test_no_school_pulse_when_doe_has_no_students_but_the_ferry_still_runs(conn):
    found = set().union(*(causes(conn, c, ELECTION_DAY_8AM) for c in kips_bay_3(ELECTION_DAY_8AM)))
    assert not any(f.startswith("school") for f in found), found
    assert any("East 34th" in f or "East 35th" in f for f in found), found
