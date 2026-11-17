import Foundation
import QuartzCore
import SwiftUI
import UIKit

/// Launch and the wait, as in loop-launch-and-wait-v1 (UI chat, 2026-11-08):
/// logo fades into the map → location pulses → the landing sheet rises and its field types an
/// example (UI chat, 2026-11-09: the sheet replaces the floating bar) → send →
/// camera pushes in while Loop reads (~3 s) → camera pulls back, the reach ring opens with warm
/// parks and water → candidate lines draw → the leader draws → the existing settle.
/// The parse is simulated from the saved file until the iPhone is wired to the Phase 3 server.
extension MainModel {
    static let exampleRequest = "3 miles by the water at 7"

    enum Timing {
        static let logoFade: TimeInterval = 0.9
        static let pulseIn: TimeInterval = 1.3
        static let sheetIn: TimeInterval = 1.7
        static let typeStart: TimeInterval = 2.2
        static let typeStep: TimeInterval = 0.055
        /// Send → parsed (the parser's median, decision log 2026-11-08).
        static var parse: TimeInterval {
            #if DEBUG
            // Debug: `-LoopParseAt 1.7` simulates when `parsed` arrives (median 1.7 s, p90 3.1 s, 2026-11-09).
            let args = ProcessInfo.processInfo.arguments
            if let i = args.firstIndex(of: "-LoopParseAt"), i + 1 < args.count, let t = Double(args[i + 1]) { return t }
            #endif
            return 3.0
        }
        /// parsed → first route.
        static let firstRoute: TimeInterval = 1.0
        static let candidatesAfterParse: TimeInterval = 0.5
        static let reachOpen: TimeInterval = 1.1
        static let reachFade: TimeInterval = 0.45
        static let candidateDraw: TimeInterval = 0.7
        static let candidateStagger: TimeInterval = 0.15
    }

    /// The launch sequence. `autoSend` plays the video's "you tap and send" with the example (debug).
    func runLaunch(reduceMotion: Bool, autoSend: Bool) {
        flow?.cancel()
        build = BuildState()
        frameVersion += 1
        drawnFraction = 0
        requestText = nil
        stage = .logo
        logoShown = true
        landingShown = false
        landing.slide(to: 0, animated: false)
        landingAnchor = nil
        sheetShown = false
        fieldExample = ""
        clearSelection()
        requestCamera(.at(location, zoom: 14.2), animated: false)
        flow = Task { @MainActor [weak self] in
            func wait(_ t: TimeInterval) async -> Bool {
                try? await Task.sleep(for: .seconds(t)); return !Task.isCancelled
            }
            guard await wait(Timing.logoFade), let self else { return }
            // Hold the logo until the map has drawn (at most 5 s more), so it fades into a map.
            var held = 0.0
            while !self.mapReady && held < 5 { guard await wait(0.1) else { return }; held += 0.1 }
            // The style's first load fits the overview; put the location back in the middle.
            self.requestCamera(.at(self.location, zoom: 14.2), animated: false)
            withAnimation(reduceMotion ? nil : .timingCurve(0.2, 0, 0, 1, duration: 0.6)) { self.logoShown = false }
            guard await wait(Timing.pulseIn - Timing.logoFade) else { return }
            self.locationPulsing = !reduceMotion
            self.stage = .landing
            guard await wait(Timing.sheetIn - Timing.pulseIn) else { return }
            // It arrives open (field, runs, recent), rising whole.
            self.landingShown = true
            self.landingAnchor = self.landing.openHeight
            self.landing.settle(rest: .open, animated: !reduceMotion) { [weak self] in self?.landingAnchor = nil }
            guard await wait(Timing.typeStart - Timing.sheetIn) else { return }
            if reduceMotion {
                self.fieldExample = Self.exampleRequest
            } else {
                for ch in Self.exampleRequest {
                    guard self.stage == .landing else { return }
                    self.fieldExample.append(ch)
                    guard await wait(Timing.typeStep) else { return }
                }
            }
            if autoSend {
                guard await wait(0.8), self.stage == .landing else { return }
                self.demoTyping = true
                self.stage = .typing
                guard await wait(0.7) else { return }
                self.send(Self.exampleRequest, reduceMotion: reduceMotion)
            }
        }
    }

    /// The runner taps the field: the example stops typing at once and the field is empty with a
    /// static placeholder; the sheet crossfades to matching runs and grows with the keyboard, on
    /// the keyboard's own curve (the keyboard notification drives it).
    func beginTyping() {
        guard stage == .landing else { return }
        fieldMatches = runs.matches(fieldText)
        stage = .typing
        fieldExample = ""
        pickedShape = UsualShape(rawValue: runs.profile.usualShape) ?? .any
        shapeTouched = false
        // No keyboard coming (a hardware keyboard): settle on our own curve.
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(0.6))
            guard let self, self.searchMode, self.keyboardHeight == 0 else { return }
            self.layoutSearch(animated: !UIAccessibility.isReduceMotionEnabled)
        }
    }

    /// Tapping the map or the sheet, or dragging it down: the keyboard goes, the text stays. The
    /// keyboard's hide drives the sheet back to its rest; with no keyboard up, it settles now.
    func endTyping() {
        guard stage == .typing, !demoTyping else { return }
        stage = .landing
        if keyboardHeight == 0 {
            landing.settle(rest: landing.rest, animated: !UIAccessibility.isReduceMotionEnabled)
        }
    }

    /// Cancel: ends editing, clears the field, and the placeholder comes back.
    func cancelTyping() {
        fieldText = ""
        endTyping()
    }

    /// Search mode's height: the field and one 40 pt row per match, sitting on the keyboard (the
    /// sheet runs on under the keyboard, so its height includes it).
    func landingSearchHeight(keyboard: CGFloat) -> CGFloat {
        let inset = LandingSheet.bottomInset
        let rows = CGFloat(fieldMatches.count)
        // The route-type row and matches as measured (until measured: the field, the row at
        // 10 + 44, 40 pt per match), 10 pt under them; never taller than the space under the header.
        let listBottom = landingSearchBottom ?? landingFieldBottom + 54 + (rows > 0 ? 6 + rows * 40 : 0)
        let content = listBottom + 10
        let room = UIScreen.main.bounds.height - headerBottom - 8
        return min(content + (keyboard > 0 ? keyboard : inset), room).rounded()
    }

    /// The typing list was measured (it moves when the return prompt above the field hides, and
    /// grows or shrinks with the matches): refit the sheet to it.
    func searchListMeasured(_ bottom: CGFloat) {
        guard searchMode else { landingSearchBottom = nil; return }
        guard abs((landingSearchBottom ?? -1) - bottom) > 0.5 else { return }
        landingSearchBottom = bottom
        layoutSearch(animated: !UIAccessibility.isReduceMotionEnabled)
    }

    /// While typing, the sheet fits the field and the rows decided when typing started; it
    /// doesn't change as the runner types.
    func layoutSearch(animated: Bool) {
        guard searchMode, landingShown, landingAnchor == nil else { return }
        landing.slide(to: landingSearchHeight(keyboard: keyboardHeight), animated: animated,
                      duration: 0.2, curve: SheetState.settleCurve)
    }

    /// The keyboard came, went or changed: the sheet moves with it, on its curve and duration, so
    /// they move as one. The map's padding follows the sheet every frame (no camera animations).
    func keyboardChanged(height: CGFloat, duration: TimeInterval) {
        guard abs(height - keyboardHeight) > 0.5 else { return }
        keyboardHeight = height
        // The rating from the return prompt lifts itself onto the keyboard (MainScreen); the sheet stays.
        guard landingShown, landingAnchor == nil, rating?.fromPrompt != true else { return }
        let target = searchMode ? landingSearchHeight(keyboard: height) : landing.height(for: landing.rest)
        landing.slide(to: target, animated: duration > 0, duration: duration, curve: SheetState.keyboardCurve)
    }

    /// The sheet slides away (the Mapbox logo follows it down).
    func hideLanding(reduceMotion: Bool) {
        landingShown = false
        landingAnchor = max(landing.height, landing.collapsedHeight)
        landing.slide(to: 0, animated: !reduceMotion)
    }

    /// Send a request. Until the API is wired, every request resolves to the saved Kips Bay file.
    func send(_ text: String, reduceMotion: Bool) {
        let sentence = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !sentence.isEmpty else { return }
        // Leave typing first, so nothing reacting to the cleared field thinks the runner is still typing.
        stage = .reading
        routeCameraFree = false
        rating = nil
        cardMode = .normal
        currentRoute = nil
        shapeNote = nil
        returnPrompt = nil
        flow?.cancel()
        playbackCancel()
        clearSelection()
        build = BuildState()
        drawnFraction = 0
        frameVersion += 1
        reachStart = nil; reachFadeStart = nil; candidatesStart = nil
        demoTyping = false
        fieldText = ""
        recordOnSettle = sentence
        hideLanding(reduceMotion: reduceMotion)
        withAnimation(reduceMotion ? nil : .timingCurve(0.2, 0, 0, 1, duration: 0.4)) { sheetShown = false }
        let shown = sentence.hasSuffix(".") ? sentence : sentence + "."
        withAnimation(reduceMotion ? nil : Motion.textArrive) { requestText = shown }
        exitEditMode()
        readOut = nil
        stage = .reading
        locationPulsing = !reduceMotion
        sheet.settle(open: false, animated: false)
        Haptics.prepareSettle()

        liveTask?.cancel()
        pendingQuestion = nil
        liveNotice = nil
        let z0 = zoom
        // Push in on the start while Loop reads, then keep drifting in slowly.
        requestCamera(.at(location, zoom: z0 + 1.4), animated: true, duration: 1.2)

        // With the server, its events drive the rest (LiveFlow.swift).
        if let api = LoopAPI.live {
            startLive(sentence: sentence, shown: shown, api: api, z0: z0, reduceMotion: reduceMotion)
            return
        }
        liveMode = false
        liveReachM = nil
        data = fixtureData
        flow = Task { @MainActor [weak self] in
            func wait(_ t: TimeInterval) async -> Bool { try? await Task.sleep(for: .seconds(t)); return !Task.isCancelled }
            guard await wait(1.2), let self else { return }
            self.requestCamera(.at(self.location, zoom: z0 + 1.6), animated: true, duration: 1.8)
            guard await wait(Timing.parse - 1.2) else { return }
            // Parsed: pull back to the reach, open the ring, then candidates.
            self.readOut = ReadOut.simulated(shown, data: self.data, file: nil)
            let t = CACurrentMediaTime()
            self.reachStart = reduceMotion ? t - 10 : t
            self.candidatesStart = reduceMotion ? t - 10 : t + Timing.candidatesAfterParse
            self.frameVersion += 1
            self.requestCamera(.circle(self.location, radiusM: self.reachMetres), animated: true, duration: 1.0)
            guard await wait(Timing.firstRoute) else { return }
            self.stage = .building
            self.locationPulsing = false
            self.startBuild(reduceMotion: reduceMotion)
        }
    }

    /// The engine's stream, faked from the file: #1 first, the provisional flag once the line has
    /// drawn, the final a little later. Settle = provisional: reach and candidates fade, sheet rises.
    /// Also draws a kept route (ComeBack.openRoute) the same way.
    func startBuild(reduceMotion: Bool) {
        let t0 = CACurrentMediaTime()
        receiveEvent(.top3(data.candidates.map(\.rank)), at: t0)
        requestCamera(.overview, animated: true, duration: 0.9)
        let drawTime = (shown?.line.length ?? 4800) / Motion.drawMetresPerSecond
        flow = Task { @MainActor [weak self] in
            func wait(_ t: TimeInterval) async -> Bool { try? await Task.sleep(for: .seconds(t)); return !Task.isCancelled }
            guard await wait(reduceMotion ? 0.2 : drawTime + 0.25), let self else { return }
            self.reachFadeStart = CACurrentMediaTime()
            self.receiveEvent(.provisional, at: CACurrentMediaTime())
            withAnimation(reduceMotion ? nil : Motion.sheetSettle) { self.sheetShown = true }
            guard await wait(1.8) else { return }
            self.receiveEvent(.final(self.data.candidates.map(\.rank)), at: CACurrentMediaTime())
            self.stage = .settled
            if let request = self.recordOnSettle, let route = self.shown {
                self.recordOnSettle = nil
                self.runs.addRecent(request: request, distanceMi: route.distanceMi, line: route.line)
            }
            if self.currentRoute == nil { self.currentRoute = self.identityOfShown(archive: RouteArchive.fixture, routeId: nil) }
            if let r = self.currentRoute, self.cardMode == .normal { self.runs.noteViewed(r) }
        }
    }

    /// Back to home (the card's ×, swiping the card down past collapsed, or the wordmark): the
    /// route and the sentence clear, the shown route goes to the top of Recent, the camera returns
    /// to the location and the landing sheet rises open.
    func goHome() {
        guard stage != .logo, stage != .landing, stage != .typing else { return }
        let reduceMotion = UIAccessibility.isReduceMotionEnabled
        if let text = requestText, let route = shown, cardRevealed {
            runs.addRecent(request: text, distanceMi: route.distanceMi, line: route.line, countsAsRun: false,
                           serverId: liveMode ? liveRouteId : nil)
        }
        liveTask?.cancel()
        pendingQuestion = nil
        liveNotice = nil
        rating = nil
        cardMode = .normal
        currentRoute = nil
        flow?.cancel()
        playbackCancel()
        clearSelection()
        exitEditMode()
        recordOnSettle = nil
        reachStart = nil; reachFadeStart = nil; candidatesStart = nil
        build = BuildState()
        drawnFraction = 0
        frameVersion += 1
        withAnimation(reduceMotion ? nil : Motion.sheetSettle) { sheetShown = false }
        withAnimation(reduceMotion ? nil : Motion.textArrive) { requestText = nil }
        readOut = nil
        fieldExample = ""
        stage = .landing
        locationPulsing = !reduceMotion
        landingShown = true
        landingAnchor = landing.openHeight
        // One ease to the location above the open sheet, timed with the sheet's rise; the map's
        // padding binds to the sheet again once both have arrived.
        landingCameraBound = false
        requestCamera(.above(location, bottom: landing.openHeight, zoom: 14.2), animated: !reduceMotion,
                      duration: SheetState.settleDuration)
        landing.settle(rest: .open, animated: !reduceMotion) { [weak self] in
            self?.landingAnchor = nil
            self?.landingCameraBound = true
        }
        sheet.settle(open: false, animated: false)
    }

    /// A saved run or a recent row: the sheet slides away and the route draws straight away (no
    /// wait: nothing to read), then its card opens. Until the API is wired, every run is the saved file's.
    func openRun(request: String) {
        let sentence = request.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !sentence.isEmpty, stage == .landing || stage == .typing else { return }
        // With the server, a saved run or recent is built again for now (closures, crowds, time).
        if LoopAPI.live != nil {
            send(sentence, reduceMotion: UIAccessibility.isReduceMotionEnabled)
            return
        }
        data = fixtureData
        liveMode = false
        routeCameraFree = false
        let reduceMotion = UIAccessibility.isReduceMotionEnabled
        flow?.cancel()
        playbackCancel()
        clearSelection()
        build = BuildState()
        drawnFraction = 0
        frameVersion += 1
        reachStart = nil; reachFadeStart = nil; candidatesStart = nil
        recordOnSettle = nil
        hideLanding(reduceMotion: reduceMotion)
        sheet.settle(open: false, animated: false)
        let shown = sentence.hasSuffix(".") ? sentence : sentence + "."
        withAnimation(reduceMotion ? nil : Motion.textArrive) { requestText = shown }
        readOut = ReadOut.simulated(shown, data: data, file: nil)
        locationPulsing = false
        stage = .building
        Haptics.prepareSettle()
        startBuild(reduceMotion: reduceMotion)
    }

    // MARK: Map frames for the wait

    func reachFrame(now: CFTimeInterval, reduceMotion: Bool) -> RouteFrame.Reach? {
        guard let start = reachStart else { return nil }
        let open = min(1, max(0, (now - start) / Timing.reachOpen))
        let eased = 1 - pow(1 - open, 3)
        var fade = 1.0
        if let f = reachFadeStart {
            fade = reduceMotion ? 0 : max(0, 1 - (now - f) / Timing.reachFade)
            if fade == 0 { return nil }
        }
        return RouteFrame.Reach(center: location, radiusM: reachMetres * eased,
                                ringOpacity: 0.6 * fade, dimOpacity: 0.6 * eased * fade, warmOpacity: eased * fade)
    }

    func candidateFrame(now: CFTimeInterval, reduceMotion: Bool) -> ([[GeoPoint]], Double) {
        guard let start = candidatesStart, now >= start else { return ([], 0) }
        var fade = 1.0
        if let f = reachFadeStart {
            fade = reduceMotion ? 0 : max(0, 1 - (now - f) / Timing.reachFade)
            if fade == 0 { return ([], 0) }
        }
        // Until the engine streams `candidates`, the file's top 3 outlines stand in.
        if liveMode {
            // Live: the engine's outlines as they arrive, each drawn in over 0.7 s.
            let lines: [[GeoPoint]] = liveOutlines.suffix(60).compactMap { o in
                let t = (now - max(start, o.at)) / Timing.candidateDraw
                let p = 1 - pow(1 - min(1, max(0, t)), 2)
                guard p > 0 else { return nil }
                let line = Polyline(o.points)
                let pts = line.slice(from: 0, to: line.length * p)
                return pts.count >= 2 ? pts : nil
            }
            return (lines, 0.3 * fade)
        }
        let lines: [[GeoPoint]] = data.candidates.enumerated().compactMap { i, c in
            let t = (now - start - Double(i) * Timing.candidateStagger) / Timing.candidateDraw
            let p = 1 - pow(1 - min(1, max(0, t)), 2)
            guard p > 0 else { return nil }
            let pts = c.line.slice(from: 0, to: c.line.length * p)
            return pts.count >= 2 ? pts : nil
        }
        return (lines, 0.3 * fade)
    }

    func waitIsMoving(now: CFTimeInterval, reduceMotion: Bool) -> Bool {
        guard let start = reachStart else { return false }
        if let f = reachFadeStart { return now - f < Timing.reachFade + 0.05 }
        if liveMode {
            // Live: moving while the ring opens or an outline is still drawing in.
            let lastOutline = liveOutlines.last?.at ?? 0
            return now - start < Timing.reachOpen + 0.05 || now - lastOutline < Timing.candidateDraw + 0.05
        }
        let candidatesDone = (candidatesStart.map { now - $0 } ?? 0) > Timing.candidateDraw + Double(data.candidates.count) * Timing.candidateStagger
        return now - start < Timing.reachOpen + 0.05 || !candidatesDone
    }
}
