# 038: Past routes and planned runs — the last of Phase 3

**Status:** accepted (2026-11-09). Phase 3, step 11 (the brief's step 10). Before this, a past route was a blocking
can't-do line and a planned second run wasn't built.

## Decision
- **A past route is found by its id, and its line comes from `saved_routes`** (`api/past_routes.py`).
  - The phone's recent-routes list carries the id Loop gave each route: `r_xxxxxxxx.N`, or a build id for its #1.
  - The stored `final` (decision 030) has every top-3 route's line.
  - Only names and ids ever go to Claude, never a line.
- **"Rebuilt for now" means the same line, run now.**
  - The route starts where it started, and runs as a lap along its own line (decision 035's rule): waypoints every
    200 m and at every sharp corner, and the rebuilt route must run along 90% of the old line.
  - Closures, no-go zones, avoids and crowds are as of now.
  - A loop or out-and-back is a closed lap; a run that ended elsewhere is an open line to its end (an A-to-B build).
  - **"The other direction"** runs the line backwards.
  - **"Longer" (after "How much longer?")**: the distance is the recent route's `distance_mi` plus the answer. The
    lap's detours add the extra, still along 90% of the old line.
  - **Not on file:** no route, and a note (`past_route_not_found`, rule 3).
- **"Skip the ferry part" is matched in code (H04).**
  - Claude records the runner's word ("ferry"). Code finds the ferry landings (`pulse_sources`, NYC Ferry GTFS and
    the SeaStreak timetable) within 100 m of the line of every route the request may mean. That's both of last
    week's runs while "Which one?" is open, then the one picked.
  - Each landing becomes an area avoid with its coordinates and source: "E 34th St ferry landing". Two operators
    at one pier are one avoid.
  - The engine makes a 120 m circle around each landing a no-go zone for the request.
    - 120 m because the landing point is out on the pier, about 55 m from the esplanade. At 60 m, the rebuilt
      route still ran past it, 69 m away.
  - The past route's waypoints and coverage leave out the stretch within 160 m.
  - No landing along the route: the word stays as said, and the engine's can't-do line says it can't avoid it.
- **A planned run is built after the first** (`api/server.py`; D6):
  - It's built from its own start (home on a later day, R16), for its own day and time, so crowds are for Saturday
    at 07:00.
  - It's stored like any build. Only a `planned` event is streamed for it: `{route_id, date, chips, summary,
    constraints, notes}`, then `done`.
  - If it can't be built now, `route_id` is null with a note (`planned_not_built`), and the app builds it on the day.
- **Prompt `parse_v6` adds one sentence:** a part of a past route to skip ("skip the ferry part") is an avoid,
  named by the runner's word. On v5, Haiku left it out of all three runs. With it, H04 passed 5 of 5 alone and all
  three full runs.
- **Nothing in Phase 3 is left for later:** the engine's "later" list is empty, and nothing blocks a build.
- **Two fixes along the way:**
  - **Coverage now counts each segment on its own.** One intersection over a whole out-and-back line merges its
    two directions and counts the path once, so a perfect rebuild of an out-and-back scored 47%. Rings (decision
    035) are unchanged.
  - **A lap skips spots it must miss:** `Via.skip` takes the waypoints out of the avoided circle, and the stretch
    out of the line to cover.
- **Eval fixtures:**
  - `evals/past_routes.py` routes the contexts' three recent routes through public waypoints near the Kips Bay
    Library stand-in. They're never a real run.
  - It stores them in `saved_routes` as `fixture` builds under their ids (`rt_a`, `rt_b`, `rt_c`), tuned to the
    listed 3.0, 4.0 and 3.1 mi.
  - The route evals and live parse evals seed them first.

## Results (live, Kips Bay)
| Case | Built | Along the old line | Notes |
|---|---|---|---|
| H01 "same as Tuesday" | out-and-back, 2.99 mi | 100% | `rt_a` (3.0 mi), 1.2 s |
| H02 "my usual but longer", +1 mi | three out-and-backs, 4.03–4.09 mi | 100% | 8.0 s |
| H03 "the river one, other direction" | out-and-back, 2.99 mi | 100% | reversed |
| H04 "skip the ferry part", Tuesday's route | out-and-back, 3.04 mi | 88% (90%+ of the rest) | 128 m from the landing at its closest |
| H05 "my usual" | out-and-back, 2.99 mi | 100% | the most-run route |
| P45 "5k tonight and a 10 miler sat" | 3.1 mi now; 10 mi on Saturday from home | — | `planned` after `final` |

## Parse evals (Haiku 5.5, low effort, three runs of the 51 cases)
| Prompt | Pass per run | Cases passing all 3 | Cost / parse | Claude latency, median |
|---|---|---|---|---|
| v5 with step 11's code | 49 / 48 / 48 | 45 | $0.00061 | 3.2–3.4 s |
| **v6** | **46 / 50 / 47** | **44** | **$0.00060** | **3.2–3.3 s** |

- H04 now passes every run; it was the case that waited on this step.
- The misses are spread over seven cases, none about past routes:
  - P49 twice: the East River path read as the Esplanade, so the via place and surface differ;
  - P50 twice: a stray can't-do line, not seen again in three fresh parses;
  - R05 twice: `familiar=new` from "new to this area";
  - R01, P38, P04 and R11 once each.
- v6's per-run range (46–50) overlaps v5's (47–50).
- 44 passing all three is exactly step 5b's bar.
- This round cost about $0.20, logged in `llm_calls`.
- All 156 live route evals pass. One is skipped: the personal-runs eval, which needs the git-ignored run data.

## Tests
- `api/tests/test_engine.py`:
  - a past route rebuilt from its own start;
  - the other direction;
  - longer;
  - no line on file;
  - an avoid with coordinates is a no-go circle.
- `api/tests/test_answers.py`:
  - longer is the past distance plus the answer;
  - the ferry part is matched along the routes it could mean;
  - a route with no ferry keeps the words.
- `api/tests/test_server.py`:
  - a past route builds;
  - a planned run is built for its day and sent after `final`, and stored;
  - one that can't be built says so.
- `api/tests/test_via.py`: a lap skips a spot it must miss.
- `api/tests/test_geometry.py`: coverage counts an out-and-back both ways.
- `evals/routes/test_past_routes.py`: H01–H05 and P45 end to end.
