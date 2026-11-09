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
