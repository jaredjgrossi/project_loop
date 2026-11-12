import AVFoundation
import CoreHaptics
import QuartzCore
import SwiftUI
import UIKit

/// Signature moment D, "Pencil, then ink" (signature-moments-v1). Behind the lab switch.
///
/// While Loop looks, everything on the map is pencil: the candidates are graphite sketch lines
/// and so is the current best. At the flag the winner is inked: the route's own line sweeps along
/// the pencil from the start, mile marks stamp in as the ink passes them, the distance on the card
/// rolls up to land with the last stroke, and the phone plays one pattern for the whole move (a
/// rising hum, a tick per mile, a soft knock at the end) in place of a single tap.
///
/// The wildcard (D+) adds a tilted "drafting table" camera at the settle, paper grain over the
/// screen, and a brush-and-knock sound.
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
        guard DesignLab.shared.ink, let flag = build.provisionalAt, let line = shown?.line else { return false }
        return now - flag < inkDuration(lengthM: line.length) + 0.1
    }

    /// Turn the frame the map is about to draw into pencil (before the flag) or pencil being inked
    /// (during the sweep). Once the ink is dry the frame is left as it was.
    func applyInk(_ frame: inout RouteFrame, shown: Candidate, now: CFTimeInterval, reduceMotion: Bool) {
        frame.sketch = true
        guard let p = inkProgress(now: now, reduceMotion: reduceMotion) else {
            // Pencil: what would have been drawn as the route is a graphite line, with no marks.
            frame.pencil = frame.casing
            frame.casing = []
            frame.lead = []
            if drawnFraction != 0 { drawnFraction = 0 }
            return
        }
        guard p < 1 else { return }
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
        if DesignLab.shared.isOn(.inkWild) { InkSound.shared.playSettle(duration: duration) }
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

    /// D+: the settle tilts the map like a drafting table, looking along the route.
    var heroTilt: Bool { DesignLab.shared.isOn(.inkWild) && build.provisional && !fly.active }

    /// The bearing from the start to the route's farthest point: the way the hero shot looks.
    var heroBearing: Double {
        guard let pts = shown?.line.points, let first = pts.first else { return 0 }
        var far = first, best = 0.0
        for p in pts { let d = first.distance(to: p); if d > best { best = d; far = p } }
        return first.bearing(to: far)
    }
}

extension GeoPoint {
    /// Compass bearing to another point, in degrees clockwise from north.
    func bearing(to other: GeoPoint) -> Double {
        let lat1 = lat * .pi / 180, lat2 = other.lat * .pi / 180
        let dLon = (other.lon - lon) * .pi / 180
        let y = sin(dLon) * cos(lat2)
        let x = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dLon)
        return (atan2(y, x) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
    }
}

// MARK: Haptics

/// Patterns, not taps (Core Haptics). Each is one continuous gesture the hand can read without the
/// screen. Silent where the hardware has no engine (the simulator, older phones).
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

    /// The arrival (moment F): a long rise while the run draws onto the map, three ascending taps
    /// as the totals land, and a full, round finish.
    func playArrival(draw: TimeInterval, totalsAt: TimeInterval) {
        var events = [Self.hum(0, draw, 0.4, 0.1)]
        for (i, dt) in [0.0, 0.16, 0.32].enumerated() {
            events.append(Self.tap(totalsAt + dt, 0.5 + Float(i) * 0.15, 0.45 + Float(i) * 0.15))
        }
        events.append(Self.tap(totalsAt + 0.62, 1.0, 0.2))
        let rise = CHHapticParameterCurve(parameterID: .hapticIntensityControl, controlPoints: [
            .init(relativeTime: 0, value: 0.15), .init(relativeTime: draw, value: 0.9),
        ], relativeTime: 0)
        play(events, curves: [rise])
    }

    /// One soft tick with a little body: a mile passing in the flyover.
    func playMile() { play([Self.tap(0, 0.6, 0.55), Self.tap(0.07, 0.25, 0.2)]) }
}

// MARK: Sound (D+ only)

/// Two made sounds, no audio files: a brush of filtered noise while the ink runs, and a low wooden
/// knock when it lands. Plays as ambient audio, so the ring switch silences it and music keeps
/// playing. Written by ear-less hands: tune on the phone before anyone else hears it.
@MainActor
final class InkSound {
    static let shared = InkSound()
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1)!
    private var ready = false

    private func start() -> Bool {
        if ready { return true }
        do {
            try AVAudioSession.sharedInstance().setCategory(.ambient, options: [.mixWithOthers])
            engine.attach(player)
            engine.connect(player, to: engine.mainMixerNode, format: format)
            try engine.start()
            ready = true
        } catch { ready = false }
        return ready
    }

    private func buffer(seconds: Double, _ sample: (Double, Double) -> Float) -> AVAudioPCMBuffer? {
        let n = AVAudioFrameCount(seconds * format.sampleRate)
        guard let b = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: n), let ch = b.floatChannelData?[0] else { return nil }
        b.frameLength = n
        for i in 0..<Int(n) { ch[i] = sample(Double(i) / format.sampleRate, Double(i) / Double(n)) }
        return b
    }

    func playSettle(duration: TimeInterval) {
        guard start() else { return }
        // Brush: noise through a one-pole low-pass, swelling then easing off.
        var last: Float = 0
        let brush = buffer(seconds: duration) { _, u in
            let white = Float.random(in: -1...1)
            last += 0.08 * (white - last)
            let env = Float(sin(u * .pi)) * Float(0.4 + 0.6 * u)
            return last * env * 0.22
        }
        // Knock: two low partials with a fast decay.
        let knock = buffer(seconds: 0.22) { t, _ in
            let env = Float(exp(-t * 26))
            return (Float(sin(2 * .pi * 172 * t)) * 0.6 + Float(sin(2 * .pi * 344 * t)) * 0.25) * env * 0.5
        }
        if let brush { player.scheduleBuffer(brush) }
        if let knock { player.scheduleBuffer(knock) }
        player.play()
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

/// A mark lands like a stamp: a little large, then seated.
struct StampIn: ViewModifier {
    let active: Bool
    @State private var seated = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        if active, !reduceMotion {
            content
                .scaleEffect(seated ? 1 : 1.7)
                .opacity(seated ? 1 : 0)
                .onAppear { withAnimation(.spring(response: 0.26, dampingFraction: 0.58)) { seated = true } }
        } else {
            content
        }
    }
}

/// D+: paper grain over the whole screen, multiplied in at a few percent, so type and map read as
/// printed on the same sheet. One small noise tile, made once.
struct PaperGrain: View {
    private static let tile: UIImage = {
        let side = 128
        var rng = SystemRandomNumberGenerator()
        var bytes = [UInt8](repeating: 0, count: side * side)
        for i in bytes.indices { bytes[i] = UInt8(clamping: 242 + Int.random(in: -13...13, using: &rng)) }
        let provider = CGDataProvider(data: Data(bytes) as CFData)!
        let cg = CGImage(width: side, height: side, bitsPerComponent: 8, bitsPerPixel: 8, bytesPerRow: side,
                         space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGBitmapInfo(rawValue: 0),
                         provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)!
        return UIImage(cgImage: cg, scale: 2, orientation: .up)
    }()

    var body: some View {
        Image(uiImage: Self.tile)
            .resizable(resizingMode: .tile)
            .blendMode(.multiply)
            .opacity(0.7)
            .ignoresSafeArea()
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }
}
