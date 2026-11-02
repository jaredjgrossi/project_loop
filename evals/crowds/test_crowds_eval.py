"""Crowd eval (decisions 013, 016). Needs Postgres with etl.load_crowds run.

1. Rank agreement with DOT's bi-annual counts at street sites, on the latest round (May 2026), held out: the model's
   subway volume at each site, against that round's count, per period. It must stay at or above 0.70. The model has
   no parameters fitted to DOT counts (013 fixed the kernel before comparing), so the held-out round is a fair test.
2. Times Square on a weekday at 6pm is high.
3. A residential block more than 800 m from the subway (near the Victory Blvd review start, Staten Island) is low.
"""

import json
from pathlib import Path

import psycopg
import pytest
from scipy.stats import spearmanr

from api.crowds import BANDS, STATION_CUT_M, STATION_SIGMA_M
from etl.load import database_url

HELD_OUT = "may26"
PERIOD_BAND = {"am": "weekday_am", "pm": "weekday_pm", "md": "saturday_midday"}
MIN_RHO = 0.70
TIMES_SQUARE = json.loads((Path(__file__).resolve().parents[2] / "routing" / "no_go_zones.geojson").read_text())["features"][0]
QUIET_BLOCK = (-74.15411, 40.60484)  # the Victory Blvd review start


@pytest.fixture(scope="module")
def conn():
    try:
        c = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"Postgres not reachable ({exc}). Try: make up")
    if not c.execute("SELECT to_regclass('sidewalk_crowd') IS NOT NULL").fetchone()[0]:
        pytest.skip("crowd tables not built. Run: uv run python -m etl.load_crowds")
    yield c
    c.close()


SITE_VOLUME = f"""
WITH f AS (SELECT complex_id, avg(flow) AS flow, avg(lat) AS lat, avg(lon) AS lon FROM station_flow
           WHERE daytype = %(daytype)s AND hour = ANY(%(hours)s) GROUP BY complex_id)
SELECT d.site, d.count, coalesce(sum(f.flow * exp(-0.5 * power(
           ST_Distance(ST_SetSRID(ST_MakePoint(d.lon, d.lat), 4326)::geography,
                       ST_SetSRID(ST_MakePoint(f.lon, f.lat), 4326)::geography) / {STATION_SIGMA_M}, 2))), 0)
FROM dot_ped_counts d LEFT JOIN f ON ST_DWithin(ST_SetSRID(ST_MakePoint(d.lon, d.lat), 4326)::geography,
                                                ST_SetSRID(ST_MakePoint(f.lon, f.lat), 4326)::geography, {STATION_CUT_M})
WHERE d.kind = 'street' AND d.round = %(round)s AND d.period = %(period)s
GROUP BY d.site, d.count
"""


@pytest.mark.parametrize("period", ["am", "pm", "md"])
def test_rank_agreement_with_the_held_out_dot_round(conn, period):
    daytype, hours, label = BANDS[PERIOD_BAND[period]]
    rows = conn.execute(SITE_VOLUME, {"daytype": daytype, "hours": hours, "round": HELD_OUT, "period": period}).fetchall()
    assert len(rows) >= 80, f"only {len(rows)} street sites with a {HELD_OUT} {period} count"
    rho = spearmanr([r[1] for r in rows], [r[2] for r in rows])[0]
    print(f"{label}: Spearman {rho:.2f} over {len(rows)} street sites ({HELD_OUT}, held out)")
    assert rho >= MIN_RHO, f"Spearman {rho:.2f} < {MIN_RHO} for {label}"


def test_times_square_is_high_on_a_weekday_evening(conn):
    rows = conn.execute(
        """SELECT c.level, count(*) FROM sidewalk_crowd c JOIN osm_ways w USING (way_id)
           WHERE c.band = 'weekday_pm' AND ST_Intersects(w.geom, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))
           GROUP BY c.level""", (json.dumps(TIMES_SQUARE["geometry"]),)).fetchall()
    levels = dict(rows)
    assert levels, "no sidewalk ways in Times Square"
    assert max(levels, key=levels.get) == "high", f"Times Square sidewalk levels at 4-7pm: {levels}"


def test_a_residential_block_far_from_the_subway_is_low(conn):
    rows = conn.execute(
        """SELECT c.level, c.basis, c.nearest_station_m FROM sidewalk_crowd c JOIN osm_ways w USING (way_id)
           WHERE c.band = 'weekday_pm' AND ST_DWithin(w.geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 150)""",
        QUIET_BLOCK).fetchall()
    assert rows, "no sidewalk ways near the quiet block"
    assert all(r[0] == "low" for r in rows) and all(r[2] > 800 for r in rows)
    assert all("far from the subway" in r[1] for r in rows)
