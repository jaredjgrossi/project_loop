# 015: The lights preference, router side. A signal penalty for runners who wait; an expected-wait estimate with zig-zag credit

**Status:** accepted and implemented (Phase 2, 2026-11-01). Implements 009's plan for `RunConstraints.lights`. No ranking weights changed.

## Context
Decision 009 found that GraphHopper can penalize signalized crosswalks per request, but turn penalties push runners into the roadway. It planned two things: a signal penalty for runners who wait at lights, and an expected-wait estimate that credits a zig-zagger for turning on a red. Until now `lights` only changed ranking weights (010).

## Decision
**1. Crossing data in the graph.** `routing/config.yml` adds the `crossing` encoded value (OSM crosswalk type per edge) and re-imports into `routing/graph-cache/foot-v4`. The `foot-v3` cache was deleted once `foot-v4` was confirmed serving routes with elevation and crossing details.

**2. Runners who wait: a signal penalty in every request** (`api/lights.py`, `api/scripts/make_loop.routers_for`).
- **The rule:** `crossing == TRAFFIC_SIGNALS → priority × 0.2` (`SIGNAL_PRIORITY`, provisional) is merged into the custom model of every route, round-trip and feature-area request.
- **Zig-zaggers get no penalty.**
- **This is a router setting, not a ranking weight.** It changes which paths routes take, not how candidates are scored.

Why ×0.2: decision 009's router test, rerun on the new graph from the Kips Bay review start (a public stand-in near 009's original start) to E 72nd St & York Ave:

| Signal priority | km | Signalized crosswalks | per km | On road centerlines |
|---|---|---|---|---|
| none | 4.12 | 39 | 9.5 | 5% |
| × 0.5 | 4.16 | 35 | 8.4 | 2% |
| × 0.3 | 4.16 | 35 | 8.4 | 2% |
| **× 0.2** | **4.72** | **21** | **4.4** | **1%** |
| × 0.1 | 5.23 | 16 | 3.1 | 7% |
| × 0.05 | 5.59 | 14 | 2.5 | 7% |

×0.2 roughly halves signals for 15% more distance, and keeps the route on sidewalks and paths. Stronger penalties creep back onto road centerlines, though less than 009's turn penalties did (76%).

**3. Expected wait at lights, labeled `estimate`, for both kinds of runner** (`api/lights.expected_wait`). It is reported in the CLI, the review page and the candidate pool's metric vector. **It is not scored:** making it a ranking dimension, or replacing signals per mile with it for zig-zaggers, would change the ranking and is left for the ratings.

**Assumptions** (all provisional):
- **Signal timing:** a signal cycle is 90 s, with DON'T WALK, including the flashing phase, for 60% of it. A runner arriving at a random moment waits 0.6² × 90 / 2 = **16.2 s per signalized crosswalk** on average. NYC cycles and splits vary by intersection, and none of this comes from DOT signal timing data.
- **Zig-zag credit:** at a signalized crosswalk, a zig-zagger has a same-length alternative when all four of these hold:
  - the start has a street grid (grid strength at or above 0.45, as the generator uses);
  - over the next 400 m the route runs monotonically, within 15% of the grid-aligned L1 distance, so it doesn't double back;
  - it still needs at least one block (80 m) along both grid axes;
  - so a staircase that takes the green direction first is the same length.

  A credited crosswalk costs only the all-red clearance: 5% of the cycle, about 0.1 s. A straight avenue, a curving park path or the stretch before a turnaround gets no credit.
- **What counts:** only the signalized crosswalks the route walks (OSM `crossing=traffic_signals`). Crossings on road centerlines have no crosswalk way and are missed (009).

**4. Wiring to `RunConstraints.lights`.**
- **Everywhere:** `routers_for(zones, lights)` and `context_for(lights, grid, use_prior)` are used by the CLI (`--lights waits|zigzags`), the eval harness and the review page (`render_review --lights`).
- **Request and results:** the parsed request shows the setting; the default is zig-zags.

**5. Also measured** (`api/route_context.roadway_share`): the share of a route whose nearest walkable way is a road centerline rather than a sidewalk, path or crosswalk. It's reported here, but not yet in the ranking; that's the roadway dimension, Phase 2 step 4.

## Result (measured, except wait, which is an estimate; the #1 route from each start, generated without the reviewer's runs, on untrimmed routes)

| start | mi | setting | signals/mi | wait (estimate) | roadway % | first candidate s (before → after) | #1 |
|---|---|---|---|---|---|---|---|
| kips-bay | 3 | waits | 2.6 → 2.9 | 2.4 min | 14 → 10 | 0.32 → 0.31 | waterfront loop (was the out-and-back) |
| kips-bay | 3 | zigzags | 2.6 | 1.4 min | 14 | 0.28 → 0.26 | waterfront out-and-back |
| kips-bay | 4 | waits | 2.5 → 2.2 | 2.4 min | 12 → 7 | 0.14 → 0.24 | waterfront out-and-back, both ways |
| kips-bay | 4 | zigzags | 2.5 | 1.9 min | 12 | 0.13 → 0.31 | waterfront out-and-back, both ways |
| kips-bay | 6 | waits | 3.4 → 3.0 | 4.9 min | 8 → 4 | 0.17 → 0.47 | waterfront out-and-back |
| kips-bay | 6 | zigzags | 3.4 | 4.3 min | 8 | 0.16 → 0.28 | waterfront out-and-back |
| flatiron | 3 | waits | 2.3 → 2.3 | 1.9 min | 1 → 1 | 0.16 → 0.20 | East River Esplanade out-and-back |
| flatiron | 3 | zigzags | 2.3 | 1.9 min | 1 | 0.11 → 0.14 | East River Esplanade out-and-back |
| flatiron | 4 | waits | 3.4 → 2.8 | 3.0 min | 12 → 5 | 0.15 → 0.18 | waterfront path out-and-back |
| flatiron | 4 | zigzags | 3.4 | 3.2 min | 12 | 0.25 → 0.20 | East River Esplanade out-and-back |
| flatiron | 6 | waits | 3.2 → 2.9 | 4.6 min | 4 → 3 | 0.22 → 0.36 | waterfront out-and-back |
| flatiron | 6 | zigzags | 3.2 | 4.6 min | 4 | 0.21 → 0.62 | waterfront out-and-back |

"Before" for the waits rows is this code before the change: the same ranking weights, no router penalty. Zig-zag rows have no router change, so their signals and roadway columns didn't change.

- **Does the penalty push routes into the roadway? No.** For runners who wait, the #1 route's roadway share went down at every start and distance (Kips Bay 4 mi 12% → 7%, Flatiron 4 mi 12% → 5%). That matches the router test.
- **Signals for runners who wait:** down at 4 of 6 rows, flat at 1. At Kips Bay 3 mi they went up, 2.6 → 2.9, because the ranking picked a different #1: a waterfront loop rather than the out-and-back. The penalty changes paths between waypoints, not which candidate wins.
- **Zig-zag credit:** largest where routes have staircase stretches (Kips Bay 3 mi: 1.4 min against 2.4 for the same kind of route when waiting). Nearly zero on routes that are mostly waterfront path or straight avenue (Flatiron 3 mi: 1.9 min either way).
- **Time to first candidate:** 0.14–0.62 s after, against 0.11–0.32 s before, still within the 1 s budget. The wait estimate adds work per candidate. Totals rose too (up to 23 s for Flatiron 6 mi when waiting, from 10 s). This needs work, and the UI brief's ~5 s full-pool budget isn't met.

## Why "I wait" picked a route with more signals at Kips Bay 3 mi
This is not the ranking trading signals for something else, and not a code bug. **It is a candidate the penalty changed.**

The zig-zag winner is a waterfront out-and-back (heading 159°): 4,921 m, 8 signalized crosswalks (2.6 per mile), 60% park or water. Routed with the penalty, the same job came out as a different path: 4,711 m, 3.1 per mile, 4.8 turns per mile against 3.3. The 2.6-per-mile route no longer existed in the waits candidate set. The waits ranking then picked the best of what it had: the waterfront loop.

| | zig-zag #1 (out-and-back) | waits #1 (loop) |
|---|---|---|
| distance | 4,921 m | 4,958 m |
| signalized crosswalks (per mile) | 8 (2.6) | 9 (2.9) |
| park or water | 60% | 60% |
| turns per mile | 3.3 | 3.9 |
| on runs of 500 m or more | 66% | 61% |
| expected wait for a runner who waits (estimate) | 2.2 min | 2.4 min |

For a runner who waits, the zig-zag winner is slightly better: one signal fewer and about 0.2 min less estimated wait.

**Why the penalty can add a signal.** GraphHopper custom models can only multiply an edge's cost, and an edge's cost grows with its length. So the penalty is per meter of signalized crosswalk, not per crossing, and on some legs the router swaps one wide avenue crosswalk for two narrow street crosswalks. Across the 113 distinct anchored requests in the Kips Bay 3 mi waits run, the same waypoints routed with the penalty instead of without gave:
- fewer signalized crosswalks for 95, the same for 11, more for 7 (mostly +1 signal for about +51 m; one went from 25 to 45);
- 31% fewer in total (2,688 → 1,847) for 4% more distance.

GraphHopper's own `crossing` value agreed with our signal count on 275 of 300 sampled signalized crosswalks, so this isn't the router and the metric meaning different things.

**Remedy, not built:** for runners who wait, also generate the unpenalized candidates and let the ranking choose. The ranking already weighs signals twice as heavily for them. That would have kept the 2.6-per-mile route here, at the cost of roughly twice the candidates for that setting. A fixed per-crossing cost would need additive per-edge costs, which custom models don't offer; turn costs are additive but push routes into the roadway (009).

## Still open from the UI brief (`docs/ui/brief-v1.md`, "What the engine must provide")
- per-segment crowd estimate and surface;
- streaming over the network (server-sent events or WebSocket; today a callback);
- feedback endpoints;
- edit operations (dragging waypoints, drawing avoid areas);
- named climbs;
- the ~5 s full-pool budget.

## Limits
- **Signal timing is assumed,** not measured. DOT's signal timing data was not checked.
- **The zig-zag credit is a geometric test.** It doesn't know which crosswalks have signals on both streets, or whether the alternative block has its own signal.
- **The wait isn't in the ranking,** so it can't yet make a zig-zagger's route differ from a waiter's except through the router penalty and 010's weights.
- **One router test, and two starts in the table.**
