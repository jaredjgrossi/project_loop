import XCTest
@testable import Loop

final class RouteHitTests: XCTestCase {
    // An L on screen: (0,0) → (100,0) → (100,100), 100 m per leg.
    let pts = [CGPoint(x: 0, y: 0), CGPoint(x: 100, y: 0), CGPoint(x: 100, y: 100)]
    let along = [0.0, 100, 200]

    func testNearestPointOnASegment() throws {
        let hit = try XCTUnwrap(RouteHit.nearest(to: CGPoint(x: 40, y: 10), projected: pts, cumulative: along))
        XCTAssertEqual(hit.alongM, 40, accuracy: 1e-9)
        XCTAssertEqual(hit.distance, 10, accuracy: 1e-9)
        let second = try XCTUnwrap(RouteHit.nearest(to: CGPoint(x: 120, y: 75), projected: pts, cumulative: along))
        XCTAssertEqual(second.alongM, 175, accuracy: 1e-9)
        XCTAssertEqual(second.distance, 20, accuracy: 1e-9)
    }

    func testToleranceIs22Points() {
        XCTAssertEqual(RouteHit.tolerance, 22)
        let far = RouteHit.nearest(to: CGPoint(x: 50, y: 30), projected: pts, cumulative: along)!
        XCTAssertGreaterThan(far.distance, RouteHit.tolerance)
    }

    func testOverlappingOutAndBackPrefersOutbound() throws {
        // Out along y=0 to x=100, back along the same line.
        let p = [CGPoint(x: 0, y: 0), CGPoint(x: 100, y: 0), CGPoint(x: 0, y: 0)]
        let hit = try XCTUnwrap(RouteHit.nearest(to: CGPoint(x: 30, y: 5), projected: p, cumulative: [0, 100, 200]))
        XCTAssertEqual(hit.alongM, 30, accuracy: 1e-9)
    }
}

final class CubicBezierTests: XCTestCase {
    func testEndsAndShape() {
        XCTAssertEqual(CubicBezier.ease(0.2, 0, 0, 1, x: 0), 0)
        XCTAssertEqual(CubicBezier.ease(0.2, 0, 0, 1, x: 1), 1)
        XCTAssertEqual(CubicBezier.ease(0, 0, 1, 1, x: 0.3), 0.3, accuracy: 1e-4, "linear control points")
        // Fast start, gentle end: well past halfway at the time midpoint.
        XCTAssertGreaterThan(CubicBezier.ease(0.2, 0, 0, 1, x: 0.5), 0.8)
    }
}

@MainActor
final class SheetStateTests: XCTestCase {
    func testDragFollowsTheFingerOneToOne() {
        let s = SheetState()
        s.beginDrag()
        s.drag(translation: -100)
        XCTAssertEqual(s.height, SheetState.collapsed + 100)
        s.drag(translation: -182)
        XCTAssertEqual(s.height, SheetState.open)
        s.drag(translation: -212)   // 30 pt past open: resists to a third
        XCTAssertEqual(s.height, SheetState.open + 10)
    }

    func testEndDragPicksStateAndSettlesInstantlyWithoutAnimation() {
        let s = SheetState()
        var opened: Bool?
        var heights: [CGFloat] = []
        s.onHeightChange = { heights.append($0) }
        s.beginDrag()
        s.drag(translation: -60)
        s.endDrag(predictedTranslation: -150, animated: false) { opened = $0 }
        XCTAssertEqual(opened, true)
        XCTAssertTrue(s.restingOpen)
        XCTAssertEqual(s.height, SheetState.open)
        XCTAssertFalse(s.isMoving)
        XCTAssertEqual(heights.last, SheetState.open, "every height change reaches the map's ornaments")
    }

    /// The landing sheet: its own rests (bar only, open, more recents), arriving open.
    func testLandingRestsCollapseToTheBarAndReachMoreRecents() {
        let s = SheetState(collapsed: 120, open: 370)
        s.readHeight = 560
        s.slide(to: 0, animated: false)
        s.settle(rest: .open, animated: false)
        XCTAssertEqual(s.height, 370)
        s.beginDrag()
        s.drag(translation: 200)
        s.endDrag(predictedTranslation: 260, animated: false) { _ in }
        XCTAssertEqual(s.rest, .collapsed)
        XCTAssertEqual(s.height, 120)
        s.beginDrag()
        s.drag(translation: -400)
        s.endDrag(predictedTranslation: -440, animated: false) { _ in }
        XCTAssertEqual(s.rest, .read)
        XCTAssertEqual(s.height, 560)
    }
}
