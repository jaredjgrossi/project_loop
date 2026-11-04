import SwiftUI

/// The selected mile: a 30 pt marker on the route with a short tick to the chip "Mile 1 · <stretch>".
struct SelectionOverlay: View {
    let model: MainModel

    var body: some View {
        GeometryReader { geo in
            if let mile = model.selectedMile, let detail = model.shownDetail,
               let mark = detail.miles.first(where: { $0.mile == mile }),
               let p = model.screenPoint(mark.point) {
                let name = detail.stretch(atMile: mark.alongMi)?.name ?? ""
                let marker = Metrics.selectedMileMarker
                let tick: CGFloat = 7
                // Chip sits left of the marker; if there's no room, it flips to the right.
                let leftRoom = p.x - marker / 2 - tick - 8
                let flip = leftRoom < 200
                ZStack(alignment: .topLeading) {
                    Path { path in
                        let y = p.y
                        let x0 = flip ? p.x + marker / 2 : p.x - marker / 2 - tick
                        path.move(to: CGPoint(x: x0, y: y))
                        path.addLine(to: CGPoint(x: x0 + tick, y: y))
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
                        .frame(width: flip ? geo.size.width - (p.x + marker / 2 + tick) - 8 : max(0, leftRoom),
                               alignment: flip ? .leading : .trailing)
                        .position(x: flip ? (p.x + marker / 2 + tick + geo.size.width - 8) / 2 : 8 + max(0, leftRoom) / 2,
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
