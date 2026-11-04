import Foundation

/// Every sentence and label the card builds from the file, in one place so wording is easy to change.
/// Rule 1: no numbers are made up here. Each value comes from the file and is only formatted.
enum CardText {

    // MARK: Reason sentence

    /// "About half by the water: 3.6 lights a mile."
    /// The waterfront band is chosen on the whole-number percent the card shows, so the
    /// sentence and the stat never disagree (59.6% shows as 60% and reads "Mostly by the water").
    /// `lightsPerMile` is the every-crossing value (`summary.lights_per_mile`), not the ranking's.
    static func reason(waterfrontPct: Double, lightsPerMile: Double) -> String {
        let shown = Int(waterfrontPct.rounded())
        let lead: String
        switch shown {
        case 60...: lead = "Mostly by the water"
        case 40..<60: lead = "About half by the water"
        default: lead = "Mostly on streets"
        }
        return "\(lead): \(oneDecimal(lightsPerMile)) lights a mile."
    }

    static func reason(_ s: RouteFile.Summary) -> String {
        reason(waterfrontPct: s.waterfrontPct.value, lightsPerMile: s.lightsPerMile.value)
    }

    // MARK: Eyebrow

    /// Before the final top 3 arrives, only the route kind; after, "BEST OF 31 · OUT AND BACK".
    static func eyebrow(kind: String, bestOf: Int?) -> String {
        guard let n = bestOf else { return kind }
        return "BEST OF \(n) · \(kind)"
    }

    static func kindText(_ kind: String) -> String {
        switch kind {
        case "out_and_back": return "OUT AND BACK"
        case "loop": return "LOOP"
        default: return kind.replacingOccurrences(of: "_", with: " ").uppercased()
        }
    }

    // MARK: Stats (whole route)

    struct Stat: Equatable {
        let value: String
        let label: String
        let trust: Trust
    }

    static func stats(_ s: RouteFile.Summary) -> [Stat] {
        [
            Stat(value: oneDecimal(s.lightsPerMile.value), label: "lights a mile", trust: Trust(s.lightsPerMile.status)),
            Stat(value: "\(Int(s.waterfrontPct.value.rounded()))%", label: "waterfront", trust: Trust(s.waterfrontPct.status)),
            Stat(value: "\(trimmed(s.climb.value)) m", label: "climb", trust: Trust(s.climb.status)),
        ]
    }

    /// "Crowds at 7:00 · moderate on E 31st St · esplanade and FDR not scored · estimate"
    /// Names stretches, not percentages. Only the busiest band present is named (high "busy",
    /// medium "moderate", low "quiet"), then the stretches with no crowd data by bare name,
    /// longest first, at most two names per part. Out-and-back repeats of a street count once.
    static func crowdLine(_ d: RouteDetail, startTime: String) -> String {
        func names(_ stretches: [Stretch], bare: Bool = false) -> [String] {
            var total: [String: Double] = [:]
            var order: [String] = []
            for s in stretches {
                let n = bare ? bareName(s.name) : shortName(s.name)
                if total[n] == nil { order.append(n) }
                total[n, default: 0] += s.lengthM
            }
            return order.sorted { total[$0]! > total[$1]! }
        }
        func list(_ n: [String]) -> String {
            let shown = Array(n.prefix(2))
            let rest = n.count - shown.count
            let joined = shown.joined(separator: " and ")
            return rest > 0 ? "\(joined) and \(rest) more" : joined
        }
        var parts = ["Crowds at \(startTime)"]
        let scored = d.stretches.filter { $0.crowd != nil }
        for (band, word) in [("high", "busy"), ("medium", "moderate"), ("low", "quiet")] {
            let hits = scored.filter { $0.crowd == band }
            if !hits.isEmpty { parts.append("\(word) on \(list(names(hits)))"); break }
        }
        let unscored = d.stretches.filter { $0.crowd == nil }
        if !unscored.isEmpty { parts.append("\(list(names(unscored, bare: true))) not scored") }
        parts.append(Trust(d.summary.crowds.status).text)
        return parts.joined(separator: " · ")
    }

    /// Breaks a " · " line into lines of at most `maxChars`, only at the separators.
    static func wrapAtSeparators(_ line: String, maxChars: Int) -> [String] {
        var lines: [String] = []
        var current = ""
        for part in line.components(separatedBy: " · ") {
            let candidate = current.isEmpty ? part : current + " · " + part
            if candidate.count <= maxChars || current.isEmpty { current = candidate }
            else { lines.append(current); current = part }
        }
        if !current.isEmpty { lines.append(current) }
        return lines
    }

    /// The shortest recognisable name: "East River Esplanade" → "esplanade", "FDR Drive" → "FDR",
    /// "East 31st Street" → "E 31st".
    static func bareName(_ name: String) -> String {
        var words = shortName(name).split(separator: " ").map(String.init)
        if words.first == "the" { words.removeFirst() }
        let suffixes: Set = ["St", "Ave", "Dr", "Blvd", "Pl", "Rd", "Pkwy"]
        if words.count > 1, let last = words.last, suffixes.contains(last) { words.removeLast() }
        return words.joined(separator: " ")
    }

    /// Short street names for data lines: "East 31st Street" → "E 31st St", "FDR Drive" → "FDR Dr",
    /// "East River Esplanade" → "the esplanade".
    static func shortName(_ name: String) -> String {
        var words = name.split(separator: " ").map(String.init)
        guard let last = words.last else { return name }
        let features = ["Esplanade", "Greenway", "Promenade", "Park", "Pier", "Path", "Bridge", "Bikeway"]
        if features.contains(last) { return "the \(last.lowercased())" }
        let suffix = ["Street": "St", "Avenue": "Ave", "Drive": "Dr", "Boulevard": "Blvd",
                      "Place": "Pl", "Road": "Rd", "Parkway": "Pkwy"]
        if let short = suffix[last] { words[words.count - 1] = short }
        let compass = ["East": "E", "West": "W", "North": "N", "South": "S"]
        if words.count >= 2, let c = compass[words[0]], words[1].first?.isNumber == true { words[0] = c }
        return words.joined(separator: " ")
    }

    static func distance(_ mi: Double) -> String { String(format: "%.2f", mi) }

    // MARK: Selection chip

    /// The selection chip: "East River Esplanade · 1.0 mi · Look around", or without the last
    /// part where Apple has no Look Around scene.
    static func selectionChip(stretchName: String, alongMi: Double, lookAround: Bool) -> String {
        let base = "\(stretchName) · \(oneDecimal(alongMi)) mi"
        return lookAround ? base + " · Look around" : base
    }

    // MARK: Request

    /// Builds the request line and its provenance from the file's request items.
    /// "3 miles from the Kips Bay Library at 7 am." / "3 mi · 7:00 am you said · Training preset"
    static func request(items: [RouteFile.RequestItem], about: RouteFile.About) -> RequestCard {
        func value(_ key: String) -> String? { items.first { $0.key == key }?.value }
        let distance = value("distance") ?? ""
        let miles = distance.replacingOccurrences(of: " mi", with: "")
        let milesWord = miles == "1" ? "1 mile" : "\(miles) miles"
        // "Kips Bay Library, a public stand-in ..." → "Kips Bay Library"
        let place = about.start.split(separator: ",").first.map(String.init) ?? "the start"
        let (hour, minute) = parseClock(value("start_time") ?? "")
        let shortTime = minute == 0 ? "\(hour12(hour)) \(ampm(hour))" : "\(hour12(hour)):\(pad(minute)) \(ampm(hour))"
        let fullTime = "\(hour12(hour)):\(pad(minute)) \(ampm(hour))"
        let mode = value("mode") ?? ""
        return RequestCard(
            text: "\(milesWord) from the \(place) at \(shortTime).",
            provenance: "\(distance) · \(fullTime) you said · \(mode) preset",
            startHourText: "\(hour):\(pad(minute))")
    }

    // MARK: Formatting helpers

    static func oneDecimal(_ v: Double) -> String { String(format: "%.1f", v) }

    /// 8.0 → "8", 8.5 → "8.5"
    static func trimmed(_ v: Double) -> String {
        v.rounded() == v ? String(Int(v)) : String(format: "%.1f", v)
    }

    private static func parseClock(_ s: String) -> (Int, Int) {
        // "07:00 (hour 7; sets the crowd band)"
        let head = s.prefix(5).split(separator: ":")
        guard head.count == 2, let h = Int(head[0]), let m = Int(head[1]) else { return (0, 0) }
        return (h, m)
    }
    private static func hour12(_ h: Int) -> Int { h % 12 == 0 ? 12 : h % 12 }
    private static func ampm(_ h: Int) -> String { h < 12 ? "am" : "pm" }
    private static func pad(_ m: Int) -> String { m < 10 ? "0\(m)" : "\(m)" }
}
