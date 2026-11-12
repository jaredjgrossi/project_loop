import SwiftUI

/// Design lab A, "Asking" (design-review-v1, problem 1). Two parts, both only when the lab switch is on:
/// - `ComposerField`: the request field as a composer. It grows from one line to three, so a
///   sentence is read whole, and it has a send arrow once there is something to send (the keyboard's
///   go key still sends). No magnifying glass: this isn't a search field.
/// - `TryExamples`: for a runner with no runs of their own, a short list of sentences that each
///   show a different thing Loop understands. A tap puts the sentence in the field; it doesn't send.
struct ComposerField: View {
    @Bindable var model: MainModel
    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let style = TypeStyle.field
    private static let cancelWidth: CGFloat = 72
    private static let radius: CGFloat = 25

    private var canSend: Bool { !model.fieldText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        let typing = model.stage == .typing
        let editing = model.searchMode
        HStack(alignment: .bottom, spacing: 0) {
            HStack(alignment: .bottom, spacing: 8) {
                ZStack(alignment: .topLeading) {
                    if model.fieldText.isEmpty {
                        Text(editing || model.fieldExample.isEmpty ? "Describe your run" : model.fieldExample)
                            .typeStyle(Self.style)
                            .foregroundStyle(Palette.inkMuted.color)
                            .lineLimit(1)
                            .accessibilityHidden(true)
                    }
                    TextField("", text: $model.fieldText, axis: .vertical)
                        .typeStyle(Self.style)
                        .foregroundStyle(Palette.ink.color)
                        .tint(Palette.focusRing.color)
                        .lineLimit(1...3)
                        .focused($focused)
                        .submitLabel(.go)
                        .onSubmit { send() }
                        .accessibilityLabel("Describe your run")
                }
                .padding(.vertical, 13)
                .frame(maxWidth: .infinity, alignment: .leading)

                // The send arrow: only when there is something to send.
                if canSend {
                    Button(action: send) {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(Palette.onAction.color)
                            .frame(width: 34, height: 34)
                            .background(Circle().fill(Palette.action.color))
                            .frame(width: Metrics.minTap, height: 50)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Send")
                    .accessibilityHint("Builds this run")
                    .transition(.opacity.combined(with: .scale(scale: 0.8)))
                }
            }
            .padding(.leading, 20)
            .padding(.trailing, canSend ? 3 : 20)
            .frame(minHeight: 50)
            .background(RoundedRectangle(cornerRadius: Self.radius, style: .continuous).fill(Palette.surfaceSunken.color))
            .overlay(RoundedRectangle(cornerRadius: Self.radius, style: .continuous)
                .strokeBorder(Palette.focusRing.color, lineWidth: 1.5).opacity(typing ? 1 : 0))
            .contentShape(RoundedRectangle(cornerRadius: Self.radius, style: .continuous))
            .onTapGesture { focused = true }

            ZStack(alignment: .leading) {
                if editing {
                    Button("Cancel") { model.cancelTyping() }
                        .typeStyle(.body)
                        .foregroundStyle(Palette.ink.color)
                        .fixedSize()
                        .frame(minHeight: 50)
                        .padding(.leading, 14)
                        .transition(.opacity)
                }
            }
            .frame(width: editing ? Self.cancelWidth : 0, alignment: .leading)
            .clipped()
        }
        .animation(reduceMotion ? nil : Motion.crossfade, value: editing)
        .animation(reduceMotion ? nil : Motion.crossfade, value: canSend)
        .onChange(of: model.fieldText) { _, v in
            // A vertical field turns return into a newline; treat it as go.
            if v.contains("\n") {
                model.fieldText = v.replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces)
                send()
            }
        }
        .onChange(of: focused) { _, isFocused in
            if isFocused { model.beginTyping() } else if model.searchMode { model.endTyping() }
        }
        .onChange(of: model.stage) { _, stage in
            if stage == .typing, model.demoTyping {
                model.fieldText = model.fieldExample
            } else if stage != .typing {
                focused = false
            }
        }
        .onChange(of: model.focusFieldRequest) { _, _ in focused = true }
    }

    private func send() {
        guard canSend else { return }
        model.send(model.fieldText, reduceMotion: reduceMotion)
    }
}

/// Sentences a new runner can try. Each shows one thing Loop understands; all are requests the
/// engine handles from any start in the city. The UI chat owns the wording.
enum TryExample {
    static let all = [
        "4 miles by the water",
        "5 miles, fewest lights",
        "A real loop, 3 miles",
        "Somewhere quiet",
        "6 miles, flat",
    ]
}

struct TryExamples: View {
    let model: MainModel
    var limit = 4
    var hidden = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Try")
                .typeStyle(.eyebrow)
                .foregroundStyle(Palette.inkMuted.color)
                .accessibilityAddTraits(.isHeader)
            VStack(spacing: 0) {
            ForEach(Array(TryExample.all.prefix(limit).enumerated()), id: \.offset) { i, text in
                Button { model.useExample(text) } label: {
                    HStack(spacing: 12) {
                        Text(text)
                            .typeStyle(.field)
                            .foregroundStyle(Palette.inkSoft.color)
                            .lineLimit(1)
                        Spacer(minLength: 8)
                        // "Put this in the field": the same glyph Safari uses for a suggestion.
                        Image(systemName: "arrow.up.left")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(Palette.inkMuted.color)
                    }
                    .frame(height: Metrics.minTap)
                    .contentShape(Rectangle())
                    .overlay(alignment: .bottom) {
                        if i < min(limit, TryExample.all.count) - 1 {
                            Rectangle().fill(Palette.lineHairline.color).frame(height: 1)
                        }
                    }
                }
                .buttonStyle(.plain)
                .accessibilityHint("Puts this in the field")
            }
            }
            .padding(.top, 4)
        }
        .accessibilityHidden(hidden)
        .allowsHitTesting(!hidden)
    }
}

extension RunStore {
    /// No saved routes, no runs marked, and fewer than three requests sent: the home sheet teaches
    /// instead of listing.
    /// The first launch seeds a "Usual" run and one recent from the bundled route; those aren't
    /// the runner's own and don't count. The lab's "as a new runner" switch forces this on.
    var isNewRunner: Bool {
        if DesignLab.shared.isOn(.asNewRunner) { return true }
        let ownSaved = saved.filter { !($0.id == "usual" && $0.archive == RouteArchive.fixture) }
        let ownRecents = recents.filter { $0.id != "rt_seed" }
        return ownSaved.isEmpty && runs.isEmpty && ownRecents.count < 3
    }
}

extension MainModel {
    /// A "Try" row: the sentence goes into the field and the keyboard comes up, so the runner
    /// reads it, can change a word, and sends it themselves.
    func useExample(_ text: String) {
        fieldText = text
        focusFieldRequest += 1
    }
}
