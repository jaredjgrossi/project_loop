"""Build the places table from our OSM extract:  python -m etl.load_places  (make places)

Phase 3, step 2 (decision 026). One row per named place, each with its source and load time (decision 006):
- named OSM nodes: rail and subway stations, subway entrances, squares, neighborhoods, amenities, shops, tourism,
  leisure
- named OSM areas, as a point plus outline: squares, pedestrian plazas, water (the Reservoir), station buildings,
  bridges; parks come from osm_parks
- named streets and paths from osm_ways, one row per name and borough, with the merged line as outline
- street crossings: where two differently named roads share an OSM node, one point per crossing
- subway stations from station_flow (MTA, decision 016), when that table is loaded
- corridors from the corridor catalog (decision 012), when built
- curated aliases and redirects (etl/curated/place_aliases.json) for everyday names OSM lacks ("Central Park
  Reservoir"; "West Side Highway" for the Hudson River Greenway)

Borough outlines come from the OSM borough boundaries in routing/data/new-york-latest.osm.pbf. A row outside all
five boroughs is dropped: the extract holds a few New Jersey features (Hoboken's ferry terminals), and Loop only
covers New York City.

Needs osm_ways and osm_parks (make setup); osmium (brew install osmium-tool). Rebuilt from scratch each run.
"""

import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from api.places import display_name, normalize, street_base
from etl.load import database_url
from etl.load_osm import NYC_PBF, STATE_PBF, WORK_DIR, export_ways, snapshot_time

CURATED_ALIASES = Path(__file__).resolve().parent / "curated" / "place_aliases.json"
OSM_SOURCE, OSM_DATASET = "OpenStreetMap", "osm:geofabrik-new-york"
BOROUGHS = ("Manhattan", "Brooklyn", "Queens", "The Bronx", "Staten Island")
BOROUGH_LABEL = {"The Bronx": "Bronx"}
PATH_HIGHWAYS = ("footway", "path", "cycleway", "pedestrian", "steps", "track", "bridleway")
NOT_A_PLACE = ("service", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
               "construction", "proposed", "platform", "elevator", "corridor", "bus_stop", "raceway", "abandoned",
               "razed", "services", "rest_area", "emergency_bay", "busway")
# Roads whose shared nodes are crossings a runner would name. Not motorways (FDR Drive has no crossings to stand at).
CROSSING_HIGHWAYS = ("trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street",
                     "pedestrian")
CROSSING_CLUSTER_M = 60  # the shared nodes of one crossing (dual carriageways, wide junctions) are this close
NODE_FILTER = ["n/railway=station,halt,subway_entrance", "n/public_transport=station", "n/place=square",
               "n/place=neighbourhood,suburb,quarter", "n/amenity",
               "n/shop", "n/tourism", "n/leisure"]
AREA_FILTER = ["a/place=square", "a/highway=pedestrian", "a/natural=water", "a/railway=station",
               "a/public_transport=station", "a/man_made=bridge"]
ALIAS_TAGS = ("alt_name", "official_name", "short_name")
FT_PER_M = 3.28084

SCHEMA = """
DROP TABLE IF EXISTS places, boroughs;
CREATE TABLE boroughs (
    name               text PRIMARY KEY,
    source_dataset_id  text NOT NULL,
    source_row_id      text NOT NULL,
    source_updated_at  timestamptz,
    loaded_at          timestamptz NOT NULL,
    geom               geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX ON boroughs USING gist (geom);
CREATE TABLE places (
    id                 serial PRIMARY KEY,
    name               text NOT NULL,          -- as the source writes it; crossings: "1st Ave & E 23rd St"
    kind               text NOT NULL,
    category           text,                   -- the source tag, e.g. amenity=cafe, highway=residential
    borough            text,
    aliases            text[] NOT NULL DEFAULT '{}',
    norm               text,                   -- api.places.normalize(name)
    base               text,                   -- norm without a leading direction (street halves)
    alias_norms        text[] NOT NULL DEFAULT '{}',
    redirects          text[] NOT NULL DEFAULT '{}',  -- curated names for a different thing that mean this place
    redirect_norms     text[] NOT NULL DEFAULT '{}',
    streets            text[],                 -- crossings: the two street names, as OSM writes them
    street_norms       text[],
    street_bases       text[],
    geom               geometry(Point, 4326) NOT NULL,
    outline            geometry(Geometry, 4326),  -- area or line, when the place has one
    area_ha            double precision,
    trust              text NOT NULL DEFAULT 'listed' CHECK (trust IN ('verified', 'listed', 'seasonal_or_closed')),
    source             text NOT NULL,
    source_dataset_id  text NOT NULL,
    source_row_id      text NOT NULL,
    source_updated_at  timestamptz,
    loaded_at          timestamptz NOT NULL
);
CREATE TEMP TABLE places_in (
    name text, kind text, category text, aliases text[], geojson text, source_row_id text
);
"""

INDEXES = """
CREATE INDEX ON places (norm);
CREATE INDEX ON places (base);
CREATE INDEX ON places USING gin (alias_norms);
CREATE INDEX ON places USING gin (redirect_norms);
CREATE INDEX ON places USING gin (street_bases);
CREATE INDEX ON places (kind);
CREATE INDEX ON places USING gist (geom);
CREATE INDEX ON places USING gist (outline);
"""


def node_kind(p: dict) -> tuple[str, str] | None:
    """(kind, category) for a named OSM node, or None when it isn't a place someone would name as a start or end."""
    if p.get("railway") in ("station", "halt") or (p.get("public_transport") == "station" and "railway" not in p):
        subway = p.get("station") == "subway" or "subway" in str(p.get("network", "")).casefold()
        return ("subway_station" if subway else "station"), f"railway={p.get('railway', 'station')}"
    if p.get("public_transport") in ("stop_position", "platform") or p.get("railway") in ("stop", "platform"):
        return None
    if p.get("railway") == "subway_entrance":
        return "subway_entrance", "railway=subway_entrance"
    if p.get("place") == "square":
        return "square", "place=square"
    if p.get("place") in ("neighbourhood", "suburb", "quarter"):
        return "neighborhood", f"place={p['place']}"
    for tag in ("tourism", "leisure", "amenity", "shop"):
        if tag in p:
            return tag, f"{tag}={p[tag]}"
    return None


def area_kind(p: dict) -> tuple[str, str] | None:
    if p.get("place") == "square":
        return "square", "place=square"
    if p.get("highway") == "pedestrian":
        return "plaza", "highway=pedestrian"
    if p.get("natural") == "water":
        return "water", f"natural=water{';water=' + p['water'] if 'water' in p else ''}"
    if p.get("railway") == "station" or p.get("public_transport") == "station":
        return ("subway_station" if p.get("station") == "subway" else "station"), "railway=station"
    if p.get("man_made") == "bridge":
        return "bridge", "man_made=bridge"
    return None


def aliases(p: dict) -> list[str]:
    out = []
    for tag in ALIAS_TAGS:
        for v in str(p.get(tag, "")).split(";"):
            v = v.strip()
            if v and v != p.get("name") and v not in out:
                out.append(v)
    return out


def read_features(path: Path, classify) -> tuple[list[tuple], Counter]:
    rows, skipped = [], Counter()
    with path.open() as fh:
        for line in fh:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            f = json.loads(line)
            p = f["properties"]
            name = (p.get("name") or "").strip()
            kind = classify(p)
            if not name or kind is None:
                skipped["unnamed or not a place"] += 1
                continue
            osm_id = str(f.get("id", ""))
            row_id = {"n": "node/", "w": "way/", "a": "area/", "r": "relation/"}.get(osm_id[:1], "") + osm_id[1:]
            rows.append((name, kind[0], kind[1], aliases(p), json.dumps(f["geometry"]), row_id))
    return rows, skipped


def load_boroughs(conn, loaded_at, snapshot) -> int:
    path = export_ways(STATE_PBF, "r/admin_level=7", "osm_boroughs", geometry_types="polygon")
    found = 0
    for line in path.open():
        line = line.strip().lstrip("\x1e")
        if not line:
            continue
        f = json.loads(line)
        p = f["properties"]
        if p.get("border_type") != "borough" or p.get("name") not in BOROUGHS:
            continue
        conn.execute(
            """INSERT INTO boroughs VALUES (%s, %s, %s, %s, %s,
               ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), 3)))""",
            (BOROUGH_LABEL.get(p["name"], p["name"]), OSM_DATASET, f"relation/{str(f.get('id', ''))[1:]}", snapshot,
             loaded_at, json.dumps(f["geometry"])))
        found += 1
    if found != 5:
        raise SystemExit(f"expected the five borough boundaries in {STATE_PBF.name}, found {found}")
    return found


def load_osm_features(conn, rows, loaded_at, snapshot) -> None:
    conn.execute("TRUNCATE places_in")
    with conn.cursor().copy("COPY places_in FROM STDIN") as copy:
        for r in rows:
            copy.write_row(r)
    conn.execute(
        """INSERT INTO places (name, kind, category, aliases, geom, outline, area_ha, source, source_dataset_id,
                               source_row_id, source_updated_at, loaded_at)
           SELECT name, kind, category, aliases,
                  CASE WHEN GeometryType(g) = 'POINT' THEN g ELSE ST_PointOnSurface(g) END,
                  CASE WHEN GeometryType(g) = 'POINT' THEN NULL ELSE g END,
                  CASE WHEN GeometryType(g) = 'POINT' THEN NULL ELSE ST_Area(ST_Transform(g, 2263)) / 107639.1 END,
                  %s, %s, source_row_id, %s, %s
           FROM (SELECT *, CASE WHEN GeometryType(raw) = 'POINT' THEN raw
                                ELSE ST_Multi(ST_CollectionExtract(ST_MakeValid(raw), 3)) END g
                 FROM (SELECT *, ST_SetSRID(ST_GeomFromGeoJSON(geojson), 4326) raw FROM places_in) r) t
           WHERE NOT ST_IsEmpty(g)""",
        (OSM_SOURCE, OSM_DATASET, snapshot, loaded_at))


def load_parks(conn) -> None:
    conn.execute(
        """INSERT INTO places (name, kind, category, geom, outline, area_ha, source, source_dataset_id, source_row_id,
                               source_updated_at, loaded_at)
           SELECT name, 'park', 'leisure=' || leisure, ST_PointOnSurface(geom), geom,
                  ST_Area(ST_Transform(geom, 2263)) / 107639.1, %s, source_dataset_id, source_row_id,
                  source_updated_at, loaded_at
           FROM osm_parks WHERE name IS NOT NULL""", (OSM_SOURCE,))


def load_streets(conn, loaded_at) -> None:
    """One row per street or path name per borough. A way belongs to the borough holding its midpoint."""
    conn.execute(
        """INSERT INTO places (name, kind, category, borough, geom, outline, source, source_dataset_id, source_row_id,
                               source_updated_at, loaded_at)
           SELECT name, kind, category, borough, ST_ClosestPoint(line, ST_Centroid(line)), line, %(src)s, dataset,
                  row_id, updated, %(at)s
           FROM (SELECT w.name, b.name borough,
                        CASE WHEN w.name ~* '\\m(bridge|viaduct)\\M' AND bool_or(w.tags ? 'bridge') THEN 'bridge'
                             WHEN bool_and(w.highway = ANY(%(paths)s)) THEN 'path' ELSE 'street' END kind,
                        'highway=' || mode() WITHIN GROUP (ORDER BY w.highway) category,
                        ST_Multi(ST_LineMerge(ST_Collect(w.geom))) line, min(w.source_dataset_id) dataset,
                        'way/' || min(w.way_id)
                            || CASE WHEN count(*) > 1 THEN ' +' || (count(*) - 1) || ' ways' ELSE '' END row_id,
                        max(w.source_updated_at) updated
                 FROM osm_ways w JOIN boroughs b ON ST_Intersects(b.geom, ST_LineInterpolatePoint(w.geom, 0.5))
                 WHERE w.name IS NOT NULL AND NOT (w.highway = ANY(%(skip)s))
                 GROUP BY w.name, b.name) t""",
        {"paths": list(PATH_HIGHWAYS), "skip": list(NOT_A_PLACE), "src": OSM_SOURCE, "at": loaded_at})


def load_crossings(conn, loaded_at, snapshot) -> int:
    """Two differently named roads sharing an OSM node cross there. Shared nodes of one pair within
    CROSSING_CLUSTER_M are one crossing."""
    rows = conn.execute(
        """WITH pts AS (
               SELECT name, way_id, (ST_DumpPoints(geom)).geom g FROM osm_ways
               WHERE name IS NOT NULL AND highway = ANY(%(hw)s)),
           shared AS (
               SELECT min(g) g, array_agg(DISTINCT name) names, min(way_id) way_id FROM pts
               GROUP BY ST_AsBinary(g) HAVING count(DISTINCT name) >= 2),
           pairs AS (
               SELECT a, b, g, way_id FROM shared, unnest(names) a, unnest(names) b WHERE a < b),
           clustered AS (
               SELECT a, b, g, way_id,
                      ST_ClusterDBSCAN(ST_Transform(g, 2263), eps := %(eps)s, minpoints := 1)
                          OVER (PARTITION BY a, b) c
               FROM pairs)
           SELECT a, b, ST_AsText(ST_Centroid(ST_Collect(g))), min(way_id) FROM clustered GROUP BY a, b, c""",
        {"hw": list(CROSSING_HIGHWAYS), "eps": CROSSING_CLUSTER_M * FT_PER_M}).fetchall()
    with conn.cursor().copy(
            "COPY places (name, kind, category, streets, geom, source, source_dataset_id, source_row_id, "
            "source_updated_at, loaded_at) FROM STDIN") as copy:
        for a, b, wkt, way_id in rows:
            first, second = crossing_order(a, b)
            copy.write_row((f"{display_name(first)} & {display_name(second)}", "crossing", "crossing",
                            [first, second], f"SRID=4326;{wkt}", OSM_SOURCE, OSM_DATASET,
                            f"shared node of way/{way_id}", snapshot, loaded_at))
    return len(rows)


def crossing_order(a: str, b: str) -> tuple[str, str]:
    """Avenues before streets, the way New Yorkers say it ('1st Ave & E 23rd St'); otherwise alphabetical."""
    def rank(name):
        last = normalize(name).split()[-1:] or [""]
        return 1 if last[0] == "st" else 0
    return tuple(sorted((a, b), key=lambda n: (rank(n), n)))


def load_stations(conn, loaded_at) -> int:
    if not conn.execute("SELECT to_regclass('station_flow') IS NOT NULL").fetchone()[0]:
        print("  station_flow not loaded (make crowds); skipping MTA station names")
        return 0
    return conn.execute(
        """INSERT INTO places (name, kind, category, geom, source, source_dataset_id, source_row_id, loaded_at)
           SELECT DISTINCT ON (complex_id) name, 'subway_station', 'mta_complex',
                  ST_SetSRID(ST_Point(lon, lat), 4326), 'MTA', source, 'complex/' || complex_id, %s
           FROM station_flow ORDER BY complex_id""", (loaded_at,)).rowcount


def load_corridors(conn, loaded_at) -> int:
    if not conn.execute("SELECT to_regclass('corridors') IS NOT NULL").fetchone()[0]:
        print("  corridor catalog not built (make corridors); skipping corridors")
        return 0
    return conn.execute(
        """INSERT INTO places (name, kind, category, geom, outline, source, source_dataset_id, source_row_id,
                               loaded_at)
           SELECT name, 'corridor', kind, ST_ClosestPoint(geom, ST_Centroid(geom)), geom,
                  'Loop corridor catalog (OpenStreetMap, decision 012)', 'loop:corridors', 'corridor/' || id, %s
           FROM corridors""", (loaded_at,)).rowcount


def apply_curated_aliases(conn) -> int:
    curated = json.loads(CURATED_ALIASES.read_text())
    for column, key, entries in (("aliases", "alias", curated["aliases"]),
                                 ("redirects", "name_used", curated.get("redirects", []))):
        for e in entries:
            n = conn.execute(f"UPDATE places SET {column} = array_append({column}, %s) WHERE name = %s AND kind = %s",
                             (e[key], e["name"], e["kind"])).rowcount
            if n == 0:
                raise SystemExit(f"curated {key} {e[key]!r}: no {e['kind']} named {e['name']!r} in places")
    return len(curated["aliases"]) + len(curated.get("redirects", []))


def fill_names(conn) -> None:
    """Normalized names for matching, computed in Python with the same code lookups use."""
    rows = conn.execute("SELECT id, name, aliases, redirects, streets FROM places").fetchall()
    conn.execute("CREATE TEMP TABLE names_in (id int, norm text, base text, alias_norms text[], redirect_norms text[], "
                 "street_norms text[], street_bases text[])")
    with conn.cursor().copy("COPY names_in FROM STDIN") as copy:
        for pid, name, als, redirects, streets in rows:
            norm = normalize(name)
            sn = [normalize(s) for s in streets] if streets else None
            copy.write_row((pid, norm, street_base(norm), [normalize(a) for a in als],
                            [normalize(r) for r in redirects], sn, [street_base(s) for s in sn] if sn else None))
    conn.execute("""UPDATE places p SET norm = n.norm, base = n.base, alias_norms = n.alias_norms,
                    redirect_norms = n.redirect_norms, street_norms = n.street_norms, street_bases = n.street_bases
                    FROM names_in n WHERE p.id = n.id""")


def assign_boroughs(conn) -> int:
    conn.execute("""UPDATE places p SET borough = b.name FROM boroughs b
                    WHERE p.borough IS NULL AND ST_Intersects(b.geom, p.geom)""")
    return conn.execute("DELETE FROM places WHERE borough IS NULL").rowcount


def main() -> int:
    if shutil.which("osmium") is None:
        print("osmium not found. Install it with:  brew install osmium-tool", file=sys.stderr)
        return 1
    for pbf in (NYC_PBF, STATE_PBF):
        if not pbf.exists():
            print(f"{pbf} not found. Build it first:  python -m routing.prepare_osm", file=sys.stderr)
            return 1
    loaded_at, snapshot = datetime.now(UTC), snapshot_time()
    print("Exporting named nodes and areas with osmium ...")
    node_path = _export(NYC_PBF, NODE_FILTER, "places_nodes", "point")
    area_path = _export(NYC_PBF, AREA_FILTER, "places_areas", "polygon")
    nodes, n_skip = read_features(node_path, node_kind)
    areas, a_skip = read_features(area_path, area_kind)

    with psycopg.connect(database_url()) as conn:
        with conn.transaction():
            conn.execute(SCHEMA)
            print("Borough boundaries ...")
            load_boroughs(conn, loaded_at, snapshot)
            load_osm_features(conn, nodes + areas, loaded_at, snapshot)
            load_parks(conn)
            print("Streets and paths ...")
            load_streets(conn, loaded_at)
            print("Crossings ...")
            crossings = load_crossings(conn, loaded_at, snapshot)
            stations = load_stations(conn, loaded_at)
            corridors = load_corridors(conn, loaded_at)
            dropped = assign_boroughs(conn)
            curated = apply_curated_aliases(conn)
            fill_names(conn)
            conn.execute(INDEXES)
            counts = conn.execute("SELECT kind, count(*) FROM places GROUP BY 1 ORDER BY 2 DESC").fetchall()
            (total,) = conn.execute("SELECT count(*) FROM places").fetchone()
    print(f"places  {total:7d} rows  (OSM snapshot {snapshot})")
    for kind, n in counts:
        print(f"  {kind:<16} {n:7d}")
    print(f"  nodes read {len(nodes)}, areas read {len(areas)}; crossings {crossings}; MTA stations {stations}; "
          f"corridors {corridors}; curated aliases {curated}")
    print(f"  dropped {dropped} rows outside the five boroughs (New Jersey features in the extract)")
    return 0


def _export(pbf: Path, filters: list[str], name: str, geometry_types: str) -> Path:
    """export_ways with several tags-filter expressions."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    filtered, out = WORK_DIR / f"{name}.osm.pbf", WORK_DIR / f"{name}.geojsonseq"
    subprocess.run(["osmium", "tags-filter", "--overwrite", "-o", str(filtered), str(pbf), *filters], check=True)
    subprocess.run(["osmium", "export", "--overwrite", "-f", "geojsonseq", "--add-unique-id=type_id",
                    f"--geometry-types={geometry_types}", "-o", str(out), str(filtered)], check=True)
    return out


if __name__ == "__main__":
    sys.exit(main())
