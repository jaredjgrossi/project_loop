import Foundation

/// Routes kept on the phone so a saved route or a run can be drawn again with its card, offline:
/// the server's `final` payload as it came (about 60–200 KB a route), one file per route in
/// Application Support/routes. The bundled Kips Bay file is the key "fixture".
enum RouteArchive {
    static let fixture = "fixture"

    static var directory: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("routes", isDirectory: true)
    }

    private static func url(_ key: String) -> URL {
        let safe = key.map { $0.isLetter || $0.isNumber || $0 == "_" || $0 == "-" || $0 == "." ? $0 : "_" }
        return directory.appendingPathComponent(String(safe) + ".json")
    }

    /// Keeps a live build's `final` event JSON under the route's key.
    static func save(key: String, finalJSON: Data) {
        guard key != fixture else { return }
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? finalJSON.write(to: url(key), options: .atomic)
    }

    static func has(_ key: String) -> Bool {
        key == fixture || FileManager.default.fileExists(atPath: url(key).path)
    }

    /// The route file for a key: the bundled one, or one rebuilt from a kept `final`.
    static func load(_ key: String, start: String) -> RouteFile? {
        if key == fixture { return try? RouteFile.loadBundled() }
        guard let data = try? Data(contentsOf: url(key)),
              let final = try? LoopAPI.decoder.decode(ServerEvent.Final.self, from: data) else { return nil }
        return RouteFile.from(final: final, start: start)
    }
}

extension RouteFile {
    /// A route file from a `final` event: the #1 in full, the top 3, the pool, and the request the
    /// engine read (`about` is made on the phone).
    static func from(final f: ServerEvent.Final, start: String) -> RouteFile? {
        guard let route = f.route, let first = route.features.first else { return nil }
        return RouteFile(about: .init(generatedAt: ISO8601DateFormatter().string(from: Date()), start: start),
                         request: first.properties.request ?? [],
                         route: route, top3: f.routes,
                         pool: f.pool ?? .init(candidates: f.poolSize ?? 0, bestOf: f.poolSize ?? 0))
    }
}

/// Loop's name for a route, from its longest stretch and its kind: "East River out-and-back",
/// "E 31st St loop". The runner can rename a saved route.
enum RouteNaming {
    /// Words that name what a place is, not which one: dropped so the place reads short.
    private static let generic: Set<String> = ["Esplanade", "Greenway", "Promenade", "Walk", "Path", "Bikeway", "Drive"]

    static func name(_ d: RouteDetail) -> String {
        var total: [String: Double] = [:]
        for s in d.stretches { total[s.name, default: 0] += s.lengthM }
        let longest = total.max { $0.value < $1.value }?.key ?? ""
        return [place(longest), kindWord(d.summary.kind)].filter { !$0.isEmpty }.joined(separator: " ")
    }

    static func place(_ stretch: String) -> String {
        var words = stretch.split(separator: " ").map(String.init)
        if words.count > 1, let last = words.last, generic.contains(last) {
            words.removeLast()
            return words.joined(separator: " ")
        }
        return CardText.shortName(stretch).replacingOccurrences(of: "the ", with: "")
    }

    static func kindWord(_ kind: String) -> String {
        switch kind {
        case "out_and_back": return "out-and-back"
        case "loop", "lollipop": return "loop"
        case "a_to_b": return "run"
        default: return "route"
        }
    }
}
