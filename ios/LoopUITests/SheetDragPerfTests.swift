import XCTest

/// Measures hitches while the sheet is dragged open and closed at a finger-like speed.
/// Run on a device (iOS 26+): compare Debug and Release with -configuration.
final class SheetDragPerfTests: XCTestCase {
    func testSheetDragHitches() throws {
        guard #available(iOS 26.0, *) else { throw XCTSkip("XCTHitchMetric needs iOS 26") }
        let app = XCUIApplication()
        app.launchArguments = ["-LoopSettled"]   // start on a finished route, not the launch sequence
        app.launch()
        XCTAssertTrue(app.buttons["Send to watch"].waitForExistence(timeout: 30))
        sleep(4)   // let the map tiles and style settle first

        let low = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.84))
        let high = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.62))
        let options = XCTMeasureOptions()
        options.iterationCount = 5
        measure(metrics: [XCTHitchMetric(application: app)], options: options) {
            // Up, hold, release (settles open; the map refits after), then down the same way.
            low.press(forDuration: 0.05, thenDragTo: high, withVelocity: 300, thenHoldForDuration: 0.1)
            Thread.sleep(forTimeInterval: 1.0)
            high.press(forDuration: 0.05, thenDragTo: low, withVelocity: 300, thenHoldForDuration: 0.1)
            Thread.sleep(forTimeInterval: 1.0)
        }
    }
}
