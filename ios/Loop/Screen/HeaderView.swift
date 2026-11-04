import SwiftUI

/// Wordmark, preferences button, request text and provenance line, over a fade from the map.
struct HeaderView: View {
    let request: RequestCard
    var trailing: AnyView? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Loop")
                    .typeStyle(.wordmark)
                    .foregroundStyle(Palette.ink.color)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                if let trailing { trailing }
                PreferencesButton()
            }
            VStack(alignment: .leading, spacing: 0) {
                Text(request.text)
                    .typeStyle(.request)
                    .foregroundStyle(Palette.ink.color)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, 12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityLabel("Your run: \(request.text)")
                Rectangle().fill(Palette.requestRule.color).frame(height: 1)
            }
            Text(request.provenance)
                .typeStyle(.data)
                .foregroundStyle(Palette.inkMuted.color)
        }
        .padding(.horizontal, Metrics.s24)
        .padding(.top, 4)
    }
}

/// The 44 pt round preferences button. Preferences are out of scope for this slice; it does nothing.
struct PreferencesButton: View {
    var body: some View {
        Button {} label: {
            Image(systemName: "slider.horizontal.3")
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(Palette.ink.color)
                .frame(width: Metrics.minTap, height: Metrics.minTap)
                .background(Circle().fill(Palette.surfaceSheet.color.opacity(0.92)))
                .overlay(Circle().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Preferences and layers")
        .accessibilityHint("Not available yet")
    }
}
