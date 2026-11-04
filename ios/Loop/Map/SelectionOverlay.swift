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

/// "Mile 1 · East River Esplanade". Opens Look Around when Apple has imagery there.
struct MileChip: View {
    let mile: Int
    let stretchName: String
    let model: MainModel

    var body: some View {
        HStack(spacing: 8) {
            Text(CardText.mileChip(mile: mile, stretchName: stretchName))
                .typeStyle(.label)
                .foregroundStyle(Palette.ink.color)
                .lineLimit(1)
        }
        .padding(.leading, 12)
        .padding(.trailing, 12)
        .frame(height: 34)
        .background(Capsule().fill(Palette.surfaceSheet.color))
        .overlay(Capsule().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
        .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.10), radius: 7, y: 4)
        .accessibilityElement(children: .combine)
    }
}
