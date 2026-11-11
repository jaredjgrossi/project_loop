# 043: The app's features — feedback, install id, stored routes, run again, route type, favorites; street names

**Status:** accepted (2026-11-10). Asked for with the iPhone app's new screens ("I ran it", ratings, favorites,
history, profile, route type) and from Jared's phone testing, before merging PR #11. Contract changes are in
`docs/phase3/parse-contract-v1.md`.

## Decision
1. **Feedback: `POST /v1/routes/{id}/feedback`** — `{ran, ran_at, rating: good | not_for_me | null, reasons, note}`.
   - Reasons are keys: crowded, lights, water, safety, other.
   - It's written to Phase 2's `route_feedback`, migrated on first use:
     - new `install_id`, `verdict`, `reasons` and `updated_at` columns;
     - Phase 2's rule that every run carries a 1–5 rating is relaxed to "a rating needs a run";
     - a unique index on (route, install).
   - So a later post updates the same row: the runner can rate after "I ran it", or change their mind.
   - `generated_routes` gets the route's row (line, kind, label, score, the #1's stretches) from `saved_routes`, so
     feedback stays joined to what was shown.
2. **An anonymous install id: the `X-Loop-Install` header**, a random id the app makes once per install.
   - It's stored with each build's request in `saved_routes` and with feedback.
   - It's never sent to Claude and never stored with the request text or a location.
   - It groups one runner's ratings without an account, and becomes Phase 4's per-user key.
   - Required for feedback; optional elsewhere.
3. **Stored routes live for good.** `saved_routes` is never pruned (decision 030).
   - `GET /v1/routes/{id}` now also takes a route's own id (`r_xxxxxxxx.N`), and returns its build's `final`, with
     every route's full line.
4. **"Run again" is the same line, read for now:** `{route_id, mode: "exact"}` on `POST /v1/runs`.
   - No routing: the stored line is scored as it is, with this moment's clock for crowds, so the geometry can't
     change.
   - The stream is `parsed` (the stored request's chips), `final`, `done`.
   - "Rebuild for now" stays `reuse_route_id` (decision 038), which may route around a new closure.
5. **The route type from the app: a top-level `shape`** (`any | loop | out_and_back | one_way`).
   - It beats the words, with source `said` (span null: it isn't in the sentence).
   - `one_way` needs an end. With none named, the parse asks "Where do you want to end?" (`about: "end"`), and a
     typed place answers it.
   - `profile.usual_shape` takes the same values, with source `usual`.
6. **Favorites in `recent_routes`:** `saved: true`, the runner's own `name`, and `ran_count`.
   - "My usual" is the most run.
   - A renamed favorite is found by its name ("the Stuy loop").
   - Claude sees the name, the count and `saved`, never a line.
7. **Street names on their own.** Lookups already read "west 71st st", "W. 71st Street" and "71st and Columbus".
   The phone bug was elsewhere, and is now fixed:
   - The bug:
     - For "W 71st St" as the start of a run in "the park", the parser looked only for where the street meets
       that park.
     - From Broadway at W 79th St, "the park" is Riverside Park, which W 71st St doesn't reach. So the answer was
       "Couldn't find W 71st St".
   - The fix: if the street doesn't meet the park, take its point nearest the park, else nearest the runner,
     labeled listed.
   - **"Where on …?" for long streets:** a street over 2.5 km whose nearest point is over 800 m away asks, with up
     to four crossings about 400 m apart, nearest first. W 71st St (1.1 km) never asks.
8. **"The park" picks without a question when one clearly wins** (R13).
   - That's when only one runnable place fits the run, or the nearest is at most half as far as the next.
   - For a run that goes to the park from elsewhere, a place fits only within 45% of the run's length.
   - P20 ("start at the park, 3 mi" from Kips Bay) now starts at the East River Esplanade, 0.4 mi, against 1.2 mi
     for the next. It used to ask.

## Evals
- `evals/parse/cases/P51–P53`: "west 71st st", "W. 71st Street, 4 mi" and "71st and Columbus, 5k". The set is now
  54 cases.
- `evals/parse/test_app_requests.py` (live, Claude):
  - the route type beats the words;
  - one way without an end asks;
  - one way with an end doesn't;
  - a renamed favorite by name;
  - "my usual" is the most-run favorite.
- `evals/routes/test_app_features.py` (live):
  - a rating round-trip and a changed rating, one row per install;
  - "run again" returns the same line;
  - W 71st St with "the park" from Broadway at 79th (fails without the fix);
  - a long street far off asks where on it, and a short one doesn't.
- Unit tests in `api/tests/`:
  - `test_server.py`: feedback checks and errors, the install id stored, run again, the route type;
  - `test_parse.py`: one way, favorites, the park pick;
  - `test_engine.py`: run again keeps the line exactly.

## Checks
- 1,031 unit tests pass, and 1,033 with CI's no-database settings.
- Parse evals (prompt v7, three runs of the 54 cases): 54, 53 and 54 pass, so 53 pass all three. R07 once
  recorded 42nd St as an area, not "along". Claude's median latency was 1.36–1.67 s, at $0.00024 a parse.
- All 210 live place, route and app evals pass. One is skipped: the personal-runs eval, which needs the
  git-ignored run data.
