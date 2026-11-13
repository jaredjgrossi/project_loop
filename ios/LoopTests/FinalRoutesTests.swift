import XCTest
@testable import Loop

/// What the `final` event carries since decision 049: every route in full, the server's names,
/// the route-type flag and the reason line.
final class FinalRoutesTests: XCTestCase {

    private func fixture() throws -> [String: Any] {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "kips3-ui", withExtension: "json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
    }

    /// A `final` the way the server sends it now: each route has its own `file`, a name, and `shape`.
    private func finalEvent(shape: [String: Any]?, reason: String?? = nil) throws -> ServerEvent.Final {
        let f = try fixture()
        let route = try XCTUnwrap(f["route"] as? [String: Any])
        var features = try XCTUnwrap(route["features"] as? [[String: Any]])
        if let reason {
            var props = features[0]["properties"] as! [String: Any]
            var summary = props["summary"] as! [String: Any]
            summary["reason"] = ["text": reason as Any? ?? NSNull(), "status": "estimate", "source": "route numbers"]
            props["summary"] = summary
            features[0]["properties"] = props
        }
        var file = route
        file["features"] = features
        let names = ["Out-and-back on East River Esplanade", "Loop through Stuyvesant Town", "Out-and-back on Second Avenue"]
        let top = try XCTUnwrap(f["top3"] as? [[String: Any]])
        let routes: [[String: Any]] = top.enumerated().map { i, t in
            var t = t
            t["id"] = "r_1.\(i + 1)"
            t["label"] = names[i]
            t["file"] = file
            return t
        }
        var event: [String: Any] = ["event": "final", "route_id": "r_1", "routes": routes, "route": file,
                                    "pool": f["pool"] as Any, "pool_size": 31]
        if let shape { event["shape"] = shape }
        let e = ServerEvent.decode(try JSONSerialization.data(withJSONObject: event))
        guard case let .final(final, _) = e else { throw XCTSkip("not a final: \(e)") }
        return final
    }

    func testEveryRouteCarriesItsFullDetailAndTheFinalName() throws {
        let final = try finalEvent(shape: ["requested": "any", "met": true, "shown": ["out_and_back", "loop"]])
        let file = try XCTUnwrap(RouteFile.from(final: final, start: "Kips Bay Library"))
        let data = try LoopData(file: file)
        XCTAssertEqual(data.candidates.count, 3)
        for c in data.candidates {
            let d = try XCTUnwrap(c.detail, "route \(c.rank) is fully viewable, not an outline")
            XCTAssertFalse(d.stretches.isEmpty)
            XCTAssertFalse(d.profile.isEmpty)
            XCTAssertFalse(CardText.stats(d.summary).isEmpty)
        }
        XCTAssertEqual(data.candidates.map(\.name), ["Out-and-back on East River Esplanade", "Loop through Stuyvesant Town",
                                                     "Out-and-back on Second Avenue"])
        XCTAssertEqual(data.candidates.map(\.serverId), ["r_1.1", "r_1.2", "r_1.3"])
    }

    func testOlderFinalGivesOutlinesForTheOthers() throws {
        // The bundled file (and finals before decision 049): only #1 has detail.
        let data = try LoopData(file: RouteFile.loadBundled())
        XCTAssertNotNil(data.candidate(rank: 1)?.detail)
        XCTAssertNil(data.candidate(rank: 2)?.detail)
    }

    func testShapeFlag() throws {
        let met = try finalEvent(shape: ["requested": "loop", "met": true, "shown": ["loop"]])
        XCTAssertEqual(met.shape, .init(requested: "loop", met: true, shown: ["loop"]))
        XCTAssertNil(CardText.shapeNote(met.shape), "nothing to say when the type was found")
        XCTAssertNil(CardText.shapeNote(nil), "an older server sends no flag")
        let miss = try finalEvent(shape: ["requested": "loop", "met": false, "shown": ["out_and_back"]])
        XCTAssertEqual(CardText.shapeNote(miss.shape), "No loop from here beats this out-and-back.")
        XCTAssertEqual(CardText.shapeNote(.init(requested: "out_and_back", met: false, shown: ["loop"])),
                       "No out-and-back found. This is the best loop.")
        XCTAssertEqual(CardText.shapeNote(.init(requested: "one_way", met: false, shown: ["out_and_back"])),
                       "No one-way run found. This is the best out-and-back.")
        XCTAssertNil(CardText.shapeNote(.init(requested: "loop", met: false, shown: [])), "no route: the notice says so")
    }

    func testReasonLineIsTheServersWhenItHasOne() throws {
        let with = try finalEvent(shape: nil, reason: "58% on the waterfront, 22 lights, flat")
        let summary = try XCTUnwrap(with.route?.features.first?.properties.summary)
        XCTAssertEqual(CardText.reasonLine(summary), "58% on the waterfront, 22 lights, flat.")
        XCTAssertEqual(summary.reason?.source, "route numbers")

        let lower = try finalEvent(shape: nil, reason: "no lights, flat")
        XCTAssertEqual(CardText.reasonLine(try XCTUnwrap(lower.route?.features.first?.properties.summary)), "No lights, flat.")

        // Nothing stands out (text null) or an older server (no key): the sentence built here.
        let none = try finalEvent(shape: nil, reason: .some(nil))
        let fallback = CardText.reasonLine(try XCTUnwrap(none.route?.features.first?.properties.summary))
        XCTAssertEqual(fallback, "About half by the water: 3.6 lights a mile.")
        let old = try finalEvent(shape: nil)
        XCTAssertEqual(CardText.reasonLine(try XCTUnwrap(old.route?.features.first?.properties.summary)), fallback)
    }

    func testPickingARouteAfterFinalOnly() {
        var b = BuildState()
        b.apply(.top3([1, 2, 3]), at: 0)
        b.select(2, at: 1)
        XCTAssertEqual(b.shownRank, 1, "before final the engine decides")
        b.apply(.provisional, at: 2)
        b.apply(.final([1, 2, 3]), at: 3)
        b.select(2, at: 4)
        XCTAssertEqual(b.shownRank, 2)
        XCTAssertEqual(b.morph, BuildState.Morph(from: 1, to: 2, start: 4))
        XCTAssertEqual(b.otherRanks, [1, 3])
        b.select(9, at: 5)
        XCTAssertEqual(b.shownRank, 2, "not one of the three")
    }
}
