import Foundation

/// What the map draws at one moment: the lead route (whole or partly drawn, by kind or as one
/// plain line while it morphs or lacks detail) and the other candidates as faint dotted strokes.
struct RouteFrame: Equatable {
    struct Segment: Equatable {
        /// nil while the line has no per-piece detail (morphing, or a route the file only outlines).
        let kind: DrawKind?
        let points: [GeoPoint]
        /// True for a dash cut from a dashed path run.
        var isDash = false

        /// The map layer this segment goes to. Dashes are drawn as solid segments on the path layer.
        var layerKind: String { kind?.rawValue ?? "lead" }
    }

    /// One line under all runs: the whole drawn route, so the casing never breaks at a join.
    var casing: [GeoPoint] = []
    var lead: [Segment] = []
    var others: [[GeoPoint]] = []
    var othersOpacity: Double = 0.35

    /// Path dash pattern on the map, in points.
    static let dashOn: Double = 9
    static let dashOff: Double = 6
    /// Neighbouring runs overlap by this much (half on each side of a join), in points.
    static let joinOverlap: Double = 1

    /// The lead route drawn up to `fraction` of its length, split by drawn piece kind.
    /// With `metresPerPoint`: runs shorter than 40 pt on screen join their longer neighbour; a path
    /// run of at least two full dashes (30 pt) is cut into dashes fitted to start and end on a dash;
    /// shorter path runs are solid; every run reaches 0.5 pt past each join so neighbours overlap.
    static func segments(for candidate: Candidate, fraction: Double, metresPerPoint: Double? = nil) -> [Segment] {
        let f = min(1, max(0, fraction))
        let line = candidate.line
        let drawn = line.length * f
        guard drawn > 0 else { return [] }
        guard let detail = candidate.detail, !detail.drawn.isEmpty else {
            return [Segment(kind: nil, points: line.slice(from: 0, to: drawn))]
        }
        let mpp = metresPerPoint ?? 0
        var runs = detail.drawn
        if mpp > 0 {
            runs = DrawnPiece.merged(runs.map { ($0.kind, $0.lengthM) }, lineLength: line.length,
                                     minimum: MapScale.minimumRunPoints * mpp)
        }
        let half = joinOverlap / 2 * mpp
        var out: [Segment] = []
        for (i, run) in runs.enumerated() where run.fromM < drawn {
            let from = i == 0 ? run.fromM : run.fromM - half
            let to = min(i == runs.count - 1 ? run.toM : run.toM + half, drawn)
            if run.kind == .path, mpp > 0, run.lengthM / mpp >= MapScale.minimumDashedPoints {
                for dash in fittedDashes(from: from, to: run.toM + (i == runs.count - 1 ? 0 : half), mpp: mpp)
                where dash.0 < drawn {
                    let pts = line.slice(from: dash.0, to: min(dash.1, drawn))
                    if pts.count >= 2 { out.append(Segment(kind: .path, points: pts, isDash: true)) }
                }
            } else {
                let pts = line.slice(from: from, to: to)
                if pts.count >= 2 { out.append(Segment(kind: run.kind, points: pts)) }
            }
        }
        return out
    }

    /// Dashes over [from, to] metres that start and end on a dash: the 9/6 pt pattern is stretched
    /// or squeezed (never more than half a period) so a whole number of dashes fits.
    static func fittedDashes(from: Double, to: Double, mpp: Double) -> [(Double, Double)] {
        let length = to - from
        guard length > 0, mpp > 0 else { return [] }
        let on = dashOn * mpp, off = dashOff * mpp
        let n = max(2, Int(((length + off) / (on + off)).rounded()))
        let scale = length / (Double(n) * on + Double(n - 1) * off)
        return (0..<n).map { k in
            let start = from + Double(k) * (on + off) * scale
            return (start, start + on * scale)
        }
    }

    /// Run kinds as drawn at a scale, one entry per run (dashes of one run count once), for tests.
    static func layerKinds(for candidate: Candidate, metresPerPoint: Double) -> [String] {
        var kinds: [String] = []
        var lastWasDash = false
        for seg in segments(for: candidate, fraction: 1, metresPerPoint: metresPerPoint) {
            if seg.isDash && lastWasDash { continue }
            kinds.append(seg.layerKind)
            lastWasDash = seg.isDash
        }
        return kinds
    }

    /// A plain line drawn up to `fraction` (used mid-morph, on blended points).
    static func plain(_ points: [GeoPoint], fraction: Double) -> [Segment] {
        guard points.count >= 2 else { return [] }
        let f = min(1, max(0, fraction))
        if f >= 1 { return [Segment(kind: nil, points: points)] }
        let pts = Polyline(points).slice(from: 0, to: Polyline(points).length * f)
        return pts.count >= 2 ? [Segment(kind: nil, points: pts)] : []
    }
}
