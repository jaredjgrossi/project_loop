import Foundation
import Observation

/// Design explorations, each behind its own switch (design-review-v1, 2026-11-12). Every switch is
/// off by default and exists only in Debug builds: with all three off, or in Release, the app
/// behaves exactly as `main` does. Switches live in "You" → Design lab and are kept in UserDefaults.
/// For screenshots, `-LoopLab composer,calmWait,routes` turns the named ones on for that launch.
@Observable
@MainActor
final class DesignLab {
    static let shared = DesignLab()

    enum Feature: String, CaseIterable, Identifiable {
        /// A: the request field grows to three lines with a send arrow; a new runner sees
        /// examples to try instead of placeholder tiles.
        case composer
        /// B: the wait holds the reach ring's frame until the settle, changes leader less
        /// often, and says how many routes it has looked at.
        case calmWait
        /// C: the other two routes stay on the map and can be opened; the card says which route
        /// and what kind; the open sheet lists the way.
        case routes
        /// A helper for A: show the home sheet as a runner with no runs of their own sees it.
        case asNewRunner
        /// D: while Loop looks, everything is pencil; at the flag the winner is inked, miles stamp
        /// in, the distance rolls up, and the phone plays one pattern for the whole move.
        case ink
        /// D+ (wildcard): a tilted drafting-table camera at the settle, paper grain, and sound.
        case inkWild
        /// E: fly the route at street height, in the light of the hour it's planned for.
        case flyover
        /// E+ (wildcard): drag to scrub the flight, tap to pause, and a paper-model city.
        case flyoverWild
        /// F: after "I ran it", the run draws onto the map of every run and the totals roll.
        case arrival
        /// F+ (wildcard): a poster of every run, for the share sheet.
        case arrivalWild

        var id: String { rawValue }

        var title: String {
            switch self {
            case .composer: return "A · Asking"
            case .calmWait: return "B · The wait"
            case .routes: return "C · Reading the route"
            case .asNewRunner: return "A · As a new runner"
            case .ink: return "D · Pencil, then ink"
            case .inkWild: return "D+ · Wildcard: tilt, grain, sound"
            case .flyover: return "E · Fly the route"
            case .flyoverWild: return "E+ · Wildcard: scrub, paper city"
            case .arrival: return "F · The run joins your map"
            case .arrivalWild: return "F+ · Wildcard: the poster"
            }
        }

        var summary: String {
            switch self {
            case .composer: return "Field grows to three lines, send arrow, examples to try"
            case .calmWait: return "Camera holds the reach ring, fewer leader swaps, a live count"
            case .routes: return "All three routes, kind and name on the card, the way as a list"
            case .asNewRunner: return "With A on: the home sheet as someone with no runs sees it"
            case .ink: return "Candidates and leader in graphite; the winner inks in at the flag, with a haptic pattern"
            case .inkWild: return "Adds a tilted camera at the settle, paper grain over the screen, a brush-and-knock sound"
            case .flyover: return "A play button on the card flies the route in 3D, lit for the planned hour"
            case .flyoverWild: return "Adds drag to scrub and tap to pause; buildings as a cream paper model"
            case .arrival: return "After a rating, the run draws onto every run so far and the totals roll"
            case .arrivalWild: return "Adds a shareable poster of every run (ends trimmed 200 m)"
            }
        }
    }

    private var stored: [Feature: Bool] = [:]
    @ObservationIgnored private let forced: Set<Feature>

    private init() {
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "-LoopLab"), i + 1 < args.count {
            forced = Set(args[i + 1].split(separator: ",").compactMap { Feature(rawValue: String($0)) })
        } else {
            forced = []
        }
        for f in Feature.allCases { stored[f] = UserDefaults.standard.bool(forKey: Self.key(f)) }
        #else
        forced = []
        #endif
    }

    private static func key(_ f: Feature) -> String { "lab." + f.rawValue }

    func isOn(_ f: Feature) -> Bool {
        #if DEBUG
        return forced.contains(f) || (stored[f] ?? false)
        #else
        return false
        #endif
    }

    func set(_ f: Feature, _ on: Bool) {
        #if DEBUG
        stored[f] = on
        UserDefaults.standard.set(on, forKey: Self.key(f))
        #endif
    }

    /// Set by a launch argument for this launch only (the switch shows on and can't be turned off).
    func isForced(_ f: Feature) -> Bool { forced.contains(f) }

    var composer: Bool { isOn(.composer) }
    var calmWait: Bool { isOn(.calmWait) }
    var routes: Bool { isOn(.routes) }
    /// A wildcard switch turns its own moment on too.
    var ink: Bool { isOn(.ink) || isOn(.inkWild) }
    var flyover: Bool { isOn(.flyover) || isOn(.flyoverWild) }
    var arrival: Bool { isOn(.arrival) || isOn(.arrivalWild) }
}
