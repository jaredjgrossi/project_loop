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

        var id: String { rawValue }

        var title: String {
            switch self {
            case .composer: return "A · Asking"
            case .calmWait: return "B · The wait"
            case .routes: return "C · Reading the route"
            case .asNewRunner: return "A · As a new runner"
            }
        }

        var summary: String {
            switch self {
            case .composer: return "Field grows to three lines, send arrow, examples to try"
            case .calmWait: return "Camera holds the reach ring, fewer leader swaps, a live count"
            case .routes: return "All three routes, kind and name on the card, the way as a list"
            case .asNewRunner: return "With A on: the home sheet as someone with no runs sees it"
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
}
