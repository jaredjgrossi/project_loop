# Phase 3 contract: request in, parse and routes out — v1
*Status: agreed at a high level (2026-11-05). This is what the iPhone app sends, and what the server streams back, before and during a build. The UI chat designs how chips, the question, can't-do lines, notes and planned runs look. This doc only fixes the data. Evals: `phase3/parse-evals-v1.md`. Build: `phase3/build-brief-v1.md`.*

## The flow
1. The runner types a request and the app sends it to `POST /v1/runs`.
2. The server streams back server-sent events:
   1. `parsed`: chips, can't-do lines, notes, and possibly one question. Target: under about 2 s.
   2. If `parsed.question` is set, the stream ends there. The app shows the question. The answer goes back as a new `POST /v1/runs` with `answer`, and the stream picks up from step 2.1 with the merged request.
   3. `top3` (repeats as the leader changes; first route target under about 1 s after `parsed`), then `provisional`, then `final`.
   4. A question can also come from the engine after `parsed` (for example "The greenway is far for 3 mi"). It arrives as a `question` event, and the stream ends.
   5. `planned`: only if the request had two runs (D6). It's sent after `final`.
   6. `done`, or `error`.
3. Editing a chip resends `constraints`, not text. That skips Claude and goes straight to routing.

## Request: `POST /v1/runs`
Exactly one of `text`, `answer` or `constraints`.
```json
{
  "v": 1,
  "text": "Chill run on the west side highway, 3 easy miles",
  "answer": {"parse_id": "p_8f2c", "question_id": "q_1", "option_id": "a", "text": null},
  "constraints": { "...": "RunConstraints, from an earlier parsed event, with edits" },
  "client": {
    "now": "2026-11-03T06:40:00-05:00",
    "tz": "America/New_York",
    "location": {"lat": 40.7438, "lon": -73.9799, "accuracy_m": 15}
  },
  "profile": {
    "usual_distance_mi": 3.1,
    "usual_time": "07:00",
    "saved_places": [{"id": "home", "label": "Home", "lat": 40.7438, "lon": -73.9799}]
  },
  "recent_routes": [
    {"id": "rt_a", "date": "2026-10-27", "name": "East River esplanade out-and-back", "distance_mi": 3.0, "times_run": 5}
  ]
}
```
- `location` is null when location is off.
- `profile` and `recent_routes` live on the phone (minimal storage, no accounts) and are sent with every request.
- **Privacy:** Claude receives the text, the time, saved-place labels and recent-route names. Coordinates never go to Claude; the server resolves them.
- Auth: a Loop token in a request header. The Claude API key never leaves the server.

## Event: `parsed`
```json
{
  "event": "parsed",
  "v": 1,
  "parse_id": "p_8f2c",
  "chips": [
    {"id": "c_start", "field": "start", "text": "86th St at the park", "source": "said", "editable": true,
     "place": null},
    {"id": "c_via", "field": "via", "text": "The Reservoir", "source": "said", "editable": true,
     "place": {"name": "Central Park Reservoir", "lat": 40.7829, "lon": -73.9654, "trust": "listed", "from": "OpenStreetMap"}},
    {"id": "c_end", "field": "end", "text": "Central Park South", "source": "said", "editable": true, "place": {"...": "..."}},
    {"id": "c_time", "field": "time", "text": "Now", "source": "default", "editable": true}
  ],
  "question": {
    "id": "q_1", "about": "start", "from": "places",
    "text": "Which 86th St?",
    "options": [{"id": "a", "text": "East side (5th Ave)"}, {"id": "b", "text": "West side (Central Park West)"}],
    "allow_text": true
  },
  "cant": [],
  "notes": [],
  "constraints": { "...": "the RunConstraints this parse produced, for chip edits" }
}
```

### Chips
- One chip per thing the runner said, plus defaults that matter: start, end, via, distance, time, shape, mode, then preferences, avoids, amenities, and reuse and reverse. Code sets the order.
- `field` is one of: `start`, `end`, `via`, `distance`, `time`, `shape`, `mode`, `lights`, `crowds`, `scenery`, `surface`, `turns`, `familiar`, `hills`, `avoid`, `amenity`, `reuse`, `reverse`. A chip can repeat for lists (`via`, `avoid`, `amenity`).
- `source` is one of: `said`, `preset`, `default`, `usual`. These are request words, not the five trust words (measured, estimate, listed, verified, not scored), which only appear on data such as `place.trust`.
- `text` is short and plain ("5 mi", "Avoid crowds", "End: McCarren Park"). It always comes from templates.

### Question
- At most one per response.
- `about` is one of: `distance`, `start`, `end`, `via`, `time`, `reuse`, `amount`.
- `from` is one of: `parser`, `places`, `engine`.
- `options`: 0–4 tap answers. `allow_text`: whether typing is offered.
- While a question is open, no routes stream.

### Can't-do lines and notes
- `cant`: `{"id", "gap", "text"}`, for example `{"id": "k_1", "gap": "G9", "text": "Can't plan around street lighting yet"}`.
- `notes`: `{"id", "key", "text", "trust"}`, for example `{"key": "fountains_seasonal", "text": "Fountains may be off for the season", "trust": "listed"}`.
- Evals match on `gap` and `key`, never on wording, so the UI chat can rewrite the copy freely.

## Events: `top3`, `provisional`, `final`
These are the engine's three stream events (decision 024 and the streaming notes in the UI decisions log), each carrying the route payload the iPhone slice already reads from `kips3-ui.json`, plus:
```json
{"event": "top3", "route_id": "r_51d0", "elapsed_s": 0.8, "provisional": false, "routes": ["... same shape as the fixture file ..."]}
```
- `route_id` identifies the stored result (`GET /v1/routes/{id}`).
- `final` also carries `pool_size` ("Best of N").

## Event: `question` (engine)
Same shape as `parsed.question`, with `from: "engine"` and its own `parse_id`. The stream ends after it.

## Event: `planned`
```json
{"event": "planned", "parse_id": "p_9a11", "route_id": "r_77c2", "date": "2026-11-07", "chips": ["..."], "summary": {"distance_mi": 10.0, "start_time": "07:00"}}
```
The app saves it to the planned list. Opening it on the day calls `POST /v1/runs` with its `constraints`, and the app keeps the old route if the new one isn't better.

## Events: `done` and `error`
- `done`: `{"event": "done"}`.
- `error`: `{"event": "error", "code": "engine_unavailable" | "parse_failed" | "bad_request", "text": "..."}`. The text comes from templates.

## Other endpoints
- `GET /v1/routes/{id}`: a stored result, the same payload as `final`.
- `GET /v1/health`: the server is up and the engine is ready.
- Feedback endpoints come later. The feedback tables from Phase 2 already exist.

## Copy
Every string the runner sees (chip text, questions, can't-do lines, notes, errors) lives in one template file on the server. The UI chat owns the wording; Code owns the keys. Claude only fills in place names and route names.

## Versioning
Every request and event carries `"v": 1`. A breaking change bumps the version, and the server accepts both for one release.
