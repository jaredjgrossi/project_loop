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

/// The sentence in edit mode: each understood phrase takes one dotted underline, through its spaces
/// ("from the Kips Bay Library" is one piece), and opens its editor; any other word, tapped,
/// switches to editing the text. One text, so it wraps exactly as the sentence does outside edit
/// mode. VoiceOver gets the same pieces as buttons (the text's own links would read as links).
struct EditableSentence: View {
    let sentence: String
    let understood: [ReadOut.Understood]
    let onUnderstood: (String) -> Void
    let onOtherWord: () -> Void
    /// When a phrase was last tapped: the tap on the text behind it is then ignored.
    @State private var phraseTapAt = Date.distantPast

    /// A run of the sentence: an understood phrase (with its field) or the words between two.
    struct Piece: Equatable, Identifiable {
        let id: Int
        let text: String
        let field: String?
    }

    private static let scheme = "loop-edit:"

    /// The sentence cut into pieces, in order, with nothing lost: joined, they are the sentence.
    /// Phrases that overlap an earlier one, or run past the end, are left as plain words.
    static func pieces(_ sentence: String, understood: [ReadOut.Understood]) -> [Piece] {
        let ns = sentence as NSString
        var out: [Piece] = []
        var i = 0
        func add(_ text: String, _ field: String?) {
            if !text.isEmpty { out.append(Piece(id: out.count, text: text, field: field)) }
        }
        for u in understood.sorted(by: { $0.start < $1.start }) where u.start >= i && u.length > 0 && u.start + u.length <= ns.length {
            add(ns.substring(with: NSRange(location: i, length: u.start - i)), nil)
            add(ns.substring(with: NSRange(location: u.start, length: u.length)), u.field)
            i = u.start + u.length
        }
        if i < ns.length { add(ns.substring(from: i), nil) }
        return out
    }

    /// The sentence with each understood phrase as one underlined link (`loop-edit:<field>`).
    static func attributed(_ pieces: [Piece]) -> AttributedString {
        var out = AttributedString()
        for p in pieces {
            var run = AttributedString(p.text)
            if let field = p.field {
                run.link = URL(string: scheme + field)
                run.swiftUI.underlineStyle = Text.LineStyle(pattern: .dot, color: Palette.action.color)
                run.swiftUI.foregroundColor = Palette.ink.color
            }
            out += run
        }
        return out
    }

    /// What VoiceOver reads: the phrases, and the stretches of other words that have a letter or a
    /// digit in them (a lone space or full stop is not a stop on the way).
    static func spoken(_ pieces: [Piece]) -> [Piece] {
        pieces.compactMap { p in
            let text = p.field == nil ? p.text.trimmingCharacters(in: .whitespacesAndNewlines) : p.text
            guard text.contains(where: { $0.isLetter || $0.isNumber }) else { return nil }
            return Piece(id: p.id, text: text, field: p.field)
        }
    }

    var body: some View {
        let pieces = Self.pieces(sentence, understood: understood)
        Text(Self.attributed(pieces))
            .typeStyle(.request)
            .foregroundStyle(Palette.ink.color)
            .tint(Palette.ink.color)
            .lineLimit(3)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .environment(\.openURL, OpenURLAction { url in
                let s = url.absoluteString
                guard s.hasPrefix(Self.scheme) else { return .systemAction }
                phraseTapAt = Date()
                onUnderstood(String(s.dropFirst(Self.scheme.count)))
                return .handled
            })
            .onTapGesture {
                // A tap on a phrase is the phrase's, whichever handler hears it first.
                DispatchQueue.main.async {
                    if Date().timeIntervalSince(phraseTapAt) > 0.4 { onOtherWord() }
                }
            }
            .accessibilityRepresentation {
                // Each understood phrase is a button that opens its editor, in reading order; the
                // other words are a button that edits the text, as a tap on them does. The buttons
                // share the sentence's area as bands, top to bottom (a wrapped phrase has no one
                // rectangle to give them).
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Self.spoken(pieces)) { p in
                        Group {
                            if let field = p.field {
                                Button(p.text) { onUnderstood(field) }
                                    .accessibilityHint("Opens the editor")
                            } else {
                                Button(p.text) { onOtherWord() }
                                    .accessibilityHint("Edits the words")
                            }
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
                    }
                }
            }
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
