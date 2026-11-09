# Wiring the iPhone app to the Loop API (Phase 3, step 6)

*For the iPhone build session. The server side is done (decision 029). The data shapes are in
`parse-contract-v1.md`; this doc covers how to call the API from iOS. Code in the Phase 3 session doesn't edit
`ios/`; everything below is yours to build.*

**Milestone:** a typed request on Jared's phone draws a streamed route.

## 1. Endpoint and secrets
- **Base URL:** `https://<mac-name>.<tailnet>.ts.net`, from Jared once Tailscale is set up
  (`tailscale-steps.md`). It's HTTPS with a real certificate, so no App Transport Security exception is needed.
  The Simulator can use the same URL, because it shares the Mac's network.
- **Put the URL in `ios/Config/Secrets.xcconfig`** (git-ignored) as `LOOP_API_BASE`, and pass it through
  `project.yml`'s Info.plist properties, as `MBXAccessToken` is.
  - xcconfig treats `//` as the start of a comment, so write it as `LOOP_API_BASE = https:/$()/<mac-name>.<tailnet>.ts.net`.
- **The Loop token is a secret.** Keep it out of the bundle, the xcconfig and git (brief: nothing secret goes in the
  app).
  - Jared pastes it once into the debug screen (Universal Clipboard from the Mac works). Store it in the Keychain
    as a generic password, and never print or log it.
  - Every request but health sends `Authorization: Bearer <token>`. A wrong or missing token gets HTTP 401, with no
    event stream.
- **Without a URL or a token**, the app keeps working on the bundled `kips3-ui.json`, as it does today.

## 2. Endpoints
| | |
|---|---|
| `GET /v1/health` | No token. `{"v":1,"ok":true,"engine":true,"database":true,"parser":true}` |
| `POST /v1/runs` | The request; the response is an event stream (`text/event-stream`) |
| `GET /v1/routes/{route_id}` | A finished build's `final` payload. Kept in memory for the last 50 until step 7 stores them |

## 3. The request
Send JSON with `Content-Type: application/json`, and encode it with `keyEncodingStrategy = .convertToSnakeCase`.
Exactly one of `text`, `answer` or `constraints`:

```json
{"v": 1,
 "text": "3 easy miles, mostly by the water",
 "client": {"now": "2026-11-08T06:40:00-05:00", "tz": "America/New_York",
            "location": {"lat": 40.7438, "lon": -73.9799, "accuracy_m": 15}},
 "profile": {"usual_distance_mi": 3.1, "usual_time": "07:00", "saved_places": []},
 "recent_routes": []}
```
- **`client.now`:** use `ISO8601DateFormatter` with `timeZone = .current`, so it carries the offset. A UTC `Z`
  also works: the server reads it in `tz`.
- **`location`:** from Core Location, when-in-use. It needs an `NSLocationWhenInUseUsageDescription` in
  `project.yml`. Send `null` when it's off or denied: the server then starts from Home, or asks where to start.
- **`profile` and `recent_routes`** live on the phone. For the debug screen, a fixed usual distance and time with
  empty lists is enough. If Home is set, it stays on the phone and is sent with each request; it's never put in a
  fixture or committed.
- **Text** is at most 500 characters.

## 4. Reading the stream
`URLSession.bytes(for:)`, then `bytes.lines`:

```swift
var req = URLRequest(url: base.appending(path: "v1/runs"))
req.httpMethod = "POST"
req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
req.setValue("application/json", forHTTPHeaderField: "Content-Type")
req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
req.timeoutInterval = 60            // an idle limit; the server sends ": ping" every 15 s
req.httpBody = try encoder.encode(body)

let (bytes, response) = try await URLSession.shared.bytes(for: req)
guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw LoopAPIError.unauthorized }
for try await line in bytes.lines {
    guard line.hasPrefix("data:") else { continue }       // skip "event:" lines and ": ping" comments
    let data = Data(line.dropFirst(5).utf8)
    switch try decoder.decode(EventKind.self, from: data).event {   // {"event": "parsed" | "top3" | ...}
    case "parsed": ...
    case "candidates": ...                               // light outlines while the engine searches
    case "question": ...                                 // the engine asks (step 8); answer it as in section 6
    case "top3", "provisional": ...
    case "final": ...
    case "done": return
    case "error": ...
    default: continue                                    // a newer server's event: ignore it
    }
}
```
- **Each event's data is one line of JSON** and carries its own `"event"` field. Switch on that, and ignore the
  `event:` lines. `bytes.lines` drops the blank lines that separate events, so don't wait for them.
- **Decode with `keyDecodingStrategy = .convertFromSnakeCase`**, as `RouteFile.decode` already does.
- **Run each stream in a `Task`.** Cancel it when a new request starts. If the phone disconnects, the server still
  finishes the build and keeps it.
- **`done` ends every clean stream**, including one that ends with a question. `error` ends a failed one. If the
  connection closes with neither, treat it as `engine_unavailable`.

## 5. The events, in order
1. **`parsed`**, about 3 s after send. It carries:
   - `chips`: `{id, field, text, source, editable, place?}`
   - `cant`: `{id, gap, text}`
   - `notes`: `{id, key, text, trust}`
   - `question` (or null)
   - `constraints` and `parse_id`

   Each chip also has `span`: `{text, start, end}`, the runner's words behind it, counted in Unicode scalars
   (`text.unicodeScalars`), end exclusive; null for preset, default and usual values. Light those words up in the
   sentence. `question.chip_id` names the chip a question is about. When the runner edits a chip, drop that chip's
   entry from `constraints.spans` and `constraints.sources` before sending the constraints back.
   Show every string as sent; they all come from the server's templates. Lines with `gap: "later"` say what the
   engine can't build yet. When the request needs one of those (an end place, a via place, an along-avoid, a past
   route), the stream goes straight to `done` with no routes.
   `parsed.reach_m` is how far the run can get from the start, in meters (null with no distance yet, or an A-to-B run).
2. **`candidates`**, from right after `parsed` until `final`, one event per route the engine tries: `{route_id, elapsed_s, candidates: [{id, kind, points}]}`. `points` is a light `[lon, lat]` outline, at most 40 points, about 1 KB an event, 50–100 a build. For drawing the search only. A candidate's `id` is the one it keeps if it reaches `top3`. Ignore it if you don't draw it.
3. **`top3`**, the first about 0.3–0.6 s after `parsed`, then again each time the top 3 changes:
   `{route_id, elapsed_s, provisional, routes: [...]}`.
   - Each route has `{id, rank, kind, label, score, distance, geometry}`. That is the fixture's `top3` entry plus
     `id`.
   - **`id` is the same for the same route in every event of one build**, so a route that moved from #2 to #1 can
     morph, and a new one can be drawn in.
   - Don't show `score` (the fixture rule: the ranking score stays off screen).
4. **`provisional`**, once: the same shape. This is the settle moment from decision 018; in testing, #1 has never
   changed after it.
5. **`final`**, 9–29 s after send, depending on distance. It carries:
   - `routes`: the final top 3, the same as the last `top3`
   - `route`: the #1 in full, exactly the fixture's `route`, with summary, markers, stretches and pieces. It's null
     when no route could be built.
   - `pool`: `{candidates, best_of}`, the fixture's `pool`
   - `pool_size`: "Best of N"
   - `notes`: a distance miss with the closest route and how far off it is, or `no_route`
   - `timing`: for logs only

   It's about 200 KB for 8 mi.
6. **`done`**.

**Building a `RouteFile` from `final`:**
- `route` ← `final.route`
- `top3` ← `final.routes` (an extra `id` and `score` decode harmlessly)
- `pool` ← `final.pool`
- `request` ← `final.route.features[0].properties.request`
- `about` is made on the phone: the time now, and the start label from the start chip

Before `final`, only outlines and distances exist; the card details arrive with `final`. The replay's `BuildEvent`
uses ranks into the saved file. For a live build, keying it by route `id` fits the stream; the fixture replay can
use "1", "2" and "3" as ids. That's your call.

## 6. Questions and answers
When `parsed.question` is set (`{id, about, from, text, options: [{id, text}], allow_text}`), show it. The stream
then ends with `done`, and no routes stream while the question is open.

The engine can ask too, after `parsed` (step 8): a `question` event with the same fields at its top level, plus its
own `parse_id`, then `done`. For example, "The shortest way there is 4.5 mi. Make it 4.5 mi?" when a run to a place
is shorter than the shortest way there. Answer it the same way, with that event's `parse_id`.

The answer is a new `POST /v1/runs` with the same `client`, `profile` and `recent_routes`, and:
```json
"answer": {"parse_id": "<the parsed event's parse_id>", "question_id": "q_1", "option_id": "b", "text": null}
```
or, typed, `"option_id": null, "text": "about 6 miles"`.
- The stream picks up from `parsed`, in about 0.1 s, because Claude isn't called again. Then come the routes, or
  the next question. Each `parsed` has a new `parse_id`; answer the latest one.
- If code can't read a typed answer, the same question comes back.
- **`error` with `code: "expired"`:** the question was open more than 15 minutes, or the server restarted. Resend
  the original `text` request automatically, once.

## 7. Errors
`{"event": "error", "code": ..., "text": ...}`. Show `text` as sent.
| code | What the app does |
|---|---|
| `expired` | Resend the original text request once (section 6) |
| `parse_failed` | Show the text; the runner rewords |
| `engine_unavailable` | Show the text; offer to retry |
| `bad_request` | A bug in the request we built: log it (no body, no location) and show the text |

HTTP 401 means the token is wrong. Send the runner to the debug screen's token field.

## 8. The temporary debug screen
This is temporary, until the UI chat designs the request screen. Put it behind a Debug-build-only button.
- **Server:** the base URL (read-only), a secure token field (saved to the Keychain), and **Check**, which calls
  `GET /v1/health` and shows each flag.
- **Request:** a text field and **Send**. Under them, a log of events, one line each, with the seconds since send,
  like the command-line client (`python -m api.scripts.ask`). Show chips, can't-do lines and notes as plain text.
- **A question:** its text, one button per option, and a text field when `allow_text` is true.
- **Routes:** feed `top3`, `provisional` and `final` into the main screen's map, so the milestone is visible: a
  typed request draws a streamed route.

## 8b. Route kinds
`kind` is `"loop"`, `"out_and_back"`, `"lollipop"`, or (step 8) `"a_to_b"` for a run that ends somewhere else. An
A-to-B route starts at the start and ends at the end chip's place; it has no turnaround.

## 9. Privacy
- Never log request bodies or the location. Never log the token.
- Home and recent routes stay on the phone.
- Claude never sees coordinates; the server resolves places itself.

## 10. Checking it from the Mac
To watch the same stream the phone gets:
```bash
python -m api.scripts.ask "3 easy miles, mostly by the water" --url https://<mac-name>.<tailnet>.ts.net
```
