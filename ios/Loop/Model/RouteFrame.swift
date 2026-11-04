import Foundation

/// What the map draws at one moment: the lead route (whole or partly drawn, by kind or as one
/// plain line while it morphs or lacks detail) and the other candidates as faint dotted strokes.
struct RouteFrame: Equatable {
    struct Segment: Equatable {
        /// nil while the line has no per-stretch detail (morphing, or a route the file only outlines).
        let kind: DrawKind?
        let points: [GeoPoint]
    }

    var lead: [Segment] = []
    var others: [[GeoPoint]] = []
    var othersOpacity: Double = 0.35

    /// The lead route drawn up to `fraction` of its length, split by drawn piece kind.
    static func segments(for candidate: Candidate, fraction: Double) -> [Segment] {
        let f = min(1, max(0, fraction))
        let line = candidate.line
        let drawn = line.length * f
        guard drawn > 0 else { return [] }
        guard let detail = candidate.detail, !detail.drawn.isEmpty else {
            return [Segment(kind: nil, points: line.slice(from: 0, to: drawn))]
        }
        return detail.drawn.compactMap { piece in
            let pts = line.slice(from: piece.fromM, to: min(piece.toM, drawn))
            return pts.count >= 2 ? Segment(kind: piece.kind, points: pts) : nil
        }
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
