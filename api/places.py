"""Look up a named place in the places table (Phase 3, step 2; decision 026).

`lookup(name, near=None)` returns every place the name can mean: none, one, or several. The caller decides what to
do with several (rule R12: ask). Claude normalizes the runner's words ("penn" -> "Penn Station") before they get here;
this module never invents a place and never guesses between two.

How a name matches, in order:
- A crossing ("1st Ave & E 23rd St"): the two streets must cross. A street written with a direction (E 23rd St)
  matches only that side; without one (23rd St) it matches either.
- An exact name, alias, curated redirect ("West Side Highway" means the Hudson River Greenway beside it) or street
  base. A street without a direction matches both its East and West halves, which
  count as one street per borough ("42nd St" in Manhattan).
- Failing that, a name holding every word of the query ("Penn Station" -> "New York Penn Station").

Then places that are one place are joined: the same street in one borough, or same-name rows within
SAME_PLACE_M of each other (the Penn Station node, its area and the two subway stations under it). A name that ends
like a street ("86th St") keeps streets and paths only, so it doesn't also return the 86 St stations.

`near` is a point (lat, lon) or a PlaceMatch. A point sorts the matches by distance; `near_m` drops those farther
than that (off by default: decision 005, ask). A PlaceMatch with an area means "at": only places touching it are
kept, and a street that touches it in several spots is one match per spot, labeled by the crossing street there
("86th St" at Central Park: 5th Ave, or Central Park West).

Every match is from the table, so trust is "listed" and the source is named.
"""

import math
import re
from dataclasses import dataclass, field

import psycopg

SAME_PLACE_M = 400  # same-name rows this close are one place (Penn Station's node, area and subway stations)
TOUCH_M = 75  # "at" an area: a place this close to its outline touches it
CONTACT_SPLIT_M = 300  # contact stretches this far apart are different spots ("86th St" at Central Park: two)
CROSSING_LABEL_M = 150  # the crossing street that labels a contact spot is within this distance
MAJOR_PARK_HA = 10  # "the park" (R13): a named OSM leisure=park at least this big (about 25 acres). Provisional.
MAJOR_PARK_RADIUS_M = 1609  # ... within about 1 mi of the start
# Smaller parks that also count as "the park" (Jared, 2026-11-06), as (name, borough).
MAJOR_PARK_ALSO = (("Battery Park", "Manhattan"),)
PICK_NEAREST_M = 3000  # R19 step 2: the nearest match wins when it is this close and every other match is farther
PARTIAL_LIMIT = 300
FT_PER_M = 3.28084

# Which row speaks for a group of rows that are one place.
KIND_PRIORITY = ("park", "water", "square", "plaza", "bridge", "station", "subway_station", "path", "corridor",
                 "street", "crossing", "tourism", "leisure", "amenity", "shop", "subway_entrance", "neighborhood")
LINE_KINDS = ("street", "path", "bridge")
# Kinds a partial name match keeps when any of them matched: a business or artwork that only shares words with a
# landmark is not what the runner meant.
LANDMARK_KINDS = ("park", "water", "square", "plaza", "bridge", "station", "subway_station", "path", "corridor",
                  "street")

_SUFFIX = {"street": "st", "st": "st", "avenue": "ave", "ave": "ave", "av": "ave", "boulevard": "blvd", "blvd": "blvd",
           "road": "rd", "rd": "rd", "place": "pl", "pl": "pl", "drive": "dr", "dr": "dr", "parkway": "pkwy",
           "pkwy": "pkwy", "lane": "ln", "ln": "ln", "terrace": "ter", "ter": "ter", "highway": "hwy", "hwy": "hwy",
           "expressway": "expy", "expy": "expy", "court": "ct", "ct": "ct", "square": "sq", "sq": "sq"}
_STREET_SUFFIXES = set(_SUFFIX.values()) - {"sq"}
_DIRS = {"east": "e", "e": "e", "west": "w", "w": "w", "north": "n", "n": "n", "south": "s", "s": "s"}
_WORD_ORDINALS = {"first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
                  "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "eleventh": "11th",
                  "twelfth": "12th"}
_DISPLAY_SUFFIX = {"Street": "St", "Avenue": "Ave", "Boulevard": "Blvd", "Road": "Rd", "Place": "Pl", "Drive": "Dr",
                   "Parkway": "Pkwy", "Lane": "Ln", "Terrace": "Ter", "Court": "Ct"}
_DISPLAY_DIR = {"East": "E", "West": "W", "North": "N", "South": "S"}


def _ordinal(n: str) -> str:
    k = int(n)
    suffix = "th" if 10 <= k % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th")
    return f"{n}{suffix}"


def normalize(name: str) -> str:
    """Lowercase words with street words shortened, so 'East 42nd Street' and 'E. 42nd St' compare equal."""
    s = re.sub(r"\([^)]*\)", " ", name.casefold())
    s = s.replace("'", "").replace("’", "").replace(".", "")
    s = re.sub(r"[–—\-/,&:;]", " ", s)
    tokens = s.split()
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    out = []
    for i, t in enumerate(tokens):
        t = _WORD_ORDINALS.get(t, t)
        t = _SUFFIX.get(t, _DIRS.get(t, t))
        nxt = _SUFFIX.get(tokens[i + 1]) if i + 1 < len(tokens) else None
        if t.isdigit() and nxt in _STREET_SUFFIXES:
            t = _ordinal(t)
        out.append(t)
    return " ".join(out)


_LIB_SYSTEMS = (("nypl", "new york public library"), ("bpl", "brooklyn public library"),
                ("qpl", "queens public library"))
_LIB_PREFIX = re.compile(r"^(?:nypl|new york public library|bpl|brooklyn public library|qpl|queens public library)"
                         r"\s*[:\-–—]?\s*(?:at\s+)?", re.I)
_LIB_SUFFIX = re.compile(r"\s*(?:branch library|public library|library|branch)\.?$", re.I)


def name_variants(name: str, kind: str | None, category: str | None) -> list[str]:
    """Other names people use for a library, station or park (phone test, 2026-11-09: "Kips Bay Library" is
    "NYPL: Kips Bay Library" in OSM). Stored as aliases by etl.load_places; normalize() is applied there.
    - a library: "X Library", "X Branch", "X Branch Library", and "NYPL X Branch" style names for its system;
    - a station: with and without "Station";
    - a park: with and without "Park" ("McCarren" is McCarren Park)."""
    out: list[str] = []
    if category == "amenity=library":
        system = next((s for s in _LIB_SYSTEMS if name.casefold().startswith(s)), None)
        core = _LIB_SUFFIX.sub("", _LIB_PREFIX.sub("", name.strip())).strip(" -–—:")
        if core:
            out += [f"{core} Library", f"{core} Branch", f"{core} Branch Library"]
            if system:
                out += [f"{system[0]} {core} Branch", f"{system[1]} {core} Branch", f"{system[1]} {core}"]
    elif kind in ("station", "subway_station"):
        out.append(name[: -len(" station")] if name.casefold().endswith(" station") else f"{name} Station")
    elif kind == "park" and (category or "").startswith("leisure=park"):
        if name.casefold().endswith(" park"):
            if len(name.split()) > 1:
                out.append(name[: -len(" park")])
        else:
            out.append(f"{name} Park")
    return [v for v in out if v.strip() and v.casefold() != name.casefold()]


def token_key(norm: str) -> str:
    """A normalized name's words in order, without "the": "library kips bay" and "the kips bay library" match."""
    return " ".join(sorted(w for w in norm.split() if w != "the"))


def street_base(norm: str) -> str:
    """A normalized street name without its leading direction: 'e 42nd st' -> '42nd st'. Kept when nothing but
    the suffix would be left ('s st' is South Street)."""
    tokens = norm.split()
    if len(tokens) >= 3 and tokens[0] in ("e", "w", "n", "s"):
        return " ".join(tokens[1:])
    return norm


def is_streetlike(norm: str) -> bool:
    return bool(norm) and norm.split()[-1] in _STREET_SUFFIXES


def display_name(name: str) -> str:
    """The short form a chip shows: 'East 42nd Street' -> 'E 42nd St', 'First Avenue' -> '1st Ave'."""
    words = name.split()
    if not words:
        return name
    if words[-1] in _DISPLAY_SUFFIX and len(words) >= 2:
        words[-1] = _DISPLAY_SUFFIX[words[-1]]
        ordinal = _WORD_ORDINALS.get(words[-2].casefold())
        if ordinal:
            words[-2] = ordinal
    if len(words) >= 3 and words[0] in _DISPLAY_DIR and words[1][:1].isdigit():
        words[0] = _DISPLAY_DIR[words[0]]
    return " ".join(words)


def split_crossing(name: str) -> tuple[str, str] | None:
    """'1st Ave & E 23rd St' -> ('1st ave', 'e 23rd st'); None when it isn't two names joined by & or 'and'."""
    parts = re.split(r"\s*&\s*|\s+and\s+", name.strip(), flags=re.IGNORECASE)
    if len(parts) != 2 or not all(p.strip() for p in parts):
        return None
    return normalize(parts[0]), normalize(parts[1])


def group_ids(ids: list[int], pairs: list[tuple[int, int]]) -> list[list[int]]:
    """Join ids linked by pairs, transitively. Groups come back sorted, in order of their smallest id."""
    parent = {i: i for i in ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in pairs:
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    groups: dict[int, list[int]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


@dataclass(frozen=True)
class PlaceMatch:
    name: str  # as a chip shows it ("E 42nd St", "New York Penn Station")
    kind: str
    borough: str
    lat: float
    lon: float
    matched: str  # the name or alias the query matched ("Central Park Reservoir")
    source: str
    ids: tuple[int, ...] = field(default=())  # places rows behind this match
    trust: str = "listed"
    distance_m: float | None = None  # from `near`, when near is a point
    at: str | None = None  # the crossing street at this spot, when near is an area ("5th Ave")
    area_ha: float | None = None


_ROW = """id, name, kind, borough, norm, base, aliases, alias_norms, ST_Y(geom), ST_X(geom), source, area_ha,
          outline IS NOT NULL AND GeometryType(outline) IN ('POLYGON', 'MULTIPOLYGON')"""


@dataclass
class _Row:
    id: int
    name: str
    kind: str
    borough: str
    norm: str
    base: str
    aliases: list
    alias_norms: list
    lat: float
    lon: float
    source: str
    area_ha: float | None
    has_area: bool


def _connect(conn):
    if conn is not None:
        return conn, False
    from etl.load import database_url
    return psycopg.connect(database_url()), True


def _crossing_rows(conn, a: str, b: str) -> list[_Row]:
    def matches(part, norms, bases):
        has_dir = part.split()[0] in ("e", "w", "n", "s") and len(part.split()) >= 3
        for n, base in zip(norms, bases):
            if part == n or (not has_dir and part == base):
                return True
            if not has_dir and not is_streetlike(part):  # "1st" for "1st ave", "23rd" for "e 23rd st"
                bt = base.split()
                if bt[:-1] == part.split() and bt[-1] in _STREET_SUFFIXES:
                    return True
        return False

    rows = conn.execute(
        f"""SELECT {_ROW}, street_norms, street_bases FROM places
            WHERE kind = 'crossing'
              AND EXISTS (SELECT 1 FROM unnest(street_bases) s WHERE split_part(s, ' ', 1) = %s)
              AND EXISTS (SELECT 1 FROM unnest(street_bases) s WHERE split_part(s, ' ', 1) = %s)""",
        (street_base(a).split()[0], street_base(b).split()[0])).fetchall()
    out = []
    for r in rows:
        norms, bases = r[-2], r[-1]
        for x, y in ((a, b), (b, a)):
            if matches(x, norms[:1], bases[:1]) and matches(y, norms[1:], bases[1:]):
                out.append(_Row(*r[:-2]))
                break
    return out


def _name_rows(conn, q: str) -> tuple[list[_Row], bool]:
    """Rows matching the normalized query exactly (name, alias or street base), else every row holding all its
    words. Returns the rows and whether the match was exact."""
    has_dir = street_base(q) != q
    rows = conn.execute(
        f"""SELECT {_ROW} FROM places WHERE kind <> 'crossing'
            AND (norm = %(q)s OR %(q)s = ANY(alias_norms) OR %(q)s = ANY(redirect_norms)
                 OR (NOT %(dir)s AND base = %(q)s))""",
        {"q": q, "dir": has_dir}).fetchall()
    if rows:
        return [_Row(*r) for r in rows], True
    words = [w for w in q.split() if w != "the"]
    if not words:
        return [], False
    pattern = " AND ".join(["(norm ~ %s OR array_to_string(alias_norms, ' | ') ~ %s)"] * len(words))
    rows = conn.execute(f"SELECT {_ROW} FROM places WHERE kind <> 'crossing' AND {pattern} LIMIT {PARTIAL_LIMIT}",
                        [p for w in words for p in (rf"\m{re.escape(w)}\M",) * 2]).fetchall()
    found = [_Row(*r) for r in rows]
    key = token_key(q)  # the same words in another order, or with "the": as good as exact (phone test, 2026-11-09)
    same = [r for r in found if token_key(r.norm) == key or any(token_key(a) == key for a in r.alias_norms or [])]
    return (same, True) if same else (found, False)


def _groups(conn, rows: list[_Row], q: str) -> list[list[_Row]]:
    by_id = {r.id: r for r in rows}
    ids = list(by_id)
    pairs = []
    if street_base(q) == q:  # no direction asked for: a street's East and West halves in one borough are one street
        lines: dict[tuple, list[int]] = {}
        for r in rows:
            if r.kind in LINE_KINDS:
                lines.setdefault((r.base, r.borough), []).append(r.id)
        pairs += [(g[0], i) for g in lines.values() for i in g[1:]]
    if len(ids) > 1:
        pairs += conn.execute(
            """SELECT a.id, b.id FROM places a JOIN places b ON a.id < b.id
               WHERE a.id = ANY(%(ids)s) AND b.id = ANY(%(ids)s)
                 AND ST_DWithin(ST_Transform(coalesce(a.outline, a.geom), 2263),
                                ST_Transform(coalesce(b.outline, b.geom), 2263), %(ft)s)""",
            {"ids": ids, "ft": SAME_PLACE_M * FT_PER_M}).fetchall()
    return [[by_id[i] for i in g] for g in group_ids(ids, pairs)]


def _rep(group: list[_Row]) -> _Row:
    return min(group, key=lambda r: (KIND_PRIORITY.index(r.kind) if r.kind in KIND_PRIORITY else 99,
                                     -(r.area_ha or 0), r.id))


def _matched(rep: _Row, q: str, query: str, exact: bool, group_name: str) -> str:
    """The name the runner's query matched: the place's own name, an alias ("Central Park Reservoir"), the street
    ("42nd St" for both halves), or, for a match holding all the query's words, the query itself ("Penn Station")."""
    if rep.norm == q:
        return rep.name
    for alias, n in zip(rep.aliases or [], rep.alias_norms or []):
        if n == q:
            return alias
    return group_name if exact else query.strip()


def _name(group: list[_Row], rep: _Row, q: str) -> str:
    if rep.kind == "crossing":
        return rep.name
    halves = {r.norm for r in group if r.kind in LINE_KINDS and r.base == rep.base}
    if rep.kind in LINE_KINDS and len(halves) > 1 and street_base(q) == q:
        words = rep.name.split()
        return display_name(" ".join(words[1:]) if words[0] in _DISPLAY_DIR else rep.name)
    return display_name(rep.name)


def _match(group, q, query: str = "", exact: bool = True, **kw) -> PlaceMatch:
    rep = _rep(group)
    name = _name(group, rep, q)
    base = dict(name=name, kind=rep.kind, borough=rep.borough, lat=rep.lat, lon=rep.lon,
                matched=_matched(rep, q, query, exact, name), source=rep.source, ids=tuple(r.id for r in group),
                area_ha=rep.area_ha)
    return PlaceMatch(**(base | kw))


def _near_point(conn, group, q, lat, lon, **kw) -> PlaceMatch:
    ids = [r.id for r in group]
    rep = _rep(group)
    plat, plon, dist = conn.execute(
        """WITH g AS (SELECT ST_Collect(coalesce(outline, geom)) g FROM places WHERE id = ANY(%(ids)s)),
                p AS (SELECT ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326) p)
           SELECT ST_Y(c), ST_X(c), ST_Distance(ST_Transform(g.g, 2263), ST_Transform(p.p, 2263)) / %(f)s
           FROM g, p, LATERAL (SELECT CASE WHEN %(line)s THEN ST_ClosestPoint(g.g, p.p)
                                           ELSE (SELECT geom FROM places WHERE id = %(rep)s) END c) x""",
        {"ids": ids, "lat": lat, "lon": lon, "f": FT_PER_M, "line": rep.kind in LINE_KINDS, "rep": rep.id}).fetchone()
    return _match(group, q, lat=plat, lon=plon, distance_m=round(dist, 1), **kw)


def _near_area(conn, group, q, area: PlaceMatch, **kw) -> list[PlaceMatch]:
    ids = [r.id for r in group]
    rep = _rep(group)
    params = {"ids": ids, "area": list(area.ids), "touch": TOUCH_M * FT_PER_M, "split": CONTACT_SPLIT_M * FT_PER_M,
              "label": CROSSING_LABEL_M * FT_PER_M}
    (touches,) = conn.execute(
        """SELECT ST_DWithin((SELECT ST_Transform(ST_Collect(coalesce(outline, geom)), 2263) FROM places WHERE id = ANY(%(ids)s)),
                             (SELECT ST_Transform(ST_Collect(coalesce(outline, geom)), 2263) FROM places WHERE id = ANY(%(area)s)),
                             %(touch)s)""", params).fetchone()
    if not touches:
        return []
    if rep.kind not in LINE_KINDS:
        return [_match(group, q, **kw)]
    spots = conn.execute(
        """WITH area AS (SELECT ST_Buffer(ST_Transform(ST_Collect(coalesce(outline, geom)), 2263), %(touch)s) g
                         FROM places WHERE id = ANY(%(area)s)),
                line AS (SELECT ST_Transform(ST_Collect(outline), 2263) g FROM places WHERE id = ANY(%(ids)s)),
                piece AS (SELECT (ST_Dump(ST_Intersection(line.g, area.g))).geom g FROM line, area),
                spot AS (SELECT g, ST_ClusterDBSCAN(g, eps := %(split)s, minpoints := 1) OVER () c FROM piece)
           SELECT ST_Transform(ST_ClosestPoint(ST_Collect(g), ST_Centroid(ST_Collect(g))), 4326) FROM spot GROUP BY c""",
        params).fetchall()
    names = [r.norm for r in group]
    out = []
    for (point,) in spots:
        label = conn.execute(
            """SELECT streets, street_norms FROM places
               WHERE kind = 'crossing' AND street_norms && %(names)s::text[]
                 AND ST_DWithin(ST_Transform(geom, 2263), ST_Transform(%(p)s::geometry, 2263), %(label)s)
               ORDER BY ST_Distance(geom, %(p)s::geometry) LIMIT 5""",
            params | {"names": names, "p": point}).fetchall()
        at = None
        for streets, norms in label:
            other = next(((s, n) for s, n in zip(streets, norms) if n not in names), None)
            # The street's own continuation ("86th Street Transverse" for 86th St) doesn't say which spot this is.
            if other and not street_base(other[1]).startswith(rep.base):
                at = display_name(other[0])
                break
        lat, lon = conn.execute("SELECT ST_Y(%(p)s::geometry), ST_X(%(p)s::geometry)", {"p": point}).fetchone()
        out.append(_match(group, q, lat=lat, lon=lon, at=at, **kw))
    return out


def lookup(name: str, near: tuple[float, float] | PlaceMatch | None = None, near_m: float | None = None,
           conn=None) -> list[PlaceMatch]:
    """Every place `name` can mean; see the module docstring."""
    conn, own = _connect(conn)
    try:
        q = normalize(name)
        rows: list[_Row] = []
        crossing = split_crossing(name)
        if crossing:
            rows = _crossing_rows(conn, *crossing)
        if not rows:
            rows, exact = _name_rows(conn, q)
            if exact and is_streetlike(q) and any(r.kind in LINE_KINDS for r in rows):
                rows = [r for r in rows if r.kind in LINE_KINDS]
            if not exact and any(r.kind in LANDMARK_KINDS for r in rows):  # "Penn Station", not "Penn Station Eagle"
                rows = [r for r in rows if r.kind in LANDMARK_KINDS]
        else:
            exact = True
        if not rows:
            return []
        groups = _groups(conn, rows, q)
        kw = {"query": name, "exact": exact}
        if isinstance(near, PlaceMatch):
            return [m for g in groups for m in _near_area(conn, g, q, near, **kw)]
        if near is not None:
            found = sorted((_near_point(conn, g, q, *near, **kw) for g in groups), key=lambda m: m.distance_m)
            return [m for m in found if near_m is None or m.distance_m <= near_m]
        found = [_match(g, q, **kw) for g in groups]
        return sorted(found, key=lambda m: (KIND_PRIORITY.index(m.kind) if m.kind in KIND_PRIORITY else 99, m.borough))
    finally:
        if own:
            conn.close()


def pick_by_borough(matches: list, ref_borough: str | None = None, nearest_m: float = PICK_NEAREST_M):
    """Rule R19 (decision 026): which of several matches the runner means, or None to ask. Works on anything with
    `.borough` and `.distance_m`: PlaceMatch, or a geocoded address.

    1. Prefer the match in the reference borough (the runner's current borough for a start today, the saved start's
       borough for a later day, the route's start borough for an end or via point).
    2. Otherwise, the nearest match within `nearest_m` when every other match is farther.
    3. Otherwise, None: ask.
    """
    if len(matches) == 1:
        return matches[0]
    if ref_borough is not None:
        mine = [m for m in matches if m.borough == ref_borough]
        if len(mine) == 1:
            return mine[0]
        if mine:
            matches = mine
    near = sorted((m for m in matches if m.distance_m is not None), key=lambda m: m.distance_m)
    if near and len(near) == len(matches) and near[0].distance_m <= nearest_m \
            and all(m.distance_m > nearest_m for m in near[1:]):
        return near[0]
    return None


def major_parks_near(lat: float, lon: float, radius_m: float = MAJOR_PARK_RADIUS_M, min_ha: float = MAJOR_PARK_HA,
                     conn=None) -> list[PlaceMatch]:
    """'The park' (R13): named parks of at least `min_ha`, or on MAJOR_PARK_ALSO, within `radius_m` of the point,
    nearest first."""
    conn, own = _connect(conn)
    try:
        rows = conn.execute(
            f"""WITH p AS (SELECT ST_Transform(ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326), 2263) p)
                SELECT DISTINCT ON (name) {_ROW}, ST_Distance(ST_Transform(outline, 2263), p.p) / %(f)s d
                FROM places, p
                WHERE kind = 'park' AND category = 'leisure=park'  -- not nature reserves: the Hudson's sanctuary is water
                  AND (area_ha >= %(ha)s OR (name, borough) IN (SELECT * FROM unnest(%(also_n)s::text[], %(also_b)s::text[])))
                  AND ST_DWithin(ST_Transform(outline, 2263), p.p, %(ft)s)
                ORDER BY name, d""",
            {"lat": lat, "lon": lon, "ha": min_ha, "ft": radius_m * FT_PER_M, "f": FT_PER_M,
             "also_n": [n for n, _ in MAJOR_PARK_ALSO], "also_b": [b for _, b in MAJOR_PARK_ALSO]}).fetchall()
        found = [PlaceMatch(name=r[1], kind=r[2], borough=r[3], lat=r[8], lon=r[9], matched=r[1], source=r[10],
                            ids=(r[0],), area_ha=r[11], distance_m=round(r[-1], 1)) for r in rows]
        return sorted(found, key=lambda m: m.distance_m)
    finally:
        if own:
            conn.close()


def borough_at(lat: float, lon: float, conn=None) -> str | None:
    """The borough holding the point, or None outside New York City."""
    conn, own = _connect(conn)
    try:
        row = conn.execute("SELECT name FROM boroughs WHERE ST_Intersects(geom, ST_SetSRID(ST_Point(%s, %s), 4326))",
                           (lon, lat)).fetchone()
        return row[0] if row else None
    finally:
        if own:
            conn.close()


NEIGHBORHOOD_M = 1200  # "kip bay 3 mi" from inside Kips Bay: the runner is this close to the neighborhood's point


def in_neighborhood(name: str, lat: float, lon: float, within_m: float = NEIGHBORHOOD_M, conn=None) -> bool:
    """Whether the point is in (near the OSM point of) the named neighborhood."""
    conn, own = _connect(conn)
    try:
        q = normalize(name)
        (hit,) = conn.execute(
            """SELECT EXISTS (SELECT 1 FROM places WHERE kind = 'neighborhood' AND (norm = %(q)s OR %(q)s = ANY(alias_norms))
                 AND ST_DWithin(ST_Transform(geom, 2263), ST_Transform(ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326), 2263),
                                %(ft)s))""",
            {"q": q, "lat": lat, "lon": lon, "ft": within_m * FT_PER_M}).fetchone()
        return hit
    finally:
        if own:
            conn.close()


def park_around(place: PlaceMatch, conn=None) -> PlaceMatch | None:
    """The park a place sits in (the Reservoir is in Central Park), largest first; None if it isn't in one."""
    conn, own = _connect(conn)
    try:
        row = conn.execute(
            f"""SELECT {_ROW} FROM places WHERE kind = 'park' AND name IS NOT NULL
                  AND ST_Intersects(outline, ST_SetSRID(ST_Point(%s, %s), 4326))
                ORDER BY area_ha DESC NULLS LAST LIMIT 1""", (place.lon, place.lat)).fetchone()
        if row is None:
            return None
        r = _Row(*row)
        return PlaceMatch(name=r.name, kind=r.kind, borough=r.borough, lat=r.lat, lon=r.lon, matched=r.name,
                          source=r.source, ids=(r.id,), area_ha=r.area_ha)
    finally:
        if own:
            conn.close()


RUNNABLE_RADIUS_M = 8000  # "Which park?" offers runnable places this far away, nearest first (Jared, 2026-11-09)
LONG_PATH_M = 2000  # a named path at least this long, by the water, counts as a place to run
WATERFRONT_M = 60  # by the water: within this of the shoreline (decision 014's waterfront distance) ...
WATERFRONT_SHARE = 0.5  # ... for at least this share of the path (the High Line touches the water at one end only).
# etl.load_places measures it once per long path (places.waterfront_share).
SAME_OPTION_M = 150  # two options whose nearest points are this close are one place to run


def parks_near(lat: float, lon: float, limit: int = 4, radius_m: float = RUNNABLE_RADIUS_M,
               conn=None) -> list[PlaceMatch]:
    """The options when 'the park' needs a question (R13): only places a runner can run in, nearest first, even past
    1 mi. Major parks (MAJOR_PARK_HA and up, or MAJOR_PARK_ALSO) and named waterfront paths at least LONG_PATH_M long,
    one per name, each with its distance to its nearest edge. Never playgrounds, courts or small squares (phone
    test, 2026-11-09: the old list offered the nearest parks of any size)."""
    parks = major_parks_near(lat, lon, radius_m=radius_m, conn=conn)
    conn, own = _connect(conn)
    try:
        rows = conn.execute(
            f"""WITH p AS (SELECT ST_Transform(ST_SetSRID(ST_Point(%(lon)s, %(lat)s), 4326), 2263) p)
                SELECT DISTINCT ON (name) {_ROW}, ST_X(c), ST_Y(c), d FROM (
                  SELECT places.*, ST_Distance(ST_Transform(outline, 2263), p.p) / %(f)s d,
                         ST_ClosestPoint(outline, ST_Transform(p.p, 4326)) c
                  FROM places, p
                  WHERE kind = 'path' AND waterfront_share >= %(share)s
                    AND ST_DWithin(ST_Transform(outline, 2263), p.p, %(ft)s)) places
                ORDER BY name, d""",
            {"lat": lat, "lon": lon, "ft": radius_m * FT_PER_M, "f": FT_PER_M, "share": WATERFRONT_SHARE}).fetchall()
        nearest = {r[0]: (r[-2], r[-3]) for r in rows}
        if parks:
            nearest |= {r[0]: (r[2], r[1]) for r in conn.execute(
                """SELECT id, ST_X(c), ST_Y(c) FROM (SELECT id, ST_ClosestPoint(outline, ST_SetSRID(ST_Point(%s, %s), 4326)) c
                   FROM places WHERE id = ANY(%s)) x""", (lon, lat, [m.ids[0] for m in parks])).fetchall()}
    finally:
        if own:
            conn.close()
    paths = [PlaceMatch(name=r[1], kind=r[2], borough=r[3], lat=r[8], lon=r[9], matched=r[1], source=r[10],
                        ids=(r[0],), area_ha=r[11], distance_m=round(r[-1], 1)) for r in rows]
    out = []
    for m in sorted([*parks, *paths], key=lambda m: m.distance_m):
        here = nearest.get(m.ids[0])
        same = any(normalize(m.name) == normalize(o.name) or (here and nearest.get(o.ids[0]) and
                   _meters(here, nearest[o.ids[0]]) <= SAME_OPTION_M) for o in out)
        if not same:  # the Hudson River Park, its greenway and its esplanade are one place to run: the nearest
            out.append(m)
    return out[:limit]


def _meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    kx = 111_320 * math.cos(math.radians(a[0]))
    return math.hypot((a[1] - b[1]) * kx, (a[0] - b[0]) * 110_574)
