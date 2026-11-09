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
from api.geometry import outline
from api.a_to_b import ask_miles, generate_a_to_b, shorter_than_the_shortest_way
from api.units import meters_to_miles
from api.via import Via, features_on_vias, through_rules, tour, via_jobs
from api.nogo import resolve as resolve_zones
from api.routing import RoutingError, graphhopper_url
from api.scripts import make_loop as ml
from api.summary import METERS_PER_MILE, route_summary

# The engine can't build a request with these until a later step, so it builds nothing and says why (rule 3).
BLOCKING = ("avoid_along", "reuse_route_id")
# These leave a buildable run: hills aren't scored (step 9) and the second run isn't planned (step 10). The first run
# is built, with a can't-do line.
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
    """'Going through Hudson River Greenway takes at least 3.9 mi. Make it 3.9 mi?' (brief, step 9; rule 3)."""
    miles = ask_miles(shortest_m)
    shown = f"{miles:g}"
    q = {"id": "q_1", "about": "distance", "from": "engine",
         "text": render("question.engine.via_far", name=" and ".join(v.name for v in vias), miles=shown),
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
            found = lookup(r.name, near=(r.lat, r.lon), conn=conn)
            if found:
                row = conn.execute(
                    """SELECT ST_AsGeoJSON(ST_Collect(coalesce(outline, geom))) FROM places
                       WHERE id = ANY(%(ids)s) AND ST_DWithin(coalesce(outline, geom)::geography,
                             ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326)::geography, %(reach)s)""",
                    {"ids": list(found[0].ids), "lon": r.lon, "lat": r.lat, "reach": VIA_SHAPE_REACH_M}).fetchone()
                if row and row[0]:
                    shape = json.loads(row[0])
            out.append(Via(r.lat, r.lon, r.name, shape))
    return out


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
    _, unknown = resolve_zones([a.name for a in rc.avoid_places if a.how == "area"], zones)
    for name in unknown:
        lines.append({"gap": "avoid_unknown", "key": "avoid_unknown", "text": render("cant.avoid_unknown", name=name)})
    return lines, any(k in BLOCKING for k in later)


def entry(rank: int, c: Candidate, route_key: str | None = None) -> dict:
    """One route of the top 3 as the fixture's `top3` holds it: outline, label, score and the measured distance, plus
    `id`, the same for the same route in every event of one build, so the app can tell a route that moved up from a
    new one."""
    return {"id": route_key, "rank": rank, "kind": c.kind, "label": c.label, "score": round(c.score),
            "distance": route_summary(c, [], [], {})["distance"],
            "geometry": {"type": "LineString", "coordinates": c.route.coordinates}}


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
        zones, _ = resolve_zones([a.name for a in rc.avoid_places if a.how == "area"])
        miles = rc.distance_mi
        try:
            grid = self.grid_fn(start.lat, start.lon)
            reach_mi = miles if miles is not None else 2 * meters_to_miles(_straight_m((start.lat, start.lon), end))
            closures = self.closures_fn(start.lat, start.lon, reach_mi) if self.closures_fn else []
            if end is not None and self.closures_fn:  # and those near the end, once each
                closures = list({c.id: c for c in [*closures, *self.closures_fn(*end, reach_mi)]}.values())
        except psycopg.Error as exc:
            raise EngineUnavailable(f"Postgres: {exc.__class__.__name__}") from exc
        route_fn, round_trip_fn, area_fn = self.routers_fn(zones, prefs["lights"], closures)
        try:
            vias = self.vias_fn(rc.via_places) if rc.via_places else []
        except psycopg.Error as exc:
            raise EngineUnavailable(f"Postgres: {exc.__class__.__name__}") from exc
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

        def on_candidate(c: Candidate, elapsed: float) -> None:  # every route that passes the rules, as it does
            send({"event": "candidates", "v": 1, "route_id": route_id, "elapsed_s": round(elapsed, 3),
                  "candidates": [{"id": key(c), "kind": c.kind, "points": outline(c.route.coordinates)}]})

        context_fn = ml.context_for(prefs["lights"], grid, use_prior=self.use_prior, start=rc.start_moment())
        try:
            if end is not None:
                result = self.a_to_b_fn(
                    here, end, miles, grid, route_fn=route_fn, shortest=shortest, top_n=TOP_N,
                    prefs=prefs, avoid=zones, closures=closures, context_fn=context_fn, anchor_fn=self.anchor_fn,
                    feature_anchor_fn=self.feature_anchor_fn, area_route_fn=area_fn if self.feature_anchor_fn else None,
                    on_top3=on_top3, on_candidate=on_candidate, vias=[v.point for v in vias], through=through)
            elif vias:  # through or along named places, back to the start (step 9)
                sources = self.feature_anchor_fn or []
                sources = list(sources) if isinstance(sources, (list, tuple)) else [sources]
                result = self.generate_fn(
                    start.lat, start.lon, miles, grid, route_fn=route_fn, round_trip_fn=round_trip_fn, top_n=TOP_N,
                    shape=rc.shape, prefs=prefs, avoid=zones, closures=closures, context_fn=context_fn,
                    anchor_fn=None, feature_anchor_fn=[features_on_vias(f, vias) for f in sources],
                    area_route_fn=area_fn if sources else None, on_top3=on_top3, on_candidate=on_candidate,
                    only_anchored=True, extra_jobs=via_jobs(here, vias, miles, route_fn, shortest, rc.shape),
                    through=through)
            else:
                result = self.generate_fn(
                    start.lat, start.lon, miles, grid, route_fn=route_fn, round_trip_fn=round_trip_fn, top_n=TOP_N,
                    shape=rc.shape, prefs=prefs, avoid=zones, closures=closures, context_fn=context_fn,
                    anchor_fn=self.anchor_fn, feature_anchor_fn=self.feature_anchor_fn,
                    area_route_fn=area_fn if self.feature_anchor_fn else None, on_top3=on_top3,
                    on_candidate=on_candidate)
        except RoutingError as exc:
            raise EngineUnavailable(f"GraphHopper: {exc}") from exc
        except psycopg.Error as exc:
            raise EngineUnavailable(f"Postgres: {exc.__class__.__name__}") from exc
        chosen = result.candidates
        route = (ml.route_file(chosen[0], 1, start.lat, start.lon, start.label, miles, rc, result.best_of,
                               self.stretch_fn) if chosen else None)
        return {"event": "final", "v": 1, "route_id": route_id,
                "elapsed_s": round(time.perf_counter() - t0, 3), "provisional": False,
                "routes": [entry(r, c, key(c)) for r, c in enumerate(chosen, 1)], "route": route,
                "pool_size": result.best_of, "pool": {"candidates": result.generated, "best_of": result.best_of},
                "notes": distance_notes(rc, chosen, result.within_tolerance),
                "timing": result.timing}
