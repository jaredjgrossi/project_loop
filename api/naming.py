"""Route names from what a route is (phone test, 2026-11-11; decision 044).

A generator's label says how a route was made ("loop on Riverside Walk, heading 19 degrees" is the anchored-loop
job), not what came out: that job can return a route that is mostly retraced. The name shown to the runner (the
route card, its eyebrow, the route file, saved routes) starts from the kind measured on the geometry, and keeps only
the place from the label: "Out-and-back on Riverside Walk".
"""

import math
import re

from api.copy import render
from api.markers import point_along

_PLACE = re.compile(r"\b(on|through|along|with a lap of)\s+(.+?)(?:\s+and beyond)?(?:,|\s+to the end|\s+from the start|$)")


def display_name(kind: str, label: str) -> str:
    """'Out-and-back on Riverside Walk', 'Loop through Central Park', 'Loop on the street grid', 'One way'."""
    word = render(f"name.kind.{kind}")
    if label.startswith("rectangle"):  # a grid rectangle: corners on the street grid
        return render("name.on_the_grid", kind=word)
    m = _PLACE.search(label)
    if not m:
        return render("name.shortest", kind=word) if label.startswith("the shortest way") else word
    return render("name.with_place", kind=word, prep=m.group(1), place=m.group(2).strip())


MAIN_SHARE = 0.4  # a stretch that carries this much of the route names it


def main_stretch(stretches: list[dict]) -> dict | None:
    """The stretch (by name and kind) the route runs most, its pieces added up: {name, kind, length_m, share}. The
    stretches are the route file's stretch properties (api/segments.py)."""
    totals: dict[tuple[str, str], float] = {}
    for s in stretches:
        key = (s.get("name") or "", s.get("kind") or "")
        totals[key] = totals.get(key, 0.0) + s.get("length_m", 0)
    whole = sum(totals.values())
    if not whole:
        return None
    (name, kind), length = max(totals.items(), key=lambda kv: kv[1])
    return {"name": name, "kind": kind, "length_m": length, "share": length / whole}


def _has_a_real_name(name: str) -> bool:
    """Not "unnamed path", "waterfront path", or "waterfront path near E 23rd St": those say nothing."""
    return not name.startswith(("unnamed", "waterfront path"))


MAX_NAME = 36  # characters; the phone's route card (phone test 2026-11-13: "about 30")
SECOND_SHARE = 0.15  # a second named stretch this big joins the first in a loop's name
FAR_MIN_M = 300  # a far point closer than this to the start gives no direction to head in
CROSS_RADIUS_M = 80

_ABBREVIATIONS = (("Street", "St"), ("Avenue", "Ave"), ("Boulevard", "Blvd"), ("Road", "Rd"), ("Place", "Pl"))
_COMPASS = ("north", "east", "south", "west")


def short(name: str) -> str:
    """"East 30th Street" -> "E 30th St"; a name that has no direction word or street type stays as it is."""
    for long, abbr in _ABBREVIATIONS:
        name = re.sub(rf"\b{long}\b", abbr, name)
    return re.sub(r"^(East|West|North|South) (?=\d)", lambda m: m.group(1)[0] + " ", name)


def cross_label(name: str) -> str:
    """The street a runner turns around at, as they say it: "East 34th Street" -> "34th", "1st Avenue" -> "1st Ave",
    "Canal Street" -> "Canal"."""
    name = re.sub(r"^(East|West|North|South) (?=\d)", "", name)
    if re.match(r"\d", name) and name.endswith(("Avenue", "Ave")):
        return short(name)
    return re.sub(r"\s+(Street|St|Avenue|Ave|Place|Pl|Road|Rd|Boulevard|Blvd)$", "", name)


def compass(bearing: float) -> str:
    """The four points, 45 degrees either side of each: Manhattan's avenues run 29 degrees off north and a runner
    still says north."""
    return _COMPASS[int(((bearing % 360) + 45) // 90) % 4]


def _xy(coords: list[list[float]]) -> list[tuple[float, float]]:
    lat0 = coords[0][1]
    kx = 111_320 * math.cos(math.radians(lat0))
    return [((c[0] - coords[0][0]) * kx, (c[1] - lat0) * 110_574) for c in coords]


def far_point(coords: list[list[float]]) -> tuple[int, float, float]:
    """(index, meters from the start, bearing from the start) of the point farthest from the start: the turnaround of
    an out-and-back, the end of a one-way run."""
    xy = _xy(coords)
    i = max(range(len(xy)), key=lambda k: math.hypot(*xy[k]))
    x, y = xy[i]
    return i, math.hypot(x, y), math.degrees(math.atan2(x, y)) % 360


def _along_m(coords: list[list[float]], i: int) -> float:
    xy = _xy(coords)
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(xy[:i], xy[1:i + 1]))


def clockwise(coords: list[list[float]]) -> bool:
    """Whether a loop runs clockwise (shoelace on the metric xy, x east and y north)."""
    xy = _xy(coords)
    area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(xy, xy[1:] + xy[:1]))
    return area < 0


def _label_place(label: str) -> str:
    """The place in a generator's label, for a route with no stretch to name it: "Street grid", "Waterfront"."""
    if label.startswith("rectangle"):
        return "Street grid"
    if label.startswith("the shortest way"):
        return "Shortest way"
    m = _PLACE.search(label)
    place = re.sub(r"^the ", "", m.group(2).strip()) if m else "Street run"
    return place[:1].upper() + place[1:]


def _fit(base: str, tails: list[str]) -> str:
    """"base, tail" with the most tail that fits in MAX_NAME (street words shortened first), else the base alone."""
    for tail in tails:
        for b in (base, short(base)):
            if len(f"{b}, {tail}") <= MAX_NAME:
                return f"{b}, {tail}"
    return base if len(base) <= MAX_NAME else short(base)[:MAX_NAME].rstrip()


def name_ladder(kind: str, label: str, coords: list[list[float]], stretches: list[dict], cross_fn=None,
                miles: float | None = None) -> list[str]:
    """Names for a route, most telling first (phone test 2026-11-13: "out-and-back on the waterfront, heading 175" is
    not a name). The main stretch a runner would know, then which way it heads and where it turns:
    "East River Esplanade, north to 34th". No route type (the app's eyebrow says it), no compass degrees, no
    generator words. A loop is named by its two main stretches, or its one and the way round ("Central Park,
    clockwise"). `cross_fn(lat, lon, exclude)` names the street at a point, or None. The later names tell routes
    apart: the same name with the distance. `settle_names` picks one per route so the three differ."""
    totals: dict[str, float] = {}
    kinds: dict[str, str] = {}
    for st in stretches:
        n = st.get("name") or ""
        if n and _has_a_real_name(n):
            totals[n] = totals.get(n, 0.0) + st.get("length_m", 0)
            kinds[n] = st.get("kind") or ""
    whole = sum(st.get("length_m", 0) for st in stretches) or 1
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    share = lambda n: totals[n] / whole  # noqa: E731
    top = None
    if ranked and share(ranked[0][0]) >= (SECOND_SHARE if kind == "loop" else MAIN_SHARE):
        top = ranked[0][0]
    elif kind != "loop":  # nothing carries it: the biggest path, corridor or park a runner would know, if it is some
        top = next((n for n, _ in ranked if kinds[n] != "street" and share(n) >= SECOND_SHARE), None)
    second = next((n for n, _ in ranked if n != top and share(n) >= SECOND_SHARE), None)
    base = top or _label_place(label)
    tails: list[str] = []
    if len(coords) > 1:
        i, far_m, bearing = far_point(coords)
        if kind == "loop":
            if top and second:  # a loop on the street grid: the two streets it runs most
                base = f"{short(top)} & {short(second)}"
            tails = ["clockwise" if clockwise(coords) else "counterclockwise"]
        elif far_m >= FAR_MIN_M:
            # which way it heads: from where it joins its main stretch (a start inland of the river runs "east" to get
            # there), not from the start
            entry = next((st for st in stretches if st.get("name") == top and "from_mile" in st), None)
            if entry is not None:
                x, y = point_along(coords, entry["from_mile"] * 1609.344)
                ex, ey = _xy([[x, y]] + [coords[i]])[1]
                if math.hypot(ex, ey) >= FAR_MIN_M:
                    bearing = math.degrees(math.atan2(ex, ey)) % 360
            elif i > 4:  # no stretch to start from: skip the way out to it, a quarter of the way to the far point
                x, y = point_along(coords, _along_m(coords, i) / 4)
                ex, ey = _xy([[x, y]] + [coords[i]])[1]
                if math.hypot(ex, ey) >= FAR_MIN_M:
                    bearing = math.degrees(math.atan2(ex, ey)) % 360
            heading = compass(bearing)
            cross = cross_fn(coords[i][1], coords[i][0], top or "") if cross_fn else None
            tails = ([f"{heading} to {cross_label(cross)}"] if cross else []) + [heading]
    first = _fit(base, tails) if tails else (base if len(base) <= MAX_NAME else short(base)[:MAX_NAME].rstrip())
    out = [first]
    if miles is not None:
        out.append(_fit(base, [f"{miles:.1f} mi"]))
    return [n[:1].upper() + n[1:] for n in dict.fromkeys(out)]


def settle_names(files: list[dict]) -> None:
    """One name for each route of a result, none the same as another's: each takes the first name of its ladder that no
    route before it took, else its first name with " (2)", " (3)". Writes `name` and `label`, and drops the ladder and
    the generator's `plan` from the files (the app shows neither)."""
    used: set[str] = set()
    for f in files:
        props = f["features"][0]["properties"]
        ladder = props.pop("name_ladder", None) or [props.get("name") or ""]
        props.pop("plan", None)
        pick = next((n for n in ladder if n not in used), None)
        if pick is None:
            stem, k = ladder[0][:MAX_NAME - 4].rstrip(), 2
            while f"{stem} ({k})" in used:
                k += 1
            pick = f"{stem} ({k})"
        used.add(pick)
        props["name"] = props["label"] = pick
