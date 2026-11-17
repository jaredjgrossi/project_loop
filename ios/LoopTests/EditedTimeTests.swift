import XCTest
@testable import Loop

/// The time editor writes the new time the way the runner typed it (found in the demo cut: "at 7am" became "at 8 am").
final class EditedTimeTests: XCTestCase {
    func testKeepsTheTypedForm() {
        XCTAssertEqual(EditedTime.phrase(typed: "at 7am", minutes: 8 * 60), "at 8am")
        XCTAssertEqual(EditedTime.phrase(typed: "at 7 am", minutes: 8 * 60), "at 8 am")
        XCTAssertEqual(EditedTime.phrase(typed: "at 7", minutes: 8 * 60), "at 8")
        XCTAssertEqual(EditedTime.phrase(typed: "7am", minutes: 8 * 60), "8am", "a span without the preposition")
        XCTAssertEqual(EditedTime.phrase(typed: "at 7AM", minutes: 8 * 60), "at 8AM")
        XCTAssertEqual(EditedTime.phrase(typed: "at 7 a.m.", minutes: 8 * 60), "at 8 a.m.")
        XCTAssertEqual(EditedTime.phrase(typed: "at 6pm", minutes: 19 * 60), "at 7pm")
    }

    func testMinutes() {
        XCTAssertEqual(EditedTime.phrase(typed: "at 7am", minutes: 8 * 60 + 15), "at 8:15am", "minutes appear when the new time has some")
        XCTAssertEqual(EditedTime.phrase(typed: "at 7:30am", minutes: 7 * 60 + 45), "at 7:45am")
        XCTAssertEqual(EditedTime.phrase(typed: "at 7:30 am", minutes: 8 * 60), "at 8:00 am", "and stay when they were typed")
        XCTAssertEqual(EditedTime.phrase(typed: "at 18:00", minutes: 19 * 60 + 15), "at 19:15", "a 24-hour clock stays one")
    }

    func testCrossingNoon() {
        XCTAssertEqual(EditedTime.phrase(typed: "at 7 am", minutes: 13 * 60), "at 1 pm")
        XCTAssertEqual(EditedTime.phrase(typed: "at 7a.m.", minutes: 13 * 60), "at 1p.m.")
        XCTAssertEqual(EditedTime.phrase(typed: "at 7", minutes: 12 * 60 + 15), "at 12:15 pm", "am/pm is added only when a bare hour would mislead")
        XCTAssertEqual(EditedTime.phrase(typed: "at 7", minutes: 19 * 60), "at 7 pm")
    }

    func testNoDigitsFallsBack() {
        XCTAssertNil(EditedTime.phrase(typed: "in the morning", minutes: 8 * 60))
        XCTAssertNil(EditedTime.phrase(typed: "before work", minutes: 8 * 60))
    }
}
