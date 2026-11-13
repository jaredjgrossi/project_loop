import Foundation

/// One line of the step-by-step list: where it begins (miles along the route), what to do, and how far
/// the run is before the next step.
struct DirectionStep: Equatable, Identifiable {
    enum Kind: Equatable { case start, run, turnaround, finish }
    let id: Int
    let kind: Kind
    let mile: Double
    let text: String
    /// Length of the run this step starts, in miles; nil for the turnaround and the finish.
    let miles: Double?
}

/// "Start on X, continue onto Y for 0.8 mi, turn around, head back...", from the file's stretches in order
/// and its turnaround. Deterministic code only: the names and distances are the server's measured
/// stretches. The file has no left/right turns, so a change of street reads "Continue onto".
enum Directions {
    /// A stretch under this length (miles, about 50 m) joins its neighbour: a crossing, not a step.
    static let minimumLeg = 0.03
    /// A turnaround this close to a stretch's end is at the boundary, not inside the stretch.
    static let boundary = 0.02

    struct Leg: Equatable {
        var name: String
        var from: Double
        var to: Double
    }

    static func steps(for detail: RouteDetail) -> [DirectionStep] {
        // The server's turns when the file has them; the stretch list for saved routes and older files.
        if let turns = detail.summary.steps, !turns.isEmpty {
            return steps(turns: turns, total: detail.distanceMi, backAtStart: detail.kindText != "ONE WAY")
        }
        return steps(legs: detail.stretches.map { Leg(name: $0.name, from: $0.fromMile, to: $0.toMile) },
              turnaround: detail.turnaround?.alongMi, total: detail.distanceMi,
              backAtStart: detail.kindText != "ONE WAY")
    }

    static func steps(legs input: [Leg], turnaround: Double?, total: Double, backAtStart: Bool) -> [DirectionStep] {
        var legs = tidy(input.sorted { $0.from < $1.from })
        guard !legs.isEmpty else { return [] }
        legs[0].from = 0
        legs[legs.count - 1].to = max(total, legs[legs.count - 1].from)

        // Split at the turnaround: a boundary inside a stretch makes two legs of the same name.
        var turnAfter: Int?   // the turnaround comes after legs[turnAfter]
        if let t = turnaround, t > boundary, t < total - boundary {
            if let k = legs.firstIndex(where: { t > $0.from + boundary && t < $0.to - boundary }) {
                let tail = Leg(name: legs[k].name, from: t, to: legs[k].to)
                legs[k].to = t
                legs.insert(tail, at: k + 1)
                turnAfter = k
            } else if let k = legs.lastIndex(where: { $0.to <= t + boundary }) , k < legs.count - 1 {
                turnAfter = k
            }
        }

        var out: [DirectionStep] = []
        func add(_ kind: DirectionStep.Kind, _ mile: Double, _ text: String, _ miles: Double? = nil) {
            out.append(DirectionStep(id: out.count, kind: kind, mile: mile, text: text, miles: miles))
        }
        for (i, leg) in legs.enumerated() {
            let name = CardText.nameLine(leg.name)
            let afterTurn = turnAfter.map { i == $0 + 1 } ?? false
            let text: String
            if i == 0 { text = "Start on \(name)" }
            else if afterTurn && legs[i - 1].name == leg.name { text = "Head back on \(name)" }
            else { text = "Continue onto \(name)" }
            add(i == 0 ? .start : .run, leg.from, text, leg.to - leg.from)
            if turnAfter == i { add(.turnaround, leg.to, "Turn around") }
        }
        add(.finish, total, backAtStart ? "Finish back at the start" : "Finish")
        return out
    }

    /// The server's maneuvers as list lines: "Turn left onto East 33rd Street", "Continue onto ...".
    /// A null street on a turn is deliberate (the runner is already on it): "Turn left", no "onto".
    static func steps(turns: [RouteFile.Turn], total: Double, backAtStart: Bool) -> [DirectionStep] {
        let ordered = turns.sorted { $0.index < $1.index }
        var out: [DirectionStep] = []
        for t in ordered {
            let street = t.street.map(CardText.nameLine)
            let miles = t.distance.miles
            let kind: DirectionStep.Kind
            let text: String
            var run: Double? = miles
            switch t.maneuver {
            case "start":
                kind = .start; text = street.map { "Start on \($0)" } ?? "Start"
            case "turnaround":
                kind = .turnaround
                text = street.map { "Turn around, head back on \($0)" } ?? "Turn around"
            case "finish":
                kind = .finish; text = backAtStart ? "Finish back at the start" : "Finish"; run = nil
            case "continue":
                kind = .run; text = street.map { "Continue onto \($0)" } ?? "Continue"
            default:
                kind = .run; text = turnPhrase(t.maneuver, street: street)
            }
            out.append(DirectionStep(id: out.count, kind: kind, mile: t.fromMile, text: text, miles: run))
        }
        return out
    }

    private static func turnPhrase(_ maneuver: String, street: String?) -> String {
        let verb: String
        switch maneuver {
        case "left": verb = "Turn left"
        case "right": verb = "Turn right"
        case "slight_left": verb = "Bear left"
        case "slight_right": verb = "Bear right"
        case "sharp_left": verb = "Turn sharp left"
        case "sharp_right": verb = "Turn sharp right"
        case "u_turn": verb = "Make a U-turn"
        default: verb = "Continue"
        }
        return street.map { "\(verb) onto \($0)" } ?? verb
    }

    /// Short stretches join the one before them (the first joins the one after), and neighbours with the
    /// same name become one.
    private static func tidy(_ input: [Leg]) -> [Leg] {
        var legs = input
        while legs.count > 1, let i = legs.firstIndex(where: { $0.to - $0.from < minimumLeg }) {
            if i > 0 { legs[i - 1].to = legs[i].to } else { legs[1].from = legs[0].from }
            legs.remove(at: i)
        }
        var merged: [Leg] = []
        for leg in legs {
            if var last = merged.last, last.name == leg.name { last.to = leg.to; merged[merged.count - 1] = last }
            else { merged.append(leg) }
        }
        return merged
    }

    /// "0.35 mi", or "260 ft" under a tenth of a mile.
    static func distanceText(_ miles: Double) -> String {
        if miles < 0.1 { return "\(Int((miles * 5280 / 10).rounded()) * 10) ft" }
        return String(format: "%.2f mi", miles)
    }

    /// The mile a step begins at, two decimals (the same precision as the distances beside it).
    static func mileText(_ mile: Double) -> String { String(format: "%.2f", mile) }
}
