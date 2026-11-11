import SwiftUI

/// Wordmark and preferences, then the runner's sentence: the header's only content once a request
/// is sent (UI chat, 2026-11-08). Tapping the sentence enters edit mode: the understood words take a
/// dotted underline and open the editor; tapping any other word edits the text, and go re-sends.
struct HeaderView: View {
    let model: MainModel
    var trailing: AnyView? = nil
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                // The wordmark is a shortcut home once there's a route or a request.
                Text("Loop")
                    .typeStyle(.wordmark)
                    .foregroundStyle(Palette.ink.color)
                    .frame(minHeight: Metrics.minTap)
                    .contentShape(Rectangle())
                    .onTapGesture { model.goHome() }
                    .accessibilityAddTraits(model.requestText != nil ? [.isHeader, .isButton] : .isHeader)
                    .accessibilityHint(model.requestText != nil ? "Goes back home" : "")
                Spacer()
                // Debug replay only once there's a route: the landing has no mono or data styling.
                if let trailing, model.requestText != nil { trailing }
                YouButton(model: model)
            }
            if model.requestText == nil {
                WeatherLine()
                    .padding(.top, -6)
                    .transition(.opacity)
            }
            if let sentence = model.requestText {
                Group {
                    if model.editingText {
                        SentenceField(model: model, initial: sentence)
                    } else if model.editMode {
                        EditableSentence(sentence: sentence, understood: model.readOut?.understood ?? []) { field in
                            model.openEditor(.understood(field))
                        } onOtherWord: {
                            model.editingText = true
                        }
                    } else {
                        Text(sentence)
                            .typeStyle(.request)
                            .foregroundStyle(Palette.ink.color)
                            .lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                            .onTapGesture { model.enterEditMode() }
                            .accessibilityLabel("Your run: \(sentence)")
                            .accessibilityHint("Double-tap to edit")
                            .accessibilityAddTraits(.isButton)
                    }
                }
                .padding(.bottom, model.editMode ? 11 : 0)
                .overlay(alignment: .bottom) {
                    if model.editMode { Rectangle().fill(Palette.focusRing.color).frame(height: 2) }
                }
                .transition(reduceMotion ? .identity : .opacity.combined(with: .offset(y: 8)))
            }
        }
        .padding(.horizontal, Metrics.s24)
        .padding(.top, 4)
    }
}

/// The sentence in edit mode: understood phrases are dotted-underlined buttons; other words, tapped,
/// switch to editing the text.
struct EditableSentence: View {
    let sentence: String
    let understood: [ReadOut.Understood]
    let onUnderstood: (String) -> Void
    let onOtherWord: () -> Void

    private struct Token: Identifiable { let id: Int; let text: String; let field: String? }

    private var tokens: [Token] {
        let ns = sentence as NSString
        var out: [Token] = []
        var i = 0, n = 0
        let spans = understood.sorted { $0.start < $1.start }
        func words(_ s: String) {
            for w in s.split(separator: " ", omittingEmptySubsequences: true) { out.append(Token(id: n, text: String(w), field: nil)); n += 1 }
        }
        for u in spans where u.start >= i && u.start + u.length <= ns.length {
            words(ns.substring(with: NSRange(location: i, length: u.start - i)))
            // Each word of an understood phrase is its own button, so the sentence wraps naturally.
            for w in ns.substring(with: NSRange(location: u.start, length: u.length)).split(separator: " ") {
                out.append(Token(id: n, text: String(w), field: u.field)); n += 1
            }
            i = u.start + u.length
        }
        if i < ns.length { words(ns.substring(from: i)) }
        // Punctuation sticks to the word before it, with no gap ("7 am.").
        var merged: [Token] = []
        for t in out {
            if t.field == nil, t.text.allSatisfy({ ".,;:!?".contains($0) }), let last = merged.last {
                merged[merged.count - 1] = Token(id: last.id, text: last.text + t.text, field: last.field)
            } else { merged.append(t) }
        }
        return merged
    }

    var body: some View {
        FlowLayout(spacing: 7, lineSpacing: 4) {
            ForEach(tokens) { t in
                if let field = t.field {
                    Button { onUnderstood(field) } label: {
                        Text(t.text)
                            .typeStyle(.request)
                            .foregroundStyle(Palette.ink.color)
                            .underline(true, pattern: .dot, color: Palette.action.color)
                    }
                    .buttonStyle(.plain)
                    .accessibilityHint("Opens the editor")
                } else {
                    Text(t.text)
                        .typeStyle(.request)
                        .foregroundStyle(Palette.ink.color)
                        .onTapGesture { onOtherWord() }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// The sentence as text, with the keyboard; go re-sends (and re-parses).
struct SentenceField: View {
    let model: MainModel
    let initial: String
    @State private var text = ""
    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TextField("Describe your run", text: $text, axis: .vertical)
            .typeStyle(.request)
            .foregroundStyle(Palette.ink.color)
            .tint(Palette.focusRing.color)
            .focused($focused)
            .submitLabel(.go)
            .onSubmit { model.send(text, reduceMotion: reduceMotion) }
            .onChange(of: text) { _, v in
                // A vertical TextField turns return into a newline; treat it as go.
                if v.contains("\n") { model.send(v.replacingOccurrences(of: "\n", with: ""), reduceMotion: reduceMotion) }
            }
            .onAppear { text = initial; focused = true }
    }
}

/// Wraps its children onto lines like text.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 4

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineH: CGFloat = 0, maxX: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width { x = 0; y += lineH + lineSpacing; lineH = 0 }
            x += size.width + spacing; lineH = max(lineH, size.height); maxX = max(maxX, x - spacing)
        }
        return CGSize(width: min(width, maxX), height: y + lineH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, lineH: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX { x = bounds.minX; y += lineH + lineSpacing; lineH = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing; lineH = max(lineH, size.height)
        }
    }
}

/// The 44 pt round preferences button. Preferences are out of scope for this slice; it does nothing.
