import XCTest

/// The landing sheet: tapping a saved run draws it and opens its card.
final class LandingUITests: XCTestCase {
    func testUsualTileOpensItsCard() throws {
        let app = XCUIApplication()
        app.launchArguments.append("-LoopOffline")
        app.launch()   // the launch sequence: logo, landing sheet

        let usual = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Usual, '")).firstMatch
        XCTAssertTrue(usual.waitForExistence(timeout: 40))
        XCTAssertTrue(app.buttons["By the water"].exists, "suggestions follow the runner's own runs")
        usual.tap()

        XCTAssertTrue(app.buttons["Send to watch"].waitForExistence(timeout: 20), "the route's card opens")
        XCTAssertFalse(usual.isHittable, "the landing sheet slid away")
    }

    func testLandingCollapsesToTheBarAndReopens() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-LoopNewUser"]
        app.launchArguments.append("-LoopOffline")
        app.launch()

        let water = app.buttons["By the water"]
        XCTAssertTrue(water.waitForExistence(timeout: 40), "arrives open, with the runs")
        sleep(3)   // let the example finish typing
        let handle = app.descendants(matching: .any)["Hide your runs"]
        XCTAssertTrue(handle.exists)
        handle.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.99)),
                   withVelocity: .slow, thenHoldForDuration: 0.2)
        let show = app.descendants(matching: .any)["Show your runs"]
        XCTAssertTrue(show.waitForExistence(timeout: 3), "collapsed to the bar")
        XCTAssertFalse(water.isHittable)
        XCTAssertTrue(app.descendants(matching: .any)["Describe your run"].exists, "the bar stays")

        show.tap()
        XCTAssertTrue(app.descendants(matching: .any)["Hide your runs"].waitForExistence(timeout: 3), "tapping the handle reopens it")
        XCTAssertTrue(water.isHittable)
    }

    /// The card's ×, swiping the card down past collapsed, and the wordmark all go home; the
    /// dismissed route becomes the top Recent row.
    func testCloseSwipeAndWordmarkGoHome() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-LoopNewUser"]
        app.launchArguments.append("-LoopOffline")
        app.launch()
        let field = app.descendants(matching: .any)["Describe your run"]
        let water = app.buttons["By the water"]
        XCTAssertTrue(water.waitForExistence(timeout: 40))

        // 1. Close button.
        water.tap()
        let close = app.buttons["Close route"]
        XCTAssertTrue(close.waitForHittable(timeout: 30), "the card opens")
        close.tap()
        XCTAssertTrue(water.waitForHittable(timeout: 5), "home sheet is back")
        let recent = app.buttons.matching(NSPredicate(format: "label BEGINSWITH '3 miles by the water'")).firstMatch
        XCTAssertTrue(recent.exists, "the dismissed route is the top Recent row")
        XCTAssertFalse(app.staticTexts["3 miles by the water."].exists, "the sentence cleared")

        // 2. Swipe the card down past collapsed.
        recent.tap()
        XCTAssertTrue(close.waitForHittable(timeout: 30))
        let grabber = app.descendants(matching: .any)["Open route details"]
        XCTAssertTrue(grabber.waitForExistence(timeout: 5))
        grabber.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            .press(forDuration: 0.05, thenDragTo: app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 1.0)), withVelocity: .fast, thenHoldForDuration: 0)
        XCTAssertTrue(water.waitForHittable(timeout: 5), "swiping down dismissed the card")

        // 3. Wordmark.
        recent.tap()
        XCTAssertTrue(close.waitForHittable(timeout: 30))
        app.buttons["Loop"].tap()   // a button once there is a route
        XCTAssertTrue(water.waitForHittable(timeout: 5), "the wordmark goes home")
        XCTAssertTrue(field.exists)
    }
}

extension XCUIElement {
    func waitForHittable(timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if exists && isHittable { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        return false
    }
}
