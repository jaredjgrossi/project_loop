"""Load the sources of scheduled crowd pulses on paths (decision 022):  python -m etl.load_pulses  (make pulses)

Public downloads in data/pulses/raw/ (git-ignored):
- schools/extracted/SchoolPoints_APS_2024_08_28.* : DOE School Point Locations (NYC Open Data jfju-ynrr, file dated
  2024-08-28), unzipped
- nycferry/extracted/*.txt : NYC Ferry's static GTFS (http://nycferry.connexionz.net/rtt/public/resource/gtfs.zip)
Plus OSM schools from routing/data/nyc.osm.pbf (osmium), and SeaStreak's East 35th St landing from
etl/curated/seastreak_schedule.json.

Writes pulse_sources (schools and ferry landings), pulse_ways (path ways within PULSE_RADIUS_M of a source),
ferry_services, ferry_service_dates and ferry_arrivals. Rebuilt from scratch each run.
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path

import psycopg

from api.pulses import PULSE_RADIUS_M, SEASTREAK_FILE, gtfs_time
from etl.load import database_url
from etl.load_osm import NYC_PBF, export_ways

RAW = Path(__file__).resolve().parents[1] / "data" / "pulses" / "raw"
SCHOOLS_SHP = RAW / "schools" / "extracted" / "SchoolPoints_APS_2024_08_28.shp"
GTFS = RAW / "nycferry" / "extracted"
DOE_SOURCE = "NYC DOE School Point Locations (NYC Open Data jfju-ynrr, file dated 2024-08-28)"
OSM_SAME_SCHOOL_M = 75  # an OSM school this close to a DOE point is that school
OSM_DUPLICATE_M = 60  # OSM often maps one school as a node and an area
PATH_HIGHWAYS = ("footway", "path", "cycleway", "pedestrian", "steps", "track", "bridleway")

SCHEMA = """
DROP TABLE IF EXISTS pulse_ways, pulse_sources, ferry_arrivals, ferry_services, ferry_service_dates;
CREATE TABLE pulse_sources (
    id            serial PRIMARY KEY,
    kind          text NOT NULL CHECK (kind IN ('school', 'ferry')),
    name          text NOT NULL,
    operator      text,             -- DOE | OSM | NYC Ferry | SeaStreak
    gtfs_stop_id  text,
    source        text NOT NULL,
    trust         text NOT NULL CHECK (trust IN ('verified', 'listed', 'seasonal_or_closed')),
    geom          geometry(Point, 4326) NOT NULL
);
CREATE INDEX ON pulse_sources USING gist (geom);
CREATE TABLE pulse_ways (source_id integer REFERENCES pulse_sources(id), way_id bigint, dist_m double precision,
                         PRIMARY KEY (source_id, way_id));
CREATE INDEX ON pulse_ways (way_id);
CREATE TABLE ferry_services (service_id text PRIMARY KEY, days smallint[] NOT NULL, start_date date, end_date date);
CREATE TABLE ferry_service_dates (service_id text, day date, kind smallint, PRIMARY KEY (service_id, day));
CREATE TABLE ferry_arrivals (stop_id text, service_id text, arrival time, route text);
CREATE INDEX ON ferry_arrivals (stop_id);
"""

# Only catalog corridor ways and waterfront paths: the paths decision 016 leaves not_scored that runners use as routes.
# Any non-sidewalk footway would take in schoolyards, plazas and park paths (1,310 of 1,950 DOE schools).
CATALOG_PATH_WAYS = """
CREATE TEMP TABLE catalog_path_ways AS
SELECT w.way_id, w.geom FROM osm_ways w JOIN waterfront_paths p USING (way_id)
UNION
SELECT w.way_id, w.geom FROM osm_ways w JOIN corridors c ON w.geom && c.geom
WHERE w.highway = ANY(%s) AND coalesce(w.tags->>'footway', '') NOT IN ('sidewalk', 'crossing')
  AND ST_CoveredBy(w.geom, ST_Buffer(c.geom::geography, 2)::geometry)
"""
# A source pulses a path only when no street lies between them: a school on the running path itself (UNIS at
# Waterside Plaza), not one across the FDR Drive or East End Avenue, whose students never enter the path (the
# reviewer, 2026-11-03; Bobby Wagner Walk was 82% "busy" at 8am without this). Tested on the straight line from the
# source to the nearest point of the way; service roads don't count, since they run inside campuses and parks.
BARRIER_HIGHWAYS = ("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
                    "secondary_link", "tertiary", "tertiary_link", "residential", "unclassified", "living_street")
PULSE_WAYS_INSERT = f"""
INSERT INTO pulse_ways (source_id, way_id, dist_m)
SELECT s.id, w.way_id, ST_Distance(w.geom::geography, s.geom::geography)
FROM pulse_sources s JOIN catalog_path_ways w ON ST_DWithin(w.geom::geography, s.geom::geography, {PULSE_RADIUS_M})
WHERE NOT EXISTS (
    SELECT 1 FROM osm_ways m
    WHERE m.highway = ANY(%s) AND m.geom && ST_ShortestLine(s.geom, w.geom)
      AND ST_Intersects(m.geom, ST_ShortestLine(s.geom, w.geom)))
"""


def doe_schools() -> list[tuple]:
    import shapefile  # pyshp; the ETL's only use of it

    r = shapefile.Reader(str(SCHOOLS_SHP))
    names = [f[0] for f in r.fields[1:]]
    return [(rec["Name"], rec["ATS"], rec["Longitude"], rec["Latitude"])
            for rec in (dict(zip(names, x)) for x in r.records()) if rec["Latitude"] and rec["Longitude"]]


def osm_schools() -> list[tuple]:
    out = []
    # split on newlines only: str.splitlines() also splits on the record separator (\x1e) that starts each line
    for line in export_ways(NYC_PBF, "nwr/amenity=school", "osm_schools", "point,polygon").read_text().split("\n"):
        if not (line := line.strip("\x1e \r")):
            continue
        f = json.loads(line)
        if f["properties"].get("amenity") == "school":
            out.append((f["properties"].get("name") or "school (unnamed in OSM)", f["id"], json.dumps(f["geometry"])))
    return out


def load_gtfs(conn) -> int:
    rows = lambda name: list(csv.DictReader(open(GTFS / name, encoding="utf-8-sig")))
    day = lambda s: date(int(s[:4]), int(s[4:6]), int(s[6:]))
    for r in rows("calendar.txt"):
        days = [int(r[d]) for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")]
        conn.execute("INSERT INTO ferry_services VALUES (%s, %s, %s, %s)",
                     (r["service_id"], days, day(r["start_date"]), day(r["end_date"])))
    for r in rows("calendar_dates.txt"):
        conn.execute("INSERT INTO ferry_service_dates VALUES (%s, %s, %s)",
                     (r["service_id"], day(r["date"]), int(r["exception_type"])))
    for r in rows("stops.txt"):
        conn.execute("""INSERT INTO pulse_sources (kind, name, operator, gtfs_stop_id, source, trust, geom)
                        VALUES ('ferry', %s, 'NYC Ferry', %s, 'NYC Ferry GTFS', 'listed',
                                ST_SetSRID(ST_MakePoint(%s, %s), 4326))""",
                     (r["stop_name"], r["stop_id"], float(r["stop_lon"]), float(r["stop_lat"])))
    trips = {t["trip_id"]: t for t in rows("trips.txt")}
    routes = {r["route_id"]: r["route_short_name"] or r["route_long_name"] for r in rows("routes.txt")}
    by_trip: dict[str, list[dict]] = {}
    for st in rows("stop_times.txt"):
        by_trip.setdefault(st["trip_id"], []).append(st)
    n = 0
    with conn.cursor().copy("COPY ferry_arrivals (stop_id, service_id, arrival, route) FROM STDIN") as cp:
        for trip_id, stops in by_trip.items():
            stops.sort(key=lambda s: int(s["stop_sequence"]))
            t = trips[trip_id]
            for st in stops[1:]:  # nobody gets off at a trip's first stop
                if st.get("drop_off_type", "0") in ("", "0") and (at := gtfs_time(st["arrival_time"])):
                    cp.write_row((st["stop_id"], t["service_id"], at, routes.get(t["route_id"], "")))
                    n += 1
    return n


def main() -> int:
    for need in (SCHOOLS_SHP, GTFS / "stop_times.txt"):
        if not need.exists():
            print(f"Missing {need}. Decision 022 says where each download comes from.", file=sys.stderr)
            return 1
    sea = json.loads(SEASTREAK_FILE.read_text())
    with psycopg.connect(database_url()) as conn:
        conn.execute(SCHEMA)
        with conn.cursor().copy("COPY pulse_sources (kind, name, operator, source, trust, geom) FROM STDIN") as cp:
            for name, ats, lon, lat in doe_schools():
                cp.write_row(("school", name, "DOE", f"{DOE_SOURCE}, {ats}", "listed", f"SRID=4326;POINT({lon} {lat})"))
        conn.execute("CREATE TEMP TABLE osm_school (name text, osm_id text, geom geometry(Point, 4326))")
        for name, osm_id, geojson in osm_schools():
            conn.execute("""INSERT INTO osm_school
                            SELECT %s, %s, ST_PointOnSurface(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)))""",
                         (name, osm_id, geojson))
        conn.execute(f"""
            INSERT INTO pulse_sources (kind, name, operator, source, trust, geom)
            SELECT DISTINCT ON (name, cluster) 'school', name, 'OSM',
                   'OpenStreetMap amenity=school, ' || osm_id || ' (not in the DOE list; DOE calendar assumed)',
                   'listed', geom
            FROM (SELECT o.*, ST_ClusterDBSCAN(ST_Transform(o.geom, 2263), {OSM_DUPLICATE_M * 3.28084}, 1)
                              OVER (PARTITION BY o.name) AS cluster
                  FROM osm_school o
                  WHERE NOT EXISTS (SELECT 1 FROM pulse_sources d WHERE d.operator = 'DOE'
                                    AND ST_DWithin(d.geom::geography, o.geom::geography, {OSM_SAME_SCHOOL_M}))) x
            ORDER BY name, cluster, osm_id""")
        arrivals = load_gtfs(conn)
        lon, lat = sea["landing_lonlat"]
        conn.execute("""INSERT INTO pulse_sources (kind, name, operator, source, trust, geom)
                        VALUES ('ferry', %s, 'SeaStreak', %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))""",
                     (sea["landing"], "SeaStreak timetable, " + sea["sources"]["weekday"], sea["trust"], lon, lat))
        conn.execute(CATALOG_PATH_WAYS, (list(PATH_HIGHWAYS),))
        conn.execute("CREATE INDEX ON catalog_path_ways USING gist (geom)")
        conn.execute(PULSE_WAYS_INSERT, (list(BARRIER_HIGHWAYS),))
        summary = conn.execute("""
            SELECT s.kind, s.operator, count(DISTINCT s.id), count(DISTINCT s.id) FILTER (WHERE w.way_id IS NOT NULL),
                   count(DISTINCT w.way_id)
            FROM pulse_sources s LEFT JOIN pulse_ways w ON w.source_id = s.id GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()
    for kind, operator, n, near, ways in summary:
        print(f"  {kind:6s} {operator:9s} {n:5d} sources, {near:4d} within {PULSE_RADIUS_M} m of a catalog or waterfront path, {ways:5d} path ways")
    print(f"  NYC Ferry arrivals with drop-off: {arrivals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
