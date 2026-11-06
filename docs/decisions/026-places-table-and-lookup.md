# 026: A places table from our OSM extract, and `lookup(name, near)`

**Status:** accepted for Phase 3, step 2 (2026-11-05). Two choices wait on Jared (below). Extends 025; follows 005
(several matches ask) and 006 (every row keeps its source and load time).

## Decision
- **`places` in PostGIS, built by `make places`** (`etl/load_places.py`, about 20 s) from data already on disk.
  113,576 rows on the 2026-10-28 snapshot:
  - named OSM nodes: rail and subway stations, subway entrances, squares, amenities, shops, tourism, leisure
  - named OSM areas as a point plus outline: squares, pedestrian plazas, water, station buildings, bridges, and the
    parks in `osm_parks`
  - named streets and paths from `osm_ways`: one row per name and borough, the merged line as outline
  - 45,666 street crossings: two differently named roads sharing an OSM node, with shared nodes of one pair within
    60 m counted as one crossing
  - the 428 MTA station complexes in `station_flow`, and the 158 catalog corridors (decision 012)
- **Borough outlines** come from the OSM borough boundaries in `new-york-latest.osm.pbf`, stored in `boroughs`.
  Rows outside all five are dropped (66, all in New Jersey, such as Hoboken's ferry terminals), so New Jersey names
  find nothing.
- **Matching** (`api/places.py`), in order:
  1. A crossing ("1st Ave & E 23rd St"). A street written with a direction matches only that side.
  2. An exact name, alias or street base. "42nd St" matches East and West 42nd Street as one street per borough.
  3. Failing that, names holding every word of the query, keeping landmarks over businesses ("Penn Station" finds
     New York Penn Station, not the Penn Station Eagle artwork).
  4. Then same-name rows within 400 m are one place. A query ending like a street ("86th St") keeps only streets
     and paths.
  - There is no typo tolerance. Claude normalizes the runner's words first ("reservor", "penn"), as rule R12 says.
- **`near`:**
  - A point sorts matches by distance. `near_m` drops far ones, but it is off by default, so several boroughs still
    means several matches (decision 005).
  - A place with an area means "at": only places touching it count. A street touching it in several spots gives one
    match per spot, labeled by the crossing street there. So "86th St" at Central Park is 5th Ave or Central Park
    West.
- **Curated aliases** in `etl/curated/place_aliases.json` cover everyday names OSM lacks. There is one entry:
  "Central Park Reservoir" for Jacqueline Kennedy Onassis Reservoir. The loader fails if an entry's place is missing.
- **Every row is trust `listed`** and names its source: OpenStreetMap, MTA or the Loop corridor catalog.
- **"The park" (R13)** is the nearest named OSM `leisure=park` of 10 ha or more within 1 mi of the start
  (`major_parks_near`). That gives 103 parks; the list and the reasoning are in
  `docs/phase3/major-parks-proposal.md`.

## Tests
- `api/tests/test_places.py` covers names, bases, display, crossings and grouping. It runs with the unit tests and
  needs no services.
- `evals/places/test_lookup.py` needs the loaded table, so it lives with the evals (decision 019). It covers Penn
  Station, McCarren Park, Central Park Reservoir, Central Park South, "86th St" at Central Park (two), 1st Ave &
  E 23rd St, 42nd St, E 42nd St, Hudson River Greenway, Prospect Park, New Jersey names (none), "the park" from
  three starts, and provenance on every row. 19 pass, and lookups take 12–110 ms.

## Waiting on Jared
1. **Several boroughs.** On this data these names exist in more than one borough:
   - "42nd St": Manhattan, Brooklyn and Queens
   - "E 42nd St": Manhattan and East Flatbush
   - "Grand Army Plaza": Manhattan (5th Ave & 59th St) and Brooklyn

   Today the lookup returns all of them, so the parser would ask. Eval R07 ("avoid the chaos of 42nd st", no
   question) needs the nearest instead. The choice is to always ask, or to use the nearest when it is within
   `near_m` of the runner and the others are not.
2. **The major-park bar:** 10 ha within 1 mi, or something else (`docs/phase3/major-parks-proposal.md`).
