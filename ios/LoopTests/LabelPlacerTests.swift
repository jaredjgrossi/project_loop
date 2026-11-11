import XCTest
@testable import Loop

/// START, TURN and mile marks sit beside their markers, never on the route line.
final class LabelPlacerTests: XCTestCase {
    func testStaysOffAVerticalLineAndFlipsWhenTheFirstSideIsTaken() {
        // A line straight up through the anchor: "above" would sit on it, so the label goes beside it.
        let line = [CGPoint(x: 100, y: 0), CGPoint(x: 100, y: 300)]
        let size = LabelPlacer.labelSize("Start")
        let c = LabelPlacer.place(size: size, anchor: CGPoint(x: 100, y: 150), gap: 11,
                                  directions: LabelPlacer.aboveFirst, line: line, obstacles: [])
        let r = CGRect(x: c.x - size.width / 2, y: c.y - size.height / 2, width: size.width, height: size.height)
        XCTAssertGreaterThanOrEqual(LabelPlacer.distance(from: r, to: line), 4)

        // An out-and-back: the return leg 20 pt to the left takes that side, so it flips right.
        let back = [CGPoint(x: 80, y: 0), CGPoint(x: 80, y: 300)]
        let mark = LabelPlacer.place(size: CGSize(width: 20, height: 20), anchor: CGPoint(x: 100, y: 150), gap: 8,
                                     directions: [CGVector(dx: -1, dy: 0), CGVector(dx: 1, dy: 0)],
                                     line: line + back.reversed(), obstacles: [])
        XCTAssertGreaterThan(mark.x, 100, "flips to the side with room")
    }

    func testKeepsThePreferredSideWhenItIsClear() {
        // A horizontal line: above is clear, so START stays above.
        let line = [CGPoint(x: 0, y: 200), CGPoint(x: 300, y: 200)]
        let c = LabelPlacer.place(size: LabelPlacer.labelSize("Start"), anchor: CGPoint(x: 150, y: 200), gap: 11,
                                  directions: LabelPlacer.aboveFirst, line: line, obstacles: [])
        XCTAssertLessThan(c.y, 200)
        XCTAssertEqual(c.x, 150, accuracy: 0.001)
    }

    func testRectSegmentDistance() {
        let r = CGRect(x: 0, y: 0, width: 10, height: 10)
        XCTAssertEqual(LabelPlacer.distance(from: r, a: CGPoint(x: 20, y: -5), b: CGPoint(x: 20, y: 15)), 10, accuracy: 0.001)
        XCTAssertEqual(LabelPlacer.distance(from: r, a: CGPoint(x: -5, y: 5), b: CGPoint(x: 15, y: 5)), 0, "crossing")
    }
}
