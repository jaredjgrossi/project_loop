#if DEBUG
import QuartzCore
import SwiftUI
import UIKit

/// Plays the demo video's sequence (segments A to G, decision 060; the brief's A to F with two new range beats) on the app itself: it types, taps,
/// scrolls and waits, with each wait tied to the thing it waits for (the parse, the card, the final, the sheet, the
/// landing) rather than a fixed sleep, so a slow build can't break the timing. Every route and number on screen comes
/// from the live server; the script only drives the app the way a finger would and marks each tap with a dot.
///
/// Starting from a later segment plays the earlier ones first with the holds skipped (the builds still take their
/// real time), then holds two seconds still so the recording has a clean start.
@MainActor
final class DemoDriver {
    static let shared = DemoDriver()

    private weak var model: MainModel?
    private var task: Task<Void, Never>?
    /// Staging an earlier segment: no holds, instant typing, no dots.
    private var fast = false
    /// The route segment A built, for segment E's return prompt.
    private var routeA: RouteIdentity?

    static let requestA = "3 miles by the water at 7"
    static let requestD = "a lap of the Reservoir at 7"
    static let requestE = "3 miles around Prospect Park at 7"
    /// The opening drift's zoom: the street grid at neighborhood zoom; its points come from the start (DemoMode.Start).
    static let driftZoom = 15.35

    func start(model: MainModel, from segment: Character) {
        self.model = model
        task?.cancel()
        task = Task { @MainActor [weak self] in await self?.run(from: segment) }
    }

    func stop() { task?.cancel() }

    private func run(from segment: Character) async {
        let order: [Character] = ["A", "B", "C", "D", "E", "F", "G"]
        let startAt = order.firstIndex(of: segment) ?? 0
        LoopClock.pinned = DemoMode.morning
        log("starting at \(segment)")
        for (i, s) in order.enumerated() {
            fast = i < startAt
            if i == startAt, i > 0 { await sleep(2.0) }   // still, so the edit has a clean start
            switch s {
            case "A": await segmentA()
            case "B": await segmentB()
            case "C": await segmentC()
            case "D": await segmentD()
            case "E": await segmentE()
            case "F": await segmentF()
            default: await segmentG()
            }
            guard !Task.isCancelled else { return }
            log("segment \(s) done")
        }
        log("done")
    }

    // MARK: Segments

    /// A: the real open (the mark fades into the map), 3 s of drift over the grid from the library, the bar rises and
    /// types, send, the build in real time, 3 s on the card.
    private func segmentA() async {
        guard let model else { return }
        LoopClock.pinned = DemoMode.morning
        let home = DemoMode.start("kips-bay-library")
        model.locationProvider.simulate(home.point)
        // A clean map: no bundled route, no card, no sentence (what runLaunch resets, without its logo and camera).
        model.flow?.cancel()
        model.playbackCancel()
        model.build = BuildState()
        model.frameVersion += 1
        model.drawnFraction = 0
        model.requestText = nil
        model.readOut = nil
        model.sheetShown = false
        model.sheet.settle(open: false, animated: false)
        model.fieldExample = ""
        model.clearSelection()
        model.landing.slide(to: 0, animated: false)   // as runLaunch leaves it before the sheet rises
        model.logoShown = true
        model.stage = .logo
        model.landingShown = false
        // The real open: the route-L mark holds until the map has drawn, then fades into it (runLaunch's timings).
        await until("the map") { model.mapReady }
        model.requestCamera(.at(home.driftFrom, zoom: Self.driftZoom), animated: false)
        await hold(MainModel.Timing.logoFade)
        withAnimation(fast ? nil : .timingCurve(0.2, 0, 0, 1, duration: 0.6)) { model.logoShown = false }
        await hold(0.6)
        model.locationPulsing = !fast
        model.stage = .landing
        // Then the drift over the grid until the bar rises.
        model.requestCamera(.at(home.driftTo, zoom: Self.driftZoom - 0.1), animated: true, duration: 3.2)
        await hold(3.0)
        model.landingShown = true
        model.landingAnchor = model.landing.openHeight
        model.landing.settle(rest: .open, animated: !fast) { [weak model] in model?.landingAnchor = nil }
        await hold(1.0)
        model.fieldExample = ""
        await type(Self.requestA) { model.fieldExample.append($0) }
        await hold(0.7)
        model.demoTyping = true
        model.stage = .typing
        await hold(0.5)
        model.send(Self.requestA, reduceMotion: false)
        await awaitBuild()
        routeA = model.currentRoute
        await hold(3.0)
    }

    /// B (the brief's fallback, Look Around out): open the sheet, tap the route at a mile on the esplanade, a second
    /// mile so the strip's cursor moves, routes #2 and #3, then the bookmark.
    private func segmentB() async {
        guard let model else { return }
        await tap("grabber") { model.setSheet(open: true, animated: true) }
        await hold(0.9)
        guard let d = model.shownDetail else { return }
        let water = d.drawn.filter { $0.kind == .waterfront }.max { ($0.toM - $0.fromM) < ($1.toM - $1.fromM) }
        let first = water.map { $0.fromM + ($0.toM - $0.fromM) * 0.35 } ?? d.line.length * 0.35
        let second = water.map { min($0.toM - 30, first + 600) } ?? d.line.length * 0.55
        await tap(at: model.screenPoint(d.line.point(at: first))) { model.selectPoint(alongM: first) }
        await hold(1.5)
        await tap(at: model.screenPoint(d.line.point(at: second))) { model.selectPoint(alongM: second) }
        await hold(1.5)
        let lead = model.shownRank
        for rank in model.otherRanks.sorted() {
            guard let other = model.data.candidate(rank: rank)?.line else { continue }
            let p = Self.farthest(on: other, from: d.line)
            await tap(at: model.screenPoint(p)) { model.showRoute(rank: rank) }
            await hold(1.6)
        }
        if let lead { model.showRoute(rank: lead) }
        await hold(0.9)
        await tap("bookmark") { model.toggleSave() }
        await hold(1.5)
    }

    /// C: tap the sentence, tap the distance, two taps on + (3 → 4), Done; the route rebuilds; 3 s on the new route
    /// with the sheet open on its crowd line.
    private func segmentC() async {
        guard let model else { return }
        model.setSheet(open: false, animated: true)
        await hold(0.5)
        await tap("sentence") { model.enterEditMode() }
        await hold(1.0)
        let f = DemoTargets.frames["sentence"]
        await tap(at: f.map { CGPoint(x: $0.minX + 12, y: $0.minY + 20) }) { model.openEditor(.understood("distance")) }
        await hold(1.0)
        await tap("editorPlus") { model.demoEditorPlus += 1 }
        await hold(0.5)
        await tap("editorPlus") { model.demoEditorPlus += 1 }
        await hold(0.7)
        await tap("editorDone") { model.demoEditorDone += 1 }
        guard await until("the rebuild to start", timeout: 10, { !model.build.final }) else { return }
        await awaitBuild()
        await hold(0.6)
        model.setSheet(open: true, animated: true)
        await hold(3.0)
    }

    /// D: home, the location moves to 5th Ave & E 86th St, the Reservoir lap is typed and sent, the build, 6 s held.
    private func segmentD() async {
        await goHomeAt("fifth-ave-86th")
        await typeAndSend(Self.requestD)
        await awaitBuild()
        await hold(6.0)
    }

    /// E: home, the location moves to Grand Army Plaza, the Prospect Park request is typed and sent; the engine asks
    /// (the lap and the way there need more than 3 mi) and the script taps the first answer; the build, 6 s held.
    private func segmentE() async {
        guard let model else { return }
        await goHomeAt("grand-army-plaza")
        await typeAndSend(Self.requestE)
        // The parse lands first and the engine's question a moment later: wait for the card itself, or for a route
        // if none comes.
        await until("the question card", timeout: 40) { model.pendingQuestion != nil || model.cardRevealed || model.liveNotice != nil }
        if let q = model.pendingQuestion, let first = q.options.first {
            await hold(1.5)   // the card is read
            await tap("questionOption1") { model.answerQuestion(optionId: first.id, text: nil) }
        } else {
            log("no question came for the Prospect Park lap")
        }
        await awaitBuild()
        await hold(6.0)
    }

    /// F: later the same morning, back at the library. Home with the return prompt for segment A's route and the saved
    /// tile; "I ran it", "Good"; the run at the top of History; 1.5 s on the list.
    private func segmentF() async {
        guard let model else { return }
        LoopClock.pinned = DemoMode.laterMorning
        model.demoClockVersion += 1
        await WeatherStore.shared.refresh(force: true)
        if let a = routeA { model.runs.demoStageViewed(a, at: DemoMode.date(hour: 7, minute: 9)) }
        model.locationProvider.simulate(DemoMode.start("kips-bay-library").point)
        model.goHome()
        await until("the landing") { model.landingShown && model.landingAnchor == nil }
        if model.stage == .typing { model.cancelTyping() }   // the field kept its focus from the typed request
        model.demoBlurRequest += 1
        await sleep(0.3)
        model.checkReturnPrompt(openedAt: LoopClock.now())
        model.landing.refreshRest()
        model.landing.settle(rest: .open, animated: !fast)
        await hold(2.0)
        await tap("promptRanIt") { model.ranItFromPrompt() }
        await until("the rating") { model.rating != nil }
        await hold(1.2)
        await tap("rateGood") { model.rateGood() }
        await hold(1.2)
        await tap("you") { model.youShown = true }
        await hold(1.2)
        await tap("historyLink") { model.demoHistoryRequest += 1 }
        await hold(1.5)
        model.youShown = false
        await hold(0.8)
    }

    /// G: the route-L button; the hero map (draw-in), the numbers, the 8-week chart, back to the hero for 5 s.
    private func segmentG() async {
        guard let model else { return }
        await tap("you") { model.youShown = true }
        await hold(3.3)
        scroll("stats"); await hold(2.5)
        scroll("weeks"); await hold(2.5)
        scroll("hero"); await hold(5.0)
    }

    // MARK: Segment pieces

    /// Home, then the simulated location moves to a named public start and the map eases there.
    private func goHomeAt(_ key: String) async {
        guard let model else { return }
        await tap("wordmark") { model.goHome() }
        await until("the landing") { model.landingShown && model.landingAnchor == nil }
        if model.stage == .typing { model.cancelTyping() }
        model.demoBlurRequest += 1
        let start = DemoMode.start(key)
        model.locationProvider.simulate(start.point)
        model.requestCamera(.above(start.point, bottom: model.landing.openHeight, zoom: 14.2), animated: !fast, duration: 0.9)
        await hold(1.3)
    }

    /// Tap the field, type the request a character at a time, send it the way the keyboard's Go key does.
    private func typeAndSend(_ text: String) async {
        guard let model else { return }
        await tap("field") { model.focusFieldRequest += 1 }
        await until("typing", timeout: 3) { model.stage == .typing }
        await hold(0.4)
        await type(text) { model.fieldText.append($0) }
        await hold(0.7)
        if let f = DemoTargets.frames["field"] { dot(CGPoint(x: f.maxX - 28, y: f.midY)) }
        await sleep(fast ? 0 : 0.14)
        model.demoSubmitRequest += 1
    }

    // MARK: Helpers

    /// Parsed, the card, then the final: the engine's own pace.
    private func awaitBuild() async {
        guard let model else { return }
        await until("the parse") { model.readOut != nil || model.pendingQuestion != nil || model.liveNotice != nil }
        if model.pendingQuestion != nil || model.liveNotice != nil { log("the build asked a question or failed"); return }
        await until("the card") { model.cardRevealed }
        await until("the final") { model.build.final }
    }

    private func scroll(_ target: String) {
        model?.demoScrollTarget = target
        model?.demoScrollRequest += 1
    }

    private func hold(_ seconds: Double) async {
        guard !fast else { return }
        try? await Task.sleep(for: .seconds(seconds))
    }

    private func sleep(_ seconds: Double) async {
        guard seconds > 0 else { return }
        try? await Task.sleep(for: .seconds(seconds))
    }

    @discardableResult
    private func until(_ what: String, timeout: Double = 150, _ condition: @escaping @MainActor () -> Bool) async -> Bool {
        let t0 = CACurrentMediaTime()
        while !condition() {
            if Task.isCancelled { return false }
            if CACurrentMediaTime() - t0 > timeout { log("timed out waiting for \(what)"); return false }
            try? await Task.sleep(for: .seconds(0.05))
        }
        return true
    }

    private func dot(_ point: CGPoint?) {
        guard !fast, let point else { return }
        TapDots.shared.tap(at: point)
    }

    /// Waits (up to 3 s) for the view to be on screen, so a tap never lands before the thing it taps exists, even
    /// while staging with the holds skipped.
    private func tap(_ target: String, then action: () -> Void) async {
        await until("a frame for \(target)", timeout: 3) { DemoTargets.center(target) != nil }
        dot(DemoTargets.center(target))
        await sleep(fast ? 0.05 : 0.14)
        action()
    }

    private func tap(at point: CGPoint?, then action: () -> Void) async {
        dot(point)
        await sleep(fast ? 0 : 0.14)
        action()
    }

    /// Characters arrive one at a time at a natural pace: a little slower after a space, never even.
    private func type(_ text: String, each: (Character) -> Void) async {
        for ch in text {
            each(ch)
            guard !fast else { continue }
            try? await Task.sleep(for: .seconds(ch == " " ? 0.17 : Double.random(in: 0.055...0.11)))
        }
    }

    /// The point of `other` farthest from `line`: where a tap picks the other route, not this one.
    private static func farthest(on other: Polyline, from line: Polyline) -> GeoPoint {
        let ref = stride(from: 0, to: line.points.count, by: 4).map { line.points[$0] }
        var best = other.points[other.points.count / 2], bestD = -1.0
        for p in stride(from: 0, to: other.points.count, by: 3).map({ other.points[$0] }) {
            let d = ref.map { $0.distance(to: p) }.min() ?? 0
            if d > bestD { best = p; bestD = d }
        }
        return best
    }

    private func log(_ s: String) { NSLog("Loop demo: %@", s) }
}
#endif
