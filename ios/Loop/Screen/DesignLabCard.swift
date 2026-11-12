#if DEBUG
import SwiftUI

/// "You" → Design lab (Debug builds only): one switch per exploration, so old and new can be
/// compared on the phone. A change applies from the next screen or the next request.
struct DesignLabCard: View {
    private var lab: DesignLab { DesignLab.shared }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Design lab").typeStyle(.eyebrow).foregroundStyle(Palette.inkMuted.color)
                .accessibilityAddTraits(.isHeader)
            Text("Debug builds only. Off is the app as it is on main.")
                .typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                .padding(.top, 6)
            VStack(spacing: 0) {
                ForEach(DesignLab.Feature.allCases) { f in
                    Toggle(isOn: Binding(get: { lab.isOn(f) }, set: { lab.set(f, $0) })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(f.title).typeStyle(.body).foregroundStyle(Palette.ink.color)
                            Text(f.summary).typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .tint(Palette.action.color)
                    .disabled(lab.isForced(f))
                    .padding(.vertical, 10)
                    .frame(minHeight: Metrics.minTap)
                    .overlay(alignment: .bottom) {
                        if f != DesignLab.Feature.allCases.last {
                            Rectangle().fill(Palette.lineHairline.color).frame(height: 1)
                        }
                    }
                    .accessibilityIdentifier("lab." + f.rawValue)
                }
            }
            .padding(.horizontal, 16)
            .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Palette.surfaceSunken.color))
            .padding(.top, 10)
        }
    }
}
#endif
