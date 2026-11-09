"""Small planar predicates on [lon, lat] coordinates, for hard rules such as no-go zones.

Over the size of a no-go zone (hundreds of meters) treating lon/lat as planar is exact enough for a yes/no
"does this route touch this area" answer; anything measured in meters goes through PostGIS or api/shape.py instead.
"""

import math


def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    """Ray casting. The ring's last point repeats its first."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def segments_cross(p, q, a, b) -> bool:
    def orient(u, v, w):
        return (v[0] - u[0]) * (w[1] - u[1]) - (v[1] - u[1]) * (w[0] - u[0])

    d1, d2, d3, d4 = orient(a, b, p), orient(a, b, q), orient(p, q, a), orient(p, q, b)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def _inside(x: float, y: float, rings: list[list[list[float]]]) -> bool:
    outer, holes = rings[0], rings[1:]
    return point_in_ring(x, y, outer) and not any(point_in_ring(x, y, h) for h in holes)


def line_touches_polygon(coords: list[list[float]], rings: list[list[list[float]]]) -> bool:
    """Whether a route enters a polygon given as GeoJSON rings (outer first, then holes)."""
    if any(_inside(c[0], c[1], rings) for c in coords):
        return True
    edges = [(a, b) for ring in rings for a, b in zip(ring, ring[1:])]
    return any(segments_cross(p, q, a, b) for p, q in zip(coords, coords[1:]) for a, b in edges)


# ---- outlines for the candidates event (step 7b, decision 031) ----------------------------------------------------

OUTLINE_MAX_POINTS = 40
OUTLINE_DECIMALS = 5  # about 1 m


def outline(coords: list[list[float]], max_points: int = OUTLINE_MAX_POINTS) -> list[list[float]]:
    """A light outline of a route for drawing while the engine works: Douglas-Peucker with the smallest tolerance
    that leaves at most `max_points` points (20-40 on a long route), so corners and the ends are kept, then [lon, lat]
    rounded to about 1 m. Elevation is dropped. Only for drawing: nothing is measured on it."""
    from shapely.geometry import LineString

    flat = [[c[0], c[1]] for c in coords]
    pts = flat
    if len(flat) > max_points:
        line, tol = LineString(flat), 1e-6  # degrees; about 0.1 m
        while True:
            pts = [list(p) for p in line.simplify(tol, preserve_topology=False).coords]
            if len(pts) <= max_points:
                break
            tol *= 1.5
    return [[round(x, OUTLINE_DECIMALS), round(y, OUTLINE_DECIMALS)] for x, y in pts]


# ---- passing through a via (step 9, decision 034) -----------------------------------------------------------------

def shapes_within(a: dict, b: dict, tolerance_m: float, origin: tuple[float, float] | None = None) -> bool:
    """Whether two GeoJSON geometries come within `tolerance_m` of each other (overlapping counts), in meters on a
    local flat projection around `origin` ([lon, lat]; default a's first coordinate)."""
    import numpy as np
    import shapely
    from shapely.geometry import shape as to_shape

    ga, gb = to_shape(a), to_shape(b)
    lon0, lat0 = origin or shapely.get_coordinates(ga)[0]
    scale = np.array([111_320 * math.cos(math.radians(lat0)), 110_574])

    def flat(xy):
        return (xy - np.array([lon0, lat0])) * scale

    return shapely.transform(ga, flat).distance(shapely.transform(gb, flat)) <= tolerance_m


def passes_through(coords: list[list[float]], shape: dict, tolerance_m: float) -> bool:
    """Whether a [lon, lat] route comes within `tolerance_m` of a GeoJSON geometry (a park's outline, a path's line,
    a point): measured in meters on a local flat projection around the route's start, which is exact enough across
    a city run."""
    if len(coords) < 2:
        return False
    return shapes_within({"type": "LineString", "coordinates": [c[:2] for c in coords]}, shape, tolerance_m)


def _flat(origin: tuple[float, float]):
    """[lon, lat] -> meters on a local flat projection around `origin` ([lon, lat])."""
    import numpy as np
    lon0, lat0 = origin
    scale = np.array([111_320 * math.cos(math.radians(lat0)), 110_574])
    return lambda xy: (xy - np.array([lon0, lat0])) * scale


def line_length_m(coords: list[list[float]]) -> float:
    """The length of a [lon, lat] line in meters (local flat projection; exact enough across the city)."""
    import shapely
    from shapely.geometry import LineString
    return shapely.transform(LineString([c[:2] for c in coords]), _flat(coords[0][:2])).length


def covered_share(coords: list[list[float]], line: dict, tolerance_m: float) -> float:
    """The share of a GeoJSON line (a lap's ring, a past route) that a [lon, lat] route runs along: the length of the
    line within `tolerance_m` of the route over the line's length (decision 035). Measured segment by segment, so a
    line that runs its path twice (an out-and-back, step 11) counts both ways: one intersection of the whole line
    would merge the two and count it once."""
    import numpy as np
    import shapely
    from shapely.geometry import LineString
    from shapely.geometry import shape as to_shape

    if len(coords) < 2:
        return 0.0
    flat = _flat(coords[0][:2])
    route = shapely.transform(LineString([c[:2] for c in coords]), flat)
    target = shapely.transform(to_shape(line), flat)
    parts = getattr(target, "geoms", [target])
    segs = [np.array(p.coords) for p in parts if not p.is_empty]
    pairs = np.concatenate([np.stack([s[:-1], s[1:]], axis=1) for s in segs if len(s) > 1]) if segs else []
    if len(pairs) == 0:
        return 0.0
    pieces = shapely.linestrings(pairs)
    total = shapely.length(pieces).sum()
    if total == 0:
        return 0.0
    return float(shapely.length(shapely.intersection(pieces, route.buffer(tolerance_m))).sum() / total)

def oriented(coords: list, direction: str) -> list:
    """A closed ring's [lon, lat] coordinates, turned to run counterclockwise or clockwise."""
    from shapely.geometry import LinearRing

    ccw = LinearRing([c[:2] for c in coords]).is_ccw
    return list(coords) if ccw == (direction == "counterclockwise") else list(coords)[::-1]
