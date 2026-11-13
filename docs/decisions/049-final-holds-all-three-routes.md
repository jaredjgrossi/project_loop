# 049: The final event holds all three routes in full

**Status:** accepted (2026-11-12). From the UI review (design-review-v1): the iPhone app's route switcher, "The way" list
and route cards need the second and third routes' details, honest names and the shape flag.

## What was there
- `final.routes` carried the top 3 as outlines (`id`, `rank`, `kind`, `label`, `score`, `distance`, `geometry`), and
  `final.route` the first route's full file (summary, markers, stretches, pieces). Routes 2 and 3 had no stats.
- Names came from the generator's label: "out-and-back on East River Esplanade and beyond", or just "on the waterfront".
- A loop that couldn't be found came back as the best out-and-back with a `no_good_loop` note, and nothing else
  for the app to act on.
- Stretches took the nearest named way, so a stretch of the East River Esplanade came back "FDR Drive" and the Hudson
  River Greenway "11th Avenue".

## Decision
1. **Each route of `final.routes` has `file`**, the route file `route` is: summary (distance, total lights, climb, waterfront
   and park share, wait, crowds, turnarounds, rank), markers, stretches and pieces. `route` stays as `routes[0].file` for
   the app until it reads `file`. The files are built side by side, one database read each. A real build's `final` is
   about 285 kB for three routes, against 76 kB.
2. **`final.shape`**: `{requested, met, shown}`. `met` is false when the shape asked for wasn't found (`shown` says what
   came back) or there is no route. A run to an end is `one_way`. The existing `kind` values stay (`loop`,
   `out_and_back`, `lollipop`, `a_to_b`): the app decodes them already, and a one-way run is `a_to_b` on the wire.
3. **Names from the main stretch** (superseded by [050](050-names-a-runner-would-say.md)). The stretch (name and kind, its pieces added up) that carries at least 40% of the
   route names it: "Out-and-back on East River Esplanade", "Loop through Central Park". With none that stands out, the
   generator's label decides ("Loop on the street grid"). "Unnamed path" and "waterfront path" never name a route. The
   `top3` and `provisional` events still use the generator's label, since measuring stretches for every candidate as
   it arrives would cost too much; the `final` name is the one to show.
4. **A stretch list, `summary.way`**: each stretch's name, kind, mile range and distance (measured), its trust label and
   source (the name is `listed`, from OSM or the corridor catalog), and `turnaround` on the stretch the run turns on.
5. **A path is named after itself.** A waterfront sample takes the named non-sidewalk path's own name, else "waterfront
   path"; a sample whose nearest way within 12 m is a path with no name is "unnamed path". A road's sidewalk or crossing
   keeps the road's name. Before: 320 m of the Esplanade came back "FDR Drive" (Upper East Side 3 mi, #2) and 800 m of
   the Hudson greenway "11th Avenue" (Astor Place 6 mi, #3).
6. **A reason line, `summary.reason`**, written by code from the route's own numbers, never the model: the park (named,
   at 40% or more with one park carrying it, else "in parks" from 20%), the waterfront (from 20%), the lights, and flat or
   hilly. At most three parts. A park route isn't called a waterfront route for a sliver by the water.

## Known gaps
- Two routes can share a name when they run the same corridor ("Out-and-back on East River Esplanade" twice, with
  different turnarounds). The distance, score and stretch list tell them apart.
- A corridor with no name in the catalog is still "waterfront path near E 23rd St" (the road as a place to find it, not
  as its name); it never names a route.
- The `top3` names can differ from the `final` names.

## Tests
- `api/tests/test_segments.py` (the path naming), `test_naming.py` (route_name), `test_reason.py`, `test_summary.py` (the
  way list and turnaround, the reason), `test_make_loop.py` (the file is named from its stretches), `test_engine.py` (all
  three files, named from their own stretches, from the pool too, the shape flag in each case).
- Live, `evals/routes/test_final_detail.py`: a real build's three routes each have a full file with a way list that adds up
  to the route, a reason and the same name in the list and the file, no stretch by the water or on a path is named
  like a road, and a loop request that is met says so.
