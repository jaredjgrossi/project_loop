import Foundation

/// The app's clock. Every "now" that reaches the server (`client.now`), a date label, the weather line or the
/// return prompt reads it, so a debug build can pin the time for a recording (demo mode, decision 060). In Release
/// it is the system clock and nothing else.
enum LoopClock {
    #if DEBUG
    /// Debug only: a moment the clock is pinned to. It ticks on from there in real time. nil: the system clock.
    static var pinned: Date? { didSet { pinnedAt = Date() } }
    private static var pinnedAt = Date()

    static func now() -> Date {
        guard let pinned else { return Date() }
        return pinned.addingTimeInterval(Date().timeIntervalSince(pinnedAt))
    }
    #else
    @inline(__always) static func now() -> Date { Date() }
    #endif
}
