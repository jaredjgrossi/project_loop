import SwiftUI

/// Wordmark and preferences button, then the runner's sentence: the header's only content once a
/// request is sent (UI chat, 2026-11-08: no chips, no provenance line).
struct HeaderView: View {
    let sentence: String?
    var trailing: AnyView? = nil
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

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
            if let sentence {
                Text(sentence)
                    .typeStyle(.request)
                    .foregroundStyle(Palette.ink.color)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityLabel("Your run: \(sentence)")
                    .transition(reduceMotion ? .identity : .opacity.combined(with: .offset(y: 8)))
            }
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
