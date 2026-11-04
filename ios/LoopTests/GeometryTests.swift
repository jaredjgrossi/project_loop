import XCTest
@testable import Loop

final class GeometryTests: XCTestCase {

    // A 3-point line along a meridian: 0 → ~111 m → ~222 m.
    private let line = Polyline([
        GeoPoint(lon: 10.0, lat: 50.0000),
        GeoPoint(lon: 10.0, lat: 50.0010),
        GeoPoint(lon: 10.0, lat: 50.0020),
    ])

    func testHaversineOneThousandthDegreeLatitude() {
        let d = GeoPoint(lon: 0, lat: 0).distance(to: GeoPoint(lon: 0, lat: 0.001))
        XCTAssertEqual(d, 111.195, accuracy: 0.01)
    }

    func testLengthIsSumOfSegments() {
        XCTAssertEqual(line.length, 2 * 111.195, accuracy: 0.05)
    }

    func testPointAtDistanceInterpolatesAndClamps() {
        XCTAssertEqual(line.point(at: -5), line.points[0])
        XCTAssertEqual(line.point(at: line.length + 5), line.points[2])
        let mid = line.point(at: line.length / 2)
        XCTAssertEqual(mid.lat, 50.0010, accuracy: 1e-9)
        let quarter = line.point(at: line.length / 4)
        XCTAssertEqual(quarter.lat, 50.0005, accuracy: 1e-7)
    }

    func testSliceHasExactEndsAndLength() {
        let s = Polyline(line.slice(from: 50, to: 180))
        XCTAssertEqual(s.length, 130, accuracy: 0.01)
        XCTAssertEqual(s.points.count, 3, "cut, middle vertex, cut")
        XCTAssertTrue(line.slice(from: 100, to: 100).isEmpty)
        XCTAssertTrue(line.slice(from: 120, to: 80).isEmpty)
    }

    func testResamplePreservesEndsAndSpacing() {
        let r = line.resampled(count: 5)
        XCTAssertEqual(r.count, 5)
        XCTAssertEqual(r.first, line.points.first)
        XCTAssertEqual(r.last, line.points.last)
        let spacing = r[0].distance(to: r[1])
        for (a, b) in zip(r, r.dropFirst()) {
            XCTAssertEqual(a.distance(to: b), spacing, accuracy: 0.01)
        }
    }

    func testBlendEndpoints() {
        let a = line.resampled(count: 4)
        let b = a.map { GeoPoint(lon: $0.lon + 0.01, lat: $0.lat) }
        XCTAssertEqual(blend(a, b, 0), a)
        XCTAssertEqual(blend(a, b, 1), b)
        XCTAssertEqual(blend(a, b, 0.5)[0].lon, a[0].lon + 0.005, accuracy: 1e-12)
    }
}
