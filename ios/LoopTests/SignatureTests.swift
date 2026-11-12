import XCTest
@testable import Loop

/// The pure parts of the signature moments (signature-moments-v1): the ink's timing, bearings for
/// the flyover, and the line art's geometry and privacy trim.
@MainActor
final class SignatureTests: XCTestCase {

    // MARK: D. Ink

    func testInkEasesFromStartToEndAndItsInverseAgrees() {
        XCTAssertEqual(MainModel.inkEase(0), 0)
        XCTAssertEqual(MainModel.inkEase(1), 1)
        XCTAssertEqual(MainModel.inkEase(0.5), 0.5, accuracy: 1e-9)
        // A tick for a mile a third of the way along lands when the ink is a third of the way along.
        for p in [0.1, 1.0 / 3, 0.5, 0.9] {
            XCTAssertEqual(MainModel.inkEase(MainModel.inkTime(forProgress: p)), p, accuracy: 1e-4)
        }
    }

    func testInkTakesAboutASecondAndNeverLong() throws {
        let model = MainModel(data: try LoopData(file: RouteFile.loadBundled()), runs: RunStore())
        XCTAssertEqual(model.inkDuration(lengthM: 3 * 1609.344), 0.99, accuracy: 0.01)
        XCTAssertEqual(model.inkDuration(lengthM: 26 * 1609.344), 1.5)
    }

    func testPencilBeforeTheFlagAndInkAfter() throws {
        let model = MainModel(data: try LoopData(file: RouteFile.loadBundled()), runs: RunStore())
        model.build = BuildState()
        model.build.apply(.top3([1, 2, 3]), at: 100)
        XCTAssertNil(model.inkProgress(now: 101, reduceMotion: false), "no ink until the flag")
        model.build.apply(.provisional, at: 102)
        XCTAssertEqual(model.inkProgress(now: 102, reduceMotion: false), 0)
        XCTAssertEqual(model.inkProgress(now: 110, reduceMotion: false), 1)
        XCTAssertEqual(model.inkProgress(now: 102, reduceMotion: true), 1, "Reduce Motion: inked at once")
    }

    // MARK: E. Flyover

    func testBearings() {
        let a = GeoPoint(lon: -73.98, lat: 40.74)
        XCTAssertEqual(a.bearing(to: GeoPoint(lon: -73.98, lat: 40.75)), 0, accuracy: 0.01)
        XCTAssertEqual(a.bearing(to: GeoPoint(lon: -73.97, lat: 40.74)), 90, accuracy: 0.01)
        XCTAssertEqual(a.bearing(to: GeoPoint(lon: -73.98, lat: 40.73)), 180, accuracy: 0.01)
        XCTAssertEqual(a.bearing(to: GeoPoint(lon: -73.99, lat: 40.74)), 270, accuracy: 0.01)
    }

    // MARK: F. The runs as line art

    func testLineArtKeepsOneFrameAndItsShape() {
        let ink = RunsInk(runs: [
            [GeoPoint(lon: -74.00, lat: 40.70), GeoPoint(lon: -73.98, lat: 40.70)],
            [GeoPoint(lon: -73.99, lat: 40.70), GeoPoint(lon: -73.99, lat: 40.72)],
        ])
        XCTAssertEqual(ink.lines.count, 2)
        for p in ink.lines.flatMap({ $0 }) {
            XCTAssertTrue((0...1).contains(p.x) && (0...1).contains(p.y))
        }
        // North is up: the second run's northern end is at the top.
        XCTAssertEqual(ink.lines[1][1].y, 0, accuracy: 1e-9)
        XCTAssertEqual(ink.lines[1][0].y, 1, accuracy: 1e-9)
        // 0.02 degrees of longitude at this latitude is narrower than 0.02 degrees of latitude.
        XCTAssertLessThan(ink.aspect, 1)
    }

    func testPosterTrimsTwoHundredMetresFromEachEnd() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let line = try XCTUnwrap(data.candidate(rank: 1)?.line)
        let trimmed = RunsInk.trimmed(line.points)
        let kept = Polyline(trimmed)
        XCTAssertEqual(kept.length, line.length - 400, accuracy: 2)
        XCTAssertGreaterThan(line.points[0].distance(to: trimmed[0]), 150, "the start isn't on the poster")
        // A run too short to trim isn't drawn at all.
        XCTAssertTrue(RunsInk.trimmed(line.slice(from: 0, to: 300)).isEmpty)
    }
}
