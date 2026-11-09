import XCTest
@testable import Loop

@MainActor
final class RunStoreTests: XCTestCase {
    private var url: URL!

    override func setUp() {
        url = FileManager.default.temporaryDirectory.appendingPathComponent("runs-\(UUID().uuidString).json")
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: url)
    }

    func testFirstLaunchSeedsUsualAndOneRecentFromTheFixture() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let store = RunStore.load(data: data, url: url)
        XCTAssertEqual(store.saved.map(\.name), ["Usual"])
        XCTAssertEqual(store.saved[0].request, data.request.text)
        XCTAssertEqual(store.saved[0].distanceMi, data.candidate(rank: 1)!.distanceMi, accuracy: 1e-9)
        XCTAssertEqual(store.recents.count, 1)
        // Suggestions fill the tiles after the runner's own runs: three tiles before Save.
        XCTAssertEqual(store.suggestedTiles.map(\.name), ["3 mi from here", "By the water"])
        XCTAssertTrue(FileManager.default.fileExists(atPath: url.path))
    }

    func testThumbnailShapeIsSmallAndKeepsTheEnds() throws {
        let line = try LoopData(file: RouteFile.loadBundled()).candidate(rank: 1)!.line
        let shape = RunStore.shape(of: line)
        XCTAssertLessThan(shape.count, line.points.count)
        XCTAssertLessThan(shape.count, 120)
        XCTAssertEqual(shape.first, [line.points[0].lon, line.points[0].lat])
        XCTAssertEqual(shape.last, [line.points.last!.lon, line.points.last!.lat])
    }

    func testSavedRunsAndRecentsSurviveARelaunch() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let first = RunStore.load(data: data, url: url)
        first.addRecent(request: "3 miles by the water at 7.", distanceMi: 3.03, line: data.candidates[0].line)
        let again = RunStore.load(data: data, url: url)
        XCTAssertEqual(again.saved.map(\.name), ["Usual"])
        XCTAssertEqual(again.recents.map(\.request), ["3 miles by the water at 7.", data.request.text])
    }

    func testTheSameRequestMovesUpAndCountsTimesRun() throws {
        let line = try LoopData(file: RouteFile.loadBundled()).candidates[0].line
        let store = RunStore()
        store.addRecent(request: "3 miles by the water", distanceMi: 3, line: line)
        store.addRecent(request: "6 miles", distanceMi: 6, line: line)
        store.addRecent(request: "3 miles by the water.", distanceMi: 3, line: line)
        XCTAssertEqual(store.recents.map(\.request), ["3 miles by the water.", "6 miles"])
        XCTAssertEqual(store.recents[0].timesRun, 2)
    }

    func testANewRunnerSeesSuggestionsOnly() {
        let store = RunStore()
        XCTAssertTrue(store.saved.isEmpty)
        XCTAssertTrue(store.recents.isEmpty)
        XCTAssertEqual(store.suggestedTiles.count, 2)
    }

    func testDayText() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "America/New_York")!
        let now = cal.date(from: DateComponents(year: 2026, month: 11, day: 9, hour: 7))!   // a Monday
        func ago(_ d: Int) -> Date { cal.date(byAdding: .day, value: -d, to: now)! }
        XCTAssertEqual(RunStore.dayText(now, now: now, calendar: cal), "Today")
        XCTAssertEqual(RunStore.dayText(ago(1), now: now, calendar: cal), "Yesterday")
        XCTAssertEqual(RunStore.dayText(ago(1).addingTimeInterval(-3600 * 20), now: now, calendar: cal), "Sat")
        XCTAssertEqual(RunStore.dayText(ago(6), now: now, calendar: cal), "Tue")
        XCTAssertEqual(RunStore.dayText(ago(7), now: now, calendar: cal), "Nov 2")
    }

    func testThumbnailFitsTheBoxKeepingAspect() {
        // A 200 m × 100 m L: fits the box's width, centred vertically, y flipped to screen.
        let pts = [CGPoint(x: 0, y: 100), CGPoint(x: 0, y: 0), CGPoint(x: 200, y: 0)]
        let box = CGRect(x: 10, y: 10, width: 40, height: 40)
        let f = RouteThumbnail.fit(pts, in: box)
        XCTAssertEqual(f[1].x, 10, accuracy: 1e-9)
        XCTAssertEqual(f[2].x, 50, accuracy: 1e-9)
        XCTAssertEqual(f[0].y, 20, accuracy: 1e-9)   // top of a 20-high shape centred in 10...50
        XCTAssertEqual(f[1].y, 40, accuracy: 1e-9)
    }
}
