# Loop Phase 3: build brief (2026-11-05)
*Handoff for a fresh Claude Code session. Read this brief, `parse-contract-v1.md` and `parse-evals-v1.md`. Jared puts all three in `~/Developer/loop-design/phase3/` on his Mac, since Code can't open claude.ai. The first commit copies them into `docs/phase3/` in the repo.*

## Goal
A runner types a plain-English request on the iPhone and gets routes streamed back from the engine running on Jared's Mac. The parse comes first (chips, can't-do lines, or one question), then the routes. Phase 3 also adds what real requests asked for: ending somewhere else, running through named places, avoiding hills, reusing past routes, and planning a second run.

**First milestone:** the phone gets real routes from a typed request. Everything after builds on it.

## Before any code
1. Read the three docs. Check `main` is clean and up to date.
2. Answer these from the code and tell Jared:
   - Did the bike-lane rule land? This decides eval P25.
   - Map every field in `parse-evals-v1.md` to `api/constraints.py`. List the new fields Phase 3 adds and any name that differs.
   - Which Python and FastAPI versions you'd add. FastAPI isn't in `pyproject.toml` yet.
3. Propose a step plan with a commit list, and wait for Jared's approval.

## Repo rules
- `main` is the only long-lived branch. Work on a new branch from `main` in its own git worktree. Other Claude sessions use this repo at the same time, so never switch branches in the main checkout.
- One commit per step, each passing `make test` and its own evals. Open a PR to `main`; Jared merges.
- **Secrets:** the Claude API key and the Loop token go in `.env`, git-ignored. Nothing secret goes in the iPhone app or in git.
- **Privacy:** fixtures use public stand-ins (Kips Bay Library, Grand Army Plaza, Union Square), never a real home address. Personal runs stay in their git-ignored folder. Before every commit, search for addresses, coordinates and raw GPS. Don't log request text alongside the runner's location.
- Don't install anything big (Tailscale, a new database) without telling Jared first.

## Decisions already made (don't reopen)
| Topic | Decision |
|---|---|
| "Loop" (D1) | Plain "loop" means `shape=any`; "real loop" or "circle" means `loop` |
| Places (D2, D3) | Look up in an OSM places table built from our extract. One match: use it (listed). Several: ask. None: ask for an address. Claude never outputs coordinates |
| Default hours (D4) | No time means now; morning = usual time; lunch 12:00; after work 18:30; tonight 20:00 |
| Distance (D5) | 0.5–30 mi, the engine's existing bounds |
| Two runs (D6) | Build the soonest; return the other as `planned`, built for its day and saved |
| Start default | Today: current location. Later day: saved home, otherwise ask |
| Lights | "No lights" and "uninterrupted" mean `lights=waits` |
| Streets in avoids | Don't run along them; crossing is fine |
| In Phase 3 | `end_place` (A to B), `via_places` (through or along, not "the whole way"), `hills`, past-route reuse and reverse, `planned`, minimal storage |
| Claude call | Server-side only. Structured output via one tool call. The cheapest model that passes the evals wins, starting with Haiku 5.5 |
| Copy | Every string the runner sees comes from one template file. Claude writes none of it |
| Server | FastAPI on Jared's Mac. The phone reaches it over Tailscale (free Personal plan) |
| Streaming | Server-sent events on `POST /v1/runs`, shaped as the contract says |
| Scope | One Phase 3; the steps below are in order |

## Steps
Each step ends with its tests and evals passing, then a commit.

**1. Eval harness.** Turn `parse-evals-v1.md` into fixtures under `evals/parse/`: one file per case with context, text and expected output. Write the grader from its Grading section, plus the three contexts and the recent-routes fixture. Run it against a stub parser that fails everything, to prove the harness works. Done: `make eval-parse` prints a pass/fail table.

**2. Places table.** Build `places` in PostGIS from `routing/data/nyc.osm.pbf`:
- named nodes: stations, subway entrances, amenities, shops, tourism, leisure
- named areas as a point plus outline: parks (reuse `osm_parks`), squares
- named bridges (ways)
- street-crossing points, for intersections
- `station_flow` subway names

Keep source and load time on every row (decision 006). Write `lookup(name, near=None)`, returning 0, 1 or several matches. Done: unit tests for Penn Station, McCarren Park, Central Park Reservoir, Central Park South, "86th St" at Central Park (two), 1st Ave & E 23rd St, 42nd St, Hudson River Greenway, Prospect Park, and Hoboken (none). Propose the major-park list for "the park" (R13).

**3. Parser.** `api/parse.py`. One Claude call with a single extraction tool whose schema holds what the runner said, not `RunConstraints` itself. Deterministic code then:
- resolves places (step 2)
- applies rules R1–R18 from the evals doc
- builds `RunConstraints`, chips, can't-do lines, notes, or the one question, from templates in `api/copy.py`

Use prompt caching for the instructions. The API key comes from `.env`. Run the evals on Haiku 5.5 first, and try a larger model only if cases fail. Report the pass rate, cost per parse and median latency for each model tried. Done: every case passes except those marked for later steps (end, via, reuse, hills, planned), and the parsed result arrives in about 3 s median (target raised from 2 s by Jared, 2026-11-08; the app designs the wait).

**4. API and streaming.** Add FastAPI. Build `POST /v1/runs` as server-sent events, following the contract:
- the `text`, `answer` and `constraints` paths
- pending parses kept in memory for 15 minutes; after that the app resends the original request (Jared, 2026-11-08)
- the engine's `on_top3` callbacks bridged from worker threads into the event stream
- `GET /v1/routes/{id}` and `GET /v1/health`
- the Loop token check

Add a small command-line client that prints the events, for testing without the phone. Done: a typed request streams `parsed`, then `top3`, `provisional` and `final` from the command line, with the first route under about 3 s after send.

**5. Reach from the phone (Jared and the iPhone session).** Write Jared exact steps to install Tailscale on the Mac and the iPhone and run the server. Write `docs/phase3/ios-wiring.md` for the iPhone build session: the endpoint, the event shapes, how to read the stream on iOS, and a temporary debug text field until the UI chat designs the request screen. Code doesn't edit `ios/` in this session. Written: `docs/phase3/tailscale-steps.md` (Tailscale serve gives the Mac an HTTPS address on the tailnet, so iOS needs no ATS exception) and `docs/phase3/ios-wiring.md` (2026-11-08). **Milestone:** a typed request on Jared's phone draws a streamed route.

**5b. A shorter tool input (added by Jared, 2026-11-08).** Right after the phone milestone: let the model leave unsaid fields out of `record_request`, to cut output tokens and latency. Three eval runs; keep it only if accuracy holds (44 or more cases passing all three runs).

**6. Minimal storage.** A `saved_routes` table in Postgres: `route_id`, request, constraints and the final payload. The server stores every build. The phone's planned, saved and past lists stay on the phone and go out as `recent_routes` (that list is the iPhone session's job). Done: `GET /v1/routes/{id}` returns a stored route after a server restart. Built (decision 030): the stored request keeps its kind, parse id and clock, never the raw text (R8) or the phone's location.

**7. A to B.** A generator for start → end that still reaches water, parks and corridors. Check the requested distance against the shortest way. If it's shorter, the engine asks with `from: "engine"` ("The shortest way is 4.2 mi. Make it 4.2?"). Distance is optional when an end is given. Done: R01 end to end, plus new route evals (Kips Bay → McCarren Park at 8 mi; an end that's too far for the distance asks). Built (decision 032): `api/a_to_b.py`; route evals in `evals/routes/test_a_to_b.py`.

**8. Via.** Route through or along `via_places`, reusing the corridor-anchored generators. "The whole way" stays a can't-do line. If a via point is too far for the distance, the engine asks. Done: R02 (after its answer), R03 (the engine asks), R09 (after its answer), P49. Built (decision 034): `api/via.py`; route evals in `evals/routes/test_via.py`. Around or through (added by Jared, 2026-11-09; decision 035): a via is passed or lapped. "Around", "loop of" and "lap of" run a full lap; four known running loops (`etl/curated/running_loops.json`) mean their lap when named on their own; the lap counts toward the distance. R02 becomes a full Reservoir lap between 86th St (west) and Central Park South; P50 ("Loop of Prospect Park from Grand Army Plaza") joins the parse and route evals.

**8b. "Along" avoids (added by Jared, 2026-11-06).** Make running along a named street, or a named stretch such as "1st Ave, E 26th–E 34th St", costly in the router, while crossings stay cheap. Done: R07 and P23 work end to end, with a route eval for each. Built (decision 036): `api/along.py`; route evals in `evals/routes/test_along.py`.

**9. Hills.** A `hills` preference scored from the elevation every 0.1 mi (measured), with a provisional weight. Done: P33, and R11 after its answer; a route eval where "flat" changes #1 on a hilly start. Built (decision 037): `api/hills.py`; labeled `estimate`, like decision 014's climb (same elevation tiles); route evals in `evals/routes/test_hills.py` (Fort Tryon Park is the hilly start).

**10. Past routes and planned runs.** `reuse_route_id` (rebuild the stored route's request for now), `reverse`, "longer" (ask how much), and `planned` (D6: build the second run for its day, store it, send it after `final`). A part of a past route ("skip the ferry part") is matched in code against the `pulse_sources` ferry landings along the reused route, not by the model (Jared, 2026-11-08). Done: H01–H05 and P45.

## Out of scope
The request-screen design (the UI chat), accounts and sync, cloud hosting, the watch, workout-segment routes, lighting and safety, "the whole way" routing, soft avoids, minutes instead of miles, commercial place search, and changing ranking weights.

## Done when
- All 51 parse evals pass on the chosen model, and the earlier evals and unit tests still pass.
- On Jared's phone over Tailscale, a typed request shows the parse in about 3 s and the first route under about 3 s after it.
- Questions from the parser, places and the engine all reach the phone the same way, and answering one continues the build.
- No API key in the app or in git. Claude never receives coordinates.
- Jared's review: do the chips read right, and do the questions feel necessary?

## Open questions Code raises, doesn't decide
- The bike-lane rule's status (P25).
- Same address or crossing in several boroughs: always ask (decision 005), or use the one near the runner? Today it's ask.
- The major-park list and radius for "the park".
- How fuzzy place matching should be before it asks.
- How long a pending question stays open. Decided: 15 minutes, then the app resends the original request (Jared, 2026-11-08).
- If Haiku 5.5 fails some cases, whether a larger model is worth its cost.
