# Loop — NYC Run Builder

Loop turns a plain-English run request ("6 mi loop from Kips Bay, mostly waterfront, bathroom near mile 3") into real routes, scored with NYC data. Full plan: `docs/PROJECT_PLAN.md`.

## Non-negotiable product rules
1. **The LLM never generates geometry or numbers.** Claude only (a) parses requests into the `RunConstraints` schema and (b) explains routes using scored fields passed to it. All routing and scoring is deterministic code.
2. **Every amenity or fact carries a source and a trust label**: `verified`, `listed`, or `seasonal_or_closed`. Never show an amenity without one.
3. **Say when a limit can't be met.** Return the nearest alternative and how far off it is. Never quietly relax a limit.
4. If parsing fails validation, return a clarifying question. Don't guess.

## Stack
- Frontend: React + Vite + TypeScript, MapLibre GL, phone-first PWA (`/web`)
- Backend: FastAPI + Pydantic v2, Python 3.12 (`/api`)
- DB: Postgres 16 + PostGIS (SRID 4326 for storage; project to EPSG:2263, NY State Plane in feet, for distance and area math)
- Routing: self-hosted GraphHopper in Docker, NYC OSM extract, `foot` profile with custom models (`/routing`)
- LLM: Anthropic API with tool use; prompts live in `/api/prompts/`, versioned
- Analytics: PostHog

## Layout
```
/api        FastAPI app, scoring, Claude client
/web        React app
/routing    GraphHopper config + custom models
/etl        scripts that load NYC Open Data + OSM into PostGIS
/evals      parse + route eval suites
/docs       plan, discovery notes, decisions/
```

## Commands
- `docker compose up` (Postgres+PostGIS, GraphHopper, API)
- `pytest api/` (unit tests) · `pytest evals/` (eval suites)
- `cd web && npm run dev`

## Conventions
- Write tests first for anything geometric (distance, share-of-route, near-mile-X lookups).
- Log tokens and cost for every Claude call into the `llm_calls` table.
- Record each architecture choice as a short note in `docs/decisions/NNN-title.md`.
- Keep each phase shippable; don't start v2 (tours) work until asked.
- Personal run data (`apple_health_export/`, `data/`) is git-ignored and never committed. Trim the first and last 200 m of any real route before storing or rendering it (decision 011).
