# 012: Park, waterfront and corridor generators from OSM, a verified corridor catalog, and round trips everywhere

**Status:** accepted and implemented (Phase 2 step 2, 2026-10-30). Extends 008, 010 and 011. Changes 008 (round trips are no longer weak-grid only), 010 (adds the lollipop route type) and the duplicate test from 008.

## Context
Calibration (011) found that the biggest gap between the reviewer's runs and generated routes was where they go. Real runs were a median 48% in parks and 62% by the water; generated routes were 5% and 0%. The geometric generators (rectangles, headings, round trips) don't know where parks or the water are. The runner-prior placement from 011 only helps a runner whose own runs reach far enough, and it can't help anyone else.

## Decision
**1. Anchored candidates, built from OSM for every runner** (`api/anchors.py`). An anchor set is a feature's points. The set's entry is its nearest point to the start, and the other points are grouped into 45° directions as candidate turnarounds. There are three sources:
- **Parks:** OSM `leisure=park` and `nature_reserve` areas (new table `osm_parks`, 2,018 rows, loaded by `etl/load_osm.py`). Unlike Parks Properties these include Hudson River Park, Brooklyn Bridge Park and Governors Island. The nearest 3 parks of at least 2 ha within reach are used, with points on the paths inside each one.
- **Waterfront:** path-like ways (no sidewalks or crosswalks) within 60 m of the OSM coastline, the same 60 m as the waterfront share.
- **Corridors:** the nearest 3 catalog corridors within reach (point 2).

"Within reach" means the nearest point is within 80% of the turnaround radius (half the distance ÷ 1.25).

**2. Corridor catalog** (`etl/build_corridors.py`, tables `corridors` and `corridor_gaps`, run by `make setup` and `make corridors`).
- **What goes in:** path-like ways that are waterfront (within 60 m of the coastline), named greenways, esplanades, promenades and boardwalks, or car-free park drives (named "… Drive" inside an OSM park, tagged pedestrian or footway, not a road).
- **Grouping:** ways are grouped per kind with DBSCAN (ways within 20 m of each other belong together) and kept at 800 m or more. A first version grouped all kinds together and chained bridge promenades into 25 km networks.
- **Verification with GraphHopper:** route between each corridor's two farthest points, with a per-request custom model that makes leaving the corridor 20 times as costly. A first version used plain shortest paths, which cut across streets even where a corridor was continuous: Hudson River Park scored 15% on-corridor. If less than 80% of the route stays on the corridor, the corridor is marked not continuous, and the stretches where the route leaves it are stored as internal gaps.
- **Gaps between corridors:** two corridors 50 m to 1 km apart that don't connect are stored as a gap.
- **Result:** 160 corridors (88 of 102 waterfront, 51 of 53 greenway and all 5 park drives verified continuous), 21 internal gaps and 86 between-corridor gaps. The East River gap shows up as expected: East Midtown Greenway has a 709 m internal gap.
- **Names are approximate.** A cluster takes the name of its longest named way, so "Manhattan Bridge Pedestrian Path" labels a 10.8 km waterfront cluster.

**3. How anchored routes are built** (`api/generate.py`):
- **Two variants per direction:**
  - out-and-back: start → entry → turnaround → entry → start;
  - free return: start → entry → turnaround → start, classified by its geometry as a loop, a lollipop or an out-and-back.
- **Turnaround:** picked to fit the distance among the feature's own points, never moved off the feature. When the feature is too small for the distance, the route runs through it to its far end and continues the same way ("and beyond"). If that point is off the map (in the river), the route turns at the far end and its miss is reported.
- **Routing:** anchored routes go to GraphHopper with a custom model in which edges outside the feature cost twice as much (`OFF_FEATURE_PRIORITY = 0.5`, provisional). Without it, the shortest way to a far turnaround ran inland, and a 6 mi waterfront route touched the water only at its tip (12% park or water). This is the path preference in the custom model that decision 009 planned. It changes where routes go, not how they're scored.
- **Directions tried:** all directions for the waterfront set, two per park or corridor.

**4. Lollipop is a route type** (out, around and back). A route with 15–70% retraced used to be rejected: too retraced for a loop, not enough for an out-and-back. Most of the reviewer's real runs look like this (011: median 76% retraced). Lollipops are ranked like out-and-backs, without the retracing and loop-shape dimensions. A `loop` request accepts them, since they start and end as a loop does. Only anchored free-return routes are classified this way; rectangles and round trips keep 008's rules.

**5. Round trips everywhere.** They no longer run only where the grid is weak. They are the one generator not tied to the grid, and the ranking decides.

**6. Duplicates.** Two routes are duplicates when each mostly runs on the other: the smaller of the two overlap shares is at least 0.8. 008 used the larger share, which counted a loop as a copy of the out-and-back it shares its way out with.

**7. Your-runs placement is unchanged and stays optional.** It is never an input to these generators. The real-run eval now runs with "matches routes you run" off on both sides and without that placement (`top_loops(..., use_prior=False)`), so the reviewer's runs are only the answer key.

**No ranking weights changed in this step.** The only change to `api/ranking.py` adds the lollipop type.

## Result (all values measured; generated without the reviewer's runs; shares on routes trimmed 200 m at both ends)
Real-run eval at 3 mi, "matches routes you run" off:

| Start | Before | After |
|---|---|---|
| kips-bay (89 runs) | 61 vs 77, fails | 87 vs 77, passes |
| flatiron (same runs) | 68 vs 77, fails | 85 vs 77, passes |
| upper-east-side (107 runs) | 92 vs 87, passes | 95 vs 87, passes |

The kips-bay start is a public stand-in 192 m from the reviewer's address. The 63 vs 77 gap quoted in the brief was measured from the address itself before the switch. From the stand-in, the before is 61.

The full before and after table for all 10 starts is in `HANDOFF.md`. The #1 route reaches a park or the water at most starts and distances. It does not at Kips Bay 4 mi or Flatiron 4 mi, where every waterfront and corridor candidate missed the ±5% distance limit.

The step 1 route generated in about 1 s per start; with the new candidates it takes 5–15 s.

## Limits and next levers
- **Turnarounds are chosen by straight-line distance.** Where the shore bends, crosses a bridge or has a gap (the UN stretch), the routed distance jumps and some distances can't be met. That's why the 4 mi starts above fail. More rescale attempts didn't help (tried: 6 instead of 3). The fix is to pick turnarounds by walking distance along the feature.
- **Park share still uses Parks Properties,** kept fixed so before and after compare. Routes in parks that are only in OSM get water credit but no park credit.
- **Closures and bike lanes are still not enforced.** No closure data is loaded, and the bike-lane rule still needs NYC DOT data. The corridor gaps are structural (no path), not temporary closures.
- **No unit tests for the corridor catalog.** It is SQL plus live GraphHopper. It was checked by running it and by its known East River gap. The anchor grouping, route building, classification and fallbacks have unit tests.
- **One runner's eval.** The routes still need review on the page, and passing the eval is not proof that the routes are good.
