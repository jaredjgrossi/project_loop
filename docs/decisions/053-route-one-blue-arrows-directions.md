# 053 · One blue route, first-pass arrows, a Directions list

Date: 2026-11-13 (phone test of PR #18). iOS only; no server change.

## Decisions
1. **The route is one blue line.** Street, path and waterfront are three tints of one blue (lightest, middle,
   deepest); path stays dashed. The tan street colour read as map, so only the waterfront looked like the
   route. The profile strip uses the same colours. Routes you are not on are neutral (warm white at night, ink on
   paper) at 55%, solid.
2. **Direction arrows, first pass only.** Thin chevrons in the route's own colour (the lightest blue at night, the deepest on paper), a little
   wider than the line so they read as arrowheads growing from it, spaced 72 pt apart in screen points. `RouteDirection.firstPass` drops any stretch that retraces ground covered at least 150 m earlier
   (within 14 m, for 5+ samples of 10 m), so an out-and-back or a lollipop's stick has arrows on the way out only.
   Big haloed arrows were rejected as bulky and tiny casing-coloured notches as
   unintentional-looking (phone, 2026-11-13); they follow the line as drawn at each zoom.
3. **Directions list.** A pill on the card opens the steps, built by code from the file's stretches and turnaround
   (`Directions.steps`): start on X, continue onto Y for 0.25 mi, turn around, head back, finish. Stretches under
   0.03 mi fold into the one before; same-name neighbours merge. Names are `listed` (OSM and the corridor catalog)
   and distances `measured`; the footer says so.
4. **Weather** comes from the server's `GET /v1/weather/nyc` (decision 051): city-level, no coordinates sent.

## Known gap
The file has no left/right turns, so a change of street reads "Continue onto". Turn-by-turn needs the server to
send maneuvers (GraphHopper instructions: sign, street, distance) with each route.
