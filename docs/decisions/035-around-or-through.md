# 035: Around or through — a via is passed or lapped

**Status:** accepted (2026-11-09). Asked for by Jared after step 9 (decision 034), before step 8b. Extends 034 (via
places) and 033 (spans).

## Decision
- **A via has a mode:** `through` (pass it, decision 034's rule) or `around` (run a full lap of it).
- **Claude records the word; code sets the mode.** The extraction tool's via items get `word`, the runner's own words
  for how the run uses the place, copied as typed. Prompt `parse_v5` is v4 plus one sentence about it.
  - Code (`api/loops.py`) reads the word:
    - A word with "through", "via", "past", "across", "in", "on" or "along" (and the like) means `through`.
      "Loop through" is through.
    - Otherwise "around", "loop", "lap" or "circle" means `around` ("loop of", "lap of", "2 laps around").
    - No word: a known running loop named on its own means `around`. That covers the Reservoir as a place, and each
      loop's own names ("the Prospect Park loop", "McCarren track").
    - Everything else is `through`, so "a few miles in the park" (R09) still passes Prospect Park.
  - Claude never sets the mode, the loop or a length.
- **The curated list** (`etl/curated/running_loops.json`, proposed for Jared's review):

| Loop | Means its lap when named alone | Published | Source | Measured from OSM | Direction |
|---|---|---|---|---|---|
| The Reservoir running track | yes (the Reservoir) | 1.58 mi | [Central Park Conservancy](https://centralparknyc.org/locations/stephanie-and-fred-shuman-running-track) | 1.57 mi (one closed way, 179679714) | counterclockwise (posted) |
| The Central Park drive loop | by its names ("Central Park loop") | 6.1 mi | [Central Park Conservancy running guide](https://centralparknyc.org/activities/running) | 6.05 mi (outer ring of East, West and Center Drive) | counterclockwise (traffic) |
| The Prospect Park drive loop | by its names ("Prospect Park loop") | 3.35 mi | [Citi Bike: Prospect Park Loop](https://citibikenyc.com/rides/prospect-park-loop) | 3.49 mi (+4%; outer ring of East and West Drive) | counterclockwise (traffic) |
| The McCarren Park track | by its names ("McCarren track") | 400 m | [Greenpointers on the 2019 reopening](https://greenpointers.com/2019/01/29/mccarren-park-track-reopens-following-improvements) | none | counterclockwise |

  - **Prospect Park measures 4% long.** The drive ring in OSM is 3.49 mi, against the 3.35 mi most sources give.
    Their figure is probably measured on the inside lane, or without the bend at Grand Army Plaza. Loop counts the
    routed lap.
  - **McCarren's track can't be run yet.** OSM maps it only as an area (`leisure=track`, way 4102021), with no path on
    it, so GraphHopper can't route a lap. "McCarren track" passes McCarren Park instead, with a can't-do line
    (`gap: "lap"`, rule 3).
    - The fix is to add the track's outline as a footway in `routing/prepare_osm.py` and re-import GraphHopper.
    - That changes the routing graph near McCarren Park, which R01 ends at, so it's Jared's call.
- **Where a loop has no curated ring:** around a park or water off the list runs the outline of its biggest polygon.
  Around a street, path or point passes it instead, with a can't-do line.
- **The ring is data, built in code.** `etl/build_running_loops.py` writes `running_loops`. A loop is kept only if:
  - its ring is within 8% of the published length;
  - a GraphHopper lap through points on it covers at least 90% of the ring.

  All three routable loops covered 99–100%.
  - `drive_ring` joins dangling ends within 45 m of another drive (10 m for Prospect Park, where a wider join picks
    up a spur). It then takes the outside of the faces the drives enclose, which leaves out the cross drives.
- **A lap** is a run of waypoints on the ring, in the loop's direction, from the point nearest the way in and back
  to it:
  - a point every 200 m, plus every corner sharper than 45° (14 points for the Reservoir, 50 for Central Park);
  - the hard rule: a route runs along at least 90% of the ring, within 30 m (`misses_lap` otherwise);
  - the lap counts toward the distance;
  - no out-and-backs through a lap (it would run twice);
  - feature anchors only on vias passed, not lapped.
- **Distance:** an around via with no distance said sets none (not the usual distance). The engine builds the lap
  plus the shortest way there and on, and the distance chip reads "The lap and the way there".
  - Too short for the lap and the way there: the engine asks, as for vias: "A lap of the Reservoir running track and
    the way there takes at least X mi. Make it X mi?".
  - `RunConstraints` accepts no distance when a via is around.
- **Contract:**
  - via chips and `constraints.via_places` carry `mode`; known loops also carry `loop`;
  - new chip text "A lap of {name}, {borough}";
  - new can't-do gap `lap`.
- **Evals:**
  - rule R20 and grading rule 9 (each via's mode);
  - R02 keeps `mode=around`, and its route eval is a full Reservoir lap;
  - P50 ("Loop of Prospect Park from Grand Army Plaza", context C2) joins as the 51st case, with a route eval.

## Results (live)
- **R02** after "West side": 86th St at Central Park West, a full Reservoir lap (100% of the track),
  then Central Park South. 3.46 mi, the shortest such way (no distance said). Final in 2.4 s.
- **P50:** Grand Army Plaza, a full lap of the drive (100%), and back. 3.97 mi, a loop. Final in 0.5 s.
- R03, R09 and P49 are unchanged (through).
- All 145 live route evals pass, so the pinned loop top 3s didn't move. One is skipped: the personal-runs eval, which needs the git-ignored run data.

## Parse evals (Haiku 5.5, low effort, three runs of the 51 cases)
| Prompt | Pass per run | Cases passing all 3 | Cost / parse | Claude latency, median |
|---|---|---|---|---|
| v4 (decision 033, 50 cases) | 49 / 47 / 48 | 47 of 50 | $0.00062 | 3.25 s |
| **v5 (51 cases)** | **47 / 49 / 50** | **46 of 51** | **$0.00061** | **3.29–3.50 s** |

- P50 and R02 passed all three runs.
- The five that missed at least once:
  - **H04:** in code, step 11.
  - **H02:** one API call error.
  - **P28:** a stray can't-do line, once.
  - **R06 and R09:** a chip without its span, once each.
- None of the misses involve the via word.
- This round cost about $0.09, logged in `llm_calls`.

## Tests
- `api/tests/test_loops.py`:
  - the word sets the mode;
  - the curated list's rules;
  - McCarren and a street fall back with a can't-do line.
- `api/tests/test_via.py`:
  - lap points run the whole ring from the nearest point, in its direction;
  - every route runs the lap and fits the distance;
  - a route that only touches the ring is rejected.
- `api/tests/test_geometry.py`: covered share, length, orientation.
- `api/tests/test_engine.py`: a lap too long for the distance asks; no distance means the lap and the way there.
- `etl/tests/test_running_loops.py`: the drive ring joins small gaps and leaves out a cross drive.
- `api/tests/test_parse.py`: P50 with the right extraction passes; the harness checks rule 9.
- `evals/routes/test_via.py`: R02 (a lap) and P50.
