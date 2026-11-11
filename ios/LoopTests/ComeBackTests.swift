import XCTest
@testable import Loop

/// Come back (2026-11-10): saves, runs and ratings, the return prompt, stats, naming, the request.
@MainActor
final class ComeBackTests: XCTestCase {
    private func route(_ id: String, mi: Double = 3, stretches: [String] = ["East River Esplanade"], start: String? = "07:00") -> RouteIdentity {
        RouteIdentity(routeId: id, archive: id, name: "Route \(id)", request: "3 miles", distanceMi: mi,
                      shape: [[-73.97, 40.74], [-73.96, 40.75]], stretches: stretches, startTime: start)
    }

    func testSaveRenameRemove() {
        let store = RunStore()
        let r = route("r_a.1")
        store.save(r)
        XCTAssertTrue(store.isSaved(r))
        store.save(r)
        XCTAssertEqual(store.saved.count, 1, "saving twice keeps one")
        store.rename(store.saved[0].id, to: "  the Stuy loop ")
        XCTAssertEqual(store.saved[0].name, "the Stuy loop")
        store.remove(store.saved[0].id)
        XCTAssertFalse(store.isSaved(r))
    }

    func testRunMarkedThenRatedLater() {
        let store = RunStore()
        let log = store.markRun(route("r_a.1"))
        XCTAssertNil(store.runs.first?.rating, "marking without a rating is allowed")
        store.rate(log.id, RunRating(verdict: .notForMe, reasons: ["crowded", "other"], note: "Ferry crowd"))
        XCTAssertEqual(store.runs.first?.rating?.verdict, .notForMe)
        XCTAssertEqual(store.runs.first?.rating?.reasons, ["crowded", "other"])
    }

    func testReturnPromptOncePerRouteWithin24Hours() {
        let store = RunStore()
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        store.noteViewed(route("r_a.1"), at: now.addingTimeInterval(-3 * 3600))
        XCTAssertEqual(store.returnPrompt(openedAt: now)?.route.routeId, "r_a.1")
        store.markPrompted(store.returnPrompt(openedAt: now)!)
        XCTAssertNil(store.returnPrompt(openedAt: now), "asked once")

        store.noteViewed(route("r_b.1"), at: now.addingTimeInterval(-25 * 3600))
        XCTAssertNil(store.returnPrompt(openedAt: now), "gone after 24 h")

        store.noteViewed(route("r_c.1"), at: now.addingTimeInterval(-3600))
        store.markRun(route("r_c.1"), at: now.addingTimeInterval(-60))
        XCTAssertNil(store.returnPrompt(openedAt: now), "not for a route already marked as run")
    }

    func testPromptWording() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "America/New_York")!
        let now = cal.date(from: DateComponents(year: 2026, month: 11, day: 10, hour: 18))!
        var r = route("r_a.1")
        r.name = "East River out-and-back"
        let morning = ViewedRoute(route: r, at: cal.date(from: DateComponents(year: 2026, month: 11, day: 10, hour: 7))!)
        XCTAssertEqual(MainModel.promptText(morning, now: now, calendar: cal), "Did you run the East River out-and-back route this morning?")
        let yesterday = ViewedRoute(route: r, at: cal.date(from: DateComponents(year: 2026, month: 11, day: 9, hour: 19))!)
        XCTAssertEqual(MainModel.promptText(yesterday, now: now, calendar: cal), "Did you run the East River out-and-back route yesterday?")
    }

    func testStats() {
        var cal = Calendar(identifier: .gregorian)
        cal.firstWeekday = 2
        cal.timeZone = TimeZone(identifier: "America/New_York")!
        let now = cal.date(from: DateComponents(year: 2026, month: 11, day: 12, hour: 9))!   // a Thursday
        func run(_ daysAgo: Int, _ mi: Double, _ start: String?, _ stretches: [String]) -> RunLog {
            RunLog(id: "x\(daysAgo)", route: route("r_\(daysAgo)", mi: mi, stretches: stretches, start: start),
                   ranAt: cal.date(byAdding: .day, value: -daysAgo, to: now)!, rating: nil)
        }
        let s = RunStats(runs: [run(0, 3, "07:00", ["Esplanade"]), run(2, 6, "07:10", ["Esplanade", "E 31st St"]),
                                run(8, 3, "06:50", ["E 31st St"]), run(15, 4, nil, ["Esplanade"])],
                         now: now, calendar: cal)
        XCTAssertEqual(s.count, 4)
        XCTAssertEqual(s.miles, 16, accuracy: 1e-9)
        XCTAssertEqual(s.average ?? 0, 4, accuracy: 1e-9)
        XCTAssertEqual(s.longest, 6)
        XCTAssertEqual(s.weekStreak, 3, "this week, last week and the week before")
        XCTAssertEqual(s.lastEightWeeks.last ?? 0, 9, accuracy: 1e-9, "this week")
        XCTAssertEqual(s.lastEightWeeks.count, 8)
        XCTAssertEqual(s.usualStart, "7:00 am", "the median planned start")
        XCTAssertEqual(s.mostRun?.name, "Esplanade")
        XCTAssertEqual(s.mostRun?.count, 3)
        XCTAssertNil(RunStats(runs: []).average, "hidden until the first run")
    }

    func testRouteNaming() throws {
        let detail = try XCTUnwrap(LoopData(file: RouteFile.loadBundled()).candidate(rank: 1)?.detail)
        XCTAssertEqual(RouteNaming.name(detail), "East River out-and-back")
        XCTAssertEqual(RouteNaming.place("East 31st Street"), "E 31st St")
        XCTAssertEqual(RouteNaming.kindWord("lollipop"), "loop")
    }

    func testRequestCarriesProfileFavoritesShapeAndRunAgain() throws {
        let store = RunStore()
        var r = route("r_a.1")
        r.name = "East River out-and-back"
        store.save(r)
        store.rename(store.saved[0].id, to: "the river one")
        store.markRun(r)
        store.markRun(r)
        store.profile = RunnerProfile(usualDistanceMi: 4.5, usualTime: "06:30", usualShape: "one_way",
                                      home: .init(label: "Home", lat: 40.7, lon: -73.9))
        let recents = store.recentRoutesPayload
        XCTAssertEqual(recents.count, 1, "one route, saved and run")
        XCTAssertEqual(recents[0].name, "the river one", "the runner's own name for a favorite")
        XCTAssertTrue(recents[0].saved)
        XCTAssertEqual(recents[0].ranCount, 2)

        var body = RunRequest(text: nil, answer: nil, constraints: nil, client: RunRequest.client(location: nil),
                              profile: RunRequest.Profile(store.profile), recentRoutes: recents)
        body.routeId = "r_a.1"
        body.mode = "exact"
        let top = try XCTUnwrap(JSONSerialization.jsonObject(with: LoopAPI.encoder.encode(body)) as? [String: Any])
        XCTAssertEqual(top["mode"] as? String, "exact")
        XCTAssertEqual(top["route_id"] as? String, "r_a.1")
        XCTAssertNil(top["text"])
        let profile = try XCTUnwrap(top["profile"] as? [String: Any])
        XCTAssertEqual(profile["usual_shape"] as? String, "one_way")
        XCTAssertEqual(profile["usual_distance_mi"] as? Double, 4.5)
        XCTAssertEqual((profile["saved_places"] as? [[String: Any]])?.first?["id"] as? String, "home")
        let recent = try XCTUnwrap((top["recent_routes"] as? [[String: Any]])?.first)
        XCTAssertEqual(recent["saved"] as? Bool, true)
        XCTAssertEqual(recent["ran_count"] as? Int, 2)

        var typed = RunRequest(text: "4 miles by the river", answer: nil, constraints: nil,
                               client: RunRequest.client(location: nil), profile: .init(), recentRoutes: [])
        typed.shape = "out_and_back"
        let t = try XCTUnwrap(JSONSerialization.jsonObject(with: LoopAPI.encoder.encode(typed)) as? [String: Any])
        XCTAssertEqual(t["shape"] as? String, "out_and_back", "the picked route type beats the words")
        XCTAssertNil(t["mode"])
    }

    func testFixtureArchiveLoads() throws {
        let file = try XCTUnwrap(RouteArchive.load(RouteArchive.fixture, start: "the start"))
        XCTAssertNoThrow(try LoopData(file: file))
    }
}
