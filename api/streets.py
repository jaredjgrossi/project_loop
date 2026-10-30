"""Street geometry near a point, from the osm_ways table."""

import json
import math

import psycopg

from api.grid import GridEstimate, estimate_grid_angle, segments_from_linestring

# Road classes whose direction reflects the city's street grid. Footways, cycleways and
# service roads follow park curves and building lots, not the grid.
GRID_HIGHWAYS = ("residential", "tertiary", "secondary", "primary", "unclassified", "living_street", "trunk")


def segments_near(
    linestrings: list[list[list[float]]], lat: float, lon: float, radius_m: float
) -> list[tuple[float, float]]:
    """(bearing, meters) for each segment of the ways whose midpoint lies within radius_m of the point."""
    kx, ky = 111_320 * math.cos(math.radians(lat)), 110_574
    out = []
    for coords in linestrings:
        for (lon0, lat0), (lon1, lat1) in zip((c[:2] for c in coords), (c[:2] for c in coords[1:])):
            mx, my = ((lon0 + lon1) / 2 - lon) * kx, ((lat0 + lat1) / 2 - lat) * ky
            if math.hypot(mx, my) <= radius_m:
                out += segments_from_linestring([[lon0, lat0], [lon1, lat1]])
    return out


def fetch_street_segments(conn: psycopg.Connection, lat: float, lon: float, radius_m: float = 1000):
    dlat = radius_m / 110_574
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    rows = conn.execute(
        """
        SELECT ST_AsGeoJSON(geom)
        FROM osm_ways
        WHERE highway = ANY(%s)
          AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
        """,
        (list(GRID_HIGHWAYS), lon - dlon, lat - dlat, lon + dlon, lat + dlat),
    ).fetchall()
    ways = [json.loads(r[0])["coordinates"] for r in rows]
    return segments_near(ways, lat, lon, radius_m)


def grid_at(conn: psycopg.Connection, lat: float, lon: float, radius_m: float = 1000) -> GridEstimate:
    return estimate_grid_angle(fetch_street_segments(conn, lat, lon, radius_m))
