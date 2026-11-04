import XCTest

/// Drives the real sheet: drag open, check the open state and the mile chip, drag closed.
final class SheetUITests: XCTestCase {
    func testDragOpenAndClosed() throws {
        let app = XCUIApplication()
        app.launch()

        let send = app.buttons["Send to watch"]
        XCTAssertTrue(send.waitForExistence(timeout: 30))
        let lights = app.descendants(matching: .any)["3.6 lights a mile, measured"]
        XCTAssertFalse(lights.exists, "collapsed sheet hides the stats")

        // Drag up from the card to open (sheet top sits at 75% of the height when collapsed).
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.80))
            .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.40)))
        XCTAssertTrue(lights.waitForExistence(timeout: 3), "open sheet shows whole-route stats")
        XCTAssertTrue(app.descendants(matching: .any)["51% waterfront, measured"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["Mile 1 selected"].waitForExistence(timeout: 3))

        // Mile 1 is on the East River Esplanade, where Apple has Look Around imagery.
        let chip = app.buttons["Look at the street at mile 1, East River Esplanade"]
        XCTAssertTrue(chip.waitForExistence(timeout: 15))
        chip.tap()
        let close = app.buttons["Close street view"]
        XCTAssertTrue(close.waitForExistence(timeout: 10))
        close.tap()

        // Drag down from the grabber area to close.
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.58))
            .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.97)))
        let gone = NSPredicate(format: "exists == false")
        expectation(for: gone, evaluatedWith: lights)
        waitForExpectations(timeout: 3)
    }
}
