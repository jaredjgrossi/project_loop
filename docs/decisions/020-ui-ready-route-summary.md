# 020: A route summary the main screen can show as-is: labeled values, stretches that add up, lights at every crossing

**Status:** accepted and implemented (Phase 2, 2026-11-03). Extends 014. No ranking weights or ranking inputs changed.

## Context
The reviewer picked main-screen direction D (`docs/ui/references-v1.md` was the study behind it). For the Kips Bay 3 mi #1 route, D shows:
- the distance, "Route 1 of 3 · out and back", and the request with *you said* / *preset* chips;
- the turnaround and mile markers on the map, and esplanade and street bands on the profile;
- "60% waterfront · measured", "2.9 lights a mile · measured" and "8.5 m climb · estimate".

Printing that route in the 014 format (Kips Bay Library stand-in, 3 mi, 7:00, Training) showed four problems:
- **The stretches didn't add up to the summary.** The stretch kinds came to 70% corridor and 30% street, while the summary said 60.4% park or water.
- **The lights didn't agree.** The stretches added up to 18 signals; the summary said 9.
- **Values were missing:** the turnaround distance, mile points in the GeoJSON, a trust label on summary values such as distance, a street share, and a "Best of N" count.
- **describe() labeled only the preferences,** not start, distance, shape, mode or start time.

## Why the numbers differed
**Waterfront.** The summary and the stretches use two different classifiers:
- **The summary (`shares`):** every 5 m, a sample is waterfront if it's within 60 m of the OSM coastline, and park if it's inside NYC Parks properties.
- **The stretches:** every 20 m, the first label that applies wins: catalog corridor (within 15 m), then OSM park, then coastline, then street. Changes shorter than 150 m are absorbed.

So "corridor" is a caption, not a share. On this route, 524 m of the esplanade stretch was more than 60 m from the coastline, which is why the two didn't match.

**Lights.** There were three counts:
- **The summary and the ranking (`crossing_counts`):** each signalized OSM crosswalk the route covers by 60% or more, once, however often it's crossed. That gives 9 (2.9 a mile).
- **The stretches:** the same test run on each stretch's 20 m resampled line. Street stretches exist once per direction, so their crosswalks counted twice. The esplanade is one stretch covering both directions, so its crosswalks counted once. Resampling also cut corners: the same street showed 5 going out and 0 coming back. The total of 18 matched the truth only by coincidence.
- **The truth:** each of the 9 crosswalks is crossed twice, which makes 18 (5.9 a mile).

## Decision
1. **Markers** (`api/markers.py`). Mile points and turnarounds are GeoJSON points with their distance along the route, `measured`, sourced from the route geometry. The GPX waypoints use the same code.
2. **One sampler for all shares** (`route_context.sample_classes`, `composition_by_range`).
   - Every 5 m sample gets exactly one class:
     - *waterfront:* the shares' own coastline test;
     - *park:* in a park and not by the water;
     - *path:* within 15 m of a catalog corridor and neither of those;
     - *street:* everything else.
   - Each stretch carries meters of each class. Every sample stands for an equal share of the route, so the stretches add up to the summary's waterfront and park-or-water shares exactly.
   - The stretch `kind` stays as the caption.
3. **Lights at every crossing** (`route_context.crossing_passes`).
   - A crosswalk crossed twice counts twice. Each pass must cover 60% of the crosswalk, the same test as before.
   - A crosswalk covered only by its passes together counts once, so the count is never below `crossing_counts`.
   - Stretches count the crossings inside them, and the summary's lights a mile is their sum. The expected wait (015, an estimate that isn't scored) uses every crossing too.
   - **The ranking keeps `crossing_counts`.** Its text now says "each counted once", and the summary carries it separately as `ranking_signals_per_mile`. Decision 021 covers what that costs.
4. **Summary with trust labels** (`api/summary.py`).
   - The route feature's `summary` holds:
     - distance;
     - the four shares;
     - signalized crossings and lights a mile;
     - the ranking's once-per-crosswalk figure;
     - climb, wait at lights and crowds;
     - turnarounds;
     - score, rank and Best of N.
   - Each has a unit, a status and a source. Statuses are `measured`, `estimate`, `not_scored` with a reason (never zero), or `provisional` for the score.
   - Distance is the geometry's length, the same one the markers and stretches use. GraphHopper's slightly different figure is kept as `router_meters`.
5. **"Best of N"** (`GenerationResult.best_of`). N counts the routes that passed every hard rule within the distance limit, with duplicates dropped by the same similarity rule as the top 3. Routes outside the limit and rejected routes don't count. N is `None` when nothing came within the limit; the miss is then reported as before (product rule 3).
6. **Origins for every request field** (`constraints.request_items`).
   - Each field is labeled "you said", "<Mode> preset" or "default". "You said" applies only to a field given with a value.
   - `describe()` prints these items, and the route GeoJSON carries them as `request`.
   - The CLI passes only the flags given, so an unset `--shape` reads "any (default)".
7. **A time without a day** (`constraints.with_default_date`). It means the next time that clock time comes round in New York, labeled "default", so crowds get a band instead of going unscored. The crowd band only distinguishes weekday, Saturday and Sunday (016), so any weekday gives the same result. Holidays aren't modeled; 2026-11-03, Election Day, counts as a normal Tuesday.

## Result (Kips Bay Library stand-in, 3 mi, Training, Tuesday 7:00; measured unless marked)
| Value | Before | Now |
|---|---|---|
| Waterfront, summary / sum of stretches | 60.4% / no stretch shares | 60.44% / 60.44% |
| Path, street | none | 5.5%, 34.1% |
| Signalized crossings, summary / sum of stretches | 9 / 18 (by coincidence) | 18 / 18 (5.9 a mile: 18 over the geometry's 3.07 mi, 4,938 m) |
| Ranking's signals input | 2.9 a mile | 2.9 a mile, unchanged |
| Wait at lights for a runner who waits (estimate) | 146 s | 292 s |
| Turnaround | not in the output | 1.54 mi (2,476 m) |
| Best of N | none | 30 distinct (43 routes within the limit) |

The extra duplicate pass for N takes about 0.4 s after the last job, so the first route isn't delayed. 436 unit tests pass.

## The real-run baseline, recounted (011, 012)
011 counted lights on the reviewer's runs the same way as the ranking, each crosswalk once, giving a median of 2.2 a mile. Recounted at every crossing, on the same trimmed, map-matched runs (n=197; aggregates only):

| | Each crosswalk once | Every crossing |
|---|---|---|
| Real runs, all | 2.2 a mile | 3.1 a mile |
| Real out-and-backs | 1.8 | 2.8 |
| Real loops | 3.1 | 3.6 |
| Generated #1 at 3 mi, Kips Bay and Flatiron (out-and-backs, trimmed) | 2.2 | 4.4 |

- **Why the real runs rise less:** on the way back, the reviewer often takes the other sidewalk, which is a different crosswalk. That's a ratio of 1.36 for real out-and-backs, against 2.0 for generated out-and-backs, which retrace exactly.
- **The 011 and 012 conclusions still stand.** Their pass and fail verdicts come from ranking scores, and the ranking input is unchanged on both sides. 011's main finding, that the gap is placement (parks and water), doesn't depend on how lights are counted.
- **One descriptive reading flips.** Counting each crosswalk once, the #1 routes matched the reviewer's runs on lights (2.2 against 2.2). Counting every crossing, they cross more lights a mile than the reviewer's typical run (4.4 against 3.1). The once-per-crosswalk count flatters exact-retrace out-and-backs: see 021.
- **012's 66% and 2.2 are trimmed figures.** Its tables measure routes trimmed 200 m at both ends, for comparison with real runs. The same zig-zag winner reads 60.0% and 2.6 a mile untrimmed. With Training ("I wait"), 015's router penalty picks a different winner: 60.4% and 2.9 untrimmed. The UI shows untrimmed values, the route as run. `061ad17` (decision 018, step 2) didn't move these numbers: runs before and after it are identical.

## Limits
- **"Street" is everything that isn't waterfront, park or a catalog path:** sidewalks, plazas and unnamed paths. The stretch that absorbed part of East 33rd Street shows 248 m of street inside the esplanade stretch.
- **Crossings still miss road centerlines** (009). The pass split assumes the route runs along the crosswalk way, as OSM maps it.
- **Decision 015's wait numbers counted each crosswalk once,** so its table understates waits on out-and-backs by up to half.
- **There's no API yet.** All of this is in the GeoJSON `make_loop` writes.
