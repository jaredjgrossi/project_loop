import Foundation

/// What the engine streams during a live build (decision 018).
enum BuildEvent: Equatable {
    /// The current top 3 by rank, best first. Sent whenever it changes; the first under 1 s.
    case top3([Int])
    /// The early jobs finished. #1 has never changed after this in testing: the settle moment.
    case provisional
    /// The whole pool finished: the final top 3 and the "Best of N" count.
    case final([Int])
}

/// A timed list of events, faked from the saved file's top 3 for this slice.
struct BuildScript: Equatable {
    let name: String
    let events: [Timed]

    struct Timed: Equatable {
        let at: TimeInterval
        let event: BuildEvent
    }

    /// The brief's example: #2 first, morph to #1 at 1.5 s, flag at 3 s, final at 6 s.
    static let standard = BuildScript(name: "Play the build", events: [
        .init(at: 0.3, event: .top3([2, 3])),
        .init(at: 1.5, event: .top3([1, 2, 3])),
        .init(at: 3.0, event: .provisional),
        .init(at: 6.0, event: .final([1, 2, 3])),
    ])

    /// For testing the chip without fast fingers: #1 only arrives after the flag.
    static let lateBetterRoute = BuildScript(name: "Play: better route after the flag", events: [
        .init(at: 0.3, event: .top3([2, 3])),
        .init(at: 3.0, event: .provisional),
        .init(at: 4.5, event: .top3([1, 2, 3])),
        .init(at: 6.0, event: .final([1, 2, 3])),
    ])
}

/// The replay's state, advanced by events and by the runner's touches. Pure, so it is tested
/// without a screen. Times are seconds on any monotonic clock.
struct BuildState: Equatable {
    struct Morph: Equatable {
        let from: Int
        let to: Int
        let start: TimeInterval
    }

    /// The engine's current top 3.
    private(set) var engineTop3: [Int] = []
    /// The route the runner sees as #1. Changes only by morphing before the flag, untouched,
    /// or when the runner taps "A better route came in".
    private(set) var shownRank: Int?
    private(set) var drawStart: TimeInterval?
    private(set) var morph: Morph?
    private(set) var touched = false
    private(set) var provisional = false
    private(set) var final = false
    /// When the provisional flag arrived (candidate outlines fade out from here).
    private(set) var provisionalAt: TimeInterval?
    /// When the settle beat (ring pulse + light haptic) fires; nil if skipped.
    private(set) var settleAt: TimeInterval?
    /// A better #1 the runner hasn't taken yet: shows the quiet chip.
    private(set) var betterRank: Int?

    init() {}

    /// Fully arrived and drawn (the launch state).
    static func settled(top3: [Int]) -> BuildState {
        var s = BuildState()
        s.engineTop3 = top3
        s.shownRank = top3.first
        s.drawStart = -.greatestFiniteMagnitude
        s.provisional = true
        s.provisionalAt = -.greatestFiniteMagnitude
        s.final = true
        return s
    }

    var cardRevealed: Bool { provisional }
    var showsCount: Bool { final }
    var otherRanks: [Int] { engineTop3.filter { $0 != shownRank } }

    /// May the shown route still change under the runner? Only before the flag and untouched.
    private var canSwap: Bool { !touched && !provisional }

    mutating func apply(_ event: BuildEvent, at t: TimeInterval) {
        switch event {
        case let .top3(ranks):
            receive(ranks, at: t)
        case .provisional:
            guard !provisional else { return }
            provisional = true
            provisionalAt = t
            if !touched { settleAt = t }
        case let .final(ranks):
            receive(ranks, at: t)
            final = true
        }
    }

    private mutating func receive(_ ranks: [Int], at t: TimeInterval) {
        engineTop3 = ranks
        guard let lead = ranks.first else { return }
        guard let shown = shownRank else {
            shownRank = lead
            drawStart = t
            return
        }
        if lead == shown {
            betterRank = nil
        } else if canSwap {
            morph = Morph(from: shown, to: lead, start: t)
            shownRank = lead
            betterRank = nil
        } else {
            betterRank = lead
        }
    }

    /// The runner touched the route or the card (scrub, look around, the button, the sheet).
    mutating func touch() { touched = true }

    /// The runner tapped "A better route came in".
    mutating func acceptBetterRoute(at t: TimeInterval) {
        guard let better = betterRank, let shown = shownRank else { return }
        morph = Morph(from: shown, to: better, start: t)
        shownRank = better
        betterRank = nil
    }

    /// Design lab C: the runner opens another of the top three. The line morphs to it; from here
    /// the shown route is the runner's choice, so nothing swaps under them.
    mutating func show(_ rank: Int, at t: TimeInterval) {
        guard engineTop3.contains(rank), let shown = shownRank, rank != shown else { return }
        morph = Morph(from: shown, to: rank, start: t)
        shownRank = rank
        touched = true
        betterRank = nil
    }

    /// Share of the shown route drawn at `t`: constant speed from when it first arrived.
    func drawnFraction(at t: TimeInterval, length: Double, metresPerSecond: Double) -> Double {
        guard let start = drawStart, length > 0 else { return 0 }
        return min(1, max(0, (t - start) * metresPerSecond / length))
    }

    /// Opacity of the other candidates' faint outlines: `peak` while building, fading to 0 over
    /// `fade` seconds from the provisional flag. None are visible once settled.
    func outlineOpacity(at t: TimeInterval, peak: Double, fade: TimeInterval) -> Double {
        guard let flag = provisionalAt else { return peak }
        return peak * max(0, 1 - (t - flag) / fade)
    }

    /// Morph progress 0...1 at `t`, or nil when not morphing.
    func morphProgress(at t: TimeInterval, duration: TimeInterval) -> Double? {
        guard let m = morph else { return nil }
        let p = (t - m.start) / duration
        return p >= 1 ? nil : max(0, p)
    }
}
