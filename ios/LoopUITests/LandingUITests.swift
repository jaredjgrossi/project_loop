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
}
