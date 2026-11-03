# Loop: handoff (Phase 2 core complete except the run-test gate)

As of 2026-11-02. Plan: `PROJECT_PLAN.md`. Reasons for each choice: `decisions/001`–`017`. Decisions 009–016 and the GPX writer are merged into main (PRs #1–#3); 013 is a crowd-signal research spike. Decision 017 (closures) is in PR #4 (`phase2-closures`).

**Phase 2 core is complete except the reviewer's run-test gate:** running the Kips Bay 3, 4 and 6 mi test routes (`out/run-tests/kips-bay-{3,4,6}mi-{zigzags,waits}.gpx`, with a map image for each; git-ignored) and reporting back. None of them enters a known closure (checked 2026-11-02).

**Where it stands:**
- Routes are ranked against the runner's preferences, with every dimension labeled `measured`, `estimate` or `not_scored` (decisions 009 and 010).
- No-go zones are a hard rule.
- Out-and-backs are a route type alongside loops.
- The ranking has been compared with the reviewer's own map-matched runs using identical definitions (decision 011).
- **Phase 2 step 2 (decision 012):** park, waterfront and corridor generators built from OSM for every runner, plus a verified corridor catalog and round trips everywhere. With the reviewer's runs off, the real-run check now passes at all three home-area starts (Kips Bay 87 vs 77, up from 61). At most starts and distances the #1 route reaches a park or the water. It doesn't at Kips Bay 4 mi or Flatiron 4 mi (see Known issues).
- **Decision 014:**
  - streaming, prioritized generation, with the first candidate in 0.1–0.3 s;
  - the candidate pool with metric vectors;
  - per-segment GeoJSON with stretch names and trust labels;
  - elevation with mile positions (estimate);
  - start hour;
  - the feedback schema;
  - turnarounds by walking distance, plus "both ways" routes;
  - cleaned corridor names and a catalog regression check.

  All 15 review rows now have a park, waterfront or corridor route at #1.
- **Decision 015, lights:**
  - runners who wait get a signal penalty in every GraphHopper request;
  - both kinds of runner get an expected wait at lights (estimate, not scored), with zig-zag credit where a same-length staircase exists;
  - the penalty lowers the share of the route on road centerlines; it doesn't raise it.
- **Decision 016, crowds** (estimate):
  - a low / medium / high level per sidewalk way and DOT count window, from subway volume per foot of sidewalk width;
  - a crowds ranking dimension when the request has a start date and time;
  - a crowd level on each stretch;
  - "crowded" reports logged for calibration.

  Paths, Sundays, before 7am and after 8pm are not scored. Only known-busy distance costs a route; no-data distance is neutral. Eval: Spearman 0.73–0.82 against the held-out DOT round.
- **Decision 017, closures** (hard rule):
  - a route with 30 m or more inside a known closure is rejected;
  - the corridor catalog's East Midtown Greenway missing link applies; the other 106 gaps are recorded with the reason (between two corridors, walkable ways along the link, or the link is too short), because treating them as closures closed real paths;
  - curated closures (`routing/curated_closures.geojson`): checked by hand against public sources, with a `listed` trust label, the date checked and a review-by date; the eval fails once a review-by date passes. First entry: East River Park north of Houston St (East Side Coastal Resiliency, closed since 2025-09-08, reopening projected end of 2027; review by 2027-02-01);
  - "closed or blocked" stretch reports go to `closure_reports`, and a reviewer confirms one into a closure that GraphHopper routes around.
- **All weights are provisional.** Turns and retracing in particular are not to be tuned before more calibration.

## What's built
- **Local stack:** Postgres 16 + PostGIS and GraphHopper 11.1 (`foot` profile, ferries excluded) on an NYC-only OSM extract.
- **Data in PostGIS**, every row with source dataset id, source row id and load time: Parks Properties, Drinking Fountains, Public Restrooms, 414k OSM street and path ways (now with `crossing` tags), the OSM coastline (`osm_coastline`), OSM park areas (`osm_parks`) and the corridor catalog (`corridors`, `corridor_gaps`, built by `etl/build_corridors.py`).
- **Geocoder** (`api/geocoding.py`): NYC GeoSearch plus checks. Ambiguous boroughs, wrong house numbers and place names are refused.
- **Request schema** (`api/constraints.py`): `RunConstraints` holds hard limits plus these preferences:
  - lights, crowds, scenery, surface, turns, and "matches routes you run";
  - Training and Exploring presets;
  - `describe()`, which the CLI prints before routing.

  An unstated shape is `any`.
- **Generator** (`api/generate.py`): candidates come from four sources:
  - rectangles and round trips (everywhere);
  - out-and-backs on 8 headings;
  - anchored routes to parks, the waterfront and catalog corridors (`api/anchors.py`, from OSM). Each is an out-and-back or a free return, which can come out as a loop, a lollipop or an out-and-back. They are routed to prefer staying on the feature;
  - optionally, the same along the runner's own corridors, when a runner prior is loaded and wanted.

  Each is rescaled to the distance, checked against no-go zones and ranked. Route types are loop, out-and-back and lollipop.
- **UI-ready outputs** (decision 014):
  - `GenerationResult.pool` and `.timing`, and an `on_candidate` streaming callback;
  - `api/segments.py`: stretches with names, miles, signals, climb, and sourced, trust-labeled facts;
  - `api/elevation.py`: profile every 0.1 mi, labeled estimate;
  - `api/feedback.py` plus the `generated_routes` and `route_feedback` tables.
- **Ranking** (`api/ranking.py`):
  - measured: turns, straight runs, loop shape, retracing (loops only), park/water, signals, matches routes you run;
  - estimate: crowds (only with a start date and time, decision 016);
  - not scored: roadway.
- **Closures** (`api/closures.py`, `etl/build_closures.py`, `routing/curated_closures.geojson`, table `closures`; `make closures` reloads them): a hard rule, like no-go zones (decision 017).
- **No-go zones** (`routing/no_go_zones.geojson`, `api/nogo.py`): GraphHopper avoid-areas plus a geometry check. Times Square is a default zone.
- **Metrics** (`api/shape.py`, `api/route_context.py`): turns (definition revised in decision 011), straight runs, retracing, out-and-back share, closure, width, compactness, park share, waterfront share, crosswalks and signalized crosswalks per mile.
- **Review loop** (`evals/routes/`):
  - 10 fixed starts (`starts.json`, stored coordinates);
  - a review page;
  - every rejected route as a failing eval (`rejected_routes.json`);
  - a positive check against the reviewer's real runs (`test_real_runs.py`).
- **Real-run calibration** (`evals/health_routes/`):
  - first-pass scripts (`analyze_routes.py`, `summarize.py`);
  - GraphHopper map matching (`match_runs.py`);
  - the per-way runner prior and corridors (`build_prior.py`);
  - the real vs generated comparison (`calibrate.py`).

  All outputs are personal and go to `data/health/` (git-ignored) or the local `runner_prior` table.

## Run it
```bash
make setup        # first time: ~600 MB download, a few minutes
uv run python -m api.scripts.make_loop "11 Madison Ave, Manhattan" 4 --top 3 [--shape loop|out_and_back|any] [--mode training] [--avoid "Times Square"] [--start-time 06:45] [--lights waits|zigzags] [--pool out/pool.json]
```
Drag the files in `out/` onto geojson.io: each holds the route, its start, and its stretch features. Day to day: `make up`, `make down`, `make test`, and `make corridors` after an OSM reload. Setup details and troubleshooting: `README.md`.

Review after every change to scoring or generation (needs `make up`):
```bash
uv run python -m evals.routes.render_review   # writes out/review/index.html (git-ignored)
uv run pytest evals/                          # rejected routes (red until fixed) and the real-run check
```
To reject a route, add a case to `evals/routes/rejected_routes.json`. `make test` does not run `evals/`.

Real-run calibration (personal data; the reviewer's machine only):
```bash
uv run python -m evals.health_routes.match_runs apple_health_export/workout-routes --since 2025-10-30
uv run python -m evals.health_routes.build_prior     # ~3 min; writes runner_prior, data/health/way_prior.csv, corridors.geojson
uv run python -m evals.health_routes.calibrate       # writes data/health/calibration.md
uv run python -m evals.routes.report_starts --label after   # before/after table for every review start (out/review/)
```

## Verified
- 295 unit tests pass (decision 014 added walking-distance anchors, stretches, elevation, feedback, corridor names, and the scheduler's order, streaming, timing and pool). Before that, 245: geocoder against recorded real responses, ETL parsers against real rows, shape metrics and share-of-route on hand-made shapes, no-go geometry, ranking, anchor grouping, generator with a fake router (anchored routes, lollipops, running past a feature, the off-map fallback), request schema and presets.
- `pytest evals/` passes 9 of 9, including the four corridor catalog checks (decision 014). As of 012 it was 5 of 5: Times Square at 4 and 6 mi, and the real-run check at kips-bay, flatiron and upper-east-side. The real-run check now runs with "matches routes you run" off on both sides and generates without the reviewer's runs (decision 012). No weights changed to get there.
- Corridor catalog: 160 corridors, checked end to end with GraphHopper. The known East River gap shows up (709 m internal gap, East Midtown Greenway).
- The kips-bay review start is a public stand-in (Kips Bay Library, 446 3rd Ave), 192 m from the reviewer's address, which is kept out of the repo.
- Map matching: 197 of the 205 runs from the last 12 months matched. The 8 that didn't are outside NYC. Matching was checked visually on 4 runs at 3 accuracy settings.
- The turn definition is checked on synthetic shapes and on how closely raw and matched versions of the same run agree (decision 011).

## Not verified
- **Review pages:** the reviewer has seen none of `step1-ranking.html`, `step3-prior.html` or `phase2-step2-generators.html`, and I looked at only a few sections of each. The newest page is rendered without the reviewer's runs; `render_review --with-prior` includes them.
- **Corridor catalog:** names are approximate (each cluster takes the name of its longest named way). There are no unit tests for the SQL and GraphHopper build.
- **Setup:** `make setup` end to end with the coastline load, and the suite on a fresh clone.
- **Platforms:** Linux/Intel machines and CI.
- **Weights:** every weight is a provisional judgment. There are no ratings.
- **Map matching:** checked visually on a handful of runs only. The usage threshold for the prior (25 m or half a way) is a judgment.


## Before and after Phase 2 step 2
Generated without the reviewer's runs; shares on routes trimmed 200 m at both ends; all values measured. The real-run gap is the best generated score minus the median real run at 3 mi, with "matches routes you run" off.

| start | mi | #1 park % before → after | #1 water % | #1 signals/mi | top 3 after | real-run gap |
|---|---|---|---|---|---|---|
| kips-bay | 3 | 3 → 1 | 0 → 66 | 10.6 → 2.2 | water out-and-back, water loop, rectangle | −16 → +9 |
| kips-bay | 4 | 4 → 4 | 26 → 26 | 9.4 → 9.4 | rectangle, rectangle, out-and-back | |
| kips-bay | 6 | 18 → 39 | 0 → 54 | 12.6 → 3.2 | water out-and-back, rectangle, rectangle | |
| flatiron | 3 | 6 → 0 | 0 → 52 | 7.0 → 2.2 | corridor out-and-back ×2, rectangle | −9 → +8 |
| flatiron | 4 | 5 → 5 | 20 → 20 | 5.5 → 5.5 | rectangle, rectangle, out-and-back | |
| astor-place | 6 | 11 → 42 | 16 → 68 | 9.4 → 1.8 | corridor out-and-back, corridor loop, rectangle | |
| upper-east-side | 3 | 60 → 83 | 76 → 97 | 2.9 → 0.0 | corridor loop, out-and-back, rectangle | +5 → +8 |
| upper-east-side | 4 | 34 → 89 | 0 → 99 | 5.3 → 0.0 | corridor out-and-back, round trip, park loop | |
| upper-east-side | 6 | 29 → 52 | 13 → 88 | 7.6 → 0.0 | corridor out-and-back, water out-and-back, rectangle | |
| williamsburg | 4 | 0 → 29 | 6 → 29 | 8.4 → 2.5 | corridor out-and-back, rectangle, rectangle | |
| dumbo | 3 | 5 → 30 | 0 → 85 | 9.3 → 0.0 | park out-and-back, corridor out-and-back, rectangle | |
| flushing-meadows | 3 | 73 → 83 | 0 → 0 | 1.1 → 0.0 | park loop, out-and-back, round trip | |
| grand-concourse | 4 | 9 → 38 | 0 → 0 | 4.3 → 0.3 | park loop, park out-and-back, water loop | |
| st-george (weak grid) | 3 | 0 → 0 | 23 → 51 | 1.5 → 0.7 | water out-and-back, rectangle, out-and-back | |
| victory-blvd (weak grid) | 3 | 67 → 67 | 0 → 0 | 0.0 → 0.0 | out-and-back ×2, round trip | |

Weak-grid starts on Staten Island are reported, not targeted. The full tables are `out/review/starts-before.md` and `starts-after.md` (git-ignored).

Decision 014 changed the 4 mi rows:
- **kips-bay 4 mi:** park 4 → 16, water 26 → 76, signals 9.4 → 2.2, with a both-ways waterfront out-and-back at #1;
- **flatiron 4 mi:** park 5 → 10, water 20 → 38, signals 5.5 → 3.3, with a corridor out-and-back at #1.

`out/review/starts-after-turnarounds.md` has all rows.

## Known issues
- **The eventual #1 can arrive late:** the first candidate arrives in 0.1–0.3 s, but the winner can take up to 10.5 s (Kips Bay 6 mi) and totals reach 18 s (decision 014). Levers: cache anchors and areas per start, and check gaps with GraphHopper in the catalog build.
- **Kips Bay 6 mi is a near tie** between a waterfront route and a rectangle under the provisional weights.
- **Staten Island scores low** (winding streets); weak-grid starts are mixed.
- **Port 8989 (resolved 2026-10-30):** `project_loop-graphhopper-1`, from the clone at `~/project_loop`, had identical config, custom models, map (same SHA-256) and Dockerfile. It is stopped, and this folder's container serves 8989; it had to be recreated with `docker compose up -d --force-recreate graphhopper` to publish the port. Starting the other clone again would take the port back.
- **Fountain data is stale** (last updated 2024-07-15, no status or season): `listed` at best (decision 004).
- **Crosswalk gaps:** crosswalks are missed wherever a route runs on a road centerline (decision 009).
- **Park share** uses Parks Properties only. Waterfront share covers Hudson River Park.
- **Start addresses:** the start must be a street address with a number; place names are refused on purpose.
- **Graph cache:** the graph is `routing/graph-cache/foot-v4`, with elevation and crossing types (`foot-v2` and `foot-v3` were deleted 2026-11-01). After changing the map or `routing/config.yml`, delete it or bump the suffix.
- **Config module:** `make_loop.py` imports `database_url` from `etl.load`; move it to a shared config module.

## Left for Phase 2
**The gate:** the reviewer's run test of the Kips Bay files above. Steps 4, 7 and 8 below are still open and are not counted in the core.

Order after decision 011. Each step ends with the review page and `pytest evals/`.
1. ~~Combined ranking with no-go zones~~ (decision 010). ~~Park and waterfront share~~ and ~~signal counts~~ (decision 011). ~~Park, water and corridor generators; round trips everywhere~~ (decision 012).
2. ~~Turnarounds by walking distance~~ (decision 014). Next: gaps checked with GraphHopper so walking distance can cross them, and caching for speed.
3. ~~Lights preference, router side~~ (decision 015). Was: A signal penalty in GraphHopper for runners who wait (needs the `crossing` encoded value and a re-import). An expected-wait estimate, labeled `estimate`, that credits a zig-zagger for turning on a red.
4. **Roadway share and the bike-lane rule.** Measure the share of a route on a road centerline where a separate sidewalk exists. The bike-lane rule has lower priority, and its purpose is narrow: never send a runner down an on-street lane such as 3rd Ave's because it is emptier. It needs NYC DOT bike-route data.
5. ~~Crowds~~ (decision 016). Next: calibrate with "crowded" reports, and find a source for paths and greenways (DOT's automated counters cover 21 path ways).
6. ~~Closures layer~~ (decision 017), with curated closures. Next: a live closure source (DOT construction closures, Parks), and showing the runner when a closure changed their route.
7. **Amenities after the ranking**: they annotate the top 3 with trust labels and don't change the order.
8. **Calibrate, then tune.** Re-run `calibrate.py` after each generator change. Tune turns and retracing only once there are ratings or more runners.

**Claude parsing stays in scope** (Phase 3). It fills `RunConstraints`, `describe()` shows the result to the runner before routing, and a validation failure becomes a clarifying question. Later phases: the API, the frontend, ratings. `docs/discovery/` is intentionally untracked.
