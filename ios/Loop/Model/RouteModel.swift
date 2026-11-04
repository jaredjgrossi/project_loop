import Foundation

/// The three ways a piece of route is drawn. Never told apart by color alone:
/// waterfront is solid and wide, path is dashed, street is solid and thinner.
enum DrawKind: String, CaseIterable {
    case waterfront, path, street

    /// The file's piece kinds. Park is drawn as path (dashed) for now.
    init?(pieceKind: String) {
        switch pieceKind {
        case "waterfront": self = .waterfront
        case "path", "park": self = .path
        case "street": self = .street
        default: return nil
        }
    }

    /// The stretch's largest measured share decides how it is drawn (first slice).
    /// Park metres count as path (off-street). Ties go waterfront, then path, then street.
    static func largestShare(_ c: RouteFile.Composition) -> DrawKind {
        let shares: [(DrawKind, Double)] = [
            (.waterfront, c.waterfrontM),
            (.path, c.pathM + c.parkM),
            (.street, c.streetM),
        ]
        var best = shares[0]
        for s in shares.dropFirst() where s.1 > best.1 { best = s }
        return best.0
    }

    var legend: String { rawValue }
}

/// A trust label as shown beside a number.
struct Trust: Equatable {
    let raw: String
    init(_ raw: String) { self.raw = raw }
    /// "not_scored" reads as "not scored".
    var text: String { raw.replacingOccurrences(of: "_", with: " ") }
}

struct Stretch: Equatable {
    let index: Int
    let name: String
    let kind: DrawKind
    let fromMile: Double
    let toMile: Double
    /// Along-route metres on the route line, scaled so the stretches tile the line exactly.
    let fromM: Double
    let toM: Double
    let composition: Composition
    /// The file's crowd band for this stretch ("low", "medium", "high"), nil when not scored.
    let crowd: String?
    let crowdTrust: Trust
    var lengthM: Double { toM - fromM }

    struct Composition: Equatable {
        let waterfrontM, pathM, parkM, streetM: Double
    }
}

struct MileMark: Equatable {
    let mile: Int
    let point: GeoPoint
    let alongM: Double
    let alongMi: Double
    let trust: Trust
}

struct Turnaround: Equatable {
    let point: GeoPoint
    let alongM: Double
    let alongMi: Double
}

/// Everything the card and map need about one fully described route (the file's #1).
struct RouteDetail {
    let line: Polyline
    let kindText: String
    let distanceMi: Double
    let distanceTrust: Trust
    let stretches: [Stretch]
    /// How the line is drawn, from the file's pieces (merged under 20 m).
    let drawn: [DrawnPiece]
    let miles: [MileMark]
    let turnaround: Turnaround?
    let start: GeoPoint
    let profile: [RouteFile.ProfilePoint]
    let profileTrust: Trust
    let summary: RouteFile.Summary

    /// One bar on the profile strip.
    struct StripRun: Equatable {
        let kind: DrawKind
        let fromMile: Double
        let toMile: Double
        let dashed: Bool
    }

    /// The map's merged runs at the strip's scale: runs under 16 pt join their longer neighbour,
    /// same-kind neighbours join with no gap, and path is dashed only if it fits two full strip
    /// dashes (4 on, 2.5 off: 10.5 pt). Otherwise path is a solid bar in route-path.
    static let stripMinimumRunPoints: Double = 16
    static let stripDash: (on: Double, off: Double) = (4, 2.5)

    func stripRuns(width: Double) -> [StripRun] {
        guard width > 0, line.length > 0 else { return [] }
        let mpp = line.length / width
        let runs = DrawnPiece.merged(drawn.map { ($0.kind, $0.lengthM) }, lineLength: line.length,
                                     minimum: Self.stripMinimumRunPoints * mpp)
        let twoDashes = 2 * Self.stripDash.on + Self.stripDash.off
        return runs.map {
            StripRun(kind: $0.kind,
                     fromMile: $0.fromM / line.length * distanceMi,
                     toMile: $0.toM / line.length * distanceMi,
                     dashed: $0.kind == .path && $0.lengthM / mpp >= twoDashes)
        }
    }

    func stretch(atMile mile: Double) -> Stretch? {
        stretches.first { mile >= $0.fromMile && mile < $0.toMile } ?? stretches.last { mile >= $0.fromMile }
    }

    /// Elevation in metres at a mile, linear between profile points, flat past the ends.
    func elevation(atMile mile: Double) -> Double {
        guard let first = profile.first, let last = profile.last else { return 0 }
        if mile <= first.mile { return first.elevationM }
        if mile >= last.mile { return last.elevationM }
        for (a, b) in zip(profile, profile.dropFirst()) where mile >= a.mile && mile <= b.mile {
            let t = b.mile > a.mile ? (mile - a.mile) / (b.mile - a.mile) : 0
            return a.elevationM + (b.elevationM - a.elevationM) * t
        }
        return last.elevationM
    }
}

/// A run of route drawn one way, by along-route metres on the route line.
struct DrawnPiece: Equatable {
    let kind: DrawKind
    let fromM: Double
    let toM: Double
    var lengthM: Double { toM - fromM }

    static let minimumDrawnLength: Double = 20

    /// For drawing only: every piece shorter than `minimum` metres joins its longer neighbour
    /// (shortest first), then neighbours of the same kind join up. `pieces` are in route order;
    /// lengths are scaled so the result tiles a line of `lineLength` exactly.
    static func merged(_ pieces: [(kind: DrawKind, lengthM: Double)], lineLength: Double,
                       minimum: Double = minimumDrawnLength) -> [DrawnPiece] {
        var runs = pieces.map { (kind: $0.kind, length: $0.lengthM) }
        while runs.count > 1, let i = runs.indices.filter({ runs[$0].length < minimum })
                .min(by: { runs[$0].length < runs[$1].length }) {
            let prev = i > 0 ? i - 1 : nil
            let next = i < runs.count - 1 ? i + 1 : nil
            let into: Int
            switch (prev, next) {
            case let (p?, n?): into = runs[p].length >= runs[n].length ? p : n
            case let (p?, nil): into = p
            case let (nil, n?): into = n
            default: return []
            }
            runs[into].length += runs[i].length
            runs.remove(at: i)
        }
        var joined: [(kind: DrawKind, length: Double)] = []
        for r in runs {
            if let last = joined.last, last.kind == r.kind { joined[joined.count - 1].length += r.length }
            else { joined.append(r) }
        }
        let total = joined.reduce(0) { $0 + $1.length }
        guard total > 0 else { return [] }
        var out: [DrawnPiece] = []
        var at = 0.0
        for (i, r) in joined.enumerated() {
            let end = i == joined.count - 1 ? lineLength : at + r.length / total * lineLength
            out.append(DrawnPiece(kind: r.kind, fromM: at, toM: end))
            at = end
        }
        return out
    }
}

/// Screen scale for zoom-dependent drawing (Mapbox: 512 pt tiles, Web Mercator).
enum MapScale {
    static func metresPerPoint(zoom: Double, latitude: Double) -> Double {
        cos(latitude * .pi / 180) * 40_075_016.686 / (512 * pow(2, zoom))
    }
    /// Runs shorter than this on screen join their longer neighbour.
    static let minimumRunPoints: Double = 40
    /// A path run is dashed only when it fits at least two full 9/6 pt dashes.
    static let minimumDashedPoints: Double = 30
}

/// One of the top 3. Only the file's #1 carries full detail; the others are outlines.
struct Candidate: Identifiable {
    let rank: Int
    let line: Polyline
    let distanceMi: Double
    /// The file's trust label for the distance (nil if the file gives none).
    let distanceTrust: Trust?
    let kindText: String
    let detail: RouteDetail?
    var id: Int { rank }
}

/// The request as shown at the top of the screen.
struct RequestCard: Equatable {
    let text: String
    let provenance: String
    let startHourText: String
}

/// The decoded file turned into what the screen uses.
struct LoopData {
    let request: RequestCard
    let candidates: [Candidate]
    let bestOf: Int

    func candidate(rank: Int) -> Candidate? { candidates.first { $0.rank == rank } }

    init(file: RouteFile) throws {
        guard let routeFeature = file.route.features.first,
              let routeCoords = routeFeature.geometry.lineString,
              let summary = routeFeature.properties.summary
        else { throw CocoaError(.coderValueNotFound) }

        let line = Polyline(routeCoords)
        let features = file.route.features

        // Stretches: mile ranges from the file, mapped onto the route line in proportion
        // so they tile it exactly (the file's miles and the line length agree to a few metres).
        let totalMi = summary.distance.value
        let stretches: [Stretch] = features.compactMap { f in
            let p = f.properties
            guard p.feature == "stretch", let idx = p.stretch, let name = p.name,
                  let from = p.fromMile, let to = p.toMile, let comp = p.composition else { return nil }
            return Stretch(
                index: idx, name: name, kind: DrawKind.largestShare(comp),
                fromMile: from, toMile: to,
                fromM: line.length * from / totalMi, toM: line.length * to / totalMi,
                composition: .init(waterfrontM: comp.waterfrontM, pathM: comp.pathM,
                                   parkM: comp.parkM, streetM: comp.streetM),
                crowd: p.crowd?.value, crowdTrust: Trust(p.crowd?.status ?? "not_scored"))
        }.sorted { $0.index < $1.index }

        let pieces: [(kind: DrawKind, lengthM: Double)] = features
            .filter { $0.properties.feature == "piece" }
            .sorted { ($0.properties.piece ?? 0) < ($1.properties.piece ?? 0) }
            .compactMap { f in
                guard let k = f.properties.kind.flatMap(DrawKind.init(pieceKind:)), let len = f.properties.lengthM else { return nil }
                return (k, len)
            }
        let drawn = DrawnPiece.merged(pieces, lineLength: line.length)

        let miles: [MileMark] = features.compactMap { f in
            let p = f.properties
            guard p.feature == "mile", let m = p.mile, let pt = f.geometry.point,
                  let alongM = p.alongM, let alongMi = p.alongMi else { return nil }
            return MileMark(mile: m, point: pt, alongM: alongM, alongMi: alongMi,
                            trust: Trust(p.status ?? "measured"))
        }.sorted { $0.mile < $1.mile }

        let turnaround: Turnaround? = features.first { $0.properties.feature == "turnaround" }.flatMap { f in
            guard let pt = f.geometry.point, let m = f.properties.alongM, let mi = f.properties.alongMi else { return nil }
            return Turnaround(point: pt, alongM: m, alongMi: mi)
        }

        // The start point is the first Point feature without a `feature` tag.
        let start = features.first { $0.properties.feature == nil && $0.geometry.point != nil }?
            .geometry.point ?? routeCoords[0]

        guard let elevation = routeFeature.properties.elevation else { throw CocoaError(.coderValueNotFound) }

        let detail = RouteDetail(
            line: line,
            kindText: CardText.kindText(summary.kind),
            distanceMi: summary.distance.value,
            distanceTrust: Trust(summary.distance.status),
            stretches: stretches, drawn: drawn, miles: miles, turnaround: turnaround, start: start,
            profile: elevation.profile, profileTrust: Trust(elevation.status),
            summary: summary)

        candidates = file.top3.compactMap { t in
            guard let coords = t.geometry.lineString, coords.count >= 2 else { return nil }
            return Candidate(
                rank: t.rank,
                line: t.rank == 1 ? line : Polyline(coords),
                distanceMi: t.rank == 1 ? summary.distance.value : t.distance.value,
                distanceTrust: Trust(t.rank == 1 ? summary.distance.status : t.distance.status),
                kindText: CardText.kindText(t.kind),
                detail: t.rank == 1 ? detail : nil)
        }.sorted { $0.rank < $1.rank }

        bestOf = file.pool.bestOf
        request = CardText.request(items: file.request, about: file.about)
    }
}
