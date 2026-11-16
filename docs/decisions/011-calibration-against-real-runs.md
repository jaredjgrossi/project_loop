# 011: Calibrate against real runs. Map-match them, measure both sides with one set of definitions, and use the runner's own corridors as a prior

**Status:** accepted and implemented (Phase 2, 2026-10-30). Changes 008's turn definition, adds metrics, and adds three ranking dimensions to 010.

## Context
The reviewer exported 1,640 Apple Health workout routes from 2020 to now. Their first-pass scripts (`evals/health_routes/analyze_routes.py`, `summarize.py`) ran on raw, unmatched GPS. Over the last 12 months (205 runs): median 3.07 mi, 58% out-and-back, 47% retracing heavily, and most runs from a few places. The generator penalized retracing and had never been compared with a real run.

## Privacy rules (from the reviewer)
- Raw tracks never leave `apple_health_export/`, which is git-ignored, and are never written anywhere else.
- Every track is trimmed by 200 m at both ends **before** map matching, so nothing stored or rendered starts or ends at a door. The only number taken from the untrimmed track is the start-to-finish gap, kept as a distance.
- Outputs go to `data/health/` (git-ignored) and to the local PostGIS table `runner_prior`, which is marked personal. Nothing personal is committed. This note gives only aggregates.
- Generated routes are trimmed the same way whenever they are compared with real runs.

## Decision
**1. Map matching uses GraphHopper's own `/match`** (`evals/health_routes/match_runs.py`).
- **Why this one:** it is a hidden Markov model matcher already in the 11.1 jar, and it matches onto the same foot graph the generator routes on. A real run and a generated route therefore become the same kind of geometry. Writing our own HMM, or snapping to PostGIS ways, would add code and a second graph.
- **`gps_accuracy=40`, GraphHopper's default,** was chosen by looking at matched runs drawn over their trimmed GPS:
  - at 15 m, matching hugged GPS noise and hopped between parallel paths through short connectors (matched length 1.05–1.14× the GPS length);
  - at 60 m, it cut corners into staircases;
  - at 40 m it gave 1.04–1.07× with the closest fit.
- **Run set:** last 12 months, using `summarize.py`'s run rule. 210 files gave 197 matched, 8 outside NYC (no graph there; all 8 failed at their first point and were confirmed out of town), 4 not runs and 1 with too few points.

**2. One set of metric definitions for both sides** (`api/shape.py`, `api/route_context.py`). They were fixed before any comparison.
- **Turns change.** 008 (simplify at 8 m, at least 45°) failed on shapes with known answers: two 10–20 m spurs counted as 8 turns, and an L-shape with 3 m GPS jitter counted as 55. On matched runs it gave 5.8 turns per mile, against 3.2 for the same runs as raw GPS. The new definition first removes spurs (out-and-back excursions of up to 50 m), then simplifies at 20 m and counts changes of at least 45°. It gets every synthetic case right (rectangle, an 80 m-block staircase with every corner, spurs, jitter, a sidewalk jog, a smooth arc). It also agrees best between the raw and matched versions of the same run: median difference 0.54 turns per mile, against 0.80 for the first-pass script's definition (at least 60° over about 75 m on a 25 m resample) and 2.71 for 008's.
- **Retracing is unchanged** (within 15 m of a part of the route more than 150 m away). It counts both passes, so a pure out-and-back is about 100%. The first-pass script counts only the second pass, so its numbers are about half and its "> 30%" threshold doesn't carry over. A 35 m radius, to treat opposite sidewalks as one corridor, changed the share of runs over 30% from 90% to 93%, so 15 m stays.
- **New:**
  - out-and-back share: the share of the second half within 15 m of the first half;
  - closure: the start-to-finish gap;
  - park share: inside a Parks Properties polygon of a runnable type, which leaves out plazas, gardens, malls and playgrounds;
  - waterfront share: within 60 m of the OSM coastline, newly loaded into `osm_coastline`, which covers Hudson River Park where Parks Properties misses it;
  - crosswalks and signalized crosswalks per mile: OSM crosswalk ways the route covers at least 60% of. The `crossing` tags are now kept by `etl/osm_parser.py`, and 47,518 crosswalk ways are signalized.
  - All of these are `measured`.

**3. Runner prior** (`evals/health_routes/build_prior.py`). A matched run uses an OSM way when it covers at least min(25 m, half the way) within 10 ft. Motorways and trunk roads are excluded: in 2D the FDR overlaps the esplanade stacked above or below it. Result: 1,424 ways used at least once, 798 on 2 or more runs, and 13 corridors of 300 m or more used by at least 10% of runs. These are written to `runner_prior`, `data/health/way_prior.csv` and `data/health/corridors.geojson`.

**4. The prior is a soft bonus, in scoring and in placement.**
- **Scoring:** a new dimension, "Matches routes you run" (`familiar`), is the share of the route on ways run 2 or more times. It is `measured`. The `RunConstraints.familiar` preference sets it to favor (double weight), some, or new (fit reversed). Training presets to favor; Exploring and the default are some. With no prior loaded it is `not_scored`.
- **Placement:** the generator adds out-and-backs that go out and back through the nearest corridor point (the entry) and turn around at a corridor point picked to fit the distance, never moved off the corridor. Two tiers are tried and the ranking picks: ways used on at least 10% of runs, and ways used on at least 2.5%. With only the 10% tier, the corridor near the Kips Bay review start stopped 1.5 km out, too short for a 3 mi out-and-back. With only the 2.5% tier, the entry point near the Upper East Side moved to a lesser way and the best familiar candidate fell from 88 to 60.
- **Also added in this step:** park/water and signals as ranking dimensions (`measured`), from the same context code.
- **Weights:** all provisional (decision 010).

**5. Positive eval** (`evals/routes/test_real_runs.py`). For each review start with at least 20 real runs starting within 1.5 km, the best generated 3 mi route must score at least the median real run there. Both sides are trimmed and scored by the same ranking and context with neutral preferences. It skips on machines without the personal data.

## Gaps as measured (all values measured; medians, both sides trimmed)
| | Real runs (n=197) | Generated before step 3 (n=42) | Generated after step 3 (n=42) |
|---|---|---|---|
| Turns per mile | 3.4 | 1.6 | 2.1 |
| Retraced % | 76 | 92 (loops 0, out-and-backs 95) | 3 (loops 1, out-and-backs 94) |
| Out-and-back (> 50% of second half revisits first) | 66% of runs | 52% | 40% |
| In a park % | 48 | 0 | 5 |
| Waterfront % | 62 | 0 | 0 |
| Signalized crosswalks per mile | 2.2 | 6.3 | 5.5 |
| Ends within 400 m of start | 82% | 100% | 100% |

"Before step 3" is the step 1 generator (ranking and no-go zones only), measured with the fixed definitions. "After step 3" adds park/water, signals and the runner prior to the ranking, and familiar placement. The kips-bay review start is a public stand-in (Kips Bay Library) near the reviewer's address. "Before" was measured from the reviewer's address, "after" from the stand-in.

Positive eval at 3 mi:

| Start | Best generated | Typical real run | Result |
|---|---|---|---|
| upper-east-side (107 runs) | 92 | 89 | passes |
| kips-bay (89 runs) | 50 | 82 | fails |
| flatiron (the same 89 runs) | 64 | 82 | fails |

With "matches routes you run" switched off, the Kips Bay gap is 61 against 77, so the gap is park, water and signals, not familiarity.

## What this says (one runner; hypotheses)
- Real runs turn more than generated ones (3.4 against 2.1 turns per mile) and accept that to reach parks and water. A fewer-turns default works against what this runner does, so the turn weight must not be locked in.
- Retracing is normal: a median of 76% on real runs. The 15% cap stays only as a test for "is this a loop", and out-and-backs are ranked separately.
- The biggest gap is placement. Generic generators don't reach the water or the parks, and the runner's own corridors fix that only where they reach far enough (Upper East Side, not Kips Bay). Corridor and park/water generators (Phase 2 step 7) are the next lever.

## Limits
- One runner, and their numbers come from their own two home areas.
- Matching artifacts (short spurs) remain in the stored geometry; the turn definition removes them before counting.
- Crosswalks are missed wherever a route runs on a road centerline (decision 009).
- Park share misses parks outside Parks Properties.
- No ratings yet. The calibration says where the generator differs from this runner, not whether either one is good.
