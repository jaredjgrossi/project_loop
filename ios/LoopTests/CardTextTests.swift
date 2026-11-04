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
        XCTAssertEqual(CardText.crowdLine(data.candidate(rank: 1)!.detail!, startTime: data.request.startHourText),
                       "Crowds at 7:00 · moderate on E 31st St · esplanade and FDR not scored · estimate")
    }

    func testRequestCard() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        XCTAssertEqual(data.request.text, "3 miles from the Kips Bay Library at 7 am.")
        XCTAssertEqual(data.request.provenance, "3 mi · 7:00 am you said · Training preset")
    }

    func testWrapAtSeparators() {
        let line = "Crowds at 7:00 · moderate on E 31st St · esplanade and FDR not scored · estimate"
        XCTAssertEqual(CardText.wrapAtSeparators(line, maxChars: 50), [
            "Crowds at 7:00 · moderate on E 31st St",
            "esplanade and FDR not scored · estimate",
        ])
        XCTAssertEqual(CardText.wrapAtSeparators("a · b", maxChars: 50), ["a · b"])
    }

    func testShortNames() {
        XCTAssertEqual(CardText.shortName("East 31st Street"), "E 31st St")
        XCTAssertEqual(CardText.shortName("FDR Drive"), "FDR Dr")
        XCTAssertEqual(CardText.shortName("East River Esplanade"), "the esplanade")
        XCTAssertEqual(CardText.shortName("Hudson River Greenway"), "the greenway")
        XCTAssertEqual(CardText.shortName("East End Avenue"), "East End Ave", "compass word kept before a name")
        XCTAssertEqual(CardText.shortName("Broadway"), "Broadway")
        XCTAssertEqual(CardText.bareName("East River Esplanade"), "esplanade")
        XCTAssertEqual(CardText.bareName("FDR Drive"), "FDR")
        XCTAssertEqual(CardText.bareName("East 31st Street"), "E 31st")
        XCTAssertEqual(CardText.bareName("Broadway"), "Broadway")
    }

    func testTrustText() {
        XCTAssertEqual(Trust("not_scored").text, "not scored")
        XCTAssertEqual(Trust("verified").text, "verified")
    }

    func testSelectionChip() {
        XCTAssertEqual(CardText.selectionChip(stretchName: "East River Esplanade", alongMi: 1.0, lookAround: true),
                       "East River Esplanade · 1.0 mi · Look around")
        XCTAssertEqual(CardText.selectionChip(stretchName: "FDR Drive", alongMi: 0.537, lookAround: false),
                       "FDR Drive · 0.5 mi")
    }
}
