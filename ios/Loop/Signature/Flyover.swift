import Observation
import QuartzCore
import SwiftUI
import UIKit

/// Signature moment E, "Run it before you run it" (signature-moments-v1). Behind the lab switch.
///
/// From the route card, a preview flies the route at street height: the camera tilts down onto the
/// start and follows the line, buildings stand up, and the light is the light of the hour the run
/// is planned for (dawn at 6, dusk at 6 in the evening). A caption counts the distance and names
/// each stretch as it passes; the phone ticks at every mile. An out-and-back flies out to the turn.
/// It ends by rising back to the whole route with the card.
///
/// The wildcard (E+) makes it yours to hold: drag anywhere to scrub along the route, tap to pause,
/// and the city is a cream paper model.
@Observable
@MainActor
final class FlyState {
    /// The preview is up (changes rarely: safe to read from the main screen).
    var active = false
    /// Where the camera is along the route, in metres (changes every frame).
    var alongM = 0.0
    var endM = 1.0
    var playing = false
    @ObservationIgnored var speed = 250.0
    @ObservationIgnored var heading = 0.0
    @ObservationIgnored var lastTick: CFTimeInterval?
    @ObservationIgnored var lastMile = 0
    /// False while the camera eases into or out of the flight (the frame loop leaves it alone).
    @ObservationIgnored var cameraLive = false
}

extension MainModel {
    static let flyZoom: Double = 16.2
    static let flyPitch: Double = 62

    /// Start the preview from the card.
    func startFlyover() {
        guard DesignLab.shared.flyover, let d = shownDetail, !fly.active, d.line.length > 200 else { return }
        touch()
        clearSelection()
        let outAndBack = d.summary.kind == "out_and_back"
        let end = (outAndBack ? d.turnaround?.alongM : nil) ?? d.line.length
        fly.endM = end
        fly.alongM = 0
        fly.lastMile = 0
        fly.lastTick = nil
        // About 230 m a second of flight, held between 9 and 22 seconds.
        fly.speed = end / min(22, max(9, end / 230))
        fly.heading = d.line.point(at: 0).bearing(to: d.line.point(at: min(end, 160)))
        fly.cameraLive = false
        fly.playing = false
        let reduceMotion = UIAccessibility.isReduceMotionEnabled
        withAnimation(reduceMotion ? nil : Motion.sheetSettle) { sheetShown = false }
        fly.active = true
        Haptics.settle()
        requestCamera(.pose(d.line.point(at: 0), zoom: Self.flyZoom, bearing: fly.heading, pitch: Self.flyPitch),
                      animated: !reduceMotion, duration: 1.5)
        flyTask?.cancel()
        flyTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(reduceMotion ? 0.1 : 1.6))
            guard let self, !Task.isCancelled, self.fly.active else { return }
            self.fly.lastTick = nil
            self.fly.cameraLive = true
            self.fly.playing = true
        }
    }

    /// The end of the route, or the ×: rise back to the whole route and bring the card back.
    func finishFlyover() {
        guard fly.active else { return }
        flyTask?.cancel()
        fly.playing = false
        fly.cameraLive = false
        fly.active = false
        let reduceMotion = UIAccessibility.isReduceMotionEnabled
        routeCameraFree = false
        requestCamera(.overview, animated: !reduceMotion, duration: 1.3)
        withAnimation(reduceMotion ? nil : Motion.sheetSettle) { sheetShown = true }
        frameVersion += 1
    }

    /// E+: the runner's finger sets the position (and pauses the flight).
    func scrubFlyover(to alongM: Double) {
        guard fly.active else { return }
        fly.playing = false
        fly.cameraLive = true
        fly.alongM = min(fly.endM, max(0, alongM))
    }

    func toggleFlyoverPlaying() {
        guard fly.active, fly.cameraLive else { return }
        if fly.alongM >= fly.endM - 1 { fly.alongM = 0; fly.lastMile = 0 }
        fly.lastTick = nil
        fly.playing.toggle()
    }

    /// The light for the preview: the hour the run is planned for, else now.
    var flyLight: (preset: String, word: String) {
        let planned = RunStats.minutes(data.request.startHourText).map { $0 / 60 }
        let hour = planned ?? Calendar.current.component(.hour, from: Date())
        switch hour {
        case 5..<8: return ("dawn", "Dawn light")
        case 8..<17: return ("day", "Daylight")
        case 17..<20: return ("dusk", "Evening light")
        default: return ("night", "After dark")
        }
    }

    /// What the caption says at the camera's position.
    var flyCaption: (miles: Double, name: String, kind: DrawKind?) {
        guard let d = shownDetail, d.line.length > 0 else { return (0, "", nil) }
        let miles = fly.alongM / d.line.length * d.distanceMi
        let s = d.stretch(atMile: miles)
        return (miles, s?.name ?? "", s?.kind)
    }
}

/// The preview's own screen furniture: a caption that counts and names, a progress line with mile
/// ticks, the runner's dot, and a way out. Everything else on the screen steps back.
struct FlyoverOverlay: View {
    let model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var dragStart: Double?

    private var fly: FlyState { model.fly }
    private var wild: Bool { DesignLab.shared.isOn(.flyoverWild) }

    var body: some View {
        GeometryReader { geo in
            let caption = model.flyCaption
            ZStack(alignment: .bottomLeading) {
                // E+: the whole screen scrubs and pauses.
                if wild {
                    Color.clear.contentShape(Rectangle())
                        .gesture(DragGesture(minimumDistance: 4)
                            .onChanged { v in
                                if dragStart == nil { dragStart = fly.alongM }
                                model.scrubFlyover(to: (dragStart ?? 0) + Double(v.translation.width / geo.size.width) * fly.endM)
                            }
                            .onEnded { _ in dragStart = nil })
                        .onTapGesture { model.toggleFlyoverPlaying() }
                        .accessibilityHidden(true)
                }

                LinearGradient(colors: [Palette.mapLand.color.opacity(0), Palette.mapLand.color.opacity(0.92)],
                               startPoint: .top, endPoint: .bottom)
                    .frame(height: 250)
                    .frame(maxHeight: .infinity, alignment: .bottom)
                    .ignoresSafeArea()
                    .allowsHitTesting(false)

                // The runner: where the camera is looking.
                if let d = model.shownDetail, let p = model.screenPoint(d.line.point(at: fly.alongM)) {
                    ZStack {
                        Circle().fill(Palette.accentStart.color.opacity(0.22)).frame(width: 34, height: 34)
                        Circle().fill(Palette.accentStart.color)
                            .overlay(Circle().strokeBorder(Palette.routeCasing.color, lineWidth: 2.5))
                            .frame(width: 16, height: 16)
                    }
                    .position(p)
                    .ignoresSafeArea()
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
                }

                VStack(alignment: .leading, spacing: 0) {
                    Text("Preview · \(model.flyLight.word)")
                        .typeStyle(.eyebrow)
                        .foregroundStyle(Palette.inkMuted.color)
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text(CardText.oneDecimal(caption.miles))
                            .typeStyle(.numeralXL)
                            .monospacedDigit()
                            .foregroundStyle(Palette.ink.color)
                        Text("mi").typeStyle(.numeralL).foregroundStyle(Palette.unitInk.color)
                    }
                    .padding(.top, 2)
                    HStack(spacing: 10) {
                        KindSwatch(kind: caption.kind)
                        Text(caption.name)
                            .typeStyle(.bodyStrong)
                            .foregroundStyle(Palette.ink.color)
                            .lineLimit(1)
                            .contentTransition(.opacity)
                            .animation(reduceMotion ? nil : Motion.textArrive, value: caption.name)
                    }
                    .frame(height: 24)
                    FlyProgress(model: model)
                        .frame(height: 14)
                        .padding(.top, 14)
                    if wild {
                        Text(fly.playing ? "Drag to scrub · tap to pause" : "Drag to scrub · tap to play")
                            .typeStyle(.label)
                            .foregroundStyle(Palette.inkMuted.color)
                            .padding(.top, 8)
                    }
                }
                .padding(.horizontal, Metrics.s24)
                .padding(.bottom, 18)
                .allowsHitTesting(false)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("Preview, \(CardText.oneDecimal(caption.miles)) miles, \(caption.name)")
                .accessibilityAddTraits(.updatesFrequently)

                CloseCardButton { model.finishFlyover() }
                    .accessibilityLabel("Close preview")
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                    .padding(.trailing, 14)
                    .padding(.top, 6)
            }
        }
        .transition(.opacity)
    }
}

/// A hairline for the flight with a tick at each mile; the part flown is inked.
private struct FlyProgress: View {
    let model: MainModel

    var body: some View {
        let fly = model.fly
        Canvas { ctx, size in
            let y = size.height / 2
            var track = Path()
            track.move(to: CGPoint(x: 0, y: y))
            track.addLine(to: CGPoint(x: size.width, y: y))
            ctx.stroke(track, with: .color(Palette.lineControl.color.opacity(0.5)), style: StrokeStyle(lineWidth: 1.5, lineCap: .round))
            var mile = 1609.344
            while mile < fly.endM {
                let x = size.width * mile / fly.endM
                var tick = Path()
                tick.move(to: CGPoint(x: x, y: y - 4))
                tick.addLine(to: CGPoint(x: x, y: y + 4))
                ctx.stroke(tick, with: .color(Palette.inkMuted.color), lineWidth: 1)
                mile += 1609.344
            }
            var done = Path()
            done.move(to: CGPoint(x: 0, y: y))
            done.addLine(to: CGPoint(x: size.width * min(1, fly.alongM / max(1, fly.endM)), y: y))
            ctx.stroke(done, with: .color(Palette.routeWater.color), style: StrokeStyle(lineWidth: 3, lineCap: .round))
        }
    }
}

/// The card's way in: a small play button beside the bookmark.
struct PreviewButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "play.fill")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Palette.ink.color)
                .frame(width: 30, height: 30)
                .background(Circle().fill(Palette.surfaceSunken.color))
                .frame(width: Metrics.minTap, height: Metrics.minTap)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Preview the route")
        .accessibilityHint("Flies along the route")
    }
}
