# 010: One combined ranking with labeled dimensions, no-go zones as a hard rule, and out-and-back as a first-class route type

**Status:** accepted and implemented (Phase 2 step 1, 2026-10-30). Changes 008 (shape is no longer the whole score; out-and-backs are no longer rejected as retraced) and implements 009 items 2, 4 and 5.

## Context
Under 008, a loop's shape score was the whole ranking. From the Kips Bay review start, two of the top loops went through Times Square, one ranked 2 with a score of 95. The reviewer's own runs then showed that out-and-backs are normal for them (58% of the last 12 months on their first-pass numbers), while 008 rejected anything more than 15% retraced.

## Decision
**1. Combined ranking** (`api/ranking.py`). Each candidate gets a list of dimensions. Each one is `measured`, `estimate` or `not_scored` and carries a display value, a fit from 0 to 1 and a weight. The score is the weighted mean of the scored fits. A dimension without data is listed as `not_scored` with weight 0. It is never counted as zero. The weights come from the resolved preferences (`api/constraints.py`):
- turns weigh more for "fewer turns";
- straight runs and signals weigh more for a runner who waits at lights;
- park and water weigh more for "park or water";
- "matches routes you run" weighs more for "favor", and its fit is reversed for "new" (decision 011).

**The weights are provisional and deliberately untuned**, retracing and turns in particular. They are 008's numbers plus starting values for the context dimensions, and they are to be calibrated against real runs and ratings (decision 011) before anyone tunes them.

**2. No-go zones** (`routing/no_go_zones.geojson`, `api/nogo.py`).
- Each zone has an id, a name, aliases, a reason and a source. Default zones apply to every request, and the rest apply when the runner names them (`RunConstraints.avoid_places`).
- GraphHopper gets each zone as an area with priority 0 in the per-request custom model. Decision 009's router test showed it routes around them.
- Every candidate is also checked with a pure geometry test (`api/geometry.py`). One that still touches a zone is rejected as `no_go_zone`.
- A name that matches no zone is reported back ("isn't in the no-go list, so it was NOT applied"), never dropped silently (product rule 3).
- The first zone is Times Square (Broadway and 7th Ave, W 42nd–47th St, plus 40 m), from the reviewer's rejection.

**3. Out-and-back is a route type**, not a penalized loop (`api/generate.py`):
- **How it's generated:** out along 8 headings (4 along the grid, 4 diagonal) to a turnaround at half the distance, then back, rescaled like rectangles.
- **Acceptance:** at least 70% of the route is retraced. Less than that and the way back isn't the way out (`not_out_and_back`).
- **Ranking:** out-and-backs are not scored on retracing or loop shape.
- **Shape requests:** `RunConstraints.shape` now defaults to `any` when the runner says nothing. A request for `any` keeps the best of each type in the top 3. A request for `loop` never gets an out-and-back.

## Result (2026-10-30)
- `pytest evals/`: the Times Square case passes at 4 and 6 mi, where both failed before this step.
- From the Kips Bay review start at 4 mi the top 3 are two rectangles and one out-and-back. The out-and-back runs straight up an avenue sidewalk. At this step nothing scored signals or park share, so nothing could tell that route apart from a good one. Decision 011 adds those dimensions.
- 196 unit tests passed at the end of this step.

## Not done here
Crowds beyond named zones, closures, roadway share and the bike-lane rule are still `not_scored`. Times Square is avoided because a reviewer named it, not because Loop knows it is crowded.
