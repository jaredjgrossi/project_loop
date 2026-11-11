import XCTest
@testable import Loop

/// The profile strip's axis labels: "turn" never draws over a mile number (phone, 2026-11-11: "turn1").
final class StripLabelsTests: XCTestCase {
    private func mile(_ text: String, _ x: CGFloat, _ w: CGFloat = 8) -> StripLabels.Label {
        .init(text: text, x: x, width: w, isTurn: false)
    }
    private func turn(_ x: CGFloat) -> StripLabels.Label { .init(text: "turn", x: x, width: 26, isTurn: true) }

    private func placed(_ out: [StripLabels.Placed], _ text: String) -> StripLabels.Placed? {
        out.first { $0.text == text }
    }

    private func overlaps(_ out: [StripLabels.Placed], gap: CGFloat) -> Bool {
        let shown = out.filter { !$0.hidden }.sorted { $0.x < $1.x }
        return zip(shown, shown.dropFirst()).contains { a, b in a.x + a.width / 2 + gap > b.x - b.width / 2 }
    }

    func testApartLabelsStayPut() {
        let out = StripLabels.layout([mile("0", 0), mile("1", 110), mile("2", 220), turn(165)], width: 342)
        XCTAssertEqual(placed(out, "turn")?.x, 165)
        XCTAssertEqual(placed(out, "1")?.x, 110)
        XCTAssertFalse(out.contains { $0.hidden })
    }

    func testTurnJustBeforeAMileSlidesLeftOfIt() {
        // Turnaround 6 pt before mile 1: "turn" would cover the "1".
        let out = StripLabels.layout([mile("0", 0), mile("1", 114), mile("2", 228), turn(108)], width: 342)
        let t = try! XCTUnwrap(placed(out, "turn"))
        XCTAssertLessThan(t.x, 108, "it moves away from the mile label, toward its own side")
        XCTAssertLessThanOrEqual(108 - t.x, StripLabels.maxShift)
        XCTAssertEqual(placed(out, "1")?.x, 114, "the mile number stays on its mark")
        XCTAssertFalse(out.contains { $0.hidden })
        XCTAssertFalse(overlaps(out, gap: StripLabels.gap))
    }

    func testTurnJustAfterAMileSlidesRight() {
        let out = StripLabels.layout([mile("0", 0), mile("1", 114), mile("2", 228), turn(118)], width: 342)
        XCTAssertGreaterThan(placed(out, "turn")!.x, 118)
        XCTAssertFalse(overlaps(out, gap: StripLabels.gap))
    }

    func testNoRoomToSlideHidesTheMileNumber() {
        // Miles 30 pt apart: "turn" can't fit between them without covering one, so it takes the
        // spot and the mile number under it hides (the tick still marks the turnaround).
        let out = StripLabels.layout([mile("0", 0), mile("1", 30), mile("2", 60), mile("3", 90), turn(60)], width: 120)
        XCTAssertEqual(placed(out, "turn")?.hidden, false)
        XCTAssertEqual(placed(out, "2")?.hidden, true)
        XCTAssertFalse(overlaps(out, gap: StripLabels.gap))
    }

    func testLabelsStayInsideTheStrip() {
        let out = StripLabels.layout([mile("0", 0), mile("3", 342), turn(340)], width: 342)
        for p in out where !p.hidden {
            XCTAssertGreaterThanOrEqual(p.x - p.width / 2, 0)
            XCTAssertLessThanOrEqual(p.x + p.width / 2, 342)
        }
        XCTAssertFalse(overlaps(out, gap: StripLabels.gap))
    }
}
