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

    // MARK: Phone test of PR #18 (2026-11-13)

    @MainActor private func model(from data: LoopData) -> MainModel {
        let m = MainModel(data: data, runs: RunStore())
        return m
    }

    @MainActor func testOnlyFullRoutesAreOffered() throws {
        // A saved route from before the server sent files: one route in full, two outlines.
        let m = model(from: try LoopData(file: RouteFile.loadBundled()))
        m.receiveEvent(.final([1, 2, 3]), at: 0)
        XCTAssertEqual(m.routeChoices, [], "no dots, no swipe, no alternates for a single full route")
        XCTAssertFalse(m.showNeighbour(1))
        XCTAssertEqual(m.eyebrowText, "OUT AND BACK", "no position, no mode, no count")

        let final = try finalEvent(shape: nil)
        let full = try LoopData(file: XCTUnwrap(RouteFile.from(final: final, start: "Kips Bay Library")))
        let n = model(from: full)
        n.receiveEvent(.final([1, 2, 3]), at: 0)
        XCTAssertEqual(n.routeChoices, [1, 2, 3])
        XCTAssertEqual(n.eyebrowText, "1 OF 3 · OUT AND BACK")
        XCTAssertTrue(n.showNeighbour(1))
        XCTAssertEqual(n.shownRank, 2)
        XCTAssertTrue(n.eyebrowText.hasPrefix("2 OF 3"))
        XCTAssertFalse(n.eyebrowText.contains("BEST OF"))
        XCTAssertTrue(n.showNeighbour(1))
        XCTAssertFalse(n.showNeighbour(1), "no fourth route")
        XCTAssertTrue(n.showNeighbour(-1))
        XCTAssertEqual(n.shownRank, 2)
    }

    func testNameIsCapitalisedAndWrapsToTwoLines() {
        XCTAssertEqual(CardText.nameLine("out-and-back on the waterfront"), "Out-and-back on the waterfront")
        XCTAssertEqual(CardText.nameLines("Loop through Central Park", width: 342), 1)
        XCTAssertEqual(CardText.nameLines("Out-and-back on the Franklin D. Roosevelt East River Drive Greenway", width: 342), 2)
    }

    func testClimbReadsInFeet() {
        XCTAssertEqual(CardText.feet(10), 33)
        XCTAssertEqual(CardText.feet(8), 26)
    }

    func testSwipeRules() {
        XCTAssertEqual(RouteSwipe.axis(of: CGSize(width: -30, height: 4), canSwipe: true), .horizontal)
        XCTAssertEqual(RouteSwipe.axis(of: CGSize(width: 10, height: -30), canSwipe: true), .vertical, "up and down is the sheet's")
        XCTAssertEqual(RouteSwipe.axis(of: CGSize(width: 20, height: 18), canSwipe: true), .vertical, "a diagonal stays with the sheet")
        XCTAssertEqual(RouteSwipe.axis(of: CGSize(width: -30, height: 2), canSwipe: false), .vertical, "one route: nothing to swipe to")
        XCTAssertFalse(RouteSwipe.commits(translation: -20, predicted: -60))
        XCTAssertTrue(RouteSwipe.commits(translation: -60, predicted: -80))
        XCTAssertTrue(RouteSwipe.commits(translation: 20, predicted: 200), "a flick")
    }
}
