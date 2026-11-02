# 016: Crowds. A level on sidewalk stretches from subway volume, with time from DOT's count windows

**Status:** proposed (Phase 2 step 5, 2026-11-02). Final crowds rule: only known-busy distance costs a route; no-data distance is neutral (reviewer's choice, 2026-11-02). Implements decision 013's recommendation. Adds one ranking weight (crowds); no other weight changed.

## Context
`RunConstraints.crowds` (avoid / some / don't mind) existed since decision 009 but was not scored. Decision 013 compared the crowd sources we can get for free and recommended a level per sidewalk from subway volume, timed by DOT's count windows, with `not_scored` wherever the data can't speak. It also asked us to check DOT's automated pedestrian counters for paths.

## Decision
**1. Inputs** (`etl/load_crowds.py`, `make crowds`; public downloads in `data/crowds/raw/`, git-ignored):
- **Subway volume:** MTA hourly ridership entries (`5wq4-mkjj`) plus origin-destination exits (`y2qv-fytt`, `28vm-gjqr`), averaged per station complex, day type and hour, for Sept–Oct 2025 and May 2026 (DOT's count rounds) → `station_flow`.
- **Sidewalk width:** a transect across each OSM sidewalk way into the NYC planimetric sidewalk polygons (`52n9-sdep`, 2022 imagery). Stubs under 30 ft inherit a neighbor's width, and widths are clamped to 5–40 ft → `sidewalk_width`. 135,282 of 137,380 sidewalk ways (98.5%) have a width; the median is 10.5 ft.
- **DOT bi-annual pedestrian counts** (`cqsj-cfgu`) → `dot_ped_counts`, for the eval and the counter thresholds only.
- **DOT automated counters** (`ct66-47at`, locations `6up2-gnw8`, Aug–Oct 2026) → `ped_counters`, `counter_crowd`, `counter_ways`.

**2. Level per sidewalk way and band** (`sidewalk_crowd`, `api/crowds.py`):
- **Volume:** station flow summed with a Gaussian kernel (σ 300 m, cut at 800 m) around each way, divided by its width.
- **Levels:** high at or above the 85th percentile of volume per foot within the band, medium at or above the 50th, otherwise low.
- **Far from the subway:** a way more than 800 m from any station is low, basis "far from the subway (assumption)".
- **Bands, from DOT's windows:**
  - weekday 7–9am;
  - weekday 9am–4pm, labeled "between DOT count windows";
  - weekday 4–7pm, with 7–8pm assumed like it;
  - Saturday 12–2pm.
- **Not scored, never assumed quiet:** Sundays, before 7am, after 8pm, and Saturday outside 12–2pm ("no count data at this hour").
- **Off mapped sidewalks:** paths, greenways, bridges and road centerlines are not scored ("no crowd data off mapped sidewalks"). The one exception is the counter paths (point 3).
- **Hour at each point:** the start time plus the distance so far at an assumed 10 min per mile.

**3. DOT automated counters, where they're current.**
- **Counters checked:** 4 pedestrian counter sites (10 sensor entries).
- **Current** (last data within 30 days of the 2026-11-01 download): 2.
  - **Concrete Plant Park** (Bronx River Greenway): 16 path ways.
  - **Emmons Ave** (Sheepshead Bay): 5 path ways.
- **Stale:** High Bridge (last data 2026-06-07) and Willis Ave Bridge (2025-12-31).
- **How paths use them:** a path way within 400 m of a current counter, on the same catalog corridor, takes that counter's mean hourly count for the day type and hour, at any hour. Levels use DOT street sites' per-hour counts from the last two rounds: high at or above 2,513 people/hour (85th percentile), medium at or above 1,111 (median).
- **Coverage: 21 path ways in the whole city.** None of them is near a review start. Paths stay `not_scored` almost everywhere.

**4. Wiring.**
- **Request:**
  - `RunConstraints.start_date` is new;
  - `start_moment()` combines it with `start_time`;
  - `describe()` shows the weekday;
  - CLI: `--start-date YYYY-MM-DD` with `--start-time HH:MM`;
  - eval harness: `top_loops(..., when=)`;
  - review page: `render_review --start 2026-11-03T18:00 --crowds avoid`.
- **Route context** (`ContextScores`): `crowd_high_pct`, `crowd_medium_pct`, `crowd_low_pct` and `crowd_not_scored_pct`, all shares of the route's distance, plus `crowd_band` and `crowd_reason`.
- **Ranking** (`api/ranking.py`): `crowds` is a context dimension with status `estimate`.
  - **Weight:** 25, provisional; × 2 for avoid, × 1 for some, × 0.25 for don't mind.
  - **Fit:** 1 − high share. Only known-busy distance costs a route. Distance with no crowd data is neutral, neither quiet nor busy: it costs nothing, and it isn't credited as quiet either, since a low level costs nothing too. The dimension's text says so ("N% has no crowd data, counted as neither quiet nor busy"). The first version counted no-data distance as a typical sidewalk. Result says why that was replaced.
  - **Scored for every candidate in a request, or for none.** It's decided by the start moment: crowds are not scored, for any route, when there's no start time or the start is outside the count windows (the reason is shown).
  - **Without a start time,** every ranking is the same as before this decision.

  **Why not drop the dimension for mostly-path routes.** The first version followed 013's rule: no crowds score for a route with more than half its distance unscored. The comparison below showed what that does. The rule removed the crowds weight from mostly-path routes only, so a street route won just by being scorable. With avoid at 8am and 6pm:
  - **Victory Blvd 3 mi:** the Willowbrook Park out-and-back (62% park or water, 0% high) lost to a street out-and-back (0% park or water, 0% high).
  - **Kips Bay 6 mi:** the waterfront out-and-back (51% park or water, 3.4 signals/mi) lost to one with 30% and 4.9, at the same 0.8% high.

  Neither replacement was less crowded. Scoring every candidate or none fixes this.
- **Stretches** (`api/segments.py`): each stretch has `crowd: {value, status, basis, band, high_pct}`.
  - The value is the stretch's most common scored level (ties go to the busier level). A stretch with no data on half or more of its length is not scored, with the most common reason.
  - A stretch mostly on measured sidewalks gets the fact "Sidewalk about N ft wide" (source 52n9-sdep, trust `listed`).
- **Feedback** (`api/feedback.py`, table `crowd_reports`): every "crowded" report, for the whole route or a stretch, is stored with:
  - the stretch's index and name;
  - the level the route showed there and its band;
  - the hour and weekday run (`ran_at`, else the requested start).

  Nothing reads the reports yet. They are the calibration set for paths and hours once there are enough.

**5. Dependencies:** numpy, pandas, shapely, pyproj and scipy, for the ETL and the eval. The API's request path needs none of them.

## Eval (`evals/crowds/`, held-out DOT round May 2026, street sites)
| period | Spearman | sites |
|---|---|---|
| weekday 7–9am | 0.81 | 98 |
| weekday 4–7pm | 0.82 | 98 |
| Saturday 12–2pm | 0.73 | 98 |

All three are at or above the 0.70 bar. Nothing in the model was fitted to DOT counts: 013 fixed the kernel before comparing.
- **Times Square, weekday 6pm:** most of its sidewalk ways are high.
- **Quiet block** (near the Victory Blvd review start, more than 800 m from the subway): low, basis "far from the subway".

## Result at the review starts (Tuesday 2026-11-03, #1 route, without the reviewer's runs; crowds "some" vs "avoid")
Four runs per row: Tuesday 8am and 6pm, each with crowds "some" (the default) and "avoid". The baseline is the same request with no start time, which is unchanged from before this decision. Shares are of the #1 route's distance at 6pm with avoid: busy = high level, no data = not scored. "same" means the same route as the baseline.

| row | #1 without a start time | 8am some | 8am avoid | 6pm some | 6pm avoid | busy | no data | park or water | signals/mi |
|---|---|---|---|---|---|---|---|---|---|
| Kips Bay 3 mi | waterfront out-and-back | same | same | same | same | 1.5% | 74% | 60% | 2.6 |
| Kips Bay 4 mi | waterfront out-and-back, both ways | same | same | same | same | 1.1% | 78% | 70% | 2.5 |
| Kips Bay 6 mi | waterfront out-and-back | same | same | same | same | 0.8% | 64% | 51% | 3.4 |
| Flatiron 3 mi | East River Esplanade out-and-back | same | same | same | same | 16.5% | 62% | 48% | 2.3 |
| Flatiron 4 mi | East River Esplanade and beyond | same | same | same | same | 12.2% | 52% | 35% | 3.4 |
| Astor Place 6 mi | Hudson River Park Esplanade, both ways | same | same | same | same | 19.3% | 78% | 69% | 1.3 |
| Upper East Side 3 mi | loop on Bobby Wagner Walk | same | same | same | same | 0% | 89% | 86% | 0.7 |
| Upper East Side 4 mi | loop on Bobby Wagner Walk | same | same | same | same | 0% | 92% | 89% | 0.5 |
| Upper East Side 6 mi | Bobby Wagner Walk and beyond | same | same | same | same | 0% | 96% | 82% | 0.3 |
| Williamsburg 4 mi | North 5th Street Pier out-and-back | same | same | same | same | 0% | 43% | 42% | 2.3 |
| DUMBO 3 mi | waterfront out-and-back, both ways | same | same | same | same | 0% | 81% | 85% | 0 |
| Flushing Meadows 3 mi | out-and-back through the park | same | loop through the park | same | same | 0% | 87% | 83% | 0 |
| Grand Concourse 4 mi | Mosholu-Pelham Greenway out-and-back | same | same | same | same | 0% | 42% | 32% | 3.1 |
| St. George 3 mi | North Shore Esplanade out-and-back | same | same | same | same | 0% | 60% | 59% | 0.7 |
| Victory Blvd 3 mi | Willowbrook Park out-and-back | same | same | same | same | 0% | 83% | 62% | 0 |

- **14 of 15 rows are the same route in all four runs.** Flushing Meadows at 8am with avoid is a near-tie: the same distance (2.93 mi), crowd, park and signal numbers, classified as a loop instead of an out-and-back.
- **Crowd avoidance changes nothing at these starts.** The #1 routes have no more than 1.5% busy distance, except Flatiron (12–17%) and Astor Place (17–19%). For both of those, the busy distance is on the streets between the start and the esplanade, and every alternative uses those same streets. So this records that the dimension doesn't make things worse. It doesn't yet show that it helps; that needs a start with a busy #1 and a quiet alternative.
- **Morning against evening:** levels shift (Flushing Meadows' scored sidewalks are low at 8am, medium at 6pm), but the #1 doesn't.

**Tried first and replaced:** no-data distance counted as a typical sidewalk (fit 1 − (high + 0.15 × no data)). It is pessimistic next to the sidewalks these routes use, which are 0–2% busy, so a route with more known-quiet sidewalk won. At Upper East Side 3 mi (avoid) and Williamsburg 4 mi (every run with a start time), the park and water #1 lost to street routes that were no less crowded (0% busy before and after). That cost 34 and 27 points of park or water, and 1.8–3.0 more signals per mile. St. George, Victory Blvd and Flushing Meadows also flipped between near-identical routes. The reviewer chose the neutral rule on 2026-11-02.

## Limits
- **Levels are relative within a band,** not absolute. A high at 8am and a high at 6pm are each the busiest 15% of sidewalks for that window. Only 3.4% of sidewalk ways (4,704 of 137,380) change level between weekday morning and evening. Mostly the level says where, not when.
- **Subway volume stands in for pedestrians.** It misses tourists, shoppers who arrive on foot or by bus, and events. 013 section 6 lists where it fails, such as Fifth Ave retail and parks.
- **Paths, greenways and waterfront esplanades are not scored,** and most of the routes Loop prefers run on them. On a mostly-path route the crowds score only sees the streets (42–96% of the #1 routes above has no data), and a crowded esplanade counts as neutral. The counters cover 21 path ways citywide.
- **Pace is assumed** at 10 min per mile.
- **Snapshot data.** Sidewalk widths are from 2022 imagery, station flows from Sept–Oct 2025 and May 2026, counters from Aug–Oct 2026.
- **The downloads aren't scripted.** `etl/load_crowds.py` refuses to run without them, and the dataset IDs above are where they come from.
