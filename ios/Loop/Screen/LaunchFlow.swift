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
        static let parse: TimeInterval = 3.0
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
            self.landingShown = true
            self.landing.settle(open: false, animated: !reduceMotion)
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
                guard await wait(0.8) else { return }
                self.demoTyping = true
                self.stage = .typing
                guard await wait(0.7) else { return }
                self.send(Self.exampleRequest, reduceMotion: reduceMotion)
            }
        }
    }

    /// The runner taps the field.
    func beginTyping() {
        guard stage == .landing else { return }
        stage = .typing
    }

    /// The sheet slides away (the Mapbox logo follows it down).
    private func hideLanding(reduceMotion: Bool) {
        landingShown = false
        landing.slide(to: 0, animated: !reduceMotion)
    }

    /// Send a request. Until the API is wired, every request resolves to the saved Kips Bay file.
    func send(_ text: String, reduceMotion: Bool) {
        let sentence = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !sentence.isEmpty else { return }
        flow?.cancel()
        playbackCancel()
        clearSelection()
        build = BuildState()
        drawnFraction = 0
        frameVersion += 1
        reachStart = nil; reachFadeStart = nil; candidatesStart = nil
        demoTyping = false
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

        let z0 = zoom
        // Push in on the start while Loop reads, then keep drifting in slowly.
        requestCamera(.at(location, zoom: z0 + 1.4), animated: true, duration: 1.2)
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
    private func startBuild(reduceMotion: Bool) {
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
        }
    }

    /// A saved run or a recent row: the sheet slides away and the route draws straight away (no
    /// wait: nothing to read), then its card opens. Until the API is wired, every run is the saved file's.
    func openRun(request: String) {
        let sentence = request.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !sentence.isEmpty, stage == .landing || stage == .typing else { return }
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
        let candidatesDone = (candidatesStart.map { now - $0 } ?? 0) > Timing.candidateDraw + Double(data.candidates.count) * Timing.candidateStagger
        return now - start < Timing.reachOpen + 0.05 || !candidatesDone
    }
}
