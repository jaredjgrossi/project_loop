import XCTest
@testable import Loop

/// The temperature under the wordmark: refresh timing and never showing a stale number.
@MainActor
final class WeatherTests: XCTestCase {
    private let t0 = Date(timeIntervalSince1970: 1_800_000_000)

    private func reading(_ temp: String, at: Date) -> WeatherStore.Reading {
        .init(symbol: "cloud", temperature: temp, at: at)
    }

    func testNoSourceShowsNothing() async {
        let store = WeatherStore()
        await store.refresh(now: t0)
        XCTAssertNil(store.visible(at: t0))
    }

    func testFreshReadingShowsAndOldOneHides() async {
        let store = WeatherStore(provider: { [t0] in .init(symbol: "sun.max", temperature: "51°", at: t0) })
        await store.refresh(now: t0)
        XCTAssertEqual(store.visible(at: t0.addingTimeInterval(29 * 60))?.temperature, "51°")
        XCTAssertNil(store.visible(at: t0.addingTimeInterval(31 * 60)), "older than 30 minutes: hidden")
    }

    func testFailedRefreshKeepsTheReadingOnlyWhileItIsFresh() async {
        struct Down: Error {}
        var fail = false
        let t0 = self.t0
        let store = WeatherStore(provider: { if fail { throw Down() }; return .init(symbol: "sun.max", temperature: "51°", at: t0) })
        await store.refresh(now: t0)
        fail = true
        await store.refresh(now: t0.addingTimeInterval(15 * 60))
        XCTAssertEqual(store.visible(at: t0.addingTimeInterval(16 * 60))?.temperature, "51°", "still under 30 minutes")
        await store.refresh(now: t0.addingTimeInterval(31 * 60))
        XCTAssertNil(store.visible(at: t0.addingTimeInterval(31 * 60)), "30 minutes old and the refresh failed: hidden")
    }

    func testLaunchAndForegroundTogetherAreOneAsk() async {
        var asks = 0
        let t0 = self.t0
        let store = WeatherStore(provider: { asks += 1; return .init(symbol: "cloud", temperature: "50°", at: t0) })
        await store.refresh(now: t0)
        await store.refresh(now: t0.addingTimeInterval(5))
        XCTAssertEqual(asks, 1)
        await store.refresh(now: t0.addingTimeInterval(60))
        XCTAssertEqual(asks, 2, "a return to the foreground a minute later asks again")
        await store.refresh(now: t0.addingTimeInterval(61), force: true)
        XCTAssertEqual(asks, 3)
    }

    func testNewestReadingReplacesTheOld() async {
        var temp = "50°"
        let store = WeatherStore(provider: { .init(symbol: "cloud", temperature: temp, at: Date()) })
        await store.refresh(now: t0)
        temp = "47°"
        await store.refresh(now: t0.addingTimeInterval(900))
        XCTAssertEqual(store.reading?.temperature, "47°")
    }
}

/// The server's `GET /v1/weather/nyc` body (decision 051).
final class WeatherResponseTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-11-13T19:00:00Z")!

    private func body(_ extra: String = "", temp: String = "41", at: String = "2026-11-13T18:51:00Z", v: Int = 1, condition: String = "cloudy") -> Data {
        Data("""
        {"v":\(v),"temp_f":\(temp),"condition":"\(condition)","description":"Cloudy","observed_at":"\(at)","station":"KNYC","source":"National Weather Service, KNYC Central Park","status":"measured"\(extra)}
        """.utf8)
    }

    func testReadsTheServersBody() throws {
        let r = try XCTUnwrap(LoopAPI.reading(from: body(), now: now))
        XCTAssertEqual(r.temperature, "41°")
        XCTAssertEqual(r.symbol, "cloud")
        XCTAssertEqual(r.at, ISO8601DateFormatter().date(from: "2026-11-13T18:51:00Z"), "the station's time, not the request's")
        XCTAssertEqual(r.source, "National Weather Service, KNYC Central Park")
    }

    func testRefusesWhatItCannotTrust() {
        XCTAssertNil(LoopAPI.reading(from: body(v: 2), now: now), "unknown version")
        XCTAssertNil(LoopAPI.reading(from: body(at: "yesterday"), now: now), "no usable time")
        XCTAssertNil(LoopAPI.reading(from: body(at: "2026-11-13T19:30:00Z"), now: now), "measured in the future would never go stale")
        XCTAssertNil(LoopAPI.reading(from: Data("{}".utf8), now: now))
        XCTAssertNil(LoopAPI.reading(from: Data(#"{"detail":"weather_unavailable"}"#.utf8), now: now))
    }

    func testEveryConditionHasAGlyph() {
        let noon = ISO8601DateFormatter().date(from: "2026-11-13T17:00:00Z")!   // noon in New York
        let night = ISO8601DateFormatter().date(from: "2026-11-14T03:00:00Z")!  // 10 pm
        for c in ["clear", "partly_cloudy", "cloudy", "fog", "rain", "snow", "thunderstorm", "other"] {
            XCTAssertFalse(LoopAPI.weatherSymbol(c, at: noon).isEmpty, c)
        }
        XCTAssertEqual(LoopAPI.weatherSymbol("clear", at: noon), "sun.max")
        XCTAssertEqual(LoopAPI.weatherSymbol("clear", at: night), "moon.stars")
        XCTAssertEqual(LoopAPI.weatherSymbol("partly_cloudy", at: night), "cloud.moon")
    }

    func testWholeDegreesAreRounded() throws {
        XCTAssertEqual(LoopAPI.reading(from: body(temp: "41.6"), now: now)?.temperature, "42°")
        XCTAssertEqual(LoopAPI.reading(from: body(temp: "-3"), now: now)?.temperature, "-3°")
    }
}
