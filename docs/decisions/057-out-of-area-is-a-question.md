# 057 — Out of area is a question, and every error has its own words

**Status:** accepted · pairs with the server's 056 (`out_of_area`)

## Decisions
1. **`out_of_area` is not an error.** The SSE `error` event with that code decodes to its own case. The app
   shows a question-style card, in its own copy built from `place` and `covers`, never the server's text:
   "Loop doesn't know Tampa yet. It covers New York City for now." With no place: "Loop covers New York City
   for now." One button, "Change the start": back to the landing with the typed sentence still in the field and
   the keyboard up (it waits for the sheet to rise, or the field opens behind the keyboard).
2. **The landing knows before a request, on the phone.** The server has no coverage endpoint and the phone's
   location never goes to it for this. A simplified outline is bundled (`Loop/Resources/coverage.geojson`,
   a FeatureCollection with a Polygon or MultiPolygon and `properties.name`); the phone checks its own location
   against it (ray cast on lon/lat). Outside it, one quiet line under the field, "Loop covers <name> for now.",
   and the Try-one tiles name a start inside the area. The name comes from the file, never from code.
3. **"Can't reach Loop" is for real network failures only.** Every error code has its own copy
   (`ErrorCopy`): engine_unavailable, bad_final, parse_failed, bad_request, expired, route_not_found. An unknown
   code shows the server's text if it sent some, else "Something went wrong with that request." The old fall-through
   (empty text shown as "can't reach") is what said that in Florida.

## Not done
- The outline file itself comes from Phase 3. Until it is in the app there is no landing line and no switch of
  examples (the phone never guesses where it is); the question card after sending works without it.
- The Try-one examples' New York starts (Bryant Park, Kips Bay) are examples, not coverage: they change if the
  covered area does.
