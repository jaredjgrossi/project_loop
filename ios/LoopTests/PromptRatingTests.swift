import XCTest
@testable import Loop

/// "I ran it" on the return prompt goes straight to "How was it?" without drawing the route, and a rating goes
/// on to the You sheet (decision 062).
@MainActor
final class PromptRatingTests: XCTestCase {
    private func model() throws -> (MainModel, RouteIdentity) {
        let m = MainModel(data: try LoopData(file: RouteFile.loadBundled()), runs: RunStore())
        let r = RouteIdentity(routeId: nil, archive: nil, name: "East River out-and-back", request: "3 miles",
                              distanceMi: 3.03, shape: [[-73.97, 40.74], [-73.96, 40.75]],
                              stretches: ["East River Esplanade"], startTime: "07:00")
        m.returnPrompt = ViewedRoute(route: r, at: Date())
        return (m, r)
    }

    func testIRanItRatesWhereItStands() throws {
        let (m, r) = try model()
        m.ranItFromPrompt()
        XCTAssertNil(m.returnPrompt)
        XCTAssertEqual(m.rating?.fromPrompt, true, "the home sheet holds the rating")
        XCTAssertEqual(m.rating?.route, r)
        XCTAssertNil(m.currentRoute, "the route is not opened first")
        XCTAssertEqual(m.runs.runs.count, 1, "the run is marked at once")
        XCTAssertNil(m.runs.runs.first?.rating)
        XCTAssertFalse(m.youShown)
    }

    func testGoodGoesOnToTheYouSheet() throws {
        let (m, _) = try model()
        m.ranItFromPrompt()
        m.rateGood()
        XCTAssertNil(m.rating)
        XCTAssertEqual(m.runs.runs.first?.rating?.verdict, .good)
        XCTAssertTrue(m.youShown, "the run is now on the profile")
    }

    func testNotForMeGoesOnToTheYouSheetToo() throws {
        let (m, _) = try model()
        m.ranItFromPrompt()
        m.chooseNotForMe()
        m.toggleReason("crowded")
        m.finishNotForMe()
        XCTAssertEqual(m.runs.runs.first?.rating?.verdict, .notForMe)
        XCTAssertTrue(m.youShown)
    }

    func testNotNowStaysHome() throws {
        let (m, _) = try model()
        m.ranItFromPrompt()
        m.closeRating()
        XCTAssertNil(m.rating)
        XCTAssertEqual(m.runs.runs.count, 1, "the run stays marked")
        XCTAssertFalse(m.youShown, "nothing to show yet")
    }

    func testARatingFromTheCardStillComesBackToTheCard() throws {
        let m = MainModel(data: try LoopData(file: RouteFile.loadBundled()), runs: RunStore())
        let r = RouteIdentity(routeId: nil, archive: nil, name: "Route", request: "3 miles", distanceMi: 3,
                              shape: [], stretches: [], startTime: nil)
        m.rating = MainModel.RatingState(runId: m.runs.markRun(r).id, route: r)
        m.rateGood()
        XCTAssertNil(m.rating)
        XCTAssertFalse(m.youShown, "from the card, the card comes back")
    }
}
