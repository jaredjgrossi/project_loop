"""What a route passes through: park share, waterfront share, crossings and signals (decision 011).

The geometry is pure Python on [lon, lat] lines (tested on hand-made shapes); `fetch_context` reads only the
nearby features from PostGIS. All values are `measured` (straight from geometry and datasets), with these limits:
- park share uses NYC Parks Properties, which misses Hudson River Park and Governors Island (decision 004); the
  waterfront share, from the OSM coastline, covers them;
- crossings are OSM crosswalk ways the route walks along. A stretch run on a road centerline crosses streets without
  a crosswalk way, so those crossings are missed (decision 009).
"""

import json
import math
from dataclasses import dataclass

from api.geometry import point_in_ring

SAMPLE_M = 5.0
WATERFRONT_M = 60.0  # within this of the shoreline: the esplanade and greenways, not the next block inland
CROSSING_NEAR_M = 4.0
CROSSING_COVERED = 0.6  # share of a crosswalk's length the route must cover to have crossed it
RUNNABLE_PARK_TYPES = (  # Parks Properties typecategory values a run can meaningfully be "in" (decision 004)
    "Flagship Park", "Community Park", "Nature Area", "Parkway", "Waterfront Facility", "Neighborhood Park",
    "Managed Sites", "Historic House Park",
)


@dataclass(frozen=True)
class Crossing:
    way_id: int
    signals: bool
    coords: list


@dataclass(frozen=True)
class Context:
    parks: list  # each a list of GeoJSON rings
    shoreline: list  # each a [lon, lat] line
    crossings: list[Crossing]
    familiar: list | None = None  # lines of ways the runner has run 2+ times; None when there is no runner prior


@dataclass(frozen=True)
class ContextScores:
    park_pct: float
    waterfront_pct: float
    park_or_water_pct: float
    crossings_per_mile: float
    signals_per_mile: float
    familiar_pct: float | None  # None: no runs on file
    # Expected wait at lights for the runner's lights setting (decision 015). An estimate, reported but not scored.
    wait_s: float | None = None
    wait_signals: int | None = None
    wait_credited: int | None = None  # signals where a zig-zagger has a same-length alternative
    # Crowds (decision 016): shares of the route by estimated level, and the share with no crowd data.
    crowd_high_pct: float | None = None
    crowd_medium_pct: float | None = None
    crowd_low_pct: float | None = None
    crowd_not_scored_pct: float | None = None
    crowd_band: str | None = None
    crowd_reason: str | None = None  # why nothing was scored, when no stretch had a band
    crowd_start_band: str | None = None  # the band at the start; None: crowds not scored for any route in the request


class _Frame:
    def __init__(self, lat0: float):
        self.kx, self.ky = 111_320 * math.cos(math.radians(lat0)), 110_574

    def xy(self, c):
        return c[0] * self.kx, c[1] * self.ky


def _samples(coords, frame: _Frame, step: float = SAMPLE_M):
    pts = [frame.xy(c) for c in coords]
    out = [pts[0]]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) // step))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1)]
    return out


def _seg_dist(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def _in_parks(samples, parks, frame: _Frame) -> list[bool]:
    if not parks:
        return [False] * len(samples)
    polys = [[[frame.xy(c) for c in ring] for ring in rings] for rings in parks]
    boxes = [(min(x for x, _ in p[0]), min(y for _, y in p[0]), max(x for x, _ in p[0]), max(y for _, y in p[0])) for p in polys]

    def inside(x, y):
        for (x0, y0, x1, y1), rings in zip(boxes, polys):
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_ring(x, y, rings[0]) \
                    and not any(point_in_ring(x, y, h) for h in rings[1:]):
                return True
        return False

    return [inside(x, y) for x, y in samples]


def park_share(coords, parks) -> float:
    """Percent of the route inside any park polygon."""
    frame = _Frame(coords[0][1])
    samples = _samples(coords, frame)
    return 100 * sum(_in_parks(samples, parks, frame)) / len(samples)


class _SegmentIndex:
    """Line segments bucketed on a grid of `within`-sized cells, for 'is this point within `within` of a line?'."""

    def __init__(self, lines, frame: _Frame, within: float):
        self.within = within
        self.grid: dict[tuple[int, int], list] = {}
        for line in lines:
            pts = [frame.xy(c) for c in line]
            for a, b in zip(pts, pts[1:]):
                for gx in range(int(min(a[0], b[0]) // within) - 1, int(max(a[0], b[0]) // within) + 2):
                    for gy in range(int(min(a[1], b[1]) // within) - 1, int(max(a[1], b[1]) // within) + 2):
                        self.grid.setdefault((gx, gy), []).append((a, b))

    def near(self, p) -> bool:
        cell = (int(p[0] // self.within), int(p[1] // self.within))
        return any(_seg_dist(p, a, b) <= self.within for a, b in self.grid.get(cell, ()))


def _near_lines(samples, lines, frame: _Frame, within: float) -> list[bool]:
    index = _SegmentIndex(lines, frame, within)
    return [index.near(p) for p in samples]


def waterfront_share(coords, shoreline, within_m: float = WATERFRONT_M) -> float:
    """Percent of the route within `within_m` of the shoreline."""
    if not shoreline:
        return 0.0
    frame = _Frame(coords[0][1])
    samples = _samples(coords, frame)
    return 100 * sum(_near_lines(samples, shoreline, frame, within_m)) / len(samples)


FAMILIAR_NEAR_M = 8.0


def park_or_water_share(coords, parks, shoreline, within_m: float = WATERFRONT_M) -> float:
    """Percent of the route in a park or by the water (each stretch counted once)."""
    frame = _Frame(coords[0][1])
    samples = _samples(coords, frame)
    water = _near_lines(samples, shoreline, frame, within_m) if shoreline else [False] * len(samples)
    in_park = _in_parks(samples, parks, frame)
    return 100 * sum(w or p for w, p in zip(water, in_park)) / len(samples)


def shares(coords, parks, shoreline, within_m: float = WATERFRONT_M) -> tuple[float, float, float]:
    """(park_share, waterfront_share, park_or_water_share) from one set of samples: the same numbers as the three
    functions, without sampling the route and testing every park three times (decision 018)."""
    frame = _Frame(coords[0][1])
    samples = _samples(coords, frame)
    n = len(samples)
    water = _near_lines(samples, shoreline, frame, within_m) if shoreline else [False] * n
    in_park = _in_parks(samples, parks, frame)
    return (100 * sum(in_park) / n, 100 * sum(water) / n if shoreline else 0.0,
            100 * sum(w or p for w, p in zip(water, in_park)) / n)


CORRIDOR_NEAR_M = 15.0  # as the stretch labels (api/segments.py)
COMPOSITION = ("waterfront", "park", "path", "street")


def sample_classes(coords, parks, shoreline, corridors, within_m: float = WATERFRONT_M) -> tuple[list[str], list[float]]:
    """A class for every SAMPLE_M sample of the route, and its distance along the route (decision 020). The classes
    split the route without overlap, from the same samples and tests as `shares`:
    - waterfront: within `within_m` of the shoreline (so its share is exactly `waterfront_share`);
    - park: in a park and not by the water (waterfront + park is exactly `park_or_water_share`);
    - path: within CORRIDOR_NEAR_M of a catalog corridor (a lines list) and neither of those;
    - street: everything else, streets and their sidewalks, plazas and unnamed paths."""
    frame = _Frame(coords[0][1])
    samples = _samples(coords, frame)
    n = len(samples)
    water = _near_lines(samples, shoreline, frame, within_m) if shoreline else [False] * n
    in_park = _in_parks(samples, parks, frame)
    on_path = _near_lines(samples, corridors, frame, CORRIDOR_NEAR_M) if corridors else [False] * n
    classes = ["waterfront" if w else "park" if p else "path" if c else "street"
               for w, p, c in zip(water, in_park, on_path)]
    along = [0.0]
    for a, b in zip(samples, samples[1:]):
        along.append(along[-1] + math.dist(a, b))
    return classes, along


def composition_by_range(classes: list[str], along: list[float], bounds_m: list[float]) -> list[dict]:
    """Meters of each class in each range [bounds_m[i], bounds_m[i+1]) along the route; the last range runs to the
    end. Every sample stands for an equal share of the route, so the ranges add up to the route's shares exactly."""
    total = along[-1]
    per = total / len(classes) if classes else 0.0
    out = [{k: 0.0 for k in COMPOSITION} for _ in bounds_m]
    i = 0
    for cls, a in zip(classes, along):
        while i + 1 < len(bounds_m) and a >= bounds_m[i + 1]:
            i += 1
        out[i][cls] += per
    return out


def pieces_by_range(coords, classes: list[str], along: list[float], bounds_m: list[float]) -> list[dict]:
    """The route line cut wherever the class or the range changes (decision 023): each piece has one class
    (`kind`), the range it sits in, where it starts and ends along the route, and its line. A piece's `length_m`
    weighs every sample as `composition_by_range` does, so the pieces add up to the ranges' meters exactly. Each
    line runs from its first sample to the next piece's first sample, so neighbors join without a gap."""
    if not classes:
        return []
    frame = _Frame(coords[0][1])
    lonlat = [[x / frame.kx, y / frame.ky] for x, y in _samples(coords, frame)]
    per = along[-1] / len(classes)
    ranges, i = [], 0
    for a in along:
        while i + 1 < len(bounds_m) and a >= bounds_m[i + 1]:
            i += 1
        ranges.append(i)
    pieces, start = [], 0
    for k in range(1, len(classes) + 1):
        if k < len(classes) and (classes[k], ranges[k]) == (classes[start], ranges[start]):
            continue
        last = min(k, len(classes) - 1)  # the next piece's first sample, or the route's end
        line = lonlat[start:last + 1] if last > start else lonlat[max(0, start - 1):start + 1]
        pieces.append({"kind": classes[start], "range": ranges[start], "start_m": along[start],
                       "end_m": along[k] if k < len(classes) else along[-1], "length_m": (k - start) * per,
                       "coordinates": line})
        start = k
    return pieces


def any_cell(grid: dict, xy: list, size: float, pad: int = 0) -> bool:
    """Whether the grid (cells of `size`) has an entry in any cell under the points' bounding box, widened by `pad`
    cells. When it has none, no point there can be near anything in the grid, so the exact test can be skipped."""
    x0, x1 = int(min(x for x, _ in xy) // size) - pad, int(max(x for x, _ in xy) // size) + pad
    y0, y1 = int(min(y for _, y in xy) // size) - pad, int(max(y for _, y in xy) // size) + pad
    if (x1 - x0 + 1) * (y1 - y0 + 1) > len(grid):
        return any(x0 <= gx <= x1 and y0 <= gy <= y1 for gx, gy in grid)
    return any((gx, gy) in grid for gx in range(x0, x1 + 1) for gy in range(y0, y1 + 1))


def familiar_share(coords, familiar_lines) -> float:
    """Percent of the route on ways the runner has run before (within FAMILIAR_NEAR_M of them)."""
    if not familiar_lines:
        return 0.0
    frame = _Frame(coords[0][1])
    samples = _samples(coords, frame)
    return 100 * sum(_near_lines(samples, familiar_lines, frame, FAMILIAR_NEAR_M)) / len(samples)


def crossing_counts(coords, crossings: list[Crossing]) -> tuple[int, int]:
    """(crosswalks walked, of which signalized). A crosswalk counts when the route covers most of its length."""
    if not crossings:
        return 0, 0
    frame = _Frame(coords[0][1])
    route = _SegmentIndex([coords], frame, CROSSING_NEAR_M)
    count = signals = 0
    for c in crossings:
        # A crosswalk under no cell the route occupies can't be walked: skip sampling it (decision 018). One cell of
        # margin, so a sample that rounding puts just over a cell edge is still covered.
        if not any_cell(route.grid, [frame.xy(p) for p in c.coords], CROSSING_NEAR_M, pad=1):
            continue
        pts = _samples(c.coords, frame, step=1.0)
        near = [route.near(p) for p in pts]
        if sum(near) / len(near) >= CROSSING_COVERED:
            count += 1
            signals += c.signals
    return count, signals


PASS_GAP_M = 25.0  # route samples near one crosswalk this far apart along the route are separate crossings


def crossing_passes(coords, crossings: list[Crossing]) -> list[tuple[float, bool]]:
    """(meters along the route, signalized) for every crossing the route makes, in order (decision 020). A crosswalk
    walked twice, as on an out-and-back, is two crossings. Each pass counts when it covers CROSSING_COVERED of the
    crosswalk, the test `crossing_counts` applies to the whole route; a crosswalk that only the passes together cover
    is one crossing. So the count is never below `crossing_counts`, which counts each crosswalk once and stays the
    ranking's input."""
    if not crossings:
        return []
    frame = _Frame(coords[0][1])
    route = _SegmentIndex([coords], frame, CROSSING_NEAR_M)
    pts = _samples(coords, frame)
    along = [0.0]
    for a, b in zip(pts, pts[1:]):
        along.append(along[-1] + math.dist(a, b))
    cell = CROSSING_NEAR_M
    by_cell: dict[tuple[int, int], list[int]] = {}
    for k, (x, y) in enumerate(pts):
        by_cell.setdefault((int(x // cell), int(y // cell)), []).append(k)
    out = []
    for c in crossings:
        cxy = [frame.xy(p) for p in c.coords]
        if not any_cell(route.grid, cxy, CROSSING_NEAR_M, pad=1):  # as crossing_counts (decision 018)
            continue
        cpts = _samples(c.coords, frame, step=1.0)
        if sum(route.near(p) for p in cpts) / len(cpts) < CROSSING_COVERED:
            continue
        segs = list(zip(cxy, cxy[1:])) or [(cxy[0], cxy[0])]
        near = sorted({k for x, y in cpts for gx in range(int(x // cell) - 1, int(x // cell) + 2)
                       for gy in range(int(y // cell) - 1, int(y // cell) + 2) for k in by_cell.get((gx, gy), ())
                       if any(_seg_dist(pts[k], a, b) <= CROSSING_NEAR_M for a, b in segs)})
        groups: list[list[int]] = []
        for k in near:
            if groups and along[k] - along[groups[-1][-1]] <= PASS_GAP_M:
                groups[-1].append(k)
            else:
                groups.append([k])
        made = []
        for g in groups:
            lo, hi = max(0, g[0] - 1), min(len(pts) - 1, g[-1] + 1)
            part = list(zip(pts[lo:hi], pts[lo + 1:hi + 1]))
            if sum(any(_seg_dist(p, a, b) <= CROSSING_NEAR_M for a, b in part) for p in cpts) / len(cpts) >= CROSSING_COVERED:
                made.append(along[g[len(g) // 2]])
        if not made:
            mid = cpts[len(cpts) // 2]
            made = [along[min(range(len(pts)), key=lambda k: math.dist(pts[k], mid))]]
        out += [(a, c.signals) for a in made]
    return sorted(out)


# --- PostGIS --------------------------------------------------------------------------

_BBOX = "ST_Expand(ST_Envelope(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), 0.002)"


def fetch_context(conn, coords) -> Context:
    line = json.dumps({"type": "LineString", "coordinates": coords})
    parks = [json.loads(g)["coordinates"] for (g,) in conn.execute(
        f"SELECT ST_AsGeoJSON((ST_Dump(geom)).geom) FROM parks WHERE geom && {_BBOX} AND typecategory = ANY(%s)",
        (line, list(RUNNABLE_PARK_TYPES)),
    )]
    shore = [json.loads(g)["coordinates"] for (g,) in conn.execute(
        f"SELECT ST_AsGeoJSON(geom) FROM osm_coastline WHERE geom && {_BBOX}", (line,)
    )]
    crossings = [
        Crossing(way_id, bool(sig), json.loads(g)["coordinates"])
        for way_id, sig, g in conn.execute(
            f"""SELECT way_id, (tags->>'crossing' = 'traffic_signals' OR tags->>'crossing:signals' = 'yes'), ST_AsGeoJSON(geom)
                FROM osm_ways WHERE tags->>'footway' = 'crossing' AND geom && {_BBOX}""",
            (line,),
        )
    ]
    familiar = None
    if conn.execute("SELECT to_regclass('runner_prior') IS NOT NULL").fetchone()[0]:
        familiar = [json.loads(g)["coordinates"] for (g,) in conn.execute(
            f"""SELECT ST_AsGeoJSON(w.geom) FROM runner_prior p JOIN osm_ways w USING (way_id)
                WHERE p.runs >= 2 AND w.geom && {_BBOX}""",
            (line,),
        )]
    return Context(parks, shore, crossings, familiar)


def score_context(conn, coords, use_prior: bool = True, lights=None, grid=None, start=None) -> ContextScores:
    """use_prior=False leaves "matches routes you run" unscored, as if no runs were on file (the honest eval setting).
    With lights and grid (a GridEstimate), also estimates the wait at lights for that kind of runner (decision 015)."""
    ctx = fetch_context(conn, coords)
    if not use_prior:
        ctx = Context(ctx.parks, ctx.shoreline, ctx.crossings, None)
    frame = _Frame(coords[0][1])
    pts = [frame.xy(c) for c in coords]
    miles = sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) / 1609.344
    crossings, signals = crossing_counts(coords, ctx.crossings)
    park_pct, waterfront_pct, park_or_water_pct = shares(coords, ctx.parks, ctx.shoreline)
    return ContextScores(
        park_pct=park_pct,
        waterfront_pct=waterfront_pct,
        park_or_water_pct=park_or_water_pct,
        crossings_per_mile=crossings / miles,
        signals_per_mile=signals / miles,
        familiar_pct=None if ctx.familiar is None else familiar_share(coords, ctx.familiar),
        **_wait_fields(coords, ctx.crossings, lights, grid),
        **_crowd_fields(conn, coords, start),
    )


def _crowd_fields(conn, coords, start) -> dict:
    from api.crowds import band_for, route_crowds, summarize

    if start is None and conn.execute("SELECT to_regclass('sidewalk_crowd') IS NOT NULL").fetchone()[0]:
        # Without a start time every sample is not scored for the same reason, so the summary is known without
        # sampling the route (decision 018). Stretches still sample it, for each stretch's reason.
        band, reason = band_for(None)
        c = {**summarize([None]), "band": None, "reason": reason, "start_band": band}
    else:
        c = route_crowds(conn, coords, start)
    return {"crowd_high_pct": c["high_pct"], "crowd_medium_pct": c["medium_pct"], "crowd_low_pct": c["low_pct"],
            "crowd_not_scored_pct": c["not_scored_pct"], "crowd_band": c["band"],
            "crowd_reason": c["reason"], "crowd_start_band": c["start_band"]}


def _wait_fields(coords, crossings, lights, grid) -> dict:
    if lights is None or grid is None:
        return {}
    from api.grid import MIN_GRID_STRENGTH
    from api.lights import expected_wait

    w = expected_wait(coords, crossings, grid.angle_deg, grid.strength >= MIN_GRID_STRENGTH, lights)
    return {"wait_s": w["seconds"], "wait_signals": w["signals"], "wait_credited": w["credited"]}


ROADWAY_HIGHWAYS = ("primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link", "residential",
                    "unclassified", "living_street", "service", "road")
_ROADWAY = """
WITH s AS (
    SELECT ord, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
    FROM unnest(%(lons)s::float8[], %(lats)s::float8[]) WITH ORDINALITY AS u(lon, lat, ord)
)
SELECT count(*) FILTER (WHERE w.highway = ANY(%(roads)s)), count(w.highway)
FROM s LEFT JOIN LATERAL (
    SELECT highway FROM osm_ways w WHERE w.geom && ST_Expand(s.g, 0.0001)
      AND ST_DWithin(w.geom::geography, s.g::geography, 6) ORDER BY w.geom <-> s.g LIMIT 1) w ON true
"""


def roadway_share(conn, coords, step_m: float = 10.0) -> float | None:
    """Percent of the route whose nearest walkable way (within 6 m) is a road centerline rather than a sidewalk,
    path or crosswalk (decision 015). Measured. Routed geometry sits on the graph's ways, so the nearest way is the
    one walked. None when no sample has a way nearby."""
    frame = _Frame(coords[0][1])
    pts = _samples(coords, frame, step=step_m)
    lons = [x / frame.kx for x, _ in pts]
    lats = [y / frame.ky for _, y in pts]
    roads, known = conn.execute(_ROADWAY, {"lons": lons, "lats": lats, "roads": list(ROADWAY_HIGHWAYS)}).fetchone()
    return 100 * roads / known if known else None
