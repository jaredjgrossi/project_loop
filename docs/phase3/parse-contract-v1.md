# Phase 3 contract: request in, parse and routes out — v1
*Status: agreed at a high level (2026-11-05). This is what the iPhone app sends, and what the server streams back, before and during a build. The UI chat designs how chips, the question, can't-do lines, notes and planned runs look. This doc only fixes the data. Evals: `phase3/parse-evals-v1.md`. Build: `phase3/build-brief-v1.md`.*

## The flow
1. The runner types a request and the app sends it to `POST /v1/runs`.
2. The server streams back server-sent events:
   1. `parsed`: chips, can't-do lines, notes, and possibly one question. Target: about 3 s (raised from 2 s, 2026-11-08).
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
  "reach_m": 5070,
  "constraints": { "...": "the RunConstraints this parse produced, for chip edits" }
}
```

### `reach_m` (step 7b)
How far from the start the run can get, in meters, to 10 m: half the longest the run may be (the distance plus its tolerance), since a loop or an out-and-back has to turn back by then. Null when there's no distance yet, or when the run ends somewhere else (for now). For the map while routes build.

### Chips
- One chip per thing the runner said, plus defaults that matter: start, end, via, distance, time, shape, mode, then preferences, avoids, amenities, and reuse and reverse. Code sets the order.
- `field` is one of: `start`, `end`, `via`, `distance`, `time`, `shape`, `mode`, `lights`, `crowds`, `scenery`, `surface`, `turns`, `familiar`, `hills`, `avoid`, `amenity`, `reuse`, `reverse`. A chip can repeat for lists (`via`, `avoid`, `amenity`).
- `source` is one of: `said`, `preset`, `default`, `usual`. These are request words, not the five trust words (measured, estimate, listed, verified, not scored), which only appear on data such as `place.trust`.
- `text` is short and plain ("5 mi", "Avoid crowds", "End: McCarren Park"). It always comes from templates.
- `span` (2026-11-09, for the request screen: the runner's sentence is the header and the understood words light up): `{"text", "start", "end"}`, the runner's exact words behind the chip and where they are in the request `text`. Positions count Unicode code points (Swift: `text.unicodeScalars`), start inclusive, end exclusive; `text` is always the request's own characters at those positions. Claude quotes the words; code finds them and never guesses: words that aren't in the request give `span: null`. `null` for `preset`, `default` and `usual` values. One phrase may feed two chips, so spans can overlap. A chip code set from another one's words (park scenery from "a few miles in the park") shares that chip's span. Example: `{"id": "c_distance", "field": "distance", "text": "8 mi", "source": "said", "editable": true, "span": {"text": "8 miles", "start": 19, "end": 26}}`.
- Source words (`source`) stay in the chip data; the app shows them only in the chip editor.
- `constraints.spans` carries the same spans by chip id, so a chip edit (which sends `constraints`, not text) keeps the other chips' spans. When the runner edits a chip, the app drops that chip's entry from `constraints.spans` (and from `constraints.sources`): an edited value is said, but not in the sentence. Spans are never stored with a build (R8).

### Question
- At most one per response.
- `about` is one of: `distance`, `start`, `end`, `via`, `time`, `reuse`, `amount`.
- `from` is one of: `parser`, `places`, `engine`.
- `options`: 0–4 tap answers. `allow_text`: whether typing is offered.
- `chip_id` (2026-11-09): the chip the question is about, so the app can mark its words in the sentence; null when the runner said nothing about it ("How far?" after "what do you suggest"). When nothing was built for it yet ("Which 86th St?"), the event carries a chip for it made from the runner's own words, with its span.
- While a question is open, no routes stream.

### Can't-do lines and notes
- `cant`: `{"id", "gap", "text"}`, for example `{"id": "k_1", "gap": "G9", "text": "Can't plan around street lighting yet"}`.
- `notes`: `{"id", "key", "text", "trust"}`, for example `{"key": "fountains_seasonal", "text": "Fountains may be off for the season", "trust": "listed"}`.
- Evals match on `gap` and `key`, never on wording, so the UI chat can rewrite the copy freely.

## Event: `candidates` (step 7b)
Light outlines of the routes the engine is trying, one event per route that passes the rules, from right after `parsed` until `final`. For drawing the search, never for measuring.
```json
{"event": "candidates", "v": 1, "route_id": "r_51d0", "elapsed_s": 0.42,
 "candidates": [{"id": "r_51d0.7", "kind": "out_and_back", "points": [[-73.97994, 40.74384], "..."]}]}
```
- `points`: `[lon, lat]`, at most 40 (Douglas-Peucker with the smallest tolerance that fits, so corners and ends stay), rounded to about 1 m. 35 points at the median.
- `id` is the same id the route has if it reaches `top3`.
- About 1 KB an event; 50–100 events a build (53–89 KB in all, measured 2026-11-08). `candidates` is a list so events can be batched later.

## Events: `top3`, `provisional`, `final`
These are the engine's three stream events (decision 024 and the streaming notes in the UI decisions log), each carrying the route payload the iPhone slice already reads from `kips3-ui.json`, plus:
```json
{"event": "top3", "route_id": "r_51d0", "elapsed_s": 0.8, "provisional": false, "routes": ["... same shape as the fixture file ..."]}
```
- `route_id` identifies the stored result (`GET /v1/routes/{id}`).
- `final` also carries `pool_size` ("Best of N").

## Event: `question` (engine)
Same shape as `parsed.question`, with `from: "engine"` and its own `parse_id`. The stream ends after it (then `done`). Built in step 8: when a run ends somewhere else and the distance is shorter than the shortest way there, beyond the tolerance, the engine asks before anything streams but `parsed`:
```json
{"event": "question", "v": 1, "parse_id": "p_9b21", "id": "q_1", "about": "distance", "from": "engine",
 "text": "The shortest way there is 4.5 mi. Make it 4.5 mi?", "options": [{"id": "a", "text": "4.5 mi"}], "allow_text": true}
```
Step 9 adds the same question for via places: "Going through Hudson River Greenway takes at least 4.3 mi. Make it 4.3 mi?" when the shortest way through them (and back, or on to the end) is longer than the distance. Answer it as any question, with this event's `parse_id`. The offer is the shortest way rounded up to 0.1 mi; a typed distance works too. The answer is a said distance; Claude isn't called again.

## Event: `planned`
```json
{"event": "planned", "parse_id": "p_9a11", "route_id": "r_77c2", "date": "2026-11-07", "chips": ["..."], "summary": {"distance_mi": 10.0, "start_time": "07:00"}}
```
The app saves it to the planned list. Opening it on the day calls `POST /v1/runs` with its `constraints`, and the app keeps the old route if the new one isn't better.

## Events: `done` and `error`
- `done`: `{"event": "done"}`.
- `error`: `{"event": "error", "code": "engine_unavailable" | "parse_failed" | "bad_request" | "expired", "text": "..."}`. The text comes from templates.
- `expired`: the answer's `parse_id` is unknown or older than 15 minutes (pending questions are kept in memory for 15 minutes, and a server restart forgets them). The app resends the original request (Jared, 2026-11-08).

## Built in step 5 (decision 029)
- **`done` ends every clean stream**, including one that ends with a question, so the app can tell a finished stream from a dropped connection. `error` ends a stream that failed.
- **A to B (step 8):** with an end place, route `kind` is `"a_to_b"`. No distance means the shortest way (the distance chip says "Shortest way"); a distance shorter than the shortest way gets the engine's `question`. `reach_m` stays null for these runs.
- **Via places (step 9):** every route passes every via place, within 30 m of a park's or a lake's outline, 60 m of a path or street, or 150 m of a point. With an end too, the route goes through the vias on its way there.
- **Route entries** in `top3`, `provisional` and `final` carry `id`, the same for the same route in every event of one build (step 6).
- **`client.now`** may be UTC (`Z`); the server reads it in `client.tz` (step 6).
- **`final`** also carries `pool` (`{candidates, best_of}`, the fixture's `pool`; step 6), `routes` (the top 3, as in `top3`), `route` (the #1 in full, the fixture's `route`: summary, markers, stretches and pieces), `pool_size`, `notes` (a distance miss with the nearest route and how far off, or no route; `trust: "measured"`) and `timing`.
- **Can't-do lines from the engine:** `gap: "later"` for what a later step builds (along-avoids and past routes build nothing yet; an end place builds from step 8 and via places from step 9, and the stream ends after `parsed`; hills and a planned second run build the first run anyway), and `gap: "avoid_unknown"` for an avoid that isn't on the no-go list.
- **Answers:** a tapped option settles what it names. Typed text is read by code (a distance, a place name or address, a borough, a recent route's name); text code can't read brings the same question back with a new `parse_id`. No Claude call either way.
- **Auth:** `Authorization: Bearer <Loop token>` on everything but `GET /v1/health`. A missing or wrong token is HTTP 401; every other problem is an `error` event.

## Other endpoints
- `GET /v1/routes/{id}`: a stored result, the same payload as `final`.
- `GET /v1/health`: the server is up and the engine is ready.
- Feedback endpoints come later. The feedback tables from Phase 2 already exist.

## Copy
Every string the runner sees (chip text, questions, can't-do lines, notes, errors) lives in one template file on the server. The UI chat owns the wording; Code owns the keys. Claude only fills in place names and route names.

## Versioning
Every request and event carries `"v": 1`. A breaking change bumps the version, and the server accepts both for one release.
