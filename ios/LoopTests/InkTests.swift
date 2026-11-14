import XCTest
@testable import Loop

/// The pure parts of "pencil, then ink": the ink's timing and when it starts.
@MainActor
final class InkTests: XCTestCase {
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
        var frame = model.frame(now: 101, reduceMotion: false)
        XCTAssertTrue(frame.casing.isEmpty, "before the flag the route is pencil only")
        XCTAssertGreaterThanOrEqual(frame.pencil.count, 2)
        // Long after the pencil line has finished drawing, there are still no direction chevrons.
        frame = model.frame(now: 101.9, reduceMotion: false)
        XCTAssertTrue(frame.arrows.isEmpty, "no direction chevrons on a sketch")
        XCTAssertEqual(frame.arrowsOpacity, 0)
        model.build.apply(.provisional, at: 102)
        XCTAssertEqual(model.inkProgress(now: 102, reduceMotion: false), 0)
        XCTAssertEqual(model.inkProgress(now: 110, reduceMotion: false), 1)
        XCTAssertEqual(model.inkProgress(now: 102, reduceMotion: true), 1, "Reduce Motion: inked at once")
        // Early in the sweep the chevrons are still held back; they come in with the last of the ink.
        frame = model.frame(now: 102.3, reduceMotion: false)
        XCTAssertTrue(frame.arrows.isEmpty, "chevrons wait for the ink")
        frame = model.frame(now: 110, reduceMotion: false)
        XCTAssertTrue(frame.pencil.isEmpty, "once the ink is dry the pencil is gone")
        XCTAssertGreaterThanOrEqual(frame.casing.count, 2)
        XCTAssertFalse(frame.arrows.isEmpty, "the inked route shows its direction")
        XCTAssertEqual(frame.arrowsOpacity, Motion.arrowOpacity, accuracy: 1e-9)
    }

    func testASettledRouteIsInkWithNoSweep() throws {
        let model = MainModel(data: try LoopData(file: RouteFile.loadBundled()), runs: RunStore())
        XCTAssertFalse(model.inkIsMoving(now: 5))
        XCTAssertTrue(model.frame(now: 5, reduceMotion: false).pencil.isEmpty)
    }
}
