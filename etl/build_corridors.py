"""Build the corridor catalog from OSM in PostGIS and verify each corridor with GraphHopper (decision 012).

    uv run python -m etl.build_corridors      (after etl.load_osm, with GraphHopper running)

A corridor is a connected stretch of path-like ways a runner can stay on: waterfront paths (within WATERFRONT_M of
the OSM coastline), named greenways, esplanades and promenades, and car-free park drives. Ways are grouped with
DBSCAN (ways within CLUSTER_M of each other belong together) and kept when the group is at least MIN_LENGTH_M long.

Verification: GraphHopper routes between the two points of each corridor that are farthest apart, with a per-request
custom model that makes leaving the corridor OFF_CORRIDOR_PRIORITY times as costly (a plain shortest path cuts across
streets even where the corridor is continuous). If less than VERIFIED_SHARE of that route stays on the corridor, the
corridor is not continuous on foot, and the stretches where the route leaves it are recorded as internal gaps. Gaps between neighboring corridors (closer than GAP_MAX_M but
not connected) are recorded too; the East River path is the known example.

Also stores waterfront_paths: every path-like way within WATERFRONT_M of the coastline, which the generator's
waterfront anchors read (decision 014; computing it per request took about 0.8 s).

Writes the tables corridors and corridor_gaps (rebuilt from scratch each run; derived from OSM only, never from a
runner's own routes).
"""

import json
import sys

import httpx
import psycopg

from api.routing import RoutingError, request_route
from etl.corridor_names import choose_name
from etl.load import database_url

WATERFRONT_M = 60
CLUSTER_M = 20
MIN_LENGTH_M = 800
VERIFY_NEAR_M = 25
VERIFIED_SHARE = 0.8
GAP_MIN_M = 50
GAP_MAX_M = 1000
OFF_CORRIDOR_PRIORITY = 0.05
AREA_BUFFER_M = 30
FT = 3.28084

SCHEMA = """
DROP TABLE IF EXISTS corridor_gaps;
DROP TABLE IF EXISTS corridors;
CREATE TABLE corridors (
    id               serial PRIMARY KEY,
    name             text NOT NULL,          -- see etl/corridor_names.py; becomes the UI stretch name
    name_source      text NOT NULL,          -- way | park | none
    cluster_key      text NOT NULL,
    kind             text NOT NULL,          -- waterfront | greenway | park_drive
    length_m         double precision NOT NULL,
    ways             integer NOT NULL,
    verified         boolean,                -- NULL until routed; true when the end-to-end route stays on it
    on_corridor_pct  double precision,
    routed_m         double precision,
    span_m           double precision,       -- straight line between the two farthest points
    source           text NOT NULL,
    built_at         timestamptz NOT NULL DEFAULT now(),
    geom             geometry(MultiLineString, 4326) NOT NULL
);
CREATE INDEX corridors_geom_idx ON corridors USING gist (geom);
CREATE TABLE corridor_gaps (
    id          serial PRIMARY KEY,
    kind        text NOT NULL,                -- internal (route leaves the corridor) | between (two corridors don't meet)
    corridor_a  integer NOT NULL REFERENCES corridors(id),
    corridor_b  integer REFERENCES corridors(id),
    gap_m       double precision NOT NULL,
    geom        geometry(Geometry, 4326) NOT NULL
);
"""

CANDIDATES = f"""
CREATE TEMP TABLE corridor_ways AS
WITH ways AS (
    SELECT w.way_id, w.name, w.highway, w.geom FROM osm_ways w
    WHERE w.highway IN ('footway', 'path', 'cycleway', 'pedestrian', 'track', 'bridleway', 'service')
      AND coalesce(w.tags->>'footway', '') NOT IN ('sidewalk', 'crossing', 'traffic_island', 'access_aisle')
      AND coalesce(w.tags->>'foot', 'yes') NOT IN ('no', 'private')
      AND coalesce(w.tags->>'access', 'yes') NOT IN ('no', 'private')
)
SELECT w.way_id, w.name, w.geom, ST_Transform(w.geom, 2263) AS g,
       EXISTS (SELECT 1 FROM osm_coastline c WHERE c.geom && ST_Expand(w.geom, 0.001)
               AND ST_DWithin(ST_Transform(c.geom, 2263), ST_Transform(w.geom, 2263), {WATERFRONT_M * FT})) AS near_coast,
       CASE
         WHEN w.name ~* ' drive$' AND w.highway <> 'service' AND EXISTS (
              SELECT 1 FROM osm_parks p WHERE p.geom && w.geom AND ST_Within(w.geom, p.geom)) THEN 'park_drive'
         WHEN w.name ~* '(greenway|esplanade|promenade|boardwalk)' THEN 'greenway'
         ELSE 'waterfront'
       END AS kind
FROM ways w
WHERE (w.highway <> 'service' AND w.name ~* '(greenway|esplanade|promenade|boardwalk)')
   OR (w.highway <> 'service' AND w.name ~* ' drive$' AND EXISTS (
          SELECT 1 FROM osm_parks p WHERE p.geom && w.geom AND ST_Within(w.geom, p.geom)))
   OR (w.highway <> 'service' AND EXISTS (
          SELECT 1 FROM osm_coastline c
          WHERE c.geom && ST_Expand(w.geom, 0.001)
            AND ST_DWithin(ST_Transform(c.geom, 2263), ST_Transform(w.geom, 2263), {WATERFRONT_M * FT})));
CREATE INDEX ON corridor_ways USING gist (g);
DROP TABLE IF EXISTS waterfront_paths;
CREATE TABLE waterfront_paths AS SELECT way_id, geom FROM corridor_ways WHERE near_coast;
CREATE INDEX waterfront_paths_geom_idx ON waterfront_paths USING gist (geom);
"""

CLUSTERS = f"""
-- Clustered per kind, so a waterfront path, a bridge promenade and a park drive don't chain into one network.
CREATE TEMP TABLE clustered AS
SELECT *, kind || ':' || ST_ClusterDBSCAN(g, eps := {CLUSTER_M * FT}, minpoints := 1) OVER (PARTITION BY kind) AS cid
FROM corridor_ways;
WITH kinds AS (
    SELECT cid, kind, row_number() OVER (PARTITION BY cid ORDER BY sum(ST_Length(g)) DESC) AS rn
    FROM clustered GROUP BY cid, kind
)
INSERT INTO corridors (name, name_source, cluster_key, kind, length_m, ways, source, geom)
SELECT 'pending', 'none', c.cid, k.kind, sum(ST_Length(c.g)) / {FT}, count(*),
       'osm:geofabrik-new-york ways (decisions 012, 014)', ST_Multi(ST_Collect(c.geom))
FROM clustered c JOIN kinds k ON k.cid = c.cid AND k.rn = 1
GROUP BY c.cid, k.kind
HAVING sum(ST_Length(c.g)) / {FT} >= {MIN_LENGTH_M}
"""

WAY_NAMES = f"""
SELECT name, sum(ST_Length(g)) / {FT} FROM clustered WHERE cid = %s AND name IS NOT NULL GROUP BY name
"""

PARK_SHARES = f"""
SELECT p.name, ST_Length(ST_Intersection(ST_Transform(c.geom, 2263), ST_Transform(p.geom, 2263))) / {FT}
FROM corridors c JOIN osm_parks p ON p.geom && c.geom AND ST_Intersects(p.geom, c.geom)
WHERE c.id = %s AND p.name IS NOT NULL
"""

ENDS = """
SELECT id, ST_Y(ST_StartPoint(l)), ST_X(ST_StartPoint(l)), ST_Y(ST_EndPoint(l)), ST_X(ST_EndPoint(l)),
       ST_Length(l::geography)
FROM (SELECT id, ST_LongestLine(geom, geom) AS l FROM corridors) x
"""

AREA = f"""
SELECT ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(ST_Buffer(ST_Transform(geom, 2263), {AREA_BUFFER_M * FT}), 15), 4326), 6)
FROM corridors WHERE id = %s
"""

ON_CORRIDOR = f"""
WITH r AS (SELECT ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%(route)s), 4326), 2263) AS g),
c AS (SELECT ST_Buffer(ST_Transform(geom, 2263), {VERIFY_NEAR_M * FT}) AS b FROM corridors WHERE id = %(id)s)
SELECT ST_Length(ST_Intersection(r.g, c.b)) / nullif(ST_Length(r.g), 0),
       ST_AsGeoJSON(ST_Transform(ST_Difference(r.g, c.b), 4326))
FROM r, c
"""

INTERNAL_GAPS = f"""
INSERT INTO corridor_gaps (kind, corridor_a, gap_m, geom)
SELECT 'internal', %(id)s, ST_Length(d.geom::geography), d.geom
FROM (SELECT (ST_Dump(ST_SetSRID(ST_GeomFromGeoJSON(%(off)s), 4326))).geom) d
WHERE ST_Length(d.geom::geography) >= {GAP_MIN_M}
"""

BETWEEN_GAPS = f"""
INSERT INTO corridor_gaps (kind, corridor_a, corridor_b, gap_m, geom)
SELECT DISTINCT ON (a.id) 'between', a.id, b.id, ST_Distance(a.geom::geography, b.geom::geography),
       ST_ShortestLine(a.geom, b.geom)
FROM corridors a JOIN corridors b ON a.id < b.id AND a.kind IN ('waterfront', 'greenway') AND b.kind IN ('waterfront', 'greenway')
 AND ST_DWithin(a.geom::geography, b.geom::geography, {GAP_MAX_M})
 AND NOT ST_DWithin(a.geom::geography, b.geom::geography, {GAP_MIN_M})  -- touching corridors of two kinds aren't a gap
ORDER BY a.id, ST_Distance(a.geom::geography, b.geom::geography)
"""


def main() -> int:
    with psycopg.connect(database_url(), autocommit=True) as conn:
        for table in ("osm_ways", "osm_coastline", "osm_parks"):
            if not conn.execute(f"SELECT EXISTS (SELECT 1 FROM {table})").fetchone()[0]:
                print(f"{table} is empty. Run: uv run python -m etl.load_osm", file=sys.stderr)
                return 1
        print("Selecting corridor ways ...")
        conn.execute(SCHEMA)
        conn.execute(CANDIDATES)
        print("Grouping them into corridors ...")
        conn.execute(CLUSTERS)
        for cid, key, kind, length in conn.execute("SELECT id, cluster_key, kind, length_m FROM corridors").fetchall():
            name, source = choose_name(conn.execute(WAY_NAMES, (key,)).fetchall(),
                                       conn.execute(PARK_SHARES, (cid,)).fetchall(), kind, length)
            conn.execute("UPDATE corridors SET name = %s, name_source = %s WHERE id = %s", (name, source, cid))
        ends = conn.execute(ENDS).fetchall()
        print(f"Verifying {len(ends)} corridors with GraphHopper ...")
        failed = 0
        with httpx.Client(timeout=60) as client:
            for cid, lat1, lon1, lat2, lon2, span in ends:
                (area,) = conn.execute(AREA, (cid,)).fetchone()
                stay_on = {
                    "priority": [{"if": "!in_corridor", "multiply_by": str(OFF_CORRIDOR_PRIORITY)}],
                    "areas": {"type": "FeatureCollection", "features": [
                        {"type": "Feature", "id": "corridor", "properties": {}, "geometry": json.loads(area)}]},
                }
                try:
                    route = request_route([(lat1, lon1), (lat2, lon2)], client=client, custom_model=stay_on)
                except RoutingError:
                    failed += 1
                    conn.execute("UPDATE corridors SET verified = false, span_m = %s WHERE id = %s", (span, cid))
                    continue
                line = json.dumps({"type": "LineString", "coordinates": route.coordinates})
                share, off = conn.execute(ON_CORRIDOR, {"route": line, "id": cid}).fetchone()
                share = share or 0.0
                conn.execute(
                    "UPDATE corridors SET verified = %s, on_corridor_pct = %s, routed_m = %s, span_m = %s WHERE id = %s",
                    (share >= VERIFIED_SHARE, 100 * share, route.distance_m, span, cid),
                )
                if share < VERIFIED_SHARE and off:
                    conn.execute(INTERNAL_GAPS, {"id": cid, "off": off})
        conn.execute(BETWEEN_GAPS)
        summary = conn.execute(
            "SELECT kind, count(*), count(*) FILTER (WHERE verified), round(sum(length_m) / 1000) FROM corridors GROUP BY 1 ORDER BY 1"
        ).fetchall()
        gaps = conn.execute("SELECT kind, count(*), round(avg(gap_m)) FROM corridor_gaps GROUP BY 1").fetchall()
        longest = conn.execute(
            "SELECT name, kind, round(length_m), verified, round(on_corridor_pct) FROM corridors ORDER BY length_m DESC LIMIT 12"
        ).fetchall()
        sources = conn.execute("SELECT name_source, count(*) FROM corridors GROUP BY 1 ORDER BY 1").fetchall()
    for kind, n, ok, km in summary:
        print(f"  {kind:11s} {n:4d} corridors, {ok:4d} verified continuous, {km:5.0f} km of ways")
    for kind, n, avg in gaps:
        print(f"  gaps {kind:8s} {n:4d} (mean {avg:.0f} m)")
    if failed:
        print(f"  {failed} corridors could not be routed end to end (marked not verified)")
    print("  names from: " + ", ".join(f"{s} {n}" for s, n in sources))
    print("Longest:")
    for name, kind, length, ok, pct in longest:
        print(f"  {length:7.0f} m  {kind:11s} {'verified' if ok else 'GAPS    '} {pct or 0:3.0f}% on corridor  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
