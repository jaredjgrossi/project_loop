import Foundation

/// Which parts of a route get direction arrows. A route that runs back along itself (an out-and-back,
/// the stick of a lollipop) would show arrows pointing both ways on the same line, so only the first
/// pass is kept: any stretch that retraces earlier ground is dropped.
enum RouteDirection {
    /// Samples this far apart along the line (metres).
    static let step = 10.0
    /// A sample this close to ground covered earlier counts as the same ground.
    static let retraceDistance = 14.0
    /// Ground covered less than this far back along the line is not "earlier" (a bend, not a retrace).
    static let minimumGap = 150.0
    /// A retrace shorter than this many samples is a crossing or a near miss, not the way back.
    static let minimumRun = 5

    /// The first-pass pieces of the line, in order, resampled every `step` metres.
    static func firstPass(of points: [GeoPoint]) -> [[GeoPoint]] {
        guard points.count >= 2 else { return [] }
        let line = Polyline(points)
        guard line.length > step else { return [] }
        let n = Int(line.length / step) + 1
        let samples = (0...n).map { line.point(at: min(line.length, Double($0) * step)) }

        // Local flat metres, enough for a run.
        let lat0 = samples[0].lat * .pi / 180
        let xy = samples.map { (x: $0.lon * 111_320 * cos(lat0), y: $0.lat * 111_320) }
        let gap = Int(minimumGap / step)
        var retraced = [Bool](repeating: false, count: samples.count)
        for i in gap..<samples.count {
            for j in 0...(i - gap) {
                let dx = xy[i].x - xy[j].x, dy = xy[i].y - xy[j].y
                if dx * dx + dy * dy <= retraceDistance * retraceDistance { retraced[i] = true; break }
            }
        }
        // Short retraced runs are crossings: keep them.
        var i = 0
        while i < retraced.count {
            guard retraced[i] else { i += 1; continue }
            var j = i
            while j < retraced.count, retraced[j] { j += 1 }
            if j - i < minimumRun { for k in i..<j { retraced[k] = false } }
            i = j
        }

        var runs: [[GeoPoint]] = []
        var current: [GeoPoint] = []
        for (k, s) in samples.enumerated() {
            if retraced[k] {
                if current.count >= 2 { runs.append(current) }
                current = []
            } else {
                current.append(s)
            }
        }
        if current.count >= 2 { runs.append(current) }
        return runs
    }
}
