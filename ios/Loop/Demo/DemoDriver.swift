#if DEBUG
import QuartzCore
import SwiftUI
import UIKit

/// Plays the demo video's sequence (the brief's segments A to F, decision 060) on the app itself: it types, taps,
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
    static let requestD = "3 miles to Union Square at 7"
    /// The opening drift: Kips Bay's street grid at neighborhood zoom, no park in frame, ending near the start.
    static let driftFrom = GeoPoint(lon: -73.9826, lat: 40.7449)
    static let driftTo = GeoPoint(lon: -73.9815, lat: 40.7443)
    static let driftZoom = 15.35

    func start(model: MainModel, from segment: Character) {
        self.model = model
        task?.cancel()
        task = Task { @MainActor [weak self] in await self?.run(from: segment) }
    }

    func stop() { task?.cancel() }

    private func run(from segment: Character) async {
        let order: [Character] = ["A", "B", "C", "D", "E", "F"]
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
            default: await segmentF()
            }
            guard !Task.isCancelled else { return }
            log("segment \(s) done")
        }
        log("done")
    }

    // MARK: Segments

    /// A: 2 s still, 3 s of drift over the grid, the bar rises and types, send, the build in real time, 3 s on the card.
    private func segmentA() async {
        guard let model else { return }
        LoopClock.pinned = DemoMode.morning
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
        model.logoShown = false
        model.stage = .landing
        model.landingShown = false
        await until("the map") { model.mapReady }
        model.requestCamera(.at(Self.driftFrom, zoom: Self.driftZoom), animated: false)
        await hold(2.0)
        model.requestCamera(.at(Self.driftTo, zoom: Self.driftZoom - 0.1), animated: true, duration: 3.2)
        await hold(3.0)
        model.locationPulsing = !fast
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

    /// D: home, tap the field, type the Union Square request, send, the build, 6 s on the finished route.
    private func segmentD() async {
        guard let model else { return }
        await tap("wordmark") { model.goHome() }
        await until("the landing") { model.landingShown && model.landingAnchor == nil }
        await hold(0.8)
        await tap("field") { model.focusFieldRequest += 1 }
        await until("typing", timeout: 3) { model.stage == .typing }
        await hold(0.4)
        await type(Self.requestD) { model.fieldText.append($0) }
        await hold(0.7)
        if let f = DemoTargets.frames["field"] { dot(CGPoint(x: f.maxX - 28, y: f.midY)) }
        await sleep(fast ? 0 : 0.14)
        // The field's own send, as the keyboard's Go key does it: a send from the script's task left the header stale.
        model.demoSubmitRequest += 1
        await awaitBuild()
        await hold(6.0)
    }

    /// E: later the same morning. Home with the return prompt for segment A's route and the saved tile; "I ran it",
    /// "Good"; the run at the top of History; 1.5 s on the list.
    private func segmentE() async {
        guard let model else { return }
        LoopClock.pinned = DemoMode.laterMorning
        model.demoClockVersion += 1
        await WeatherStore.shared.refresh(force: true)
        if let a = routeA { model.runs.demoStageViewed(a, at: DemoMode.date(hour: 7, minute: 9)) }
        model.goHome()
        await until("the landing") { model.landingShown && model.landingAnchor == nil }
        if model.stage == .typing { model.cancelTyping() }   // the field kept its focus from D
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

    /// F: the route-L button; the hero map (draw-in), the numbers, the 8-week chart, back to the hero for 5 s.
    private func segmentF() async {
        guard let model else { return }
        await tap("you") { model.youShown = true }
        await hold(3.3)
        scroll("stats"); await hold(2.5)
        scroll("weeks"); await hold(2.5)
        scroll("hero"); await hold(5.0)
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
