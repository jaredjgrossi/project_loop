"""Turn-by-turn steps for the Directions list (decision 054).

The maneuvers are GraphHopper's own turn signs for the foot route (asked for again, with `instructions: true`, for the
final routes only: api/routing.with_instructions); the street names are the route's labeled stretches (api/segments.py), the same names `summary.way` lists, so a path is named after itself and
a road's sidewalk or crossing keeps the road's name (decision 049). GraphHopper's own street names are left out on
purpose: for the foot profile they are blank on most sidewalks and crossings. Nothing here is written by the LLM.

Steps are the places where the runner has something to do, and they tile the route:
- a GraphHopper turn, or a change of street with no turn ("Continue onto X");
- the turnaround, taken from the turnaround marker (GraphHopper has only a U-turn there, or a left, a via and a right);
- a stretch under MIN_STEP_M is part of the step before (a crossing, a curb jog, a roundabout's exits);
- where such a stretch is folded away, the next turn is measured again from the line, so a jog with a turn on each
  side doesn't leave one bare "left"; a "continue" onto the street the runner is already on is not a step, nor is a
  bend inside the one path, park or corridor (a U-turn is); a real turn on a street the runner is already on keeps
  the turn and leaves the name out ("Turn left", never "onto" the street it is on);
- a GraphHopper turn the line doesn't make (under CONTINUE_DEG either side of it) is a "continue";
- a start stub under MIN_STEP_M (the door to the corner) joins the first street.
"""

import math
from bisect import bisect_right

from api.markers import _along, _xy

METERS_PER_MILE = 1609.344
MIN_STEP_M = 50
TURN_SNAP_M = 25  # a GraphHopper instruction this close to the turnaround is the turnaround's
STRETCH_SNAP_M = 30  # a change of street this close to a GraphHopper instruction is that instruction's
WINDOW_M = 25  # the heading before and after a turn is read over this much line
CONTINUE_DEG = 11.5  # a turn under this is no turn (GraphHopper's own threshold)
DISTANCE_SOURCE = "route geometry (GraphHopper)"
MANEUVER_SOURCE = "GraphHopper turn instructions (foot profile)"
SOURCE_BY_KIND = {
    "start": "route geometry: the start of the route",
    "gh": MANEUVER_SOURCE,
    "turn": "route geometry: the turnaround marker (where the route turns back on itself)",
    "stretch": "route geometry: the street changes here with no turn",
}
MEASURED_SOURCE = "route geometry: the turn measured from the line, after short steps were folded away"

# GraphHopper's turn signs: -3..3 sharp left to sharp right, +-7 keep left/right, +-8 and -98 U-turns. 4 (finish),
# 5 (via point) and anything else it adds are not steps; 6 (roundabout) is measured from the line.
SIGN_MANEUVER = {-3: "sharp_left", -2: "left", -1: "slight_left", 0: "continue", 1: "slight_right", 2: "right",
                 3: "sharp_right", -7: "slight_left", 7: "slight_right", -8: "u_turn", 8: "u_turn", -98: "u_turn"}
NOT_A_STEP = {4, 5}


def maneuver_from_angle(degrees: float) -> str:
    """The maneuver for a turn of this many degrees (right is positive), at GraphHopper's own thresholds."""
    a = abs(degrees)
    if a < CONTINUE_DEG:
        return "continue"
    side = "right" if degrees > 0 else "left"
    if a < 46:
        return f"slight_{side}"
    if a < 103:
        return side
    if a < 170:
        return f"sharp_{side}"
    return "u_turn"


class _Line:
    """The route on the flat meter grid the markers use."""

    def __init__(self, coords):
        self.coords, self.xy = coords, _xy(coords)
        self.along = _along(self.xy)
        self.length = self.along[-1]

    def _at(self, m):
        m = max(0.0, min(self.length, m))
        i = min(max(bisect_right(self.along, m) - 1, 0), len(self.along) - 2)
        span = (self.along[i + 1] - self.along[i]) or 1.0
        f = (m - self.along[i]) / span
        return i, f

    def xy_at(self, m):
        i, f = self._at(m)
        (ax, ay), (bx, by) = self.xy[i], self.xy[i + 1]
        return ax + (bx - ax) * f, ay + (by - ay) * f

    def lonlat_at(self, m):
        i, f = self._at(m)
        a, b = self.coords[i], self.coords[i + 1]
        return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f

    def turn_at(self, m, before_m=None) -> float:
        """Degrees turned (right positive) between the line arriving at `before_m` (default m) and leaving m."""
        end = m if before_m is None else before_m
        a, b = self.xy_at(end - WINDOW_M), self.xy_at(end)
        c, d = self.xy_at(m), self.xy_at(m + WINDOW_M)
        if math.dist(a, b) < 1 or math.dist(c, d) < 1:
            return 0.0
        into = math.degrees(math.atan2(b[0] - a[0], b[1] - a[1]))
        out = math.degrees(math.atan2(d[0] - c[0], d[1] - c[1]))
        return (out - into + 540) % 360 - 180


def _stretch_ranges(stretches: list[dict], length: float) -> list[tuple[float, float, dict]]:
    """(start, end, properties) of each stretch along the line: their lengths, stretched to the line's own."""
    props = [s["properties"] for s in stretches]
    total = sum(p.get("length_m", 0) for p in props)
    if not total:
        return []
    out, at = [], 0.0
    for p in props:
        end = at + p.get("length_m", 0) * length / total
        out.append((at, end, p))
        at = end
    return out


def _street_of(ranges, start: float, end: float) -> dict | None:
    """The stretch the step runs most."""
    best, best_m = None, 0.0
    for a, b, p in ranges:
        m = min(b, end) - max(a, start)
        if m > best_m + 1e-9:
            best, best_m = p, m
    return best


def _remeasure_next(bounds, i, gone) -> None:
    """A turn folded away: the next GraphHopper turn is measured again from the line, from where the folded one began."""
    if gone["kind"] == "gh" and i < len(bounds) and bounds[i]["kind"] == "gh":
        bounds[i]["geom"], bounds[i]["pre"] = True, gone["pre"] if gone["pre"] is not None else gone["m"]


def route_steps(coords: list[list[float]], instructions, stretches: list[dict], turn_along_m: list[float],
                total_m: int) -> list[dict] | None:
    """The steps of a route, or None when it has no instructions. `instructions` are GraphHopper's (sign, meters
    along the route) in order; `turn_along_m` are the turnaround markers' distances along the route; `total_m` is the
    distance the summary shows, which the steps' meters add up to."""
    if not instructions or len(coords) < 2:
        return None
    line = _Line(coords)
    if line.length <= 0:
        return None
    scale = total_m / line.length
    ranges = _stretch_ranges(stretches, line.length)

    bounds: list[dict] = [{"m": 0.0, "kind": "start", "maneuver": "start", "geom": False, "pre": None}]
    for sign, along_m in instructions:
        m = float(along_m)
        if sign in NOT_A_STEP or m <= 0 or m >= line.length - 1:
            continue
        bounds.append({"m": m, "kind": "gh", "maneuver": SIGN_MANEUVER.get(sign), "geom": sign not in SIGN_MANEUVER,
                       "pre": None})
    for t in turn_along_m:
        if 0 < t < line.length:
            bounds = [b for b in bounds if b["kind"] == "start" or abs(b["m"] - t) > TURN_SNAP_M]
            bounds.append({"m": float(t), "kind": "turn", "maneuver": "turnaround", "geom": False, "pre": None})
    anchors = [b["m"] for b in bounds if b["kind"] != "start"]
    for (a1, b1, p1), (a2, b2, p2) in zip(ranges, ranges[1:]):
        if p1.get("name") != p2.get("name") and all(abs(a2 - m) > STRETCH_SNAP_M for m in anchors):
            bounds.append({"m": a2, "kind": "stretch", "maneuver": "continue", "geom": False, "pre": None})
    bounds.sort(key=lambda b: (b["m"], b["kind"] != "turn"))
    bounds = [b for i, b in enumerate(bounds) if i == 0 or b["m"] - bounds[i - 1]["m"] > 0.5 or b["kind"] == "turn"]

    def span(i):
        return (bounds[i + 1]["m"] if i + 1 < len(bounds) else line.length) - bounds[i]["m"]

    folding = True
    while folding:  # a stretch under the minimum is part of the step before it
        folding = False
        if span(0) < MIN_STEP_M and len(bounds) > 1 and bounds[1]["kind"] != "turn":
            jog = span(1) < MIN_STEP_M  # a turn with another close behind it is a jog; a long step after it isn't
            gone = bounds.pop(1)  # a stub from the door to the corner is part of the first street, not a step of its own
            if jog:
                _remeasure_next(bounds, 1, gone)
            folding = True
            continue
        for i in range(1, len(bounds)):
            if bounds[i]["kind"] != "turn" and span(i) < MIN_STEP_M:
                _remeasure_next(bounds, i, bounds.pop(i))
                folding = True
                break

    for b in bounds[1:]:  # turns read from the line: after a fold, or a sign GraphHopper has no word for here
        if b["geom"] or b["maneuver"] is None:
            b["maneuver"] = maneuver_from_angle(line.turn_at(b["m"], b["pre"]))
        elif b["kind"] == "gh" and b["maneuver"] != "continue" and abs(line.turn_at(b["m"])) < CONTINUE_DEG:
            b["maneuver"] = "continue"  # a sidewalk kink GraphHopper counts as a turn but the line doesn't make

    def street(i):
        return _street_of(ranges, bounds[i]["m"], bounds[i]["m"] + span(i))

    dropping = True
    while dropping:  # the same street twice is not a new step
        dropping = False
        for i in range(1, len(bounds)):
            b = bounds[i]
            if b["kind"] == "turn":
                continue
            here, before = street(i), street(i - 1)
            if not (here and before and here.get("name") and here.get("name") == before.get("name")):
                continue  # only when both names are known and the same
            if b["maneuver"] == "continue" or ((here or {}).get("kind") != "street" and b["maneuver"] != "u_turn"):
                bounds.pop(i)  # a "continue", or a bend in the one path, park or corridor the runner is on
                dropping = True
                break
            b["unnamed"] = True  # a real turn on a street, onto a name it already has: "Turn left", not "onto" it

    out = []
    at = [round(b["m"] * scale) for b in bounds] + [total_m]
    for i, b in enumerate(bounds):
        p = street(i)
        fact = ((p or {}).get("facts") or [{}])[0]
        lon, lat = line.lonlat_at(b["m"])
        how = MEASURED_SOURCE if b["geom"] and b["kind"] == "gh" else SOURCE_BY_KIND[b["kind"]]
        out.append(_step(i, b["maneuver"], None if b.get("unnamed") else (p or {}).get("name"), at[i], at[i + 1], lat,
                         lon, fact, how))
    lon, lat = coords[-1][0], coords[-1][1]
    out.append(_step(len(out), "finish", None, total_m, total_m, lat, lon, {}, "route geometry: the end of the route"))
    for s, nxt in zip(out, out[1:]):  # the miles shown tile as well as the meters
        s["distance"]["value"] = round(nxt["from_mile"] - s["from_mile"], 2)
    return out


def _step(index, maneuver, street, start_m, end_m, lat, lon, fact, how) -> dict:
    return {"index": index, "maneuver": maneuver, "street": street or None,
            "from_mile": round(start_m / METERS_PER_MILE, 2), "from_meters": start_m,
            "distance": {"value": 0.0, "unit": "mi", "meters": end_m - start_m, "status": "measured",
                         "source": DISTANCE_SOURCE},
            "point": {"lat": round(lat, 6), "lon": round(lon, 6)},
            "status": "measured", "maneuver_source": how,
            "trust": fact.get("trust", "listed") if street else "listed",
            "source": fact.get("source", DISTANCE_SOURCE) if street else DISTANCE_SOURCE}
