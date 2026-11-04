import CoreLocation
import Foundation

/// A WGS84 coordinate. Plain value type so geometry code stays testable without MapKit or Mapbox.
struct GeoPoint: Hashable {
    var lon: Double
    var lat: Double

    var coordinate: CLLocationCoordinate2D { CLLocationCoordinate2D(latitude: lat, longitude: lon) }

    /// Great-circle distance in metres (haversine, mean Earth radius).
    func distance(to other: GeoPoint) -> Double {
        let r = 6_371_008.8
        let φ1 = lat * .pi / 180, φ2 = other.lat * .pi / 180
        let dφ = φ2 - φ1
        let dλ = (other.lon - lon) * .pi / 180
        let h = sin(dφ / 2) * sin(dφ / 2) + cos(φ1) * cos(φ2) * sin(dλ / 2) * sin(dλ / 2)
        return 2 * r * asin(min(1, sqrt(h)))
    }

    /// Straight-line interpolation. Fine at route scale (segments of tens of metres).
    static func lerp(_ a: GeoPoint, _ b: GeoPoint, _ t: Double) -> GeoPoint {
        GeoPoint(lon: a.lon + (b.lon - a.lon) * t, lat: a.lat + (b.lat - a.lat) * t)
    }
}

enum Units {
    static let metresPerMile = 1_609.344
}

/// A line with its cumulative length, for along-route lookups.
struct Polyline: Equatable {
    let points: [GeoPoint]
    /// cumulative[i] is the distance in metres from the first point to points[i].
    let cumulative: [Double]

    init(_ points: [GeoPoint]) {
        precondition(points.count >= 2, "A polyline needs two points")
        self.points = points
        var acc: [Double] = [0]
        acc.reserveCapacity(points.count)
        for i in 1..<points.count {
            acc.append(acc[i - 1] + points[i - 1].distance(to: points[i]))
        }
        cumulative = acc
    }

    var length: Double { cumulative[cumulative.count - 1] }

    /// The point `distance` metres along the line, clamped to the ends.
    func point(at distance: Double) -> GeoPoint {
        if distance <= 0 { return points[0] }
        if distance >= length { return points[points.count - 1] }
        let i = segmentIndex(containing: distance)
        let segLen = cumulative[i + 1] - cumulative[i]
        let t = segLen > 0 ? (distance - cumulative[i]) / segLen : 0
        return GeoPoint.lerp(points[i], points[i + 1], t)
    }

    /// The part of the line between two along-distances, with exact cut points at both ends.
    /// Returns an empty array when the range is empty.
    func slice(from start: Double, to end: Double) -> [GeoPoint] {
        let a = max(0, min(start, length))
        let b = max(0, min(end, length))
        guard b > a else { return [] }
        var out = [point(at: a)]
        for i in points.indices where cumulative[i] > a && cumulative[i] < b {
            out.append(points[i])
        }
        out.append(point(at: b))
        return out
    }

    /// `count` points evenly spaced by distance, first and last kept exactly.
    func resampled(count: Int) -> [GeoPoint] {
        precondition(count >= 2)
        return (0..<count).map { point(at: length * Double($0) / Double(count - 1)) }
    }

    /// Along-distance of the vertex nearest to `p` (vertex-level, enough for snapping markers).
    func alongDistance(nearest p: GeoPoint) -> Double {
        var best = 0, bestD = Double.infinity
        for (i, q) in points.enumerated() {
            let d = q.distance(to: p)
            if d < bestD { bestD = d; best = i }
        }
        return cumulative[best]
    }

    private func segmentIndex(containing distance: Double) -> Int {
        // Binary search for the last cumulative value <= distance.
        var lo = 0, hi = cumulative.count - 1
        while hi - lo > 1 {
            let mid = (lo + hi) / 2
            if cumulative[mid] <= distance { lo = mid } else { hi = mid }
        }
        return lo
    }
}

/// Point-by-point blend of two lines with the same number of points.
func blend(_ a: [GeoPoint], _ b: [GeoPoint], _ t: Double) -> [GeoPoint] {
    precondition(a.count == b.count)
    return zip(a, b).map { GeoPoint.lerp($0, $1, t) }
}
