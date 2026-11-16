#if DEBUG
import Observation
import SwiftUI

/// A soft dot where each scripted tap lands, since a screen recording shows no touches (decision 060).
/// The look, for Jared to approve from the test capture: a 44 pt disc in the action blue at 16%, a 1.5 pt ring at
/// 45%, rising from 60% size and fading over 500 ms. Quiet enough not to read as part of the app.
@MainActor @Observable
final class TapDots {
    struct Dot: Identifiable, Equatable {
        let id: Int
        let point: CGPoint
    }

    static let shared = TapDots()
    private(set) var dots: [Dot] = []
    private var next = 0

    func tap(at point: CGPoint) {
        next += 1
        let dot = Dot(id: next, point: point)
        withAnimation(.easeOut(duration: 0.18)) { dots.append(dot) }
        Task { @MainActor in
            try? await Task.sleep(for: .seconds(0.5))
            withAnimation(.easeOut(duration: 0.35)) { dots.removeAll { $0.id == dot.id } }
        }
    }
}

/// Draws the dots in screen coordinates. `origin` is the hosting view's own screen origin, so a layer inside a
/// presented sheet draws them in the right place too.
struct TapDotLayer: View {
    private let dots = TapDots.shared

    var body: some View {
        GeometryReader { g in
            let origin = g.frame(in: .global).origin
            ZStack {
                ForEach(dots.dots) { d in
                    Circle()
                        .fill(Palette.action.color.opacity(0.16))
                        .overlay(Circle().strokeBorder(Palette.action.color.opacity(0.45), lineWidth: 1.5))
                        .frame(width: 44, height: 44)
                        .position(x: d.point.x - origin.x, y: d.point.y - origin.y)
                        .transition(.scale(scale: 0.6).combined(with: .opacity))
                }
            }
        }
        .allowsHitTesting(false)
        .ignoresSafeArea()
    }
}
#endif
