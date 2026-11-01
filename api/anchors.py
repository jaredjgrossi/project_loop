"""Anchors: points on parks, waterfront paths and corridors that candidate routes go out to (decision 012).

A route built from an anchor set goes from the start to the set's entry (its nearest point), on to a turnaround
picked by walking distance along the feature to fit the distance (decision 014), and back: either the same way (an
out-and-back) or by whatever way is shortest (a loop or lollipop). These sets come from OSM in PostGIS for every runner: OSM park areas (osm_parks, which include
Hudson River Park), path-like ways along the OSM coastline, and the corridor catalog (etl/build_corridors.py). The
runner's own routes are a separate, optional source (api/scripts/make_loop.familiar_anchors) and never feed these.
"""

import heapq
import json
import math
from dataclasses import dataclass

REACH_FRACTION = 0.8  # a feature farther than this share of the radius is outside the budget
MAX_PARKS = 3
MAX_CORRIDORS = 3
MIN_PARK_M2 = 20_000  # 2 hectares: big enough to run in, not a triangle or a garden


@dataclass(frozen=True)
class Anchors:
    entry: tuple[float, float] | None  # nearest point: out-and-backs go out and back through it
    # Per direction, (lat, lon, straight-line meters from start, meters along the feature from the entry), nearest
    # first. The runner-prior source has no along distance (3-tuples) and is placed by straight-line distance.
    directions: list[list[tuple]]
    source: str = "familiar"  # familiar | park | water | corridor
    name: str | None = None
    area: dict | None = None  # GeoJSON polygon of the feature: routes to it are routed to prefer staying inside it
    placement: str = "along"  # along: turnarounds by walking distance; straight: by straight-line distance


# --- walking distance along the feature (decision 014) -----------------------------------

DENSIFY_M = 50  # split long segments so a turnaround can land anywhere along them
ALONG_SAMPLE_M = 100  # one candidate turnaround per this much walking distance
MIN_BRANCH_M = 100  # shorter branches out of the entry can't hold a turnaround
MAX_ALONG_FACTOR = 3.0  # candidates up to this many radii along the feature
SNAP_M = 25  # a path's dead end joins any other path this close: OSM connects them through ways not in the set
def _join_dead_ends(graph: dict, coords: dict, xy) -> None:
    """Connect each dead end to the nearest node within SNAP_M that isn't already its neighbor. Breaks of a few meters
    (a sidewalk or crossing joins two waterfront paths) close; real gaps (hundreds of meters) stay open."""
    pos = {n: xy(lon, lat) for n, (lat, lon) in coords.items()}
    grid: dict[tuple[int, int], list] = {}
    for n, (x, y) in pos.items():
        grid.setdefault((int(x // SNAP_M), int(y // SNAP_M)), []).append(n)
    for node in [n for n, edges in graph.items() if len(edges) == 1]:
        x, y = pos[node]
        neighbors = {m for m, _ in graph[node]}
        best, best_d = None, SNAP_M
        for gx in (int(x // SNAP_M) - 1, int(x // SNAP_M), int(x // SNAP_M) + 1):
            for gy in (int(y // SNAP_M) - 1, int(y // SNAP_M), int(y // SNAP_M) + 1):
                for m in grid.get((gx, gy), ()):
                    if m != node and m not in neighbors:
                        d = math.hypot(pos[m][0] - x, pos[m][1] - y)
                        if d <= best_d:
                            best, best_d = m, d
        if best is not None:
            graph[node].append((best, best_d))
            graph[best].append((node, best_d))


def along_feature(lines, start: tuple[float, float], radius_m: float, source: str, name: str | None,
                  area: dict | None = None) -> Anchors:
    """Anchors whose turnarounds are measured by walking distance along the feature from its entry.

    lines: the feature's ways as [lon, lat] lists. They become a graph (ways that share a vertex connect), the entry
    is the vertex nearest the start, and walking distances come from Dijkstra over that graph. A piece the feature's
    paths don't connect to (the other bank of a river, the far side of a gap) is never offered. Each branch out of the
    entry is a direction. Points are (lat, lon, straight-line meters from the start, meters along the feature).
    A gap in the feature (the Con Ed plant, the UN stretch) ends a direction; the route then continues past the end
    on streets ("and beyond")."""
    lat0, lon0 = start
    kx, ky = 111_320 * math.cos(math.radians(lat0)), 110_574

    def xy(lon, lat):
        return (lon - lon0) * kx, (lat - lat0) * ky

    graph: dict[tuple, list[tuple[tuple, float]]] = {}
    coords: dict[tuple, tuple[float, float]] = {}
    for line in lines:
        prev = None
        for lon, lat in (c[:2] for c in line):
            if prev is not None:
                (plon, plat), (x0, y0), (x1, y1) = prev, xy(*prev), xy(lon, lat)
                n = max(1, int(math.hypot(x1 - x0, y1 - y0) // DENSIFY_M))
                last = (round(plon, 6), round(plat, 6))
                coords[last] = (plat, plon)
                for k in range(1, n + 1):
                    f = k / n
                    clon, clat = plon + (lon - plon) * f, plat + (lat - plat) * f
                    # Interior split points are private to their segment; vertices are shared with other ways.
                    node = (round(clon, 6), round(clat, 6)) if k == n else (round(clon, 6), round(clat, 6), id(line), k)
                    coords[node] = (clat, clon)
                    d = math.hypot(*(a - b for a, b in zip(xy(clon, clat), xy(*coords[last][::-1]))))
                    graph.setdefault(last, []).append((node, d))
                    graph.setdefault(node, []).append((last, d))
                    last = node
            prev = (lon, lat)
    if not graph:
        return Anchors(entry=None, directions=[], source=source, name=name, area=area)
    _join_dead_ends(graph, coords, xy)

    def straight(node):
        lat, lon = coords[node]
        return math.hypot(*xy(lon, lat))

    root = min(graph, key=straight)
    along, branch = {root: 0.0}, {root: None}
    heap = [(0.0, 0, root)]
    counter = 1
    while heap:
        d, _, node = heapq.heappop(heap)
        if d > along.get(node, math.inf) or d > MAX_ALONG_FACTOR * radius_m:
            continue
        for nxt, w in graph[node]:
            nd = d + w
            if nd < along.get(nxt, math.inf):
                along[nxt] = nd
                branch[nxt] = nxt if node == root else branch[node]
                heapq.heappush(heap, (nd, counter, nxt))
                counter += 1
    by_branch: dict = {}
    for node, d in along.items():
        if node != root and d <= MAX_ALONG_FACTOR * radius_m:
            by_branch.setdefault(branch[node], []).append((d, node))
    directions = []
    for nodes in by_branch.values():
        nodes.sort()
        if nodes[-1][0] < MIN_BRANCH_M:
            continue
        kept, last = [], -math.inf
        for d, node in nodes:
            if d - last >= ALONG_SAMPLE_M:
                kept.append((*coords[node], straight(node), d))
                last = d
        if kept[-1][3] != nodes[-1][0]:
            d, node = nodes[-1]
            kept.append((*coords[node], straight(node), d))
        directions.append(kept)
    directions.sort(key=lambda pts: -pts[-1][3])  # the branch that reaches farthest first
    return Anchors(entry=coords[root], directions=directions, source=source, name=name, area=area)


SECTOR_DEG = 45
MIN_TURN_FRACTION = 0.2  # a straight-line turnaround nearer than this share of the radius can't make the distance


def straight_line_anchors(lines, start: tuple[float, float], radius_m: float, source: str, name: str | None,
                          area: dict | None = None) -> Anchors:
    """The same feature placed by straight-line distance from the start (decision 012's method), over every piece of
    it whether its paths connect or not. It complements along_feature: where a feature ends at a gap, a turnaround on
    the piece past the gap is still offered and routing finds the way (decision 014)."""
    lat0, lon0 = start
    kx, ky = 111_320 * math.cos(math.radians(lat0)), 110_574
    points = []
    for line in lines:
        prev = None
        for lon, lat in (c[:2] for c in line):
            if prev is not None:
                (plon, plat) = prev
                seg = math.hypot((lon - plon) * kx, (lat - plat) * ky)
                for k in range(1, max(1, int(seg // ALONG_SAMPLE_M)) + 1):
                    f = k / max(1, int(seg // ALONG_SAMPLE_M))
                    points.append((plat + (lat - plat) * f, plon + (lon - plon) * f))
            else:
                points.append((lat, lon))
            prev = (lon, lat)
    if not points:
        return Anchors(entry=None, directions=[], source=source, name=name, area=area, placement="straight")

    def polar(p):
        dx, dy = (p[1] - lon0) * kx, (p[0] - lat0) * ky
        return math.hypot(dx, dy), math.degrees(math.atan2(dx, dy)) % 360

    nearest = min(points, key=lambda p: polar(p)[0])
    sectors: dict[int, list] = {}
    for p in points:
        dist, bearing = polar(p)
        if dist >= MIN_TURN_FRACTION * radius_m:
            sectors.setdefault(int(bearing // SECTOR_DEG), []).append((p[0], p[1], dist))
    busiest = sorted(sectors.values(), key=len, reverse=True)
    return Anchors(entry=nearest, directions=[sorted(pts, key=lambda q: q[2]) for pts in busiest],
                   source=source, name=name, area=area, placement="straight")


# --- PostGIS ----------------------------------------------------------------------------

_HERE = "ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326)::geography"
_PATHLIKE = """
    w.highway IN ('footway', 'path', 'cycleway', 'pedestrian', 'track', 'bridleway')
    AND coalesce(w.tags->>'footway', '') NOT IN ('sidewalk', 'crossing', 'traffic_island', 'access_aisle')
    AND coalesce(w.tags->>'foot', 'yes') NOT IN ('no', 'private')
    AND coalesce(w.tags->>'access', 'yes') NOT IN ('no', 'private')
"""


AREA_BUFFER_M = 30  # line features (paths, corridors) become an area this wide on each side
AREA_SIMPLIFY_DEG = 0.0001  # ~10 m: keeps the GraphHopper request small


def _lines(conn, lines_sql: str, params: dict) -> list:
    """The feature's ways as [lon, lat] coordinate lists."""
    return [json.loads(g)["coordinates"] for (g,) in conn.execute(
        f"SELECT ST_AsGeoJSON((ST_Dump(g)).geom, 7) FROM ({lines_sql}) AS f(g)", params)]


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
        found = _lines(conn, lines, params)
        if found:
            area = _area(conn, f"SELECT geom FROM osm_parks WHERE area_id = {int(area_id)}", params)
            out.append(along_feature(found, (lat, lon), radius_m, source="park", name=name, area=area))
            out.append(straight_line_anchors(found, (lat, lon), radius_m, source="park", name=name, area=area))
    return out


def water_anchors(conn, lat: float, lon: float, radius_m: float, within_m: float = 60) -> list[Anchors]:
    """Points on path-like ways within `within_m` of the OSM coastline (the same 60 m as the waterfront share)."""
    params = {"lat": lat, "lon": lon, "far": 1.5 * radius_m, "reach": REACH_FRACTION * radius_m}
    if conn.execute("SELECT to_regclass('waterfront_paths') IS NOT NULL").fetchone()[0]:
        # Precomputed by etl/build_corridors.py with the same 60 m rule (decision 014).
        lines = f"""SELECT geom FROM waterfront_paths
                    WHERE geom && ST_Expand(ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326), %(far)s / 80000.0)
                      AND ST_DWithin(geom::geography, {_HERE}, %(far)s)"""
    else:
        lines = f"""SELECT w.geom FROM osm_ways w
                    WHERE ST_DWithin(w.geom::geography, {_HERE}, %(far)s) AND {_PATHLIKE}
                      AND EXISTS (SELECT 1 FROM osm_coastline c WHERE c.geom && ST_Expand(w.geom, 0.001)
                                  AND ST_DWithin(c.geom::geography, w.geom::geography, {within_m}))"""
    found = _lines(conn, lines, params)
    if not found:
        return []
    area = _area(conn, lines, params)
    anchors = along_feature(found, (lat, lon), radius_m, source="water", name="waterfront", area=area)
    if anchors.entry is None or _meters((lat, lon), anchors.entry) > params["reach"]:
        return []
    return [anchors, straight_line_anchors(found, (lat, lon), radius_m, source="water", name="waterfront", area=area)]


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
        found = _lines(conn, lines, params)
        if found:
            area = _area(conn, lines, params)
            out.append(along_feature(found, (lat, lon), radius_m, source="corridor", name=name, area=area))
            out.append(straight_line_anchors(found, (lat, lon), radius_m, source="corridor", name=name, area=area))
    return out


def _meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot((a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0])), (a[0] - b[0]) * 110_574)


def feature_anchors(conn, lat: float, lon: float, radius_m: float) -> list[Anchors]:
    return park_anchors(conn, lat, lon, radius_m) + water_anchors(conn, lat, lon, radius_m) + \
        corridor_anchors(conn, lat, lon, radius_m)
