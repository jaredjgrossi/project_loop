"""Known closures (decision 017): places a route may not pass through.

Two sources, both in the closures table (etl/sql/schema.sql):
- corridor_gap: a missing link of the corridor catalog (decision 012), drawn as a strip along the link, applied only
  where no walkable OSM way runs along it (etl/build_closures.py). Nothing routable runs there, so GraphHopper is not
  told; the hard rule is the check below.
- report: a runner's "closed or blocked" report on a stretch, once a reviewer confirms it (confirm_report). It sits
  on a real way, so GraphHopper gets it as an area with priority 0, like a no-go zone (decision 010).

The hard rule: a route with PASS_THROUGH_M or more of its length inside a closure is rejected (reason "closure").
A street that only crosses a closure's strip stays open.
"""

import json
import math
from dataclasses import dataclass

from api.geometry import point_in_ring

PASS_THROUGH_M = 30
STEP_M = 2.0  # sampling step for the length inside a polygon
EARTH_M_PER_DEG = 111_320


@dataclass(frozen=True, eq=False)
class Closure:
    id: int
    kind: str  # corridor_gap | report
    name: str
    reason: str
    source: str
    trust: str  # verified | listed | seasonal_or_closed (product rule 2)
    rings: list  # GeoJSON polygon rings, [lon, lat]
    in_router: bool  # given to GraphHopper as an impassable area

    @property
    def area_id(self) -> str:
        return f"closure_{self.id}"


def _inside(x: float, y: float, rings) -> bool:
    return point_in_ring(x, y, rings[0]) and not any(point_in_ring(x, y, h) for h in rings[1:])


def length_inside_m(coords: list[list[float]], rings) -> float:
    """Meters of the route inside the polygon, by sampling each segment every STEP_M (local planar meters)."""
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    box = (min(xs), min(ys), max(xs), max(ys))
    m_lon = EARTH_M_PER_DEG * math.cos(math.radians((box[1] + box[3]) / 2))
    total = 0.0
    for (x1, y1, *_), (x2, y2, *_) in zip(coords, coords[1:]):
        if max(x1, x2) < box[0] or min(x1, x2) > box[2] or max(y1, y2) < box[1] or min(y1, y2) > box[3]:
            continue
        seg = math.hypot((x2 - x1) * m_lon, (y2 - y1) * EARTH_M_PER_DEG)
        n = max(1, math.ceil(seg / STEP_M))
        for i in range(n):
            t = (i + 0.5) / n
            if _inside(x1 + t * (x2 - x1), y1 + t * (y2 - y1), rings):
                total += seg / n
    return total


def passes_through(coords: list[list[float]], closure: Closure) -> bool:
    return length_inside_m(coords, closure.rings) >= PASS_THROUGH_M


def passed(coords: list[list[float]], closures) -> list[Closure]:
    return [c for c in closures if passes_through(coords, c)]


def custom_model(closures) -> dict | None:
    """A GraphHopper per-request custom model that makes each router closure impassable, or None when there are none."""
    routed = [c for c in closures if c.in_router]
    if not routed:
        return None
    return {
        "priority": [{"if": f"in_{c.area_id}", "multiply_by": "0"} for c in routed],
        "areas": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": c.area_id, "properties": {}, "geometry": {"type": "Polygon", "coordinates": c.rings}}
            for c in routed]},
    }


_LOAD = """
SELECT id, kind, name, reason, source, trust, ST_AsGeoJSON(geom), in_router FROM closures
WHERE applied AND (active_until IS NULL OR active_until >= current_date)
  AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
ORDER BY id
"""


def load_closures(conn, lat: float, lon: float, reach_m: float) -> list[Closure]:
    """The applied, current closures within reach_m of the start."""
    if not conn.execute("SELECT to_regclass('closures') IS NOT NULL").fetchone()[0]:
        return []
    return [Closure(id=r[0], kind=r[1], name=r[2], reason=r[3], source=r[4], trust=r[5],
                    rings=json.loads(r[6])["coordinates"], in_router=r[7])
            for r in conn.execute(_LOAD, (lon, lat, reach_m)).fetchall()]


def reach_m(miles: float) -> float:
    """How far from the start a route of this length can reach, with room for the distance tolerance."""
    return miles * 1609.344 / 2 * 1.2 + 200


REPORT_BUFFER_M = 8

_CONFIRM = f"""
INSERT INTO closures (kind, name, reason, source, trust, applied, in_router, report_id, active_until, geom)
SELECT 'report', coalesce(r.stretch_name, 'reported stretch'), 'closed or blocked (runner report)',
       'runner report #' || r.id || ' on route ' || r.route_id || ', confirmed ' || current_date, 'listed', true, true,
       r.id, %(until)s,
       ST_Transform(ST_Buffer(ST_Transform(r.geom, 2263), {REPORT_BUFFER_M} * 3.28084), 4326)
FROM closure_reports r WHERE r.id = %(id)s AND r.geom IS NOT NULL AND r.status = 'reported'
RETURNING id
"""


def confirm_report(conn, report_id: int, until=None) -> int | None:
    """Make a reported closure a hard rule (a reviewer step: one report doesn't close a path for everyone). Returns the
    new closure's id, or None when the report has no stretch geometry or was already handled."""
    row = conn.execute(_CONFIRM, {"id": report_id, "until": until}).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE closure_reports SET status = 'confirmed', closure_id = %s WHERE id = %s", (row[0], report_id))
    return row[0]
