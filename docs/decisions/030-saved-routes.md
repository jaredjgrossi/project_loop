# 030: saved_routes — every build stored, with no request text and no location

**Status:** accepted (2026-11-08). Phase 3, step 7 (the brief's step 6, "Minimal storage"). Builds on 029 (the API).

## Decision
- **One row per build** in `saved_routes` (`api/saved_routes.py`), in the local Postgres:
  - `route_id`: the build's id, `r_xxxxxxxx`. Its routes are `r_xxxxxxxx.N`.
  - `request`: what kind it was (`text`, `answer` or `constraints`), its `parse_id`, and the phone's clock and
    time zone.
  - `constraints`: the RunConstraints as built.
  - `final`: the final event's payload, as streamed.
- **What it never keeps:**
  - The raw request text, because rule R8 says health details are never saved to saved routes. The text stays only
    in `llm_calls`, for 30 days, without location (decision 025).
  - The phone's location, profile and recent routes. Those live on the phone and come with each request (the brief:
    don't keep request text alongside the runner's location).
- **What it does keep:** the route's own line, which starts where the runner starts. That is the product. It stays in
  this Postgres, never exported or committed. Rows aren't deleted for now.
- **The build is stored before `final` is sent**, so any route id the phone holds works, after a restart too. The
  insert takes a few milliseconds. Questions and builds the engine can't do yet store nothing.
- **`GET /v1/routes/{id}`** reads the server's memory (the last 50 builds), then `saved_routes`.
- **The table is created on first use, once per process**, as `llm_calls` is, so `make setup` isn't needed again.
- **Storing never breaks a build:** if Postgres is down, that's said once on stderr and the stream goes on.
- **`generated_routes`** (decision 014, one row per shown route, for feedback) is left as it is; nothing writes to it
  yet. When feedback comes to the app, a route the runner ran is named by its `r_xxxxxxxx.N` id.

## Tests
- `api/tests/test_saved_routes.py` (5): the stored request has no text, location or profile; a build loads back from
  a fresh store; saving twice keeps one row; a database that's down is reported, not raised. The Postgres tests skip
  when the database isn't up.
- `api/tests/test_server.py` (4 more, 31 in all): a build is served after a restart (a new app with the same
  store); the stored row has no text or location; answers and chip edits are stored with their kind; questions and
  blocked builds store nothing.
- **Live:** a 2 mi build on a test server; the server was restarted, and `GET /v1/routes/r_dd651e6b` returned it
  with its route ids and pool. The row is 24 kB in Postgres.
- All 839 unit tests pass.
