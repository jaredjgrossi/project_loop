import Foundation
import UIKit

/// Every sentence and label the card builds from the file, in one place so wording is easy to change.
/// Rule 1: no numbers are made up here. Each value comes from the file and is only formatted.
enum CardText {

    // MARK: Reason sentence

    /// "About half by the water: 3.6 lights a mile."
    /// The waterfront band is chosen on the whole-number percent the card shows, so the
    /// sentence and the stat never disagree (59.6% shows as 60% and reads "Mostly by the water").
    /// `lightsPerMile` is the every-crossing value (`summary.lights_per_mile`), not the ranking's.
    /// With a number missing (not scored), the sentence says only what it knows; with neither, nil.
    static func reason(waterfrontPct: Double?, lightsPerMile: Double?) -> String? {
        let lead: String? = waterfrontPct.map {
            switch Int($0.rounded()) {
            case 60...: return "Mostly by the water"
            case 40..<60: return "About half by the water"
            default: return "Mostly on streets"
            }
        }
        switch (lead, lightsPerMile) {
        case let (lead?, lights?): return "\(lead): \(oneDecimal(lights)) lights a mile."
        case let (lead?, nil): return "\(lead)."
        case let (nil, lights?): return "\(oneDecimal(lights)) lights a mile."
        case (nil, nil): return nil
        }
    }

    static func reason(_ s: RouteFile.Summary) -> String? {
        reason(waterfrontPct: s.waterfrontPct.value, lightsPerMile: s.lightsPerMile.value)
    }

    /// The card's reason line: the server's own (`summary.reason`, decision 049: the park, the water,
    /// the lights, flat or hilly, from the route's numbers) with a full stop, or, when the server sent
    /// none or has nothing to say, the sentence built here from the waterfront share and the lights.
    static func reasonLine(_ s: RouteFile.Summary) -> String? {
        if let t = s.reason?.text?.trimmingCharacters(in: .whitespaces), !t.isEmpty {
            let sentence = t.prefix(1).uppercased() + t.dropFirst()
            return sentence.hasSuffix(".") ? sentence : sentence + "."
        }
        return reason(s)
    }

    // MARK: Route type not found

    /// One plain line when the route type asked for wasn't found (`final.shape.met` false), else nil.
    /// "No loop from here beats this out-and-back." Never worded as if the runner got what they asked for.
    static func shapeNote(_ shape: ServerEvent.Shape?) -> String? {
        guard let shape, !shape.met, let have = shape.shown.first.map(shapeWord) else { return nil }
        switch shape.requested {
        case "loop": return "No loop from here beats this \(have)."
        case "out_and_back": return "No out-and-back found. This is the best \(have)."
        case "one_way": return "No one-way run found. This is the best \(have)."
        default: return nil
        }
    }

    private static func shapeWord(_ kind: String) -> String {
        switch kind {
        case "loop": return "loop"
        case "out_and_back": return "out-and-back"
        case "lollipop": return "lollipop"
        case "a_to_b": return "one-way run"
        default: return kind.replacingOccurrences(of: "_", with: " ")
        }
    }

    // MARK: Eyebrow

    /// "1 OF 3 · OUT AND BACK · BEST OF 31": the route's place among the routes, its type, and the size of the
    /// pool it won (decision 020's "Best of N", back in the eyebrow 2026-11-17; the mode never). With one route,
    /// or before `final`, no position; with a pool of one, or none yet, no count.
    static func eyebrow(kind: String, position: Int?, of count: Int?, bestOf: Int? = nil) -> String {
        var parts: [String] = []
        if let position, let count, count > 1 { parts.append("\(position) OF \(count)") }
        if !kind.isEmpty { parts.append(kind) }
        if let bestOf, bestOf > 1 { parts.append("BEST OF \(bestOf)") }
        return parts.joined(separator: " · ")
    }

    static func kindText(_ kind: String) -> String {
        switch kind {
        case "out_and_back": return "OUT AND BACK"
        case "loop": return "LOOP"
        case "lollipop": return "LOLLIPOP"
        case "a_to_b", "one_way": return "ONE WAY"
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
        // A value the server couldn't score shows a dash with its "not scored" label, never a zero.
        [
            Stat(value: s.lightsPerMile.value.map(oneDecimal) ?? "–", label: "lights a mile",
                 trust: Trust(s.lightsPerMile.status), source: s.lightsPerMile.source),
            Stat(value: s.waterfrontPct.value.map { "\(Int($0.rounded()))%" } ?? "–", label: "waterfront",
                 trust: Trust(s.waterfrontPct.status), source: s.waterfrontPct.source),
            Stat(value: s.climb.value.map { "\(feet($0)) ft" } ?? "–", label: "climb",
                 trust: Trust(s.climb.status), source: s.climb.source),
        ]
    }

    /// Trust words are hidden by default: estimates get "≈ " before the number, measured values nothing.
    static func approx(_ value: String, _ trust: Trust?) -> String {
        trust?.isEstimate == true ? "≈ " + value : value
    }

    /// One sentence about crowds, or nil (then the sheet shows no line). When the route meets a scheduled
    /// ferry or school pulse (decision 059), the first one in route order names the cause and when the run
    /// gets there: "≈ Busy near the E 35th St ferry around 8:05." Otherwise, only when a stretch is
    /// moderate or busy at the start time: "Busier on E 31st St around 7.", naming the busiest band present
    /// (busy, else moderate), longest first, at most two.
    static func crowdSentence(_ d: RouteDetail, startTime: String) -> String? {
        if let pulse = d.summary.crowds.pulses?.first, let line = pulseSentence(pulse) {
            return line
        }
        return stretchCrowdSentence(d, startTime: startTime)
    }

    /// "≈ Busy near the E 35th St ferry around 8:05." for a ferry arrival; "≈ Busy near a school at drop-off
    /// around 8:11." (or "at pick-up" for a dismissal) for a school. The "≈" is the estimate mark the stats
    /// use; the clock is the server's `at`, the moment the run first meets the pulse. Nothing here is made up:
    /// an unknown cause gives nil and the stretch sentence stands in.
    static func pulseSentence(_ p: RouteFile.Pulse) -> String? {
        let when = clockText(p.at)
        switch p.cause {
        case "ferry":
            let where_ = p.place.map { "the \(shortName($0)) ferry" } ?? "the ferry landing"
            return "≈ Busy near \(where_) around \(when)."
        case "school":
            let moment = p.event == "dismissal" ? "pick-up" : "drop-off"
            return "≈ Busy near a school at \(moment) around \(when)."
        default:
            return nil
        }
    }

    /// "08:05" → "8:05", "08:00" → "8", "14:20" → "14:20" (the card keeps the server's 24-hour clock, as the
    /// request line's hour does).
    static func clockText(_ hhmm: String) -> String {
        let trimmed = hhmm.hasPrefix("0") ? String(hhmm.dropFirst()) : hhmm
        return hourText(trimmed)
    }

    /// The stretch-level sentence: the busiest band present (high "Busier", else medium), longest first.
    static func stretchCrowdSentence(_ d: RouteDetail, startTime: String) -> String? {
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

    /// Metres as whole feet: the climb reads in feet, as the miles do (phone, 2026-11-13).
    static func feet(_ metres: Double) -> Int { Int((metres * 3.28084).rounded()) }

    /// The route's name for the card: first letter capitalised, never cut.
    static func nameLine(_ name: String) -> String {
        let t = name.trimmingCharacters(in: .whitespaces)
        return t.prefix(1).uppercased() + t.dropFirst()
    }

    /// How many lines a name takes at the card's text width (1 or 2): the card reserves room for them.
    static func nameLines(_ name: String, width: CGFloat) -> Int {
        let style = TypeStyle.bodyStrong
        let box = (nameLine(name) as NSString).boundingRect(
            with: CGSize(width: width, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: [.font: style.uiFont, .kern: style.trackingPoints], context: nil)
        return min(2, max(1, Int((box.height / style.uiFont.lineHeight).rounded(.up))))
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

    // MARK: Display

    /// A route or place name as it is shown: it wraps at spaces, never inside a hyphenated word
    /// ("East River out-and-back" never breaks after "out-"). An invisible word joiner goes after
    /// each hyphen (neither font has a non-breaking hyphen). Display only: nothing that is
    /// compared, stored or sent uses it.
    static func unbroken(_ name: String) -> String {
        name.replacingOccurrences(of: "-", with: "-\u{2060}")
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
