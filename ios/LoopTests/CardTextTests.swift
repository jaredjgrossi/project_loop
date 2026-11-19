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
        XCTAssertEqual(CardText.eyebrow(kind: "OUT AND BACK", position: nil, of: nil), "OUT AND BACK")
        XCTAssertEqual(CardText.eyebrow(kind: "OUT AND BACK", position: 1, of: 1), "OUT AND BACK", "one route has no position")
        XCTAssertEqual(CardText.eyebrow(kind: "OUT AND BACK", position: 1, of: 3), "1 OF 3 · OUT AND BACK")
        XCTAssertEqual(CardText.eyebrow(kind: "OUT AND BACK", position: 1, of: 3, bestOf: 31), "1 OF 3 · BEST OF 31", "all three would truncate")
        XCTAssertEqual(CardText.eyebrow(kind: "LOLLIPOP", position: 1, of: 1, bestOf: 7), "LOLLIPOP · BEST OF 7", "one route keeps its type")
        XCTAssertEqual(CardText.eyebrow(kind: "LOLLIPOP", position: 1, of: 1, bestOf: 1), "LOLLIPOP", "a pool of one is no pool")
        XCTAssertEqual(CardText.eyebrow(kind: "", position: 2, of: 3, bestOf: 12), "2 OF 3 · BEST OF 12")
        XCTAssertEqual(CardText.kindText("a_to_b"), "ONE WAY")
        XCTAssertEqual(CardText.kindText("out_and_back"), "OUT AND BACK")
        XCTAssertEqual(CardText.kindText("loop"), "LOOP")
    }

    func testWholeRouteLinesFromFixture() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let s = data.candidate(rank: 1)!.detail!.summary
        let stats = CardText.stats(s)
        XCTAssertEqual(stats.map(\.value), ["3.6", "51%", "26 ft"])
        XCTAssertEqual(stats.map(\.label), ["lights a mile", "waterfront", "climb"])
        XCTAssertEqual(stats.map(\.trust.raw), ["measured", "measured", "estimate"])
        // Trust words hidden: measured values bare, estimates with "≈".
        XCTAssertEqual(stats.map(\.shown), ["3.6", "51%", "≈ 26 ft"])
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

    /// All five product words explain themselves in one line (decision 059); any other word shows bare.
    func testEveryTrustWordHasOneLineAndNoOtherWordDoes() {
        for word in ["measured", "estimate", "listed", "verified", "not_scored"] {
            let line = Trust(word).description
            XCTAssertNotNil(line, word)
            XCTAssertFalse(line!.contains("\n"), word)
        }
        XCTAssertEqual(Trust("verified").description, "Checked on the ground by a runner.")
        XCTAssertNil(Trust("provisional").description, "a word the file sends that isn't one of the five shows bare")
        XCTAssertNil(Trust("").description)
    }

    // MARK: Crowd sentence from the pulses the route meets (decision 059)

    private static let ferry: [String: Any] = [
        "cause": "ferry", "name": "SeaStreak", "place": "East 35th St", "arrival": "08:00", "event": NSNull(),
        "from_mile": 0.57, "to_mile": 0.65, "meters": 100, "at": "08:05", "status": "estimate",
        "source": "SeaStreak arrival 08:00 at East 35th St (window -2/+8 min assumed, estimate)"]
    private static let school: [String: Any] = [
        "cause": "school", "name": "United Nations International School", "place": NSNull(), "arrival": NSNull(),
        "event": "arrival", "from_mile": 1.11, "to_mile": 1.92, "meters": 200, "at": "08:11", "status": "estimate",
        "source": "school arrival at United Nations International School (window 07:30-08:30 assumed, estimate)"]

    /// The bundled fixture with `summary.crowds.pulses` set on the #1 route, as the server now sends it.
    private func fixture(pulses: [[String: Any]]?) throws -> RouteFile {
        let url = Bundle.main.url(forResource: "kips3-ui", withExtension: "json")!
        var json = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as! [String: Any]
        var route = json["route"] as! [String: Any]
        var features = route["features"] as! [[String: Any]]
        for i in features.indices {
            var props = features[i]["properties"] as! [String: Any]
            guard var summary = props["summary"] as? [String: Any] else { continue }
            var crowds = summary["crowds"] as! [String: Any]
            if let pulses { crowds["pulses"] = pulses } else { crowds.removeValue(forKey: "pulses") }
            summary["crowds"] = crowds
            props["summary"] = summary
            features[i]["properties"] = props
        }
        route["features"] = features
        json["route"] = route
        return try RouteFile.decode(JSONSerialization.data(withJSONObject: json))
    }

    func testFerryPulseNamesTheLandingAndTheClock() throws {
        let data = try LoopData(file: fixture(pulses: [Self.ferry]))
        let detail = data.candidate(rank: 1)!.detail!
        XCTAssertEqual(detail.summary.crowds.pulses?.count, 1)
        XCTAssertEqual(detail.summary.crowds.pulses?.first?.place, "East 35th St")
        XCTAssertEqual(CardText.crowdSentence(detail, startTime: "8:00"), "≈ Busy near the E 35th St ferry around 8:05.")
    }

    func testSchoolPulseSaysDropOffOrPickUp() throws {
        let data = try LoopData(file: fixture(pulses: [Self.school]))
        XCTAssertEqual(CardText.crowdSentence(data.candidate(rank: 1)!.detail!, startTime: "8:00"),
                       "≈ Busy near a school at drop-off around 8:11.")
        var dismissal = Self.school
        dismissal["event"] = "dismissal"
        dismissal["at"] = "14:40"
        let later = try LoopData(file: fixture(pulses: [dismissal]))
        XCTAssertEqual(CardText.crowdSentence(later.candidate(rank: 1)!.detail!, startTime: "14:30"),
                       "≈ Busy near a school at pick-up around 14:40.")
    }

    func testFirstPulseInRouteOrderNamesTheLine() throws {
        let data = try LoopData(file: fixture(pulses: [Self.ferry, Self.school]))
        XCTAssertEqual(CardText.crowdSentence(data.candidate(rank: 1)!.detail!, startTime: "8:00"),
                       "≈ Busy near the E 35th St ferry around 8:05.")
    }

    func testNoPulsesFallsBackToTheStretchSentence() throws {
        // An empty list (crowds scored, no pulse met) and no list at all (older file) both read the stretches.
        for pulses in [[[String: Any]]?.some([]), nil] {
            let data = try LoopData(file: fixture(pulses: pulses))
            XCTAssertEqual(CardText.crowdSentence(data.candidate(rank: 1)!.detail!, startTime: data.request.startHourText),
                           "Busier on E 31st St around 7.")
        }
    }

    func testPulseSentenceNeverInventsACause() throws {
        var odd = Self.ferry
        odd["cause"] = "parade"
        let data = try LoopData(file: fixture(pulses: [odd]))
        XCTAssertEqual(CardText.crowdSentence(data.candidate(rank: 1)!.detail!, startTime: "7:00"),
                       "Busier on E 31st St around 7.", "an unknown cause falls back to the stretches")
        var noPlace = Self.ferry
        noPlace["place"] = NSNull()
        XCTAssertEqual(CardText.pulseSentence(try LoopData(file: fixture(pulses: [noPlace])).candidate(rank: 1)!.detail!
                                                .summary.crowds.pulses!.first!),
                       "≈ Busy near the ferry landing around 8:05.")
    }

    func testClockText() {
        XCTAssertEqual(CardText.clockText("08:05"), "8:05")
        XCTAssertEqual(CardText.clockText("08:00"), "8")
        XCTAssertEqual(CardText.clockText("14:20"), "14:20")
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

    func testANameNeverBreaksInsideAHyphenatedWord() {
        let shown = CardText.unbroken("East River out-and-back")
        XCTAssertEqual(shown, "East River out-\u{2060}and-\u{2060}back", "a word joiner after each hyphen")
        XCTAssertEqual(shown.replacingOccurrences(of: "\u{2060}", with: ""), "East River out-and-back", "nothing else changes")
        XCTAssertEqual(CardText.unbroken("Kips Bay loop"), "Kips Bay loop")
    }
}
