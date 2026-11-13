import SwiftUI

/// The pill on the card that opens the step-by-step list.
struct DirectionsButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: "list.bullet")
                    .font(.system(size: 12, weight: .semibold))
                Text("Directions")
                    .typeStyle(.label)
            }
            .foregroundStyle(Palette.inkSoft.color)
            .padding(.horizontal, 12)
            .frame(height: 32)
            .background(Capsule().fill(Palette.surfaceSunken.color))
            .frame(minHeight: Metrics.minTap)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Directions")
        .accessibilityHint("Lists the route street by street")
    }
}

/// Step by step: where to start, each stretch with its length, the turnaround, the finish. Street
/// names are listed (OpenStreetMap and Loop's corridor catalog) and distances are measured along the
/// route; the footer says so, since every fact carries its source.
struct DirectionsSheet: View {
    let name: String
    let distanceMi: Double
    let steps: [DirectionStep]
    let onDone: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Directions")
                        .typeStyle(.eyebrow)
                        .foregroundStyle(Palette.inkMuted.color)
                    Text(name.isEmpty ? "\(CardText.distance(distanceMi)) mi" : CardText.nameLine(name))
                        .typeStyle(.bodyStrong)
                        .foregroundStyle(Palette.ink.color)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Button(action: onDone) {
                    Image(systemName: "xmark")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(Palette.inkMuted.color)
                        .frame(width: 30, height: 30)
                        .background(Circle().fill(Palette.surfaceSunken.color))
                        .frame(width: Metrics.minTap, height: Metrics.minTap)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Close directions")
            }
            .padding(.horizontal, 24)
            .padding(.top, 20)

            ScrollView {
                VStack(spacing: 0) {
                    ForEach(steps) { step in
                        StepRow(step: step, isLast: step.id == steps.count - 1)
                    }
                    Text("Street names are listed, from OpenStreetMap and Loop's corridor catalog. Distances are measured along the route.")
                        .typeStyle(.label)
                        .foregroundStyle(Palette.inkMuted.color)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.top, 16)
                        .padding(.bottom, 24)
                }
                .padding(.horizontal, 24)
                .padding(.top, 8)
            }
        }
        .background(Palette.surfaceSheet.color)
    }
}

private struct StepRow: View {
    let step: DirectionStep
    let isLast: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Text(Directions.mileText(step.mile))
                .typeStyle(.numeralS)
                .foregroundStyle(Palette.inkMuted.color)
                .frame(width: 44, alignment: .trailing)
                .padding(.top, 10)
            // The rail: a dot per step, a line to the next.
            ZStack(alignment: .top) {
                if !isLast {
                    Rectangle().fill(Palette.routeStreet.color.opacity(0.5)).frame(width: 2).padding(.top, 22)
                }
                marker.padding(.top, 14)
            }
            .frame(width: 14)
            VStack(alignment: .leading, spacing: 2) {
                Text(step.text)
                    .typeStyle(.bodyStrong)
                    .foregroundStyle(Palette.ink.color)
                    .fixedSize(horizontal: false, vertical: true)
                if let miles = step.miles {
                    Text(step.kind == .start ? "Run \(Directions.distanceText(miles))" : "For \(Directions.distanceText(miles))")
                        .typeStyle(.body)
                        .foregroundStyle(Palette.inkSoft.color)
                }
            }
            .padding(.vertical, 8)
            .padding(.bottom, 8)
            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(["Mile \(Directions.mileText(step.mile))", step.text,
                             step.miles.map { Directions.distanceText($0) }].compactMap { $0 }.joined(separator: ", "))
    }

    @ViewBuilder private var marker: some View {
        switch step.kind {
        case .start: Circle().fill(Palette.accentStart.color).frame(width: 12, height: 12)
        case .turnaround: Circle().strokeBorder(Palette.ink.color, lineWidth: 2).background(Circle().fill(Palette.surfaceSheet.color)).frame(width: 12, height: 12)
        case .run: Circle().fill(Palette.routeWater.color).frame(width: 8, height: 8).padding(2)
        case .finish: Circle().fill(Palette.ink.color).frame(width: 12, height: 12)
        }
    }
}
