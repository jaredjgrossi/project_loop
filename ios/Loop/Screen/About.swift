import SwiftUI
import UIKit

/// What the About section at the foot of "You" shows (decision 063): the version and build from the bundle,
/// and the install id, copied bare so a runner can paste it into a deletion request.
@MainActor
enum AboutInfo {
    static func copyInstallId(of store: RunStore, to pasteboard: UIPasteboard = .general) {
        pasteboard.string = store.installId
    }

    static func versionLine(version: String?, build: String?) -> String {
        switch (version, build) {
        case let (v?, b?): return "\(v) (\(b))"
        case let (v?, nil): return v
        case let (nil, b?): return "(\(b))"
        case (nil, nil): return ""
        }
    }

    static var versionLine: String {
        let info = Bundle.main.infoDictionary
        return versionLine(version: info?["CFBundleShortVersionString"] as? String,
                           build: info?["CFBundleVersion"] as? String)
    }
}

/// The About section: a hairline, the ABOUT eyebrow, the version row and the install id row. Tapping the id
/// copies it and the row says "Copied" for a moment.
struct AboutSection: View {
    let runs: RunStore
    @State private var copied = false
    @State private var copiedReset: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Rectangle().fill(Palette.lineHairline.color).frame(height: 1).padding(.top, 26)
            Text("About").typeStyle(.eyebrow).foregroundStyle(Palette.inkMuted.color)
                .padding(.top, 26).accessibilityAddTraits(.isHeader)
            HStack {
                Text("Version").typeStyle(.body).foregroundStyle(Palette.ink.color)
                Spacer()
                Text(AboutInfo.versionLine).typeStyle(.body).foregroundStyle(Palette.inkMuted.color)
            }
            .frame(minHeight: Metrics.minTap)
            .padding(.top, 10)
            .accessibilityElement(children: .combine)
            Button(action: copy) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Install id").typeStyle(.body).foregroundStyle(Palette.ink.color)
                        Text(runs.installId).typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                            .lineLimit(1).minimumScaleFactor(0.8)
                    }
                    Spacer(minLength: Metrics.s12)
                    Text(copied ? "Copied" : "Copy").typeStyle(.bodyStrong).foregroundStyle(Palette.action.color)
                        .contentTransition(.opacity)
                }
                .frame(minHeight: Metrics.minTap)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Install id \(runs.installId)")
            .accessibilityHint("Copies it")
            .accessibilityValue(copied ? "Copied" : "")
            Text("No account: this id is all Loop knows you by. Send it to have your runs deleted.")
                .typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                .padding(.top, 4)
        }
    }

    private func copy() {
        AboutInfo.copyInstallId(of: runs)
        withAnimation(Motion.crossfade) { copied = true }
        copiedReset?.cancel()
        copiedReset = Task { @MainActor in
            try? await Task.sleep(for: .seconds(1.6))
            guard !Task.isCancelled else { return }
            withAnimation(Motion.crossfade) { copied = false }
        }
    }
}
