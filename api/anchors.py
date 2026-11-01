"""Anchors: points on parks, waterfront paths and corridors that candidate routes go out to (decision 012).

A route built from an anchor set goes from the start to the set's entry (its nearest point), on to a turnaround
point picked to fit the distance, and back: either the same way (an out-and-back) or by whatever way is shortest (a
loop or lollipop). These sets come from OSM in PostGIS for every runner: OSM park areas (osm_parks, which include
Hudson River Park), path-like ways along the OSM coastline, and the corridor catalog (etl/build_corridors.py). The
runner's own routes are a separate, optional source (api/scripts/make_loop.familiar_anchors) and never feed these.
"""

import json
from dataclasses import dataclass

SECTOR_DEG = 45
MIN_TURN_FRACTION = 0.2  # a turnaround nearer than this share of the radius can't make the distance
REACH_FRACTION = 0.8  # a feature farther than this share of the radius is outside the budget
MAX_PARKS = 3
MAX_CORRIDORS = 3
MIN_PARK_M2 = 20_000  # 2 hectares: big enough to run in, not a triangle or a garden
SAMPLE_M = 150  # spacing of candidate turnaround points along ways


@dataclass(frozen=True)
class Anchors:
    entry: tuple[float, float] | None  # nearest point: out-and-backs go out and back through it
    directions: list[list[tuple[float, float, float]]]  # per direction, (lat, lon, meters from start), nearest first
    source: str = "familiar"  # familiar | park | water | corridor
    name: str | None = None
    area: dict | None = None  # GeoJSON polygon of the feature: routes to it are routed to prefer staying inside it


def group_into_directions(rows, radius_m: float, source: str = "familiar", name: str | None = None,
                          area: dict | None = None) -> Anchors:
    """rows: (lat, lon, meters from start, weight, bearing from start). The nearest point is the entry; the rest are
    grouped into SECTOR_DEG-wide directions, the directions with the most weight first, points nearest first."""
    if not rows:
        return Anchors(entry=None, directions=[], source=source, name=name, area=area)
    nearest = min(rows, key=lambda r: r[2])
    sectors: dict[int, list] = {}
    for lat, lon, dist, weight, bearing in rows:
        if dist >= MIN_TURN_FRACTION * radius_m:
            sectors.setdefault(int((bearing % 360) // SECTOR_DEG), []).append((lat, lon, dist, weight))
    busiest = sorted(sectors.values(), key=lambda pts: -sum(p[3] for p in pts))
    return Anchors(
        entry=(nearest[0], nearest[1]),
        directions=[sorted((p[:3] for p in pts), key=lambda p: p[2]) for pts in busiest],
        source=source, name=name, area=area,
    )


# --- PostGIS ----------------------------------------------------------------------------

_HERE = "ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography"
_PATHLIKE = """
    w.highway IN ('footway', 'path', 'cycleway', 'pedestrian', 'track', 'bridleway')
    AND coalesce(w.tags->>'footway', '') NOT IN ('sidewalk', 'crossing', 'traffic_island', 'access_aisle')
    AND coalesce(w.tags->>'foot', 'yes') NOT IN ('no', 'private')
    AND coalesce(w.tags->>'access', 'yes') NOT IN ('no', 'private')
"""
# Points every SAMPLE_M along a way (its midpoint if shorter), with distance and bearing from the start.
_POINTS = f"""
SELECT ST_Y(p), ST_X(p), ST_Distance(p::geography, {_HERE}), 1.0, degrees(ST_Azimuth({_HERE}, p::geography))
FROM (
    SELECT (ST_Dump(ST_LineInterpolatePoints(g, LEAST(0.5, {SAMPLE_M} / GREATEST(ST_Length(g::geography), 1)), true))).geom AS p
    FROM ({{lines}}) AS lines(g)
) pts
WHERE ST_DWithin(p::geography, {_HERE}, %(far)s)
"""


AREA_BUFFER_M = 30  # line features (paths, corridors) become an area this wide on each side
AREA_SIMPLIFY_DEG = 0.0001  # ~10 m: keeps the GraphHopper request small


def _points(conn, lines_sql: str, params: dict) -> list:
    return conn.execute(_POINTS.format(lines=lines_sql), params).fetchall()


def _area(conn, geom_sql: str, params: dict, buffer_m: float = AREA_BUFFER_M) -> dict | None:
    """The feature as one simplified GeoJSON (multi)polygon; line features are buffered by buffer_m."""
    (g,) = conn.execute(
        f"""SELECT ST_AsGeoJSON(ST_CollectionExtract(ST_SimplifyPreserveTopology(
                   CASE WHEN ST_Dimension(g) = 2 THEN g ELSE ST_Buffer(g::geography, {buffer_m})::geometry END,
                   {AREA_SIMPLIFY_DEG}), 3), 6)  -- polygons only: GraphHopper areas can't be collections
            FROM (SELECT ST_Collect(geom) AS g FROM ({geom_sql}) AS f(geom)) x""",
        params,
    ).fetchone()
    return json.loads(g) if g else None


def park_anchors(conn, lat: float, lon: float, radius_m: float) -> list[Anchors]:
    """For the nearest OSM parks of at least MIN_PARK_M2 within reach: points on the paths inside each park."""
    params = {"lat": lat, "lon": lon, "far": 1.5 * radius_m, "reach": REACH_FRACTION * radius_m}
    parks = conn.execute(
        f"""SELECT area_id, coalesce(name, 'unnamed park') FROM osm_parks
            WHERE ST_DWithin(geom::geography, {_HERE}, %(reach)s) AND ST_Area(geom::geography) >= {MIN_PARK_M2}
            ORDER BY ST_Distance(geom::geography, {_HERE}) LIMIT {MAX_PARKS}""",
        params,
    ).fetchall()
    out = []
    for area_id, name in parks:
        lines = f"""SELECT w.geom FROM osm_ways w, osm_parks p WHERE p.area_id = {int(area_id)}
                    AND w.geom && p.geom AND ST_Intersects(w.geom, p.geom) AND {_PATHLIKE}"""
        rows = _points(conn, lines, params)
        if rows:
            area = _area(conn, f"SELECT geom FROM osm_parks WHERE area_id = {int(area_id)}", params)
            out.append(group_into_directions(rows, radius_m, source="park", name=name, area=area))
    return out


def water_anchors(conn, lat: float, lon: float, radius_m: float, within_m: float = 60) -> list[Anchors]:
    """Points on path-like ways within `within_m` of the OSM coastline (the same 60 m as the waterfront share)."""
    params = {"lat": lat, "lon": lon, "far": 1.5 * radius_m, "reach": REACH_FRACTION * radius_m}
    lines = f"""SELECT w.geom FROM osm_ways w
                WHERE ST_DWithin(w.geom::geography, {_HERE}, %(far)s) AND {_PATHLIKE}
                  AND EXISTS (SELECT 1 FROM osm_coastline c WHERE c.geom && ST_Expand(w.geom, 0.001)
                              AND ST_DWithin(c.geom::geography, w.geom::geography, {within_m}))"""
    rows = _points(conn, lines, params)
    if not rows or min(r[2] for r in rows) > params["reach"]:
        return []
    return [group_into_directions(rows, radius_m, source="water", name="waterfront", area=_area(conn, lines, params))]


def corridor_anchors(conn, lat: float, lon: float, radius_m: float) -> list[Anchors]:
    """For the nearest catalog corridors within reach: points along each corridor."""
    if not conn.execute("SELECT to_regclass('corridors') IS NOT NULL").fetchone()[0]:
        return []
    params = {"lat": lat, "lon": lon, "far": 1.5 * radius_m, "reach": REACH_FRACTION * radius_m}
    corridors = conn.execute(
        f"""SELECT id, name FROM corridors WHERE ST_DWithin(geom::geography, {_HERE}, %(reach)s)
            ORDER BY verified DESC NULLS LAST, ST_Distance(geom::geography, {_HERE}) LIMIT {MAX_CORRIDORS}""",
        params,
    ).fetchall()
    out = []
    for cid, name in corridors:
        lines = f"SELECT (ST_Dump(geom)).geom FROM corridors WHERE id = {int(cid)}"
        rows = _points(conn, lines, params)
        if rows:
            out.append(group_into_directions(rows, radius_m, source="corridor", name=name,
                                             area=_area(conn, lines, params)))
    return out


def feature_anchors(conn, lat: float, lon: float, radius_m: float) -> list[Anchors]:
    return park_anchors(conn, lat, lon, radius_m) + water_anchors(conn, lat, lon, radius_m) + \
        corridor_anchors(conn, lat, lon, radius_m)
