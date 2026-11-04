# 018: Generation speed

**Status:** proposed (2026-11-04). Steps 2 and 3 are done. Step 3 covers the plan-order tiebreak, context scoring in processes, the provisional and final top 3, and the measured decision not to simplify feature areas.

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

## Step 2 (done): the three exact changes
The reviewer approved the profile and the order on 2026-11-03.

1. **No crowd sampling without a start time** (`api/route_context.py: _crowd_fields`). The summary is known without sampling: 100% not scored, "no start time given". Stretches still sample the route, since they need each stretch's reason.
2. **Prefilters and shared samples:**
   - `crossing_counts` and `signal_positions` skip any crosswalk whose box touches no grid cell the route occupies, with one or two cells of margin. A crosswalk there can't be walked.
   - `score_context` computes the park and water shares from one set of samples (`shares`), not three.
3. **Each distinct router request is sent once per generation** (`api/scripts/make_loop.py: _Reused`). A routing failure is reused too. A request already in flight is waited for, not sent again.

**Checked:**
- **Same scores:** every candidate route at the 15 rows, both lights settings (2,350 routes), scored with and without a start time: 4,700 `ContextScores` identical to the old code, field by field.
- **Randomized unit tests:** 100 cases compare the new crossing counts, signal positions and shares against the old algorithms, kept in the tests as references.
- **Pinned top 3:** 30 of 30.

**Timing (one pass):**
- **Full pool:** median 8.5 s (from 10.4 s), max 21.5 s (from 28.2 s).
- **First candidate:** median 0.29 s, max 1.48 s (Astor Place 6 mi, "waits", still over 1 s).
- **Context scoring:** summed time down 35%, from 546–637 s to 379 s across the 30 cases.
- **Routing:** summed time unchanged. The repeated requests are mostly sent at the same moment by sibling jobs, so the second thread waits for the first. GraphHopper does less work, but the waiting thread's time still counts.
- **Noise:** the two "before" passes differ by 20% (median 9.4 s against 11.5 s), so the final before/after table will average several passes.

## Step 3 (done): tiebreak, scoring processes, provisional then final
The base is `66610dc`: the closure, the pulses and the UI-outputs format, with no step-3 changes.

**Re-pinned top 3.** It was re-pinned from that commit, because the NYU Langone closure (decision 017) changed the Kips Bay top 3:
- Kips Bay 3 mi: a new #1;
- Kips Bay 4 and 6 mi: the same routes by label, rerouted along E 34th St.

No other case changed from the original pin, so the UI-outputs line changed no other top 3.

1. **Ties broken by plan order.** `_run_prioritized` returns outcomes in plan order: top-level jobs in the order given, an anchor lookup's jobs in the order it returned them. Score ties used to go to whichever thread finished first. The Flushing Meadows pin once failed this way and passed on a rerun.
   - Two pinned cases changed label only. St. George 3 mi "zigzags" #3 and Upper East Side 4 mi "waits" #1 are the same route with the same score, built by two generators. Plan order puts the corridor source first, so the label is now "loop on unnamed waterfront path" and "out-and-back on Bobby Wagner Walk". Re-pinned.
2. **Context scoring in worker processes** (`api/scoring_pool.py`). It's the same `score_context`, so results can't change, and a waiting thread doesn't hold the interpreter lock. Each process keeps one autocommit Postgres connection.
   - **Process pool, not PostGIS:** moving the share, crossing and wait geometry into SQL would be a rewrite that could shift numbers. The pool is exact by construction.
   - **Configuration:** 5 processes with 6 generator threads, from a sweep on Upper East Side 6 mi "waits", Kips Bay 6 mi "zigzags" and Astor Place 6 mi "waits":

     | scoring | threads | pool (s) | first candidate (s) |
     |---|---|---|---|
     | inline | 4 | 26.4 / 21.3 / 14.7 | 0.47 / 1.27 / 1.71 |
     | 3 processes | 4 | 18.9 / 14.2 / 14.6 | 0.48 / 0.53 / 1.40 |
     | 3 processes | 6 | 22.8 / 20.2 / 17.8 | 0.37 / 0.42 / 0.83 |
     | 5 processes | 6 | 16.3 / 14.5 / 14.1 | 0.50 / 0.42 / 0.63 |
     | 5 processes | 8 | 20.5 / 22.7 / 23.3 | 0.48 / 0.79 / 1.51 |

3. **Simpler feature areas: measured, not done.** Replaying 150 feature-area requests:

   | area | median vertices | GraphHopper per request (alone) | same route |
   |---|---|---|---|
   | as built (~10 m) | 12 | 52 ms | 150/150 |
   | simplified to 25 m | 10 | 49 ms | 91/150 |
   | simplified to 50 m | 6.5 | 46 ms | 94/150 |

   It saves 6–12% of routing time and changes 40% of area routes. The real routing cost is contention: the same requests take 52 ms alone and about 160 ms in the pool.
4. **Provisional, then final** (the reviewer's choice, 2026-11-04). `generate_loops(on_top3=...)` streams events:
   - `top3` whenever the current top 3 changes, computed by the same `_select` as the final one, over the candidates so far in plan order;
   - `provisional` once, when every anchor lookup and anchored job (tiers 0–2) has finished;
   - `final` when the pool is done. It's identical to `result.candidates`.

   The result keeps the provisional top 3, `provisional_s`, and how many times #1 changed after the flag.

**Flag tier, measured on all 30 cases:**

| flag after | provisional, median / max | #1 changed after the flag | top 3 already final at the flag |
|---|---|---|---|
| tiers 0–2, all anchored (chosen) | 5.2 s / 17.0 s | 0 of 30 | 4 of 30 |
| tiers 0–1, along-feature anchored only | 2.2 s / 7.6 s | 11 of 30 (up to 4 times) | 1 of 30 |

**Before and after.** Before is `66610dc`; after is step 3, two passes. Provisional and #1 changes are from the pass with the flag after tiers 0–2.

| row | lights | first candidate (s) before → after | provisional (s) | final, full pool (s) before → after (pass 1 / pass 2) | #1 changes after provisional |
|---|---|---|---|---|---|
| Kips Bay 3 mi | zigzags | 0.21 → 0.27 | 3.86 | 9.5 → 5.7 / 5.5 | 0 |
| Kips Bay 4 mi | zigzags | 0.57 → 0.25 | 4.64 | 11.3 → 7.1 / 7.1 | 0 |
| Kips Bay 6 mi | zigzags | 0.62 → 0.37 | 9.36 | 17.9 → 12.4 / 12.5 | 0 |
| Flatiron 3 mi | zigzags | 0.43 → 0.24 | 3.26 | 8.0 → 6.1 / 5.2 | 0 |
| Flatiron 4 mi | zigzags | 0.37 → 0.19 | 4.69 | 10.7 → 6.6 / 7.1 | 0 |
| Astor Place 6 mi | zigzags | 0.34 → 0.42 | 8.13 | 15.3 → 9.9 / 13.7 | 0 |
| Upper East Side 3 mi | zigzags | 0.32 → 0.21 | 5.80 | 15.6 → 7.2 / 10.3 | 0 |
| Upper East Side 4 mi | zigzags | 0.36 → 0.23 | 8.47 | 16.3 → 10.8 / 15.6 | 0 |
| Upper East Side 6 mi | zigzags | 0.21 → 0.30 | 11.74 | 26.4 → 16.8 / 27.9 | 0 |
| Williamsburg 4 mi | zigzags | 0.42 → 0.34 | 4.61 | 8.4 → 7.3 / 9.9 | 0 |
| DUMBO 3 mi | zigzags | 0.31 → 0.20 | 6.11 | 9.0 → 7.7 / 10.1 | 0 |
| Flushing Meadows 3 mi | zigzags | 0.26 → 0.12 | 1.98 | 5.1 → 3.4 / 4.4 | 0 |
| Grand Concourse 4 mi | zigzags | 0.17 → 0.17 | 1.76 | 5.7 → 3.4 / 6.4 | 0 |
| St. George 3 mi | zigzags | 0.18 → 0.12 | 1.08 | 1.7 → 1.4 / 1.6 | 0 |
| Victory Blvd 3 mi | zigzags | 0.12 → 0.19 | 0.93 | 2.3 → 1.6 / 2.2 | 0 |
| Kips Bay 3 mi | waits | 0.13 → 0.29 | 4.30 | 8.1 → 6.9 / 7.5 | 0 |
| Kips Bay 4 mi | waits | 0.34 → 0.25 | 5.22 | 10.3 → 8.0 / 10.1 | 0 |
| Kips Bay 6 mi | waits | 0.57 → 0.41 | 10.52 | 20.1 → 14.4 / 17.5 | 0 |
| Flatiron 3 mi | waits | 0.53 → 0.32 | 5.12 | 11.2 → 7.3 / 7.2 | 0 |
| Flatiron 4 mi | waits | 0.92 → 0.21 | 5.71 | 15.2 → 8.0 / 10.5 | 0 |
| Astor Place 6 mi | waits | **2.68 → 0.56** | 10.55 | 20.7 → 13.4 / 17.2 | 0 |
| Upper East Side 3 mi | waits | 0.34 → 0.50 | 8.93 | 16.0 → 11.4 / 12.5 | 0 |
| Upper East Side 4 mi | waits | 0.48 → 0.48 | 14.74 | 20.9 → 18.1 / 16.5 | 0 |
| Upper East Side 6 mi | waits | 0.61 → 0.65 | 16.97 | 25.5 → 23.5 / 24.0 | 0 |
| Williamsburg 4 mi | waits | 0.46 → 0.35 | 6.70 | 8.4 → 10.4 / 8.3 | 0 |
| DUMBO 3 mi | waits | 0.24 → 0.50 | 10.46 | 8.0 → 13.4 / 9.1 | 0 |
| Flushing Meadows 3 mi | waits | 0.23 → 0.53 | 4.16 | 4.9 → 6.5 / 4.3 | 0 |
| Grand Concourse 4 mi | waits | 0.22 → 0.62 | 3.99 | 5.5 → 6.8 / 5.4 | 0 |
| St. George 3 mi | waits | 0.14 → 0.19 | 1.56 | 1.5 → 2.2 / 2.0 | 0 |
| Victory Blvd 3 mi | waits | 0.16 → 0.31 | 1.94 | 2.4 → 2.9 / 2.4 | 0 |

**Against the targets:**
- **First candidate under 1 s at all 30 cases: met.** Max 0.65 s in pass 1, 0.83 s in pass 2, against 2.68 s before.
- **Top 3 settled in about 3 s: not met.** The provisional flag comes at a median 5.2 s and a max 17.0 s. The faster flag (tiers 0–1, median 2.2 s) is wrong about #1 in 11 of 30 cases.
- **Full pool in about 8 s: not met.** Median 9.9 → 7.3 s and 8.7 s over the two passes; max 26.4 → 23.5 s and 27.9 s.
  - **The runs are noisy.** The same row varies by up to 60% between passes, as Upper East Side 6 mi "zigzags" did (16.8 s and 27.9 s). Another session was running evals against the same GraphHopper at the time.
  - **The heavy rows** (Upper East Side and 6 mi) stay at 12–28 s, limited by routing contention.
- **Top 3: unchanged.** The pinned eval passes after the two label re-pins, and the final top 3 is identical to the pin in both passes.

**What's left for about 8 s at the heavy rows:** fewer router calls per job (`_fit` makes about 3.3; a better first guess at scale would cut that), and measuring GraphHopper's own thread and CPU limits while nothing else is running.
