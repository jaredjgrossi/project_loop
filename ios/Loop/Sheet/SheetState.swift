import Observation
import QuartzCore
import UIKit

/// The sheet's height, driven frame by frame: it follows the finger 1:1 while dragging and settles
/// with our own 320 ms cubic-bezier(0.2, 0, 0, 1) instead of a SwiftUI animation, so everything
/// pinned to the sheet (the Mapbox logo and attribution, chips) can follow it on every frame.
/// Only views that read `height` re-render while it moves.
@Observable
@MainActor
final class SheetState {
    static let collapsed = Metrics.sheetCollapsed
    static let open = Metrics.sheetOpen
    static let settleDuration: CFTimeInterval = 0.32

    /// The live height, every frame.
    private(set) var height: CGFloat = SheetState.collapsed
    /// Where it rests once still.
    private(set) var restingOpen = false
    /// Dragging or settling.
    private(set) var isMoving = false

    /// Called on every height change, outside SwiftUI (the map's ornaments use it).
    @ObservationIgnored var onHeightChange: ((CGFloat) -> Void)?

    @ObservationIgnored private var dragStart: CGFloat = SheetState.collapsed
    @ObservationIgnored private var settle: (from: CGFloat, to: CGFloat, start: CFTimeInterval, done: () -> Void)?
    @ObservationIgnored private var link: CADisplayLink?
    @ObservationIgnored private lazy var proxy = DisplayLinkProxy { [weak self] in self?.step() }

    var restingHeight: CGFloat { restingOpen ? Self.open : Self.collapsed }
    var progress: CGFloat { max(0, min(1, (height - Self.collapsed) / (Self.open - Self.collapsed))) }

    // MARK: Drag

    func beginDrag() {
        stopSettle()
        isMoving = true
        dragStart = height
    }

    /// `translation` is the finger's vertical travel since the drag began (down is positive).
    func drag(translation: CGFloat) {
        if !isMoving { beginDrag() }
        let raw = dragStart - translation
        // 1:1 between the two states; past either end it resists (a third of the travel).
        let h: CGFloat
        if raw > Self.open { h = Self.open + (raw - Self.open) / 3 }
        else if raw < Self.collapsed { h = Self.collapsed - (Self.collapsed - raw) / 3 }
        else { h = raw }
        setHeight(h)
    }

    /// Picks a state from where the finger would have carried the sheet, then settles there.
    func endDrag(predictedTranslation: CGFloat, animated: Bool, completion: @escaping (Bool) -> Void) {
        let predicted = dragStart - predictedTranslation
        let open = predicted > (Self.collapsed + Self.open) / 2
        settle(open: open, animated: animated) { completion(open) }
    }

    // MARK: Settle

    func settle(open: Bool, animated: Bool, completion: @escaping () -> Void = {}) {
        restingOpen = open
        let target = open ? Self.open : Self.collapsed
        stopSettle()
        guard animated, abs(height - target) > 0.5 else {
            setHeight(target)
            isMoving = false
            completion()
            return
        }
        isMoving = true
        settle = (height, target, CACurrentMediaTime(), completion)
        let l = CADisplayLink(target: proxy, selector: #selector(DisplayLinkProxy.fire))
        l.add(to: .main, forMode: .common)
        link = l
    }

    private func step() {
        guard let s = settle else { return }
        let t = min(1, (CACurrentMediaTime() - s.start) / Self.settleDuration)
        let e = CubicBezier.ease(0.2, 0, 0, 1, x: t)
        setHeight(s.from + (s.to - s.from) * CGFloat(e))
        if t >= 1 {
            let done = s.done
            stopSettle()
            isMoving = false
            done()
        }
    }

    private func stopSettle() {
        link?.invalidate()
        link = nil
        settle = nil
    }

    private func setHeight(_ h: CGFloat) {
        guard h != height else { return }
        height = h
        onHeightChange?(h)
    }
}

/// CADisplayLink retains its target; this keeps it off the sheet state.
final class DisplayLinkProxy: NSObject {
    private let action: () -> Void
    init(_ action: @escaping () -> Void) { self.action = action }
    @objc func fire() { action() }
}

/// CSS-style cubic-bezier timing: y for a given x in 0...1.
enum CubicBezier {
    static func ease(_ x1: Double, _ y1: Double, _ x2: Double, _ y2: Double, x: Double) -> Double {
        if x <= 0 { return 0 }
        if x >= 1 { return 1 }
        func bx(_ t: Double) -> Double { 3 * (1 - t) * (1 - t) * t * x1 + 3 * (1 - t) * t * t * x2 + t * t * t }
        func by(_ t: Double) -> Double { 3 * (1 - t) * (1 - t) * t * y1 + 3 * (1 - t) * t * t * y2 + t * t * t }
        func dbx(_ t: Double) -> Double { 3 * (1 - t) * (1 - t) * x1 + 6 * (1 - t) * t * (x2 - x1) + 3 * t * t * (1 - x2) }
        // Newton, falling back to bisection.
        var t = x
        for _ in 0..<8 {
            let err = bx(t) - x
            if abs(err) < 1e-6 { return by(t) }
            let d = dbx(t)
            if abs(d) < 1e-6 { break }
            t -= err / d
        }
        var lo = 0.0, hi = 1.0
        t = x
        for _ in 0..<30 {
            let v = bx(t)
            if abs(v - x) < 1e-6 { break }
            if v < x { lo = t } else { hi = t }
            t = (lo + hi) / 2
        }
        return by(t)
    }
}
