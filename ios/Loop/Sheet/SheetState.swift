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

    /// Collapsed, open (398 pt), and "read": dragged further, or reached from the card's can't-do
    /// line, it shows "How Loop read it" below the button (UI chat, 2026-11-08).
    enum Rest { case collapsed, open, read }

    /// The live height, every frame.
    private(set) var height: CGFloat = SheetState.collapsed
    /// Where it rests once still.
    private(set) var rest: Rest = .collapsed
    var restingOpen: Bool { rest != .collapsed }
    /// The card grows by one line when the request has a can't-do line; both rests grow with it.
    var extra: CGFloat = 0
    var collapsedHeight: CGFloat { Self.collapsed + extra }
    var openHeight: CGFloat { Self.open + extra }
    /// The read rest's height (set from the screen and the list's length); nil when there's nothing to read.
    var readHeight: CGFloat?
    var maxHeight: CGFloat { readHeight ?? openHeight }
    /// Dragging or settling.
    private(set) var isMoving = false

    /// Called on every height change, outside SwiftUI (the map's ornaments use it).
    @ObservationIgnored var onHeightChange: ((CGFloat) -> Void)?

    @ObservationIgnored private var dragStart: CGFloat = SheetState.collapsed
    @ObservationIgnored private var settle: (from: CGFloat, to: CGFloat, start: CFTimeInterval, done: () -> Void)?
    @ObservationIgnored private var link: CADisplayLink?
    @ObservationIgnored private lazy var proxy = DisplayLinkProxy { [weak self] in self?.step() }

    func height(for r: Rest) -> CGFloat {
        switch r { case .collapsed: return collapsedHeight; case .open: return openHeight; case .read: return readHeight ?? openHeight }
    }
    var restingHeight: CGFloat { height(for: rest) }
    var progress: CGFloat { max(0, min(1, (height - collapsedHeight) / (openHeight - collapsedHeight))) }
    /// How far past the open state the sheet is, 0...1 (reveals "How Loop read it").
    var readProgress: CGFloat {
        guard let r = readHeight, r > openHeight else { return 0 }
        return max(0, min(1, (height - openHeight) / (r - openHeight)))
    }

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
        // 1:1 between the lowest and highest rest; past either end it resists (a third of the travel).
        let top = maxHeight, bottom = collapsedHeight
        let h: CGFloat
        if raw > top { h = top + (raw - top) / 3 }
        else if raw < bottom { h = bottom - (bottom - raw) / 3 }
        else { h = raw }
        setHeight(h)
    }

    /// Picks a state from where the finger would have carried the sheet, then settles there.
    func endDrag(predictedTranslation: CGFloat, animated: Bool, completion: @escaping (Bool) -> Void) {
        let predicted = dragStart - predictedTranslation
        var rests: [Rest] = [.collapsed, .open]
        if readHeight != nil { rests.append(.read) }
        let target = rests.min { abs(height(for: $0) - predicted) < abs(height(for: $1) - predicted) } ?? .collapsed
        settle(rest: target, animated: animated) { completion(target != .collapsed) }
    }

    // MARK: Settle

    func settle(open: Bool, animated: Bool, completion: @escaping () -> Void = {}) {
        settle(rest: open ? .open : .collapsed, animated: animated, completion: completion)
    }

    func settle(rest r: Rest, animated: Bool, completion: @escaping () -> Void = {}) {
        rest = r
        let target = height(for: r)
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

    /// Re-rest after the collapsed or read height changed (a can't-do line came or went).
    func refreshRest() {
        if !isMoving { setHeight(restingHeight) }
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
