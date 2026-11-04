# 017: Closures. Known closures are a hard rule: the corridor catalog's East Midtown missing link, curated closures, and runner reports a reviewer confirms

**Status:** proposed (Phase 2 step 6, 2026-11-02). No ranking weight changed; closures reject candidates, they don't score them.

## Context
Decision 012's corridor catalog found 107 gaps: 21 internal gaps (a corridor's end-to-end route left the corridor) and 86 gaps between corridors 50 m to 1 km apart. The East Midtown Greenway's 709 m gap is the known example. 012 noted these are structural (no path), not temporary closures, and that no closure data was loaded. This step makes known closures a hard rule (product rule 3: never quietly route through one) and adds a way for runners to report one.

## What a gap is, and why only one applies
A gap's stored geometry is not the closed piece. For an internal gap it is the **detour** the verification route took around the missing piece, on streets that are open. For the East Midtown gap, that's the 51st Street pedestrian crossing and the 54th Street pedestrian bridge. Closing it would close them.

So the closure is the **missing link**: the straight line from where the route left the corridor to where it came back. For East Midtown that's 219 m along the shore, between the end of the 51st Street esplanade and the start of the greenway. The closure is a strip 10 m either side of the link, with 25 m left off each end so the ways used to go around stay open.

**Two drafts closed real paths, and the eval caught it only indirectly.** In both, the top 3 avoided every closure, but because the rule was rejecting candidates on real paths. Counting closure rejections per review row showed it:
- **Draft 1** applied a gap when no single walkable way ran 30 m or more inside its strip. That applied 45 gaps. It rejected 35 of 93 candidates at Upper East Side 3 mi, 51 of 99 at Upper East Side 6 mi and 29 of 100 at DUMBO. The strips lay along:
  - the Queensboro Bridge's pedestrian outer roadway, tagged `access=no, foot=designated`, which the walkable filter dropped but GraphHopper routes on;
  - the Brooklyn Bridge Park Greenway at Old Fulton St, split into 17 short OSM pieces;
  - the Hudson River Park Esplanade.
- **Draft 2** fixed the filter (a `foot` tag overrides `access`, as in GraphHopper) and summed every walkable piece running within 45° of the link. That applied 39. It still rejected candidates in Hudson River Park near Christopher St, where the esplanade curves across the strip, and at Willets Point Blvd.

**Every one of those was a gap between two corridors.** A between-corridor gap is only the shortest line between two corridors 50 m to 1 km apart. Nothing closed there, and the line often runs along a real path. So:

| | gaps | applied | not applied: between corridors | not applied: walkable ways along the link | not applied: link under 80 m |
|---|---|---|---|---|---|
| internal | 21 | 1 | – | 13 | 7 |
| between corridors | 86 | 0 | 86 | – | – |

- **Applied: the East Midtown Greenway missing link**, with no walkable way inside its strip.
- **Not applied:** each row stays in `closures` with `applied = false` and its reason. For example, East River Park's 1,506 m gap gives "199 m of walkable ways run along the link (Williamsburg Bridge Footpath and others): closing it would close them".
- **"Walkable along"** sums the walkable pieces running within 45° of the link. The bar is 15 m, half the pass-through length, so a doubtful gap stays open rather than closing a real way. The cost of leaving a gap open is low: if nothing walkable runs there, no route can either.
- **Under 80 m:** after trimming, less than 30 m of strip is left, so no route could ever trip the rule there.

**Honest scope:** the one applied closure has no walkable way along it, so GraphHopper can't route through it today. The rule doesn't change any current route. It holds if OSM adds a way there that's still closed in reality. Confirmed reports are what will change routes.

## Decision
**1. Table `closures`** (etl/sql/schema.sql). Each row has:
- kind `corridor_gap` or `report`;
- name, reason, source, and trust (`listed`, product rule 2);
- `applied` and `not_applied_reason`;
- `in_router`;
- `link_m` and `walkable_along_m`;
- `active_until` (NULL: until removed);
- a polygon.

`etl/build_closures.py` rebuilds the corridor-gap rows after each catalog build (`make corridors`). Confirmed reports are kept.

**2. Hard rule** (`api/closures.py`, `api/generate.py`).
- **Rejection:** a candidate with 30 m or more of its length inside an applied closure is rejected (reason `closure`), next to the no-go-zone check. Crossing a strip, as a street across the missing link does (about 20 m inside), is allowed.
- **Measurement:** the length inside is sampled every 2 m in local planar meters, with no PostGIS in the request path.
- **Router:** closures with `in_router` (confirmed reports, which sit on real ways) also go to GraphHopper as areas with priority 0, like no-go zones (decision 010).
- **Corridor gaps aren't given to the router.** Nothing routable runs along an applied one, and an area would block any street that crosses the strip.
- **Which closures apply:** only those within reach of the start (half the distance × 1.2, + 200 m), so a request carries a few areas, not all of them.
- **Where it's wired:** `make_loop` (it prints "N known closures within reach") and the eval harness (`top_loops`).

**3. Reports** (table `closure_reports`, `api/feedback.py`).
- **What's stored:** route feedback already has the `closed_or_blocked` issue (decision 014). Each one is stored with the stretch's index, name and geometry as the route showed it, plus the run time and the note. A whole-route report is kept without geometry, since it has no place.
- **A report never closes a path by itself.** `confirm_report` (a reviewer step) turns one into a closure:
  - the stretch buffered 8 m;
  - `in_router` true;
  - source "runner report #N on route R, confirmed DATE";
  - an optional `active_until`.
- **Why a reviewer step:** one wrong report would otherwise close a path for every runner.
- **Checked against Postgres** in a rolled-back transaction: save, confirm (a second confirm returns nothing), load, and the stretch is passed through.

**4. Curated closures** (`routing/curated_closures.geojson`, parsed by `api/closures.py`, loaded by `etl/build_closures.py`; `make closures`).
- **What they are:** closed places checked by hand against public sources.
- **What each entry carries:** a name, a reason, its source URLs, a trust label (`listed`), the date it was checked and a review-by date.
- **What's refused:** an entry with a missing field, a source that isn't https, an unknown trust label, a review-by date before the checked date, or a geometry that isn't a polygon.
- **How they apply:** like every closure (30 m inside is rejected), and also given to GraphHopper (`in_router`), since a curated closure is a real closed area on ways a route would otherwise use.
- **Stale entries:** the eval fails once a review-by date passes, so a stale entry gets checked again instead of trusted forever.

**First entry: East River Park, northern section.**
- **What and since when:** closed since 2025-09-08 for the East Side Coastal Resiliency project, esplanade included, with reopening projected for the end of 2027. Checked 2026-11-02; review by 2027-02-01.
- **Sources:**
  - [EV Grieve, Dec 2025](https://evgrieve.com/2025/12/timeline-for-reopening-northern-section.html): "basically everything above Houston Street to 15th Street", reopening pushed to the end of 2027.
  - [NYC DDC, May 2025](https://www.nyc.gov/site/ddc/about/press-releases/2025/pr-052925-ESCRopenings.page): southern sections reopening, and new closures announced for the northern area, without a boundary.
- **The date:** 2025-09-08 is the reviewer's. EV Grieve dates the closure only to Phase 2 construction starting in September 2025.
- **How it's drawn:**
  - **Base:** OSM's park polygon (osm_parks area a216471684, snapshot 2026-10-28), cut along East Houston St's line extended to the water. That gives 85,640 m², 46% of the park.
  - **Northern edge:** the reviewer chose E 15th St. Because of the 29° grid, E 15th St's line reaches the river just north of the park's tip. The park polygon lies wholly south of it, at least 81 m away, and between the two are only inland streets (E 13th St, Avenue D, sidewalks). So nothing is added north of the park. The East River Esplanade past Con Ed starts 4 m north of the E 15th line and stays open.
- **OSM already shows it closed:** the 2026-10-28 snapshot marks the park's paths as `highway=construction`, and only 68 m of walkable footway is left inside. That's why GraphHopper wouldn't route through it even before this entry. The entry guards against mappers reopening paths before the park does, and holds the sources and review date.

**Second entry: the NYU Langone Health driveways between E 33rd and E 34th St, east of First Avenue** (2026-11-04).
- **Ground truth:** after a run test, the reviewer reported that the Kips Bay routes enter the esplanade at E 33rd St, but on the ground the only entrance there is E 34th St.
- **What the routes used:** E 33rd St to its dead end past First Avenue, then about 140 m through three OSM ways to E 34th St by the FDR (672581827, 672581830, 1424092636). Those ways are `highway=service`, `service=driveway`, with no access tag. Two of them lie inside OSM's polygon for NYU Langone Health – Tisch Hospital. GraphHopper's foot profile read them as a public walkway. No gate is mapped.
- **Drawn as:** the three ways merged into one line, 16 m left off each end and 1 m either side. It touches no public sidewalk or street, only two other campus driveways. A first, wider draft (4 m, 8 m trimmed) also touched two E 34th St sidewalks, which GraphHopper would have closed too.
- **Trust:** `verified`, with the ground check recorded: by the reviewer, 2026-11-04. Its sources are the three ways' OSM pages. Review by 2027-05-04.
- **Rule change:** an entry may now carry `ground_check: {by, on}`. `verified` requires one; without it an entry is `listed`.
- **Not done (the reviewer's call):**
  - removing the ways from the routing extract (a data correction that needs a graph rebuild);
  - editing OpenStreetMap. `access=private` there would make this entry unnecessary.
- **Effect on Kips Bay:** all three #1s keep their waterfront route and now reach the esplanade along E 34th St. Before, each walked 249 m through the closure area.
  - **3 mi:** score 83.4 → 75.1, signals 2.6 → 3.6 per mile, 58% park or water.
  - **4 mi:** 86.3 → 83.0.
  - **6 mi:** 68.0 → 66.0.

  The top 3 keeps the same routes at every distance. The six run-test files were regenerated.

## Eval (`evals/routes/test_closures.py`)
The route check is PostGIS's own intersection length against every applied closure in the city. It doesn't rely on the generator's sampled length or reach filter.
- The East Midtown Greenway gap is an applied closure, labeled `listed` with its catalog source.
- No applied catalog closure has 30 m or more of walkable ways inside it, summed in any direction. This is stricter than the build's along-the-link test.
- **Real paths stay open:** the four places the drafts closed (Queensboro Bridge outer roadway, Hudson River Park Esplanade near Christopher St, Brooklyn Bridge Park Greenway at Old Fulton St, Willets Point Blvd) have no applied closure within 20 m.
- A line along the East Midtown missing link is caught; the detour streets around it are not.
- **No generated route passes through a known closure:** the top 3 at all 15 review rows, for both lights settings (30 cases).
- **A confirmed report reroutes:** closing a stretch of the Upper East Side 3 mi #1 (15% of its length, buffered like a report) gives a top 3 that doesn't pass through it.
- **The NYU Langone driveways:**
  - the closure touches no public sidewalk, crossing or street;
  - no top-3 route at any of the 15 rows, for both lights settings, walks more than 5 m along their closed middle. The run-test GPX that prompted this walked 114 m there.
- **Curated closures:**
  - every entry in the file is in the table, applied and in the router, with its trust, sources and dates;
  - none is past its review-by date;
  - no top-3 route at any review row, for both lights settings, enters one (more than 1 m inside).

**Result (2026-11-02):** 38 closure checks pass, along with the 9 route evals and 5 crowd evals (52 in all). There are 349 unit tests.
- **At the review starts,** the East Midtown closure is within reach of 10 of the 15 rows and rejects none of their 863 candidates. So no review route changed.
- **The confirmed-report check at Upper East Side 3 mi:**

| | #1 | park or water | signals/mi | inside the closed stretch | score |
|---|---|---|---|---|---|
| before | out-and-back on Bobby Wagner Walk, 3.04 mi | 85% | 0.7 | 1,557 m (733 m, run both ways) | 92 |
| after | street out-and-back, heading 29°, 3.01 mi | 52% | 3.7 | 0 m | 78 |

  The old #2, a loop on the runner's own route, also ran 778 m through the stretch and dropped out. The new #2 is a waterfront loop that avoids it: 44% park or water, 4.6 signals per mile. A closure on the one waterfront path from this start costs the route most of its park and water. That's the right trade for a closed path, and the score drop shows it.

**Curated result (2026-11-02):** 84 evals pass in all (the 52 above, plus 32 for curated closures). There are 357 unit tests.
- **Review starts:** the East River Park closure is within reach of 9 of the 15 rows. With and without it, for both lights settings, no top-3 route enters it, and the top 3 is unchanged at every row.
- **Reviewer's run-test files:** none of the six Kips Bay GPX files enters it. The nearest is the 4 mi route, which turns around 285 m north of it. None was regenerated.

## Limits
- **No live closure data yet.** Parks construction closures, DOT street closures for construction (NYC Open Data) and event closures are not loaded. Corridor gaps are structural. Reports need a reviewer.
- **Missing links are straight lines.** Where a shore curves, the real missing piece can bow away from the strip.
- **Curated closures are only as current as their last check.** The review-by date makes a stale entry fail the eval, but nothing reopens one automatically. East River Park's entry has to be removed by hand when the park reopens.
- **30 m inside is the threshold.** A route that crosses a strip at a shallow angle could pass it without being caught, or be caught for crossing.
- **A reported closure's area blocks any edge that touches it** in GraphHopper, including a street crossing the closed stretch at its ends.
- **Closures don't explain themselves to the runner yet.** A rejected candidate is just gone. The stretch fact "Known gap nearby" (decision 014) still shows near a gap.
