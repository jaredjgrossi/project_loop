# 013: Crowd signal options. What we can measure by street and hour, and how good an estimate gets

**Status:** research spike, proposed (Phase 2 step 5, 2026-11-01). Nothing is built. Extends 009 (crowds is an `estimate` dimension) and 010 (crowds beyond named zones are `not_scored`).

**Numbering:** another session's uncommitted work (`api/constraints.py`, `api/segments.py`, `api/feedback.py`) cites "decision 013" for start time, stretches and feedback. One of the two notes needs to be renumbered before either is committed.

## Question
What can we measure about crowds by street and hour in NYC, and how good can an estimate get? Every number below comes from scripts in `data/crowds/scripts/`, which is git-ignored and not part of the build. Personal data is reported here only as aggregates.

## 1. Sources
| | DOT Bi-Annual Pedestrian Counts | MTA Subway Hourly Ridership | NYC Planimetric Sidewalk |
|---|---|---|---|
| Dataset | `cqsj-cfgu` (NYC Open Data) | `5wq4-mkjj` (2025 on), `wujg-7c2s` (2020–24); exits from Origin-Destination `y2qv-fytt` (2025), `28vm-gjqr` (2026) (data.ny.gov) | `52n9-sdep` (NYC Open Data) |
| What it is | Manual screenline counts, mid-block, both sidewalks summed | Entries by station complex, fare class and hour. The OD tables add estimated exits by destination, hour and day of week (monthly averages) | Sidewalk polygons, curb to property line: 50,865 polygons (right-of-way and interior) |
| Coverage | 114 sites: 99 on-street (mostly retail corridors), 14 bridges, 1 Hudson River Greenway. 112–113 sites have data in each recent round | 428 station complexes, subway only. No buses, PATH or LIRR | Citywide |
| Space | One point per site | One point per complex | Polygons accurate to about 1 ft (ASPRS Class 1, 0.5 ft imagery) |
| Time | Weekday 7–9am, weekday 4–7pm, Saturday 12–2pm. One weekday and one Saturday per round, in May and Sept/Oct (2007–2026) | Hourly. Rows were current to 2026-10-22 when pulled. OD covers average days per month | One snapshot. **2022 imagery (updated Nov 2022–Oct 2023), not 2014.** `status` is New 2,084 / Updated 12,003 / Unchanged 36,778. Unchanged means the older capture was checked against 2022 imagery |
| Updates | Every 6 months (last 2026-07-21) | Weekly to monthly | As needed (last 2024-04-24) |
| License | Public, free reuse under the NYC Open Data terms of use (no license field set) | Public, under the data.ny.gov terms of use (no license field set) | Same as DOT |
| Join to our graph | Snap the site point to OSM `footway=sidewalk` ways within 40 m. That found both sides at 102 of 113 sites. Bridges and the greenway have no sidewalk ways | Kernel or nearest station from each way's midpoint (EPSG:2263) | A transect per OSM sidewalk way (section 2) |

Also checked and not used:
- **DOT automated counters** (`ct66-47at`, 15-min, daily updates): only 3 pedestrian sensors are live (Concrete Plant Park, Emmons Ave, High Bridge), and none is on a commercial sidewalk.
- **OSM points of interest:** 64,653 shops, food, civic and tourism points from our own extract. They are better mapped in Manhattan than in the Bronx or Queens.

## 2. Sidewalk width per OSM sidewalk way
**Method:** at 25%, 50% and 75% along each of the 137,380 OSM `footway=sidewalk` ways (14,250 km), cast a ±80 ft perpendicular transect. Cut it with the polygons and merge pieces that touch. Keep the piece that holds the sample point or lies within 20 ft of it. The way's width is the median of the three samples.

| | Value |
|---|---|
| Ways with a width | 98.1% of ways, 99.3% of length |
| Ways ≥ 80 ft long (97,791) | median 10.3 ft, 10th–90th percentile 7.4–15.7 ft; 99.6% between 4 and 40 ft |
| Against OSM `width` tags | 158 sidewalk ways are tagged, 42 of them usable and ≥ 80 ft: Spearman 0.55, median ratio 0.88, median error 2.9 ft. The check set is tiny and mostly one mapper's work in one neighborhood |

**Obvious errors:**
- **Corner stubs:** 34,561 ways are under 30 ft long (curb-ramp and corner connectors). 61% of them read over 40 ft because the transect runs along the cross street's sidewalk. They are 0.7% of length. Fix: inherit the width of the longest neighboring way.
- **Plazas and open areas:** on 1.8% of ways the transect never leaves the polygon (160 ft or more).
- **Slivers:** 0.23% of long ways read under 4 ft. They don't matter for length, but they dominate any ratio that divides by width (section 3). Clamp the width to 5–40 ft before dividing.
- **Uneven readings:** on 2.5% of long ways the three samples differ by more than 10 ft (driveways, bulb-outs, a change of block).
- **Offset ways:** 14% of sidewalk length has an OSM way whose midpoint lies outside every polygon. Snapping within 20 ft handles most of these.
- **Not in the data:** scaffolding (the capture rules say sidewalks under scaffolding were not updated), sidewalk cafés, vendors, tree pits and other street furniture. The polygon width is curb to building line, not clear walking width, so the true clear width is narrower.
- **Paths:** paths, greenways and esplanades are not in this layer, so they have no width.

## 3. Crowd estimate, as briefed and with variants
Fixed before any comparison with counts:
- **Static pressure P:** the sum of POI weights × a Gaussian (σ 75 m, cut at 225 m), × 1.5 inside OSM retail or commercial land use. Weights: shops, food, banks, pharmacies, libraries and places of worship 1; theatres, cinemas, nightclubs, markets and schools 2; hospitals 3; attractions, museums, galleries and viewpoints 3; hotels 2; offices 0.5; artwork 0.2.
- **Station flow F:** mean entries per day plus mean OD exits per day, by complex, day type and hour, for Sept–Oct 2025 and May 2026 (matching the count rounds).
- **Models:**
  - **M0 = P** (static only).
  - **M1 = P × s(h)**, the brief's formula. s is the nearest complex's flow over its daily mean.
  - **M2 = G(h)**, stations only. G is the station flow summed with a Gaussian (σ 300 m, cut at 800 m).
  - **M3 = P × G(h)**.
  - The crowd index is the model divided by width in feet, and it is always labeled `estimate`.

## 4. Validation against DOT counts
"Observed" is the mean of the Oct 2024, May 2025, Oct 2025 and May 2026 rounds, with 0 treated as not collected. The table gives Spearman ρ with a bootstrap 95% CI. These are the 98 street sites with counts; all 113 sites are in `data/crowds/out/validation.json`.

| Period | Retest ceiling (Oct 25 vs May 26) | M0 static | **M1 (brief)** | **M2 stations** | M3 static × stations | Width alone |
|---|---|---|---|---|---|---|
| Weekday 7–9am | 0.95 | 0.38 | 0.41 [0.23, 0.53] | **0.81** [0.71, 0.88] | 0.76 | 0.28 |
| Weekday 4–7pm | 0.94 | 0.47 | 0.52 [0.38, 0.63] | **0.83** [0.74, 0.89] | 0.81 | 0.24 |
| Saturday 12–2pm | 0.95 | 0.48 | 0.52 [0.37, 0.64] | 0.72 [0.60, 0.81] | **0.74** | 0.25 |

**Time of day, within a site** (does the model predict how a site changes between periods?):

| Ratio | Retest | Nearest-station shape | M3 |
|---|---|---|---|
| Weekday PM / AM | 0.88 | 0.22 | 0.18 |
| Saturday midday / weekday PM | 0.72 | 0.32 | 0.46 |

**What this says:**
- **Where is busier:** subway volume nearby ranks the count sites well (0.72–0.83, against a ceiling of 0.95). POIs add nothing over stations (M3 ≈ M2). The brief's formula (M1) is weak because the hourly shape is normalized: it throws away station volume, the strongest signal, and keeps the POI layer, the weakest.
- **When is busier:** subway hours do not predict sidewalk hours. Observed street-site PM/AM is a median 2.81 (about 1.9 per hour). The station shape predicts 1.45, and citywide it makes 7am busier than 6pm (median 1.44×). Subway peaks are commute peaks, while sidewalk peaks come later in the day (shopping, dining, errands). Hour-by-hour shape is unvalidated by any source we have. The only time evidence is DOT's three windows.
- **Dividing by width is untested.** Counts measure volume, not crowding. Wider sidewalks are on busier streets (+0.25), so dividing by width works against the volume signal. Compared on a per-foot basis, M3 reaches 0.70–0.77, but that comparison shares the width term on both sides, so it is not evidence.
- **Validation range:** the sites are commercial corridors and bridges. No residential side street or park path is counted, so the contrast runners care about most (a busy avenue against a quiet side street) is under-tested.

## 5. The reviewer's runs (validation only, never input)
**Method:**
- Data: 196 matched runs (last 12 months), raw GPS with timestamps read in memory and trimmed 200 m at both ends (011). Only per-pass aggregates are written, to `data/crowds/out/`.
- Signal stops removed: fixes within 25 m of an OSM signalized crossing are dropped, and so are fixes slower than 1.0 m/s.
- Passes: fixes snapped to the nearest way within 15 m, grouped into passes of at least 60 m.
- Outcome: pass speed relative to the run's median moving speed.

**Results:**
- **The estimate can't see most of this runner's distance.** 3,465 passes, 484 km. Only 13% of moving distance is on OSM sidewalk ways. The rest is cycleway (31%), footway (24%) and pedestrian (22%): greenways, the esplanade and park paths, which have no width and almost no POIs.
- **Mostly early hours:** 124 of 196 runs started between 6 and 9am, and 78% are on weekdays.
- **On sidewalks (674 passes):** crowd index (M3/width) against relative speed gives ρ = −0.10 (95% CI −0.18 to −0.02, bootstrap by run). Passes in the top 10% of the estimate ran 1.052× the run median, against 1.082× elsewhere, about 3% slower. The signal is small and goes the expected way, but it is confounded with busier blocks having more curb cuts and unsignalized crossings.
- **Within a way, only the hour changes** (26 ways, 605 passes): ρ = −0.06. Too few hours outside 6–9am to say more.
- **On paths:** POI pressure against speed is +0.19, the wrong sign. The estimate is picking up path type and terrain, not crowds.
- **Slowdowns:** after signal zones are removed, this runner almost never drops below 1 m/s at any hour, and relative pace is flat from 6am to 6pm.

**Conclusion:** for this runner the estimate does not usefully predict where they slow down. That mostly reflects where and when they run: paths, early mornings. It is not strong evidence against the estimate on midday sidewalks.

## 6. Where it fails
- **Paths, greenways, esplanades and bridges.** These carry most of a waterfront runner's distance. The model gives the Brooklyn Bridge (5,300 people at the 4–7pm count) and the Hudson River Greenway an estimate of 0. Recreational and through traffic is invisible to a subway-and-shops model.
- **Far from the subway:** 46% of sidewalk ways have no complex within 800 m, so M2 and M3 are 0. That is weakly supported: the 10 count sites beyond 800 m have a median PM count of 729, against 4,442 elsewhere. But it is an assumption and should be labeled as one.
- **Bus and regional hubs are under-ranked:** Fordham Rd, 125th St, Queens Blvd and Third Ave in the Bronx have large bus, LIRR and Metro-North flows that the subway data doesn't see. POIs are also under-mapped there.
- **Office districts are over-ranked at 4–7pm:** FiDi, Downtown Brooklyn and Brooklyn Heights (Montague, Broad, Trinity, Delancey) have dense POIs and big stations, but their sidewalks empty out sooner than the model expects.
- **Hour of day:** the subway shape is a commute shape (section 4). Sundays, nights and before 7am have no count data at all.
- **Events, weather, season, tourists, street fairs, construction and scaffolding:** none are modeled.
- **Width as a divisor** amplifies polygon errors: the top citywide 6pm cells were 0.8–2.2 ft slivers in FiDi until widths were clamped.

## 7. Better data and what it costs (prices not verified; quotes needed)
- **[StreetLight](https://info.streetlightdata.com/streetlight-data-plans-and-pricing):**
  - What it sells: pedestrian volumes by road segment in 15-min bins, as an add-on to a multi-mode tier.
  - Cost: [one state DOT listed $99K/yr for that tier](https://iowadot.Gov/systems_planning/pdf/MPO-RPA-Meetings/0322/Mobility-Data.pdf) (undated slides).
  - Catch: the volumes are modeled from device location data, so they are another estimate that would need the same DOT validation.
  - The closest match to what we need, and the most expensive.
- **Placer.ai and other foot-traffic panels:** visits to venues, not sidewalk segments. Quote only ([G2](https://www.g2.com/products/placer-ai/pricing)). They would replace the POI layer, which is the weakest input, so they are poor value here.
- **[Strava Metro](https://www.theregister.com/2020/09/28/strava_free_data/):** free for planners, advocates and researchers since 2020. Commercial eligibility is unconfirmed. It counts Strava users, so it shows where runners go, not where crowds are, though it does cover paths.
- **User reports:** `api/feedback.py` (the other session, uncommitted) already takes `crowded` on a stretch. They cost UI work, not money. They are sparse: a stretch × day type × time band needs several reports before it means anything. Reports are the only source that covers paths and real hours, and the right long-term ground truth.
- **More runners:** this spike found a roughly 3% effect at ρ ≈ 0.1 with one runner. Telling stretches apart by hour would need many runners per stretch per time band, likely hundreds of active runners. Each one also needs consent, storage and deletion designed first (PROJECT_PLAN §3, decision 011).
- **Own counters** (computer-vision or infrared): one block each, hardware plus install, quote needed. Useful only to check specific corridors such as the esplanade.

## 8. Recommendation for Phase 2 step 5
**Build first: a crowd *level* on sidewalk stretches from subway volume, with time from DOT's windows, and `not_scored` everywhere the data can't speak.**
1. **ETL** (`etl/load_crowds.py`, new tables):
   - `station_flow` (complex × day type × hour, entries + OD exits, refreshed monthly);
   - `sidewalk_width` (way_id, width_ft, status, polygon status; stubs under 30 ft inherit from a neighbor; clamped to 5–40 ft);
   - `dot_ped_counts` (sites and rounds, for the eval).
2. **Spatial term:** M2 (station kernel), not the brief's M1. Drop the POI term: it adds nothing at the count sites and is biased by mapping. Revisit with a better POI source.
3. **Time term:** coarse bands with DOT ratios, not hourly station shapes:
   - weekday AM (7–9);
   - weekday midday, labeled "between count windows";
   - weekday PM (4–7);
   - Saturday midday.
   Before 7am, after 8pm and Sundays are `not_scored` ("no count data at this hour"), never assumed quiet.
4. **Output a level, not a number:** low / medium / high from citywide percentiles of volume per foot of width within the band. Paths, bridges and greenways are `not_scored` ("no crowd data for paths"). Ways more than 800 m from the subway are `low` with basis "far from the subway (assumption)".
5. **Eval** (`evals/crowds/`): Spearman against the latest DOT round, held out, at street sites, per period. It must stay at or above 0.70. Hand-picked checks: Times Square or Herald Square at 6pm is `high`; a residential block 800 m or more from the subway is `low`.
6. **Feedback loop:** log `crowded` stretch reports with the hour. They become the calibration set for paths and hours once there are enough.

**Fields:**
- **`RunConstraints`:**
  - reuse `start_time` / `start_hour` (in the other session's uncommitted `api/constraints.py`) as the hour input;
  - add `start_date: date | None` (defaults to the request date) to get weekday, Saturday or Sunday (and seasonal restroom rules later);
  - the existing `crowds: avoid | some | dont_mind` preference sets the weight.
- **Per stretch** (`api/segments.py` properties):
  - `crowd_level`: low | medium | high | null;
  - `crowd_status`: estimate | not_scored;
  - `crowd_basis`: plain text, for example "subway ridership within 800 m, weekday 4–7pm, sidewalk ~11 ft", or why it is not scored;
  - `crowd_band`: the day type and band used;
  - `sidewalk_width_ft` as a fact with source `52n9-sdep` (2022 imagery) and trust `listed`.
  - The hour at a stretch = start hour + miles so far × an assumed pace (10 min/mi unless stated). This matters only on runs that cross a band boundary.
- **Route level:** the `crowds` dimension = the share of distance at `high`, plus the share `not_scored`. If most of the route is `not_scored`, the dimension is reported as `not_scored`, not as 0 (009).

**Not now:** hourly crowd numbers, POI pressure, paid data. Revisit StreetLight only if user reports show sidewalk crowding is a top complaint and the band estimate is wrong.
