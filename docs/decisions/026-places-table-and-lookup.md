# 026: A places table from our OSM extract, and `lookup(name, near)`

**Status:** accepted (2026-11-05; borough rule and park list decided by Jared 2026-11-06). Extends 025 and 006
(every row keeps its source and load time). Replaces decision 005's "always ask" for several boroughs.

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
  (`major_parks_near`), plus an add-list of smaller parks that count anyway. Today the add-list is just Battery
  Park, Manhattan. That gives 104 parks; the list and the reasoning are in `docs/phase3/major-parks-proposal.md`.
- **The borough rule (R19)** applies to addresses and place names alike, through `pick_by_borough`:
  1. Prefer the match in the reference borough: the runner's current borough for a start today, the saved start's
     borough for a later day, the route's start borough for an end or via point.
  2. Otherwise, take the nearest match within 3 km when the others are farther.
  3. Otherwise, ask.

  The chip always names the borough. `lookup` still returns every match; the parser applies the rule. For
  addresses, the geocoder's several-borough error (decision 005) becomes a candidate list for the same rule in
  step 4.
- **No typo tolerance** in the lookup: Claude fixes typos before it (Jared, 2026-11-06).

## Tests
- `api/tests/test_places.py` covers names, bases, display, crossings and grouping. It runs with the unit tests and
  needs no services.
- `evals/places/test_lookup.py` needs the loaded table, so it lives with the evals (decision 019). It covers Penn
  Station, McCarren Park, Central Park Reservoir, Central Park South, "86th St" at Central Park (two), 1st Ave &
  E 23rd St, 42nd St, E 42nd St, Hudson River Greenway, Prospect Park, New Jersey names (none), "the park" from
  three starts, and provenance on every row. 19 pass, and lookups take 12–110 ms.

## Decided by Jared (2026-11-06)
- **Several boroughs:** the borough rule above, replacing decision 005's "always ask". So "42nd St" from Kips Bay
  is Manhattan's, and evals P16 and P46 now parse (Manhattan).
- **"The park":** 10 ha within 1 mi, approved, with Battery Park added.
