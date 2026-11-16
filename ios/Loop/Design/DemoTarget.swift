import SwiftUI

extension View {
    /// Debug only: registers this view's screen frame under a name, so the demo script can put a tap dot where a
    /// finger would land (decision 060). In Release this is the view itself, nothing added.
    func demoTarget(_ name: String) -> some View {
        #if DEBUG
        return background(
            GeometryReader { g in
                Color.clear
                    .onAppear { DemoTargets.set(name, g.frame(in: .global)) }
                    .onChange(of: g.frame(in: .global)) { _, f in DemoTargets.set(name, f) }
                    .onDisappear { DemoTargets.clear(name) }
            }
        )
        #else
        return self
        #endif
    }
}

#if DEBUG
/// Where the demo script's taps land: the last known screen frame of each named view.
@MainActor
enum DemoTargets {
    private(set) static var frames: [String: CGRect] = [:]

    static func set(_ name: String, _ frame: CGRect) { frames[name] = frame }
    static func clear(_ name: String) { frames[name] = nil }
    static func center(_ name: String) -> CGPoint? { frames[name].map { CGPoint(x: $0.midX, y: $0.midY) } }
}
#endif
