import SwiftUI

/// The runner's usual route type, sent with every request as `profile.usual_shape`. Kept on the
/// phone (UserDefaults).
enum UsualShape: String, CaseIterable, Identifiable {
    case any
    case loop
    case outAndBack = "out_and_back"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .any: return "Any"
        case .loop: return "Loop"
        case .outAndBack: return "Out and back"
        }
    }

    static let key = "usualShape"
    static var current: UsualShape {
        get { UserDefaults.standard.string(forKey: key).flatMap(UsualShape.init(rawValue:)) ?? .any }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: key) }
    }
}

/// Settings behind the preferences button. Plain for now; the UI chat designs it.
struct SettingsSheet: View {
    @State private var shape = UsualShape.current
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Settings").typeStyle(.wordmark).foregroundStyle(Palette.ink.color)
                Spacer()
                CloseCardButton { dismiss() }
                    .accessibilityLabel("Close settings")
            }
            Text("Usual route type")
                .typeStyle(.eyebrow)
                .foregroundStyle(Palette.inkMuted.color)
                .padding(.top, 24)
                .accessibilityAddTraits(.isHeader)
            VStack(spacing: 0) {
                ForEach(UsualShape.allCases) { s in
                    Button {
                        shape = s
                        UsualShape.current = s
                    } label: {
                        HStack {
                            Text(s.title).typeStyle(.body).foregroundStyle(Palette.ink.color)
                            Spacer()
                            if shape == s {
                                Image(systemName: "checkmark").font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(Palette.action.color)
                            }
                        }
                        .frame(minHeight: 48)
                        .contentShape(Rectangle())
                        .overlay(alignment: .bottom) { Rectangle().fill(Palette.lineHairline.color).frame(height: 1) }
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(shape == s ? .isSelected : [])
                }
            }
            .padding(.top, 8)
            Spacer()
        }
        .padding(Metrics.s24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Palette.surfaceSheet.color.ignoresSafeArea())
        .presentationDetents([.medium])
        .presentationBackground(Palette.surfaceSheet.color)
    }
}
