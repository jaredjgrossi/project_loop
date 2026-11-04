import SwiftUI

/// Where the selected marker and its chip go. Shared with the marker layer so mile labels that
/// would sit under either are hidden.
struct SelectionLayout {
    let mile: Int
    let place: MarkPlacement
    let title: String
    let stretchName: String
    let chipOnRight: Bool
    let leftRoom: CGFloat
    let rightRoom: CGFloat
    let markerRect: CGRect
    let chipRect: CGRect

    static let tick: CGFloat = 7

    @MainActor
    static func compute(_ model: MainModel, size: CGSize) -> SelectionLayout? {
        guard let mile = model.selectedMile, let detail = model.shownDetail,
              let mark = detail.miles.first(where: { $0.mile == mile }),
              let place = model.markPlacements()[mile] else { return nil }
        let p = place.center
        let marker = Metrics.selectedMileMarker
        let name = detail.stretch(atMile: mark.alongMi)?.name ?? ""
        let title = CardText.mileChip(mile: mile, stretchName: name)
        let leftRoom = p.x - marker / 2 - tick - 8
        let rightRoom = size.width - (p.x + marker / 2 + tick) - 8
        // The chip goes on the label's outer side (away from the line when the label is pushed
        // off it), flipping if there is no room.
        let prefersRight = place.isOffset && place.center.x > place.anchor.x
        let right = prefersRight ? rightRoom >= 200 || leftRoom < 200 : leftRoom < 200
        let hasEye: Bool = { if case .available = model.lookAroundAvailability(mile: mile) { return true } else { return false } }()
        let textWidth = (title as NSString).size(withAttributes: [.font: TypeStyle.label.uiFont]).width
        let chipWidth = ceil(textWidth) + 12 + (hasEye ? 8 + 16 + 10 : 12)
        let chipX = right ? p.x + marker / 2 + tick : p.x - marker / 2 - tick - chipWidth
        return SelectionLayout(
            mile: mile, place: place, title: title, stretchName: name, chipOnRight: right,
            leftRoom: leftRoom, rightRoom: rightRoom,
            markerRect: CGRect(x: p.x - marker / 2, y: p.y - marker / 2, width: marker, height: marker),
            chipRect: CGRect(x: chipX, y: p.y - 17, width: chipWidth, height: 34))
    }

    /// Would a mile label circle at `center` overlap the marker or the chip?
    func covers(_ center: CGPoint, radius: CGFloat = 10) -> Bool {
        let circle = CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2)
            .insetBy(dx: -2, dy: -2)
        return circle.intersects(markerRect) || circle.intersects(chipRect)
    }
}

/// The selected mile: a 30 pt marker on the route with a short tick to the chip "Mile 1 · <stretch>".
struct SelectionOverlay: View {
    let model: MainModel

    var body: some View {
        GeometryReader { geo in
            if let layout = SelectionLayout.compute(model, size: geo.size) {
                let p = layout.place.center
                let marker = Metrics.selectedMileMarker
                let tick = SelectionLayout.tick
                let right = layout.chipOnRight
                ZStack(alignment: .topLeading) {
                    MarkLeader(placement: layout.place)
                    Path { path in
                        let x0 = right ? p.x + marker / 2 : p.x - marker / 2 - tick
                        path.move(to: CGPoint(x: x0, y: p.y))
                        path.addLine(to: CGPoint(x: x0 + tick, y: p.y))
                    }
                    .stroke(Palette.ink.color, lineWidth: 1.5)

                    Text("\(layout.mile)")
                        .typeStyle(.dataStrong)
                        .foregroundStyle(Palette.surfaceSheet.color)
                        .frame(width: marker, height: marker)
                        .background(Circle().fill(Palette.ink.color))
                        .overlay(Circle().strokeBorder(Palette.surfaceSheet.color, lineWidth: 2))
                        .position(p)
                        .accessibilityLabel("Mile \(layout.mile) selected")

                    MileChip(mile: layout.mile, stretchName: layout.stretchName, model: model)
                        .fixedSize()
                        .frame(width: max(0, right ? layout.rightRoom : layout.leftRoom), alignment: right ? .leading : .trailing)
                        .position(x: right ? p.x + marker / 2 + tick + max(0, layout.rightRoom) / 2 : 8 + max(0, layout.leftRoom) / 2,
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
