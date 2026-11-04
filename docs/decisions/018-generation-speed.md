# 018: Generation speed

**Status:** profiling done, no engine change yet (2026-11-03). The reviewer reviews the profile below before any change.

## Target
- **Full candidate pool** in about 5 s.
- **First candidate** under 1 s.
- **Where:** at all 15 review rows, with both lights settings.
- **No ranking weight changes.** The top 3 at every row stays the same, or any change is explained.

## The guard: today's top 3, pinned
`evals/routes/test_pinned_top3.py` checks the top 3 at all 30 row and lights cases against `evals/routes/pinned_top3.json`. Each entry pins the label, kind and a fingerprint of the route: a hash at about 10 m precision. No geometry is stored. Two full passes on 2026-11-03 gave an identical top 3 in all 30 cases. So generation is deterministic, and the pin can be exact.

## Profile (before), `evals/routes/time_generation.py`
Same generation as the evals: default zones, known closures, the reviewer's runs on, top 3. Two passes, after a warm-up.

**Summary:**
- **Full pool:** median 10.4 s, max 28.2 s (Upper East Side 6 mi, "waits"). 24 of 30 cases are over 5 s.
- **First candidate:** median 0.3 s. One case misses 1 s: Astor Place 6 mi with "waits" (1.66 s and 2.34 s).

| row | lights | first candidate (s), pass A / B | full pool (s), pass A / B | jobs |
|---|---|---|---|---|
| Kips Bay 3 mi | zigzags | 0.26 / 0.19 | 9.4 / 11.5 | 98 |
| Kips Bay 4 mi | zigzags | 0.48 / 0.57 | 11.1 / 16.9 | 96 |
| Kips Bay 6 mi | zigzags | 0.56 / 0.61 | 18.9 / 17.5 | 96 |
| Flatiron 3 mi | zigzags | 0.30 / 0.22 | 8.4 / 8.5 | 88 |
| Flatiron 4 mi | zigzags | 0.21 / 0.25 | 10.3 / 12.8 | 92 |
| Astor Place 6 mi | zigzags | 0.35 / 0.37 | 15.0 / 19.3 | 96 |
| Upper East Side 3 mi | zigzags | 0.26 / 0.29 | 15.1 / 17.1 | 109 |
| Upper East Side 4 mi | zigzags | 0.47 / 0.44 | 21.0 / 20.8 | 115 |
| Upper East Side 6 mi | zigzags | 0.35 / 0.37 | 25.0 / 26.7 | 115 |
| Williamsburg 4 mi | zigzags | 0.39 / 0.29 | 7.3 / 10.0 | 72 |
| DUMBO 3 mi | zigzags | 0.39 / 0.31 | 8.4 / 10.8 | 100 |
| Flushing Meadows 3 mi | zigzags | 0.22 / 0.27 | 4.6 / 5.9 | 80 |
| Grand Concourse 4 mi | zigzags | 0.25 / 0.30 | 5.2 / 6.9 | 72 |
| St. George 3 mi | zigzags | 0.18 / 0.35 | 2.0 / 2.4 | 62 |
| Victory Blvd 3 mi | zigzags | 0.15 / 0.24 | 2.5 / 3.6 | 54 |
| Kips Bay 3 mi | waits | 0.17 / 0.20 | 8.2 / 10.4 | 98 |
| Kips Bay 4 mi | waits | 0.51 / 0.35 | 10.6 / 12.1 | 96 |
| Kips Bay 6 mi | waits | 0.68 / 0.73 | 15.4 / 19.0 | 96 |
| Flatiron 3 mi | waits | 0.20 / 0.25 | 8.1 / 11.5 | 88 |
| Flatiron 4 mi | waits | 0.90 / 0.96 | 12.0 / 14.1 | 92 |
| Astor Place 6 mi | waits | **1.66 / 2.34** | 15.1 / 18.7 | 96 |
| Upper East Side 3 mi | waits | 0.22 / 0.23 | 13.7 / 16.1 | 109 |
| Upper East Side 4 mi | waits | 0.33 / 0.41 | 17.9 / 22.2 | 115 |
| Upper East Side 6 mi | waits | 0.57 / 0.90 | 24.1 / 28.2 | 115 |
| Williamsburg 4 mi | waits | 0.63 / 0.58 | 7.6 / 10.6 | 72 |
| DUMBO 3 mi | waits | 0.30 / 0.42 | 9.3 / 11.4 | 100 |
| Flushing Meadows 3 mi | waits | 0.26 / 0.39 | 4.9 / 5.7 | 80 |
| Grand Concourse 4 mi | waits | 0.24 / 0.31 | 5.4 / 6.9 | 72 |
| St. George 3 mi | waits | 0.22 / 0.39 | 1.9 / 2.4 | 62 |
| Victory Blvd 3 mi | waits | 0.18 / 0.21 | 3.1 / 2.9 | 54 |

## Where the time goes
The pool runs about 100 jobs on 4 worker threads. The workers are busy the whole time: the summed time inside the pool divided by 4 matches the wall clock (Upper East Side 6 mi: 97 s summed, 25 s wall). So the pool time is just the total work divided by 4.

Share of the summed time, all 60 runs:

| part | share | per call | calls per row |
|---|---|---|---|
| context score (park/water, signals, wait, familiar, crowds) | **43%** | 0.15 s alone, **0.44 s inside the pool** | 30–110 |
| GraphHopper, routes with a feature area (anchored routes) | **36%** | 0.16 s | 65–260 |
| GraphHopper, plain routes (rectangles, out-and-backs) | 16% | 0.07 s | 50–145 |
| GraphHopper, round trips | 3% | 0.06 s | 13–29 |
| anchor lookups (corridors, parks, water, the runner's own) | 2% | — | 4 |

**Context scoring is mostly pure-Python geometry,** not the database. Upper East Side 6 mi, 104 routes, each part timed alone:

| part | median per route |
|---|---|
| all four Postgres queries, with parsing | 11 ms |
| crossing counts (about 1,000 crossings near the route) | 49 ms |
| crowd sampling, with **no start time** (the result isn't used) | 30 ms |
| park and water shares | 20 ms |
| expected wait at lights | 16 ms |
| "matches routes you run" share | 8 ms |
| **total** | **154 ms** |

Inside the pool the same call takes about 0.44 s. Four threads share Python's interpreter lock, so this CPU work queues behind other threads instead of running in parallel.

**Routing:**
- **Calls per job:** about 3.3. `_fit` rescales until the distance is within tolerance.
- **Feature-area routes cost twice as much** as plain ones (0.16 s against 0.07 s). Each carries up to 25 park or waterfront polygons, which GraphHopper checks per edge.
- **Repeats:** 6–14% of requests are identical to an earlier request in the same generation (Upper East Side 6 mi 6%, Kips Bay 4 mi 14%, DUMBO 3 mi 11%).

**Caching anchors and corridor lookups per start** would save at most 2%. That lookup isn't where the time goes.

## Proposed changes, in order (not started)
Each one is checked against the pinned top 3 and re-timed.

**Should give exactly the same results:**
1. **Skip crowd sampling when there's no start time.** It's about 20% of each context score. Check: same `ContextScores` on every pool route.
2. **Faster context geometry.** Prefilter crossings, parks and shoreline by the route's bounding box or a grid index before the exact tests. Check: same numbers on every pool route, plus the existing unit tests.
3. **Reuse identical router requests within one generation.** That's 6–14% of router calls.

**Could change results; the pinned eval decides:**

4. **Smaller feature areas sent to GraphHopper:** simplified polygons, or fewer parts. It targets the biggest routing cost.
5. **Real parallelism for context scoring:** a process pool, or the share and count work moved into PostGIS. More GraphHopper workers too, if the server has headroom.
6. **Skip context scoring for candidates that can't make the top 3.** That's a candidate whose best possible score, with every context dimension perfect, is below three distinct candidates of its kind already scored. The pool would then hold some unscored candidates, labeled as such.

**Expected:** changes 1–3 alone should cut roughly 30%. Upper East Side 6 mi would drop from about 26 s to about 18 s. Reaching about 5 s there needs 4, 5 or 6.
