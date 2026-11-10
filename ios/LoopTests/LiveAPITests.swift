import XCTest
@testable import Loop

/// The Phase 3 wire format (parse-contract-v1): events in, the request out.
final class LiveAPITests: XCTestCase {
    private func event(_ json: String) -> ServerEvent { ServerEvent.decode(Data(json.utf8)) }

    func testParsedWithSpansReachAndQuestion() throws {
        let e = event(#"""
        {"event":"parsed","v":1,"parse_id":"p_1","reach_m":2550,
         "chips":[{"id":"c_distance","field":"distance","text":"3 mi","source":"said","editable":true,
                   "span":{"text":"3 miles","start":2,"end":9}},
                  {"id":"c_mode","field":"mode","text":"Training","source":"preset","editable":true,"span":null}],
         "question":{"id":"q_1","about":"start","from":"places","text":"Which 86th St?",
                     "options":[{"id":"a","text":"East side"}],"allow_text":true,"chip_id":"c_start"},
         "cant":[{"id":"k_1","gap":"G9","text":"Can't plan around street lighting yet"}],
         "notes":[{"id":"n_1","key":"fountains_seasonal","text":"Fountains may be off","trust":"listed"}],
         "constraints":{"distance_mi":3}}
        """#)
        guard case let .parsed(p) = e else { return XCTFail("not parsed: \(e)") }
        XCTAssertEqual(p.parseId, "p_1")
        XCTAssertEqual(p.reachM, 2550)
        XCTAssertEqual(p.chips.first?.span, .init(text: "3 miles", start: 2, end: 9))
        XCTAssertEqual(p.question?.chipId, "c_start")
        XCTAssertEqual(p.question?.allowText, true)

        // Spans count Unicode scalars; the sentence's NSString offsets differ after an emoji.
        let sentence = "🏃 3 miles by the water."
        let r = ReadOut(parsed: p, sentence: sentence)
        let u = try XCTUnwrap(r.understood.first)
        XCTAssertEqual((sentence as NSString).substring(with: NSRange(location: u.start, length: u.length)), "3 miles")
        XCTAssertEqual(u.value, "3 mi", "values shown as sent")
        XCTAssertEqual(r.filled.map(\.main), ["Training"], "preset and default chips are what Loop filled in")
        XCTAssertEqual(r.cant.map(\.gap), ["G9"])
        XCTAssertEqual(r.notes.first?.trust, "listed")
    }

    func testRoutesFinalQuestionErrorAndUnknown() {
        let top = #"{"id":"r_1.7","rank":1,"kind":"loop","label":"Loop","score":0.42,"distance":{"value":3.02,"status":"measured","source":"route geometry"},"geometry":{"type":"LineString","coordinates":[[-73.97,40.74],[-73.96,40.75]]}}"#
        guard case let .top3(t) = event(#"{"event":"top3","route_id":"r_1","elapsed_s":0.4,"provisional":false,"routes":[\#(top)]}"#) else {
            return XCTFail("top3")
        }
        XCTAssertEqual(t.routes.first?.id, "r_1.7")
        XCTAssertEqual(t.routes.first?.distance.value, 3.02)
        guard case .provisional = event(#"{"event":"provisional","route_id":"r_1","routes":[\#(top)]}"#) else { return XCTFail("provisional") }
        guard case let .final(f) = event(#"{"event":"final","route_id":"r_1","routes":[\#(top)],"route":null,"pool":{"candidates":40,"best_of":31},"pool_size":31,"notes":[{"key":"no_route","text":"No route fits","trust":"measured"}],"timing":{}}"#) else {
            return XCTFail("final")
        }
        XCTAssertNil(f.route)
        XCTAssertEqual(f.pool?.bestOf, 31)
        XCTAssertEqual(f.notes?.first?.text, "No route fits")
        guard case let .question(q) = event(#"{"event":"question","v":1,"parse_id":"p_9","id":"q_1","about":"distance","from":"engine","text":"Make it 4.5 mi?","options":[{"id":"a","text":"4.5 mi"}],"allow_text":true}"#) else {
            return XCTFail("question")
        }
        XCTAssertEqual(q.parseId, "p_9")
        guard case let .error(code, text) = event(#"{"event":"error","code":"expired","text":"Start again"}"#) else { return XCTFail("error") }
        XCTAssertEqual(code, "expired")
        XCTAssertEqual(text, "Start again")
        guard case .done = event(#"{"event":"done"}"#) else { return XCTFail("done") }
        guard case .other = event(#"{"event":"something_new","v":2}"#) else { return XCTFail("unknown events are ignored") }
        guard case let .candidates(c) = event(#"{"event":"candidates","v":1,"route_id":"r_1","elapsed_s":0.42,"candidates":[{"id":"r_1.7","kind":"loop","points":[[-73.97,40.74],[-73.96,40.75]]}]}"#) else {
            return XCTFail("candidates")
        }
        XCTAssertEqual(c.candidates.first?.points.count, 2)
    }

    func testRequestEncodingSnakeCaseNullLocationAndAnswer() throws {
        let body = RunRequest(text: "3 miles", answer: nil, client: RunRequest.client(location: nil),
                              profile: .init(), recentRoutes: [.init(id: "r_a.1", date: "2026-11-08", name: "Esplanade",
                                                                     distanceMi: 3, timesRun: 2)])
        let json = try XCTUnwrap(String(data: LoopAPI.encoder.encode(body), encoding: .utf8))
        XCTAssertTrue(json.contains(#""location":null"#), "location is null when off")
        XCTAssertTrue(json.contains(#""usual_distance_mi":3.1"#))
        XCTAssertTrue(json.contains(#""recent_routes":[{"#))
        XCTAssertTrue(json.contains(#""times_run":2"#))
        XCTAssertFalse(json.contains(#""answer""#), "exactly one of text or answer")

        let answered = RunRequest(text: nil, answer: .init(parseId: "p_1", questionId: "q_1", optionId: nil, text: "about 6 miles"),
                                  client: RunRequest.client(location: .init(lat: 40.7, lon: -73.9, accuracyM: 15)),
                                  profile: .init(), recentRoutes: [])
        let a = try XCTUnwrap(String(data: LoopAPI.encoder.encode(answered), encoding: .utf8))
        XCTAssertTrue(a.contains(#""option_id":null"#))
        XCTAssertTrue(a.contains(#""parse_id":"p_1""#))
        XCTAssertTrue(a.contains(#""accuracy_m":15"#))
        XCTAssertFalse(a.contains(#""text":"#) && a.contains(#""v":1,"text""#), "no top-level text with an answer")
    }

    func testClientNowCarriesTheOffset() {
        let c = RunRequest.client(location: nil, now: Date(timeIntervalSince1970: 1_800_000_000))
        XCTAssertTrue(c.now.contains("T"))
        XCTAssertFalse(c.tz.isEmpty)
    }
}
