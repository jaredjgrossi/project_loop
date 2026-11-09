import SwiftUI

/// The app's mark drawn on the map colour (the icon's "route L": riverside upright, street foot,
/// turnaround ring at the top, start dot at the end). Fades into the map at launch.
struct LaunchLogo: View {
    var body: some View {
        ZStack {
            Palette.mapLand.color
            Canvas { ctx, size in
                let s = 96.0 / 100.0
                let o = CGPoint(x: size.width / 2 - 48, y: size.height / 2 - 48)
                func p(_ x: Double, _ y: Double) -> CGPoint { CGPoint(x: o.x + x * s, y: o.y + y * s) }
                var l = Path()
                l.move(to: p(36, 22))
                l.addCurve(to: p(35, 68), control1: p(32, 38), control2: p(38, 54))
                l.addQuadCurve(to: p(44, 78), control: p(34, 78))
                l.addLine(to: p(68, 78))
                ctx.stroke(l, with: .color(Palette.routeWater.color),
                           style: StrokeStyle(lineWidth: 10 * s, lineCap: .round, lineJoin: .round))
                let ring = Path(ellipseIn: CGRect(x: p(36, 22).x - 5.8 * s, y: p(36, 22).y - 5.8 * s, width: 11.6 * s, height: 11.6 * s))
                ctx.fill(ring, with: .color(Palette.mapLand.color))
                ctx.stroke(ring, with: .color(Palette.routeWater.color), lineWidth: 3.8 * s)
                let dot = Path(ellipseIn: CGRect(x: p(68, 78).x - 7.4 * s, y: p(68, 78).y - 7.4 * s, width: 14.8 * s, height: 14.8 * s))
                ctx.fill(dot, with: .color(Palette.accentStart.color))
                ctx.stroke(dot, with: .color(Palette.mapLand.color), lineWidth: 3 * s)
            }
        }
        .ignoresSafeArea()
        .accessibilityHidden(true)
    }
}

/// The runner's location: the start dot with a soft pulse every 2 s while Loop waits.
struct LocationPulse: View {
    let pulsing: Bool

    var body: some View {
        TimelineView(.animation(paused: !pulsing)) { context in
            let t = pulsing ? context.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 2) / 2 : 1
            let e = 1 - pow(1 - t, 2)
            ZStack {
                Circle()
                    .fill(Palette.accentStart.color)
                    .frame(width: 18 + 46 * e, height: 18 + 46 * e)
                    .opacity(pulsing ? 0.5 * (1 - t) : 0)
                Circle()
                    .fill(Palette.accentStart.color)
                    .overlay(Circle().strokeBorder(Palette.routeCasing.color, lineWidth: 3))
                    .frame(width: 18, height: 18)
            }
            .frame(width: 70, height: 70)
        }
        .allowsHitTesting(false)
        .accessibilityElement()
        .accessibilityLabel("Your location")
    }
}

/// The bottom request bar: at launch it types an example in its placeholder colour; tapped, it
/// takes the runner's words, and go sends.
struct RequestBar: View {
    let model: MainModel
    @State private var draft = ""
    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let typing = model.stage == .typing
        HStack(spacing: 12) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(Palette.inkMuted.color)
            ZStack(alignment: .leading) {
                if !typing {
                    Text(model.barExample)
                        .typeStyle(TypeStyle(family: .fraunces, size: 21, lineHeight: 26, weight: 400))
                        .foregroundStyle(Palette.lineControl.color)
                        .lineLimit(1)
                        .accessibilityHidden(true)
                }
                TextField("", text: $draft)
                    .typeStyle(TypeStyle(family: .fraunces, size: 21, lineHeight: 26, weight: 400))
                    .foregroundStyle(Palette.ink.color)
                    .tint(Palette.focusRing.color)
                    .focused($focused)
                    .submitLabel(.go)
                    .onSubmit { model.send(draft, reduceMotion: reduceMotion); draft = ""; focused = false }
                    .opacity(typing ? 1 : 0.011)
                    .accessibilityLabel("Describe your run")
            }
        }
        .padding(.horizontal, 22)
        .frame(height: Metrics.requestBarHeight)
        .background(Capsule().fill(Palette.surfaceSheet.color))
        .overlay(Capsule().strokeBorder(typing ? Palette.focusRing.color : Palette.lineHairline.color, lineWidth: 1))
        .contentShape(Capsule())
        .onTapGesture { model.beginTyping(); focused = true }
        .onChange(of: model.stage) { _, stage in
            guard stage == .typing else { return }
            // The debug demo "taps and sends" the example itself, without the keyboard.
            if model.demoTyping { draft = model.barExample } else { focused = true }
        }
        .onAppear { if model.stage == .typing, !model.demoTyping { focused = true } }
        .padding(.horizontal, 16)
    }
}
