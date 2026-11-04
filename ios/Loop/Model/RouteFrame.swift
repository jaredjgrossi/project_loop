import Foundation

/// What the map draws at one moment: the lead route (whole or partly drawn, by kind or as one
/// plain line while it morphs or lacks detail) and the other candidates as faint dotted strokes.
struct RouteFrame: Equatable {
    struct Segment: Equatable {
        /// nil while the line has no per-piece detail (morphing, or a route the file only outlines).
        let kind: DrawKind?
        let points: [GeoPoint]
        /// Path runs too short on screen for two full dashes are drawn solid.
        var dashed = true

        /// The map layer this segment goes to.
        var layerKind: String {
            guard let kind else { return "lead" }
            return kind == .path && !dashed ? "pathSolid" : kind.rawValue
        }
    }

    var lead: [Segment] = []
    var others: [[GeoPoint]] = []
    var othersOpacity: Double = 0.35

    /// The lead route drawn up to `fraction` of its length, split by drawn piece kind.
    /// With `metresPerPoint`, runs shorter than 40 pt on screen join their longer neighbour and
    /// path runs shorter than 30 pt are drawn solid, so the detail follows the zoom.
    static func segments(for candidate: Candidate, fraction: Double, metresPerPoint: Double? = nil) -> [Segment] {
        let f = min(1, max(0, fraction))
        let line = candidate.line
        let drawn = line.length * f
        guard drawn > 0 else { return [] }
        guard let detail = candidate.detail, !detail.drawn.isEmpty else {
            return [Segment(kind: nil, points: line.slice(from: 0, to: drawn))]
        }
        var runs = detail.drawn
        if let mpp = metresPerPoint, mpp > 0 {
            runs = DrawnPiece.merged(runs.map { ($0.kind, $0.lengthM) }, lineLength: line.length,
                                     minimum: MapScale.minimumRunPoints * mpp)
        }
        return runs.compactMap { piece in
            let pts = line.slice(from: piece.fromM, to: min(piece.toM, drawn))
            guard pts.count >= 2 else { return nil }
            let dashed = metresPerPoint.map { piece.lengthM / $0 >= MapScale.minimumDashedPoints } ?? true
            return Segment(kind: piece.kind, points: pts, dashed: dashed)
        }
    }

    /// Run kinds as drawn at a scale, for tests.
    static func layerKinds(for candidate: Candidate, metresPerPoint: Double) -> [String] {
        segments(for: candidate, fraction: 1, metresPerPoint: metresPerPoint).map(\.layerKind)
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
