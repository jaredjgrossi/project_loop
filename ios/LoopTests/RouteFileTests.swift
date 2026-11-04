import XCTest
@testable import Loop

/// Checks the fixture reads the way the card needs it. Values are the file's, not the mockups'.
final class RouteFileTests: XCTestCase {

    private var data: LoopData!
    private var detail: RouteDetail { data.candidate(rank: 1)!.detail! }

    override func setUpWithError() throws {
        data = try LoopData(file: RouteFile.loadBundled())
    }

    func testTopThreeAndPool() {
        XCTAssertEqual(data.candidates.map(\.rank), [1, 2, 3])
        XCTAssertNotNil(data.candidate(rank: 1)?.detail)
        XCTAssertNil(data.candidate(rank: 2)?.detail, "only #1 carries stretches")
        XCTAssertEqual(data.bestOf, 31)
    }

    func testTopThreeDistancesCarryTheFileTrustLabel() {
        XCTAssertEqual(data.candidate(rank: 2)?.distanceMi, 3.01)
        XCTAssertEqual(data.candidate(rank: 2)?.distanceTrust, Trust("measured"))
        XCTAssertEqual(data.candidate(rank: 3)?.distanceMi, 3.05)
        XCTAssertEqual(data.candidate(rank: 1)?.distanceTrust, Trust("measured"))
    }

    func testRouteLengthMatchesFileDistance() {
        // summary.distance.meters is 4878; haversine on the same coordinates agrees within 0.5%.
        XCTAssertEqual(detail.line.length, 4878, accuracy: 4878 * 0.005)
        XCTAssertEqual(detail.distanceMi, 3.03)
        XCTAssertEqual(detail.distanceTrust.text, "measured")
    }

    func testMilePointsSitOnTheLineAtTheirDistance() {
        XCTAssertEqual(detail.miles.map(\.mile), [1, 2, 3])
        for m in detail.miles {
            let onLine = detail.line.point(at: m.alongM)
            XCTAssertLessThan(onLine.distance(to: m.point), 25, "mile \(m.mile)")
        }
    }

    func testTurnaround() throws {
        let t = try XCTUnwrap(detail.turnaround)
        XCTAssertEqual(t.alongMi, 1.52)
        XCTAssertLessThan(detail.line.point(at: t.alongM).distance(to: t.point), 25)
    }

    func testStretchesTileTheLine() {
        let s = detail.stretches
        XCTAssertEqual(s.count, 7)
        XCTAssertEqual(s.first!.fromM, 0, accuracy: 0.001)
        XCTAssertEqual(s.last!.toM, detail.line.length, accuracy: 1)
        for (a, b) in zip(s, s.dropFirst()) {
            XCTAssertEqual(a.toM, b.fromM, accuracy: 0.001)
        }
    }

    func testMileOneIsOnTheEsplanade() {
        XCTAssertEqual(detail.stretch(atMile: 1.0)?.name, "East River Esplanade")
        XCTAssertEqual(detail.stretch(atMile: 0.1)?.name, "East 31st Street")
        XCTAssertEqual(detail.stretch(atMile: 3.03)?.name, "East 31st Street", "end of route")
    }

    func testLargestShareKinds() {
        XCTAssertEqual(detail.stretches.map(\.kind),
                       [.street, .street, .street, .waterfront, .street, .street, .street])
    }

    func testElevationProfile() {
        XCTAssertEqual(detail.profile.count, 31)
        XCTAssertEqual(detail.profileTrust.text, "estimate")
        XCTAssertEqual(detail.elevation(atMile: 0), 9.5)
        // halfway between 0.1 (9.2) and 0.2 (9.0)
        XCTAssertEqual(detail.elevation(atMile: 0.15), 9.1, accuracy: 1e-9)
        XCTAssertEqual(detail.elevation(atMile: 3.03), detail.profile.last!.elevationM)
    }
}
