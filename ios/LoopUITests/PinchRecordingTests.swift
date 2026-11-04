import XCTest

/// A real, slow pinch out over mile 1, for screen recordings of the route at every zoom.
/// Skipped unless the runner has LOOP_RECORD=1 (pass TEST_RUNNER_LOOP_RECORD=1 to xcodebuild).
final class PinchRecordingTests: XCTestCase {
    func testSlowPinchOutOverMileOne() throws {
        guard ProcessInfo.processInfo.environment["LOOP_RECORD"] == "1" else {
            throw XCTSkip("recording only")
        }
        let app = XCUIApplication()
        app.launchArguments = ["-LoopZoomAt", "1.1", "16.8", "-LoopPinchTarget"]
        app.launch()
        XCTAssertTrue(app.buttons["Send to watch"].waitForExistence(timeout: 30))
        sleep(5)   // camera on mile 1, tiles loaded
        // Pinch closed slowly over mile 1, both fingers on the map: 1x to 0.12x, slowly.
        let target = app.otherElements["pinchTarget"]
        XCTAssertTrue(target.waitForExistence(timeout: 5))
        target.pinch(withScale: 0.12, velocity: -0.02)
        sleep(2)
    }
}
