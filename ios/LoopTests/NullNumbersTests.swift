import XCTest
@testable import Loop

/// The server sends `value: null` with status "not_scored" whenever it can't score something: crowds
/// before 7 am, after 8 pm and on Sundays, climb without elevation, shares without stretches.
/// None of that may fail a `final` (the runner saw "Can't reach Loop" over a finished route,
/// full review 2026-11-12, 3.1).
final class NullNumbersTests: XCTestCase {

    private func fixture() throws -> [String: Any] {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "kips3-ui", withExtension: "json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    }

    private func notScored(_ reason: String) -> [String: Any] {
        ["value": NSNull(), "status": "not_scored", "reason": reason]
    }

    /// The fixture with the route's summary and every stretch's crowd as the server sends them off-hours.
    private func unscored(_ file: [String: Any], summaryKeys: [String]) throws -> [String: Any] {
        var file = file
        var route = try XCTUnwrap(file["route"] as? [String: Any])
        var features = try XCTUnwrap(route["features"] as? [[String: Any]])
        for i in features.indices {
            var props = try XCTUnwrap(features[i]["properties"] as? [String: Any])
            if var summary = props["summary"] as? [String: Any] {
                for k in summaryKeys { summary[k] = notScored("test") }
                props["summary"] = summary
            }
            if props["crowd"] != nil { props["crowd"] = notScored("no count data after 8pm") }
            features[i]["properties"] = props
        }
        route["features"] = features
        file["route"] = route
        return file
    }

    func testNullCrowdsDecodeAndShowNoCrowdLine() throws {
        let json = try unscored(fixture(), summaryKeys: ["crowds"])
        let file = try RouteFile.decode(JSONSerialization.data(withJSONObject: json))
        let data = try LoopData(file: file)
        let detail = try XCTUnwrap(data.candidate(rank: 1)?.detail)

        XCTAssertNil(detail.summary.crowds.value)
        XCTAssertEqual(detail.summary.crowds.status, "not_scored")
        XCTAssertNil(detail.summary.crowds.source)
        XCTAssertNil(detail.summary.crowds.notScoredPct)
        XCTAssertTrue(detail.stretches.allSatisfy { $0.crowd == nil })
        XCTAssertNil(CardText.crowdSentence(detail, startTime: "05:30"), "no crowd line when nothing is scored")
        // The rest of the card is untouched.
        XCTAssertFalse(CardText.stats(detail.summary).contains { $0.value == "–" })
        XCTAssertNotNil(CardText.reason(detail.summary))
    }

    func testEveryNumberNullStillDecodes() throws {
        let keys = ["crowds", "climb", "waterfront_pct", "park_pct", "path_pct", "street_pct",
                    "signalized_crossings", "lights_per_mile", "rank"]
        let json = try unscored(fixture(), summaryKeys: keys)
        let file = try RouteFile.decode(JSONSerialization.data(withJSONObject: json))
        let data = try LoopData(file: file)
        let detail = try XCTUnwrap(data.candidate(rank: 1)?.detail)

        XCTAssertEqual(CardText.stats(detail.summary).map(\.value), ["–", "–", "–"], "a dash, never a zero")
        XCTAssertEqual(CardText.stats(detail.summary).map(\.trust), Array(repeating: Trust("not_scored"), count: 3))
        XCTAssertNil(CardText.reason(detail.summary), "no sentence when nothing is scored")
        XCTAssertGreaterThan(data.candidate(rank: 1)?.distanceMi ?? 0, 3, "the distance is the route's own")
    }

    func testReasonSaysOnlyWhatItKnows() {
        XCTAssertEqual(CardText.reason(waterfrontPct: 72, lightsPerMile: nil), "Mostly by the water.")
        XCTAssertEqual(CardText.reason(waterfrontPct: nil, lightsPerMile: 2.0), "2.0 lights a mile.")
        XCTAssertNil(CardText.reason(waterfrontPct: nil, lightsPerMile: nil))
    }

    /// A whole `final` event off-hours decodes to a final, not to "bad_final".
    func testFinalEventWithNullCrowdsIsAFinal() throws {
        let f = try unscored(fixture(), summaryKeys: ["crowds"])
        let event: [String: Any] = ["event": "final", "route_id": "r_1", "routes": f["top3"] as Any,
                                    "route": f["route"] as Any, "pool": f["pool"] as Any, "pool_size": 31]
        let e = ServerEvent.decode(try JSONSerialization.data(withJSONObject: event))
        guard case let .final(final, _) = e else { return XCTFail("not a final: \(e)") }
        XCTAssertEqual(final.routes.count, 3)
        let summary = try XCTUnwrap(final.route?.features.first?.properties.summary)
        XCTAssertNil(summary.crowds.value)
    }
}
