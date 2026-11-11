# 031: `candidates` outlines and `reach_m` for the map while routes build

**Status:** accepted (2026-11-08). Phase 3, step 7b, asked for by Jared for the UI. Extends 029.

## Decision
- **The `candidates` event:** each route that passes the rules is streamed as a light outline, from the engine's
  existing `on_candidate` hook, from right after `parsed` until `final`. The event is `{route_id, elapsed_s,
  candidates: [{id, kind, points}]}`.
  - Outlines are cut with Douglas-Peucker, using the smallest tolerance that leaves at most 40 points
    (`api/geometry.outline`), so corners and ends survive. Coordinates are rounded to 5 decimals, about 1 m.
  - An outline is only for drawing; nothing is measured on it.
  - A candidate's `id` is the id it keeps in `top3`, so the app can grow an outline into a route.
  - There is one event per candidate. `candidates` is a list, so batching can come later without a contract
    change.
- **`parsed.reach_m`:** half the longest the run may be (the distance plus its tolerance), in meters, to 10 m. A loop
  or an out-and-back has to turn back by then. It is null with no distance yet, and for an A-to-B run until step 8
  gives it a meaning.
- The parse grader allows `reach_m` in `parsed`; it's a contract field, not free text.

## Numbers (live, Kips Bay Library stand-in)
| Request | `reach_m` | `candidates` events | Bytes per event (median / max) | All outlines | Points per outline (median, range) |
|---|---|---|---|---|---|
| "3 mi loop" | 2,530 | 95 | 993 / 1,085 | 89 KB | 36, 18–40 |
| "6 mi, mostly waterfront" | 5,070 | 85 | 972 / 1,083 | 80 KB | 35, 19–40 |
| "10 mi long run" | 8,450 | 56 | 979 / 1,094 | 53 KB | 35, 23–40 |

- When warm, the first outline arrives about 0.5 s after `parsed`.
- For comparison, a `top3` event is 9–18 KB, because it carries full route lines, and `final` is 76–235 KB.

## Tests
- `api/tests/test_geometry.py`: at most 40 points with ends kept, points stay on the route, corners survive, a short
  route is kept whole.
- `api/tests/test_engine.py`: outlines stream from worker threads, with the ids they keep in `top3`.
- `api/tests/test_answers.py`: `reach_m` for 6 mi, 5 km, a 3–4 mi range, an A-to-B run and a missing distance, and
  the same after a chip edit.
- All 850 unit tests pass.
