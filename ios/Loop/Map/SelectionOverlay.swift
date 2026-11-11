import SwiftUI

/// Where the selection marker and its chip go. Shared with the marker layer so mile labels that
/// would sit under either are hidden. A tap on the line gets a small dot; a mile gets the 30 pt
/// numbered marker (pushed off the line on an out-and-back, like the other mile labels).
struct SelectionLayout {
    let mile: Int?
    let place: MarkPlacement
    let title: String
    let hasLookAround: Bool
    let side: Side
    let markerRect: CGRect
    let chipRect: CGRect
    /// True when the chip was lifted to stay above the sheet.
    let chipLifted: Bool

    static let tick: CGFloat = 7
    static let dot: CGFloat = 10

    @MainActor
    static func compute(_ model: MainModel, size: CGSize) -> SelectionLayout? {
        guard let sel = model.selection, model.shownDetail != nil,
              let mi = model.selectionAlongMi, let point = model.selectionPoint else { return nil }
        let place: MarkPlacement
        if let m = sel.mile, let p = model.markPlacements()[m] {
            place = p
        } else if let p = model.screenPoint(point) {
            place = MarkPlacement(anchor: p, center: p)
        } else { return nil }
        let p = place.center
        let marker = sel.mile != nil ? Metrics.selectedMileMarker : dot
        let hasLookAround: Bool = { if case .available = model.selectionLookAround { return true } else { return false } }()
        let title = CardText.selectionChip(stretchName: model.selectionStretchName, alongMi: mi, lookAround: hasLookAround)

        let textWidth = (title as NSString).size(withAttributes: [.font: TypeStyle.label.uiFont]).width
        let chipWidth = ceil(textWidth) + 12 + (hasLookAround ? 8 + 18 + 10 : 12)
        let leftRoom = p.x - marker / 2 - tick - 8
        let rightRoom = size.width - (p.x + marker / 2 + tick) - 8
        // Beside the marker when it fits (outer side of a pushed-off mile label first, else left),
        // otherwise above it, or below when the header is in the way. Never on top of the marker.
        let prefersRight = place.isOffset && place.center.x > place.anchor.x
        let side: Side
        if prefersRight && rightRoom >= chipWidth { side = .right }
        else if leftRoom >= chipWidth { side = .left }
        else if rightRoom >= chipWidth { side = .right }
        else if p.y - marker / 2 - tick - 34 >= model.headerBottom + 8 { side = .above }
        else { side = .below }
        var chip: CGRect
        switch side {
        case .left: chip = CGRect(x: p.x - marker / 2 - tick - chipWidth, y: p.y - 17, width: chipWidth, height: 34)
        case .right: chip = CGRect(x: p.x + marker / 2 + tick, y: p.y - 17, width: chipWidth, height: 34)
        case .above: chip = CGRect(x: p.x - chipWidth / 2, y: p.y - marker / 2 - tick - 34, width: chipWidth, height: 34)
        case .below: chip = CGRect(x: p.x - chipWidth / 2, y: p.y + marker / 2 + tick, width: chipWidth, height: 34)
        }
        chip.origin.x = min(max(8, chip.origin.x), size.width - 8 - chipWidth)
        // The chip always shows above the sheet, whatever state the sheet is in.
        let lowestTop = size.height - model.sheet.height - 8 - 34
        let lifted = chip.origin.y > lowestTop
        if lifted { chip.origin.y = lowestTop }
        return SelectionLayout(
            mile: sel.mile, place: place, title: title, hasLookAround: hasLookAround, side: side,
            markerRect: CGRect(x: p.x - marker / 2, y: p.y - marker / 2, width: marker, height: marker),
            chipRect: chip, chipLifted: lifted)
    }

    enum Side { case left, right, above, below }

    /// The tick runs from the marker's edge to the chip's nearest edge.
    var tickEnds: (CGPoint, CGPoint) {
        let m = markerRect, c = chipRect
        switch side {
        case .left: return (CGPoint(x: m.minX, y: m.midY), CGPoint(x: c.maxX, y: c.midY))
        case .right: return (CGPoint(x: m.maxX, y: m.midY), CGPoint(x: c.minX, y: c.midY))
        case .above: return (CGPoint(x: m.midX, y: m.minY), CGPoint(x: min(max(m.midX, c.minX + 17), c.maxX - 17), y: c.maxY))
        case .below: return (CGPoint(x: m.midX, y: m.maxY), CGPoint(x: min(max(m.midX, c.minX + 17), c.maxX - 17), y: c.minY))
        }
    }

    /// Would a mile label circle at `center` overlap the marker or the chip?
    func covers(_ center: CGPoint, radius: CGFloat = 10) -> Bool {
        let circle = CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2)
            .insetBy(dx: -2, dy: -2)
        return circle.intersects(markerRect) || circle.intersects(chipRect)
    }
}

/// The selection: dot or mile marker on the route, a short tick, and the chip.
struct SelectionOverlay: View {
    let model: MainModel

    var body: some View {
        GeometryReader { geo in
            if let layout = SelectionLayout.compute(model, size: geo.size) {
                let p = layout.place.center
                let chip = layout.chipRect
                ZStack(alignment: .topLeading) {
                    MarkLeader(placement: layout.place)
                    // Tick from the marker's edge to the chip's near edge.
                    Path { path in
                        let (a, b) = layout.tickEnds
                        path.move(to: a)
                        path.addLine(to: b)
                    }
                    .stroke(Palette.ink.color, lineWidth: 1.5)

                    if let mile = layout.mile {
                        Text("\(mile)")
                            .typeStyle(.stretchName)
                            .foregroundStyle(Palette.surfaceSheet.color)
                            .frame(width: Metrics.selectedMileMarker, height: Metrics.selectedMileMarker)
                            .background(Circle().fill(Palette.ink.color))
                            .overlay(Circle().strokeBorder(Palette.surfaceSheet.color, lineWidth: 2))
                            .position(p)
                            .accessibilityLabel("Mile \(mile) selected")
                    } else {
                        Circle()
                            .fill(Palette.ink.color)
                            .overlay(Circle().strokeBorder(Palette.surfaceSheet.color, lineWidth: 2))
                            .frame(width: SelectionLayout.dot, height: SelectionLayout.dot)
                            .position(p)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                    }

                    SelectionChip(title: layout.title, hasLookAround: layout.hasLookAround, model: model)
                        .frame(width: chip.width)
                        .position(x: chip.midX, y: chip.midY)
                }
            }
        }
    }
}

/// "East River Esplanade · 1.0 mi · Look around" with binoculars; opens Look Around full screen.
/// Where Apple has no scene: stretch and distance only, and not a button.
struct SelectionChip: View {
    let title: String
    let hasLookAround: Bool
    let model: MainModel

    var body: some View {
        Button { model.openLookAround() } label: {
            HStack(spacing: 8) {
                Text(title)
                    .typeStyle(.label)
                    .foregroundStyle(Palette.ink.color)
                    .lineLimit(1)
                    .fixedSize()
                if hasLookAround {
                    Image(systemName: "binoculars")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Palette.ink.color)
                        .frame(width: 18)
                        .transition(.opacity)
                }
            }
            .padding(.leading, 12)
            .padding(.trailing, hasLookAround ? 10 : 12)
            .frame(height: 34)
            .background(Capsule().fill(Palette.surfaceSheet.color))
            .overlay(Capsule().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
            .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.10), radius: 7, y: 4)
            .frame(height: Metrics.minTap)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!hasLookAround)
        .animation(Motion.textArrive, value: hasLookAround)
        .accessibilityLabel(hasLookAround ? "Look around at \(title.replacingOccurrences(of: " · Look around", with: ""))" : title)
    }
}
