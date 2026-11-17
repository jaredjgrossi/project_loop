#if DEBUG
import Foundation
import SwiftUI

/// Demo mode (decision 060): the app plays the demo video's sequence by itself on a real phone, from staged state at a
/// public start, so the recording shows the real engine's routes with nothing personal on screen. Debug builds only:
/// this whole folder is compiled out of Release. On with the launch argument `-LoopDemoMode [A-G]` (from the Mac:
/// `xcrun devicectl device process launch ... -- -LoopDemoMode [A-G]`) or a two-second press on the wordmark.
///
/// Staged, so the post can say so: the clock (a school-day Tuesday, 6:52 for segments A to D, 9:40 for E and F), the
/// location (the Kips Bay Library stand-in), the weather reading's temperature, the sample history, the saved routes,
/// the return prompt, the opening drift and the hero map's draw-in. Not staged: every route, number, name, reason
/// line and crowd line, which come from the live server.
@MainActor
enum DemoMode {
    private(set) static var active = false
    /// The segment to start from ("A" plays everything).
    private(set) static var startSegment: Character = "A"

    /// A named public start (never a home): the simulated location for a segment, and the opening drift's two camera
    /// points derived from it (a little north-west, easing toward the start at neighborhood zoom).
    struct Start {
        let key: String
        let name: String
        let point: GeoPoint
        var driftFrom: GeoPoint { GeoPoint(lon: point.lon - 0.0027, lat: point.lat + 0.0011) }
        var driftTo: GeoPoint { GeoPoint(lon: point.lon - 0.0016, lat: point.lat + 0.0005) }
    }

    /// The short list. The first is the stand-in the sample history and the Home default use.
    static let starts: [Start] = [
        Start(key: "kips-bay-library", name: "Kips Bay Library", point: GeoPoint(lon: -73.97994, lat: 40.74384)),
        Start(key: "fifth-ave-86th", name: "5th Ave & E 86th St", point: GeoPoint(lon: -73.9602, lat: 40.7794)),
        Start(key: "grand-army-plaza", name: "Grand Army Plaza", point: GeoPoint(lon: -73.97105, lat: 40.67524)),
    ]
    static func start(_ key: String) -> Start { starts.first { $0.key == key } ?? starts[0] }

    /// The public start the demo opens at and the history belongs to: the Kips Bay Library stand-in
    /// (`evals/routes/starts.json`, `kips-bay`).
    static let start = starts[0].point
    /// The weather line's fixed sample reading.
    static let sampleTemperature = "46°"
    static let sampleSymbol = "cloud.sun"

    static let newYork = TimeZone(identifier: "America/New_York")!

    /// Tuesday 2026-11-17, a school day (NYC DOE calendar), before 7:00 so "at 7" reads as this morning.
    static var morning: Date { date(hour: 6, minute: 52) }
    /// Later the same morning, for the return prompt (segments E and F).
    static var laterMorning: Date { date(hour: 9, minute: 40) }

    static func date(hour: Int, minute: Int) -> Date {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = newYork
        return c.date(from: DateComponents(year: 2026, month: 11, day: 17, hour: hour, minute: minute))!
    }

    /// The demo's own history file, beside the real one and never the real one.
    static var storeURL: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("demo-runs.json")
    }

    private static let armedKey = "LoopDemoArmed"

    static func configure(arguments args: [String] = ProcessInfo.processInfo.arguments) {
        if UserDefaults.standard.bool(forKey: armedKey) {   // the hidden trigger, armed on the last run
            UserDefaults.standard.removeObject(forKey: armedKey)
            active = true
        }
        guard let i = args.firstIndex(of: "-LoopDemoMode") else { return }
        active = true
        if i + 1 < args.count, let c = args[i + 1].uppercased().first, "ABCDEFG".contains(c) { startSegment = c }
    }

    /// The hidden trigger on the phone: arms demo mode for the next launch (a two-second press on the wordmark).
    static func arm() { UserDefaults.standard.set(true, forKey: armedKey) }
}
#endif
