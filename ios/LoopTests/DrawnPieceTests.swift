import XCTest
@testable import Loop

final class DrawnPieceTests: XCTestCase {

    func testShortPieceJoinsLongerNeighbourThenSameKindsJoin() {
        let d = DrawnPiece.merged([(.path, 30), (.street, 5), (.path, 70)], lineLength: 105)
        XCTAssertEqual(d, [DrawnPiece(kind: .path, fromM: 0, toM: 105)])
    }

    func testPiecesOf20mOrMoreStay() {
        let d = DrawnPiece.merged([(.waterfront, 100), (.street, 20), (.waterfront, 100)], lineLength: 220)
        XCTAssertEqual(d.map(\.kind), [.waterfront, .street, .waterfront])
        XCTAssertEqual(d[1].lengthM, 20, accuracy: 1e-9)
    }

    func testChainOfShortPiecesGoesShortestFirst() {
        // 5 m goes into the 70 m path; then 15 m sits between 75 m path and 25 m path → the 75.
        let d = DrawnPiece.merged([(.waterfront, 200), (.path, 70), (.street, 5), (.street, 15), (.path, 25)],
                                  lineLength: 315)
        XCTAssertEqual(d.map(\.kind), [.waterfront, .path])
        XCTAssertEqual(d[1].lengthM, 115, accuracy: 1e-9)
    }

    func testScaledToTileTheLine() {
        let d = DrawnPiece.merged([(.street, 100), (.waterfront, 300)], lineLength: 200)
        XCTAssertEqual(d.first!.fromM, 0)
        XCTAssertEqual(d[0].toM, 50, accuracy: 1e-9)
        XCTAssertEqual(d.last!.toM, 200)
    }

    func testParkDrawsAsPath() {
        XCTAssertEqual(DrawKind(pieceKind: "park"), .path)
        XCTAssertEqual(DrawKind(pieceKind: "waterfront"), .waterfront)
        XCTAssertNil(DrawKind(pieceKind: "ferry"))
    }

    /// The fixture's 25 pieces become 11 drawn runs: the 5 and 16 m street bits on the esplanade
    /// join the path beside them, and the 5 m bit at the turn back joins the waterfront.
    func testFixtureDrawsElevenRuns() throws {
        let detail = try LoopData(file: RouteFile.loadBundled()).candidate(rank: 1)!.detail!
        XCTAssertEqual(detail.drawn.map(\.kind), [
            .street, .waterfront, .street, .path, .waterfront, .street,
            .waterfront, .path, .street, .waterfront, .street,
        ])
        XCTAssertEqual(detail.drawn.first!.fromM, 0)
        XCTAssertEqual(detail.drawn.last!.toM, detail.line.length, accuracy: 1e-6)
        for (a, b) in zip(detail.drawn, detail.drawn.dropFirst()) {
            XCTAssertEqual(a.toM, b.fromM, accuracy: 1e-9)
            XCTAssertGreaterThanOrEqual(a.lengthM, 20)
        }
        let path = detail.drawn.filter { $0.kind == .path }.reduce(0) { $0 + $1.lengthM }
        XCTAssertEqual(path, 307.2 * detail.line.length / 4877.7, accuracy: 0.5)
    }
}

final class ZoomDetailTests: XCTestCase {
    private var candidate: Candidate!

    override func setUpWithError() throws {
        candidate = try LoopData(file: RouteFile.loadBundled()).candidate(rank: 1)
    }

    func testMetresPerPoint() {
        // Zoom 0 at the equator: one 512 pt tile spans the world.
        XCTAssertEqual(MapScale.metresPerPoint(zoom: 0, latitude: 0), 40_075_016.686 / 512, accuracy: 0.01)
        XCTAssertEqual(MapScale.metresPerPoint(zoom: 1, latitude: 60), 40_075_016.686 / 512 / 4, accuracy: 0.01)
    }

    func testCloseInEveryRunShowsAndPathIsDashed() {
        let mpp = MapScale.metresPerPoint(zoom: 18, latitude: 40.74)   // about 0.45 m per pt
        let kinds = RouteFrame.layerKinds(for: candidate, metresPerPoint: mpp)
        XCTAssertEqual(kinds, candidate.detail!.drawn.filter { $0.kind != .street }.map(\.kind.rawValue),
                       "every waterfront and path run styled on the base line; street is the base line")
    }

    func testOverviewMergesShortRunsAndKeepsRulesOnScreen() {
        let mpp = MapScale.metresPerPoint(zoom: 13.5, latitude: 40.74)
        let runs = DrawnPiece.merged(candidate.detail!.drawn.map { ($0.kind, $0.lengthM) },
                                     lineLength: candidate.line.length, minimum: 40 * mpp)
        XCTAssertLessThan(runs.count, candidate.detail!.drawn.count)
        for r in runs.dropLast() { XCTAssertGreaterThanOrEqual(r.lengthM / mpp, 40) }
        let segs = RouteFrame.segments(for: candidate, fraction: 1, metresPerPoint: mpp)
        let dashedRuns = runs.filter { $0.kind == .path && $0.lengthM / mpp >= 30 }
        XCTAssertEqual(segs.contains { $0.isDash }, !dashedRuns.isEmpty)
    }

    func testDashesStartAndEndOnADash() {
        let mpp = 0.8
        let dashes = RouteFrame.fittedDashes(from: 100, to: 100 + 47 * mpp, mpp: mpp)  // 47 pt run
        XCTAssertGreaterThanOrEqual(dashes.count, 2)
        XCTAssertEqual(dashes.first!.0, 100, accuracy: 1e-9, "starts on a dash")
        XCTAssertEqual(dashes.last!.1, 100 + 47 * mpp, accuracy: 1e-9, "ends on a dash")
        let lengths = dashes.map { $0.1 - $0.0 }
        for l in lengths { XCTAssertEqual(l, lengths[0], accuracy: 1e-9) }
        // Stretch stays within half a period of the 9/6 pattern.
        XCTAssertEqual(lengths[0] / mpp, 9, accuracy: 9 * 0.5)
    }

    func testStyledRunsAreCutEdgeToEdgeFromTheDrawnLine() {
        let mpp = MapScale.metresPerPoint(zoom: 18, latitude: 40.74)
        let display = RouteFrame.displayLine(for: candidate.line, metresPerPoint: mpp)
        let runs = candidate.detail!.drawn
        let segs = RouteFrame.segments(for: candidate, fraction: 1, metresPerPoint: mpp).filter { !$0.isDash }
        // Each styled run spans exactly its mapped range on the drawn line: no overlap past a join.
        for (seg, run) in zip(segs, runs.filter { $0.kind != .street }) {
            let expected = display.along(fromFull: run.toM) - display.along(fromFull: run.fromM)
            XCTAssertEqual(Polyline(seg.points).length, expected, accuracy: 0.01)
        }
    }

    func testCasingIsOneLineForTheWholeRoute() async throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let frame = await MainActor.run { () -> RouteFrame in
            let model = MainModel(data: data, runs: RunStore())
            return model.frame(now: 0, reduceMotion: true)
        }
        // One line for the whole route, the same geometry the base line uses.
        let display = RouteFrame.displayLine(for: candidate.line, metresPerPoint: MapScale.metresPerPoint(zoom: 14, latitude: candidate.line.points[0].lat))
        XCTAssertEqual(frame.casing, display.line.points)
    }

    func testShortPathRunDrawsSolidAndRouteWithoutPiecesIsOneLine() {
        let one = Candidate(rank: 9, line: candidate.line, distanceMi: 3, distanceTrust: nil, kindText: "", detail: nil)
        XCTAssertEqual(RouteFrame.segments(for: one, fraction: 1, metresPerPoint: 1).map(\.layerKind), ["lead"])
        // At overview scale the esplanade's ~150 m path runs are under 30 pt: solid, no dashes.
        let mpp = MapScale.metresPerPoint(zoom: 14.6, latitude: 40.74)
        for seg in RouteFrame.segments(for: candidate, fraction: 1, metresPerPoint: mpp) where seg.kind == .path {
            XCTAssertFalse(seg.isDash && Polyline(seg.points).length / mpp < 1, "no sliver dashes")
        }
    }
}

final class StripRunTests: XCTestCase {
    func testStripRunsAtStripScale() throws {
        let d = try LoopData(file: RouteFile.loadBundled()).candidate(rank: 1)!.detail!
        let width = 342.0
        let runs = d.stripRuns(width: width)
        let ptPerMile = width / d.distanceMi
        XCTAssertLessThan(runs.count, d.drawn.count, "the 21-27 m street bits are under 16 pt here")
        XCTAssertEqual(runs.first!.fromMile, 0)
        XCTAssertEqual(runs.last!.toMile, d.distanceMi, accuracy: 1e-9)
        for (a, b) in zip(runs, runs.dropFirst()) {
            XCTAssertNotEqual(a.kind, b.kind, "same-kind neighbours are one run")
            XCTAssertEqual(a.toMile, b.fromMile, accuracy: 1e-9)
        }
        for r in runs {
            let pts = (r.toMile - r.fromMile) * ptPerMile
            XCTAssertGreaterThanOrEqual(pts, 16)
            XCTAssertEqual(r.dashed, r.kind == .path && pts >= 10.5)
        }
    }
}

final class DisplayLineTests: XCTestCase {
    // East 200 m with a 3 m step to the north at 100 m, then a real 90° turn north for 100 m.
    private func stepped() -> Polyline {
        let m = 1 / 111_000.0, mx = 1 / (111_320 * cos(50 * Double.pi / 180))
        return Polyline([
            GeoPoint(lon: 10, lat: 50),
            GeoPoint(lon: 10 + 100 * mx, lat: 50),
            GeoPoint(lon: 10 + 100 * mx, lat: 50 + 3 * m),
            GeoPoint(lon: 10 + 200 * mx, lat: 50 + 3 * m),
            GeoPoint(lon: 10 + 200 * mx, lat: 50 + 103 * m),
        ])
    }

    func testSmallJogRemovedRealTurnKept() {
        let d = DisplayLine(full: stepped(), toleranceMetres: 5)
        XCTAssertEqual(d.line.points.count, 3, "start, the corner, the end")
        XCTAssertEqual(d.line.points.first, stepped().points.first)
        XCTAssertEqual(d.line.points.last, stepped().points.last)
        XCTAssertEqual(DisplayLine(full: stepped(), toleranceMetres: 1).line.points.count, 5, "close in, every jog stays")
        XCTAssertEqual(DisplayLine(full: stepped(), toleranceMetres: 0).line, stepped())
    }

    func testAlongMapIsMonotonicWithMatchingEnds() {
        let full = stepped()
        let d = DisplayLine(full: full, toleranceMetres: 5)
        XCTAssertEqual(d.along(fromFull: 0), 0)
        XCTAssertEqual(d.along(fromFull: full.length), d.line.length, accuracy: 1e-9)
        var last = -1.0
        for a in stride(from: 0.0, through: full.length, by: 7) {
            let m = d.along(fromFull: a)
            XCTAssertGreaterThanOrEqual(m, last)
            last = m
        }
    }

    func testOutAndBackLegsStayOnTopOfEachOther() throws {
        let line = try LoopData(file: RouteFile.loadBundled()).candidate(rank: 1)!.line
        for z in [13.5, 15.0, 16.5] {
            let d = DisplayLine(full: line, toleranceMetres: MapScale.metresPerPoint(zoom: z, latitude: 40.74) * 2.5)
            // Every kept vertex on the esplanade's outbound leg has a kept twin on the return leg.
            let turn = 2439.0
            let outbound = d.line.points.enumerated().filter { d.fullAlong[$0.offset] > 1700 && d.fullAlong[$0.offset] < turn - 20 }
            let returning = d.line.points.enumerated().filter { d.fullAlong[$0.offset] > turn + 20 }.map(\.element)
            for (_, p) in outbound {
                let nearest = returning.map { $0.distance(to: p) }.min() ?? .infinity
                XCTAssertLessThan(nearest, 0.5, "zoom \(z)")
            }
            XCTAssertLessThan(d.line.points.count, line.points.count, "zoom \(z) drops sub-2.5 pt jogs")
        }
    }
}
