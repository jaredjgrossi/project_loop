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
  "route_id": "r_ab12cd34",
  "mode": "exact",
  "shape": "out_and_back",
  "client": {
    "now": "2026-11-03T06:40:00-05:00",
    "tz": "America/New_York",
    "location": {"lat": 40.7438, "lon": -73.9799, "accuracy_m": 15}
  },
  "profile": {
    "usual_distance_mi": 3.1,
    "usual_time": "07:00",
    "usual_shape": "out_and_back",
    "saved_places": [{"id": "home", "label": "Home", "lat": 40.7438, "lon": -73.9799}]
  },
  "recent_routes": [
    {"id": "rt_a", "date": "2026-10-27", "name": "East River esplanade out-and-back", "distance_mi": 3.0, "ran_count": 2},
    {"id": "rt_b", "date": "2026-11-02", "name": "the Stuy loop", "distance_mi": 4.0, "saved": true, "ran_count": 7}
  ]
}
```
Headers: `Authorization: Bearer <Loop token>`, and `X-Loop-Install: <a random id per app install>` (decision 043).
- `location` is null when location is off.
- `profile` and `recent_routes` live on the phone (minimal storage, no accounts) and are sent with every request.
- `shape` (decision 043): the route type the runner picked in the app before sending: `"any"`, `"loop"`,
  `"out_and_back"` or `"one_way"`, optional.
  - It beats the words: "3 mile loop" sent with `shape: "out_and_back"` builds out-and-backs. The shape chip shows
    it with `source: "said"` and `span: null`, since it isn't in the sentence.
  - `one_way` means the run ends somewhere else, so it needs an end place. If the text names none, the `parsed`
    event asks `{"about": "end", "from": "parser", "text": "Where do you want to end?", "allow_text": true}`.
    Answer it with a place name, like any question. With an end, the shape chip reads "One way".
- `profile.usual_shape` (2026-11-10): the same four values, optional.
  - It applies when neither `shape` nor the words give one: the shape chip shows it with `source: "usual"`.
  - Any shape word in the request wins over it, even a plain "loop" (which means either shape, R10).
  - A usual `one_way` asks for the end the same way.
- `recent_routes` entries (decision 043) may carry `saved: true` (a favorite), `name` (the runner's own name for a
  favorite, which can differ from Loop's) and `ran_count` (how often they ran it; `times_run` is still read).
  - "My usual" is the most run (`ran_count`).
  - A favorite is found by its name: "the Stuy loop".
  - Claude sees each route's id, date, name, distance, how often it was run and `saved`, never its line.
- `X-Loop-Install` (decision 043): a random id the app makes once per install (a UUID: 8 to 64 letters, digits or
  dashes) and sends on every request.
  - It groups one runner's ratings without an account, and becomes the per-user key in Phase 4.
  - It's stored with each build in `saved_routes` and with feedback, never with the request text or location.
  - Optional on `POST /v1/runs` and `GET /v1/routes/{id}`; required for feedback. Malformed: HTTP 400.
- **"Run again"** (decision 043): `{"v": 1, "route_id": "r_ab12cd34.2", "mode": "exact", "client": ..., "profile": ...}`,
  with no `text`, `answer` or `constraints`.
  - It runs the stored route's own line exactly, with no routing: the same geometry, read for now (crowds for the
    time it's sent).
  - The stream is `parsed` (the stored request's chips, with today's clock), `final` (one route, under a new
    `route_id`, `timing.run_again` naming the original), then `done`.
  - Not stored: `error` with `code: "route_not_found"`.
- `route_id` (2026-11-10), with `constraints` only: the build the chip edit started from (the `route_id` of its
  `final`).
  - When the edit changes only `shape`, the server answers from that build's routes at once: `parsed`, one `top3`,
    `final` (with `timing.from_pool`), then `done`, and no `candidates`.
  - It builds again when none of those routes is of the new kind (a loop-only build has no out-and-backs), or when
    the server no longer has that build (it keeps the last 8).
  - Without `route_id`, or with any other change, it builds as usual.
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
- **Via chips carry `mode`** (decision 035): `"through"` (pass the place: "Through Hudson River Greenway, Manhattan") or `"around"` (a full lap of it: "A lap of the Reservoir running track, Manhattan"). Code sets it from the runner's word, never Claude: "around", "loop of", "lap of" mean around; "through", "in", "along", "past" mean through; a known running loop named on its own means around ("Central park reservor", "the Prospect Park loop"); anything else is through. The chip editor can switch it. In `constraints.via_places`, each via has the same `mode` and, for a known running loop, `loop` (its id: `reservoir`, `central_park_drive`, `prospect_park_drive`). With an around via and no distance said, there's no usual distance: the distance chip reads "The lap and the way there" (`source: "default"`), and the engine builds the lap plus the shortest way there and on.
- `constraints.spans` carries the same spans by chip id, so a chip edit (which sends `constraints`, not text) keeps the other chips' spans. When the runner edits a chip, the app drops that chip's entry from `constraints.spans` (and from `constraints.sources`): an edited value is said, but not in the sentence. Spans are never stored with a build (R8).

### Question
- At most one per response.
- `about` is one of: `distance`, `start`, `end`, `via`, `time`, `reuse`, `amount`.
- `from` is one of: `parser`, `places`, `engine`.
- `options`: 0–4 tap answers. `allow_text`: whether typing is offered.
- "The park" with no major park within about 1 mi (R13, decision 043) picks the runnable place that clearly wins,
  with no question: the only one that fits, or the nearest when the next is at least twice as far. For a run that
  goes there from elsewhere, a place counts only within 45% of the run's length. Otherwise it asks:
- "Which park?" options (decision 041) are runnable places only, nearest first, each with how far it is: `{"id": "a", "text": "East River Esplanade · 0.4 mi"}`. Places whose shapes mostly overlap are one option, the nearer one: Hudson River Park, not also the greenway through it (decision 042).
- **A street given alone** ("west 71st st", "W. 71st Street") as a start, end or via is the point on it nearest the
  runner, or the other named place, labeled `listed` (decision 043). If the street is over 2.5 km long and that
  point is over 800 m away, the choice matters, so it asks `{"about": "start"|"end"|"via", "from": "places", "text":
  "Where on Amsterdam Ave?"}`, with up to four crossings, about 400 m apart, as options ("Amsterdam Ave & W 71st St").
- **A named park is that park** (decision 047). "Central Park" or "Prospect Park" is looked up by name, whatever kind
  Claude recorded; only "the park", "a nearby park" and the like take the nearest runnable place. A named park that isn't
  found asks "Couldn't find X. What's the address?".
- **"Here" as the answer to "Where should it start?"** ("here", "my location", "where I am", "near me") is the current
  location, source `said`. With location off it asks: "I can't see where you are. Turn on location for Loop, or type a
  place."
- **An address as a via** ("past 1000 5th Ave") is geocoded like a start's, with the same borough question.
- **Landmarks** (the Met, the Empire State Building, Yankee Stadium) are places of kind `landmark`, trust `listed`, source
  "Loop curated landmarks (position from OpenStreetMap)". A landmark beats a shop with its name.
- A place question never offers two options that read the same: of two places with one name in one borough, the place wins over a shop named after it (decision 042).
- `chip_id` (2026-11-09): the chip the question is about, so the app can mark its words in the sentence; null when the runner said nothing about it ("How far?" after "what do you suggest"). When nothing was built for it yet ("Which 86th St?"), the event carries a chip for it made from the runner's own words, with its span.
- While a question is open, no routes stream.

### Can't-do lines and notes
- `cant`: `{"id", "gap", "text"}`, for example `{"id": "k_1", "gap": "G9", "text": "Can't plan around street lighting yet"}`.
- `gap: "later"`, `key: "amenities"` (decision 047): a restroom or water stop was asked for. Loop doesn't plan stops yet:
  "Can't plan a restroom or water stop along the route yet. The route is built without it". The `amenity` chips still
  show what was understood. One line however many stops; the build isn't blocked.
- `gap: "lap"` (decision 035): a lap Loop can't run, and the route passes the place instead: "Can't run laps of the McCarren Park track yet: it isn't in Loop's path data. These routes go to it", or "Can't run a lap of 2nd Ave: it isn't a loop. These routes go through it".
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
- **`final` holds all three routes in full** (decision 049; UI review). Each entry of `routes` is as in `top3` (`id`, `rank`,
  `kind`, `label`, `score`, `distance`, `geometry`) plus:
  - `file`: the route file the app already reads for the first route (`route`): a GeoJSON FeatureCollection with the line
    and its `properties.summary`, the start, mile and turnaround markers, the stretches and the pieces by kind. So the
    second and third routes have the same stats, pieces and stretches as the first. `route` stays, equal to
    `routes[0].file`, until the app reads `file`.
  - `label` is the route's name from what it measured (below), and the same string as `file`'s `properties.label`. The
    `top3` and `provisional` events name routes from the generator's label, before the stretches are measured, so the
    name can change at `final`: show the `final` one.
- **`final.shape`**: `{"requested": "any" | "loop" | "out_and_back" | "one_way", "met": true | false, "shown": ["loop"]}`.
  `met` is false when the shape asked for couldn't be found and the routes shown are another kind (a loop request
  that came back as the best out-and-back, with the `no_good_loop` note), or when there is no route. `shown` is the
  kinds of the routes in `routes`. A run to an end is `one_way`.
- **`kind`** is `loop`, `out_and_back`, `lollipop` (an out-and-back with a loop at the far end) or `a_to_b` (a one-way run).
- **Route names** (`label`, `properties.name`; decision 050) are what a runner would say: the main stretch, which way it
  heads and where it turns: "East River Esplanade, north to 34th", "Wythe Avenue, south to Myrtle", "Central Park,
  clockwise", "1st Ave & E 30th St, clockwise". Never the route type (`kind` has it), compass degrees or generator words;
  capitalized, at most 36 characters, and different for each of the three routes of a `final`. The `top3` and
  `provisional` events still name routes from the generator ("Out-and-back on the waterfront"); show the `final` name.
  `properties.plan` (the generator's label) is no longer in the files of a `final`.
- **`summary.way`** (in each route's `file`): the stretch list for "The way", in order:
  ```json
  {"name": "East River Esplanade", "kind": "corridor", "from_mile": 0.52, "to_mile": 2.61,
   "distance": {"value": 2.09, "unit": "mi", "meters": 3363, "status": "measured", "source": "route geometry (GraphHopper)"},
   "status": "measured", "trust": "listed", "source": "Loop corridor catalog #9, from OSM ways (...)",
   "turnaround": {"mile": 1.51, "meters": 2435}}
  ```
  - `kind` is `corridor`, `park`, `waterfront`, `street` or `path`. `turnaround` is on the stretch the run turns on (one
    per turn: a route that goes out both ways has two); a loop has none.
  - A runnable path is never named after the road beside it: a stretch of the East River Esplanade or the Hudson
    River Greenway doesn't come back "FDR Drive" or "11th Avenue". A waterfront stretch with no named path is
    "waterfront path"; a path with no name is "unnamed path". A road's sidewalk or crossing keeps the road's name.
- **`summary.steps`** (in each route's `file`; decision 054): the turn-by-turn list for Directions, in order along the route.
  `summary.way` is unchanged, for older clients and for saved routes (see below).
  ```json
  {"index": 3, "maneuver": "right", "street": "East 33rd Street", "from_mile": 0.26, "from_meters": 419,
   "distance": {"value": 0.15, "unit": "mi", "meters": 244, "status": "measured", "source": "route geometry (GraphHopper)"},
   "point": {"lat": 40.7449, "lon": -73.9801}, "status": "measured",
   "maneuver_source": "GraphHopper turn instructions (foot profile)", "trust": "listed", "source": "OSM way w1"}
  ```
  - `maneuver` is one of `start`, `continue`, `slight_left`, `left`, `sharp_left`, `slight_right`, `right`,
    `sharp_right`, `u_turn`, `turnaround`, `finish`. It is GraphHopper's turn sign for the foot route, never written by
    the model. `turnaround` comes from the turnaround marker (the same one `summary.turnarounds` lists), since
    GraphHopper has only a U-turn there; a route that goes out both ways has two. `finish` is the last step, at the
    end of the route, with a distance of 0 (the app says "back at the start" from the route `kind`).
  - `street` is the name of the street, path or park the step runs most, from the same labeled stretches as
    `summary.way`: so a path is named after itself ("waterfront path", "unnamed path"), never the road beside it, and a
    road's sidewalk or crossing keeps the road's name. `null` for `finish`, for a route with no stretches, and for a
    turn onto the street the runner is already on ("Turn left", not "onto" it). `trust` and `source` are the name's
    own, as in `summary.way`.
  - **Tiling:** `from_meters` starts at 0 and each step's `from_meters` plus `distance.meters` is the next step's
    `from_meters`; `finish` is at `summary.distance.meters`. The mile values tile too: `from_mile` is
    `round(from_meters / 1609.344, 2)` and `distance.value` is the difference of the displayed miles, so the numbers on
    the screen add up. Use `meters` when you need an exact figure.
  - **What isn't a step:** a stretch under 50 m (a crossing, a curb jog, a roundabout's exits) is part of the step
    before it; where one is folded away, the next turn is measured again from the line. A "continue" onto the street
    the runner is already on, and a bend inside the one path, park or corridor they are on, are not steps (a U-turn is).
    A GraphHopper turn the line doesn't make (under 11.5 degrees) is a `continue`. A start stub under 50 m joins the
    first street. A change of street with no turn is a `continue` onto the new street.
  - `maneuver_source` says where the maneuver came from: GraphHopper's turn instructions, the turnaround marker, a
    change of street with no turn, or a turn measured from the line after short steps were folded away. `status`
    is `measured` for the maneuver and the distance; `trust` and `source` are for the street name.
  - `point` is the position on the route where the step begins. Routes that weren't routed (a stored line, "run
    again") have no `steps` key at all: keep the stretch list as the fallback.
- **`summary.reason`**: one line on why the route fits, written by code from its own numbers, never by the model:
  `{"text": "58% on the waterfront, 22 lights, flat", "parts": [{"key": "water", "text": "...", "status": "measured"}],
  "status": "estimate", "source": "..."}`. Parts, in this order and at most three:
  - `park`: "82% through Central Park" at 40% park or more with one park carrying it, else "35% in parks" from 20%;
  - `water`: "58% on the waterfront" from 20%;
  - `lights`: the total ("22 lights", "1 light", "No lights");
  - `flat` ("flat", under 8 m of climb a mile) or `hilly` ("120 m of climb", over 25 m a mile); both estimates.

  A route that is mostly park isn't called a waterfront route for a sliver by the water. `text` is null when nothing
  stands out and nothing is scored.

## Event: `question` (engine)
Same shape as `parsed.question`, with `from: "engine"` and its own `parse_id`. The stream ends after it (then `done`). Built in step 8: when a run ends somewhere else and the distance is shorter than the shortest way there, beyond the tolerance, the engine asks before anything streams but `parsed`:
```json
{"event": "question", "v": 1, "parse_id": "p_9b21", "id": "q_1", "about": "distance", "from": "engine",
 "text": "The shortest way there is 4.5 mi. Make it 4.5 mi?", "options": [{"id": "a", "text": "4.5 mi"}], "allow_text": true}
```
Step 9 adds the same question for via places: "Going through Hudson River Greenway takes at least 4.3 mi. Make it 4.3 mi?" when the shortest way through them (and back, or on to the end) is longer than the distance. With a lap (decision 035): "A lap of the Reservoir running track and the way there takes at least 2.4 mi. Make it 2.4 mi?"; the lap counts toward the distance. Answer it as any question, with this event's `parse_id`. The offer is the shortest way rounded up to 0.1 mi; a typed distance works too. The answer is a said distance; Claude isn't called again.

## Event: `planned`
```json
{"event": "planned", "v": 1, "parse_id": "p_9a11", "route_id": "r_77c2", "date": "2026-11-07", "chips": ["..."],
 "summary": {"distance_mi": 10.02, "start_time": "07:00"}, "constraints": {"...": "the planned RunConstraints"},
 "notes": []}
```
The app saves it to the planned list. Opening it on the day calls `POST /v1/runs` with its `constraints`, and the app keeps the old route if the new one isn't better.

Built in step 11 (decision 038):
- With a second run, the stream is `parsed` … `final`, then `planned`, then `done`.
- The second run is built from its own start (home on a later day, R16) for its own day and time, and stored like any build, so `GET /v1/routes/{route_id}` works. Only `planned` is streamed for it, never its candidates.
- `summary.distance_mi` is the built route's distance.
- If it can't be built now, `route_id` is null and `notes` says so (`planned_not_built`). The app builds it when the runner opens it.

## Events: `done` and `error`
- `done`: `{"event": "done"}`.
- `error`: `{"event": "error", "code": "engine_unavailable" | "parse_failed" | "bad_request" | "expired" | "route_not_found", "text": "..."}`. The text comes from templates. `route_not_found`: "run again" of a route the server doesn't have.
- `expired`: the answer's `parse_id` is unknown or older than 15 minutes (pending questions are kept in memory for 15 minutes, and a server restart forgets them). The app resends the original request (Jared, 2026-11-08).

## Built in step 5 (decision 029)
- **`done` ends every clean stream**, including one that ends with a question, so the app can tell a finished stream from a dropped connection. `error` ends a stream that failed.
- **A to B (step 8):** with an end place, route `kind` is `"a_to_b"`. No distance means the shortest way (the distance chip says "Shortest way"); a distance shorter than the shortest way gets the engine's `question`. `reach_m` stays null for these runs.
- **Via places (step 9):** every route passes every via place, within 30 m of a park's or a lake's outline, 60 m of a path or street, or 150 m of a point. With an end too, the route goes through the vias on its way there.
- **Laps (decision 035):** an `around` via is a full lap, in the loop's running direction (counterclockwise for the four known loops), entered and left at the point nearest the way in. Every route runs along at least 90% of the lap's ring, within 30 m, and the lap counts toward the distance. Known loops run their curated ring (the Reservoir track 1.57 mi, the Central Park drive 6.05 mi, the Prospect Park drive 3.49 mi, measured from OSM); any other park or water runs its outline. A lap isn't run twice, so there are no out-and-backs through it.
- **Route entries** in `top3`, `provisional` and `final` carry `id`, the same for the same route in every event of one build (step 6).
- **Kinds and names are honest** (decision 044):
  - `kind` is measured on the route's own line: `out_and_back` when 50% or more of it is retraced, else `lollipop`
    (some retracing, with a loop) or `loop`; `a_to_b` for a one-way run.
  - `label` (route entries, and `route`'s `label` and `name`) is a name built from that kind plus the place:
    "Out-and-back on Riverside Walk", "Loop through Central Park", "Loop on the street grid", "One way along Domino
    Park waterfront". It is never "loop" for a route that isn't one.
  - `route`'s `plan` keeps how the generator made it ("loop on Riverside Walk, heading 19 degrees"), for logs only.
  - The app's card, eyebrow and saved-route names should use `kind` and `label` as sent.
- **`shape: "loop"` is a hard rule** (decision 044): loops only, no out-and-backs and no lollipops.
  - If no loop fits within tolerance, the nearest loop comes back with the usual distance note.
  - If no loop is found at all, the best other kind comes back, with `notes`: `{"key": "no_good_loop", "trust":
    "measured", "text": "No good loop from here; showing the best out-and-back"}`. Never a silent swap.
- **No padding with spurs** (decision 044): no route takes a quick out-and-back off its main line to make up
  distance: a dead end it goes 150–400 m into and back, more than 300 m from the start or finish. A reversal under
  150 m is part of the line (a ramp, a footbridge approach). A past route rebuilt or run again keeps the spurs
  the runner ran.
  - A spur at one of the generator's own waypoints is removed, not rejected (decision 045): the waypoint moves to
    where the spur left the main line and the route is routed again. From Kips Bay, the waterfront entry sat 75 m
    down the East River Esplanade from E 34th St, and the waterfront route went there and back. Nothing in the
    response changes; routes that used to be dropped for such a spur now come back without it.
- **Turnaround markers** (`feature: "turnaround"`) mark only where the run turns: every dead end it reaches 400 m or
  more into, and its farthest point if it turns there. Not spurs or short reversals; a round loop has none.
- **Climb** (`summary.climb`, `route.elevation.gain_m` and `loss_m`) is read from the height every 0.1 mi through a
  2 m band, in whole meters (decision 044). Summing every route point's height counted tile noise: 130.5 m for a
  route that climbs about 50.
- **`client.now`** may be UTC (`Z`); the server reads it in `client.tz` (step 6).
- **`final`** also carries `pool` (`{candidates, best_of}`, the fixture's `pool`; step 6), `routes` (the top 3, as in `top3`), `route` (the #1 in full, the fixture's `route`: summary, markers, stretches and pieces), `pool_size`, `notes` (a distance miss with the nearest route and how far off, or no route; `trust: "measured"`) and `timing`.
- **Can't-do lines from the engine:** `gap: "avoid_unknown"` for an area avoid that isn't on the no-go list. Nothing in Phase 3 is left for later: end places (step 8), via places (step 9), along-avoids (step 8b), hills (step 10), past routes and planned runs (step 11) all build, so `gap: "later"` no longer appears.
- **Ends in a neighborhood (decision 042):** `end_place.area: "neighborhood"` marks an end that is an area. The route finishes on the way in, at the first point 300 m inside the neighborhood's area (its 2020 NTA), not at its middle. "3 miles to Williamsburg" from Kips Bay finishes after 3.6 mi on the Brooklyn side of the Williamsburg Bridge, where going to the middle would take 4.3 mi.
- **Past routes (step 11, decision 038):**
  - `reuse_route_id` is a recent route's `id`, the id Loop gave it: `r_xxxxxxxx.N`, or a build id for its #1.
  - The server reads the route's line from `saved_routes` and rebuilds it for now, from where it started: closures, no-go zones and avoids as of now, crowds for this start time.
  - Every rebuilt route runs along at least 90% of the old line. With `reverse` it runs the other way.
  - "Longer": the distance is the recent route's `distance_mi` plus the answer, and the route adds detours.
  - A route with no line on file builds nothing, and `final.notes` says so (`past_route_not_found`).
- **"Skip the ferry part" (H04):** code finds the ferry landings within 100 m of the past route(s) the request may mean (`pulse_sources`). Each becomes an area avoid with its coordinates:
  - the avoid is `{"name": "E 34th St ferry landing", "how": "area", "place": {"lat": ..., "lon": ..., "source": "NYC Ferry GTFS", "trust": "listed"}}`;
  - the rebuilt route stays 120 m from each landing and leaves that stretch of the old route out.

  Without a landing along the route, the words stay as said, and the engine says it can't avoid them.
- **Hills (step 10, decision 037):** `hills: "avoid"` ("flat", "avoid hills") ranks routes by how much they climb, from the elevation every 0.1 mi. The #1 route's `summary` then carries `hills`: `{"value": 4.2, "unit": "m/mi", "status": "estimate", "source": "...", "steepest_pct": 2.1}`, the climb per mile and the steepest 0.1 mi. It's an estimate, like `climb`, because the elevation tiles are a smoothed ground model. With "don't mind" there's no `hills` field and no change to the ranking.
- **Along-avoids (step 8b, decision 036):** `{"name": "42nd St", "how": "along"}`, or a stretch, `"1st Ave, E 25th–E 34th St"`. No route runs along the street (or the stretch) for 75 m or more in one go, within 20 m of its centre line, sidewalks included; crossing it is fine. The router steers off it too. A street Loop can't find near the start isn't avoided, and `final.notes` says so: `{"key": "avoid_not_found", "trust": "listed", "text": "Couldn't find Nowhere St near the start, so these routes don't avoid it"}`.
- **Answers:** a tapped option settles what it names. Typed text is read by code (a distance, a place name or address, a borough, a recent route's name); text code can't read brings the same question back with a new `parse_id`. No Claude call either way.
- **Auth:** `Authorization: Bearer <Loop token>` on everything but `GET /v1/health`. A missing or wrong token is HTTP 401; every other problem is an `error` event.

## Other endpoints
- `GET /v1/routes/{id}`: a stored result, the same payload as `final`, with every route's full line.
  - `{id}` is a build's `route_id` or one of its routes' ids (`r_xxxxxxxx.N`).
  - Builds are kept in `saved_routes` for good, so a route the runner saved or ran stays fetchable indefinitely
    (decision 043).
  - Unknown: HTTP 404.
- `POST /v1/routes/{id}/feedback` (decision 043): "I ran it" and the rating. Needs `X-Loop-Install`.
  ```json
  {"ran": true, "ran_at": "2026-11-10T07:30:00-05:00", "rating": "good", "reasons": [], "note": null}
  ```
  - `rating`: `"good"`, `"not_for_me"` or null. Null is fine right after "I ran it": rate later.
  - `reasons`: keys, never wording: `crowded`, `lights`, `water`, `safety`, `other`. They go with a rating.
  - `note`: at most 500 characters.
  - A rating needs `ran: true`.
  - One record per install and route: a later post replaces the earlier one, to change a rating.
  - The reply: the record as stored, plus `created_at`, `updated_at` and `updated` (true when it replaced one).
  - Errors: HTTP 400 without the install id, 404 for an unknown route, 422 for a bad body, 401 without the token.
  - Stored in Phase 2's `route_feedback` (with `generated_routes` holding the route's line), so the ranking can be
    tuned with it later.
- `GET /v1/routes/{id}/gpx` (decision 048): a stored route as a GPX file for the app's Share sheet. `application/gpx+xml`,
  `Content-Disposition: attachment; filename="loop-<route id>.gpx"`. `{id}` is a route's own id or a build's (its first
  route). It holds the line, a `Start` waypoint, `Mile n` waypoints and `Turnaround` waypoints, and no elevation.
  Unknown: HTTP 404. Needs the token.
- `GET /v1/weather/nyc` (decision 051): the city's current temperature for the header line. Needs the token. No
  query, no location: the reading is for New York, so the phone's position is never sent to Loop or on to the
  provider. `200`:
  `{"v": 1, "temp_f": 41, "condition": "cloudy", "description": "Cloudy", "observed_at": "2026-11-13T18:51:00Z",
  "station": "KNYC", "source": "National Weather Service, KNYC Central Park", "status": "measured"}`.
  - `condition` is one of `clear`, `partly_cloudy`, `cloudy`, `fog`, `rain`, `snow`, `thunderstorm`, `other`
    (`other` for haze, smoke and anything the mapping doesn't know; `description` is the station's own wording).
  - `observed_at` is when the station took the reading (UTC), not when you asked. Cached on the server for 5 minutes,
    so a reading can be a few minutes older than the request; it is never more than an hour old.
  - HTTP 503 `{"detail": "weather_unavailable"}` when no station has a fresh reading. The app keeps its last reading
    for its own 30 minutes, then hides the temperature.
- `GET /v1/health`: the server is up and the engine is ready.

## Copy
Every string the runner sees (chip text, questions, can't-do lines, notes, errors) lives in one template file on the server. The UI chat owns the wording; Code owns the keys. Claude only fills in place names and route names.

## Versioning
Every request and event carries `"v": 1`. A breaking change bumps the version, and the server accepts both for one release.
