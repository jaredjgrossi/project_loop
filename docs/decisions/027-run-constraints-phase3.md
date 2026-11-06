# 027: RunConstraints for Phase 3 — place refs, hills, reuse, planned runs and source keys

**Status:** accepted for Phase 3, step 3 (2026-11-06). Extends 009 (the schema) and 020 (labels on every field).

## Decision
- **Place refs.** `start_place`, `end_place` and `via_places` (up to 5, in order) hold a `PlaceRef` with one of
  three kinds:
  - `place`: a places-table match (decision 026)
  - `address`: geocoded
  - `saved`: from the profile, such as `home`

  A place or address needs its name, borough and coordinates; coordinates must be inside New York City. A saved
  ref needs only its id, and the server fills the coordinates from the profile. Coordinates always come from the
  server, never from Claude.
- **One start:** exactly one of `start_address` (unresolved, the CLI's way in), `use_my_location` or `start_place`.
- **Distance is optional only when an end or a reused route sets the length** (R10). A via point alone doesn't.
- **Avoids** are `{name, how}`, where `how` is `area` (today's no-go zones) or `along` (a street, R15: crossing is
  fine). A plain name still works and means an area.
- **`hills`** (`avoid` or `dont_mind`) is a seventh preference. It is `dont_mind` in both presets and the default
  until it is scored in step 9, so no ranking changed: the pinned top-3 eval still passes, 30 of 30.
- **`reuse_route_id` and `reverse`.** `reverse` needs a route to reverse.
- **`planned`** is a whole second request for its own day (D6). It must have a `start_date` and can't nest another
  planned run.
- **Sources in the contract's keys.** `sources` maps a field to `said`, `preset`, `default` or `usual` whenever the
  value wasn't simply said: `{"distance_mi": "usual"}`. It replaces the private `_defaulted` set, so it survives the
  JSON round trip when the phone sends constraints back after a chip edit. `field_sources` reports every set field;
  a planned run's fields are reported as `planned.<field>`. `resolve_preferences` now says `said`, not `stated`.
- **`api/copy.py` holds every display string.** It turns the source keys into "you said", "Training preset",
  "default" and "your usual", and holds the request list's titles and values, which moved out of `constraints.py`.
  `request_items` keeps the shape the iPhone app's fixture reads (`key`, `title`, `value`, `origin`) and adds
  `end`, `via`, `hills`, `reuse` and `reverse`. Place values name the borough ("McCarren Park, Brooklyn").
- **Never quietly drop a field (rule 3).** `unsupported(c)` lists the Phase 3 fields the engine can't build yet:
  `end_place`, `via_places`, `hills` (when not neutral), `avoid_along`, `reuse_route_id` and `planned`. The CLI exits
  with code 6 and names them. The API (step 5) will turn them into a can't-do line or a question. Each later step
  removes its entry.

## Tests
- `api/tests/test_constraints_phase3.py` (21 tests) and the existing constraints tests, now 44 in all.
- The parse grader's field list is tested against `RunConstraints`, so the two can't drift apart.
- The CLI still builds routes end to end (11 Madison Ave, 3 mi, Training, 7:00).

## Open
- **"Along" avoids have no build step.** R07 and P23 parse to them, but steps 7–10 don't route around a street
  while still allowing crossings, so until a step does, those requests get a can't-do line from `unsupported`.
  One way to do it: a GraphHopper custom-model penalty on a thin area around the street, with crossings costing
  only a little. That needs a step in the plan.
