import XCTest

/// The landing field while typing: Cancel, matches, tapping away, and dragging the keyboard away.
final class LandingKeyboardUITests: XCTestCase {
    func testCancelMatchesTapAwayAndDrag() throws {
        let app = XCUIApplication()
        app.launch()   // seeded store: "Usual" and one recent
        let field = app.textFields["Describe your run"]
        XCTAssertTrue(field.waitForExistence(timeout: 40))
        sleep(3)   // let the launch example start typing

        // Focus: the example stops, Cancel appears, recent and saved runs show (newest first).
        field.tap()
        let cancel = app.buttons["Cancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 3))
        XCTAssertEqual(field.value as? String ?? "", "", "the field is empty until the runner types")
        let usual = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Usual'")).firstMatch
        XCTAssertTrue(usual.waitForExistence(timeout: 3), "saved runs show under the field")
        XCTAssertFalse(app.buttons["By the water"].isHittable, "the tiles give way to the matches")

        // Typing filters by title.
        field.typeText("kips")
        let kips = app.buttons.matching(NSPredicate(format: "label BEGINSWITH '3 miles from the Kips Bay'")).firstMatch
        XCTAssertTrue(kips.waitForExistence(timeout: 3))
        XCTAssertFalse(usual.exists, "\"Usual\" doesn't match \"kips\"")

        // Cancel clears and ends editing.
        cancel.tap()
        XCTAssertFalse(cancel.waitForExistence(timeout: 1))
        XCTAssertEqual(field.value as? String ?? "", "")
        XCTAssertTrue(app.buttons["By the water"].waitForHittable(timeout: 3), "the runs come back")

        // Tapping the map ends editing and keeps the text.
        field.tap()
        field.typeText("water")
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.3)).tap()
        XCTAssertFalse(cancel.waitForExistence(timeout: 2), "tapping the map ends editing")
        XCTAssertEqual(field.value as? String, "water", "the text stays")

        // While typing, a drag down only ends editing; the next one collapses the sheet.
        field.tap()
        XCTAssertTrue(cancel.waitForExistence(timeout: 3))
        let handle = app.descendants(matching: .any)["Hide your runs"]
        handle.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.95)),
                   withVelocity: .slow, thenHoldForDuration: 0.1)
        XCTAssertFalse(cancel.waitForExistence(timeout: 2), "the first drag only ends editing")
        XCTAssertTrue(app.descendants(matching: .any)["Hide your runs"].waitForExistence(timeout: 3), "the sheet stays open")
        app.descendants(matching: .any)["Hide your runs"].coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.99)),
                   withVelocity: .slow, thenHoldForDuration: 0.1)
        XCTAssertTrue(app.descendants(matching: .any)["Show your runs"].waitForExistence(timeout: 3), "the second drag collapses it")
    }
}
