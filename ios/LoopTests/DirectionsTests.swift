import XCTest
@testable import Loop

/// The step-by-step list, from the file's stretches and turnaround.
final class DirectionsTests: XCTestCase {
    private typealias Leg = Directions.Leg

    private let outAndBack: [Leg] = [
        .init(name: "East 31st Street", from: 0, to: 0.21), .init(name: "East 30th Street", from: 0.21, to: 0.46),
        .init(name: "East River Esplanade", from: 0.46, to: 2.44), .init(name: "East 30th Street", from: 2.44, to: 2.88),
        .init(name: "East 31st Street", from: 2.88, to: 3.03)]

    func testOutAndBackReadsOutTurnsAroundAndComesBack() {
        let s = Directions.steps(legs: outAndBack, turnaround: 1.52, total: 3.03, backAtStart: true)
        XCTAssertEqual(s.map(\.text), [
            "Start on East 31st Street", "Continue onto East 30th Street", "Continue onto East River Esplanade",
            "Turn around", "Head back on East River Esplanade", "Continue onto East 30th Street",
            "Continue onto East 31st Street", "Finish back at the start"])
        XCTAssertEqual(s[2].miles ?? 0, 1.06, accuracy: 0.001, "out to the turnaround")
        XCTAssertEqual(s[4].miles ?? 0, 0.92, accuracy: 0.001, "and back to the end of the stretch")
        XCTAssertEqual(s[3].mile, 1.52)
        XCTAssertEqual(s.last?.mile, 3.03)
        XCTAssertEqual(s.map(\.id), Array(0..<s.count))
    }

    func testALoopHasNoTurnaround() {
        let s = Directions.steps(legs: [.init(name: "Park Drive", from: 0, to: 1.5), .init(name: "Fifth Avenue", from: 1.5, to: 3)],
                                 turnaround: nil, total: 3, backAtStart: true)
        XCTAssertEqual(s.map(\.text), ["Start on Park Drive", "Continue onto Fifth Avenue", "Finish back at the start"])
    }

    func testAOneWayRunEndsElsewhere() {
        let s = Directions.steps(legs: [.init(name: "Hudson River Greenway", from: 0, to: 4)], turnaround: nil, total: 4, backAtStart: false)
        XCTAssertEqual(s.map(\.text), ["Start on Hudson River Greenway", "Finish"])
    }

    func testNeighboursWithOneNameAreOneStepAndCrossingsAreFolded() {
        let s = Directions.steps(legs: [
            .init(name: "waterfront path", from: 0, to: 0.5), .init(name: "waterfront path", from: 0.5, to: 1),
            .init(name: "East 23rd Street", from: 1, to: 1.01),   // 16 m: a crossing
            .init(name: "waterfront path", from: 1.01, to: 2)], turnaround: nil, total: 2, backAtStart: false)
        XCTAssertEqual(s.map(\.text), ["Start on Waterfront path", "Finish"], "names get a capital; one stretch")
        XCTAssertEqual(s[0].miles ?? 0, 2, accuracy: 0.001)
    }

    func testTurnaroundAtAStretchBoundaryDoesNotSplitIt() {
        let s = Directions.steps(legs: [.init(name: "A Street", from: 0, to: 1), .init(name: "B Street", from: 1, to: 2)],
                                 turnaround: 1.0, total: 2, backAtStart: true)
        XCTAssertEqual(s.map(\.text), ["Start on A Street", "Turn around", "Continue onto B Street", "Finish back at the start"])
    }

    func testNothingToListWithoutStretches() {
        XCTAssertTrue(Directions.steps(legs: [], turnaround: nil, total: 3, backAtStart: true).isEmpty)
    }

    func testDistanceAndMileText() {
        XCTAssertEqual(Directions.distanceText(0.354), "0.35 mi")
        XCTAssertEqual(Directions.distanceText(0.05), "260 ft")
        XCTAssertEqual(Directions.distanceText(2), "2.00 mi")
        XCTAssertEqual(Directions.mileText(1.52), "1.52")
    }

    func testTheBundledRouteHasASensibleList() throws {
        let data = try LoopData(file: RouteFile.loadBundled())
        let detail = try XCTUnwrap(data.candidate(rank: 1)?.detail)
        let s = Directions.steps(for: detail)
        XCTAssertEqual(s.first?.kind, .start)
        XCTAssertEqual(s.last?.kind, .finish)
        XCTAssertEqual(s.filter { $0.kind == .turnaround }.count, 1)
        let run = s.compactMap(\.miles).reduce(0, +)
        XCTAssertEqual(run, detail.distanceMi, accuracy: 0.02, "the runs add up to the route")
    }

    // MARK: the server's turns (decision 054)

    private func turn(_ i: Int, _ m: String, _ street: String?, _ mile: Double, _ mi: Double) -> RouteFile.Turn {
        let json = """
        {"index": \(i), "maneuver": "\(m)", "street": \(street.map { "\"\($0)\"" } ?? "null"), "from_mile": \(mile),
         "from_meters": \(Int(mile * 1609.344)), "point": {"lat": 40.74, "lon": -73.98},
         "distance": {"value": \(mi), "unit": "mi", "meters": \(Int(mi * 1609.344)), "status": "measured", "source": "route geometry (GraphHopper)"},
         "status": "measured", "maneuver_source": "GraphHopper turn instructions (foot profile)", "trust": "listed", "source": "OSM way name"}
        """
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return try! d.decode(RouteFile.Turn.self, from: Data(json.utf8))
    }

    func testTurnsReadAsTurnsAndANullStreetHasNoOnto() {
        let s = Directions.steps(turns: [
            turn(0, "start", "East 31st Street", 0, 0.15), turn(1, "left", nil, 0.15, 0.11),
            turn(2, "right", "East 33rd Street", 0.26, 0.15), turn(3, "sharp_right", "East River Esplanade", 0.56, 0.95),
            turn(4, "turnaround", "East River Esplanade", 1.51, 1.14), turn(5, "continue", "East 33rd Street", 2.65, 0.18),
            turn(6, "slight_left", nil, 2.83, 0.05), turn(7, "finish", nil, 3.03, 0)], total: 3.03, backAtStart: true)
        XCTAssertEqual(s.map(\.text), [
            "Start on East 31st Street", "Turn left", "Turn right onto East 33rd Street",
            "Turn sharp right onto East River Esplanade", "Turn around, head back on East River Esplanade",
            "Continue onto East 33rd Street", "Bear left", "Finish back at the start"])
        XCTAssertEqual(s.map(\.kind), [.start, .run, .run, .run, .turnaround, .run, .run, .finish])
        XCTAssertEqual(s[3].miles ?? 0, 0.95, accuracy: 0.001)
        XCTAssertEqual(s[4].miles ?? 0, 1.14, accuracy: 0.001, "the way back runs to the next step")
        XCTAssertNil(s.last?.miles)
        XCTAssertEqual(s.map(\.id), Array(0..<s.count))
    }

    func testAOneWayFinishAndOutOfOrderSteps() {
        let s = Directions.steps(turns: [turn(2, "finish", nil, 2.68, 0), turn(0, "start", "Grand Army Plaza", 0, 0.08),
                                         turn(1, "left", "Central Park Outer Loop", 0.61, 2.07)], total: 2.68, backAtStart: false)
        XCTAssertEqual(s.map(\.text), ["Start on Grand Army Plaza", "Turn left onto Central Park Outer Loop", "Finish"])
    }

    func testSummaryDecodesStepsAndTheirAbsenceMeansTheStretchList() throws {
        // The bundled file predates steps: no key, no steps, and the stretch list still reads.
        let file = try RouteFile.loadBundled()
        let summary = try XCTUnwrap(file.route.features[0].properties.summary)
        XCTAssertNil(summary.steps)
        let data = try LoopData(file: file)
        let detail = try XCTUnwrap(data.candidate(rank: 1)?.detail)
        XCTAssertEqual(Directions.steps(for: detail).first?.kind, .start)
        XCTAssertTrue(Directions.steps(for: detail).contains { $0.text.hasPrefix("Continue onto") || $0.kind == .finish })
    }
}
