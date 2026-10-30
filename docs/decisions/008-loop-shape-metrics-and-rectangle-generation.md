# 008: Loop shape is scored (turns per mile first), and loops are generated as grid-aligned rectangles

**Status:** accepted and implemented (metrics: `api/shape.py`; generator: `api/generate.py`; grid: `api/grid.py`, `api/streets.py`)

## Context
Reviewing the Phase 1 output showed `round_trip` loops that zigzag, run out and back through one corridor, or retrace themselves. Measured on the 4 mi request from 11 Madison Ave:

| | seed 4 (the zigzag) | seed 0 (the lollipop) |
|---|---|---|
| turns per mile | 13.5 | 3.6 |
| average width | 174 m | 256 m |
| compactness | 0.21 | 0.33 |
| retraced share | 0% | 27% |

Over 40 seeds: median compactness 0.15, median 5.5 turns per mile, 2 of 40 within ±5% of 4 mi. `round_trip` picks random waypoints, and the shortest path between diagonal waypoints on a street grid is a staircase; nothing in it knows what shape a run should have.

## Decision

**1. Shape metrics are scored fields reported for every loop** (`api/shape.py`). Deterministic code only; Claude may describe them, never compute them.
- `turns_per_mile`: a turn is a direction change of at least 45° after simplifying the line to an 8 m tolerance (ignores bends in curved paths, keeps street-grid corners). On a closed loop the corner at the start/finish counts, so the number doesn't depend on where the loop starts.
- `longest_straight_m` and `pct_in_long_runs` (share of the route on straight runs of 500 m or more).
- `retraced_pct`: share of the route within 15 m of a part of the route more than 150 m away along it.
- `mean_width_m` (2 × area ÷ perimeter) and `compactness` (4π × area ÷ perimeter², 1 for a circle, about 0.79 for a square), for closed loops. These catch thin "ribbon" loops that retrace nothing.

**2. Candidates are generated as grid-aligned rectangles**, not only `round_trip`:
1. Estimate the local street-grid angle from OSM bearings within about 1 km of the start (Manhattan is about 29° off north; do not hard-code it).
2. Build rectangles at several aspect ratios, orientations and start positions, and route them through their four corners with GraphHopper.
3. Rescale the sides by requested/actual distance and re-route, up to 3 times.
4. Reject candidates with ferries, heavy retracing, or a distance miss beyond tolerance (corners that snap to a shoreline collapse the loop; one prototype went 4.0 to 1.4 mi). Rank the rest on the shape score; park, waterfront and amenity scores come after.
5. Where the grid is weak, fall back to `round_trip` seeds with the same filtering.
6. If nothing is within ±5%, return the nearest candidate and say how far off it is.

**3. Corridor anchoring (avenues, East River path) is a second increment**, measured against plain rectangles. OSM has the named greenways (East River Greenway 2.7 km, East River Esplanade 3.5 km, Hudson River Greenway 8.7 km, Hudson River Park Esplanade 6.6 km), but a naive East River-anchored prototype was worse than a plain rectangle: 5.5 to 8 turns per mile and only 14 to 29% of the route actually on the path, because the greenway has gaps and awkward entry points. It needs extracted corridors in PostGIS and chosen entry and exit points, not corner-snapping. Straightness belongs to the whole route, so it is not pushed into the GraphHopper custom model, which can only boost path types as a weak extra.

## Evidence for the rectangle approach
12 rectangle candidates (3 aspects × 4 orientations, one rescale pass), 4 mi request, one Manhattan start:

| | rectangles | `round_trip`, 40 seeds |
|---|---|---|
| within ±5% of 4 mi | 9 of 12 | 2 of 40 |
| median compactness | 0.58 | 0.15 |
| median width | 590 m | 128 m |
| turns per mile, best / median | 2.0 / 3.1 | 3.2 / 5.5 |
| longest straight run | 1.3 to 2.2 km | |

## Limits of this evidence
One start point in Manhattan. The 90° grid does not apply in much of Brooklyn, Queens or the Bronx. The two failed rectangles (1.7 and 1.4 mi) pointed into the East River.

## Supersedes
Refines the retry-loop idea in decision 007: the rescale step is the same, applied to rectangle corners instead of `round_trip.distance`.

## Result of building it (2026-10-30)
Measured on 13 real starts across all five boroughs at 3, 6 and 10 miles (39 cases), using the live GraphHopper graph and the street network loaded into PostGIS (`osm_ways`, 414k ways):

- **All 39 produced a loop within ±5% of the request**, each in 0.2 to 1.2 seconds. Rectangles won 35; round trips won 4.
- Strong-grid Manhattan starts scored 82 to 90 of 100 (2.0 to 3.9 turns per mile, compactness 0.50 to 0.70). 11 Madison Ave at 4 mi: 4.10 mi, 2.0 turns per mile, compactness 0.71, no retracing.
- The grid estimator recovers Manhattan's 29° (28.7° and strength 0.97 at 11 Madison Ave) and flags grid-less areas (Forest Hills 0.28, St. George 0.42).
- Weakest results: Staten Island, where streets wind. 1 Bay St at 3 mi scored 48 (8.4 turns per mile); 2800 Victory Blvd at 3 mi scored 23 (10.0 turns per mile). These are the best the generator found, not a failure to reach the distance. Better shapes there need corridor anchoring or more candidate variety.

## Changes made while building, from the measurements
- **Weak grids run both methods and let the shape score choose.** The first design used round trips only where the grid strength was below 0.45. Measured side by side, neither method wins everywhere (for example 1 Main St, Brooklyn at 3 mi: rectangle 67 against round trip 44; 41 Seaver Way, Queens at 3 mi: round trip 66 against rectangle 51), so rectangles are always generated and round trips are added when the grid is weak or no rectangle reaches the target. Strong-grid starts stay rectangle-only, which is what keeps them fast.
- **Ribbons are rejected** (`MIN_COMPACTNESS = 0.15`). Round trips were winning with compactness of 0.04 to 0.08 at 10 mi: nothing retraced within 15 m, but out along one street and back along the next, which is the shape the review flagged.
- The shape score's weights (turns 40, straight runs 25, compactness 25, retracing 10) are a first judgment, to be tuned with "I ran it" ratings.

## Not done yet
Corridor anchoring (avenues, East River path), crossings and signals as a score input, park and waterfront share, and amenities near mile X. The OSM export also holds the traffic signal and crossing nodes needed for crossing counts; they are not loaded yet.
