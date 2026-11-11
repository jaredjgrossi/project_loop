import SwiftUI

/// Elevation line, stretch bars in route colors, mile axis, turnaround tick and the cursor. No
/// legend (calm pass, 2026-11-09): the bars use the map's own route colours.
/// Scrubbing moves the cursor, ticks at each whole mile and selects the nearest mile.
struct ProfileStrip: View {
    let detail: RouteDetail
    /// The selected mile, if a mile mark was chosen (for VoiceOver's adjustable action).
    let selectedMile: Int?
    /// Where the cursor rests when not scrubbing: the selection's distance in miles.
    let cursorMile: Double?
    var onScrubStart: () -> Void = {}
    var onSelectMile: (Int) -> Void = { _ in }

    @State private var scrubMile: Double?
    @State private var lastWholeMile: Int?

    private let height: CGFloat = 64
    private let lineTop: CGFloat = 12, lineBottom: CGFloat = 34
    private let barY: CGFloat = 40, barH: CGFloat = 6

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            ZStack(alignment: .topLeading) {
                Canvas { ctx, size in draw(ctx, width: size.width) }
                axis(width: w)
            }
            .contentShape(Rectangle())
            .gesture(scrub(width: w))
        }
        .frame(height: height)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilitySummary)
        .accessibilityValue(cursorMile.map { String(format: "%.1f miles selected", $0) } ?? "")
        .accessibilityAdjustableAction { direction in
            let miles = detail.miles.map(\.mile)
            let current = selectedMile ?? 0
            switch direction {
            case .increment: if let next = miles.first(where: { $0 > current }) { onScrubStart(); onSelectMile(next) }
            case .decrement: if let prev = miles.last(where: { $0 < current }) { onScrubStart(); onSelectMile(prev) }
            @unknown default: break
            }
        }
    }

    private var totalMi: Double { detail.distanceMi }

    private func x(_ mile: Double, _ w: CGFloat) -> CGFloat { CGFloat(mile / totalMi) * w }

    private var elevationRange: (Double, Double) {
        let values = detail.profile.map(\.elevationM)
        let lo = values.min() ?? 0, hi = values.max() ?? 1
        return (lo, max(hi, lo + 1))
    }

    private func y(_ elevation: Double) -> CGFloat {
        let (lo, hi) = elevationRange
        return lineBottom - CGFloat((elevation - lo) / (hi - lo)) * (lineBottom - lineTop)
    }

    private var shownCursor: Double? { scrubMile ?? cursorMile }

    private func draw(_ ctx: GraphicsContext, width w: CGFloat) {
        let ink = Palette.ink.color
        // Elevation line, extended flat to the route's end.
        var path = Path()
        for (i, p) in detail.profile.enumerated() {
            let pt = CGPoint(x: x(p.mile, w), y: y(p.elevationM))
            if i == 0 { path.move(to: pt) } else { path.addLine(to: pt) }
        }
        if let last = detail.profile.last, last.mile < totalMi {
            path.addLine(to: CGPoint(x: w, y: y(last.elevationM)))
        }
        ctx.stroke(path, with: .color(ink), style: StrokeStyle(lineWidth: 1.5, lineJoin: .round))

        // Turnaround tick.
        if let t = detail.turnaround {
            let tx = x(t.alongMi, w)
            ctx.stroke(Path { $0.move(to: CGPoint(x: tx, y: lineBottom)); $0.addLine(to: CGPoint(x: tx, y: 52)) },
                       with: .color(Palette.inkMuted.color), lineWidth: 1)
        }

        // Bars from the map's merged runs at the strip's scale (under 16 pt joined). Each run
        // spans its full width, so same-kind neighbours never show a gap; a 1 pt gap separates
        // runs of different kinds. Path is dashed when it fits two full dashes, else solid.
        let runs = detail.stripRuns(width: Double(w))
        for (i, run) in runs.enumerated() {
            let x0 = x(run.fromMile, w), x1 = x(run.toMile, w)
            let gap: CGFloat = 1
            let left = x0 + (i > 0 ? gap / 2 : 0)
            let right = x1 - (i < runs.count - 1 ? gap / 2 : 0)
            let width = max(1.5, right - left)
            let color = Palette.drawColor(run.kind).color
            if run.dashed {
                var dash = Path()
                dash.move(to: CGPoint(x: left, y: barY + barH / 2))
                dash.addLine(to: CGPoint(x: left + width, y: barY + barH / 2))
                ctx.stroke(dash, with: .color(color), style: StrokeStyle(
                    lineWidth: barH, lineCap: .butt,
                    dash: [CGFloat(RouteDetail.stripDash.on), CGFloat(RouteDetail.stripDash.off)]))
            } else {
                ctx.fill(Path(roundedRect: CGRect(x: left, y: barY, width: width, height: barH),
                              cornerRadius: min(Metrics.radiusBar, width / 2)), with: .color(color))
            }
        }

        // Cursor.
        if let m = shownCursor {
            let cx = x(m, w)
            ctx.stroke(Path { $0.move(to: CGPoint(x: cx, y: 8)); $0.addLine(to: CGPoint(x: cx, y: 48)) },
                       with: .color(ink), lineWidth: 1.5)
            let cy = y(detail.elevation(atMile: m))
            let dot = Path(ellipseIn: CGRect(x: cx - 5, y: cy - 5, width: 10, height: 10))
            ctx.fill(dot, with: .color(ink))
            ctx.stroke(dot, with: .color(Palette.surfaceSheet.color), lineWidth: 2)
        }
    }

    private func axis(width w: CGFloat) -> some View {
        var marks: [(text: String, mile: Double, width: CGFloat, isTurn: Bool)] = [label("0", at: 0)]
        marks += detail.miles.map { label("\($0.mile)", at: $0.alongMi) }
        if let t = detail.turnaround { marks.append(label("turn", at: t.alongMi, isTurn: true)) }
        let placed = StripLabels.layout(marks.map { StripLabels.Label(text: $0.text, x: x($0.mile, w), width: $0.width, isTurn: $0.isTurn) },
                                        width: w)
        return ZStack(alignment: .topLeading) {
            ForEach(placed.filter { !$0.hidden }, id: \.text) { p in
                Text(p.text)
                    .typeStyle(.label)
                    .foregroundStyle(Palette.inkMuted.color)
                    .fixedSize()
                    .position(x: p.x, y: 57)
            }
        }
        .frame(width: w, height: height, alignment: .topLeading)
    }

    private func label(_ text: String, at mile: Double, isTurn: Bool = false) -> (text: String, mile: Double, width: CGFloat, isTurn: Bool) {
        let width = ceil((text as NSString).size(withAttributes: [.font: TypeStyle.label.uiFont]).width) + 1
        return (text, mile, width, isTurn)
    }

    private func scrub(width w: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { v in
                if scrubMile == nil { onScrubStart(); Haptics.prepareScrub() }
                let m = min(max(0, Double(v.location.x / w) * totalMi), totalMi)
                scrubMile = m
                let whole = Int(m.rounded(.down))
                if let last = lastWholeMile, whole != last { Haptics.mileTick() }
                lastWholeMile = whole
                if let nearest = nearestMile(to: m), nearest != selectedMile { onSelectMile(nearest) }
            }
            .onEnded { _ in
                scrubMile = nil
                lastWholeMile = nil
            }
    }

    private func nearestMile(to m: Double) -> Int? {
        detail.miles.min { abs($0.alongMi - m) < abs($1.alongMi - m) }?.mile
    }

    private var accessibilitySummary: String {
        let names = detail.stripRuns(width: 342).map(\.kind.legend)
        let lo = elevationRange.0, hi = elevationRange.1
        return "Route profile by mile, elevation \(detail.profileTrust.text). Between \(CardText.trimmed(lo.rounded())) and \(CardText.trimmed(hi.rounded())) metres up. Turnaround at mile \(detail.turnaround.map { String(format: "%.2f", $0.alongMi) } ?? "none"). \(names.joined(separator: ", ")). Swipe up or down to change the selected mile."
    }
}

/// The strip's axis labels (pure, so it's tested without a screen). Mile numbers sit on their
/// marks, inside the strip. "turn" sits on its tick unless it would cover a mile number: then it
/// slides clear (up to `maxShift`, so it still reads as the tick's label; the tick keeps the exact
/// spot), as the map pushes a label off its neighbours. With no room to slide, the mile number it
/// covers hides.
enum StripLabels {
    struct Label {
        let text: String
        let x: CGFloat
        let width: CGFloat
        let isTurn: Bool
    }

    struct Placed: Equatable {
        let text: String
        var x: CGFloat
        let width: CGFloat
        var hidden: Bool
    }

    static let gap: CGFloat = 4
    static let maxShift: CGFloat = 24

    static func layout(_ labels: [Label], width w: CGFloat) -> [Placed] {
        func inside(_ x: CGFloat, _ width: CGFloat) -> CGFloat { min(max(x, width / 2), w - width / 2) }
        var out = labels.map { Placed(text: $0.text, x: inside($0.x, $0.width), width: $0.width, hidden: false) }
        guard let ti = labels.firstIndex(where: \.isTurn) else { return out }
        let turn = out[ti]

        func hits(_ x: CGFloat) -> [Int] {
            out.indices.filter { i in
                i != ti && !out[i].hidden && abs(out[i].x - x) < (out[i].width + turn.width) / 2 + gap - 0.01
            }
        }
        let covered = hits(turn.x)
        guard !covered.isEmpty else { return out }

        // Just clear of each covered label, on either side; the nearest that fits and covers nothing.
        let candidates = covered.flatMap { i -> [CGFloat] in
            let reach = (out[i].width + turn.width) / 2 + gap
            return [out[i].x - reach, out[i].x + reach]
        }
        let slid = candidates
            .filter { abs($0 - turn.x) <= maxShift && $0 - turn.width / 2 >= 0 && $0 + turn.width / 2 <= w && hits($0).isEmpty }
            .min { abs($0 - turn.x) < abs($1 - turn.x) }
        if let x = slid {
            out[ti].x = x
        } else {
            for i in covered { out[i].hidden = true }
        }
        return out
    }
}
