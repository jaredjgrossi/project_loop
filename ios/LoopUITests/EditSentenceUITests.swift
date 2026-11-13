import XCTest

/// Edit mode: for VoiceOver each understood phrase is one button, in reading order, and nothing in
/// the sentence is a link. (What a button does when VoiceOver activates it can't be driven from
/// here: a UI test taps a point, it doesn't activate an element.)
final class EditSentenceUITests: XCTestCase {
    func testPhrasesAreButtonsNotLinksOrSingleWords() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-LoopEdit", "-LoopOffline"]
        app.launch()

        let distance = app.buttons["3 miles"]
        XCTAssertTrue(distance.waitForExistence(timeout: 30), "the phrase is one button")
        let start = app.buttons["from the Kips Bay Library"], time = app.buttons["at 7 am"]
        XCTAssertTrue(start.exists, "a phrase of several words is one button, not one per word")
        XCTAssertTrue(time.exists)
        XCTAssertFalse(app.buttons["Kips"].exists)
        XCTAssertEqual(app.links.count, 0, "nothing in the sentence reads as a link")
        XCTAssertLessThan(distance.frame.minY, start.frame.minY, "in reading order")
        XCTAssertLessThan(start.frame.minY, time.frame.minY)
    }
}
