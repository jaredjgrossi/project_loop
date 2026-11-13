import XCTest

/// Trust words are hidden by default; tapping a number shows its trust word and source.
final class TrustPopoverUITests: XCTestCase {
    func testTappingTheClimbShowsEstimateAndSource() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-LoopMile", "1"]   // the open sheet
        app.launchArguments.append("-LoopOffline")
        app.launch()

        let climb = app.buttons["26 ft climb, estimate"]
        XCTAssertTrue(climb.waitForExistence(timeout: 30))
        XCTAssertTrue(app.staticTexts["≈ 26 ft"].exists, "an estimate carries ≈")
        XCTAssertFalse(app.staticTexts["measured"].exists, "no trust words by default")
        climb.tap()
        XCTAssertTrue(app.staticTexts["Estimate"].waitForExistence(timeout: 3), "the popover names the trust word")
        XCTAssertTrue(app.staticTexts.containing(NSPredicate(format: "label CONTAINS 'elevation'")).firstMatch.exists,
                      "and the file's source")
    }
}
