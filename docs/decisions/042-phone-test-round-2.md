# 042: Phone test round 2 — one option per place, neighborhoods as areas, shape edits from the pool, usual shape

**Status:** accepted (2026-11-10). From Jared's second end-to-end phone test, before merging PR #11. Amends
decisions 026 and 041 (places), 029 (the API) and 032 (A to B).

## Decision
1. **"Which park?" merges options whose shapes mostly overlap.**
   - Two places are one option when either lies at least half within 60 m of the other (by area for a park, by
     length for a path). The nearer one stays.
   - From Union Square, Hudson River Park stands for the greenway through it.
   - This replaces decision 041's 150 m nearest-point rule, which kept both.
2. **One place per name and borough** (`api.places.one_per_name`).
   - "Which Williamsburg?" offered the neighborhood and a liquor store, both "Williamsburg, Brooklyn".
   - Of two same-name places in one borough, the most place-like kind stays, in this order: park, water,
     neighborhood, square, and so on, ahead of amenities and shops.
   - Streets and paths aren't merged here; `_groups` already joins a street's stretches.
   - Different boroughs stay apart, for R19 to pick.
3. **A neighborhood end is an area.**
   - The 2020 Neighborhood Tabulation Areas come from NYC Open Data (9nt8-h7nd, Department of City Planning), via
     `etl/load_neighborhoods.py` into `neighborhood_areas`.
   - A neighborhood's area is the NTA holding its OSM point. Every Williamsburg, Greenpoint and Park Slope point
     has one.
   - An end in a neighborhood (`end_place.area: "neighborhood"`) finishes on the shortest way toward its point, at
     the first place 300 m inside the area.
   - The way in decides, not the nearest edge as the crow flies. Williamsburg's nearest edge from Kips Bay is on
     its north side, but the way comes over the Williamsburg Bridge from the south. Finishing at that nearest edge
     took 4.5 mi, more than the 4.3 mi to the middle.
   - If the run starts inside the area, or the way never gets 300 m in, the end is the neighborhood's point.
4. **Shape edits.**
   - The constraints path did honor `shape`: editing "3 mile loop" (which means either shape) to out-and-back
     returned three out-and-backs. That build's #1 was already an out-and-back, which is likely why the phone
     looked unchanged.
   - Now a chip edit can name the build it started from (`route_id`). The engine keeps every candidate that passed
     for its last 8 builds.
   - When an edit changes only `shape`, the server answers from that pool at once (`Engine.from_pool`): the best
     routes of the new kind within the distance limit, picked by the generator's own rule.
   - It builds again only when none fits: a loop-only build has no out-and-backs, or the build is gone.
5. **`profile.usual_shape`** (`any`, `loop`, `out_and_back`): applies when the runner says no shape, with source
   `usual`. Any shape word said wins, even a plain "loop".

## Results (live)
- **"Which park?"**, with 0.02–0.07 s a list:
  - Kips Bay: East River Esplanade · 0.4, John V. Lindsay East River Park · 1.2, Hudson River Park · 1.5, Central
    Park · 1.5.
  - Union Square: East River Esplanade · 0.8, Hudson River Park · 1.0, John V. Lindsay East River Park · 1.2,
    Battery Park City Greenway · 1.7.
- **"Williamsburg"** is one place, the neighborhood.
- **"3 miles to Williamsburg" from Kips Bay:** the engine asks (rule 3). It offers the way into Williamsburg, 3.6
  mi, instead of 4.3 mi to its middle. At that distance the route finishes 300 m inside.

## Checks
- 998 unit tests pass, and 1,000 with CI's no-database settings.
- One live parse run: 51 of 51.
- All 200 live place and route evals pass. One is skipped: the personal-runs eval, which needs the git-ignored run
  data.

## Tests
- `api/tests/test_places.py`: one place per name and borough.
- `api/tests/test_engine.py`:
  - a shape edit takes the best of the new kind from the pool;
  - with none of that kind, it rebuilds;
  - the area end follows the way in;
  - an A-to-B run to a neighborhood uses its area.
- `api/tests/test_server.py`:
  - a shape-only edit comes from the pool without building;
  - any other edit builds;
  - without `route_id` the edit builds and honors the shape;
  - the usual shape comes from the profile.
- `api/tests/test_parse.py`: the usual shape applies when none is said; a said one wins.
- `evals/places/test_lookup.py`, live:
  - Williamsburg is one place;
  - overlapping shapes are one option;
  - every neighborhood point has an area.
- `evals/routes/test_neighborhoods.py`, live: 3 mi asks for the way into Williamsburg, not to its middle; at that
  distance the route finishes inside.
