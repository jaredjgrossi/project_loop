"""Small planar predicates on [lon, lat] coordinates, for hard rules such as no-go zones.

Over the size of a no-go zone (hundreds of meters) treating lon/lat as planar is exact enough for a yes/no
"does this route touch this area" answer; anything measured in meters goes through PostGIS or api/shape.py instead.
"""


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
