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
        XCTAssertEqual(kinds, candidate.detail!.drawn.map(\.kind.rawValue), "all 11 runs, path dashed")
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

    func testRunsOverlapByAboutOnePointAtJoins() {
        let mpp = MapScale.metresPerPoint(zoom: 18, latitude: 40.74)
        let segs = RouteFrame.segments(for: candidate, fraction: 1, metresPerPoint: mpp)
        // The first run reaches 0.5 pt past its end; the second 0.5 pt past both ends.
        let runs = candidate.detail!.drawn
        let first = segs[0]
        XCTAssertEqual(Polyline(first.points).length, runs[0].lengthM + 0.5 * mpp, accuracy: 0.01)
        XCTAssertEqual(segs.first { !$0.isDash && $0.kind == runs[1].kind }.map { Polyline($0.points).length } ?? 0,
                       runs[1].lengthM + 1.0 * mpp, accuracy: 0.01)
    }

    func testCasingIsOneLineForTheWholeRoute() async throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let frame = await MainActor.run { () -> RouteFrame in
            let model = MainModel(data: data)
            return model.frame(now: 0, reduceMotion: true)
        }
        XCTAssertEqual(Polyline(frame.casing).length, candidate.line.length, accuracy: 0.01)
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
