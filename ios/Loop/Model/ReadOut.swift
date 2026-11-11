import Foundation

/// How Loop read a request: the words it understood (with where they sit in the sentence), what it
/// filled in, what it can't plan yet, and notes. In the app this comes from the server's `parsed`
/// event; until the phone is wired to it, `simulated` builds a stand-in from the sentence and the
/// saved file (decision 024). Rule 1 holds either way: no numbers are invented here.
struct ReadOut: Equatable {
    struct Understood: Equatable, Identifiable {
        /// Character offsets of the phrase in the sentence.
        let start: Int
        let length: Int
        let field: String
        let title: String
        var value: String
        /// The server chip it came from (a chip edit drops this id's span).
        var chipId: String? = nil
        var id: String { field }
    }
    struct Filled: Equatable, Identifiable {
        let field: String
        let main: String
        let detail: String
        let source: String
        var chipId: String? = nil
        var id: String { field }
    }
    struct Cant: Equatable { let gap: String; let text: String }
    struct Note: Equatable { let key: String; let text: String; let trust: String }

    var understood: [Understood] = []
    var filled: [Filled] = []
    var cant: [Cant] = []
    var notes: [Note] = []

    var hasReadIt: Bool { !cant.isEmpty || !filled.isEmpty || !notes.isEmpty }

    /// From the server's `parsed` event. Every string is shown as sent (server templates). Words the
    /// runner said carry a span in Unicode scalars; here they become NSString (UTF-16) offsets.
    init(parsed: ServerEvent.Parsed, sentence: String) {
        for chip in parsed.chips {
            if chip.source == "said", let span = chip.span,
               let range = Self.utf16Range(of: span, in: sentence) {
                understood.append(Understood(start: range.location, length: range.length, field: chip.field,
                                             title: Self.title(chip.field), value: chip.text, chipId: chip.id))
            } else {
                // Preset, default and usual values, and edited ones (said, but not in the sentence):
                // listed in "How Loop read it", each opening the editor.
                filled.append(Filled(field: chip.field, main: chip.text, detail: "", source: chip.source, chipId: chip.id))
            }
        }
        cant = parsed.cant.map { Cant(gap: $0.gap, text: $0.text) }
        notes = parsed.notes.map { Note(key: $0.key, text: $0.text, trust: $0.trust ?? "") }
    }

    init() {}

    /// A span's scalar positions as an NSRange in the sentence; nil if it doesn't fit.
    static func utf16Range(of span: ServerEvent.Span, in text: String) -> NSRange? {
        let scalars = text.unicodeScalars
        guard span.start >= 0, span.end > span.start, span.end <= scalars.count else { return nil }
        let a = scalars.index(scalars.startIndex, offsetBy: span.start)
        let b = scalars.index(scalars.startIndex, offsetBy: span.end)
        return NSRange(a..<b, in: text)
    }

    /// The editor's title for a chip field ("DISTANCE · YOU SAID").
    static func title(_ field: String) -> String {
        switch field {
        case "time": return "Start time"
        case "via": return "Through"
        case "avoid": return "Avoid"
        default: return field.prefix(1).uppercased() + field.dropFirst()
        }
    }

    /// Stand-in for the server's parse (simulation only; the real one is Claude + templates).
    static func simulated(_ sentence: String, data: LoopData, file: RouteFile.Summary?) -> ReadOut {
        var r = ReadOut()
        let ns = sentence as NSString
        func find(_ pattern: String, caseSensitive: Bool = false) -> NSRange? {
            let re = try? NSRegularExpression(pattern: pattern, options: caseSensitive ? [] : [.caseInsensitive])
            return re?.firstMatch(in: sentence, range: NSRange(location: 0, length: ns.length))?.range
        }
        func add(_ range: NSRange?, _ field: String, _ title: String, _ value: (String) -> String) {
            guard let range else { return }
            let phrase = ns.substring(with: range)
            r.understood.append(Understood(start: range.location, length: range.length, field: field, title: title, value: value(phrase)))
        }
        add(find(#"\b\d+(\.\d+)?\s*(mi|mile|miles)\b"#), "distance", "Distance") { p in
            let n = p.components(separatedBy: CharacterSet(charactersIn: "0123456789.").inverted).joined()
            return "\(n) mi"
        }
        // A place name: capitalised words after "from (the)".
        let start = find(#"\b[Ff]rom (the )?[A-Z][\w'.]*( [A-Z][\w'.]*)*"#, caseSensitive: true)
        add(start, "start", "Start") { $0.replacingOccurrences(of: "from ", with: "") }
        add(find(#"\b(by the water|waterfront|along the river)\b"#), "scenery", "Scenery") { _ in "By the water" }
        add(find(#"\bat \d{1,2}(:\d{2})?( ?(am|pm))?\b"#), "time", "Start time") { $0.replacingOccurrences(of: "at ", with: "") }

        if find(#"\b(well[- ]lit|lit|lighting)\b"#) != nil { r.cant.append(Cant(gap: "G9", text: "Can't plan around street lighting yet")) }
        if find(#"\b(repeats|intervals|\d+ ?[x×] ?\d+)\b"#) != nil { r.cant.append(Cant(gap: "G8", text: "Can't build repeats into a route yet")) }

        // What Loop filled in, from the saved request's preset and default values.
        let req = data.request
        if start == nil {
            r.filled.append(Filled(field: "start", main: "Starting where you are", detail: "Kips Bay Library", source: "default"))
        }
        r.filled.append(Filled(field: "mode", main: "\(req.mode): fewer lights, crowds and turns", detail: "", source: "preset"))
        r.filled.append(Filled(field: "shape", main: "Any shape, a loop or out and back", detail: "", source: "default"))
        return r
    }
}

extension CardText {
    /// The card's one line for unmet asks (Jared, 2026-11-08): one names the gap, two join, three or more count.
    static func cantCardLine(_ gaps: [String]) -> String? {
        let names: [String: (one: String, joined: String)] = [
            "G9": ("Street lighting", "lighting"), "G8": ("Repeats", "repeats"),
            "G1": ("The whole way along a place", "the whole way"), "G3": ("Soft avoids", "soft avoids"),
            "G5": ("Minutes instead of miles", "minutes"),
        ]
        switch gaps.count {
        case 0: return nil
        case 1: return "\(names[gaps[0]]?.one ?? "One thing") isn't planned yet"
        case 2:
            guard let a = names[gaps[0]]?.joined, let b = names[gaps[1]]?.joined else { return "2 things aren't planned yet" }
            return "\(a.prefix(1).uppercased() + a.dropFirst()) and \(b) aren't planned yet"
        default: return "\(gaps.count) things aren't planned yet"
        }
    }
}
