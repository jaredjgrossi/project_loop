import XCTest
@testable import Loop

/// "Share route": the GPX the share sheet hands to other apps.
final class GPXTests: XCTestCase {
    func testTrackWaypointsAndEscaping() {
        let gpx = GPX.make(name: "Kips Bay & \"the\" <river>",
                           track: [GeoPoint(lon: -73.9780000, lat: 40.7430000), GeoPoint(lon: -73.9700000, lat: 40.7480000)],
                           waypoints: [.init(point: GeoPoint(lon: -73.97, lat: 40.748), name: "Turnaround")])
        XCTAssertTrue(gpx.hasPrefix("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"))
        XCTAssertTrue(gpx.contains("<name>Kips Bay &amp; &quot;the&quot; &lt;river&gt;</name>"))
        XCTAssertTrue(gpx.contains("<trkpt lat=\"40.7430000\" lon=\"-73.9780000\">"))
        XCTAssertTrue(gpx.contains("<wpt lat=\"40.7480000\" lon=\"-73.9700000\"><name>Turnaround</name></wpt>"))
        XCTAssertEqual(gpx.components(separatedBy: "<trkpt").count - 1, 2)
        // Well-formed XML.
        let parser = XMLParser(data: Data(gpx.utf8))
        XCTAssertTrue(parser.parse(), "\(String(describing: parser.parserError))")
    }

    func testRouteFromTheFixtureHasMilesAndTurnaround() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let c = try XCTUnwrap(data.candidate(rank: 1))
        let gpx = GPX.make(name: "Test", candidate: c)
        XCTAssertEqual(gpx.components(separatedBy: "<trkpt").count - 1, c.line.points.count)
        XCTAssertTrue(gpx.contains("<name>Mile 1</name>"))
        XCTAssertTrue(XMLParser(data: Data(gpx.utf8)).parse())
        // A route without details (#2, #3) is just the line.
        let plain = GPX.make(name: "Test", candidate: try XCTUnwrap(data.candidate(rank: 2)))
        XCTAssertFalse(plain.contains("<wpt"))
    }

    func testFileNameIsSafe() {
        XCTAssertEqual(GPX.fileName("East River / Esplanade: out & back"), "Loop - East River Esplanade out & back.gpx")
        XCTAssertEqual(GPX.fileName("///"), "Loop - route.gpx")
    }
}
