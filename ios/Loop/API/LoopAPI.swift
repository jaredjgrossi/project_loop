import Foundation

/// The Loop API (Phase 3, `docs/phase3/ios-wiring.md` and `parse-contract-v1.md`). The base URL
/// comes from the git-ignored Secrets.xcconfig through Info.plist; the token from the Keychain.
/// Nothing here logs a request body, the location or the token.
struct LoopAPI {
    let base: URL
    let token: String

    /// A random id per install (decision 043), sent as X-Loop-Install on every request. Set at launch
    /// from the store; it groups ratings without an account and is never a name.
    nonisolated(unsafe) static var installId = ""

    /// The server address, if this build has one (Secrets.xcconfig's LOOP_API_BASE).
    static var baseURL: URL? {
        #if DEBUG
        // UI tests and screenshots run on the bundled route file.
        if ProcessInfo.processInfo.arguments.contains("-LoopOffline") { return nil }
        // Debug: `-LoopUnreachable` points at an address that never answers (TEST-NET-1), to
        // check the health line and the 8 s watchdog.
        if ProcessInfo.processInfo.arguments.contains("-LoopUnreachable") { return URL(string: "https://192.0.2.1") }
        // Debug: `-LoopFakeToken` saves a made-up token, to check the 401 path end to end.
        if ProcessInfo.processInfo.arguments.contains("-LoopFakeToken"), TokenStore.load() == nil {
            TokenStore.save("not-a-real-token")
        }
        #endif
        guard let s = Bundle.main.object(forInfoDictionaryKey: "LoopAPIBase") as? String,
              s.hasPrefix("https://"), let url = URL(string: s) else { return nil }
        return url
    }

    /// A client when the build has an address and the Keychain has a token; otherwise the app runs
    /// on the bundled route file, as before.
    static var live: LoopAPI? {
        guard let base = baseURL, let token = TokenStore.load() else { return nil }
        return LoopAPI(base: base, token: token)
    }

    enum Failure: Error, Equatable {
        /// HTTP 401: the token is wrong or missing.
        case unauthorized
        /// No connection, a timeout, or the stream closed without `done` or `error`.
        case unreachable
    }

    /// `GET /v1/health` (no token): true when the server answers and says it's ready.
    static func health(base: URL, timeout: TimeInterval = 6) async -> Bool {
        var req = URLRequest(url: base.appending(path: "v1/health"))
        req.timeoutInterval = timeout
        guard let (data, response) = try? await URLSession.shared.data(for: req),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let h = try? decoder.decode(Health.self, from: data) else { return false }
        return h.ok
    }

    private struct Health: Decodable { let ok: Bool }

    /// `POST /v1/routes/{id}/feedback` (decision 043): "I ran it" and the rating. Fire and forget: the
    /// run is kept on the phone either way, and a later post replaces this one.
    func feedback(routeId: String, ranAt: Date, rating: RunRating?) {
        struct Body: Encodable {
            let ran: Bool
            let ranAt: String
            let rating: String?
            let reasons: [String]
            let note: String?
            func encode(to encoder: Encoder) throws {
                var c = encoder.container(keyedBy: K.self)
                try c.encode(ran, forKey: .ran); try c.encode(ranAt, forKey: .ranAt)
                try c.encode(rating, forKey: .rating); try c.encode(reasons, forKey: .reasons); try c.encode(note, forKey: .note)
            }
            enum K: String, CodingKey { case ran, ranAt, rating, reasons, note }
        }
        let f = ISO8601DateFormatter()
        f.timeZone = .current
        let body = Body(ran: true, ranAt: f.string(from: ranAt), rating: rating?.verdict.rawValue,
                        reasons: rating?.reasons ?? [], note: rating?.note.map { String($0.prefix(500)) })
        var req = URLRequest(url: base.appending(path: "v1/routes/\(routeId)/feedback"))
        req.httpMethod = "POST"
        req.timeoutInterval = 15
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(Self.installId, forHTTPHeaderField: "X-Loop-Install")
        req.httpBody = try? Self.encoder.encode(body)
        Task { _ = try? await URLSession.shared.data(for: req) }
    }

    /// `POST /v1/runs`, streamed. Each `data:` line is one event's JSON.
    func run(_ body: RunRequest) -> AsyncThrowingStream<ServerEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var req = URLRequest(url: base.appending(path: "v1/runs"))
                    req.httpMethod = "POST"
                    req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    if !Self.installId.isEmpty { req.setValue(Self.installId, forHTTPHeaderField: "X-Loop-Install") }
                    req.timeoutInterval = 60   // idle limit; the server pings every 15 s
                    req.httpBody = try Self.encoder.encode(body)
                    let (bytes, response) = try await URLSession.shared.bytes(for: req)
                    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                    if status == 401 { throw Failure.unauthorized }
                    guard status == 200 else { throw Failure.unreachable }
                    var ended = false
                    for try await line in bytes.lines {
                        // Pings and event names count as signs of life (the watchdog), nothing more.
                        guard line.hasPrefix("data:") else { continuation.yield(.other); continue }
                        let event = ServerEvent.decode(Data(line.dropFirst(5).utf8))
                        continuation.yield(event)
                        if case .done = event { ended = true; break }
                        if case .error = event { ended = true; break }
                    }
                    if !ended { throw Failure.unreachable }
                    continuation.finish()
                } catch let f as Failure {
                    continuation.finish(throwing: f)
                } catch is CancellationError {
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: Task.isCancelled ? CancellationError() : Failure.unreachable)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()
}

// MARK: Request

/// The body of `POST /v1/runs`: exactly one of `text` or `answer` (chip edits come later).
struct RunRequest: Encodable {
    var v = 1
    var text: String?
    var answer: Answer?
    /// A chip edit: the parse's constraints with the edit, sent instead of text (no Claude call).
    var constraints: JSONValue?
    /// With `constraints`: the build the edit started from (a shape-only edit answers from it at once).
    /// With `mode: "exact"`: the route to run again.
    var routeId: String? = nil
    /// "exact": "Run again", the stored route's own line read for now (decision 043).
    var mode: String? = nil
    /// The route type picked before sending: any, loop, out_and_back or one_way. Beats the words.
    var shape: String? = nil
    var client: Client
    var profile: Profile
    var recentRoutes: [Recent]

    struct Answer: Encodable {
        let parseId: String
        let questionId: String
        let optionId: String?
        let text: String?

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(parseId, forKey: .parseId)
            try c.encode(questionId, forKey: .questionId)
            try c.encode(optionId, forKey: .optionId)   // null when typed
            try c.encode(text, forKey: .text)           // null when tapped
        }
        private enum CodingKeys: String, CodingKey { case parseId, questionId, optionId, text }
    }

    struct Client: Encodable {
        let now: String
        let tz: String
        let location: Location?

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(now, forKey: .now)
            try c.encode(tz, forKey: .tz)
            try c.encode(location, forKey: .location)   // null when location is off
        }
        private enum CodingKeys: String, CodingKey { case now, tz, location }
    }

    struct Location: Encodable {
        let lat: Double
        let lon: Double
        let accuracyM: Double
    }

    struct Profile: Encodable {
        var usualDistanceMi: Double = 3
        var usualTime: String = "07:00"
        var savedPlaces: [SavedPlace] = []
        /// The usual route type: "any", "loop", "out_and_back" or "one_way".
        var usualShape: String = "any"

        init(usualDistanceMi: Double = 3, usualTime: String = "07:00", savedPlaces: [SavedPlace] = [], usualShape: String = "any") {
            self.usualDistanceMi = usualDistanceMi; self.usualTime = usualTime
            self.savedPlaces = savedPlaces; self.usualShape = usualShape
        }

        /// From "You" -> Your defaults. Home goes as a saved place; it stays on the phone otherwise.
        init(_ p: RunnerProfile) {
            usualDistanceMi = p.usualDistanceMi
            usualTime = p.usualTime
            usualShape = p.usualShape
            savedPlaces = p.home.map { [SavedPlace(id: "home", label: "Home", lat: $0.lat, lon: $0.lon)] } ?? []
        }
    }

    struct SavedPlace: Encodable {
        let id: String
        let label: String
        let lat: Double
        let lon: Double
    }

    struct Recent: Encodable {
        let id: String
        let date: String
        let name: String
        let distanceMi: Double
        let timesRun: Int
        var saved: Bool = false
        var ranCount: Int = 0
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(v, forKey: .v)
        try c.encodeIfPresent(text, forKey: .text)
        try c.encodeIfPresent(answer, forKey: .answer)
        try c.encodeIfPresent(constraints, forKey: .constraints)
        try c.encodeIfPresent(routeId, forKey: .routeId)
        try c.encodeIfPresent(mode, forKey: .mode)
        try c.encodeIfPresent(shape, forKey: .shape)
        try c.encode(client, forKey: .client)
        try c.encode(profile, forKey: .profile)
        try c.encode(recentRoutes, forKey: .recentRoutes)
    }
    private enum CodingKeys: String, CodingKey { case v, text, answer, constraints, routeId, mode, shape, client, profile, recentRoutes }

    static func client(location: Location?, now: Date = Date()) -> Client {
        let f = ISO8601DateFormatter()
        f.timeZone = .current
        return Client(now: f.string(from: now), tz: TimeZone.current.identifier, location: location)
    }

    static func recents(_ store: [RecentRoute]) -> [Recent] {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return store.prefix(10).map {
            Recent(id: $0.id, date: f.string(from: $0.date), name: $0.name, distanceMi: $0.distanceMi, timesRun: $0.timesRun)
        }
    }
}

// MARK: Events

/// One server-sent event. Unknown events (a newer server's) decode to `.other` and are ignored.
enum ServerEvent {
    case parsed(Parsed)
    case candidates(Candidates)
    case top3(Routes)
    case provisional(Routes)
    /// The decoded event, and its JSON as sent (kept in RouteArchive for drawing the route again).
    case final(Final, raw: Data)
    case question(Question)
    case planned
    case done
    case error(code: String, text: String)
    /// `error` with code out_of_area: a question for the runner, not a failure (decision 056).
    case outOfArea(OutOfArea)
    case other

    static func decode(_ data: Data) -> ServerEvent {
        let d = LoopAPI.decoder
        guard let kind = try? d.decode(Kind.self, from: data) else { return .other }
        switch kind.event {
        case "parsed":
            guard var p = try? d.decode(Parsed.self, from: data) else { return .other }
            // Constraints keep their own keys (a plain decoder): they go back as sent, with edits.
            p.constraints = (try? JSONDecoder().decode(ConstraintsBox.self, from: data))?.constraints
            return .parsed(p)
        case "candidates": return (try? d.decode(Candidates.self, from: data)).map(ServerEvent.candidates) ?? .other
        case "top3": return (try? d.decode(Routes.self, from: data)).map(ServerEvent.top3) ?? .other
        case "provisional": return (try? d.decode(Routes.self, from: data)).map(ServerEvent.provisional) ?? .other
        case "final":
            do { return .final(try d.decode(Final.self, from: data), raw: data) } catch { return .error(code: "bad_final", text: "") }
        case "question": return (try? d.decode(Question.self, from: data)).map(ServerEvent.question) ?? .other
        case "planned": return .planned
        case "done": return .done
        case "error":
            let e = try? d.decode(ErrorEvent.self, from: data)
            if e?.code == "out_of_area" { return .outOfArea(OutOfArea(place: e?.place, covers: e?.covers)) }
            return .error(code: e?.code ?? "engine_unavailable", text: e?.text ?? "")
        default: return .other
        }
    }

    private struct Kind: Decodable { let event: String }
    private struct ConstraintsBox: Decodable { let constraints: JSONValue? }
    private struct ErrorEvent: Decodable { let code: String; let text: String?; let place: String?; let covers: String? }

    struct Span: Decodable, Equatable {
        let text: String
        /// Unicode scalar positions in the request text, end exclusive.
        let start: Int
        let end: Int
    }

    struct Chip: Decodable, Equatable {
        let id: String
        let field: String
        let text: String
        let source: String
        let editable: Bool?
        let span: Span?
    }

    struct Cant: Decodable, Equatable { let id: String?; let gap: String; let text: String }
    struct Note: Decodable, Equatable { let id: String?; let key: String; let text: String; let trust: String? }

    struct Option: Decodable, Equatable { let id: String; let text: String }

    struct Question: Decodable, Equatable {
        /// Engine questions carry their own parse_id; a parsed question uses the parsed event's.
        let parseId: String?
        let id: String
        let about: String?
        let from: String?
        let text: String
        let options: [Option]
        let allowText: Bool
        let chipId: String?
    }

    struct Parsed: Decodable {
        let parseId: String
        let chips: [Chip]
        let question: Question?
        let cant: [Cant]
        let notes: [Note]
        let reachM: Double?
        /// The RunConstraints this parse produced, for chip edits (decoded separately, keys as sent).
        var constraints: JSONValue? = nil

        private enum CodingKeys: String, CodingKey { case parseId, chips, question, cant, notes, reachM }
    }

    struct Outline: Decodable { let id: String; let kind: String?; let points: [[Double]] }
    struct Candidates: Decodable { let candidates: [Outline] }

    /// A route in `top3`, `provisional` and `final.routes`: the fixture's top3 entry plus `id`.
    struct Routes: Decodable {
        let routeId: String?
        let routes: [RouteFile.TopCandidate]
    }

    struct FinalNote: Decodable { let key: String?; let text: String; let trust: String? }

    struct Final: Decodable {
        let routeId: String?
        let routes: [RouteFile.TopCandidate]
        let route: RouteFile.FeatureCollection?
        let pool: RouteFile.Pool?
        let poolSize: Int?
        let notes: [FinalNote]?
        /// The route type asked for and whether it was found (decision 049). Absent from older servers.
        let shape: Shape?
    }

    struct Shape: Decodable, Equatable {
        let requested: String
        let met: Bool
        let shown: [String]
    }
}
