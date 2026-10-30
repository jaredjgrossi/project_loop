# Loop: handoff (end of Phase 1, plus loop shape from Phase 2)

As of 2026-10-30. Plan: `PROJECT_PLAN.md`. Reasons for each choice: `decisions/001`–`008`.

## What's built
- **Local stack:** Postgres 16 + PostGIS and GraphHopper 11.1 (`foot` profile, ferries excluded) on an NYC-only OSM extract.
- **Data in PostGIS**, every row with source dataset id, source row id and load time: Parks Properties, Drinking Fountains, Public Restrooms, and 414k OSM street and path ways.
- **Geocoder** (`api/geocoding.py`): NYC GeoSearch plus checks. Ambiguous boroughs, wrong house numbers and place names are refused.
- **Loop generator** (`api/generate.py`): grid-aligned rectangles routed along real streets, rescaled to the distance, ranked by shape; round trips added where the street grid is weak.
- **Shape metrics** (`api/shape.py`): turns per mile, longest straight run, share on long runs, retraced share, width, compactness. Printed and saved in the GeoJSON for every loop.

## Run it
```bash
make setup        # first time: ~600 MB download, a few minutes
uv run python -m api.scripts.make_loop "11 Madison Ave, Manhattan" 4 --top 3
```
Drag the files in `out/` onto geojson.io. Day to day: `make up`, `make down`, `make test`. Setup details and troubleshooting: `README.md`.

## Verified
- 150 unit tests pass: geocoder against recorded real responses, ETL parsers against real rows, shape metrics on hand-made shapes, generator with a fake router.
- Live, 2026-10-30: 13 starts across all five boroughs at 3, 6 and 10 mi (39 cases) all landed within ±5%, each in 0.2–1.2 s.
- The Staten Island Ferry route returns "connection not found". The grid angle at 11 Madison Ave is 28.7°.

## Not verified
- No one has viewed the loops in geojson.io. I drew one Manhattan start as an image, and no personal address has been run.
- `make setup` end to end since `etl.load_osm` was added (each step was run separately), and the test suite on a fresh clone at this commit.
- Linux/Intel machines and CI.
- The shape-score weights (turns 40, straight runs 25, compactness 25, retracing 10) are a first judgment with no rating data.
- Ferry exclusion was checked on one route; geocoding on about ten queries.

## Known issues
- **Staten Island scores low** (winding streets): 1 Bay St at 3 mi scored 48, 2800 Victory Blvd at 3 mi scored 23 (10 turns per mile), though the distance is met. Weak-grid starts elsewhere are mixed (51–81).
- **Port 8989 clash:** a second GraphHopper container (`project_loop-graphhopper-1`, from a clone at `~/project_loop`) holds the port, so this folder's container exits on `make up`. It works today because config and map are identical. If they diverge: `docker stop project_loop-graphhopper-1`, then `make up`.
- **Fountain data is stale** (last updated 2024-07-15, no status or season): `listed` at best (decision 004).
- Start must be a street address with a number; place names are refused on purpose.
- After changing the map or `routing/config.yml`, delete `routing/graph-cache/foot-v2`.
- `make_loop.py` imports `database_url` from `etl.load`; move it to a shared config module.

## Left for Phase 2
1. Corridor anchoring: avenues and the East River and Hudson greenways as loop sides (decision 008).
2. Crossings and signals: load the OSM nodes (already in the export) and count per route.
3. Park and waterfront share: Parks polygons plus OSM geometry, since Parks Properties misses Hudson River Park.
4. Amenities near mile X with trust labels (restrooms from `status` + `open` + hours; fountains `listed`).
5. One combined ranking and the top 3 from the CLI, stating any limit that can't be met.
6. Tune the weights; improve Staten Island and other weak-grid areas.

Later phases: Claude parsing and explanation, the API, the frontend, ratings. `docs/discovery/` is intentionally untracked.
