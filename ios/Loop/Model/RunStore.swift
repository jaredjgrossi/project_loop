import Foundation
import Observation

/// A route the runner saved (the bookmark): a tile in Your runs and on "You". Lives on the phone.
struct SavedRun: Codable, Identifiable, Equatable {
    var id: String
    /// The runner's name for it; it starts as Loop's ("East River out-and-back").
    var name: String
    /// The request that built it.
    var request: String
    var distanceMi: Double
    /// The route's shape for the thumbnail, [lon, lat] pairs, simplified. Never sent anywhere.
    var shape: [[Double]]
    var savedAt: Date
    /// The server's id for the route (`r_xxxxxxxx.N`), for "Run again" and `recent_routes`.
    var routeId: String? = nil
    /// Where the route itself is kept on the phone (RouteArchive), to draw it again offline.
    var archive: String? = nil

    var identity: RouteIdentity {
        RouteIdentity(routeId: routeId, archive: archive, name: name, request: request, distanceMi: distanceMi,
                      shape: shape, stretches: [], startTime: nil)
    }
}

/// What a route is, wherever it's shown: what Save, "I ran it" and the return prompt keep.
struct RouteIdentity: Codable, Equatable {
    var routeId: String?
    var archive: String?
    var name: String
    var request: String
    var distanceMi: Double
    var shape: [[Double]]
    /// Its stretches' names, for "Most run".
    var stretches: [String]
    /// The planned start ("07:00"), for "usual start".
    var startTime: String?

    /// The key that ties saves, runs and prompts to one route.
    var key: String { routeId ?? archive ?? request }
}

/// "How was it?": good, or not for me with any reasons (keys, never wording) and a note.
struct RunRating: Codable, Equatable {
    enum Verdict: String, Codable { case good, notForMe = "not_for_me" }
    var verdict: Verdict
    var reasons: [String] = []
    var note: String? = nil

    /// The reason pills, in order: key and wording (copy for the UI chat to word).
    static let reasonPills: [(key: String, text: String)] = [
        ("crowded", "Too crowded"), ("lights", "Too many lights"), ("water", "Not enough water"),
        ("safety", "Didn't feel safe"), ("other", "Something else"),
    ]
}

/// A route marked as run ("I ran it"), with its rating when given.
struct RunLog: Codable, Identifiable, Equatable {
    var id: String
    var route: RouteIdentity
    var ranAt: Date
    var rating: RunRating?
}

/// A route the runner looked at or shared: the return prompt asks about it next time.
struct ViewedRoute: Codable, Equatable {
    var route: RouteIdentity
    var at: Date
    /// Asked once; never again for this route.
    var prompted = false
}

/// The runner's defaults ("You" -> Your defaults), sent as the request's `profile`.
struct RunnerProfile: Codable, Equatable {
    var usualDistanceMi: Double = 3
    /// "HH:MM", local.
    var usualTime: String = "07:00"
    var usualShape: String = UsualShape.any.rawValue
    var home: Home?

    struct Home: Codable, Equatable {
        var label: String
        var lat: Double
        var lon: Double
    }
}

/// A route the runner built recently: the contract's `recent_routes` item (id, date, name,
/// distance_mi, times_run; parse-contract-v1), plus two fields that stay on the phone: the request
/// text the row shows and the thumbnail shape.
struct RecentRoute: Codable, Identifiable, Equatable {
    var id: String
    var date: Date
    var name: String
    var distanceMi: Double
    var timesRun: Int
    var request: String
    var shape: [[Double]]
}

/// A tile shown until the runner has runs of their own. There's no route yet, so it shows a small
/// glyph in route style (never a fake route), and tapping it sends the request.
struct SuggestedRun: Identifiable, Equatable {
    enum Glyph: Equatable {
        /// A small loop returning to the start dot.
        case loop
        /// A line running along a wavy shoreline.
        case water
    }
    let id: String
    let name: String
    let request: String
    let glyph: Glyph
}

/// A row under the landing field while typing: a recent request or a saved run.
struct RunMatch: Identifiable, Equatable {
    let id: String
    /// What the row shows and what typing matches: a recent's request, a saved run's name.
    let title: String
    /// What tapping the row sends.
    let request: String
    let date: Date
    let shape: [[Double]]
}

/// Saved routes, runs with ratings, recent requests and the profile, kept in one small JSON file in
/// Application Support (no account); route geometry in RouteArchive files beside it.
@Observable
@MainActor
final class RunStore {
    private(set) var saved: [SavedRun]
    private(set) var recents: [RecentRoute]
    /// Routes marked as run, newest first.
    private(set) var runs: [RunLog] = []
    var profile = RunnerProfile() { didSet { if profile != oldValue { write() } } }
    private(set) var viewed: [ViewedRoute] = []
    /// A random id per install (decision 043: X-Loop-Install), never a name.
    private(set) var installId = UUID().uuidString
    /// nil keeps everything in memory (the debug new-user state never touches the real file).
    @ObservationIgnored private let fileURL: URL?

    static let maxRecents = 20

    /// Suggestions for the tiles after the runner's own runs (the UI chat's examples).
    static let suggestions = [
        SuggestedRun(id: "s_here", name: "3 mi from here", request: "3 miles from here", glyph: .loop),
        SuggestedRun(id: "s_water", name: "By the water", request: "3 miles by the water", glyph: .water),
    ]

    /// Starts inside the covered area, for when "from here" can't work (the phone has heard out_of_area).
    static let coveredSuggestions = [
        SuggestedRun(id: "s_bryant", name: "3 mi from Bryant Park", request: "3 miles from Bryant Park", glyph: .loop),
        SuggestedRun(id: "s_kipsbay", name: "Kips Bay by the water", request: "3 miles by the water from Kips Bay", glyph: .water),
    ]

    private struct File: Codable {
        var saved: [SavedRun]
        var recents: [RecentRoute]
        var runs: [RunLog]?
        var profile: RunnerProfile?
        var viewed: [ViewedRoute]?
        var installId: String?
    }

    init(saved: [SavedRun] = [], recents: [RecentRoute] = [], fileURL: URL? = nil) {
        self.saved = saved
        self.recents = recents
        self.fileURL = fileURL
    }

    /// The tiles: the runner's runs, then suggestions, three in all (the Save tile is the fourth).
    var suggestedTiles: [SuggestedRun] { suggestedTiles(outsideCoverage: false) }

    /// Outside coverage the examples name their start, in the covered area.
    func suggestedTiles(outsideCoverage: Bool) -> [SuggestedRun] {
        Array((outsideCoverage ? Self.coveredSuggestions : Self.suggestions).prefix(max(0, 3 - saved.count)))
    }

    nonisolated static var defaultURL: URL {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return dir.appendingPathComponent("runs.json")
    }

    /// Reads the file. A first launch seeds "Usual" (and one recent) from the saved route file,
    /// until runs can be saved from a card.
    static func load(data: LoopData, url: URL = defaultURL, now: Date = Date()) -> RunStore {
        if let bytes = try? Data(contentsOf: url),
           let file = try? JSONDecoder.runs.decode(File.self, from: bytes) {
            let store = RunStore(saved: file.saved, recents: file.recents, fileURL: url)
            // Stores from before come back: the seeded "Usual" is the bundled route.
            for i in store.saved.indices where store.saved[i].id == "usual" && store.saved[i].archive == nil {
                store.saved[i].archive = RouteArchive.fixture
            }
            store.runs = file.runs ?? []
            store.viewed = file.viewed ?? []
            if let p = file.profile {
                store.profile = p
            } else {
                store.profile.usualShape = UsualShape.legacy?.rawValue ?? UsualShape.any.rawValue
            }
            if let id = file.installId { store.installId = id } else { store.write() }
            return store
        }
        let store = RunStore(fileURL: url)
        store.seed(from: data, now: now)
        return store
    }

    /// "Usual" and one recent from the fixture's #1.
    func seed(from data: LoopData, now: Date) {
        guard let first = data.candidate(rank: 1) else { return }
        let shape = Self.shape(of: first.line)
        let request = data.request.text
        saved = [SavedRun(id: "usual", name: "Usual", request: request, distanceMi: first.distanceMi,
                          shape: shape, savedAt: now, archive: RouteArchive.fixture)]
        recents = [RecentRoute(id: "rt_seed", date: now, name: request, distanceMi: first.distanceMi,
                               timesRun: 1, request: request, shape: shape)]
        write()
    }

    /// Recent requests and saved runs whose title contains the typed text (any case), newest
    /// first, at most `limit`. With nothing typed, the most recent. A route shows once: one that
    /// was saved and run (or run several times) is one row, with its newest date.
    func matches(_ typed: String, limit: Int = 4) -> [RunMatch] {
        // (row, the route it stands for). Recent requests are sentences, not routes: never merged.
        var rows: [(match: RunMatch, route: String?)] = recents.map {
            (RunMatch(id: "r_" + $0.id, title: Self.sentence($0.request), request: $0.request, date: $0.date, shape: $0.shape), nil)
        }
        rows += saved.map {
            (RunMatch(id: "s_" + $0.id, title: $0.name, request: $0.request, date: $0.savedAt, shape: $0.shape),
             Self.routeTag($0.identity))
        }
        rows += runs.map {
            (RunMatch(id: "n_" + $0.id, title: $0.route.name, request: $0.route.request, date: $0.ranAt, shape: $0.route.shape),
             Self.routeTag($0.route))
        }
        var seen = Set<String>()
        let all = rows.sorted { $0.match.date > $1.match.date }.filter { row in
            guard let route = row.route else { return true }
            return seen.insert(route).inserted
        }.map(\.match)
        let q = typed.trimmingCharacters(in: .whitespaces)
        let hits = q.isEmpty ? all : all.filter { $0.title.localizedCaseInsensitiveContains(q) }
        return Array(hits.prefix(limit))
    }

    /// What makes two rows the same route: the server's id or the archive when there is one;
    /// otherwise the request and the name together (one request can build different routes).
    private static func routeTag(_ r: RouteIdentity) -> String {
        r.routeId ?? r.archive ?? (r.request + "|" + r.name.lowercased())
    }

    /// A request as the runner typed it, without the full stop the header adds.
    static func sentence(_ s: String) -> String { s.hasSuffix(".") ? String(s.dropLast()) : s }

    /// A request that built a route goes to the top of Recent (the same request again moves up).
    /// `countsAsRun` false (dismissing a card) moves it up without counting another run.
    func addRecent(request: String, distanceMi: Double, line: Polyline, countsAsRun: Bool = true,
                   serverId: String? = nil, now: Date = Date()) {
        let text = request.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = Self.key(text)
        var times = 1
        if let i = recents.firstIndex(where: { Self.key($0.request) == key }) {
            times = recents[i].timesRun + (countsAsRun ? 1 : 0)
            recents.remove(at: i)
        }
        // A live build's route keeps the server's id, so "that route again" can find it (step 11).
        let item = RecentRoute(id: serverId ?? "rt_\(Int(now.timeIntervalSince1970))", date: now, name: text,
                               distanceMi: distanceMi, timesRun: times, request: text, shape: Self.shape(of: line))
        recents.insert(item, at: 0)
        if recents.count > Self.maxRecents { recents.removeLast(recents.count - Self.maxRecents) }
        write()
    }

    private static func key(_ s: String) -> String {
        s.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: " ."))
    }

    private func write() {
        guard let fileURL else { return }
        try? FileManager.default.createDirectory(at: fileURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let file = File(saved: saved, recents: recents, runs: runs, profile: profile, viewed: viewed, installId: installId)
        if let bytes = try? JSONEncoder.runs.encode(file) {
            try? bytes.write(to: fileURL, options: .atomic)
        }
    }

    // MARK: Saved routes

    private func same(_ s: SavedRun, _ r: RouteIdentity) -> Bool {
        if let a = s.routeId, let b = r.routeId { return a == b }
        if let a = s.archive, let b = r.archive { return a == b }
        return false
    }

    func isSaved(_ r: RouteIdentity) -> Bool { saved.contains { same($0, r) } }

    func save(_ r: RouteIdentity, now: Date = Date()) {
        guard !isSaved(r) else { return }
        saved.insert(SavedRun(id: "sv_\(UUID().uuidString.prefix(8))", name: r.name, request: r.request, distanceMi: r.distanceMi,
                              shape: r.shape, savedAt: now, routeId: r.routeId, archive: r.archive), at: 0)
        write()
    }

    func unsave(_ r: RouteIdentity) {
        saved.removeAll { same($0, r) }
        write()
    }

    func rename(_ id: String, to name: String) {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty, let i = saved.firstIndex(where: { $0.id == id }) else { return }
        saved[i].name = clean
        write()
    }

    func remove(_ id: String) {
        saved.removeAll { $0.id == id }
        write()
    }

    // MARK: Runs and ratings

    /// "I ran it": the run is marked at once; the rating can follow, now or later.
    @discardableResult
    func markRun(_ r: RouteIdentity, at: Date = Date()) -> RunLog {
        let log = RunLog(id: "run_\(UUID().uuidString.prefix(10))", route: r, ranAt: at, rating: nil)
        runs.insert(log, at: 0)
        if let i = viewed.firstIndex(where: { $0.route.key == r.key }) { viewed[i].prompted = true }
        write()
        return log
    }

    func rate(_ runId: String, _ rating: RunRating?) {
        guard let i = runs.firstIndex(where: { $0.id == runId }) else { return }
        runs[i].rating = rating
        write()
    }

    // MARK: The return prompt

    /// A route was viewed or shared.
    func noteViewed(_ r: RouteIdentity, at: Date = Date()) {
        viewed.removeAll { $0.route.key == r.key }
        viewed.insert(ViewedRoute(route: r, at: at), at: 0)
        if viewed.count > 10 { viewed.removeLast(viewed.count - 10) }
        write()
    }

    /// At launch: the latest route viewed before this open, within 24 h, not marked as run and not
    /// asked about yet. Asked once.
    func returnPrompt(openedAt: Date = Date()) -> ViewedRoute? {
        viewed.first { v in
            !v.prompted && v.at < openedAt && openedAt.timeIntervalSince(v.at) < 24 * 3600
                && !runs.contains { $0.route.key == v.route.key && $0.ranAt >= v.at }
        }
    }

    func markPrompted(_ v: ViewedRoute) {
        guard let i = viewed.firstIndex(where: { $0.route.key == v.route.key }) else { return }
        viewed[i].prompted = true
        write()
    }

    /// The contract's `recent_routes`: saved routes (with the runner's names) and runs, by route,
    /// newest first, with how often each was run.
    var recentRoutesPayload: [RunRequest.Recent] {
        var byKey: [String: RunRequest.Recent] = [:]
        var order: [String] = []
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        for run in runs {
            let k = run.route.key
            guard byKey[k] == nil else { continue }
            let count = runs.filter { $0.route.key == k }.count
            order.append(k)
            byKey[k] = RunRequest.Recent(id: run.route.routeId ?? k, date: f.string(from: run.ranAt), name: run.route.name,
                                         distanceMi: run.route.distanceMi, timesRun: count, saved: false, ranCount: count)
        }
        for s in saved {
            let k = s.identity.key
            let count = runs.filter { $0.route.key == k }.count
            if byKey[k] == nil { order.append(k) }
            byKey[k] = RunRequest.Recent(id: s.routeId ?? s.id, date: f.string(from: s.savedAt), name: s.name,
                                         distanceMi: s.distanceMi, timesRun: count, saved: true, ranCount: count)
        }
        return order.prefix(20).compactMap { byKey[$0] }
    }

    /// A thumbnail-sized copy of a route: Douglas–Peucker at 6 m keeps its shape in a few dozen points.
    static func shape(of line: Polyline) -> [[Double]] {
        DisplayLine.simplify(line.points, tolerance: 6).map { [line.points[$0].lon, line.points[$0].lat] }
    }

    /// "Today", "Yesterday", a weekday within the last week ("Sun"), else a date ("Nov 2").
    static func dayText(_ date: Date, now: Date = Date(), calendar: Calendar = .current) -> String {
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: date), to: calendar.startOfDay(for: now)).day ?? 0
        if days <= 0 { return "Today" }
        if days == 1 { return "Yesterday" }
        let f = DateFormatter()
        f.calendar = calendar
        f.locale = Locale(identifier: "en_US")
        f.timeZone = calendar.timeZone
        f.dateFormat = days < 7 ? "EEE" : "MMM d"
        return f.string(from: date)
    }
}

#if DEBUG
extension RunStore {
    /// Debug `-LoopDemoData`: a runner with saved routes, a dozen runs over the last weeks (the bundled
    /// file's routes standing in) and a route viewed this morning, in memory only (the real store on
    /// the phone is never touched). For screenshots of the come-back screens.
    static func demo(data: LoopData, now: Date = Date()) -> RunStore {
        let store = RunStore()
        func identity(_ c: Candidate, name: String, archive: String?) -> RouteIdentity {
            RouteIdentity(routeId: nil, archive: archive, name: name, request: data.request.text, distanceMi: c.distanceMi,
                          shape: shape(of: c.line), stretches: Array(Set(c.detail?.stretches.map(\.name) ?? ["East River Esplanade"])).sorted(),
                          startTime: "07:00")
        }
        guard let first = data.candidate(rank: 1) else { return store }
        let river = identity(first, name: first.detail.map(RouteNaming.name) ?? "East River out-and-back", archive: RouteArchive.fixture)
        let others = data.candidates.filter { $0.rank != 1 }
        let loop = others.last.map { identity($0, name: "Kips Bay loop", archive: nil) } ?? river
        let back = others.first.map { identity($0, name: "Kips Bay out-and-back", archive: nil) } ?? river
        let plan: [(daysAgo: Double, route: RouteIdentity, rating: RunRating?)] = [
            (1.6, river, RunRating(verdict: .good)), (3, loop, RunRating(verdict: .notForMe, reasons: ["crowded"])),
            (6, river, nil), (8, river, RunRating(verdict: .good)), (13, back, nil), (15, river, RunRating(verdict: .good)),
            (20, river, nil), (27, loop, nil), (29, river, RunRating(verdict: .good)), (36, river, nil), (43, back, nil), (50, river, nil),
        ]
        store.runs = plan.map { RunLog(id: "demo_\($0.daysAgo)", route: $0.route, ranAt: now.addingTimeInterval(-$0.daysAgo * 86_400 + 600),
                                       rating: $0.rating) }
        store.saved = [
            SavedRun(id: "sv_river", name: river.name, request: river.request, distanceMi: river.distanceMi, shape: river.shape,
                     savedAt: now, archive: RouteArchive.fixture),
            SavedRun(id: "sv_loop", name: loop.name, request: loop.request, distanceMi: loop.distanceMi, shape: loop.shape, savedAt: now),
        ]
        store.viewed = [ViewedRoute(route: river, at: Calendar.current.startOfDay(for: now).addingTimeInterval(6.5 * 3600) < now
                                    ? Calendar.current.startOfDay(for: now).addingTimeInterval(6.5 * 3600) : now.addingTimeInterval(-3600))]
        store.profile.home = .init(label: "Kips Bay Library", lat: first.detail?.start.lat ?? 40.7439, lon: first.detail?.start.lon ?? -73.9799)
        return store
    }
}
#endif

private extension JSONEncoder {
    static var runs: JSONEncoder { let e = JSONEncoder(); e.dateEncodingStrategy = .iso8601; return e }
}

private extension JSONDecoder {
    static var runs: JSONDecoder { let d = JSONDecoder(); d.dateDecodingStrategy = .iso8601; return d }
}
