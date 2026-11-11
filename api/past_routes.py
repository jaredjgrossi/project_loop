"""Past routes (Phase 3, step 11; decision 038): a route the runner ran before, found by its id, rebuilt for now.

The phone's recent-routes list carries each route's id, the one Loop gave it (`r_xxxxxxxx.N`, or a build id
`r_xxxxxxxx` for its #1). Its line comes from `saved_routes`, which keeps every build's `final` payload (decision
030). Names and ids only ever go to Claude; the line never does.

"Skip the ferry part" (H04): a part of a past route named by a feature is matched in code, never by the model. The
ferry landings (pulse_sources, NYC Ferry GTFS and the SeaStreak timetable) within LANDING_NEAR_M of the reused
route's line are the ferry part; each becomes an area avoid with its coordinates.
"""

import json
import re
from dataclasses import dataclass

LANDING_NEAR_M = 100.0
FERRY_WORDS = re.compile(r"\bferr(y|ies)\b", re.I)


@dataclass(frozen=True)
class PastRoute:
    id: str
    coords: tuple  # [lon, lat] points, from its start
    label: str | None = None


def split_id(route_id: str) -> tuple[str, int]:
    """'r_ab12cd34.2' -> ('r_ab12cd34', 2); a build id alone means its #1."""
    build, dot, n = route_id.partition(".")
    return build, int(n) if dot and n.isdigit() else 1


def from_final(route_id: str, final: dict | None) -> PastRoute | None:
    """The route `route_id` names in a stored `final` payload: by its id, else by its rank."""
    if not final:
        return None
    _, rank = split_id(route_id)
    routes = final.get("routes") or []
    hit = next((r for r in routes if r.get("id") == route_id), None) or \
        next((r for r in routes if r.get("rank") == rank), None)
    if hit is None or not hit.get("geometry"):
        return None
    return PastRoute(route_id, tuple(tuple(c[:2]) for c in hit["geometry"]["coordinates"]), hit.get("label"))


def load(route_id: str, store) -> PastRoute | None:
    """A past route from saved_routes (`store`: api.saved_routes.PgRouteStore or a fake with `load`)."""
    return from_final(route_id, store.load(split_id(route_id)[0]))


def is_closed(coords, within_m: float = 60.0) -> bool:
    """Whether a route ends where it started (a loop or an out-and-back), not somewhere else."""
    import math
    (x0, y0), (x1, y1) = coords[0][:2], coords[-1][:2]
    kx = 111_320 * math.cos(math.radians(y0))
    return math.hypot((x1 - x0) * kx, (y1 - y0) * 110_574) <= within_m


def landing_name(name: str) -> str:
    """'East 34th Street' -> 'E 34th St ferry landing', for the avoid's chip."""
    short = re.sub(r"\bEast\b", "E", re.sub(r"\bWest\b", "W", name))
    short = re.sub(r"\bStreet\b", "St", short)
    return f"{short} ferry landing"


_LANDINGS = """
WITH r AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%(line)s), 4326) g)
SELECT DISTINCT ON (ST_SnapToGrid(p.geom, 0.0002)) p.name, ST_Y(p.geom), ST_X(p.geom), p.source, p.trust
FROM pulse_sources p, r
WHERE p.kind = 'ferry' AND ST_DWithin(p.geom::geography, r.g::geography, %(near)s)
ORDER BY ST_SnapToGrid(p.geom, 0.0002), p.operator = 'NYC Ferry' DESC, p.name
"""


def ferry_landings_along(coords, conn, near_m: float = LANDING_NEAR_M) -> list[dict]:
    """The ferry landings within `near_m` of a route's line, one per spot (two operators can share a pier), as
    avoid entries with a place: {"name", "how": "area", "place": PlaceRef}."""
    from api.constraints import PlaceRef

    line = json.dumps({"type": "LineString", "coordinates": [list(c[:2]) for c in coords]})
    out = []
    for name, lat, lon, source, trust in conn.execute(_LANDINGS, {"line": line, "near": near_m}).fetchall():
        place = PlaceRef(kind="place", name=landing_name(name), borough=_borough(conn, lat, lon), lat=lat, lon=lon,
                         source=source.split(",")[0], trust=trust or "listed")
        out.append({"name": place.name, "how": "area", "place": place.model_dump(exclude_none=True)})
    return out


def _borough(conn, lat: float, lon: float) -> str:
    from api.places import borough_at
    return borough_at(lat, lon, conn=conn) or "Manhattan"
