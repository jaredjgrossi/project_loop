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
        XCTAssertEqual(CardText.eyebrow(kind: "TRAINING", bestOf: nil), "TRAINING")
        XCTAssertEqual(CardText.eyebrow(kind: "TRAINING", bestOf: 31), "TRAINING · BEST OF 31")
        XCTAssertEqual(CardText.kindText("out_and_back"), "OUT AND BACK")
        XCTAssertEqual(CardText.kindText("loop"), "LOOP")
    }

    func testWholeRouteLinesFromFixture() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let s = data.candidate(rank: 1)!.detail!.summary
        let stats = CardText.stats(s)
        XCTAssertEqual(stats.map(\.value), ["3.6", "51%", "8 m"])
        XCTAssertEqual(stats.map(\.label), ["lights a mile", "waterfront", "climb"])
        XCTAssertEqual(stats.map(\.trust.raw), ["measured", "measured", "estimate"])
        // Trust words hidden: measured values bare, estimates with "≈".
        XCTAssertEqual(stats.map(\.shown), ["3.6", "51%", "≈ 8 m"])
        XCTAssertTrue(stats.allSatisfy { $0.source?.isEmpty == false }, "every number keeps its source for the popover")
        // One sentence, only for moderate or busy stretches.
        XCTAssertEqual(CardText.crowdSentence(data.candidate(rank: 1)!.detail!, startTime: data.request.startHourText),
                       "Busier on E 31st St around 7.")
    }

    func testApproxAndHour() {
        XCTAssertEqual(CardText.approx("3.03", Trust("measured")), "3.03")
        XCTAssertEqual(CardText.approx("8 m", Trust("estimate")), "≈ 8 m")
        XCTAssertEqual(CardText.approx("3.03", nil), "3.03")
        XCTAssertEqual(CardText.hourText("7:00"), "7")
        XCTAssertEqual(CardText.hourText("7:30"), "7:30")
    }

    func testRequestCard() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        XCTAssertEqual(data.request.text, "3 miles from the Kips Bay Library at 7 am.")
        XCTAssertEqual(data.request.provenance, "3 mi · 7:00 am you said · Training preset")
        XCTAssertEqual(data.request.mode, "Training")
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

final class ReadOutTests: XCTestCase {
    func testCardLineNamesJoinsOrCounts() {
        XCTAssertNil(CardText.cantCardLine([]))
        XCTAssertEqual(CardText.cantCardLine(["G9"]), "Street lighting isn't planned yet")
        XCTAssertEqual(CardText.cantCardLine(["G9", "G8"]), "Lighting and repeats aren't planned yet")
        XCTAssertEqual(CardText.cantCardLine(["G9", "G8", "G3"]), "3 things aren't planned yet")
    }

    func testSimulatedParseFindsWordsAndFillsTheRest() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let r = ReadOut.simulated("3 miles by the water at 7, well lit.", data: data, file: nil)
        XCTAssertEqual(r.understood.map(\.field), ["distance", "scenery", "time"])
        let s = "3 miles by the water at 7, well lit." as NSString
        XCTAssertEqual(s.substring(with: NSRange(location: r.understood[0].start, length: r.understood[0].length)), "3 miles")
        XCTAssertEqual(r.understood[0].value, "3 mi")
        XCTAssertEqual(r.cant.map(\.gap), ["G9"])
        XCTAssertEqual(r.filled.first?.main, "Starting where you are")
        XCTAssertEqual(r.filled.map(\.main), ["Starting where you are", "Training: fewer lights, crowds and turns",
                                               "Any shape, a loop or out and back"])
        XCTAssertFalse(r.filled.contains { $0.field == "tolerance" }, "no distance-tolerance row")
    }

    func testStartPlaceStopsAtTheName() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let text = "3 miles from the Kips Bay Library at 7 am."
        let r = ReadOut.simulated(text, data: data, file: nil)
        let start = try XCTUnwrap(r.understood.first { $0.field == "start" })
        XCTAssertEqual((text as NSString).substring(with: NSRange(location: start.start, length: start.length)), "from the Kips Bay Library")
        XCTAssertFalse(r.filled.contains { $0.field == "start" }, "a start the runner said isn't listed as filled in")
    }
}
