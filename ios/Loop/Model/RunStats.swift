import Foundation

/// "You": numbers from the routes marked as run, each at the route's own distance (no GPS or
/// Health import). Pure, so it's tested without a screen.
struct RunStats {
    let runs: [RunLog]
    let now: Date
    let calendar: Calendar

    init(runs: [RunLog], now: Date = Date(), calendar: Calendar = RunStats.mondayCalendar) {
        self.runs = runs
        self.now = now
        self.calendar = calendar
    }

    static var mondayCalendar: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.firstWeekday = 2
        c.timeZone = .current
        return c
    }

    var count: Int { runs.count }
    var miles: Double { runs.reduce(0) { $0 + $1.route.distanceMi } }
    var average: Double? { runs.isEmpty ? nil : miles / Double(runs.count) }
    var longest: Double? { runs.map(\.route.distanceMi).max() }
    var since: Date? { runs.map(\.ranAt).min() }

    private func weekStart(_ d: Date) -> Date {
        calendar.dateInterval(of: .weekOfYear, for: d)?.start ?? calendar.startOfDay(for: d)
    }

    /// Consecutive weeks with a run, ending this week (or last week, if this week has none yet).
    var weekStreak: Int {
        let weeks = Set(runs.map { weekStart($0.ranAt) })
        var week = weekStart(now)
        if !weeks.contains(week) { week = calendar.date(byAdding: .weekOfYear, value: -1, to: week) ?? week }
        var n = 0
        while weeks.contains(week) {
            n += 1
            week = calendar.date(byAdding: .weekOfYear, value: -1, to: week) ?? week
        }
        return n
    }

    /// Miles per week for the last 8 weeks, oldest first (this week last).
    var lastEightWeeks: [Double] {
        let thisWeek = weekStart(now)
        return (0..<8).reversed().map { back in
            let start = calendar.date(byAdding: .weekOfYear, value: -back, to: thisWeek) ?? thisWeek
            return runs.filter { weekStart($0.ranAt) == start }.reduce(0) { $0 + $1.route.distanceMi }
        }
    }

    /// The Monday the chart starts on.
    var chartStart: Date {
        calendar.date(byAdding: .weekOfYear, value: -7, to: weekStart(now)) ?? now
    }

    /// The runs' usual start: the median planned start ("HH:MM"), as "7:04 am"; nil without any.
    var usualStart: String? {
        let minutes = runs.compactMap(\.route.startTime).compactMap(Self.minutes).sorted()
        guard !minutes.isEmpty else { return nil }
        return Self.clock(minutes[minutes.count / 2])
    }

    /// The stretch in the most runs, and in how many.
    var mostRun: (name: String, count: Int)? {
        var counts: [String: Int] = [:]
        for r in runs { for s in Set(r.route.stretches) { counts[s, default: 0] += 1 } }
        guard let best = counts.max(by: { $0.value != $1.value ? $0.value < $1.value : $0.key > $1.key }) else { return nil }
        return (best.key, best.value)
    }

    static func minutes(_ hhmm: String) -> Int? {
        let p = hhmm.split(separator: ":").compactMap { Int($0) }
        guard p.count == 2 else { return nil }
        return p[0] * 60 + p[1]
    }

    /// 424 → "7:04 am".
    static func clock(_ m: Int) -> String {
        let h = m / 60, mm = m % 60, h12 = h % 12 == 0 ? 12 : h % 12
        return "\(h12):\(String(format: "%02d", mm)) \(h < 12 ? "am" : "pm")"
    }
}
