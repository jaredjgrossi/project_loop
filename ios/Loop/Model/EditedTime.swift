import Foundation

/// The time editor's Done writes the new time the way the runner typed it: "at 7am" becomes "at 8am", "at 7 am"
/// becomes "at 8 am", "at 7" becomes "at 8". The spacing before am/pm, its case and its dots are theirs; am/pm is
/// added only when they wrote none and the new time crosses noon or midnight; minutes are written when they wrote
/// some or the new time has some. A time written without digits ("in the morning") returns nil and the caller
/// falls back to the app's own form.
enum EditedTime {
    static func phrase(typed: String, minutes: Int) -> String? {
        let ns = typed as NSString
        let re = try! NSRegularExpression(pattern: #"(\d{1,2})(?::(\d{2}))?(\s*)([AaPp]\.?[Mm]\.?)?"#)
        guard let m = re.firstMatch(in: typed, range: NSRange(location: 0, length: ns.length)),
              let typedHour = Int(ns.substring(with: m.range(at: 1))) else { return nil }
        let h = minutes / 60, mm = minutes % 60
        let typedMinutes = m.range(at: 2).location != NSNotFound
        let suffix = m.range(at: 4).location != NSNotFound ? ns.substring(with: m.range(at: 4)) : nil

        var out: String
        if typedHour > 12 {
            // A 24-hour clock: "at 18" → "at 19".
            out = String(h)
        } else {
            out = String(h % 12 == 0 ? 12 : h % 12)
        }
        if typedMinutes || mm != 0 { out += ":" + (mm < 10 ? "0\(mm)" : "\(mm)") }
        if let suffix {
            // Their am/pm, with its letter swapped if the new time is on the other side of noon.
            let letter = h < 12 ? "a" : "p"
            let first = suffix.first.map(String.init) ?? "a"
            out += ns.substring(with: m.range(at: 3)) + (first == first.uppercased() ? letter.uppercased() : letter) + suffix.dropFirst()
        } else if typedHour <= 12, (typedHour < 12) != (h < 12) {
            out += h < 12 ? " am" : " pm"
        }
        let replaced = suffix == nil ? NSRange(location: m.range.location, length: m.range(at: 3).location - m.range.location)
                                     : m.range
        return ns.replacingCharacters(in: replaced, with: out)
    }
}
