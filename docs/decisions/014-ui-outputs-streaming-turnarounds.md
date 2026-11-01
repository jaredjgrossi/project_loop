# 014: UI-ready outputs, streaming generation, walking-distance turnarounds, and corridor names

**Status:** accepted and implemented (Phase 2, 2026-11-01). Extends 012. No ranking weights changed.

**Numbering:** written as 013. Renumbered to 014 because another session's crowd-signal spike (`013-crowd-signal-options.md`) took 013 first.

## Context
The UI reference study (`docs/ui/references-v1.md`) asks for these engine features:
- the first route on screen in about 1 s, refined in place;
- "Best of 20" with a reason, which needs the candidate pool;
- stretch captions ("Mile 1 · East River Greenway");
- an elevation scrubber with mile detents;
- a departure-hour slider;
- the "I ran it" rating.

Separately, 012 left Kips Bay 4 mi and Flatiron 4 mi with rectangles at #1, because every waterfront candidate missed the ±5% distance limit.

## Decision
**1. Streaming, prioritized generation** (`api/generate.py`). Jobs run on a priority queue:
1. anchor lookups, one per source (corridors, parks, waterfront), in parallel on their own connections;
2. walking-distance anchored routes;
3. straight-line anchored routes;
4. heading out-and-backs;
5. rectangles;
6. round trips.

After 012, anchored routes were #1 at 11 of 15 review starts, so they go first. `on_candidate(candidate, seconds)` is called as each candidate passes the hard rules. `GenerationResult.timing` gives the first candidate, when the eventual #1 arrived, and the total. Jobs now return a `Rejection` instead of mutating a shared counter.

**2. Candidate pool.** `GenerationResult.pool` holds every job's outcome, JSON-ready:
- its status: chosen, ranked, out of tolerance, or rejected with a reason;
- the seconds at which it arrived;
- its metric vector (`Candidate.metric_vector()`: distance, miss, every shape and context metric);
- its ranking dimensions with their labels.

`make_loop --pool FILE` writes it, together with the parsed request and the timing.

**3. Per-segment GeoJSON** (`api/segments.py`). A route is labeled every 20 m as a catalog corridor, OSM park, waterfront, street or path, and merged into stretches, with changes shorter than 150 m absorbed. Each stretch has:
- a name, a kind and its mile range;
- its signalized crosswalks (`measured`) and its climb (`estimate`);
- facts, each with a source and a trust label. Stretch facts are `listed`, because OSM and the catalog say a path is there, not that it's open today.
- any known catalog gap within 50 m, added as a fact.

An unnamed catalog corridor is named after the nearest way ("waterfront path near East 23rd Street"). `make_loop` appends the stretches to each saved route's GeoJSON.

**4. Elevation with mile positions** (`api/elevation.py`). GraphHopper now imports elevation from the Skadi provider: public Terrain Tiles on AWS, built from USGS data in the US. The graph moved to `routing/graph-cache/foot-v3`, and four tiles were downloaded. Routes carry one height per point.
- **The profile** has a point every 0.1 mi, plus gain and loss (with a 1.5 m hysteresis, so tile noise isn't climbing), min, max and the steepest 100 m grade.
- **It is labeled `estimate`:** the tiles are a smoothed ground model, and on a bridge they give the ground or water below the deck.

**5. Hour of day.** `RunConstraints.start_time` (HH:MM) has existed since 009. `start_hour` now exposes it, `describe()` shows it, and it goes into the route GeoJSON and the pool. Nothing hour-dependent (crowds, restroom hours) is scored yet, and the request says so.

**6. Feedback schema** (`api/feedback.py`, tables `generated_routes` and `route_feedback`). A runner gives "I ran it", a 1–5 rating that requires the run, issues from a fixed list (crowded, closed or blocked, too many lights, and so on), issues on a given stretch, and a note of up to 500 characters. No GPS track is accepted. `generated_routes` stores what was scored (request, metric vector, dimensions, stretches, elevation, timing), so a rating can be traced to it. There's no API yet.

**7. Turnarounds by walking distance along the feature** (`api/anchors.py`, `along_feature`).
- **The walking graph:** a feature's ways become a graph. Dead ends within 25 m of another path are joined, because OSM links them through sidewalks that aren't in the set. Walking distance from the entry is measured along it, so the opposite bank of a river is never offered and a gap ends a direction. Each branch out of the entry is a direction.
- **Picking the turnaround:** the generator picks the turnaround whose estimated total fits. The estimate is 1.3 × the straight-line distance to the entry, plus the walking distance there and back. Past a feature's end, the route continues along the path's own heading for half the shortfall.
- **New: both ways.** Reach the feature, run one branch, come back past the entry along the other, then home. From Kips Bay the waterfront runs 1.9 km south (to the Con Ed plant gap) and 0.7 km north (to the UN gap), and neither branch alone makes 4 mi.
- **Both placement methods are kept.** Walking distance alone lost the 6 mi waterfront routes that 012's straight-line method found, because those turn on a piece past a gap and let routing find the way through (Upper East Side 6 mi fell from 88% water to 13%). Every source now returns both a walking-distance set and a straight-line set, and the ranking chooses. Straight-line sets are scheduled after walking-distance ones.
- **Tried and removed:** joining gaps up to 800 m with a coastline-crossing test. On a jagged shore it rejected every same-bank join as well as cross-river ones, so it never fired.

**8. Corridor names** (`etl/corridor_names.py`, used by `etl/build_corridors.py`).
- **The rule:** use the longest path-type way name (greenway, esplanade, walk, trail and so on) that covers at least 20% of the corridor. A bridge name is used only when the bridge is most of the corridor, and a street name is never used. Otherwise use the OSM park that holds at least 30% of the corridor ("Governors Island waterfront"), without repeating "waterfront". Otherwise "unnamed".
- **Result:** 72 names come from ways, 60 from parks and 28 are unnamed. Fixed examples: "Craig Road North" became "Governors Island waterfront", and "Manhattan Bridge Pedestrian Path" (a 10.8 km waterfront cluster) became "Brooklyn Bridge Park waterfront".

**9. Corridor catalog regression check** (`evals/routes/test_corridor_catalog.py`). It checks four things:
- the count stays within 130–200 (160 today);
- an internal gap of 650–770 m is found within 300 m of East 53rd–60th St (the 709 m East Midtown Greenway gap), located by place so a renamed corridor still passes;
- no corridor is named like a bare street;
- every corridor has a name and a name source.

**10. Speed.** The catalog build now stores `waterfront_paths`. Selecting coastline paths per request took about 0.8 s.

## Result (all values measured; generated without the reviewer's runs; shares on routes trimmed 200 m at both ends)
4 mi rows, step 2 → now:

| start | #1 park % | #1 water % | #1 signals/mi | top 3 now |
|---|---|---|---|---|
| kips-bay | 4 → 16 | 26 → 76 | 9.4 → 2.2 | water out-and-back (both ways), rectangle, corridor out-and-back |
| flatiron | 5 → 10 | 20 → 38 | 5.5 → 3.3 | corridor out-and-back, rectangle, rectangle |

All 15 review rows now have a park, waterfront or corridor route at #1. The real-run check (familiarity off): kips-bay 87 vs 77, flatiron 86 vs 77, upper-east-side 95 vs 87. All 9 evals pass, including the new catalog checks.

Timing, 4 workers on an 8-core laptop:
- **First candidate:** 0.11–0.34 s at every start.
- **Eventual #1:** 0.2–10.5 s, median about 2 s.
- **Total:** 1.7–18 s, up from 1–15 s in 012, because the anchored candidates roughly doubled.

## Limits and next levers
- **The eventual winner can arrive late:** Upper East Side 3 mi takes 7.8 s and Kips Bay 6 mi 10.5 s. The first candidate is fast but not always the winner. Levers: cache anchors and areas per start, check gaps with GraphHopper in the catalog build so walking distance can cross them (replacing the straight-line set), and fewer but better straight-line directions.
- **Kips Bay 6 mi is a near tie** between a waterfront out-and-back and a rectangle under the provisional weights. A small change to the candidate set flips it. Weights are untouched; this is for the ratings to settle.
- **Elevation is coarse,** and bridges read low. Nothing scores it yet.
- **Partly built:**
  - the UI brief this list came from (`docs/ui/brief-v1.md`) isn't in the repo, so these items were built from the one-line list;
  - there's no API or storage path for feedback yet, only the schema;
  - streaming is a callback, not a network stream.
