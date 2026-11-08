# 029: The API — server-sent events, answers without Claude, a 15-minute pending store

**Status:** accepted (2026-11-08). Phase 3, step 5. Builds on 018 (streaming the top 3), 025 (parse on the server),
027 (RunConstraints) and 028 (the parser). Contract: `docs/phase3/parse-contract-v1.md`.

## Decision
- **FastAPI 0.162 with its own SSE support** (`fastapi.sse.EventSourceResponse`), run by uvicorn (`make serve`). No
  sse-starlette: FastAPI now ships SSE, with keep-alive comments. Both packages are small; nothing else was added.
- **`POST /v1/runs`** (`api/server.py`) takes exactly one of `text`, `answer` or `constraints`:
  - **text:** one Claude call (decision 028), then the rules. The stream sends `parsed`, then `top3` as the leader
    changes, `provisional`, `final`, and `done`.
  - **answer:** resumes the pending parse with what the answer settles, and runs the rules again on the same
    extraction. No second Claude call: the parse takes about 0.1 s.
  - **constraints** (a chip edit): skips Claude. Chips and notes are rebuilt from the constraints and their
    sources; with no edit, they come back identical to the parse's (tested on eight cases).
- **Answers are settled in code.** Each question carries a private map, kept on the server, from each option to
  what it settles: a place match, a borough, a distance, a recent route, or "+N mi". The map also says how typed text
  is read: a distance ("5", "about 6 mi", "8k"), a place name or address, a borough, or a recent route's name. Text
  that code can't read brings the same question back (rule 4). Answers build up across questions: a start, then a
  distance.
- **Pending questions are kept in memory for 15 minutes** (Jared, 2026-11-08), and each is used once. After that,
  or after a restart, the answer gets `error: expired`, and the app resends the original request. They are never
  written to disk or logged, because they hold the runner's location.
- **The engine** (`api/engine.py`) does the same build as the CLI. `make_loop.route_file` is now shared, so `final`'s
  `route` is the fixture's `route` exactly. The generator's `on_top3` runs on worker threads; the server passes
  each event to the stream through `loop.call_soon_threadsafe` and an asyncio queue. A build finishes, and its route
  is kept, even if the phone disconnects.
- **What the engine can't build yet is said, never dropped** (rule 3):
  - End places, via places, "along" avoids and past routes build nothing. `parsed` carries a `gap: "later"` line,
    then `done`.
  - Hills and a planned second run still build the first run, with a line.
  - An avoid that isn't on the no-go list gets an `avoid_unknown` line.
  - A distance miss gets a note in `final`, with the nearest route and how far off it is. No route at all gets a
    note too.
  - Each later step removes its line.
- **Auth:** `Authorization: Bearer <LOOP_TOKEN>` on everything but `/v1/health`. The token is compared in
  constant time, and the server won't start without it. A bad token is HTTP 401. Every other problem is an `error`
  event (`bad_request`, `parse_failed`, `engine_unavailable`, `expired`), so the app has one way to read failures.
  Request text is capped at 500 characters.
- **`GET /v1/routes/{id}`** returns the `final` payload, from memory (the last 50) until step 7 stores routes in
  Postgres.
- **`GET /v1/health`** is open, and says only true or false for the engine, the database and the parser key.
- **`done` ends every clean stream**, including one that ends with a question.
- **Copy:** the new can't-do lines, notes and the `expired` error are in `api/copy.py`. The UI chat owns the
  wording.

## Gotcha
FastAPI runs an SSE endpoint in its own task once the response has started. Reading the request body from inside
that task waits forever, so the body is read in a dependency, before the stream starts.

## Numbers (live, Kips Bay Library stand-in, 2026-11-08)
| Request | `parsed` after send | First route after `parsed` | `final` after send |
|---|---|---|---|
| "3 easy miles, mostly by the water, I wait at lights" (first after startup) | 4.46 s | 2.95 s | 14.5 s |
| same, warm | 2.88 s | about 0.3 s | 9.3 s |
| "5 mi loop, avoid crowds", warm | 3.14 s | about 0.4 s | 18.2 s |
| "long run today", then answer "8 mi" | 3.00 s (question) | answer parsed in 0.08 s | 28.8 s |

- When warm, the first route arrives 0.3–0.6 s after `parsed`, inside the contract's 1 s target. Counted from
  send, it arrives at 3.2–3.6 s, just over the brief's "about 3 s", because the parse alone is about 3 s.
- The first request after a start is slow. The scoring processes are still warming, and the first Claude call
  writes the prompt cache.
- `final` takes 9–29 s, as the engine does today (decision 018). The app draws routes from `top3` long before that.
- `final` for 8 mi is 194 KB.
- Five Claude calls in all, $0.0024, logged in `llm_calls` without location.

## Tests
- `api/tests/test_server.py` (27): the token, event order on every path, the question and answer flow, expiry,
  bad requests, chip edits, can't-do lines, the engine down, and events sent from other threads.
- `api/tests/test_answers.py` (32): options and typed answers for distance, place, park, side of the park, borough,
  typo and longer; answers that build up; the chip round trip.
- `api/tests/test_engine.py` (7) and `api/tests/test_ask.py` (3).
- All 828 unit tests pass.

## Later
- Step 5b (Jared): let the model omit unsaid fields, three eval runs, kept only at 44 or more cases passing all
  three.
- Questions from the engine (`from: "engine"`) arrive with step 7, and `planned` with step 10.
- A chip edit doesn't carry the parse's can't-do lines (lighting, bike lanes) back. They come from the words, which
  the constraints don't hold.
