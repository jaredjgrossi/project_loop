import Foundation
import Observation

/// A run the runner keeps as a tile on the landing sheet ("Usual"). Lives on the phone only.
struct SavedRun: Codable, Identifiable, Equatable {
    var id: String
    var name: String
    /// The request that builds it.
    var request: String
    var distanceMi: Double
    /// The route's shape for the thumbnail, [lon, lat] pairs, simplified. Never sent anywhere.
    var shape: [[Double]]
    var savedAt: Date
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

/// Saved runs and recent routes, kept in one small JSON file in Application Support (no account).
@Observable
@MainActor
final class RunStore {
    private(set) var saved: [SavedRun]
    private(set) var recents: [RecentRoute]
    /// nil keeps everything in memory (the debug new-user state never touches the real file).
    @ObservationIgnored private let fileURL: URL?

    static let maxRecents = 20

    /// Suggestions for the tiles after the runner's own runs (the UI chat's examples).
    static let suggestions = [
        SuggestedRun(id: "s_here", name: "3 mi from here", request: "3 miles from here", glyph: .loop),
        SuggestedRun(id: "s_water", name: "By the water", request: "3 miles by the water", glyph: .water),
    ]

    private struct File: Codable {
        var saved: [SavedRun]
        var recents: [RecentRoute]
    }

    init(saved: [SavedRun] = [], recents: [RecentRoute] = [], fileURL: URL? = nil) {
        self.saved = saved
        self.recents = recents
        self.fileURL = fileURL
    }

    /// The tiles: the runner's runs, then suggestions, three in all (the Save tile is the fourth).
    var suggestedTiles: [SuggestedRun] {
        Array(Self.suggestions.prefix(max(0, 3 - saved.count)))
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
            return RunStore(saved: file.saved, recents: file.recents, fileURL: url)
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
                          shape: shape, savedAt: now)]
        recents = [RecentRoute(id: "rt_seed", date: now, name: request, distanceMi: first.distanceMi,
                               timesRun: 1, request: request, shape: shape)]
        write()
    }

    /// A request that built a route goes to the top of Recent (the same request again moves up).
    /// `countsAsRun` false (dismissing a card) moves it up without counting another run.
    func addRecent(request: String, distanceMi: Double, line: Polyline, countsAsRun: Bool = true, now: Date = Date()) {
        let text = request.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = Self.key(text)
        var times = 1
        if let i = recents.firstIndex(where: { Self.key($0.request) == key }) {
            times = recents[i].timesRun + (countsAsRun ? 1 : 0)
            recents.remove(at: i)
        }
        let item = RecentRoute(id: "rt_\(Int(now.timeIntervalSince1970))", date: now, name: text,
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
        if let bytes = try? JSONEncoder.runs.encode(File(saved: saved, recents: recents)) {
            try? bytes.write(to: fileURL, options: .atomic)
        }
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

private extension JSONEncoder {
    static var runs: JSONEncoder { let e = JSONEncoder(); e.dateEncodingStrategy = .iso8601; return e }
}

private extension JSONDecoder {
    static var runs: JSONDecoder { let d = JSONDecoder(); d.dateDecodingStrategy = .iso8601; return d }
}
