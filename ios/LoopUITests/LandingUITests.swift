import XCTest

/// The landing sheet: tapping a saved run draws it and opens its card.
final class LandingUITests: XCTestCase {
    func testUsualTileOpensItsCard() throws {
        let app = XCUIApplication()
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
}
