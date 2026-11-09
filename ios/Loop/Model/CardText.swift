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

    /// The mode first; at the final the count joins it: "TRAINING · BEST OF 31" (UI chat, 2026-11-08).
    static func eyebrow(kind: String, bestOf: Int?) -> String {
        guard let n = bestOf else { return kind }
        return kind.isEmpty ? "BEST OF \(n)" : "\(kind) · BEST OF \(n)"
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
        var source: String? = nil
        /// As shown: "≈ 8 m" for an estimate, the bare value when measured.
        var shown: String { CardText.approx(value, trust) }
    }

    static func stats(_ s: RouteFile.Summary) -> [Stat] {
        [
            Stat(value: oneDecimal(s.lightsPerMile.value), label: "lights a mile", trust: Trust(s.lightsPerMile.status), source: s.lightsPerMile.source),
            Stat(value: "\(Int(s.waterfrontPct.value.rounded()))%", label: "waterfront", trust: Trust(s.waterfrontPct.status), source: s.waterfrontPct.source),
            Stat(value: "\(trimmed(s.climb.value)) m", label: "climb", trust: Trust(s.climb.status), source: s.climb.source),
        ]
    }

    /// Trust words are hidden by default: estimates get "≈ " before the number, measured values nothing.
    static func approx(_ value: String, _ trust: Trust?) -> String {
        trust?.isEstimate == true ? "≈ " + value : value
    }

    /// One sentence, only when a stretch is moderate or busy at the start time: "Busier on E 31st St
    /// around 7." Names the busiest band present (busy, else moderate), longest first, at most two.
    /// nil when every scored stretch is quiet or nothing is scored: then the sheet shows no line.
    static func crowdSentence(_ d: RouteDetail, startTime: String) -> String? {
        for band in ["high", "medium"] {
            let hits = d.stretches.filter { $0.crowd == band }
            guard !hits.isEmpty else { continue }
            var total: [String: Double] = [:]
            var order: [String] = []
            for s in hits {
                let n = shortName(s.name)
                if total[n] == nil { order.append(n) }
                total[n, default: 0] += s.lengthM
            }
            let names = order.sorted { total[$0]! > total[$1]! }.prefix(2).joined(separator: " and ")
            return "Busier on \(names) around \(hourText(startTime))."
        }
        return nil
    }

    /// "7:00" → "7", "7:30" → "7:30".
    static func hourText(_ t: String) -> String { t.hasSuffix(":00") ? String(t.dropLast(3)) : t }

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
            startHourText: "\(hour):\(pad(minute))",
            mode: mode)
    }

    // MARK: Formatting helpers

    static func oneDecimal(_ v: Double) -> String { String(format: "%.1f", v) }
    /// "3.0 mi" (landing tiles).
    static func miles(_ v: Double) -> String { oneDecimal(v) + " mi" }

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
