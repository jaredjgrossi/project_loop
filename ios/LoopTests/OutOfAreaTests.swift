import XCTest
@testable import Loop

/// Out-of-area is a question, not an error (server decision 056): the wire shape, the copy built from the
/// server's own words, and how long the landing remembers it.
final class OutOfAreaTests: XCTestCase {
    private func event(_ json: String) -> ServerEvent { ServerEvent.decode(Data(json.utf8)) }
    private func area(_ json: String) -> OutOfArea? {
        if case let .outOfArea(a) = event(json) { return a }
        return nil
    }

    func testOutOfAreaIsItsOwnEventNotAnError() {
        XCTAssertEqual(area(#"{"event":"error","v":1,"code":"out_of_area","text":"Loop only covers New York City, and Tampa is outside it.","place":"Tampa","covers":"New York City"}"#),
                       OutOfArea(place: "Tampa", covers: "New York City"))
        // Other error codes stay errors.
        guard case let .error(code, text) = event(#"{"event":"error","v":1,"code":"engine_unavailable","text":"x"}"#) else { return XCTFail("still an error") }
        XCTAssertEqual(code, "engine_unavailable")
        XCTAssertEqual(text, "x")
    }

    func testAPlaceCanBeNullAndTheCoverageNameCanBeMissing() {
        XCTAssertEqual(area(#"{"event":"error","code":"out_of_area","text":"t","place":null,"covers":"New York City"}"#),
                       OutOfArea(place: nil, covers: "New York City"))
        XCTAssertEqual(area(#"{"event":"error","code":"out_of_area","text":"t"}"#), OutOfArea(place: nil, covers: nil))
    }

    func testTheCardNamesThePlaceAndTheCoverageFromTheServer() {
        XCTAssertEqual(OutOfArea(place: "Tampa", covers: "New York City").message,
                       "Loop doesn't know Tampa yet. It covers New York City for now.")
        XCTAssertEqual(OutOfArea(place: "Tampa", covers: "Greater Boston").message,
                       "Loop doesn't know Tampa yet. It covers Greater Boston for now.", "nothing is hardcoded")
        XCTAssertEqual(OutOfArea.buttonTitle, "Change the start")
    }

    func testNoPlaceMeansJustTheCoverage() {
        XCTAssertEqual(OutOfArea(place: nil, covers: "New York City").message, "Loop covers New York City for now.")
        XCTAssertEqual(OutOfArea(place: "  ", covers: "New York City").message, "Loop covers New York City for now.")
        XCTAssertEqual(OutOfArea(place: nil, covers: nil).message, "Loop only covers one area for now.")
        XCTAssertEqual(OutOfArea(place: "Tampa", covers: nil).message, "Loop doesn't know Tampa yet. It only covers one area for now.")
    }

    // MARK: every error code has its own words

    func testEveryKnownCodeHasItsOwnCopyAndNoneSaysCantReach() {
        let codes = ["engine_unavailable", "bad_final", "parse_failed", "bad_request", "expired", "route_not_found"]
        let texts = codes.map { ErrorCopy.notice(code: $0, text: "").text }
        XCTAssertEqual(Set(texts).count, codes.count, "one line each")
        for t in texts { XCTAssertFalse(t.localizedCaseInsensitiveContains("reach"), t) }
        XCTAssertTrue(ErrorCopy.notice(code: "engine_unavailable", text: "").canRetry)
        XCTAssertFalse(ErrorCopy.notice(code: "parse_failed", text: "").canRetry, "trying the same words again can't help")
        // The server's text doesn't replace our copy for a code we know.
        XCTAssertEqual(ErrorCopy.notice(code: "parse_failed", text: "server words").text, ErrorCopy.notice(code: "parse_failed", text: "").text)
    }

    func testAnUnknownCodeShowsTheServersTextAndNeverCantReach() {
        XCTAssertEqual(ErrorCopy.notice(code: "new_code", text: "Loop is resting.").text, "Loop is resting.")
        let none = ErrorCopy.notice(code: "new_code", text: " ")
        XCTAssertEqual(none.text, "Something went wrong with that request.")
        XCTAssertFalse(none.text.contains("reach"))
    }

    // MARK: the phone's own coverage check

    private let squareFile = """
    {"type":"FeatureCollection","features":[{"type":"Feature","properties":{"name":"Test Town"},
     "geometry":{"type":"MultiPolygon","coordinates":[
       [[[0,0],[10,0],[10,10],[0,10],[0,0]],[[4,4],[6,4],[6,6],[4,6],[4,4]]],
       [[[20,0],[30,0],[30,10],[20,10],[20,0]]]]}}]}
    """

    func testPointInsideAnOutlineWithAHoleAndASecondIsland() throws {
        let c = try XCTUnwrap(Coverage.decode(Data(squareFile.utf8)))
        XCTAssertEqual(c.name, "Test Town")
        XCTAssertTrue(c.contains(GeoPoint(lon: 2, lat: 2)))
        XCTAssertFalse(c.contains(GeoPoint(lon: 5, lat: 5)), "inside the hole")
        XCTAssertTrue(c.contains(GeoPoint(lon: 25, lat: 5)), "the second polygon")
        XCTAssertFalse(c.contains(GeoPoint(lon: 15, lat: 5)), "between them")
        XCTAssertFalse(c.contains(GeoPoint(lon: -3, lat: 5)))
        XCTAssertFalse(c.contains(GeoPoint(lon: 5, lat: 12)))
    }

    func testAPlainPolygonAndANamelessFile() throws {
        let one = #"{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"name":"A"},"geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}]}"#
        XCTAssertTrue(try XCTUnwrap(Coverage.decode(Data(one.utf8))).contains(GeoPoint(lon: 0.5, lat: 0.5)))
        XCTAssertNil(Coverage.decode(Data(one.replacingOccurrences(of: "\"name\":\"A\"", with: "\"x\":1").utf8)), "no name, no coverage")
        XCTAssertNil(Coverage.decode(Data("nonsense".utf8)))
    }

    /// The real outline (Phase 3's coverage-nyc.geojson, simplified 0.0006 degrees, a little past the true edge).
    func testTheBundledOutlineKnowsTheFiveBoroughsAndNotTheRest() throws {
        let c = try XCTUnwrap(Coverage.loadBundled(), "coverage.geojson is in the app")
        XCTAssertEqual(c.name, "New York City")
        func at(_ lat: Double, _ lon: Double) -> Bool { c.contains(GeoPoint(lon: lon, lat: lat)) }
        XCTAssertTrue(at(40.7425, -73.9800), "Kips Bay")
        XCTAssertTrue(at(40.7829, -73.9654), "Central Park")
        XCTAssertTrue(at(40.6602, -73.9690), "Prospect Park")
        XCTAssertTrue(at(40.7676, -73.8330), "Flushing Meadows")
        XCTAssertTrue(at(40.6413, -73.7781), "JFK")
        XCTAssertTrue(at(40.5949, -73.7896), "Far Rockaway")
        XCTAssertTrue(at(40.5120, -74.2430), "Tottenville")
        XCTAssertTrue(at(40.6437, -74.0736), "St. George")
        XCTAssertTrue(at(40.6895, -74.0168), "Governors Island")
        XCTAssertTrue(at(40.7033, -74.0170), "Battery Park")
        XCTAssertFalse(at(40.7359, -74.0306), "Hoboken PATH")
        XCTAssertFalse(at(40.7032, -74.0570), "Liberty State Park")
        XCTAssertFalse(at(40.7357, -74.1724), "Newark")
        XCTAssertFalse(at(40.9312, -73.8988), "Yonkers")
        XCTAssertFalse(at(27.9506, -82.4572), "Tampa")
        XCTAssertFalse(at(48.8566, 2.3522), "Paris")
    }

    @MainActor func testTheTilesSwitchToStartsInsideCoverage() {
        let store = RunStore()
        XCTAssertEqual(store.suggestedTiles(outsideCoverage: false).map(\.request), ["3 miles from here", "3 miles by the water"])
        let inside = store.suggestedTiles(outsideCoverage: true)
        XCTAssertEqual(inside.count, 2)
        XCTAssertFalse(inside.contains { $0.request.contains("here") }, "no 'from here' when here is outside")
        XCTAssertTrue(inside.allSatisfy { $0.request.contains(" from ") }, "each names its start")
    }
}
