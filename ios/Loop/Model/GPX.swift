import Foundation

/// A route as a GPX 1.1 file: the track, with the mile marks and the turnaround as waypoints so they
/// show on a watch. Same shape as the server's `api/gpx.py`. Built on the phone from the route the
/// card shows, so it works with no server and nothing leaves the phone until the runner picks a place
/// in the share sheet.
enum GPX {
    struct Waypoint: Equatable {
        let point: GeoPoint
        let name: String
    }

    static func make(name: String, track: [GeoPoint], waypoints: [Waypoint]) -> String {
        let wpts = waypoints.map {
            "  <wpt lat=\"\(coordinate($0.point.lat))\" lon=\"\(coordinate($0.point.lon))\"><name>\(escape($0.name))</name></wpt>\n"
        }.joined()
        let trkpts = track.map {
            "      <trkpt lat=\"\(coordinate($0.lat))\" lon=\"\(coordinate($0.lon))\"></trkpt>\n"
        }.joined()
        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            + "<gpx version=\"1.1\" creator=\"Loop\" xmlns=\"http://www.topografix.com/GPX/1/1\">\n"
            + "  <metadata><name>\(escape(name))</name></metadata>\n\(wpts)"
            + "  <trk><name>\(escape(name))</name><trkseg>\n\(trkpts)    </trkseg></trk>\n</gpx>\n"
    }

    /// The card's route: the line, "Mile n" at each whole mile and "Turnaround" where it reverses
    /// (only for the route that carries its details; the other two have just a line).
    static func make(name: String, candidate: Candidate) -> String {
        var waypoints: [Waypoint] = []
        if let d = candidate.detail {
            waypoints = d.miles.map { Waypoint(point: $0.point, name: "Mile \($0.mile)") }
            if let t = d.turnaround { waypoints.append(Waypoint(point: t.point, name: "Turnaround")) }
        }
        return make(name: name, track: candidate.line.points, waypoints: waypoints)
    }

    /// Writes the file to the temporary folder under a safe name ("Loop - East River loop.gpx").
    static func write(_ gpx: String, name: String) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(fileName(name))
        try gpx.write(to: url, atomically: true, encoding: .utf8)
        return url
    }

    static func fileName(_ name: String) -> String {
        let bad = CharacterSet(charactersIn: "/\\:*?\"<>|").union(.controlCharacters)
        let clean = name.components(separatedBy: bad).joined(separator: " ")
            .split(separator: " ").joined(separator: " ")
        return "Loop - \(clean.isEmpty ? "route" : String(clean.prefix(60))).gpx"
    }

    private static func coordinate(_ v: Double) -> String { String(format: "%.7f", v) }

    static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
    }
}
