# 050: Route names a runner would say

**Status:** accepted (2026-11-13). From the phone: the `final` names read "out-and-back on the waterfront, heading 175°"
and "out-and-back both ways on the waterfront". Decision 049 named a route after its main stretch but kept the kind and
the generator's words around it.

## Decision
1. **A name is the stretch, which way it heads, and where it turns:** "East River Esplanade, north to 34th". No route
   type (the app's eyebrow has `kind`), no compass degrees, no generator words ("heading", "both ways", "rectangle").
   Capitalized, at most 36 characters (`MAX_NAME`; the phone asked for about 30, and its own example is 35).
2. **The stretch.** The one that carries at least 40% of the route, else (an out-and-back or one-way run) the biggest
   path, corridor, waterfront or park stretch that carries 15%, else the generator's place ("Waterfront", "Street grid").
   A loop is named by its two biggest stretches when each carries 15% ("1st Ave & E 30th St"), else its one.
3. **The heading** is one of four points (north is 315 to 45 degrees: Manhattan's avenues run 29 degrees off north and a
   runner still says north). It is measured from where the route joins its stretch to the point farthest from the
   start, so a start inland of the river doesn't make the esplanade run "east". With no stretch, from a quarter of the
   way out. A loop says "clockwise" or "counterclockwise" instead (shoelace on the route).
4. **Where it turns** is the nearest named street within 80 m of the far point, other than the stretch itself and not an
   expressway, highway, bridge or FDR (`db_cross_street`, from `osm_ways`), said short: "34th", "Canal", "1st Ave".
   Nothing within 80 m, or the far point within 300 m of the start: no "to X", or no heading.
5. **Fit.** If "stretch, tail" is over 36 characters it drops the turnaround, then the heading ("Hudson River Greenway,
   south to Canal" is 37, so it becomes "Hudson River Greenway, south"); street words are shortened (Street to St,
   Avenue to Ave) before the stretch is cut.
6. **Three routes, three names.** `name_ladder` gives each route its names, most telling first; the second is the
   stretch with the distance shown ("East River Esplanade, 3.0 mi"). `settle_names` (run in `route_files`, so for a
   build, a shape edit and a run again alike) gives each route the first name no earlier route took, else the first with
   " (2)". It also drops the generator's `plan` and the ladder from the files the app gets; `make_loop` writes `plan`
   for the pool and the evals.

## Not done
- `top3` and `provisional` entries still carry the generator's name with the kind in it ("Out-and-back on the
  waterfront"), since measuring stretches for every candidate as it arrives costs too much (decision 049). The `final`
  names are the ones to show.
- Two routes up the same corridor to the same cross street differ only by distance, and by "(2)" when that is the same
  too. The three-wide shapes (a loop, an out-and-back, a second out-and-back) rarely meet that.
- The cross street is the nearest named street to the turnaround, not an intersection test: a turnaround at a pier may
  name the street beside it.
