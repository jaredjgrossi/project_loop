import XCTest
@testable import Loop

final class CardTextTests: XCTestCase {

    func testReasonBands() {
        XCTAssertEqual(CardText.reason(waterfrontPct: 72, lightsPerMile: 2.0), "Mostly by the water: 2.0 lights a mile.")
        XCTAssertEqual(CardText.reason(waterfrontPct: 60, lightsPerMile: 5.9), "Mostly by the water: 5.9 lights a mile.")
        XCTAssertEqual(CardText.reason(waterfrontPct: 59.6, lightsPerMile: 1), "Mostly by the water: 1.0 lights a mile.",
                       "shows as 60%, so it reads as 60%")
        XCTAssertEqual(CardText.reason(waterfrontPct: 51.2, lightsPerMile: 3.6), "About half by the water: 3.6 lights a mile.")
        XCTAssertEqual(CardText.reason(waterfrontPct: 40, lightsPerMile: 3.6), "About half by the water: 3.6 lights a mile.")
        XCTAssertEqual(CardText.reason(waterfrontPct: 39.4, lightsPerMile: 3.6), "Mostly on streets: 3.6 lights a mile.")
    }

    func testFixtureCardUsesEveryCrossingLights() throws {
        let file = try RouteFile.loadBundled()
        let s = file.route.features[0].properties.summary!
        // lights_per_mile 3.6 counts every crossing; the ranking's 2.0 is not decoded at all.
        XCTAssertEqual(s.lightsPerMile.value, 3.6)
        XCTAssertEqual(CardText.reason(s), "About half by the water: 3.6 lights a mile.")
    }

    func testEyebrow() {
        XCTAssertEqual(CardText.eyebrow(kind: "OUT AND BACK", bestOf: nil), "OUT AND BACK")
        XCTAssertEqual(CardText.eyebrow(kind: "OUT AND BACK", bestOf: 31), "BEST OF 31 · OUT AND BACK")
        XCTAssertEqual(CardText.kindText("out_and_back"), "OUT AND BACK")
        XCTAssertEqual(CardText.kindText("loop"), "LOOP")
    }

    func testWholeRouteLinesFromFixture() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let s = data.candidate(rank: 1)!.detail!.summary
        XCTAssertEqual(CardText.stats(s), [
            .init(value: "3.6", label: "lights a mile", trust: Trust("measured")),
            .init(value: "51%", label: "waterfront", trust: Trust("measured")),
            .init(value: "8 m", label: "climb", trust: Trust("estimate")),
        ])
        XCTAssertEqual(CardText.signalsLine(s), "11 signal crossings · measured")
        XCTAssertEqual(CardText.crowdLine(s, startTime: data.request.startHourText),
                       "Crowds 7:00 · 5% busy · 58% not scored · estimate")
    }

    func testRequestCard() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        XCTAssertEqual(data.request.text, "3 miles from the Kips Bay Library at 7 am.")
        XCTAssertEqual(data.request.provenance, "3 mi · 7:00 am you said · Training preset")
    }

    func testTrustText() {
        XCTAssertEqual(Trust("not_scored").text, "not scored")
        XCTAssertEqual(Trust("verified").text, "verified")
    }

    func testMileChip() {
        XCTAssertEqual(CardText.mileChip(mile: 1, stretchName: "East River Esplanade"), "Mile 1 · East River Esplanade")
    }
}
