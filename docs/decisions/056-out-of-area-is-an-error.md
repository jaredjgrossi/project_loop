# 056 · A request outside the area is an error, not a question

*2026-11-14 · branch `out-of-area`*

## Decision
When the start or end a runner names is outside the five boroughs, the server sends an `error` event with the code
`out_of_area`, the place the runner named (`place`, e.g. "Tampa") and the short name of what Loop covers (`covers`,
"New York City"). Before, the same request got the question "Loop only covers New York City. Where should it start?",
which dropped the place's name and read as a prompt to retype, not as a limit. The contract and `ios-wiring.md` list
the code and its fields.

## What Loop covers today
All five boroughs, not Manhattan only:
- **Routing:** the GraphHopper foot graph is built from the New York State OSM extract clipped to the NYC Planning
  "Borough Boundaries (water areas included)" polygon (`routing/prepare_osm.py`), so piers and esplanades over water
  are in and New Jersey is out.
- **Places:** the `places` table keeps only features inside a borough (`etl/load_places.py`).
- **Addresses:** NYC Planning Labs GeoSearch, with a bounding-box check on what it returns (`api/geocoding.py`).

## Choices worth knowing
- **The parse decides, as before.** Claude marks a place `outside_nyc` (prompt `parse_v7`, unchanged); the rules turn
  that into the error. Claude still writes no copy: the text is a template (`error.out_of_area`, with
  `error.out_of_area_unnamed` when the request named no place).
- **The place is the runner's own word,** trimmed, not a corrected or geocoded name.
- **An error ends the stream,** like the other errors: no `parsed` event, no build, no question to answer.
- **Parse evals:** P19 ("5 mi from hoboken path") now expects `ERROR` with code `out_of_area` and place "Hoboken PATH";
  the grader reads the place as the places table reads names, so "Hoboken PATH station" also passes.

## Not done
- **A via outside the five boroughs** is not flagged (the via schema has no `outside_nyc`); the lookup finds nothing and
  the runner is asked for an address. Adding the flag means a new prompt version.
- **A phone located outside the five boroughs** still falls back to the saved home or a question (R16); no place name
  is known to put in an error.
- **Typed answers:** a place typed in answer to "Where should it start?" is not checked against the area, so it ends up
  as "Couldn't find X" if the lookup has nothing.
