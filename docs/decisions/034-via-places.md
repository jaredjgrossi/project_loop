# 034: Via places — through or along the place the runner named, a hard rule

**Status:** accepted (2026-11-09). Phase 3, step 9 (the brief's step 8). Builds on 012 and 014 (anchored generators),
026 (places), 032 (A to B) and 033 (spans).

## Decision
- **Every route passes every via place** (`generate._evaluate`, the "through" rule, a hard rule like a no-go zone).
  - Each via's shape comes from the places table: a park's or a lake's outline, a path's or a street's lines within
    3 km of the point the parse chose, or the point itself.
  - A route passes when it comes within 30 m of an outline, 60 m of a line, or 150 m of a point.
  - `api/geometry.passes_through` measures on a local flat projection, in meters.
- **The shortest way through comes first,** as for an end: start, the vias in order, then back (or on to the end).
  A distance shorter than that gets the engine's question: "Going through Hudson River Greenway takes at least 4.3
  mi. Make it 4.3 mi?". The answer is settled in code, with no second Claude call.
- **Candidates for a run back to the start** (`api/via.py`, run by `generate_loops` with `only_anchored`):
  - **The corridor-anchored generators** of decisions 012 and 014, on the park, waterfront and corridor features
    that overlap a via. "A few miles in the park" runs along Prospect Park's drives; the reviewer's own ways and the
    plain grid generators are off.
  - **Loops through the vias in order,** closed by a waypoint on an ellipse on either side, before or after the
    vias, sized to the distance and rescaled to fit.
  - **An out-and-back through the vias** to a turnaround beyond the last one.
  - **The shortest way through,** when it fits the distance.
- **With an end too** (R02), `generate_a_to_b` takes the vias: the direct way through them, and detours between
  the last via and the end. Feature detours are off, because they don't pass the vias.
- **"The whole way" stays a can't-do line (G1).** A street the whole way isn't a via (decision 028); a path the
  whole way (P49) is a via, with the line.
- `via_places` is off the can't-build list. Along-avoids and past routes are still on it.

## Numbers (live; the parser's rules on the ideal extractions, real places, reviewer's runs off)
| Case | Result | First top 3 | Final |
|---|---|---|---|
| R02, after "West side" | the shortest way through the Reservoir to Central Park South, 2.12 mi, 92% park | 0.5 s | 1.0 s |
| R03, 3 mi from Kips Bay | asks: "Going through Hudson River Greenway takes at least 4.3 mi. Make it 4.3 mi?" | — | — |
| R09, after "6 mi", from Grand Army Plaza | #1 loop through Prospect Park, 5.86 mi, 59% park; #2 out-and-back on East Drive; best of 24 | 0.4 s | 5.4 s |
| P49, 15 mi | #1 out-and-back on the waterfront, 14.93 mi (21% waterfront, 14% path); best of 7 | 2.8 s | 17.2 s |

## Tests
- `api/tests/test_geometry.py` (3 more): a point within the tolerance, touching a park, along part of a path.
- `api/tests/test_via.py` (7): every route passes the via and fits; loops and an out-and-back; a shape said keeps
  that kind; two vias; a route that misses the via is rejected; only features on a via anchor; a park is passed by
  touching it.
- `api/tests/test_a_to_b.py` (1 more): an A-to-B run through a via passes it and fits.
- `api/tests/test_engine.py` (3 more): a far via asks, with its name; a loop through a via passes it; two names.
- `evals/routes/test_via.py` (4, live): R02, R03, R09 and P49 as above.
- The pinned top-3, rejected-route and A-to-B evals pass, 35 of 35, so no loop or A-to-B ranking changed.
- All 912 unit tests pass.
