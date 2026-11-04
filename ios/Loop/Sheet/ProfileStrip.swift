import SwiftUI

/// Elevation line, stretch bars in route colors, mile axis, turnaround tick and the cursor.
/// Scrubbing moves the cursor, ticks at each whole mile and selects the nearest mile.
struct ProfileStrip: View {
    let detail: RouteDetail
    /// The selected mile (cursor rests here when not scrubbing).
    let selectedMile: Int?
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
                legend(width: w)
                axis(width: w)
            }
            .contentShape(Rectangle())
            .gesture(scrub(width: w))
        }
        .frame(height: height)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilitySummary)
        .accessibilityValue(selectedMile.map { "Mile \($0) selected" } ?? "")
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

    private var cursorMile: Double? {
        if let scrubMile { return scrubMile }
        guard let m = selectedMile, let mark = detail.miles.first(where: { $0.mile == m }) else { return nil }
        return mark.alongMi
    }

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

        // Bars from the same merged runs the map draws (pieces, under 20 m joined). Path is a
        // dashed bar in route-path, like the map, so color is never the only cue.
        for run in kindRuns() {
            let x0 = x(run.from, w), x1 = x(run.to, w)
            let gap: CGFloat = 1
            let left = x0 + (run.from > 0 ? gap : 0)
            let right = x1 - (run.to < totalMi ? gap : 0)
            let width = max(1.5, right - left)
            let color = Palette.drawColor(run.kind).color
            if run.kind == .path {
                var dash = Path()
                dash.move(to: CGPoint(x: left, y: barY + barH / 2))
                dash.addLine(to: CGPoint(x: left + width, y: barY + barH / 2))
                ctx.stroke(dash, with: .color(color), style: StrokeStyle(lineWidth: barH, lineCap: .butt, dash: [4, 2.5]))
            } else {
                ctx.fill(Path(roundedRect: CGRect(x: left, y: barY, width: width, height: barH),
                              cornerRadius: min(Metrics.radiusBar, width / 2)), with: .color(color))
            }
        }

        // Cursor.
        if let m = cursorMile {
            let cx = x(m, w)
            ctx.stroke(Path { $0.move(to: CGPoint(x: cx, y: 8)); $0.addLine(to: CGPoint(x: cx, y: 48)) },
                       with: .color(ink), lineWidth: 1.5)
            let cy = y(detail.elevation(atMile: m))
            let dot = Path(ellipseIn: CGRect(x: cx - 5, y: cy - 5, width: 10, height: 10))
            ctx.fill(dot, with: .color(ink))
            ctx.stroke(dot, with: .color(Palette.surfaceSheet.color), lineWidth: 2)
        }
    }

    private struct KindRun { let kind: DrawKind; let from: Double; let to: Double }

    private func kindRuns() -> [KindRun] {
        let len = detail.line.length
        guard len > 0 else { return [] }
        return detail.drawn.map {
            KindRun(kind: $0.kind, from: $0.fromM / len * totalMi, to: $0.toM / len * totalMi)
        }
    }

    /// Legend: only the kinds this route draws ("path" appears only when it has path).
    private var kindsPresent: [DrawKind] {
        DrawKind.allCases.filter { k in detail.drawn.contains { $0.kind == k } }
    }

    private func legend(width w: CGFloat) -> some View {
        HStack(spacing: 10) {
            ForEach(kindsPresent, id: \.self) { k in
                HStack(spacing: 4) {
                    LegendSwatch(kind: k)
                    Text(k.legend).typeStyle(.data).foregroundStyle(Palette.inkMuted.color)
                }
            }
        }
        .frame(width: w, alignment: .trailing)
        .offset(y: -2)
    }

    private func axis(width w: CGFloat) -> some View {
        var marks: [(String, Double)] = [("0", 0)]
        marks += detail.miles.map { ("\($0.mile)", $0.alongMi) }
        if let t = detail.turnaround { marks.append(("turn", t.alongMi)) }
        return ZStack(alignment: .topLeading) {
            ForEach(marks, id: \.0) { label, mile in
                Text(label)
                    .typeStyle(.data)
                    .foregroundStyle(Palette.inkMuted.color)
                    .fixedSize()
                    .position(x: labelX(mile, label: label, w), y: 57)
            }
        }
        .frame(width: w, height: height, alignment: .topLeading)
    }

    private func labelX(_ mile: Double, label: String, _ w: CGFloat) -> CGFloat {
        let half = CGFloat(label.count) * 3.3
        return min(max(x(mile, w), half), w - half)
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
        let names = kindRuns().map(\.kind.legend)
        let lo = elevationRange.0, hi = elevationRange.1
        return "Route profile by mile, elevation \(detail.profileTrust.text). Between \(CardText.trimmed(lo.rounded())) and \(CardText.trimmed(hi.rounded())) metres up. Turnaround at mile \(detail.turnaround.map { String(format: "%.2f", $0.alongMi) } ?? "none"). \(names.joined(separator: ", ")). Swipe up or down to change the selected mile."
    }
}

/// A short bar in the run's color: solid for waterfront and street, dashed for path.
private struct LegendSwatch: View {
    let kind: DrawKind
    var body: some View {
        Canvas { ctx, size in
            var line = Path()
            line.move(to: CGPoint(x: 0, y: size.height / 2))
            line.addLine(to: CGPoint(x: size.width, y: size.height / 2))
            let style = kind == .path
                ? StrokeStyle(lineWidth: 4, lineCap: .butt, dash: [4, 2.5])
                : StrokeStyle(lineWidth: 4, lineCap: .round)
            ctx.stroke(line, with: .color(Palette.drawColor(kind).color), style: style)
        }
        .frame(width: kind == .path ? 14.5 : 12, height: 8)
    }
}
