"""Along-avoids (Phase 3, step 8b; decision 036): don't run along a named street or stretch; crossing it is fine (R15).

"Avoid 42nd St" or "avoid 1st Ave by the hospitals" (a stretch, "1st Ave, E 25th–E 34th St") names a street. Code finds
its centre lines in the places table, near the start, and cuts a stretch between its two cross streets.

Two halves, like a no-go zone (decision 010) but softer in the router:
- **The router** gets a strip ALONG_HALF_WIDTH_M either side of the street (its sidewalks too), cut into one area per
  block with a gap of CROSSING_GAP_M around every crossing, and makes edges in it ALONG_PRIORITY times as attractive.
  A GraphHopper area catches every edge that touches it, so without the gaps the side streets that meet the avenue
  would cost as much as running along it.
- **The hard rule**: a route that stays inside the whole strip (no gaps) for ALONG_MAX_M in one go runs along the street
  and is rejected (`runs_along`). Crossing a 30 m avenue takes about 40 m of strip; a short block is about 80 m.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

ALONG_HALF_WIDTH_M = 20.0
CROSSING_GAP_M = 30.0
ALONG_PRIORITY = 0.05
ALONG_MAX_M = 75.0
MAX_AREAS = 60  # GraphHopper areas per avoided street: the longest blocks first


@dataclass(frozen=True)
class Along:
    name: str
    lines: tuple  # the street's (or stretch's) centre lines, each a tuple of [lon, lat]
    crossings: tuple = ()  # (lon, lat) where other streets cross it

    def __post_init__(self):  # tuples all the way down, so an Along can key the strip cache
        object.__setattr__(self, "lines", tuple(tuple(tuple(c[:2]) for c in ln) for ln in self.lines))
        object.__setattr__(self, "crossings", tuple(tuple(c[:2]) for c in self.crossings))


def _flat(origin):
    import numpy as np
    lon0, lat0 = origin
    scale = np.array([111_320 * math.cos(math.radians(lat0)), 110_574])
    return (lambda xy: (xy - np.array([lon0, lat0])) * scale), (lambda xy: xy / scale + np.array([lon0, lat0]))


@cache
def strip(a: Along, half_width_m: float = ALONG_HALF_WIDTH_M):
    """The whole strip, in flat meters around the street's first point, and the functions to and from [lon, lat].
    Cached: the hard rule checks every candidate against it."""
    import shapely
    from shapely.geometry import MultiLineString

    to_flat, to_lonlat = _flat(a.lines[0][0][:2])
    lines = shapely.transform(MultiLineString([[c[:2] for c in line] for line in a.lines]), to_flat)
    return lines.buffer(half_width_m, cap_style="flat"), to_flat, to_lonlat


def router_areas(a: Along, prefix: str) -> list[dict]:
    """GeoJSON features (single polygons, [lon, lat]) for GraphHopper: the strip with a gap around each crossing."""
    import shapely
    from shapely.geometry import MultiPoint

    whole, to_flat, to_lonlat = strip(a)
    pieces = whole
    if a.crossings:
        holes = shapely.transform(MultiPoint([c[:2] for c in a.crossings]), to_flat).buffer(CROSSING_GAP_M, quad_segs=4)
        pieces = whole.difference(holes)
    parts = sorted(getattr(pieces, "geoms", [pieces]), key=lambda g: -g.area)[:MAX_AREAS]
    out = []
    for i, part in enumerate(p for p in parts if not p.is_empty and p.area > 1.0):
        ring = shapely.transform(part.simplify(0.5).exterior, to_lonlat)
        out.append({"type": "Feature", "id": f"{prefix}_{i}", "properties": {},
                    "geometry": {"type": "Polygon", "coordinates": [[[round(x, 7), round(y, 7)]
                                                                      for x, y in ring.coords]]}})
    return out


def custom_model(alongs: Sequence[Along]) -> dict | None:
    """A per-request custom model that makes running along each street costly; None when there are none."""
    features = [f for k, a in enumerate(alongs) for f in router_areas(a, f"along_{k}")]
    if not features:
        return None
    # One rule for every area: GraphHopper checks a rule per edge, and 25 rules took three times as long (0.13 s a
    # route against 0.05 s, decision 036).
    return {"priority": [{"if": " || ".join(f"in_{f['id']}" for f in features), "multiply_by": str(ALONG_PRIORITY)}],
            "areas": {"type": "FeatureCollection", "features": features}}


def longest_run_inside_m(coords: Sequence, a: Along) -> float:
    """The longest stretch of a [lon, lat] route that stays inside the street's whole strip, in meters."""
    import shapely
    from shapely.geometry import LineString

    if len(coords) < 2:
        return 0.0
    whole, to_flat, _ = strip(a)
    route = shapely.transform(LineString([c[:2] for c in coords]), to_flat)
    inside = route.intersection(whole)
    if inside.is_empty:
        return 0.0
    parts = getattr(inside, "geoms", [inside])
    from shapely.ops import linemerge
    merged = linemerge([p for p in parts if p.geom_type == "LineString"]) if len(parts) > 1 else inside
    return max((g.length for g in getattr(merged, "geoms", [merged])), default=0.0)


def runs_along(coords: Sequence, alongs: Sequence[Along], max_m: float = ALONG_MAX_M) -> list[Along]:
    """The streets a route runs along (ALONG_MAX_M or more inside one strip in one go)."""
    return [a for a in alongs if longest_run_inside_m(coords, a) >= max_m]


def split_stretch(name: str) -> tuple[str, str | None, str | None]:
    """'1st Ave, E 25th–E 34th St' -> ('1st Ave', 'E 25th St', 'E 34th St'); a plain street -> (name, None, None).
    The parse prompt names a stretch this way (decision 028)."""
    import re

    street, comma, rest = name.partition(",")
    if not comma:
        return name.strip(), None, None
    ends = [p.strip() for p in re.split(r"\s*[–—-]\s*", rest.strip()) if p.strip()]
    if len(ends) != 2:
        return street.strip(), None, None
    first, last = ends
    suffix = re.search(r"\s(St|Ave|Avenue|Street|Pl|Place|Blvd|Rd|Dr)\.?$", last)
    if suffix and not re.search(r"\s(St|Ave|Avenue|Street|Pl|Place|Blvd|Rd|Dr)\.?$", first):
        first = f"{first}{suffix.group(0)}"
    return street.strip(), first, last


def cut_stretch(lines: Sequence, a: tuple[float, float], b: tuple[float, float]) -> tuple:
    """The parts of a street's [lon, lat] centre lines between two (lon, lat) points on or near it (its cross
    streets), as lines. Lines that don't run past both points are left out."""
    import shapely
    from shapely.geometry import LineString, Point
    from shapely.ops import linemerge, substring

    to_flat, to_lonlat = _flat(lines[0][0][:2])
    pa = shapely.transform(Point(a[:2]), to_flat)
    pb = shapely.transform(Point(b[:2]), to_flat)
    merged = linemerge([shapely.transform(LineString([c[:2] for c in line]), to_flat) for line in lines])
    out = []
    for flat in getattr(merged, "geoms", [merged]):  # OSM splits a street at every block: join it up first
        if flat.distance(pa) > 60 or flat.distance(pb) > 60:
            continue
        da, db = sorted((flat.project(pa), flat.project(pb)))
        if db - da < 1:
            continue
        piece = shapely.transform(substring(flat, da, db), to_lonlat)
        out.append(tuple([round(x, 7), round(y, 7)] for x, y in piece.coords))
    return tuple(out)


REACH_M = 6000  # an avoided street's lines within this of the start (the longest run's reach)

_LINES = """SELECT ST_AsGeoJSON(ST_Collect(outline)) FROM places
            WHERE id = ANY(%(ids)s) AND outline IS NOT NULL
              AND ST_DWithin(outline::geography, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)::geography, %(reach)s)"""
_CROSSING = """SELECT ST_X(pt), ST_Y(pt) FROM (
                 SELECT ST_ClosestPoint(ST_Intersection(s.g, ST_Collect(c.outline)), ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)) pt
                 FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(street)s), 4326) g) s, places c
                 WHERE c.id = ANY(%(ids)s) AND ST_Intersects(s.g, c.outline) GROUP BY s.g) x WHERE NOT ST_IsEmpty(pt)"""
_CROSSINGS = """WITH s AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(street)s), 4326) g)
                SELECT ST_AsGeoJSON(ST_Collect(ST_Intersection(s.g, p.outline))) FROM s, places p
                WHERE p.kind IN ('street', 'path') AND p.outline IS NOT NULL AND NOT p.id = ANY(%(ids)s)
                  AND ST_Intersects(s.g, p.outline)"""


def _points(geojson: str | None) -> tuple:
    import json
    if not geojson:
        return ()
    g = json.loads(geojson)
    out = []

    def walk(geom):
        t = geom["type"]
        if t == "Point":
            out.append(tuple(geom["coordinates"][:2]))
        elif t == "MultiPoint":
            out.extend(tuple(c[:2]) for c in geom["coordinates"])
        elif t == "GeometryCollection":
            for sub in geom["geometries"]:
                walk(sub)
    walk(g)
    return tuple(out)


def db_alongs(names: Sequence[str], near: tuple[float, float], conn, reach_m: float = REACH_M):
    """The streets (and stretches) to avoid running along, near the start, and the names code couldn't find."""
    import json

    from api.places import lookup

    found, unknown = [], []
    lat, lon = near
    for name in names:
        street, a, b = split_stretch(name)
        hits = [m for m in lookup(street, near=near, conn=conn) if m.kind in ("street", "path")]
        hit = hits[0] if hits and (hits[0].distance_m or 0) <= reach_m else None
        row = conn.execute(_LINES, {"ids": list(hit.ids), "lon": lon, "lat": lat, "reach": reach_m}).fetchone() \
            if hit else None
        if not row or not row[0]:
            unknown.append(name)
            continue
        geom = json.loads(row[0])
        lines = []
        for part in geom["geometries"] if geom["type"] == "GeometryCollection" else [geom]:
            lines += part["coordinates"] if part["type"] == "MultiLineString" else [part["coordinates"]]
        if a and b:
            ends = []
            for cross in (a, b):
                c = next(iter(lookup(cross, near=near, conn=conn)), None)
                pt = conn.execute(_CROSSING, {"street": row[0], "ids": list(c.ids), "lon": lon, "lat": lat}
                                  ).fetchone() if c else None
                ends.append(pt)
            if None in ends:
                unknown.append(name)
                continue
            lines = list(cut_stretch(lines, ends[0], ends[1]))
            if not lines:
                unknown.append(name)
                continue
        stretch = json.dumps({"type": "MultiLineString", "coordinates": [list(map(list, ln)) for ln in lines]})
        crossings = _points(conn.execute(_CROSSINGS, {"street": stretch, "ids": list(hit.ids)}).fetchone()[0])
        found.append(Along(name, tuple(tuple(tuple(c[:2]) for c in ln) for ln in lines), crossings))
    return found, unknown
