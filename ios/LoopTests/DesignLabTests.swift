import XCTest
@testable import Loop

/// The pure parts of the design-lab explorations (design-review-v1): route names, the way list,
/// opening another route, the park-aware reason and feet.
final class DesignLabTests: XCTestCase {

    // MARK: C. Route names

    func testTitleTakesThePlaceFromTheEnginesName() {
        XCTAssertEqual(RouteTitle.fromLabel("Out-and-back on East River Esplanade"), "East River Esplanade")
        XCTAssertEqual(RouteTitle.fromLabel("Out-and-back on the waterfront"), "The waterfront")
        XCTAssertEqual(RouteTitle.fromLabel("Loop on the street grid"), "The street grid")
        XCTAssertEqual(RouteTitle.fromLabel("Out-and-back through Central Park"), "Central Park")
        XCTAssertEqual(RouteTitle.fromLabel("Out-and-back with a loop with a lap of the Reservoir running track"),
                       "A lap of the Reservoir running track")
        XCTAssertNil(RouteTitle.fromLabel("Loop"), "a name with no place gives no title")
    }

    func testTitleDropsTheGeneratorsHeading() {
        XCTAssertEqual(RouteTitle.fromLabel("out-and-back on the waterfront, heading 148 degrees"), "The waterfront")
    }

    // MARK: C. Opening another of the three

    func testShowingAnotherRouteMorphsToItAndStopsSwaps() {
        var s = BuildState()
        s.apply(.top3([1, 2, 3]), at: 0)
        s.apply(.provisional, at: 3)
        s.show(2, at: 4)
        XCTAssertEqual(s.shownRank, 2)
        XCTAssertEqual(s.otherRanks, [1, 3])
        XCTAssertEqual(s.morph, .init(from: 1, to: 2, start: 4))
        XCTAssertNil(s.betterRank)
        // The final arrives with the same leader: the runner's choice stays on screen.
        s.apply(.final([1, 2, 3]), at: 6)
        XCTAssertEqual(s.shownRank, 2)
    }

    func testShowingARouteOutsideTheThreeDoesNothing() {
        var s = BuildState()
        s.apply(.top3([1, 2]), at: 0)
        s.show(7, at: 1)
        XCTAssertEqual(s.shownRank, 1)
        XCTAssertNil(s.morph)
    }

    // MARK: C. The way

    func testTheWayListsTheFixtureOutToTheTurn() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let detail = try XCTUnwrap(data.candidate(rank: 1)?.detail)
        let rows = WaySection.rows(detail)
        // An out-and-back: the way out, the turn, then "Back the same way".
        XCTAssertEqual(rows.last?.name, "Back the same way")
        XCTAssertEqual(rows.dropLast().last?.name, "Turn at 1.5 mi")
        let out = rows.dropLast(2)
        XCTAssertFalse(out.isEmpty)
        XCTAssertLessThanOrEqual(out.count, WaySection.maxRows)
        XCTAssertTrue(out.contains { $0.name == "East River Esplanade" && $0.kind == .waterfront })
        // No name twice in a row, and the way out adds up to about half the route.
        for (a, b) in zip(out, out.dropFirst()) { XCTAssertNotEqual(a.name, b.name) }
        let miles = out.compactMap(\.miles).reduce(0, +)
        XCTAssertEqual(miles, detail.distanceMi / 2, accuracy: 0.1)
    }

    // MARK: C. Numbers a runner reads

    func testFeetRoundToTheNearestFive() {
        XCTAssertEqual(CardText.feet(fromMetres: 8), "25 ft")
        XCTAssertEqual(CardText.feet(fromMetres: 20), "65 ft")
        XCTAssertEqual(CardText.feet(fromMetres: 0), "0 ft")
    }

    func testFixtureReasonIsUnchangedByTheParkAwareSentence() throws {
        let s = try XCTUnwrap(RouteFile.loadBundled().route.features[0].properties.summary)
        XCTAssertEqual(CardText.reasonWithParks(s), CardText.reason(s))
    }

    // MARK: A. Examples

    func testEveryExampleFitsTheFieldOnOneLine() {
        XCTAssertGreaterThanOrEqual(TryExample.all.count, 4)
        for e in TryExample.all { XCTAssertLessThanOrEqual(e.count, 30, e) }
    }
}
