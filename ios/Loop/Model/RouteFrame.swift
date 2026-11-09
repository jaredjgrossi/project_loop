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
        /// True for the casing-coloured bed under a dashed run (so dash gaps read as gaps).
        var isBed = false

        /// The map layer this segment goes to.
        var layerKind: String {
            if isBed { return "pathBed" }
            return kind?.rawValue ?? "lead"
        }
    }

    /// The whole drawn route as one line: the casing and the solid base line both use it, so the
    /// outline never breaks or doubles at a join.
    var casing: [GeoPoint] = []
    /// Kind styling on top of the base line: waterfront, path (bed + dashes, or solid when short),
    /// or the plain lead line. Street is the base line itself. Butt caps, cut edge to edge.
    var lead: [Segment] = []
    var others: [[GeoPoint]] = []
    var othersOpacity: Double = 0.35

    /// The wait: the reach ring (dim outside, warm parks and water inside) and candidate lines.
    struct Reach: Equatable {
        let center: GeoPoint
        let radiusM: Double
        let ringOpacity: Double
        let dimOpacity: Double
        let warmOpacity: Double
    }
    var reach: Reach?
    var candidates: [[GeoPoint]] = []
    var candidateOpacity: Double = 0

    /// A circle as a closed ring of points, `radiusM` metres around `center`.
    static func circle(_ center: GeoPoint, radiusM: Double, points n: Int = 96) -> [GeoPoint] {
        let dLat = radiusM / 111_320, dLon = radiusM / (111_320 * cos(center.lat * .pi / 180))
        return (0...n).map { i in
            let a = Double(i) / Double(n) * 2 * .pi
            return GeoPoint(lon: center.lon + dLon * cos(a), lat: center.lat + dLat * sin(a))
        }
    }

    /// Path dash pattern on the map, in points.
    static let dashOn: Double = 9
    static let dashOff: Double = 6

    /// The drawn line at this scale: jogs under 2.5 pt removed (display only), or the full line.
    static func displayLine(for line: Polyline, metresPerPoint: Double?) -> DisplayLine {
        DisplayLine(full: line, toleranceMetres: (metresPerPoint ?? 0) * DisplayLine.tolerancePoints)
    }

    /// The casing/base line and the kind styling for a route drawn up to `fraction` of its length.
    /// With `metresPerPoint`: jogs under 2.5 pt are removed from the drawn line; runs shorter than
    /// 40 pt join their longer neighbour; a path run of at least two full dashes (30 pt) gets a bed
    /// and dashes fitted to start and end on a dash; shorter path runs are solid.
    static func route(for candidate: Candidate, fraction: Double, metresPerPoint: Double? = nil)
        -> (casing: [GeoPoint], lead: [Segment]) {
        let f = min(1, max(0, fraction))
        let full = candidate.line
        let display = displayLine(for: full, metresPerPoint: metresPerPoint)
        let line = display.line
        let drawn = display.along(fromFull: full.length * f)
        guard drawn > 0 else { return ([], []) }
        let casing = line.slice(from: 0, to: drawn)
        guard let detail = candidate.detail, !detail.drawn.isEmpty else {
            return (casing, [Segment(kind: nil, points: casing)])
        }
        let mpp = metresPerPoint ?? 0
        var runs = detail.drawn
        if mpp > 0 {
            runs = DrawnPiece.merged(runs.map { ($0.kind, $0.lengthM) }, lineLength: full.length,
                                     minimum: MapScale.minimumRunPoints * mpp)
        }
        var out: [Segment] = []
        for run in runs where run.kind != .street {
            let from = display.along(fromFull: run.fromM)
            let to = display.along(fromFull: run.toM)
            guard from < drawn else { continue }
            if run.kind == .path, mpp > 0, (to - from) / mpp >= MapScale.minimumDashedPoints {
                let bed = line.slice(from: from, to: min(to, drawn))
                if bed.count >= 2 { out.append(Segment(kind: .path, points: bed, isBed: true)) }
                for dash in fittedDashes(from: from, to: to, mpp: mpp) where dash.0 < drawn {
                    let pts = line.slice(from: dash.0, to: min(dash.1, drawn))
                    if pts.count >= 2 { out.append(Segment(kind: .path, points: pts, isDash: true)) }
                }
            } else {
                let pts = line.slice(from: from, to: min(to, drawn))
                if pts.count >= 2 { out.append(Segment(kind: run.kind, points: pts)) }
            }
        }
        return (casing, out)
    }

    /// Kind styling only (see `route`).
    static func segments(for candidate: Candidate, fraction: Double, metresPerPoint: Double? = nil) -> [Segment] {
        route(for: candidate, fraction: fraction, metresPerPoint: metresPerPoint).lead
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

    /// Styled run kinds at a scale, one entry per run (a dashed run's bed and dashes count once).
    static func layerKinds(for candidate: Candidate, metresPerPoint: Double) -> [String] {
        var kinds: [String] = []
        for seg in segments(for: candidate, fraction: 1, metresPerPoint: metresPerPoint) where !seg.isDash {
            kinds.append(seg.isBed ? "path" : seg.layerKind)
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
