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

    /// "11 signal crossings · measured" (each time the route crosses, decision 020).
    static func signalsLine(_ s: RouteFile.Summary) -> String {
        let n = Int(s.signalizedCrossings.value.rounded())
        return "\(n) signal crossing\(n == 1 ? "" : "s") · \(Trust(s.signalizedCrossings.status).text)"
    }

    /// "Crowds 7:00 · 5% busy · 58% not scored · estimate"
    static func crowdLine(_ s: RouteFile.Summary, startTime: String) -> String {
        let busy = Int(s.crowds.value.rounded())
        let unscored = Int(s.crowds.notScoredPct.rounded())
        return "Crowds \(startTime) · \(busy)% busy · \(unscored)% not scored · \(Trust(s.crowds.status).text)"
    }

    static func distance(_ mi: Double) -> String { String(format: "%.2f", mi) }

    // MARK: Mile chip

    static func mileChip(mile: Int, stretchName: String) -> String { "Mile \(mile) · \(stretchName)" }

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
