import Foundation

/// The saved route file (`Fixtures/kips3-ui.json`), decoded as written by the engine.
/// Only the fields the app shows are decoded. The ranking score and the ranking's
/// once-per-crosswalk lights value are left out on purpose, so they cannot reach the screen.
struct RouteFile: Decodable {
    let about: About
    let request: [RequestItem]
    let route: FeatureCollection
    let top3: [TopCandidate]
    let pool: Pool

    struct About: Decodable {
        let generatedAt: String
        let start: String
    }

    struct RequestItem: Decodable {
        let key: String
        let title: String
        let value: String
        let origin: String
    }

    struct FeatureCollection: Decodable {
        let features: [Feature]
    }

    struct Feature: Decodable {
        let geometry: Geometry
        let properties: Properties
    }

    enum Geometry: Decodable {
        case point(GeoPoint)
        case lineString([GeoPoint])

        private enum CodingKeys: String, CodingKey { case type, coordinates }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            switch try c.decode(String.self, forKey: .type) {
            case "Point":
                let xy = try c.decode([Double].self, forKey: .coordinates)
                self = .point(GeoPoint(lon: xy[0], lat: xy[1]))
            case "LineString":
                let xys = try c.decode([[Double]].self, forKey: .coordinates)
                self = .lineString(xys.map { GeoPoint(lon: $0[0], lat: $0[1]) })
            case let other:
                throw DecodingError.dataCorruptedError(forKey: .type, in: c,
                    debugDescription: "Unsupported geometry \(other)")
            }
        }

        var lineString: [GeoPoint]? {
            if case let .lineString(points) = self { return points }
            return nil
        }

        var point: GeoPoint? {
            if case let .point(p) = self { return p }
            return nil
        }
    }

    /// Feature properties. The route, its points and its stretches share one shape here;
    /// each feature fills only its own fields.
    struct Properties: Decodable {
        // route line
        let kind: String?
        /// The request as the engine read it (the route line's own properties; used for the card).
        let request: [RequestItem]?
        let elevation: Elevation?
        let summary: Summary?
        // points
        let feature: String?
        let mile: Int?
        let alongM: Double?
        let alongMi: Double?
        let status: String?
        let source: String?
        // stretches and pieces
        let stretch: Int?
        let piece: Int?
        let stretchName: String?
        let name: String?
        let fromMile: Double?
        let toMile: Double?
        let lengthM: Double?
        let signals: Valued<Int>?
        let elevationGainM: Valued<Double>?
        let crowd: Crowd?
        let composition: Composition?
        let facts: [Fact]?
    }

    struct Valued<T: Decodable>: Decodable {
        let value: T?
        let status: String
    }

    struct Crowd: Decodable {
        let value: String?
        let status: String
        let basis: String?
    }

    struct Composition: Decodable {
        let waterfrontM: Double
        let parkM: Double
        let pathM: Double
        let streetM: Double
        let status: String
        let source: String
    }

    struct Fact: Decodable {
        let text: String
        let source: String
        let trust: String
    }

    struct Elevation: Decodable {
        let status: String
        let source: String
        let profile: [ProfilePoint]
    }

    struct ProfilePoint: Decodable, Equatable {
        let mile: Double
        let elevationM: Double
    }

    /// A number with its trust label and where it came from. The server sends `value: null` with
    /// status "not_scored" whenever it can't score something (no elevation, no stretches, crowds
    /// outside 7 am to 8 pm and on Sundays): a missing value is normal, never a decode failure.
    struct Measure: Decodable {
        let value: Double?
        let status: String
        let source: String?
        let unit: String?
        let meters: Double?

        /// The route's length in miles. The one number a route can't do without: if the value is
        /// missing, the measured metres stand in.
        var miles: Double { value ?? (meters ?? 0) / 1609.344 }
    }

    struct CrowdMeasure: Decodable {
        let value: Double?
        let status: String
        let source: String?
        let notScoredPct: Double?
    }

    struct RankMeasure: Decodable {
        let value: Int?
        let status: String
        let of: Int?
    }

    struct Summary: Decodable {
        let distance: Measure
        let kind: String
        let waterfrontPct: Measure
        let parkPct: Measure
        let pathPct: Measure
        let streetPct: Measure
        /// Every signalized crossing, each time the route crosses (decision 020).
        let signalizedCrossings: Measure
        /// Lights a mile, counting every crossing. This is the card's value.
        let lightsPerMile: Measure
        let climb: Measure
        let crowds: CrowdMeasure
        let turnarounds: [Measure]
        let rank: RankMeasure
        /// One line on why the route fits, written by the server from the route's own numbers (decision 049).
        /// Absent in older files; its `text` is null when nothing stands out.
        let reason: Reason?
        /// Turn-by-turn maneuvers in order (decision 054). The key is absent for routes that weren't routed
        /// (run-again, stored lines) and in older files: the stretch list stands in then.
        let steps: [Turn]?
    }

    /// One maneuver from the server's turn instructions. `street` is null for a turn onto the street the
    /// runner is already on, and for the finish.
    struct Turn: Decodable, Equatable {
        let index: Int
        let maneuver: String
        let street: String?
        let fromMile: Double
        let fromMeters: Double?
        let distance: Measure
        let trust: String?
        let source: String?

        static func == (a: Turn, b: Turn) -> Bool {
            a.index == b.index && a.maneuver == b.maneuver && a.street == b.street && a.fromMile == b.fromMile
        }
    }

    struct Reason: Decodable {
        let text: String?
        let status: String?
        let source: String?
    }

    struct TopCandidate: Decodable {
        /// The server's route id: the same for the same route in every event of one build (absent in
        /// the bundled file).
        let id: String?
        let rank: Int
        let kind: String
        let label: String
        let distance: Measure
        let geometry: Geometry
        /// The route in full, same as `route` is for the first (final events since decision 049):
        /// summary, markers, stretches and pieces. Absent in top3 and provisional events and in older files.
        let file: FeatureCollection?
    }

    struct Pool: Decodable {
        let candidates: Int
        let bestOf: Int
    }

    static func decode(_ data: Data) throws -> RouteFile {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(RouteFile.self, from: data)
    }

    static func loadBundled(named name: String = "kips3-ui", bundle: Bundle = .main) throws -> RouteFile {
        guard let url = bundle.url(forResource: name, withExtension: "json") else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try decode(Data(contentsOf: url))
    }
}
