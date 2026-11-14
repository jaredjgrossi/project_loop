import QuartzCore
import SwiftUI

/// Start dot, turnaround ring and mile marks, placed over the map from its projection.
/// Mid zoom and closer: mile marks and the START / TURN labels. Zoomed out: route only.
struct MarkerOverlay: View {
    let model: MainModel

    var body: some View {
        GeometryReader { geo in content(size: geo.size) }
    }

    @ViewBuilder private func content(size: CGSize) -> some View {
        let showDetailMarks = model.zoom >= MapStyle.markerMinZoom
        // Marks that appear while the ink runs land like stamps (decision 052).
        let inking = model.inkIsMoving(now: CACurrentMediaTime())
        let selection = SelectionLayout.compute(model, size: size)
        let placements = showDetailMarks ? model.markPlacements() : [:]
        // START and TURN go beside their markers, away from the line and the mile marks.
        let labels = showDetailMarks ? model.endLabelCenters(marks: placements) : (start: nil, turn: nil)
        ZStack(alignment: .topLeading) {
            if let detail = model.shownDetail {
                // Mile marks (the selected one is drawn by the selection layer instead).
                if showDetailMarks {
                    ForEach(detail.miles, id: \.mile) { m in
                        // Hidden when its circle would sit under the selected marker or the chip.
                        if m.mile != model.selectedMile, model.isDrawn(alongM: m.alongM),
                           let place = placements[m.mile], selection?.covers(place.center) != true {
                            MarkLeader(placement: place)
                            MileMarkButton(mile: m.mile) { model.tapMile(m.mile) }
                                .modifier(StampIn(active: inking))
                                .position(place.center)
                        }
                    }
                }
                if let t = detail.turnaround, model.isDrawn(alongM: t.alongM), let p = model.screenPoint(t.point) {
                    TurnaroundRing(pulseID: model.pulseID)
                        .position(p)
                    if showDetailMarks, let c = labels.turn { MapLabel(text: "Turn").modifier(StampIn(active: inking)).position(c) }
                }
            }
            // Every candidate starts at the same place, so the start shows as soon as a route does.
            if let start = model.shownDetail?.start ?? model.shown?.line.points.first,
               let p = model.screenPoint(start) {
                StartDot().position(p)
                if showDetailMarks { MapLabel(text: "Start").position(labels.start ?? CGPoint(x: p.x, y: p.y - 20)) }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

struct StartDot: View {
    var body: some View {
        Circle()
            .fill(Palette.accentStart.color)
            .overlay(Circle().strokeBorder(Palette.routeCasing.color, lineWidth: 2.5))
            .frame(width: 16, height: 16)
            .accessibilityElement()
            .accessibilityLabel("Start and finish")
    }
}

/// Ring at the turnaround. When `pulseID` changes it sends out one ring (the settle beat).
struct TurnaroundRing: View {
    let pulseID: Int
    @State private var pulse = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            Circle()
                .stroke(Palette.routeWater.color, lineWidth: 2)
                .frame(width: 16, height: 16)
                .scaleEffect(pulse ? 3.4 : 1)
                .opacity(pulse ? 0 : (pulseID > 0 ? 0.9 : 0))
            Circle()
                .fill(Palette.surfaceSheet.color)
                .overlay(Circle().strokeBorder(Palette.ink.color, lineWidth: 2.5))
                .frame(width: 16, height: 16)
        }
        .frame(width: 60, height: 60)
        .allowsHitTesting(false)
        .accessibilityElement()
        .accessibilityLabel("Turnaround")
        .onChange(of: pulseID) { _, _ in
            guard !reduceMotion else { return }
            pulse = false
            withAnimation(.timingCurve(0.2, 0, 0, 1, duration: 0.9)) { pulse = true }
        }
    }
}

/// A small numbered mile mark; 44 pt tap target.
struct MileMarkButton: View {
    let mile: Int
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text("\(mile)")
                .typeStyle(.label)
                .foregroundStyle(Palette.ink.color)
                .frame(width: 20, height: 20)
                .background(Circle().fill(Palette.surfaceSheet.color))
                .overlay(Circle().strokeBorder(Palette.lineControl.color, lineWidth: 1))
                .frame(width: Metrics.minTap, height: Metrics.minTap)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Mile \(mile)")
        .accessibilityHint("Shows this mile on the profile")
    }
}

struct MapLabel: View {
    let text: String
    var body: some View {
        Text(text)
            .typeStyle(.mapLabel)
            .foregroundStyle(Palette.mapLabelLand.color)
            .shadow(color: Palette.mapLand.color, radius: 1.5)
            .shadow(color: Palette.mapLand.color, radius: 1.5)
            .fixedSize()
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }
}

/// Where a mile mark sits on screen. `anchor` is the exact point on the route; `center` is where
/// the numbered mark goes: always beside the line, never on it, on whichever side has the most room
/// (an out-and-back's return leg, the start and other marks count as in the way). A leader joins them.
struct MarkPlacement: Equatable {
    let anchor: CGPoint
    let center: CGPoint
    var isOffset: Bool { anchor != center }
}

/// Puts a label or mark beside its point on the side away from the route line, flipping or turning
/// to a diagonal when the first choice would touch the line or another mark.
enum LabelPlacer {
    /// The shortest distance from a rectangle to a polyline (0 when they touch).
    static func distance(from r: CGRect, to line: [CGPoint]) -> CGFloat {
        guard line.count >= 2 else { return .greatestFiniteMagnitude }
        var best = CGFloat.greatestFiniteMagnitude
        for i in 1..<line.count {
            best = min(best, distance(from: r, a: line[i - 1], b: line[i]))
            if best == 0 { return 0 }
        }
        return best
    }

    static func distance(from r: CGRect, a: CGPoint, b: CGPoint) -> CGFloat {
        if r.contains(a) || r.contains(b) { return 0 }
        let corners = [CGPoint(x: r.minX, y: r.minY), CGPoint(x: r.maxX, y: r.minY),
                       CGPoint(x: r.maxX, y: r.maxY), CGPoint(x: r.minX, y: r.maxY)]
        for k in 0..<4 where segmentsCross(a, b, corners[k], corners[(k + 1) % 4]) { return 0 }
        var best = corners.map { pointSegment($0, a, b) }.min()!
        for p in [a, b] {
            let dx = max(r.minX - p.x, 0, p.x - r.maxX), dy = max(r.minY - p.y, 0, p.y - r.maxY)
            best = min(best, hypot(dx, dy))
        }
        return best
    }

    static func pointSegment(_ p: CGPoint, _ a: CGPoint, _ b: CGPoint) -> CGFloat {
        let dx = b.x - a.x, dy = b.y - a.y, l2 = dx * dx + dy * dy
        let t = l2 > 0 ? max(0, min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l2)) : 0
        return hypot(p.x - (a.x + dx * t), p.y - (a.y + dy * t))
    }

    private static func segmentsCross(_ p1: CGPoint, _ p2: CGPoint, _ q1: CGPoint, _ q2: CGPoint) -> Bool {
        func cross(_ o: CGPoint, _ a: CGPoint, _ b: CGPoint) -> CGFloat { (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x) }
        let d1 = cross(q1, q2, p1), d2 = cross(q1, q2, p2), d3 = cross(p1, p2, q1), d4 = cross(p1, p2, q2)
        return (d1 > 0) != (d2 > 0) && (d3 > 0) != (d4 > 0)
    }

    /// The center for a box of `size` beside `anchor`, `gap` points out, trying `directions` in
    /// order: the first with at least `clearance` points from the line and the obstacles wins,
    /// else the one with the most room.
    static func place(size: CGSize, anchor: CGPoint, gap: CGFloat, directions: [CGVector],
                      line: [CGPoint], obstacles: [CGRect], clearance: CGFloat = 4) -> CGPoint {
        var best: (CGPoint, CGFloat)?
        for d in directions {
            let len = max(0.001, hypot(d.dx, d.dy))
            let u = CGVector(dx: d.dx / len, dy: d.dy / len)
            let reach = gap + abs(u.dx) * size.width / 2 + abs(u.dy) * size.height / 2
            let c = CGPoint(x: anchor.x + u.dx * reach, y: anchor.y + u.dy * reach)
            let r = CGRect(x: c.x - size.width / 2, y: c.y - size.height / 2, width: size.width, height: size.height)
            var room = distance(from: r, to: line)
            for o in obstacles { room = min(room, o.intersects(r) ? 0 : distance(from: r, to: [CGPoint(x: o.minX, y: o.midY), CGPoint(x: o.maxX, y: o.midY)])) }
            if room >= clearance { return c }
            if best == nil || room > best!.1 { best = (c, room) }
        }
        return best?.0 ?? anchor
    }

    /// Up, down, left, right, then the diagonals: the order START tries.
    static let aboveFirst: [CGVector] = [.init(dx: 0, dy: -1), .init(dx: 0, dy: 1), .init(dx: -1, dy: 0), .init(dx: 1, dy: 0),
                                         .init(dx: -1, dy: -1), .init(dx: 1, dy: -1), .init(dx: -1, dy: 1), .init(dx: 1, dy: 1)]
    /// Down first: the order TURN tries.
    static let belowFirst: [CGVector] = [.init(dx: 0, dy: 1), .init(dx: 0, dy: -1), .init(dx: 1, dy: 0), .init(dx: -1, dy: 0),
                                         .init(dx: 1, dy: 1), .init(dx: -1, dy: 1), .init(dx: 1, dy: -1), .init(dx: -1, dy: -1)]

    /// A map label's box (map-label style: 11 pt capitals, 0.22 em tracking).
    static func labelSize(_ text: String) -> CGSize { CGSize(width: CGFloat(text.count) * 10 + 4, height: 14) }
}

extension MainModel {
    /// The shown route on screen, simplified to a few metres, for keeping marks off the line.
    func routeScreenLine() -> [CGPoint] {
        guard let c = shown else { return [] }
        return DisplayLine.simplify(c.line.points, tolerance: 4).compactMap { screenPoint(c.line.points[$0]) }
    }

    /// Mile marks beside the line (with a leader), each on the side with room.
    func markPlacements() -> [Int: MarkPlacement] {
        guard let detail = shownDetail else { return [:] }
        let line = detail.line
        let screenLine = routeScreenLine()
        var obstacles: [CGRect] = []
        if let s = screenPoint(detail.start) { obstacles.append(CGRect(x: s.x - 9, y: s.y - 9, width: 18, height: 18)) }
        if let t = detail.turnaround, let p = screenPoint(t.point) { obstacles.append(CGRect(x: p.x - 9, y: p.y - 9, width: 18, height: 18)) }

        var out: [Int: MarkPlacement] = [:]
        for m in detail.miles {
            guard let a = screenPoint(m.point) else { continue }
            let side = m.mile == selectedMile ? Metrics.selectedMileMarker : 20
            var directions: [CGVector] = [.init(dx: 0, dy: -1), .init(dx: 0, dy: 1)]
            if let p0 = screenPoint(line.point(at: m.alongM - 15)), let p1 = screenPoint(line.point(at: m.alongM + 15)) {
                // Left of travel first (screen y points down), then right, then the diagonals.
                let dx = p1.x - p0.x, dy = p1.y - p0.y
                let n = CGVector(dx: dy, dy: -dx), t = CGVector(dx: dx, dy: dy)
                directions = [n, CGVector(dx: -n.dx, dy: -n.dy),
                              CGVector(dx: n.dx + t.dx, dy: n.dy + t.dy), CGVector(dx: n.dx - t.dx, dy: n.dy - t.dy),
                              CGVector(dx: -n.dx + t.dx, dy: -n.dy + t.dy), CGVector(dx: -n.dx - t.dx, dy: -n.dy - t.dy)]
            }
            let c = LabelPlacer.place(size: CGSize(width: side, height: side), anchor: a, gap: 8,
                                      directions: directions, line: screenLine, obstacles: obstacles)
            out[m.mile] = MarkPlacement(anchor: a, center: c)
            obstacles.append(CGRect(x: c.x - side / 2, y: c.y - side / 2, width: side, height: side))
        }
        return out
    }

    /// START and TURN beside their markers, away from the line and the mile marks.
    func endLabelCenters(marks: [Int: MarkPlacement]) -> (start: CGPoint?, turn: CGPoint?) {
        guard let detail = shownDetail else { return (nil, nil) }
        let screenLine = routeScreenLine()
        var obstacles = marks.values.map { CGRect(x: $0.center.x - 11, y: $0.center.y - 11, width: 22, height: 22) }
        let s = screenPoint(detail.start)
        let t = detail.turnaround.flatMap { screenPoint($0.point) }
        if let s { obstacles.append(CGRect(x: s.x - 9, y: s.y - 9, width: 18, height: 18)) }
        if let t { obstacles.append(CGRect(x: t.x - 9, y: t.y - 9, width: 18, height: 18)) }
        let startCenter = s.map {
            LabelPlacer.place(size: LabelPlacer.labelSize("Start"), anchor: $0, gap: 11,
                              directions: LabelPlacer.aboveFirst, line: screenLine, obstacles: obstacles)
        }
        if let c = startCenter {
            let size = LabelPlacer.labelSize("Start")
            obstacles.append(CGRect(x: c.x - size.width / 2, y: c.y - size.height / 2, width: size.width, height: size.height))
        }
        let turnCenter = t.map {
            LabelPlacer.place(size: LabelPlacer.labelSize("Turn"), anchor: $0, gap: 11,
                              directions: LabelPlacer.belowFirst, line: screenLine, obstacles: obstacles)
        }
        return (startCenter, turnCenter)
    }
}

/// The short leader from the exact route point to a label pushed off the line, with a dot on the route.
struct MarkLeader: View {
    let placement: MarkPlacement
    var body: some View {
        if placement.isOffset {
            ZStack(alignment: .topLeading) {
                Path { p in p.move(to: placement.anchor); p.addLine(to: placement.center) }
                    .stroke(Palette.ink.color, lineWidth: 1)
                Circle().fill(Palette.ink.color)
                    .overlay(Circle().strokeBorder(Palette.routeCasing.color, lineWidth: 1))
                    .frame(width: 6, height: 6)
                    .position(placement.anchor)
            }
            .allowsHitTesting(false)
            .accessibilityHidden(true)
        }
    }
}
