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

/// Tap hit-testing against a route drawn on screen.
enum RouteHit {
    /// The tap distance that still counts as touching the line, at any zoom.
    static let tolerance: CGFloat = 22

    /// Nearest point to `tap` on the route as projected to the screen. `projected[i]` is vertex i
    /// on screen and `cumulative[i]` its along-route metres. Returns the along-route metres of the
    /// nearest point and its distance from the tap in points. On an out-and-back, where outbound and
    /// return overlap, a tie goes to the earlier (outbound) segment.
    static func nearest(to tap: CGPoint, projected: [CGPoint], cumulative: [Double]) -> (alongM: Double, distance: CGFloat)? {
        guard projected.count >= 2, projected.count == cumulative.count else { return nil }
        var best: (alongM: Double, distance: CGFloat)?
        for i in 0..<(projected.count - 1) {
            let a = projected[i], b = projected[i + 1]
            let dx = b.x - a.x, dy = b.y - a.y
            let len2 = dx * dx + dy * dy
            let t = len2 > 0 ? max(0, min(1, ((tap.x - a.x) * dx + (tap.y - a.y) * dy) / len2)) : 0
            let p = CGPoint(x: a.x + dx * t, y: a.y + dy * t)
            let d = hypot(tap.x - p.x, tap.y - p.y)
            if best == nil || d < best!.distance {
                best = (cumulative[i] + Double(t) * (cumulative[i + 1] - cumulative[i]), d)
            }
        }
        return best
    }
}

/// The route line as drawn at one zoom: the full-resolution line with jogs too small to see at
/// that scale removed (Douglas–Peucker over the whole line at once), plus a map from along-route
/// metres on the full line to along-route metres on the drawn line, so runs and dashes are cut
/// from the drawn line at the right places. Display only; the full line stays the source of truth.
struct DisplayLine {
    let line: Polyline
    /// For each drawn vertex, its along-route metres on the full line.
    let fullAlong: [Double]

    /// Jogs smaller than this on screen are removed (the route line is 4.5 pt wide).
    static let tolerancePoints: Double = 2.5

    init(full: Polyline, toleranceMetres: Double) {
        let keep = DisplayLine.simplify(full.points, tolerance: toleranceMetres)
        line = Polyline(keep.map { full.points[$0] })
        fullAlong = keep.map { full.cumulative[$0] }
    }

    /// Along-route metres on the drawn line for along-route metres on the full line.
    func along(fromFull a: Double) -> Double {
        if a <= fullAlong[0] { return 0 }
        guard let last = fullAlong.last, a < last else { return line.length }
        var lo = 0, hi = fullAlong.count - 1
        while hi - lo > 1 {
            let mid = (lo + hi) / 2
            if fullAlong[mid] <= a { lo = mid } else { hi = mid }
        }
        let span = fullAlong[hi] - fullAlong[lo]
        let t = span > 0 ? (a - fullAlong[lo]) / span : 0
        return line.cumulative[lo] + t * (line.cumulative[hi] - line.cumulative[lo])
    }

    /// Indices of the vertices Douglas–Peucker keeps (local metres, equirectangular).
    static func simplify(_ pts: [GeoPoint], tolerance: Double) -> [Int] {
        guard pts.count > 2, tolerance > 0 else { return Array(pts.indices) }
        let lat0 = pts[0].lat * .pi / 180
        let mx = 111_320 * cos(lat0), my = 110_574.0
        let xy = pts.map { (($0.lon - pts[0].lon) * mx, ($0.lat - pts[0].lat) * my) }
        var keep = [Bool](repeating: false, count: pts.count)
        keep[0] = true; keep[pts.count - 1] = true
        var stack = [(0, pts.count - 1)]
        while let (a, b) = stack.popLast() {
            guard b > a + 1 else { continue }
            let (ax, ay) = xy[a], (bx, by) = xy[b]
            let dx = bx - ax, dy = by - ay, l2 = dx * dx + dy * dy
            var worst = -1.0, idx = -1
            for i in (a + 1)..<b {
                let (px, py) = xy[i]
                let t = l2 > 0 ? max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / l2)) : 0
                let d = hypot(px - (ax + dx * t), py - (ay + dy * t))
                if d > worst { worst = d; idx = i }
            }
            if worst > tolerance {
                keep[idx] = true
                stack.append((a, idx)); stack.append((idx, b))
            }
        }
        return keep.indices.filter { keep[$0] }
    }
}
