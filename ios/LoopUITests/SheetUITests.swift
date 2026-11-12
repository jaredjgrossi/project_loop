import XCTest

/// Drives the real sheet: drag open, check the open state and the mile chip, drag closed.
final class SheetUITests: XCTestCase {
    func testDragOpenAndClosed() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-LoopSettled"]   // start on a finished route, not the launch sequence
        app.launchArguments.append("-LoopOffline")
        app.launch()

        let send = app.buttons["Share route"]
        XCTAssertTrue(send.waitForExistence(timeout: 30))
        let lights = app.descendants(matching: .any)["3.6 lights a mile, measured"]
        XCTAssertFalse(lights.exists, "collapsed sheet hides the stats")

        // Drag up from the card to the open rest (sheet top sits at 75% of the height when collapsed),
        // slowly and held, so the sheet stops at open and doesn't fling on to "How Loop read it"
        // (where the markers and chip fade out).
        app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.80))
            .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.52)),
                   withVelocity: .slow, thenHoldForDuration: 0.3)
        XCTAssertTrue(lights.waitForExistence(timeout: 3), "open sheet shows whole-route stats")
        XCTAssertTrue(app.descendants(matching: .any)["51% waterfront, measured"].exists)
        XCTAssertTrue(app.descendants(matching: .any)["Mile 1 selected"].waitForExistence(timeout: 3))

        // Mile 1 is on the East River Esplanade, where Apple has Look Around imagery.
        let chip = app.buttons["Look around at East River Esplanade · 1.0 mi"]
        XCTAssertTrue(chip.waitForExistence(timeout: 15))
        chip.tap()
        let close = app.buttons["Close street view"]
        XCTAssertTrue(close.waitForExistence(timeout: 10))
        close.tap()

        // Drag down to close: from the read rest it may take two drags (read → open → collapsed).
        // Grab the sheet by its grabber (the card's other areas include the scrubbable strip).
        let grabber = app.descendants(matching: .any)["Close route details"]
        for _ in 0..<2 where lights.exists {
            grabber.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
                .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.99)))
            sleep(1)
        }
        let gone = NSPredicate(format: "exists == false")
        expectation(for: gone, evaluatedWith: lights)
        waitForExpectations(timeout: 3)
    }
}
