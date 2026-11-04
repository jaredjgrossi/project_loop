"""Build the closures table (decision 017): corridor-gap closures from the corridor catalog, and the curated closures.

    uv run python -m etl.build_closures      (after etl.build_corridors; run by make corridors and make closures)

Curated closures (routing/curated_closures.geojson, parsed by api/closures.py) are reloaded every run as applied and
given to GraphHopper (in_router): each is a real closed area on ways a route would otherwise use.

Only internal gaps can apply: a corridor that is continuous on the map but not on foot, where the missing link is the
straight line from where the verification route left the corridor to where it came back (the gap's stored geometry
is that detour, on streets that stay open). A gap between two corridors is only the shortest line between them, not a
path that closed; drawn as closures they lay along real paths (the Queensboro Bridge path, Hudson River Park, Brooklyn
Bridge Park), so they are stored with applied = false and that reason. The closure is a strip STRIP_HALF_WIDTH_M
either side of the link, with END_TRIM_M left off each end so the ways a route uses to go around stay open.

An internal gap is applied only when less than ALONG_MAX_M of walkable OSM ways inside its strip run along the link (within 45
degrees of its direction, summed, so a path OSM splits into short pieces still counts; a street crossing the strip
doesn't). Where more does, the link is a real street or path (the shortest line between two corridors often lies along
one), and closing it would close that way: the gap is stored with applied = false and the reason. ALONG_MAX_M is half
the pass-through length, so a doubtful gap is left open rather than closing a real way. Links too short to leave PASS_THROUGH_M of strip
after trimming (no route could pass the rule there) are stored the same way.

Rebuilds the corridor_gap and curated rows of closures each run; confirmed runner reports (kind 'report') are kept.
"""

import json
import sys
from datetime import date

import psycopg

from api.closures import CURATED_FILE, PASS_THROUGH_M, parse_curated
from etl.load import SCHEMA_PATH, database_url

STRIP_HALF_WIDTH_M = 10
END_TRIM_M = 25
ALONG_MAX_M = PASS_THROUGH_M / 2
ALONG_COS = 0.7071  # within 45 degrees of the link
FT = 3.28084

# Ways a runner could be routed on (GraphHopper's foot profile refuses motorways and trunks in NYC). A foot tag overrides
# access, as in GraphHopper: the Queensboro Bridge's outer roadway is access=no, foot=designated.
WALKABLE = """
    w.highway NOT IN ('motorway', 'motorway_link', 'trunk', 'trunk_link', 'construction', 'proposed', 'corridor',
                      'elevator', 'platform', 'bus_stop', 'raceway')
    AND (coalesce(w.tags->>'foot', '') IN ('yes', 'designated', 'permissive')
         OR (coalesce(w.tags->>'foot', 'yes') NOT IN ('no', 'private')
             AND coalesce(w.tags->>'access', 'yes') NOT IN ('no', 'private')))
"""

BUILD = f"""
DELETE FROM closures WHERE kind = 'corridor_gap';
CREATE TEMP TABLE gap_links ON COMMIT DROP AS
WITH g AS (
    SELECT g.id, g.kind, g.gap_m, a.name AS name_a, b.name AS name_b,
           ST_Transform(CASE WHEN g.kind = 'internal' THEN ST_MakeLine(ST_StartPoint(g.geom), ST_EndPoint(g.geom))
                             ELSE g.geom END, 2263) AS link
    FROM corridor_gaps g JOIN corridors a ON a.id = g.corridor_a LEFT JOIN corridors b ON b.id = g.corridor_b
)
SELECT id, kind, gap_m, name_a, name_b, ST_Length(link) / {FT} AS link_m,
       ST_Azimuth(ST_StartPoint(link), ST_EndPoint(link)) AS az,
       CASE WHEN ST_Length(link) > {(2 * END_TRIM_M + PASS_THROUGH_M) * FT} THEN ST_Transform(ST_Buffer(
           ST_LineSubstring(link, {END_TRIM_M * FT} / ST_Length(link), 1 - {END_TRIM_M * FT} / ST_Length(link)),
           {STRIP_HALF_WIDTH_M * FT}, 'endcap=flat'), 4326) END AS strip
FROM g;
CREATE INDEX ON gap_links USING gist (strip);
CREATE TEMP TABLE gap_walkable ON COMMIT DROP AS
WITH seg AS (
    SELECT s.id, p.name, ST_Length(d.geom) AS len,
           abs(cos(ST_Azimuth(ST_StartPoint(d.geom), ST_EndPoint(d.geom)) - s.az)) >= {ALONG_COS} AS along
    FROM gap_links s
    JOIN LATERAL (SELECT coalesce(w.name, w.highway) AS name,
                         ST_CollectionExtract(ST_Transform(ST_Intersection(w.geom, s.strip), 2263), 2) AS g
                  FROM osm_ways w WHERE ST_Intersects(w.geom, s.strip) AND {WALKABLE}) p ON true
    CROSS JOIN LATERAL ST_DumpSegments(p.g) d
    WHERE s.strip IS NOT NULL
)
SELECT s.id, coalesce(sum(seg.len) FILTER (WHERE seg.along), 0) / {FT} AS along_m,
       (array_agg(seg.name ORDER BY seg.len DESC) FILTER (WHERE seg.along))[1] AS along_name
FROM gap_links s LEFT JOIN seg USING (id)
GROUP BY s.id;
INSERT INTO closures (kind, name, reason, source, trust, applied, not_applied_reason, in_router, corridor_gap_id,
                      link_m, walkable_along_m, geom)
SELECT 'corridor_gap',
       CASE WHEN l.kind = 'internal' THEN 'missing link of ' || l.name_a ELSE 'between ' || l.name_a || ' and ' || l.name_b END,
       CASE WHEN l.kind = 'internal' THEN 'no path: the corridor stops for ' || round(l.gap_m) || ' m of walking'
            ELSE 'no path between the two corridors' END,
       'Loop corridor catalog gap #' || l.id || ' (decision 012), from OSM ways and GraphHopper', 'listed',
       l.kind = 'internal' AND l.strip IS NOT NULL AND w.along_m < {ALONG_MAX_M},
       CASE WHEN l.kind = 'between' THEN 'between two corridors: the shortest line between them is not a closed path'
            WHEN l.strip IS NULL THEN 'link under ' || {2 * END_TRIM_M + PASS_THROUGH_M} || ' m: too short to draw after trimming the ends'
            WHEN w.along_m >= {ALONG_MAX_M} THEN round(w.along_m) || ' m of walkable ways run along the link ('
                 || w.along_name || ' and others): closing it would close them' END,
       false, l.id, l.link_m, w.along_m, l.strip
FROM gap_links l JOIN gap_walkable w USING (id);
"""

CURATED = """
INSERT INTO closures (kind, name, reason, source, trust, applied, in_router, curated_id, checked_on, review_by, geom)
VALUES ('curated', %(name)s, %(reason)s, %(source)s, %(trust)s, true, true, %(id)s, %(checked_on)s, %(review_by)s,
        ST_SetSRID(ST_GeomFromGeoJSON(%(geometry)s), 4326))
"""

SUMMARY = """
SELECT g.kind, count(*), count(*) FILTER (WHERE c.applied),
       count(*) FILTER (WHERE NOT c.applied AND c.not_applied_reason LIKE 'link under%%'),
       count(*) FILTER (WHERE NOT c.applied AND c.not_applied_reason LIKE '%%walkable ways run along%%'),
       count(*) FILTER (WHERE NOT c.applied AND c.not_applied_reason LIKE 'between two corridors%%')
FROM closures c JOIN corridor_gaps g ON g.id = c.corridor_gap_id WHERE c.kind = 'corridor_gap' GROUP BY 1 ORDER BY 1
"""


def main() -> int:
    with psycopg.connect(database_url()) as conn:
        if not conn.execute("SELECT to_regclass('corridor_gaps') IS NOT NULL").fetchone()[0]:
            print("corridor_gaps is missing. Run: make corridors", file=sys.stderr)
            return 1
        conn.execute(SCHEMA_PATH.read_text())
        conn.execute(BUILD)
        curated = parse_curated(json.loads(CURATED_FILE.read_text()))
        conn.execute("DELETE FROM closures WHERE kind = 'curated'")
        for c in curated:
            conn.execute(CURATED, {"id": c.id, "name": c.name, "reason": c.reason, "trust": c.trust,
                                   "source": "curated: " + " ; ".join(c.sources)
                                             + (f" ; ground check by {c.ground_check[0]}, {c.ground_check[1]}"
                                                if c.ground_check else ""), "checked_on": c.checked_on,
                                   "review_by": c.review_by, "geometry": json.dumps(c.geometry)})
        rows = conn.execute(SUMMARY).fetchall()
        reports = conn.execute("SELECT count(*) FROM closures WHERE kind = 'report' AND applied").fetchone()[0]
    for kind, n, applied, short, walkable, between in rows:
        print(f"  {kind:8s} gaps {n:3d}: {applied:3d} applied; not applied: {between:3d} between corridors, "
              f"{walkable:3d} walkable ways along the link, {short:3d} link too short")
    print(f"  curated closures applied: {len(curated)}")
    for c in curated:
        if c.review_by < date.today():
            print(f"  REVIEW OVERDUE: curated closure {c.id} was due for review by {c.review_by}", file=sys.stderr)
    print(f"  confirmed runner reports applied: {reports}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
