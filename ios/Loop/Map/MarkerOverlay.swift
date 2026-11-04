import SwiftUI

/// Start dot, turnaround ring and mile marks, placed over the map from its projection.
/// Mid zoom and closer: mile marks and the START / TURN labels. Zoomed out: route only.
struct MarkerOverlay: View {
    let model: MainModel

    var body: some View {
        let showDetailMarks = model.zoom >= MapStyle.markerMinZoom
        ZStack(alignment: .topLeading) {
            if let detail = model.shownDetail {
                // Mile marks (the selected one is drawn by the selection layer instead).
                if showDetailMarks {
                    ForEach(detail.miles, id: \.mile) { m in
                        // A mile mark within 80 m of the start would sit on the start dot: skip it.
                        if m.mile != model.selectedMile, model.isDrawn(alongM: m.alongM),
                           m.point.distance(to: detail.start) > 80,
                           let p = model.screenPoint(m.point) {
                            MileMarkButton(mile: m.mile) { model.tapMile(m.mile) }
                                .position(p)
                        }
                    }
                }
                if let t = detail.turnaround, model.isDrawn(alongM: t.alongM), let p = model.screenPoint(t.point) {
                    TurnaroundRing(pulseID: model.pulseID)
                        .position(p)
                    if showDetailMarks { MapLabel(text: "Turn").position(x: p.x, y: p.y + 20) }
                }
            }
            // Every candidate starts at the same place, so the start shows as soon as a route does.
            if let start = model.shownDetail?.start ?? model.shown?.line.points.first,
               let p = model.screenPoint(start) {
                StartDot().position(p)
                if showDetailMarks { MapLabel(text: "Start").position(x: p.x, y: p.y - 20) }
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
                .typeStyle(.data)
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
