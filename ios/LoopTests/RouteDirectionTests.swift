import XCTest
@testable import Loop

/// Direction arrows are drawn on the first pass only: the way back along the same line has none, so
/// an out-and-back never shows arrows pointing both ways on top of each other.
final class RouteDirectionTests: XCTestCase {
    private let origin = GeoPoint(lon: -73.98, lat: 40.74)

    /// A point `east` and `north` metres from the origin.
    private func pt(_ east: Double, _ north: Double) -> GeoPoint {
        GeoPoint(lon: origin.lon + east / (111_320 * cos(origin.lat * .pi / 180)), lat: origin.lat + north / 111_320)
    }

    private func length(_ runs: [[GeoPoint]]) -> Double {
        runs.reduce(0) { $0 + ($1.count >= 2 ? Polyline($1).length : 0) }
    }

    func testOutAndBackKeepsOnlyTheWayOut() {
        let out = stride(from: 0.0, through: 1000, by: 50).map { pt($0, 0) }
        let back = out.reversed().dropFirst().map { $0 }
        let runs = RouteDirection.firstPass(of: out + back)
        XCTAssertEqual(length(runs), 1000, accuracy: 60, "the outbound kilometre, not the 2 km line")
        // Every kept piece runs the way the route goes out (east).
        for r in runs { XCTAssertGreaterThan(r.last!.lon, r.first!.lon) }
    }

    func testALoopKeepsAllOfIt() {
        let square = [pt(0, 0), pt(500, 0), pt(500, 500), pt(0, 500), pt(0, 0)]
        let runs = RouteDirection.firstPass(of: square)
        XCTAssertEqual(length(runs), 2000, accuracy: 60)
    }

    func testALollipopLosesTheStickOnTheWayBack() {
        let stick = [pt(0, 0), pt(600, 0)]
        let loop = [pt(600, 0), pt(600, 400), pt(900, 400), pt(900, 0), pt(600, 0)]
        let line = stick + loop.dropFirst() + [pt(0, 0)]
        let runs = RouteDirection.firstPass(of: line)
        // Out 600 + loop 1400 = 2000; the 600 m back along the stick is dropped.
        XCTAssertEqual(length(runs), 2000, accuracy: 80)
    }

    func testACrossingIsNotARetrace() {
        // A figure of eight crosses itself once: nothing is dropped.
        let line = [pt(0, 0), pt(400, 400), pt(400, 0), pt(0, 400), pt(0, 0)]
        let total = Polyline(line).length
        XCTAssertEqual(length(RouteDirection.firstPass(of: line)), total, accuracy: 60)
    }

    func testTinyInput() {
        XCTAssertTrue(RouteDirection.firstPass(of: []).isEmpty)
        XCTAssertTrue(RouteDirection.firstPass(of: [pt(0, 0)]).isEmpty)
    }
}
