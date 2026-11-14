import Foundation

/// Where Loop works: a simplified outline bundled with the app (`coverage.geojson`), so the phone can say
/// "Loop covers New York City for now" before a request. The check runs on the phone; the location never
/// goes to the server for this. Names come from the file's `properties.name`, never from code.
struct Coverage: Equatable {
    struct Polygon: Equatable {
        var outer: [GeoPoint]
        var holes: [[GeoPoint]] = []
    }
    let name: String
    let polygons: [Polygon]

    func contains(_ p: GeoPoint) -> Bool {
        polygons.contains { Self.inside(p, ring: $0.outer) && !$0.holes.contains { Self.inside(p, ring: $0) } }
    }

    /// Even-odd ray cast on lon/lat: fine at the scale of a city.
    private static func inside(_ p: GeoPoint, ring: [GeoPoint]) -> Bool {
        guard ring.count >= 3 else { return false }
        var inside = false
        var j = ring.count - 1
        for i in 0..<ring.count {
            let a = ring[i], b = ring[j]
            if (a.lat > p.lat) != (b.lat > p.lat),
               p.lon < (b.lon - a.lon) * (p.lat - a.lat) / (b.lat - a.lat) + a.lon {
                inside.toggle()
            }
            j = i
        }
        return inside
    }

    // MARK: GeoJSON

    private struct Collection: Decodable {
        struct Feature: Decodable {
            struct Properties: Decodable { let name: String? }
            let properties: Properties?
            let geometry: Geometry
        }
        struct Geometry: Decodable {
            let type: String
            let coordinates: JSONValue
        }
        let features: [Feature]
    }

    /// A FeatureCollection with a Polygon or MultiPolygon (lon/lat) and `properties.name`. nil if it isn't one.
    static func decode(_ data: Data) -> Coverage? {
        guard let c = try? JSONDecoder().decode(Collection.self, from: data), let f = c.features.first,
              let name = f.properties?.name, !name.isEmpty else { return nil }
        func ring(_ v: JSONValue) -> [GeoPoint]? {
            guard case let .array(points) = v else { return nil }
            let out: [GeoPoint] = points.compactMap {
                guard case let .array(xy) = $0, xy.count >= 2, case let .number(x) = xy[0], case let .number(y) = xy[1] else { return nil }
                return GeoPoint(lon: x, lat: y)
            }
            return out.count == points.count ? out : nil
        }
        func polygon(_ v: JSONValue) -> Polygon? {
            guard case let .array(rings) = v, let first = rings.first, let outer = ring(first) else { return nil }
            return Polygon(outer: outer, holes: rings.dropFirst().compactMap(ring))
        }
        var polygons: [Polygon] = []
        switch f.geometry.type {
        case "Polygon":
            if let p = polygon(f.geometry.coordinates) { polygons = [p] }
        case "MultiPolygon":
            if case let .array(items) = f.geometry.coordinates { polygons = items.compactMap(polygon) }
        default: break
        }
        return polygons.isEmpty ? nil : Coverage(name: name, polygons: polygons)
    }

    /// The bundled outline; nil until the file is in the app (then no landing line, never a guess).
    static func loadBundled(bundle: Bundle = .main) -> Coverage? {
        guard let url = bundle.url(forResource: "coverage", withExtension: "geojson"),
              let data = try? Data(contentsOf: url) else { return nil }
        return decode(data)
    }
}
