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
        let segs = RouteFrame.segments(for: candidate, fraction: 1, metresPerPoint: mpp)
        XCTAssertLessThan(segs.count, candidate.detail!.drawn.count)
        let runs = DrawnPiece.merged(candidate.detail!.drawn.map { ($0.kind, $0.lengthM) },
                                     lineLength: candidate.line.length, minimum: 40 * mpp)
        for r in runs.dropLast() { XCTAssertGreaterThanOrEqual(r.lengthM / mpp, 40) }
        for (seg, run) in zip(segs, runs) where seg.kind == .path {
            XCTAssertEqual(seg.dashed, run.lengthM / mpp >= 30)
        }
    }

    func testShortPathRunDrawsSolid() {
        // A route without pieces draws as one plain line; a short path segment goes to the solid layer.
        let one = Candidate(rank: 9, line: candidate.line, distanceMi: 3, distanceTrust: nil, kindText: "", detail: nil)
        XCTAssertEqual(RouteFrame.segments(for: one, fraction: 1, metresPerPoint: 1).first?.layerKind, "lead")
        let seg = RouteFrame.Segment(kind: .path, points: [], dashed: false)
        XCTAssertEqual(seg.layerKind, "pathSolid")
        XCTAssertEqual(RouteFrame.Segment(kind: .path, points: []).layerKind, "path")
    }
}
