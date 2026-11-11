"""Build routes for a parsed request and stream them as contract events (Phase 3, step 5; decision 029).

The same build as the CLI (api/scripts/make_loop.py): the no-go zones, closures, the runner's lights setting, the
grid, the anchored generators and the context scoring. Each time the top 3 changes, the generator's `on_top3` sends
a `top3` event, then `provisional` once the anchored tiers are done (decision 018). This module turns those into
the contract's payloads and adds `final`: the #1 in full, as the iPhone fixture's `route` (kips3-ui.json).

`send` is called from the generator's worker threads; the server bridges it into the event stream.
"""

import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import psycopg

from api.constraints import RunConstraints, resolve_preferences, unsupported
from api.copy import render
from api.generate import TOLERANCE_PCT, Candidate, generate_loops
from api.geocoding import GeocodeError, geocode
from api.geometry import line_length_m, outline
from api.a_to_b import ask_miles, generate_a_to_b, shorter_than_the_shortest_way
from api.units import meters_to_miles
from api.via import Via, features_on_vias, through_rules, tour, via_jobs
from api.naming import display_name
from api.nogo import NoGoZone
from api.nogo import resolve as resolve_zones
from api.routing import RoutingError, graphhopper_url
from api.scripts import make_loop as ml
from api.summary import METERS_PER_MILE, route_summary

# The engine can't build a request with these until a later step, so it builds nothing and says why (rule 3).
POOLS_KEPT = 8  # builds whose candidates a shape edit can reuse; about 5 MB each
_POOLS_LOCK = threading.Lock()
BLOCKING: tuple[str, ...] = ()  # step 11 builds the last of them (past routes)
# Nothing in Phase 3 is left for later: a planned second run is built after the first (step 11, the server).
TOP_N = 3


class EngineUnavailable(Exception):
    """GraphHopper or Postgres can't be reached."""


class BadStart(Exception):
    """The request has no start (or end) the engine can use."""


class EngineQuestion(Exception):
    """The engine needs an answer before it builds (contract: the `question` event, `from: "engine"`). Carries the
    question as the phone sees it and its answer map, which stays on the server, as a parser question's does."""

    def __init__(self, question: dict, answer_map: dict):
        super().__init__(question["text"])
        self.question, self.answer_map = question, answer_map


def shortest_way_question(shortest_m: float) -> EngineQuestion:
    """'The shortest way there is 4.3 mi. Make it 4.3 mi?' (brief, step 8). Rule 3: never stretch quietly."""
    miles = ask_miles(shortest_m)
    shown = f"{miles:g}"
    q = {"id": "q_1", "about": "distance", "from": "engine",
         "text": render("question.engine.shortest", miles=shown),
         "options": [{"id": "a", "text": render("option.miles", miles=shown)}], "allow_text": True}
    return EngineQuestion(q, {"options": {"a": {"distance": miles}}, "typed": {"kind": "miles"}})


@dataclass(frozen=True)
class Start:
    lat: float
    lon: float
    label: str


def new_route_id() -> str:
    return f"r_{secrets.token_hex(4)}"


def start_for(rc: RunConstraints, location: dict | None, saved: dict, geocode_fn: Callable = geocode) -> Start:
    """Coordinates for the start: the phone's location, a place ref, a saved place from the profile, or (the CLI's
    way in) an address. Coordinates come from the server and the phone, never from Claude."""
    if rc.use_my_location:
        if not location:
            raise BadStart("use_my_location without a location")
        return Start(location["lat"], location["lon"], render("request.start.my_location"))
    if rc.start_place is not None:
        p = rc.start_place
        lat, lon = p.lat, p.lon
        if lat is None and p.kind == "saved" and p.id in saved:
            lat, lon = saved[p.id].get("lat"), saved[p.id].get("lon")
        if lat is None:
            raise BadStart(f"no coordinates for {p.kind} start")
        return Start(lat, lon, p.display())
    if rc.start_address:
        try:
            g = geocode_fn(rc.start_address)
        except GeocodeError as exc:
            raise BadStart(str(exc)) from exc
        return Start(g.lat, g.lon, g.label)
    raise BadStart("no start")


def via_far_question(vias, shortest_m: float) -> EngineQuestion:
    """'Going through Hudson River Greenway takes at least 3.9 mi. Make it 3.9 mi?' (brief, step 9; rule 3). With a
    lap (decision 035): 'A lap of the Reservoir running track and the way there takes at least 2.3 mi. ...'"""
    miles = ask_miles(shortest_m)
    shown = f"{miles:g}"
    key = "question.engine.lap_far" if any(v.lap is not None for v in vias) else "question.engine.via_far"
    q = {"id": "q_1", "about": "distance", "from": "engine",
         "text": render(key, name=" and ".join(v.name for v in vias), miles=shown),
         "options": [{"id": "a", "text": render("option.miles", miles=shown)}], "allow_text": True}
    return EngineQuestion(q, {"options": {"a": {"distance": miles}}, "typed": {"kind": "miles"}})


VIA_SHAPE_REACH_M = 3000  # a via's shape: the parts of the named place within this of the point the parse chose


def db_vias(refs) -> list[Via]:
    """Each via place with its shape from the places table: a park's or a lake's outline, a path's or a street's
    lines near the chosen point, or the point itself when the place has no shape there."""
    import json

    from api.places import lookup
    from etl.load import database_url

    out = []
    with psycopg.connect(database_url()) as conn:
        for r in refs:
            shape = {"type": "Point", "coordinates": [r.lon, r.lat]}
            name, lap = r.name, None
            found = lookup(r.name, near=(r.lat, r.lon), conn=conn)
            if found:
                row = conn.execute(
                    """SELECT ST_AsGeoJSON(ST_Collect(coalesce(outline, geom))) FROM places
                       WHERE id = ANY(%(ids)s) AND ST_DWithin(coalesce(outline, geom)::geography,
                             ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)::geography, %(reach)s)""",
                    {"ids": list(found[0].ids), "lon": r.lon, "lat": r.lat, "reach": VIA_SHAPE_REACH_M}).fetchone()
                if row and row[0]:
                    shape = json.loads(row[0])
            if getattr(r, "mode", "through") == "around":
                name, lap = lap_ring(conn, r, shape)
            out.append(Via(r.lat, r.lon, name, shape, lap))
    return out


def lap_ring(conn, ref, shape: dict) -> tuple[str, tuple | None]:
    """An around via's name and ring (decision 035): the curated loop from running_loops, or the outline of the
    place's biggest polygon, counterclockwise. No ring (a loop the table lacks, a place with no outline): None, and
    the via is passed instead."""
    import json

    from api.geometry import oriented

    if ref.loop:
        row = conn.execute("SELECT name, ST_AsGeoJSON(geom) FROM running_loops WHERE id = %s AND geom IS NOT NULL",
                           (ref.loop,)).fetchone()
        if row is None:
            return ref.name, None
        return row[0], tuple(tuple(c) for c in json.loads(row[1])["coordinates"])
    polys = ([shape["coordinates"]] if shape["type"] == "Polygon" else
             shape["coordinates"] if shape["type"] == "MultiPolygon" else [])
    if not polys:
        return ref.name, None
    from shapely.geometry import Polygon
    biggest = max(polys, key=lambda rings: Polygon(rings[0]).area)[0]
    return ref.name, tuple(tuple(c[:2]) for c in oriented(biggest, "counterclockwise"))


def end_for(rc: RunConstraints, saved: dict) -> tuple[float, float] | None:
    """The end's coordinates, for an A-to-B run (step 8): a place ref, or a saved place from the profile."""
    p = rc.end_place
    if p is None:
        return None
    lat, lon = p.lat, p.lon
    if lat is None and p.kind == "saved" and p.id in saved:
        lat, lon = saved[p.id].get("lat"), saved[p.id].get("lon")
    if lat is None:
        raise BadStart(f"no coordinates for {p.kind} end")
    return lat, lon


def before_build(rc: RunConstraints, zones=None) -> tuple[list[dict], bool]:
    """Can't-do lines for what the engine can't build yet, and whether that blocks the build. An avoid that isn't on
    the no-go list is named too: the route is built, but not around it (rule 3: never quietly)."""
    lines = []
    later = unsupported(rc)
    for key in later:
        lines.append({"gap": "later", "key": key, "text": render(f"cant.later.{key}")})
    _, unknown = resolve_zones([a.name for a in rc.avoid_places if a.how == "area" and a.place is None], zones)
    for name in unknown:
        lines.append({"gap": "avoid_unknown", "key": "avoid_unknown", "text": render("cant.avoid_unknown", name=name)})
    return lines, any(k in BLOCKING for k in later)


def entry(rank: int, c: Candidate, route_key: str | None = None) -> dict:
    """One route of the top 3 as the fixture's `top3` holds it: outline, label, score and the measured distance, plus
    `id`, the same for the same route in every event of one build, so the app can tell a route that moved up from a
    new one."""
    return {"id": route_key, "rank": rank, "kind": c.kind, "label": display_name(c.kind, c.label), "score": round(c.score),
            "distance": route_summary(c, [], [], {})["distance"],
            "geometry": {"type": "LineString", "coordinates": c.route.coordinates}}


AREA_DEPTH_M = 300  # an end in a neighborhood: this far inside it


def db_area(point: tuple[float, float]) -> tuple[dict, dict] | None:
    """A neighborhood's area (the 2020 NTA holding its point) and that area AREA_DEPTH_M inside its edge, as GeoJSON;
    None when there's no area for it."""
    import json

    from etl.load import database_url
    with psycopg.connect(database_url()) as conn:
        if not conn.execute("SELECT to_regclass('neighborhood_areas') IS NOT NULL").fetchone()[0]:
            return None
        row = conn.execute(
            """SELECT ST_AsGeoJSON(geom), ST_AsGeoJSON(ST_Transform(coalesce(
                        nullif(ST_Buffer(ST_Transform(geom, 2263), -%(depth)s), 'POLYGON EMPTY'::geometry),
                        ST_Transform(geom, 2263)), 4326))
               FROM neighborhood_areas WHERE ST_Intersects(geom, ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326))
               LIMIT 1""", {"lat": point[0], "lon": point[1], "depth": AREA_DEPTH_M * 3.28084}).fetchone()
    return (json.loads(row[0]), json.loads(row[1])) if row else None


def area_end(start: tuple[float, float], point: tuple[float, float], area: tuple[dict, dict],
             route_fn: Callable) -> tuple[float, float]:
    """Where a run to a neighborhood finishes: on the shortest way toward its point, the first place that is
    AREA_DEPTH_M inside the area. The way in decides, not the nearest edge as the crow flies (Williamsburg's is on
    the north side; the way from Manhattan comes over the bridge from the south). The point itself when the run starts
    inside the area, or the way never gets that far in."""
    from shapely.geometry import Point, shape
    whole, inner = (shape(g) for g in area)
    if whole.contains(Point(start[1], start[0])):
        return point
    try:
        way = route_fn([start, point])
    except RoutingError:
        return point
    for lon, lat, *_ in way.coordinates:
        if inner.contains(Point(lon, lat)):
            return lat, lon
    return point


def db_past_route(route_id: str):
    """A past route's line from saved_routes (step 11)."""
    from api.past_routes import load
    from api.saved_routes import PgRouteStore
    return load(route_id, PgRouteStore())


PAST_ROUTE_SHARE = 0.9  # a rebuilt route runs along this much of the one they ran (the lap rule, decision 035)
PIER_RADIUS_M = 120.0  # "skip the ferry part": a circle this size around each landing is a no-go zone for the request;
# the landing point is out on the pier, about 55 m from the esplanade, so 120 m takes the stretch beside it
SKIP_MARGIN_M = 40.0  # and the past route's waypoints and coverage leave out this much more around it


def past_route_via(past, reverse: bool, spots=()) -> tuple[Start, tuple[float, float] | None, Via]:
    """The run's start and end and a lap along the past route: a loop or out-and-back is a closed lap from its
    start; a run that ended elsewhere is an open one, to its end. Reversed for 'the other direction'."""
    from api.past_routes import is_closed
    coords = [list(c[:2]) for c in (reversed(past.coords) if reverse else past.coords)]
    start = Start(coords[0][1], coords[0][0], render("request.start.past_route"))
    closed = is_closed(coords)
    if closed:
        coords[-1] = coords[0]
    line = {"type": "LineString", "coordinates": coords}
    skip = tuple((sum(p[1] for p in z.rings[0][:-1]) / (len(z.rings[0]) - 1),
                  sum(p[0] for p in z.rings[0][:-1]) / (len(z.rings[0]) - 1), PIER_RADIUS_M + SKIP_MARGIN_M)
                 for z in spots)  # the part of the route by an avoided spot isn't run (H04: the ferry part)
    via = Via(start.lat, start.lon, render("route.past"), line, tuple(tuple(c) for c in coords), closed=closed,
              phrase=render("route.past.along"), skip=skip)
    return start, None if closed else (coords[-1][1], coords[-1][0]), via


def place_zone(avoid, i: int) -> NoGoZone:
    """An avoid with coordinates (a ferry landing, step 11) as a no-go zone for this request: a circle around it."""
    p = avoid.place
    kx = 111_320 * math.cos(math.radians(p.lat))
    ring = [[p.lon + PIER_RADIUS_M * math.cos(a) / kx, p.lat + PIER_RADIUS_M * math.sin(a) / 110_574]
            for a in (2 * math.pi * k / 16 for k in range(16))]
    return NoGoZone(id=f"avoid_{i}", name=avoid.name, aliases=(), default=False, reason="the runner's avoid",
                    source=p.source or "request", rings=[ring + [ring[0]]])


def db_alongs_near(names: list[str], near: tuple[float, float]):
    """The streets and stretches not to run along, from the places table near the start (step 8b)."""
    from api.along import db_alongs
    from etl.load import database_url

    with psycopg.connect(database_url()) as conn:
        return db_alongs(names, near, conn)


def along_notes(lost: list[str]) -> list[dict]:
    """Rule 3: a street Loop couldn't find near the start isn't avoided, and the runner is told."""
    return [{"id": f"n_a{i}", "key": "avoid_not_found", "trust": "listed",
             "text": render("note.avoid_not_found", name=name)} for i, name in enumerate(lost, 1)]


def distance_notes(rc: RunConstraints, chosen: list[Candidate], within: bool) -> list[dict]:
    """Rule 3: a miss is said, with the nearest route and how far off it is."""
    if not chosen:
        return [{"id": "n_r1", "key": "no_route", "trust": "measured", "text": render("note.no_route")}]
    if within or rc.distance_mi is None:
        return []
    c = chosen[0]  # the miss is measured on the router's distance, so the note is too
    direction = "short" if c.miss_pct < 0 else "long"
    tolerance = rc.tolerance_pct if rc.tolerance_pct is not None else TOLERANCE_PCT
    return [{"id": "n_r1", "key": "distance_off", "trust": "measured",
             "text": render(f"note.distance_off.{direction}", tolerance=f"{tolerance:g}", miles=f"{rc.distance_mi:g}",
                            actual=f"{c.route.distance_m / METERS_PER_MILE:.1f}",
                            pct=f"{abs(c.miss_pct):.0f}")}]


def _straight_m(a: tuple[float, float], b: tuple[float, float] | None) -> float:
    if b is None:
        return 0.0
    kx = 111_320 * math.cos(math.radians(a[0]))
    return math.hypot((b[1] - a[1]) * kx, (b[0] - a[0]) * 110_574)


def graphhopper_ready(timeout_s: float = 1.0) -> bool:
    try:
        return httpx.get(f"{graphhopper_url()}/health", timeout=timeout_s).status_code == 200
    except httpx.HTTPError:
        return False


@dataclass
class Engine:
    """The real build. Tests swap the functions for fakes."""
    generate_fn: Callable = generate_loops
    a_to_b_fn: Callable = generate_a_to_b
    grid_fn: Callable = ml.current_grid
    closures_fn: Callable | None = ml.db_closures
    stretch_fn: Callable | None = ml.db_stretches
    anchor_fn: Callable | None = ml.familiar_anchors
    feature_anchor_fn: object = None
    use_prior: bool = True
    ready_fn: Callable[[], bool] = graphhopper_ready
    routers_fn: Callable = ml.routers_for  # (zones, lights, closures) -> route, round-trip and area routers
    vias_fn: Callable = db_vias  # via PlaceRefs -> [Via] with their shapes
    alongs_fn: Callable = None  # (names, (lat, lon)) -> ([along.Along], names not found); default db_alongs_near
    context_for_fn: Callable = ml.context_for  # (lights, grid, use_prior=, start=) -> a route scorer (Postgres)
    past_route_fn: Callable = None  # route id -> past_routes.PastRoute | None; default saved_routes (step 11)
    pools: dict = None  # route id -> every candidate that passed, for the last POOLS_KEPT builds (shape edits)
    area_fn: Callable = None  # a neighborhood's point -> (its area, the area AREA_DEPTH_M inside), GeoJSON; db_area

    def remember_pool(self, route_id: str, candidates: list) -> None:
        with _POOLS_LOCK:
            if self.pools is None:
                self.pools = {}
            self.pools[route_id] = candidates
            while len(self.pools) > POOLS_KEPT:
                self.pools.pop(next(iter(self.pools)))

    def from_pool(self, rc: RunConstraints, start: Start, old_route_id: str, send: Callable[[dict], None],
                  route_id: str) -> dict | None:
        """A shape-only edit: the best routes of the new kind from an earlier build's candidates, with no routing
        (phone test, 2026-11-10). None when that build is gone or none of its routes is of the new kind within the
        distance limit; the caller then builds as usual."""
        from api.generate import select_from_pool
        t0 = time.perf_counter()
        with _POOLS_LOCK:
            pool = (self.pools or {}).get(old_route_id)
        if not pool or rc.distance_mi is None:
            return None
        chosen, best_of = select_from_pool(pool, TOP_N, rc.shape)
        if not chosen:
            return None
        keys = {id(c): f"{route_id}.{i}" for i, c in enumerate(chosen, 1)}
        routes = [entry(r, c, keys[id(c)]) for r, c in enumerate(chosen, 1)]
        send({"event": "top3", "v": 1, "route_id": route_id, "elapsed_s": round(time.perf_counter() - t0, 3),
              "provisional": False, "routes": routes})
        route = ml.route_file(chosen[0], 1, start.lat, start.lon, start.label, rc.distance_mi, rc, best_of,
                              self.stretch_fn)
        self.remember_pool(route_id, pool)  # another edit can start from this one
        return {"event": "final", "v": 1, "route_id": route_id, "elapsed_s": round(time.perf_counter() - t0, 3),
                "provisional": False, "routes": routes, "route": route, "pool_size": best_of,
                "pool": {"candidates": len(pool), "best_of": best_of},
                "notes": distance_notes(rc, chosen, chosen[0].within_tolerance),
                "timing": {"from_pool": old_route_id}}

    def run_again(self, rc: RunConstraints, past, route_id: str) -> dict:
        """"Run again" (decision 043): the stored route's own line, exactly, scored for now (crowds for this start
        time, today's closures noted by the scorer). No routing, so the geometry can't change. The `final` payload,
        with that one route."""
        from api.generate import SHAPE_KINDS, Rejection, _evaluate, _Rules
        from api.past_routes import is_closed
        from api.routing import Route
        t0 = time.perf_counter()
        coords = [list(c[:2]) for c in past.coords]
        start = Start(coords[0][1], coords[0][0], render("request.start.past_route"))
        prefs = resolve_preferences(rc).values
        try:
            grid = self.grid_fn(start.lat, start.lon)
        except psycopg.Error as exc:
            raise EngineUnavailable(f"Postgres: {exc.__class__.__name__}") from exc
        context_fn = self.context_for_fn(prefs["lights"], grid, use_prior=self.use_prior, start=rc.start_moment())
        route = Route(distance_m=line_length_m(coords), time_s=0.0, coordinates=coords)
        rules = _Rules(meters_to_miles(route.distance_m), prefs, (), context_fn, spurs_ok=True)  # exactly as run
        label = past.label or render("route.past")
        c = None  # what it is: a loop or out-and-back by its shape, else a run that ends elsewhere
        for kind in ((None, "out_and_back", "a_to_b") if is_closed(coords) else ("a_to_b",)):
            got = _evaluate("run_again", kind, label, route, rules, allowed=SHAPE_KINDS["any"])
            if not isinstance(got, Rejection):
                c = got
                break
        if c is None:  # a line no shape rule accepts (a ribbon): scored as a run that ends where it ends
            c = _evaluate("run_again", "a_to_b", label, route, rules, allowed=())
        if isinstance(c, Rejection):
            raise EngineUnavailable(f"can't score the stored route: {c.reason}")
        miles = round(meters_to_miles(route.distance_m), 2)
        entry_ = entry(1, c, f"{route_id}.1")
        return {"event": "final", "v": 1, "route_id": route_id, "elapsed_s": round(time.perf_counter() - t0, 3),
                "provisional": False, "routes": [entry_],
                "route": ml.route_file(c, 1, start.lat, start.lon, start.label, miles, rc, None, self.stretch_fn),
                "pool_size": None, "pool": {"candidates": 1, "best_of": None}, "notes": [],
                "timing": {"run_again": past.id}}

    def __post_init__(self):
        if self.feature_anchor_fn is None:
            self.feature_anchor_fn = ml.DB_FEATURE_ANCHOR_SOURCES

    def build(self, rc: RunConstraints, start: Start, send: Callable[[dict], None], route_id: str,
              end: tuple[float, float] | None = None) -> dict:
        """Stream `candidates`, `top3` and `provisional` through `send`, then return the `final` payload (not sent
        here). With an end (step 8), the shortest way is checked first: a distance that can't reach the end raises
        EngineQuestion before anything streams; no distance means the shortest way."""
        if not self.ready_fn():
            raise EngineUnavailable("GraphHopper isn't answering")
        t0 = time.perf_counter()
        prefs = resolve_preferences(rc).values
        zones, _ = resolve_zones([a.name for a in rc.avoid_places if a.how == "area" and a.place is None])
        zones += [place_zone(a, i) for i, a in enumerate(rc.avoid_places, 1)
                  if a.how == "area" and a.place is not None and a.place.lat is not None]  # step 11: a ferry pier
        miles = rc.distance_mi
        past_via = None
        if rc.reuse_route_id:  # step 11: the route they ran, rebuilt for now (decision 038)
            past = (self.past_route_fn or db_past_route)(rc.reuse_route_id)
            if past is None:
                return {"event": "final", "v": 1, "route_id": route_id, "elapsed_s": round(time.perf_counter() - t0, 3),
                        "provisional": False, "routes": [], "route": None, "pool_size": None,
                        "pool": {"candidates": 0, "best_of": None}, "timing": {},
                        "notes": [{"id": "n_p1", "key": "past_route_not_found", "trust": "listed",
                                   "text": render("note.past_route_not_found")}]}
            start, end, past_via = past_route_via(past, rc.reverse, [z for z in zones if z.id.startswith("avoid_")])
        try:
            grid = self.grid_fn(start.lat, start.lon)
            reach_mi = (miles if miles is not None else
                        meters_to_miles(line_length_m(past_via.lap)) if past_via is not None else
                        2 * meters_to_miles(_straight_m((start.lat, start.lon), end)))
            closures = self.closures_fn(start.lat, start.lon, reach_mi) if self.closures_fn else []
            if end is not None and self.closures_fn:  # and those near the end, once each
                closures = list({c.id: c for c in [*closures, *self.closures_fn(*end, reach_mi)]}.values())
        except psycopg.Error as exc:
            raise EngineUnavailable(f"Postgres: {exc.__class__.__name__}") from exc
        along_names = [a.name for a in rc.avoid_places if a.how == "along"]
        try:
            alongs, lost = (self.alongs_fn or db_alongs_near)(along_names, (start.lat, start.lon)) \
                if along_names else ([], [])
        except psycopg.Error as exc:
            raise EngineUnavailable(f"Postgres: {exc.__class__.__name__}") from exc
        route_fn, round_trip_fn, area_fn = self.routers_fn(zones, prefs["lights"], closures,
                                                           **({"alongs": alongs} if alongs else {}))
        along_kw = {"along": alongs} if alongs else {}  # step 8b: crossing is fine, running along isn't
        if past_via is not None:  # decision 044: the route they ran keeps its spurs
            along_kw["spurs_ok"] = True
        if end is not None and rc.end_place is not None and rc.end_place.area == "neighborhood":
            try:  # "3 miles to Williamsburg": finish once the route is a few hundred meters inside it (decision 042)
                area = (self.area_fn or db_area)(end)
            except psycopg.Error as exc:
                raise EngineUnavailable(f"Postgres: {exc.__class__.__name__}") from exc
            if area is not None:
                end = area_end((start.lat, start.lon), end, area, route_fn)
        try:
            vias = self.vias_fn(rc.via_places) if rc.via_places else []
        except psycopg.Error as exc:
            raise EngineUnavailable(f"Postgres: {exc.__class__.__name__}") from exc
        if past_via is not None:
            vias = [past_via, *vias]
        through = through_rules(vias)
        here = (start.lat, start.lon)
        shortest = None
        if end is not None or vias:  # the shortest way there, or round through the vias, comes first (rule 3)
            try:
                shortest = route_fn(tour(here, vias, end))
            except RoutingError as exc:
                raise EngineUnavailable(f"GraphHopper: {exc}") from exc
            if shorter_than_the_shortest_way(miles, rc.tolerance_pct, shortest.distance_m):
                raise (via_far_question(vias, shortest.distance_m) if vias
                       else shortest_way_question(shortest.distance_m))
            if miles is None:
                miles = round(meters_to_miles(shortest.distance_m), 2)

        keys: dict[int, str] = {}  # candidate object -> its id in this build
        keys_lock = threading.Lock()

        def key(c: Candidate) -> str:
            with keys_lock:
                return keys.setdefault(id(c), f"{route_id}.{len(keys) + 1}")

        def on_top3(ev: dict) -> None:
            if ev["event"] in ("top3", "provisional"):  # "final" is sent below, with the #1 in full
                send({"event": ev["event"], "v": 1, "route_id": route_id, "elapsed_s": ev["elapsed_s"],
                      "provisional": ev["provisional"],
                      "routes": [entry(r, c, key(c)) for r, c in enumerate(ev["candidates"], 1)]})

        passed: list[Candidate] = []

        def on_candidate(c: Candidate, elapsed: float) -> None:  # every route that passes the rules, as it does
            passed.append(c)
            send({"event": "candidates", "v": 1, "route_id": route_id, "elapsed_s": round(elapsed, 3),
                  "candidates": [{"id": key(c), "kind": c.kind, "points": outline(c.route.coordinates)}]})

        context_fn = self.context_for_fn(prefs["lights"], grid, use_prior=self.use_prior, start=rc.start_moment())
        try:
            if end is not None:
                result = self.a_to_b_fn(
                    here, end, miles, grid, route_fn=route_fn, shortest=shortest, top_n=TOP_N,
                    prefs=prefs, avoid=zones, closures=closures, context_fn=context_fn, anchor_fn=self.anchor_fn,
                    feature_anchor_fn=self.feature_anchor_fn, area_route_fn=area_fn if self.feature_anchor_fn else None,
                    on_top3=on_top3, on_candidate=on_candidate, vias=tour(here, vias, end)[1:-1],
                    through=through, **along_kw)
            elif vias:  # through or along named places, back to the start (step 9)
                sources = self.feature_anchor_fn or []
                sources = list(sources) if isinstance(sources, (list, tuple)) else [sources]
                passed = [v for v in vias if v.lap is None]  # features anchor routes only on vias passed, not laps
                result = self.generate_fn(
                    start.lat, start.lon, miles, grid, route_fn=route_fn, round_trip_fn=round_trip_fn, top_n=TOP_N,
                    shape=rc.shape, prefs=prefs, avoid=zones, closures=closures, context_fn=context_fn,
                    anchor_fn=None, feature_anchor_fn=[features_on_vias(f, passed) for f in sources] if passed else [],
                    area_route_fn=area_fn if sources and passed else None, on_top3=on_top3, on_candidate=on_candidate,
                    only_anchored=True, extra_jobs=via_jobs(here, vias, miles, route_fn, shortest, rc.shape),
                    through=through, **along_kw)
            else:
                result = self.generate_fn(
                    start.lat, start.lon, miles, grid, route_fn=route_fn, round_trip_fn=round_trip_fn, top_n=TOP_N,
                    shape=rc.shape, prefs=prefs, avoid=zones, closures=closures, context_fn=context_fn,
                    anchor_fn=self.anchor_fn, feature_anchor_fn=self.feature_anchor_fn,
                    area_route_fn=area_fn if self.feature_anchor_fn else None, on_top3=on_top3,
                    on_candidate=on_candidate, **along_kw)
        except RoutingError as exc:
            raise EngineUnavailable(f"GraphHopper: {exc}") from exc
        except psycopg.Error as exc:
            raise EngineUnavailable(f"Postgres: {exc.__class__.__name__}") from exc
        chosen = result.candidates
        shape_notes = []
        if not chosen and rc.shape == "loop" and result.fallback:  # never a silent swap (decision 044)
            chosen = result.fallback
            kind = render(f"kind.{chosen[0].kind}")
            shape_notes = [{"id": "n_s1", "key": "no_good_loop", "trust": "measured",
                            "text": render("note.no_good_loop", kind=kind)}]
        if end is None:  # a shape edit can reuse these (not an A-to-B build: its kind doesn't change with shape)
            self.remember_pool(route_id, passed)
        route = (ml.route_file(chosen[0], 1, start.lat, start.lon, start.label, miles, rc, result.best_of,
                               self.stretch_fn) if chosen else None)
        return {"event": "final", "v": 1, "route_id": route_id,
                "elapsed_s": round(time.perf_counter() - t0, 3), "provisional": False,
                "routes": [entry(r, c, key(c)) for r, c in enumerate(chosen, 1)], "route": route,
                "pool_size": result.best_of, "pool": {"candidates": result.generated, "best_of": result.best_of},
                "notes": shape_notes + distance_notes(rc, chosen, bool(chosen) and chosen[0].within_tolerance)
                + along_notes(lost),
                "timing": result.timing}
