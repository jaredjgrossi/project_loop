# NYC Run Builder — Project Plan
*Working name: **Loop**. Rename whenever.*

*The original plan (2026-10-30). Phases 0–3 are built; the frontend became the iPhone app in `ios/` rather than the web app below, and deploy, auth and analytics are not built. The current state is in the [README](../README.md) and the reasons for each choice in [`decisions/`](decisions/).*

## 1. The pitch
**Tell it the run you want. It builds that run, using real NYC data.**

> "6 miles from Kips Bay, mostly waterfront or park, as few stoplights as possible, bathroom around mile 3."

Loop turns that request into a route you can run. Every claim it makes about the route (how much is in a park, how many stoplights, where the water stops are) comes from real data and links back to its source. Version 2 adds a tour layer: the stories of the buildings and landmarks you pass.

**Target user:** NYC runners who are tired of running the same 3 routes, don't want to build routes by hand in Strava or on a map, and care about things map apps ignore: stoplights, bathrooms, water and scenery.

**Carry over from the handle-time engine.** That project's best instinct was refusing to make up numbers ("honest lower bounds," confidence tiers, Q&A grounded in the data). Make that Loop's identity too:
- **Claude never draws routes.** Claude turns the request into structured limits and explains the result. Routing and scoring are deterministic code.
- **Every amenity shows how much to trust it.** For example: *Verified* (official dataset, currently in season or open), *Listed* (in a dataset, but hours or status unknown), *Seasonal or closed now*.
- **When it can't meet a limit, it says so.** For example: "I couldn't find a bathroom near mile 3. The closest is at mile 3.8."

---

## 2. Step 0: Discovery (before writing code, about 1 week)
This is the part that makes the project read as product work. Talk to **5–8 NYC runners**: run club members, coworkers, friends. Ask:
1. Walk me through how you picked your last 3 routes.
2. When did a run go badly because of the route? (stoplights, crowds, no bathroom, bad surface)
3. What do you use today: Strava routes, Google Maps, memory, a club leader?
4. If a tool built routes for you, what would make you trust it?
5. Would you run a route someone else rated well?

**Output:** a one-page summary of the top 3 pain points and which ones v1 targets. Save the notes in the repo under `/docs/discovery/`, since they're good interview material.

---

## 3. v1 scope
**In:**
- Start point by address or "use my location"
- Loop or out-and-back, with a target distance (within ±5%). *GraphHopper's round trips only approximate the distance, so this needs a retry-and-pick loop (Phase 2; see §11).*
- Preferences: park or waterfront share, fewer street crossings, bathroom or water near mile X
- 3 route options, each with a score card: distance, % park/waterfront, estimated crossings and amenity stops (with trust labels)
- Map view and GPX export (so routes load into a watch or Strava)
- "I ran it" plus a 1–5 rating, which is the core feedback signal
- Plain-English input through Claude, plus a manual form fallback

**Out (for now):** accounts beyond simple sign-in, social features, live tracking, elevation scoring (NYC is mostly flat, so this can wait for v1.5), building stories (v2).

**Product idea, not built: "routes you already run."** A runner uploads their own GPX history, or connects Strava or Apple Health. Loop map-matches it, trims the ends for privacy, and learns which corridors they actually use. Those corridors become a "matches routes you run" dimension that the runner can turn up ("a good variation on what I already run") or reverse ("show me new ground"). It works today for one runner from a local Apple Health export (decision 011). For other runners it needs consent, storage and deletion designed first.

---

## 4. Success metrics
| Metric | Why it matters | v1 target |
|---|---|---|
| Routes generated → "I ran it" | Is the output usable? | ≥ 25% |
| Average route rating | Is the quality real? | ≥ 4.0 |
| Weekly returning users | Is it a habit or a novelty? | 10+ by week 12 |
| Requests parsed correctly (eval set) | Is Claude reliable? | ≥ 95% |
| Claude cost per route | Unit economics, your home turf | Track it; keep under $0.01 |

Use PostHog (free tier) for event tracking from day one.

---

## 5. Architecture

```
React (Vite) PWA + MapLibre GL
        │
FastAPI ─────────────── Claude API (tool use)
  │  │                    parse_request → constraints JSON
  │  │                    explain_routes → plain-English summary
  │  └── GraphHopper (Docker, NYC OSM extract, foot profile + custom models)
  │         round-trip and point-to-point candidate routes
  └── Postgres + PostGIS
        parks, waterfront, fountains, restrooms, crossings, saved routes, ratings
```

**How a request flows:**
1. **Parse:** Claude turns the text into a strict constraints object (`distance_mi`, `shape`, `prefer_green`, `max_crossings`, `amenity_at_mile`, …). Validate it with Pydantic. If validation fails, ask the user to clarify; never guess.
2. **Generate:** call GraphHopper about 10–20 times with different seeds and headings, plus a custom model that weights park and waterfront paths more heavily. Rescale the requested distance by requested/actual and retry, keep the candidate closest to the target, and report the miss if none lands within ±5% (a single `round_trip` call can be 24% short or 2.5× long; see §11). The custom model must keep ferries excluded (the stock `foot` profile routes the Staten Island Ferry).
3. **Score:** use PostGIS to measure how much of each route is park or waterfront, count crossings (OSM traffic signals and crossing points), and find amenities near the target mile with their trust labels.
4. **Rank and explain:** return the top 3. Claude writes the summary using only the scored numbers, never its own.

**Stack decisions:**
- **Postgres + PostGIS** instead of SQLite. This is the main new skill on the backend.
- **GraphHopper**, self-hosted in Docker. It's open source, supports custom routing models in JSON and has round-trip routing. The NYC extract is small, so it runs on a cheap instance.
- **MapLibre GL** for maps (free; no Mapbox bill).
- **Hosting:** frontend on Vercel, API and GraphHopper on Fly.io or Render, Postgres on Neon or Supabase (both support PostGIS).
- **Auth:** Supabase Auth or Clerk. Keep it minimal.

---

## 6. Data sources
| Data | Source | Notes |
|---|---|---|
| Streets, paths, crossings, signals | OpenStreetMap (Geofabrik NY extract) | Routing graph and crossing counts |
| Parks | NYC Open Data: Parks Properties (`enfh-gkve`) | Polygons for scoring park share. Its `waterfront` flag is a scoring input, but **Hudson River Park and Governors Island are not in it**, so waterfront share also needs OSM. Includes plazas and gardens, so weight by `typecategory` |
| Waterfront | OSM coastline and greenways; NYC waterfront access datasets | Hudson River Greenway, East River Esplanade, etc. Required, not optional: Parks Properties misses the Hudson |
| Drinking fountains | NYC Open Data: NYC Parks Drinking Fountains (`qnv7-p7a2`) | Outdoor park fountains with GPS. **The data is stale (last updated 2024-07-15), every row says "Active", and there is no seasonal field.** Fountains can be `listed` at best, never `verified`; any seasonal label comes from a rule we write, not from the data |
| Restrooms | NYC Open Data: Public Restrooms (`i7jb-7jku`) | Citywide (Parks, DOT, libraries, POPS). **Labels come from `status` + `open`** (Year Round / Seasonal / Future), with free-text `hours_of_operation` checked against the run time. **Most park restrooms are open about 8am–4pm**, so a 6:30am run needs this flagged. Mapping in decisions/004 |
| *(v2)* Landmarks | NYC Open Data: LPC Individual Landmarks and Historic Districts | Tour layer |
| *(v2)* Building facts | NYC PLUTO | Year built, etc. |

The restroom hours problem is a real product insight: plenty of NYC runners go before 8am. Fixing it is exactly the "a map app doesn't know this, Loop does" moment.

---

## 7. Evals
- **Parse evals:** 40 hand-written requests (easy, ambiguous, adversarial) paired with the expected constraints JSON. Run them on every prompt change.
- **Route evals:** for 20 fixed requests, check that distance is within tolerance, that limits are met or the miss is reported, and that no amenity appears without a source. Use pytest so it runs in CI.
- **Cost log:** tokens and cost per request, stored per route.

This is the section product and AI interviewers will ask about.

---

## 8. Build plan (part-time pace)
| Phase | Weeks | Ship |
|---|---|---|
| 0. Discovery | 1 | 5–8 runner interviews, pain-point summary, final v1 scope |
| 1. Data foundation | 2 | Docker Compose: Postgres+PostGIS and GraphHopper on the NYC extract. Load parks, fountains and restrooms. A script returns one loop from an address |
| 2. Scoring | 3 | **Loop shape first** (turns per mile, straight-run share, retraced share, width, compactness; reported for every loop), then grid-aligned rectangle candidates with a distance rescale loop (decision 008). Then, per decision 009, rank routes against the runner's preferences (`RunConstraints`: lights, crowds, scenery, surface, turns, "matches routes you run", Training vs. Exploring preset).
- Done: the combined ranking with no-go zones, out-and-back as a route type (010), and calibration against the reviewer's map-matched real runs with one set of definitions, which added park/water, signals and the runner prior (011).
- Done: park, waterfront and corridor generators from OSM for every runner, a verified corridor catalog, lollipop as a route type, and round trips everywhere (012).
- Done: UI-ready outputs (streaming with timing, the candidate pool, per-segment GeoJSON with stretch names, elevation, start hour, the feedback schema), turnarounds by walking distance, and cleaned corridor names (014).
- Done: the lights preference on the router side (signal penalty for runners who wait; expected-wait estimate with zig-zag credit) (015).
- Done: crowds as an estimate from subway volume and DOT count windows, with the start date and hour; not scored on paths and outside count hours (016).
- Done: known closures as a hard rule (the corridor catalog's East Midtown missing link), with runner reports a reviewer confirms (017).
- Next: roadway share and the bike-lane rule.
- Every value is labeled measured, estimate or not scored, and weights stay provisional until calibrated. Amenities near mile X annotate the top 3 after ranking.
- Every change is checked on the fixed review starts and against real runs. Every rejected route becomes a failing eval |
| 3. API + Claude | 4–5 | FastAPI endpoints, Claude parse step into `RunConstraints` (tool use with strict schema; the parsed request is shown to the runner before routing), explain step, parse eval set and cost logging |
| 4. Frontend | 6–7 | Phone-first PWA: request box, map with 3 options, score cards, GPX export, "I ran it" and rating |
| 5. Ship | 8 | Deploy, auth, PostHog, README with architecture and eval results, 90-second demo video |
| 6. Users | 9–12 | Put it in front of 2–3 run clubs and the discovery runners. Weekly changelog of fixes based on feedback |
| v2. Tours | 13+ | Landmark and building-story layer along routes; "scenic" preference; optional audio |

Each phase ends with something you can run. If a week slips, cut scope, not quality.

---

## 9. Ways to use Claude Code well (skills worth building)
- Start every session from the repo's `CLAUDE.md` (starter version included).
- Use plan mode for each phase before code gets written.
- Ask it to write tests first for scoring logic. Geometry bugs are subtle.
- Keep a `/docs/decisions/` folder with short notes on each architecture choice and why. This is great interview material and keeps Claude Code consistent across sessions.

---

## 10. Risks (see §11 for what Phase 1 changed)
| Risk | Mitigation |
|---|---|
| Route quality is mediocre, so nobody comes back | Phase 2 is the core work; test-run your own routes weekly. Ratings drive custom-model tuning |
| Amenity data is stale or seasonal | Trust labels and "report a problem" button; this becomes a crowdsourced data loop later |
| Scope creep into v2 too early | v2 is locked until 10+ weekly returning users |

---

## 11. Findings (what the real data and tools changed)
Checked 2026-10-30. Details and reasoning are in `docs/decisions/`.

| Finding | Effect on the plan |
|---|---|
| Fountain data is stale (2024-07-15), all rows "Active", no season field | Fountains are `listed` at best; never `verified`. Seasonal labels need a rule we define (004) |
| Restroom `status` + `open` + `hours_of_operation` are usable and current | Restroom labels derive from those fields (004) |
| Parks `waterfront` flag exists but is inconsistent, and Hudson River Park / Governors Island are missing | Flag is a scoring input only; waterfront share must also use OSM geometry (004) |
| `round_trip` distance is approximate (4 mi request: 3.0 to 10.7 mi across seeds; seed 0 was -24%) | Hitting ±5% needs a retry-and-pick loop in Phase 2 (007) |
| Stock `foot` profile routes ferries | Custom model excludes them; keep that in every Loop model (003) |
| GeoSearch has no address layer and its confidence is uninformative | Geocoder verifies number/street, refuses ambiguity and place names (005) |
| 14 park polygons are self-intersecting | Repaired and flagged at load (006) |
| Official PostGIS image is Intel-only | Use the community multi-arch image on Apple Silicon (001) |
| `round_trip` loops zigzag, ribbon, or retrace (median compactness 0.15, 5.5 turns per mile); grid rectangles did far better in a prototype | Shape metrics are scored for every loop; candidates are generated as grid-aligned rectangles (008) |
| The reviewer's real runs (197 map-matched, last 12 months): 66% out-and-back, median 76% retraced, 3.4 turns per mile, 48% in parks and 62% by the water; generated routes reached parks and water almost never | Out-and-back is a route type (010); retracing and turns stay provisional; park, water and corridor generators come next (011) |
| Decision 008's turn definition counted GPS jitter and short spurs as turns (5.8 per mile on matched runs, against 3.2 for the same runs as raw GPS) | Spurs are removed and the line simplified at 20 m before counting turns, for real and generated routes alike (011) |
