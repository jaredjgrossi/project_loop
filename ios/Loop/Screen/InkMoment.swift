import CoreHaptics
import QuartzCore
import SwiftUI
import UIKit

/// "Pencil, then ink": how a route arrives (decision 052).
///
/// While Loop looks, everything on the map is pencil: the candidates are graphite sketch lines
/// and so is the current best. At the flag the winner is inked: the route's own line sweeps along
/// the pencil from the start, mile marks stamp in as the ink passes them, the distance on the card
/// rolls up to land with the last stroke, and the phone plays one pattern for the whole move (a
/// rising hum, a tick per mile, a soft knock at the end) in place of a single tap.
///
/// Reduce Motion: no sweep, no roll, no stamp. The route is inked whole at the flag, with the
/// plain settle tap.
extension MainModel {
    /// How long the ink takes to cover the route: about a second, a little longer for long runs.
    func inkDuration(lengthM: Double) -> TimeInterval { min(1.5, 0.75 + lengthM / 1609.344 * 0.08) }

    static func inkEase(_ t: Double) -> Double { let x = min(1, max(0, t)); return x * x * (3 - 2 * x) }

    /// 0...1 once the flag has come: how much of the route is inked. nil while still pencil.
    func inkProgress(now: CFTimeInterval, reduceMotion: Bool) -> Double? {
        guard let flag = build.provisionalAt, let line = shown?.line else { return nil }
        if reduceMotion { return 1 }
        return Self.inkEase((now - flag) / inkDuration(lengthM: line.length))
    }

    /// True while the ink is still moving.
    func inkIsMoving(now: CFTimeInterval) -> Bool {
        guard let flag = build.provisionalAt, let line = shown?.line else { return false }
        return now - flag < inkDuration(lengthM: line.length) + 0.1
    }

    /// Turn the frame the map is about to draw into pencil (before the flag) or pencil being inked
    /// (during the sweep). Once the ink is dry the frame is left as it was.
    func applyInk(_ frame: inout RouteFrame, shown: Candidate, now: CFTimeInterval, reduceMotion: Bool) {
        guard let p = inkProgress(now: now, reduceMotion: reduceMotion) else {
            // Pencil: what would have been drawn as the route is a graphite line, with no marks.
            frame.pencil = frame.casing
            frame.casing = []
            frame.lead = []
            // No direction chevrons on a sketch: they say "this is the route, run it this way".
            frame.arrows = []
            frame.arrowsOpacity = 0
            if drawnFraction != 0 { drawnFraction = 0 }
            return
        }
        guard p < 1 else { return }
        // The chevrons arrive with the last of the ink (as they did with the last of the line).
        frame.arrowsOpacity *= max(0, min(1, (p - 0.9) / 0.1))
        if frame.arrowsOpacity == 0 { frame.arrows = [] }
        let mpp = MapScale.metresPerPoint(zoom: zoom, latitude: shown.line.points[0].lat)
        let inked = RouteFrame.route(for: shown, fraction: p, metresPerPoint: mpp)
        frame.casing = inked.casing
        frame.lead = inked.lead
        frame.pencil = RouteFrame.displayLine(for: shown.line, metresPerPoint: mpp).line.points
        if drawnFraction != p { drawnFraction = p }
    }

    /// The flag has come: play the settle as one move. The ring pulses when the ink arrives, not
    /// when it starts.
    func inkSettle() {
        guard let line = shown?.line else { return }
        let duration = inkDuration(lengthM: line.length)
        // A tick as the ink passes each mile.
        let miles = stride(from: 1609.344, to: line.length, by: 1609.344).map { $0 / line.length }
        let ticks = miles.map { Self.inkTime(forProgress: $0) * duration }
        InkHaptics.shared.playSettle(duration: duration, ticks: ticks)
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(duration))
            self?.bumpPulse()
        }
    }

    /// The time (0...1) at which the eased sweep reaches a share of the route.
    static func inkTime(forProgress p: Double) -> Double {
        var lo = 0.0, hi = 1.0
        for _ in 0..<24 { let mid = (lo + hi) / 2; if inkEase(mid) < p { lo = mid } else { hi = mid } }
        return (lo + hi) / 2
    }
}

// MARK: Haptics

/// The settle as a pattern, not a tap (Core Haptics): one continuous gesture the hand can read
/// without the screen. Silent where the hardware has no engine (the simulator, older phones).
@MainActor
final class InkHaptics {
    static let shared = InkHaptics()
    private var engine: CHHapticEngine?

    private init() {
        guard CHHapticEngine.capabilitiesForHardware().supportsHaptics else { return }
        engine = try? CHHapticEngine()
        engine?.isAutoShutdownEnabled = true
        engine?.resetHandler = { [weak self] in try? self?.engine?.start() }
    }

    private func play(_ events: [CHHapticEvent], curves: [CHHapticParameterCurve] = []) {
        guard let engine else { return }
        do {
            try engine.start()
            let pattern = try CHHapticPattern(events: events, parameterCurves: curves)
            try engine.makePlayer(with: pattern).start(atTime: CHHapticTimeImmediate)
        } catch {}
    }

    private static func tap(_ t: TimeInterval, _ intensity: Float, _ sharpness: Float) -> CHHapticEvent {
        CHHapticEvent(eventType: .hapticTransient, parameters: [
            .init(parameterID: .hapticIntensity, value: intensity),
            .init(parameterID: .hapticSharpness, value: sharpness),
        ], relativeTime: t)
    }

    private static func hum(_ t: TimeInterval, _ duration: TimeInterval, _ intensity: Float, _ sharpness: Float) -> CHHapticEvent {
        CHHapticEvent(eventType: .hapticContinuous, parameters: [
            .init(parameterID: .hapticIntensity, value: intensity),
            .init(parameterID: .hapticSharpness, value: sharpness),
        ], relativeTime: t, duration: duration)
    }

    /// The settle: a low hum that rises as the ink runs, a crisp tick at each mile, and one soft,
    /// round knock (with a faint echo) when the line lands.
    func playSettle(duration: TimeInterval, ticks: [TimeInterval]) {
        var events = [Self.hum(0, duration, 0.45, 0.12)]
        events += ticks.map { Self.tap($0, 0.55, 0.75) }
        events.append(Self.tap(duration, 1.0, 0.25))
        events.append(Self.tap(duration + 0.11, 0.35, 0.15))
        let rise = CHHapticParameterCurve(parameterID: .hapticIntensityControl, controlPoints: [
            .init(relativeTime: 0, value: 0.25), .init(relativeTime: duration * 0.7, value: 0.7),
            .init(relativeTime: duration, value: 1.0),
        ], relativeTime: 0)
        play(events, curves: [rise])
    }
}

// MARK: Views

/// The distance on the card rolls up from zero and lands as the ink does.
struct RollingDistance: View {
    let target: Double
    let duration: TimeInterval
    let roll: Bool
    @State private var value = 0.0

    var body: some View {
        RollingNumber(value: roll ? value : target)
            .onAppear {
                guard roll else { return }
                withAnimation(.timingCurve(0.3, 0, 0.2, 1, duration: duration)) { value = target }
            }
            .onChange(of: target) { _, v in value = v }
    }
}

private struct RollingNumber: View, Animatable {
    var value: Double
    var animatableData: Double {
        get { value }
        set { value = newValue }
    }

    var body: some View {
        Text(CardText.distance(value))
            .typeStyle(.numeralXL)
            .monospacedDigit()
            .foregroundStyle(Palette.ink.color)
    }
}

/// A mark lands like a stamp: a little large, then seated. Only for marks that appear while the
/// ink is running; a mark that comes back later (a zoom, another route) just appears.
struct StampIn: ViewModifier {
    @State private var seated: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(active: Bool) { _seated = State(initialValue: !active) }

    func body(content: Content) -> some View {
        content
            .scaleEffect(seated || reduceMotion ? 1 : 1.7)
            .opacity(seated || reduceMotion ? 1 : 0)
            .onAppear {
                guard !seated else { return }
                withAnimation(reduceMotion ? nil : .spring(response: 0.26, dampingFraction: 0.58)) { seated = true }
            }
    }
}
