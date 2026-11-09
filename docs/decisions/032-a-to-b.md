# 032: A to B — the shortest-way check, then detours that still reach water, parks and corridors

**Status:** accepted (2026-11-08). Phase 3, step 8 (the brief's step 7). Builds on 012 (anchors), 018 (streaming),
029 (the API) and 031 (candidates).

## Decision
- **The shortest way comes first.** The engine routes start to end with the same router as everything else: around
  no-go zones and closures, with the runner's lights setting.
  - **No distance:** the shortest way is the target. The distance chip says "Shortest way".
  - **A distance that can't reach the end, even at its tolerance:** the engine asks before anything streams but
    `parsed` (rule 3). The `question` event has `from: "engine"`: "The shortest way there is 4.5 mi. Make it
    4.5 mi?". The offer is the shortest way rounded up to 0.1 mi, so the answer always reaches the end.
  - **The answer** is a said distance, settled in code like a parser question's (decision 029), with no second
    Claude call. On a chip edit, which has no extraction, the answer edits the constraints instead.
- **Candidates** (`api/a_to_b.py`):
  - **The direct route,** the shortest way itself, offered only when it fits the distance. Otherwise, at 8 mi, a
    4.5 mi route was the first thing on the map.
  - **Detours through one waypoint** on an ellipse with the start and end as foci, at six angles on both sides of
    the straight way (not on the axis, which would overshoot and come back). The ellipse is sized from the extra
    distance and the shortest way's street factor, then rescaled to fit, as loops are.
  - **Detours along a feature:** the same OSM anchors loops use (parks, waterfront, catalog corridors; decision 012)
    and the runner's own ways when the prior is on. Two families: out from the start to a feature, along it, then to
    the end; or to the far end of a feature near the end, along it to its entry, then in. They are routed preferring
    the feature's area, and the point along it is picked so the estimate fits the distance. A feature whose best
    estimate misses the distance by more than 15% isn't routed at all: a small park can't absorb 3.5 extra miles,
    and those jobs were delaying the first route that fits.
  - The ellipse detours fit any distance, so they run with the first anchored tier and a fitting route arrives
    early.
- **A new route kind, `a_to_b`.** It's ranked like an out-and-back: turns, straight runs, park and water, lights,
  familiarity and crowds, with no loop shape and no retracing score. A new hard rule rejects an A-to-B route that
  retraces more than 25% (provisional), because a detour that doubles back isn't a way there. No-go zones and
  closures apply as everywhere; closures are loaded around both ends.
- **Shared plumbing:** `generate_loops`' tail is now `run_and_finish`, used by both generators: the prioritized jobs,
  streaming the top 3, the provisional flag, selection, "Best of N" and the pool. The loop tests and the pinned top 3
  are unchanged.
- **`end_place` is off the can't-build list.** Via places, along-avoids and past routes still build nothing yet.
- `reach_m` stays null for A-to-B runs.

## R01 end to end (live, through the API, Claude parse)
"Today, we're doing 8 miles on the water, ending at McCarren Park":
- `parsed` arrives at 3.0–4.4 s, with the end, 8 mi, today and park or water chips, and no can't-do line.
- The first route that fits (7.58 mi) arrives about 2 s after `parsed`.
- `final` comes at 5.5 s of engine time: #1 along the waterfront to the end, 7.63 mi; best of 7.
- Before the two changes above, the first fitting route took 6.7 s and `final` 11.2 s, with the same final top 3.
- That is slower than loops, whose first route comes 0.3–0.6 s after `parsed`: the shortest-way call and the detour
  rescaling come first.
- "2 mi run to McCarren Park" gets the engine question at 3.0 s. Answering "a" builds the shortest way (4.46 mi) in
  0.7 s, with no Claude call.

## Numbers (live, Kips Bay Library stand-in to McCarren Park, reviewer's runs off; before the two speed changes)
| Request | Result | First top 3 | Final |
|---|---|---|---|
| 8 mi, park or water | #1 along the waterfront to the end, 7.63 mi (28% waterfront, 3% park); #2 along the waterfront from the start, 8.34 mi; best of 7 | 0.8 s | 8.8 s |
| 6 mi | #1 along the waterfront from the start, 5.76 mi (31% waterfront); best of 7 | 0.3 s | 6.7 s |
| no distance | the shortest way, 4.46 mi | 0.1 s | 0.5 s |
| 2 mi | asks: "The shortest way there is 4.5 mi. Make it 4.5 mi?" | — | — |

## Tests
- `api/tests/test_a_to_b.py` (9): the question rule and the rounded offer; the ellipse keeps its straight-line sum;
  the direct route at the shortest distance; every route runs start to end; detours fit a longer distance; a
  waterfront detour passes the entry; a doubling-back route is rejected; streaming; no loop-shape score.
- `api/tests/test_engine.py` (3 more): the engine asks before anything streams; no distance gives the shortest way;
  a longer distance detours to fit.
- `api/tests/test_server.py` (3 more): an A-to-B run gets its end and builds; the engine asks, and the answer
  builds at the new distance with no second Claude call; an engine question on a chip edit edits the constraints.
- The pinned top-3 and rejected-route evals pass, 32 of 32, so no loop ranking changed with the shared
  `run_and_finish`.
- `api/tests/test_a_to_b.py` also checks that the direct route is offered only when it fits, and that a feature
  too small for the distance isn't routed.
- `evals/routes/test_a_to_b.py` (3, live): Kips Bay to McCarren Park at 8 mi; an end too far for 2 mi asks; no
  distance gives the shortest way.
- All 868 unit tests pass.
