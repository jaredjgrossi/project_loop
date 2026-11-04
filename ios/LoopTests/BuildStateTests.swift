import XCTest
@testable import Loop

final class BuildStateTests: XCTestCase {

    private func run(_ script: BuildScript, until t: TimeInterval, touchAt: TimeInterval? = nil) -> BuildState {
        var s = BuildState()
        var touched = false
        for e in script.events where e.at <= t {
            if let ta = touchAt, !touched, ta < e.at { s.touch(); touched = true }
            s.apply(e.event, at: e.at)
        }
        if let ta = touchAt, !touched, ta <= t { s.touch() }
        return s
    }

    func testFirstRouteDrawsAsSoonAsItArrives() {
        let s = run(.standard, until: 0.3)
        XCTAssertEqual(s.shownRank, 2)
        XCTAssertEqual(s.otherRanks, [3])
        XCTAssertFalse(s.cardRevealed)
        XCTAssertEqual(s.drawnFraction(at: 0.3, length: 5000, metresPerSecond: 2500), 0)
        XCTAssertEqual(s.drawnFraction(at: 1.3, length: 5000, metresPerSecond: 2500), 0.5, accuracy: 1e-9)
        XCTAssertEqual(s.drawnFraction(at: 9, length: 5000, metresPerSecond: 2500), 1)
    }

    func testNewLeaderBeforeFlagMorphs() {
        let s = run(.standard, until: 1.5)
        XCTAssertEqual(s.shownRank, 1)
        XCTAssertEqual(s.morph, .init(from: 2, to: 1, start: 1.5))
        XCTAssertEqual(s.morphProgress(at: 1.8, duration: 0.6)!, 0.5, accuracy: 1e-9)
        XCTAssertNil(s.morphProgress(at: 2.1, duration: 0.6))
        XCTAssertNil(s.betterRank)
        XCTAssertEqual(s.drawnFraction(at: 1.5, length: 5000, metresPerSecond: 2500), 0.6, accuracy: 1e-9,
                       "drawing keeps going through the morph; no redraw from scratch")
    }

    func testFlagIsTheSettleMomentAndFinalAddsTheCount() {
        var s = run(.standard, until: 3.0)
        XCTAssertTrue(s.cardRevealed)
        XCTAssertFalse(s.showsCount, "count waits for the final")
        XCTAssertEqual(s.settleAt, 3.0)
        s = run(.standard, until: 6.0)
        XCTAssertTrue(s.showsCount)
        XCTAssertEqual(s.otherRanks, [2, 3])
    }

    func testTouchBeforeFlagSkipsBeatAndNeverSwaps() {
        let s = run(.standard, until: 6.0, touchAt: 1.0)
        XCTAssertEqual(s.shownRank, 2, "never swap under the runner")
        XCTAssertNil(s.morph)
        XCTAssertNil(s.settleAt, "no pulse, no haptic")
        XCTAssertEqual(s.betterRank, 1, "quiet chip instead")
        XCTAssertTrue(s.cardRevealed)
    }

    func testTappingTheChipSwitches() {
        var s = run(.standard, until: 6.0, touchAt: 1.0)
        s.acceptBetterRoute(at: 7)
        XCTAssertEqual(s.shownRank, 1)
        XCTAssertEqual(s.morph, .init(from: 2, to: 1, start: 7))
        XCTAssertNil(s.betterRank)
    }

    func testLeaderChangeAfterFlagShowsChipEvenUntouched() {
        let s = run(.lateBetterRoute, until: 4.5)
        XCTAssertEqual(s.settleAt, 3.0)
        XCTAssertEqual(s.shownRank, 2)
        XCTAssertEqual(s.betterRank, 1)
    }

    func testOutlinesFadeAfterTheFlag() {
        let before = run(.standard, until: 2.0)
        XCTAssertEqual(before.outlineOpacity(at: 2.0, peak: 0.3, fade: 0.5), 0.3)
        let after = run(.standard, until: 3.0)
        XCTAssertEqual(after.outlineOpacity(at: 3.25, peak: 0.3, fade: 0.5), 0.15, accuracy: 1e-9)
        XCTAssertEqual(after.outlineOpacity(at: 3.6, peak: 0.3, fade: 0.5), 0)
        XCTAssertEqual(BuildState.settled(top3: [1, 2, 3]).outlineOpacity(at: 0, peak: 0.3, fade: 0.5), 0)
    }

    func testSettledLaunchState() {
        let s = BuildState.settled(top3: [1, 2, 3])
        XCTAssertEqual(s.shownRank, 1)
        XCTAssertTrue(s.cardRevealed && s.showsCount)
        XCTAssertEqual(s.drawnFraction(at: 0, length: 5000, metresPerSecond: 2500), 1)
        XCTAssertNil(s.settleAt)
    }
}
