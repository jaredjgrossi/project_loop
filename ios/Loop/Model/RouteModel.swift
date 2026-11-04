import Foundation

/// The three ways a stretch is drawn. Never told apart by color alone:
/// waterfront is solid and wide, path is dashed, street is solid and thinner.
enum DrawKind: String, CaseIterable {
    case waterfront, path, street

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
    let miles: [MileMark]
    let turnaround: Turnaround?
    let start: GeoPoint
    let profile: [RouteFile.ProfilePoint]
    let profileTrust: Trust
    let summary: RouteFile.Summary

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

/// One of the top 3. Only the file's #1 carries full detail; the others are outlines.
struct Candidate: Identifiable {
    let rank: Int
    let line: Polyline
    let distanceMi: Double
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
                                   parkM: comp.parkM, streetM: comp.streetM))
        }.sorted { $0.index < $1.index }

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
            stretches: stretches, miles: miles, turnaround: turnaround, start: start,
            profile: elevation.profile, profileTrust: Trust(elevation.status),
            summary: summary)

        candidates = file.top3.compactMap { t in
            guard let coords = t.geometry.lineString, coords.count >= 2 else { return nil }
            return Candidate(
                rank: t.rank,
                line: t.rank == 1 ? line : Polyline(coords),
                distanceMi: t.rank == 1 ? summary.distance.value : t.distanceMi,
                kindText: CardText.kindText(t.kind),
                detail: t.rank == 1 ? detail : nil)
        }.sorted { $0.rank < $1.rank }

        bestOf = file.pool.bestOf
        request = CardText.request(items: file.request, about: file.about)
    }
}
