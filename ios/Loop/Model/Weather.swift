import Foundation
import Observation

/// The temperature under the wordmark: when it refreshes and when it is too old to show.
/// Refreshes on launch, on return to the foreground and every 15 minutes while the app is open. A
/// reading older than 30 minutes is hidden (the time stays): never a stale number (phone, 2026-11-13).
///
/// Where the reading comes from is `provider`: the Loop server's `GET /v1/weather/nyc` (decision 051;
/// WeatherKit needs the paid developer program, decision 024). With no server or token the line
/// shows the time only.
@MainActor @Observable
final class WeatherStore {
    struct Reading: Equatable {
        let symbol: String
        let temperature: String
        /// When the source measured it (not when the phone asked).
        let at: Date
        /// Who measured it, for the attribution (the server's `source`).
        var source = ""
    }

    static let refreshInterval: TimeInterval = 15 * 60
    static let maxAge: TimeInterval = 30 * 60
    /// Two asks closer together than this are one (launch and foreground arrive together).
    static let minimumGap: TimeInterval = 30

    /// The Loop server's city reading. It looks the client up on each ask, so a token pasted later is used.
    static let shared = WeatherStore(provider: {
        guard let api = LoopAPI.live else { throw LoopAPI.Failure.unreachable }
        return try await api.weather()
    })

    /// The latest good reading, however old. Read it through `visible(at:)`.
    private(set) var reading: Reading?
    private(set) var lastAttempt: Date?
    /// Fetches the current weather. nil: no source, nothing to show.
    var provider: (() async throws -> Reading)?

    init(provider: (() async throws -> Reading)? = nil) { self.provider = provider }

    /// The reading, or nil when there is none or it is older than 30 minutes.
    func visible(at now: Date) -> Reading? {
        guard let r = reading, now.timeIntervalSince(r.at) <= Self.maxAge else { return nil }
        return r
    }

    /// Asks the source. A failure keeps the old reading, which `visible(at:)` hides once it is too old.
    func refresh(now: Date = Date(), force: Bool = false) async {
        if !force, let last = lastAttempt, now.timeIntervalSince(last) < Self.minimumGap { return }
        guard let provider else { return }
        lastAttempt = now
        if let r = try? await provider() { reading = r }
    }

    /// While the app is open: now, then every 15 minutes, until the task is cancelled.
    func run() async {
        while !Task.isCancelled {
            await refresh()
            try? await Task.sleep(for: .seconds(Self.refreshInterval))
        }
    }

    #if DEBUG
    /// Screenshots only (`-LoopSampleWeather`): a fixed reading, always fresh.
    func useSample() {
        provider = { Reading(symbol: "cloud.sun", temperature: "48°", at: Date()) }
    }
    #endif
}
