# 047: Misreads from the full review: named parks, "here", addresses, landmarks, amenities and lap entries

**Status:** accepted (2026-11-12). From the full product review (4.2: Q1, Q2, Q3, Q4, Q5, Q6, Q7). Amends decisions 026
(places), 035 (laps) and 041 (parks).

## Named parks (Q1, Q2)
- Haiku records "Central Park" as kind `the_park` about as often as kind `place`. The code read `the_park` as "the
  nearest park" and threw the name away, so "5 miles in Central Park" ran the East River Esplanade.
- A `the_park` whose name has any word beyond the generic ones (the, a, park, nearby, local, closest, ...) is a named
  place, looked up like any other (`parse.named_park`). "The park", "a nearby park" and "park" stay generic.
- A named park that isn't found asks, as any place does. It never falls back to the nearest park.

## "Here" as an answer (Q3)
- Typed as the answer to "Where should it start?", "here", "my location", "where I am", "near me" and the like mean the
  current location, `use_my_location`, source `said`. Before, "here" went to the place lookup and found a bar in
  Greenpoint.
- With the location off, it asks "I can't see where you are. Turn on location for Loop, or type a place." It doesn't
  fall back to home, and it doesn't ask the same question again.

## Addresses as vias (Q4)
- An address as a via ("past 1000 5th Ave", or typed in answer to "Couldn't find X. What's the address?") is geocoded
  like a start's address, with the same borough rules (R19). Before, only starts and ends were: a typed address as an
  answer to a via question looped on "Couldn't find".

## Landmarks (Q4, Q5)
- OSM maps most landmarks as building outlines or relations, which the places extract skips: the Met, the Guggenheim,
  the Whitney, the Empire State Building, the Chrysler Building, the Flatiron Building, One World Trade, Madison Square
  Garden, Gracie Mansion, Grant's Tomb, the Natural History Museum, and stadiums that were only stations ("161st
  Street-Yankee Stadium").
- `etl/curated/landmarks.json`: 40 landmarks (museums, icons, stadiums, theaters, cathedrals, campuses, stations), with
  the names runners use as aliases ("The Met", "MoMA", "Guggenheim").
  - Every position is a point inside the feature's OSM outline, read from the NYC extract. None is a remembered
    coordinate: my guesses were within 70 m for buildings but 150-200 m off for a few large sites.
  - `etl/load_landmarks.py` loads them as kind `landmark`, trust `listed`, source "Loop curated landmarks (position
    from OpenStreetMap)". `make places` runs it, and `python -m etl.load_landmarks` refreshes just them.
- A landmark beats a shop, amenity or leisure place with its name or alias: "The Met" is the museum, from any borough,
  not a shop called Met in the Bronx. Neighborhoods are untouched.
- Aliases that would shadow another place were left out ("Flatiron", "Columbia", "Seaport", "UN").
- Places that already load from OSM aren't repeated (Rockefeller Center, Lincoln Center, Times Square, Grand Central,
  Penn Station).

## Amenities (Q7)
- "Bathroom near mile 3" parsed to a chip and the engine never read it. Loop doesn't plan stops yet, so
  `before_build` says so: `{"gap": "later", "key": "amenities", "text": "Can't plan a restroom or water stop along the
  route yet. The route is built without it"}`, once however many stops. It doesn't block the build.
- The restroom and fountain data is loaded (Phase 1) and not used by the engine. Planning stops properly (nearest
  open restroom to mile N, with its source and status) is the follow-up.

## A lap starts where the way in meets the ring (Q6)
- "Loop around the reservoir" from E 86th & 2nd Ave came back "Couldn't build a route". The run enters the track by steps
  at its south-west end. The lap's start and end point was the ring point nearest the start as the crow flies, 180 m
  further along the track, so the run went there and back at the end: a 195 m spur, which decision 044 rejects. From
  W 86th St it worked, because the nearest point was the entry.
- The engine routes the shortest way through the vias, finds where that route first comes within 15 m of a closed
  lap's ring (`via.lap_entry`), and routes again with the lap starting and ending there (`Via.entered`). Open laps (a
  past A-to-B route) are unchanged.
- The same case showed that decision 045's waypoint fix didn't cover the engine's own shortest-way route. The engine
  now wraps its routers once (`without_waypoint_spurs`, idempotent) so every route it builds is covered. The wrapper
  repeats up to three times while a moved waypoint still makes a spur. It isn't used for past routes.

## Tests
- Unit: `test_parse.py` (named parks, generic parks, a park not found), `test_answers.py` ("here", the no-location
  question, a typed address for a via, a geocoder miss), `test_engine.py` (amenity line, lap entry), `test_via.py`
  (`lap_entry`, `with_entries`, `entered`), `test_waypoint_spurs.py` (the repeat and its limit),
  `etl/tests/test_landmarks.py` (the file's shape, unique names, the main landmarks present).
- Parse evals P54-P59: five named parks and "10k past the Met then home" (60 cases).
- Live: `evals/places/test_lookup.py` (17 landmarks by what a runner types, a landmark beats a shop from three
  boroughs, neighborhoods untouched); `evals/routes/test_review_fixes.py` (5 miles in Central Park routes in it; a lap of
  the reservoir builds from the east; 10k past the Met passes it; a restroom stop gets its line and the run is built).
