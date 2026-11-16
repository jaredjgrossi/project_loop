import Foundation
import QuartzCore
import SwiftUI
import UIKit

/// Come back (UI chat, 2026-11-10): Save, "I ran it" and the rating, the return prompt, History and
/// "Run again". Everything lives on the phone (RunStore, RouteArchive); "I ran it" and ratings also go
/// to the server's feedback endpoint (decision 043).
extension MainModel {
    /// The shown route as Save and History keep it: Loop's name from its longest stretch, the request,
    /// the distance, a thumbnail shape, the stretches and the planned start.
    func identityOfShown(archive: String?, routeId: String?) -> RouteIdentity? {
        guard let c = shown else { return nil }
        let start = data.request.startHourText
        return RouteIdentity(routeId: routeId, archive: archive,
                             name: c.detail.map(RouteNaming.name) ?? RunStore.sentence(requestText ?? ""),
                             request: RunStore.sentence(requestText ?? data.request.text),
                             distanceMi: c.distanceMi, shape: RunStore.shape(of: c.line),
                             stretches: Array(Set(c.detail?.stretches.map(\.name) ?? [])).sorted(),
                             startTime: RunStats.minutes(start).map { String(format: "%02d:%02d", $0 / 60, $0 % 60) })
    }

    var isCurrentSaved: Bool { currentRoute.map(runs.isSaved) ?? false }

    /// The bookmark: saves (light haptic) or unsaves the route on the card.
    func toggleSave() {
        guard let r = currentRoute else { return }
        touch()
        if runs.isSaved(r) { runs.unsave(r) } else { runs.save(r); Haptics.saved() }
    }

    /// "Share route": the route as a GPX file for the share sheet (nil if there is no route or the
    /// file can't be written).
    func gpxFileOfShown() -> URL? {
        guard let c = shown else { return nil }
        touch()
        let name = currentRoute?.name ?? identityOfShown(archive: nil, routeId: nil)?.name ?? "Loop route"
        return try? GPX.write(GPX.make(name: name, candidate: c), name: name)
    }

    /// A share finished (the runner picked a place): counts as viewing it, for the return prompt.
    func sharedRoute() {
        if let r = currentRoute { runs.noteViewed(r) }
    }

    // MARK: I ran it and the rating

    /// "I ran it": marks the run at once (rating can come later) and turns the sheet into "How was it?".
    func ranIt() {
        guard let r = currentRoute else { return }
        touch()
        let log = runs.markRun(r)
        sendFeedback(log, rating: nil)
        clearSelection()
        // A plain change (the sheet animates it): set inside withAnimation, outside a tap, the
        // sheet could re-render mid-change, read the old value and never show the rating.
        rating = RatingState(runId: log.id, route: r)
    }

    func rateGood() {
        guard let r = rating else { return }
        let value = RunRating(verdict: .good)
        runs.rate(r.runId, value)
        if let log = runs.runs.first(where: { $0.id == r.runId }) { sendFeedback(log, rating: value) }
        Haptics.success()
        closeRating()
    }

    func chooseNotForMe() {
        withAnimation(UIAccessibility.isReduceMotionEnabled ? nil : Motion.crossfade) { rating?.notForMe = true }
    }

    func toggleReason(_ key: String) {
        guard rating != nil else { return }
        if rating!.reasons.contains(key) { rating!.reasons.remove(key) } else { rating!.reasons.insert(key) }
    }

    /// Done after "Not for me": the reasons (in pill order) and the note, if any.
    func finishNotForMe() {
        guard let r = rating else { return }
        let order = RunRating.reasonPills.map(\.key)
        let note = r.note.trimmingCharacters(in: .whitespacesAndNewlines)
        let value = RunRating(verdict: .notForMe, reasons: order.filter(r.reasons.contains),
                              note: r.reasons.contains("other") && !note.isEmpty ? note : nil)
        runs.rate(r.runId, value)
        if let log = runs.runs.first(where: { $0.id == r.runId }) { sendFeedback(log, rating: value) }
        closeRating()
    }

    /// "Not now", or after rating: the card comes back (the run stays marked).
    func closeRating() {
        withAnimation(UIAccessibility.isReduceMotionEnabled ? nil : Motion.crossfade) { rating = nil }
        sheet.settle(rest: .collapsed, animated: !UIAccessibility.isReduceMotionEnabled)
    }

    private func sendFeedback(_ log: RunLog, rating: RunRating?) {
        guard let id = log.route.routeId, let api = LoopAPI.live else { return }
        api.feedback(routeId: id, ranAt: log.ranAt, rating: rating)
    }

    // MARK: The return prompt

    /// At launch: one card at the top of the home sheet for a route viewed before this open.
    func checkReturnPrompt(openedAt: Date) {
        guard let v = runs.returnPrompt(openedAt: openedAt), v.route.archive.map(RouteArchive.has) == true else { return }
        returnPrompt = v
        runs.markPrompted(v)
    }

    /// "Did you run the East River out-and-back route this morning?"
    static func promptText(_ v: ViewedRoute, now: Date = LoopClock.now(), calendar: Calendar = .current) -> String {
        let when: String
        if calendar.isDate(v.at, inSameDayAs: now) {
            let h = calendar.component(.hour, from: v.at)
            when = h < 12 ? "this morning" : h < 17 ? "this afternoon" : "this evening"
        } else {
            when = "yesterday"
        }
        return "Did you run the \(v.route.name) route \(when)?"
    }

    func dismissReturnPrompt() {
        withAnimation(UIAccessibility.isReduceMotionEnabled ? nil : Motion.crossfade) { returnPrompt = nil }
        if landingShown, landingAnchor == nil { landing.refreshRest() }
    }

    /// "I ran it" on the prompt: the route draws and its card opens straight into the rating.
    func ranItFromPrompt() {
        guard let v = returnPrompt else { return }
        returnPrompt = nil
        openRoute(v.route, mode: .normal) { [weak self] in self?.ranIt() }
    }

    // MARK: Opening kept routes

    func openSaved(_ s: SavedRun) { openRoute(s.identity, mode: .normal) }

    /// A History row: the route on the map, with "Run again" as the primary action.
    func openHistory(_ log: RunLog) { openRoute(log.route, mode: .history) }

    /// Draws a kept route (from the phone, offline) and opens its card. Without a kept copy, a live
    /// app builds the request again instead.
    func openRoute(_ r: RouteIdentity, mode: CardMode, then: (() -> Void)? = nil) {
        guard stage == .landing || stage == .typing || stage == .settled else { return }
        let start = r.request
        guard let key = r.archive, let file = RouteArchive.load(key, start: start),
              let built = try? LoopData(file: file) else {
            // No kept copy: build the request again (live), or show the bundled route (offline).
            if LoopAPI.live != nil { send(r.request, reduceMotion: UIAccessibility.isReduceMotionEnabled) } else { openRun(request: r.request) }
            return
        }
        let reduceMotion = UIAccessibility.isReduceMotionEnabled
        liveTask?.cancel()
        flow?.cancel()
        playbackCancel()
        clearSelection()
        exitEditMode()
        pendingQuestion = nil
        liveNotice = nil
        rating = nil
        returnPrompt = nil
        // The route the runner kept comes first (Save on a #2 or #3 reopens that route, not #1).
        if let id = r.routeId, let i = built.candidates.firstIndex(where: { $0.serverId == id }), i > 0 {
            var cs = built.candidates
            cs.insert(cs.remove(at: i), at: 0)
            data = LoopData(request: built.request, candidates: cs, bestOf: built.bestOf)
        } else {
            data = built
        }
        shapeNote = nil
        liveMode = false
        routeCameraFree = false
        build = BuildState()
        drawnFraction = 0
        frameVersion += 1
        reachStart = nil; reachFadeStart = nil; candidatesStart = nil
        recordOnSettle = nil
        if landingShown { hideLanding(reduceMotion: reduceMotion) }
        withAnimation(reduceMotion ? nil : .timingCurve(0.2, 0, 0, 1, duration: 0.4)) { sheetShown = false }
        sheet.settle(open: false, animated: false)
        let sentence = r.request.hasSuffix(".") ? r.request : r.request + "."
        withAnimation(reduceMotion ? nil : Motion.textArrive) { requestText = sentence }
        readOut = nil
        locationPulsing = false
        stage = .building
        currentRoute = r
        cardMode = mode
        afterSettle = then
        Haptics.prepareSettle()
        startBuild(reduceMotion: reduceMotion)
    }

    /// "Run again" (decision 043): the stored route's own line, read for now, when the server has it;
    /// otherwise the card just turns back into a normal one.
    func runAgain() {
        touch()
        guard let r = currentRoute, let id = r.routeId, LoopAPI.live != nil else {
            withAnimation(Motion.crossfade) { cardMode = .normal }
            if let r = currentRoute { runs.noteViewed(r) }
            return
        }
        runAgainLive(routeId: id, request: r.request)
    }
}
