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
