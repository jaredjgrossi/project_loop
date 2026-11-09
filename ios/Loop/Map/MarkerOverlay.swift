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
        let selection = SelectionLayout.compute(model, size: size)
        ZStack(alignment: .topLeading) {
            if let detail = model.shownDetail {
                // Mile marks (the selected one is drawn by the selection layer instead).
                if showDetailMarks {
                    let placements = model.markPlacements()
                    ForEach(detail.miles, id: \.mile) { m in
                        // Hidden when its circle would sit under the selected marker or the chip.
                        if m.mile != model.selectedMile, model.isDrawn(alongM: m.alongM),
                           let place = placements[m.mile], selection?.covers(place.center) != true {
                            MarkLeader(placement: place)
                            MileMarkButton(mile: m.mile) { model.tapMile(m.mile) }
                                .position(place.center)
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
/// the numbered label goes. On an out-and-back the outbound and return marks can land within a few
/// points of each other, so when two marks are within 24 pt each label moves off the line to the
/// left of its direction of travel: outbound on one side, return on the other.
struct MarkPlacement: Equatable {
    let anchor: CGPoint
    let center: CGPoint
    var isOffset: Bool { anchor != center }
}

extension MainModel {
    static let markCrowdingDistance: CGFloat = 24

    func markPlacements() -> [Int: MarkPlacement] {
        guard let detail = shownDetail else { return [:] }
        let line = detail.line
        var anchors: [Int: CGPoint] = [:]
        for m in detail.miles { anchors[m.mile] = screenPoint(m.point) }
        let startAnchor = screenPoint(detail.start)

        var out: [Int: MarkPlacement] = [:]
        for m in detail.miles {
            guard let a = anchors[m.mile] else { continue }
            let others = anchors.filter { $0.key != m.mile }.map(\.value) + [startAnchor].compactMap { $0 }
            let crowded = others.contains { hypot($0.x - a.x, $0.y - a.y) < Self.markCrowdingDistance }
            guard crowded,
                  let p0 = screenPoint(line.point(at: m.alongM - 15)),
                  let p1 = screenPoint(line.point(at: m.alongM + 15)) else {
                out[m.mile] = MarkPlacement(anchor: a, center: a)
                continue
            }
            let dx = p1.x - p0.x, dy = p1.y - p0.y
            let len = max(0.001, hypot(dx, dy))
            // Left of travel in screen space (y points down).
            let n = CGPoint(x: dy / len, y: -dx / len)
            let distance: CGFloat = m.mile == selectedMile ? Metrics.selectedMileMarker / 2 + 9 : 19
            out[m.mile] = MarkPlacement(anchor: a, center: CGPoint(x: a.x + n.x * distance, y: a.y + n.y * distance))
        }
        return out
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
