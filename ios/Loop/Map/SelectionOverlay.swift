import SwiftUI

/// The selected mile: a 30 pt marker on the route with a short tick to the chip "Mile 1 · <stretch>".
struct SelectionOverlay: View {
    let model: MainModel

    var body: some View {
        GeometryReader { geo in
            if let mile = model.selectedMile, let detail = model.shownDetail,
               let mark = detail.miles.first(where: { $0.mile == mile }),
               let place = model.markPlacements()[mile] {
                let p = place.center
                let name = detail.stretch(atMile: mark.alongMi)?.name ?? ""
                let marker = Metrics.selectedMileMarker
                let tick: CGFloat = 7
                // The chip goes on the label's outer side (away from the line when the label is
                // pushed off it), flipping if there is no room.
                let leftRoom = p.x - marker / 2 - tick - 8
                let rightRoom = geo.size.width - (p.x + marker / 2 + tick) - 8
                let prefersRight = place.isOffset && place.center.x > place.anchor.x
                let right = prefersRight ? rightRoom >= 200 || leftRoom < 200 : leftRoom < 200
                ZStack(alignment: .topLeading) {
                    MarkLeader(placement: place)
                    Path { path in
                        let x0 = right ? p.x + marker / 2 : p.x - marker / 2 - tick
                        path.move(to: CGPoint(x: x0, y: p.y))
                        path.addLine(to: CGPoint(x: x0 + tick, y: p.y))
                    }
                    .stroke(Palette.ink.color, lineWidth: 1.5)

                    Text("\(mile)")
                        .typeStyle(.dataStrong)
                        .foregroundStyle(Palette.surfaceSheet.color)
                        .frame(width: marker, height: marker)
                        .background(Circle().fill(Palette.ink.color))
                        .overlay(Circle().strokeBorder(Palette.surfaceSheet.color, lineWidth: 2))
                        .position(p)
                        .accessibilityLabel("Mile \(mile) selected")

                    MileChip(mile: mile, stretchName: name, model: model)
                        .fixedSize()
                        .frame(width: max(0, right ? rightRoom : leftRoom), alignment: right ? .leading : .trailing)
                        .position(x: right ? p.x + marker / 2 + tick + max(0, rightRoom) / 2 : 8 + max(0, leftRoom) / 2,
                                  y: p.y)
                }
            }
        }
    }
}

/// "Mile 1 · East River Esplanade". With Apple imagery there, it shows an eye and opens Look Around.
/// Without it, the chip stays as a plain label (no eye, not a button): never an empty view.
struct MileChip: View {
    let mile: Int
    let stretchName: String
    let model: MainModel

    var body: some View {
        let title = CardText.mileChip(mile: mile, stretchName: stretchName)
        let availability = model.lookAroundAvailability(mile: mile)
        let hasImagery: Bool = { if case .available = availability { return true } else { return false } }()

        Button { model.openLookAround(mile: mile, title: title) } label: {
            HStack(spacing: 8) {
                Text(title)
                    .typeStyle(.label)
                    .foregroundStyle(Palette.ink.color)
                    .lineLimit(1)
                if hasImagery {
                    Image(systemName: "eye")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Palette.ink.color)
                        .transition(.opacity)
                }
            }
            .padding(.leading, 12)
            .padding(.trailing, hasImagery ? 10 : 12)
            .frame(height: 34)
            .background(Capsule().fill(Palette.surfaceSheet.color))
            .overlay(Capsule().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
            .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.10), radius: 7, y: 4)
            .frame(height: Metrics.minTap)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!hasImagery)
        .animation(Motion.textArrive, value: hasImagery)
        .accessibilityLabel(accessibilityText(availability))
    }

    private func accessibilityText(_ a: LookAroundAvailability) -> String {
        let place = "mile \(mile), \(stretchName)"
        switch a {
        case .available: return "Look at the street at \(place)"
        case .none: return "Mile \(mile), \(stretchName). No street imagery here."
        case .unknown: return "Mile \(mile), \(stretchName)"
        }
    }
}
