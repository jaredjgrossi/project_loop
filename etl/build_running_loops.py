"""Build the running_loops table from the curated list and OSM in PostGIS (decision 035).

    uv run python -m etl.build_running_loops      (after etl.load_osm and etl.load_places, with GraphHopper running)

Each loop in etl/curated/running_loops.json gets its ring, oriented in the direction runners go:
- `osm_way`: one closed OSM way (the Reservoir track).
- `drive_ring`: the outer ring of the named drives inside a park. OSM splits the drives into many pieces with small
  gaps at junctions, so dangling ends within GAP_JOIN_M (or the loop's `gap_m`) of another drive are joined first; the ring is the outside of
  the faces the drives enclose, which leaves out the cross drives.
Then GraphHopper runs a lap through points on the ring (`api.via.lap_points`), and the loop is kept only if the lap
stays on the ring (VERIFIED_SHARE) and the ring is within LENGTH_CHECK_PCT of the published length. A loop with no
geometry (the McCarren track: OSM has it only as an area) is listed with a null ring, so Loop can say why.

Writes running_loops, rebuilt from scratch each run; derived from OSM and the curated list only.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import psycopg

from api.geometry import oriented
from api.units import meters_to_miles

CURATED = Path(__file__).parent / "curated" / "running_loops.json"
GAP_JOIN_M = 45.0
VERIFIED_SHARE = 0.9
LENGTH_CHECK_PCT = 8.0
FT_PER_M = 3.28084

DDL = """
DROP TABLE IF EXISTS running_loops;
CREATE TABLE running_loops (
    id text PRIMARY KEY,
    name text NOT NULL,
    published_mi double precision NOT NULL,
    source text NOT NULL,
    direction text NOT NULL,
    measured_m double precision,
    lap_share double precision,
    why_no_geometry text,
    geom geometry(LineString, 4326),
    loaded_at timestamptz NOT NULL DEFAULT now()
);
"""


def curated() -> list[dict]:
    return json.loads(CURATED.read_text())["loops"]


def drive_ring(lines, gap: float):
    """The outer ring of the faces a set of (projected) lines encloses, after joining dangling ends that come within
    `gap` of another line. None when they enclose nothing."""
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points, polygonize, unary_union

    noded = unary_union(lines)
    segs = list(getattr(noded, "geoms", [noded]))
    ends, where = Counter(), {}
    for s in segs:
        for xy in (s.coords[0], s.coords[-1]):
            key = tuple(round(v, 1) for v in xy)
            ends[key] += 1
            where[key] = (xy, s)
    joins = []
    for key, n in ends.items():
        if n != 1:
            continue
        xy, own = where[key]
        d = Point(xy)
        others = [s for s in segs if s is not own and s.distance(d) > 1e-6]
        if not others:
            continue
        best = min(others, key=lambda s: s.distance(d))
        if best.distance(d) <= gap:
            joins.append(LineString([d, nearest_points(d, best)[1]]))
    faces = list(polygonize(unary_union(segs + joins)))
    if not faces:
        return None
    whole = unary_union(faces)
    biggest = max(getattr(whole, "geoms", [whole]), key=lambda g: g.area)
    return biggest.exterior


def _ring_from_osm(conn, loop: dict) -> list | None:
    from pyproj import Transformer
    from shapely.geometry import shape

    g = loop["geometry"]
    if g["from"] == "osm_way":
        row = conn.execute("SELECT ST_AsGeoJSON(geom) FROM osm_ways WHERE way_id = %s AND ST_IsClosed(geom)",
                           (g["way_id"],)).fetchone()
        return json.loads(row[0])["coordinates"] if row else None
    rows = conn.execute(
        """WITH p AS (SELECT outline FROM places WHERE name = %(place)s AND kind = 'park'
                      ORDER BY area_ha DESC NULLS LAST LIMIT 1)  -- the big one, not a playground of the same name
           SELECT ST_AsGeoJSON(ST_Transform(w.geom, 2263)) FROM osm_ways w, p
           WHERE ST_Intersects(w.geom, ST_Buffer(p.outline::geography, 30)::geometry)
             AND w.name = ANY(%(ways)s) AND w.highway = ANY(%(highways)s)""",
        {"place": g["place"], "ways": g["ways"], "highways": g["highways"]}).fetchall()
    ring = drive_ring([shape(json.loads(r[0])) for r in rows], g.get("gap_m", GAP_JOIN_M) * FT_PER_M)
    if ring is None:
        return None
    back = Transformer.from_crs(2263, 4326, always_xy=True)
    return [[round(lon, 7), round(lat, 7)] for lon, lat in (back.transform(x, y) for x, y in ring.coords)]


def _verify(coords: list) -> float:
    """The share of the ring a GraphHopper lap through points on it covers."""
    from api.geometry import covered_share
    from api.routing import request_route
    from api.via import lap_points

    start = (coords[0][1], coords[0][0])
    route = request_route(lap_points(coords, start))
    return covered_share(route.coordinates, {"type": "LineString", "coordinates": coords}, 30.0)


def main() -> int:
    from api.geometry import line_length_m
    from etl.load import database_url

    problems = []
    with psycopg.connect(database_url()) as conn:
        conn.execute(DDL)
        for loop in curated():
            row = {k: loop[k] for k in ("id", "name", "published_mi", "source", "direction")}
            row |= {"measured_m": None, "lap_share": None, "geom": None,
                    "why_no_geometry": loop.get("why_no_geometry")}
            if loop["geometry"] is not None:
                coords = _ring_from_osm(conn, loop)
                if coords is None:
                    problems.append(f"{loop['id']}: no ring in OSM")
                    continue
                coords = oriented(coords, loop["direction"])
                measured = line_length_m(coords)
                off = 100 * (meters_to_miles(measured) - loop["published_mi"]) / loop["published_mi"]
                share = _verify(coords)
                print(f"{loop['id']}: {meters_to_miles(measured):.2f} mi measured, {loop['published_mi']} mi "
                      f"published ({off:+.1f}%), a routed lap covers {share:.0%}")
                if abs(off) > LENGTH_CHECK_PCT or share < VERIFIED_SHARE:
                    problems.append(f"{loop['id']}: {off:+.1f}% off the published length, lap covers {share:.0%}")
                    continue
                row |= {"measured_m": round(measured, 1), "lap_share": round(share, 3),
                        "geom": json.dumps({"type": "LineString", "coordinates": coords})}
            else:
                print(f"{loop['id']}: no geometry ({loop['why_no_geometry']})")
            conn.execute(
                """INSERT INTO running_loops (id, name, published_mi, source, direction, measured_m, lap_share,
                                              why_no_geometry, geom)
                   VALUES (%(id)s, %(name)s, %(published_mi)s, %(source)s, %(direction)s, %(measured_m)s,
                           %(lap_share)s, %(why_no_geometry)s, ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))""",
                row)
    for p in problems:
        print("FAILED", p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
