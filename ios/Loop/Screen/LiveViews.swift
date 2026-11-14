import SwiftUI
import UIKit

/// One-time: paste the Loop token (Universal Clipboard from the Mac works). It goes straight to
/// the Keychain; it's never shown back, logged or put in the bundle. Copy is plain until the UI
/// chat words it.
struct TokenScreen: View {
    @Bindable var model: MainModel
    @State private var token = ""
    @State private var failed = false
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Loop")
                .typeStyle(.wordmark)
                .foregroundStyle(Palette.ink.color)
            Text("Paste your Loop token")
                .typeStyle(.request)
                .foregroundStyle(Palette.ink.color)
                .padding(.top, 28)
            Text(model.tokenMessage ?? "It's saved on this phone only, in the Keychain.")
                .typeStyle(.body)
                .foregroundStyle(model.tokenMessage == nil ? Palette.inkMuted.color : Palette.alert.color)
                .padding(.top, 10)

            SecureField("", text: $token)
                .typeStyle(.field)
                .foregroundStyle(Palette.ink.color)
                .tint(Palette.focusRing.color)
                .focused($focused)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.done)
                .onSubmit(save)
                .padding(.horizontal, 18)
                .frame(height: 50)
                .background(Capsule().fill(Palette.surfaceSunken.color))
                .overlay(alignment: .leading) {
                    if token.isEmpty {
                        Text("Token").typeStyle(.field).foregroundStyle(Palette.inkMuted.color)
                            .padding(.leading, 18).allowsHitTesting(false)
                    }
                }
                .accessibilityLabel("Loop token")
                .padding(.top, 28)

            HStack(spacing: 12) {
                Button {
                    if let s = UIPasteboard.general.string { token = s }
                } label: {
                    Text("Paste").typeStyle(.bodyStrong).foregroundStyle(Palette.ink.color)
                        .frame(maxWidth: .infinity).frame(height: 54)
                        .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).strokeBorder(Palette.controlBorder.color))
                }
                Button(action: save) {
                    Text("Save").typeStyle(.bodyStrong).foregroundStyle(Palette.onAction.color)
                        .frame(maxWidth: .infinity).frame(height: 54)
                        .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).fill(Palette.action.color))
                }
                .disabled(token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .buttonStyle(.plain)
            .padding(.top, 16)

            if failed {
                Text("Couldn't save it. Try again.")
                    .typeStyle(.label).foregroundStyle(Palette.alert.color).padding(.top, 10)
            }
            Spacer()
            Button("Not now") { model.needsToken = false }
                .typeStyle(.body)
                .foregroundStyle(Palette.inkMuted.color)
                .frame(maxWidth: .infinity)
                .frame(minHeight: Metrics.minTap)
                .accessibilityHint("Runs on the saved route until a token is pasted")
        }
        .padding(.horizontal, Metrics.s24)
        .padding(.top, 24)
        .padding(.bottom, 12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Palette.surfaceSheet.color.ignoresSafeArea())
        .onAppear { focused = true }
    }

    private func save() {
        failed = !model.tokenSaved(token)
        if !failed { token = "" }
    }
}

/// A question from the parser or the engine: its text, one button per option, and a field when
/// typing is allowed. Answering continues the build.
struct QuestionCard: View {
    let model: MainModel
    let question: ServerEvent.Question
    @State private var typed = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                // Loop is speaking: the question is set like the field under it, not as small print.
                Text(question.text)
                    .typeStyle(.field)
                    .foregroundStyle(Palette.ink.color)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityAddTraits(.isHeader)
                // Never forced to pick or type: × goes back to editing the sentence.
                CloseCardButton { model.cancelQuestion() }
                    .padding(.top, -10)
                    .padding(.trailing, -10)
                    .accessibilityLabel("Close question")
                    .accessibilityHint("Goes back to editing your sentence")
            }
            if !question.options.isEmpty {
                FlowLayout(spacing: 8) {
                    ForEach(question.options, id: \.id) { o in
                        Button { model.answerQuestion(optionId: o.id, text: nil) } label: {
                            Text(o.text)
                                .typeStyle(.bodyStrong)
                                .foregroundStyle(Palette.ink.color)
                                .padding(.horizontal, 16)
                                .frame(minHeight: Metrics.minTap)
                                .background(Capsule().fill(Palette.surfaceSunken.color))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            if question.allowText {
                TextField("", text: $typed)
                    .typeStyle(.field)
                    .foregroundStyle(Palette.ink.color)
                    .tint(Palette.focusRing.color)
                    .focused($focused)
                    .submitLabel(.go)
                    .onSubmit {
                        let t = typed.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !t.isEmpty else { return }
                        model.answerQuestion(optionId: nil, text: t)
                    }
                    .padding(.horizontal, 18)
                    .frame(height: 50)
                    .background(Capsule().fill(Palette.surfaceSunken.color))
                    .overlay(alignment: .leading) {
                        if typed.isEmpty {
                            Text(question.options.isEmpty ? "Type an answer" : "Or type an answer").typeStyle(.field).foregroundStyle(Palette.inkMuted.color)
                                .padding(.leading, 18).allowsHitTesting(false)
                        }
                    }
                    .accessibilityLabel("Type an answer")
            }
        }
        .padding(Metrics.s24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(LiveCardBackground())
    }
}

/// A plain message instead of a spinner, with "Try again" when it might work and a way home.
struct NoticeCard: View {
    let model: MainModel
    let notice: LiveNotice

    var body: some View {
        if let area = notice.outOfArea { outOfArea(area) } else { plain }
    }

    /// Out of the covered area: Loop speaking, like a question. One way forward; × goes home.
    private func outOfArea(_ area: OutOfArea) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                Text(area.message)
                    .typeStyle(.field)
                    .foregroundStyle(Palette.ink.color)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityAddTraits(.isHeader)
                CloseCardButton { model.goHome() }
                    .padding(.top, -10)
                    .padding(.trailing, -10)
                    .accessibilityLabel("Close")
                    .accessibilityHint("Goes back to the start")
            }
            Button { model.changeTheStart() } label: {
                Text(OutOfArea.buttonTitle).typeStyle(.bodyStrong).foregroundStyle(Palette.onAction.color)
                    .frame(maxWidth: .infinity).frame(height: 50)
                    .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).fill(Palette.action.color))
            }
            .buttonStyle(.plain)
            .accessibilityHint("Keeps what you typed so you can name a start there")
        }
        .padding(Metrics.s24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(LiveCardBackground())
    }

    private var plain: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(notice.text)
                .typeStyle(.body)
                .foregroundStyle(Palette.ink.color)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 12) {
                Button { model.goHome() } label: {
                    Text("Back").typeStyle(.bodyStrong).foregroundStyle(Palette.ink.color)
                        .frame(maxWidth: .infinity).frame(height: 50)
                        .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).strokeBorder(Palette.controlBorder.color))
                }
                if notice.canRetry {
                    Button {
                        if model.needsToken { return }
                        model.retryLive()
                    } label: {
                        Text("Try again").typeStyle(.bodyStrong).foregroundStyle(Palette.onAction.color)
                            .frame(maxWidth: .infinity).frame(height: 50)
                            .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).fill(Palette.action.color))
                    }
                }
            }
            .buttonStyle(.plain)
        }
        .padding(Metrics.s24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(LiveCardBackground())
    }
}

/// The question and notice cards: the sheet's surface, rounded on top, at the bottom of the screen.
private struct LiveCardBackground: View {
    var body: some View {
        UnevenRoundedRectangle(topLeadingRadius: Metrics.radiusSheet, topTrailingRadius: Metrics.radiusSheet)
            .fill(Palette.surfaceSheet.color)
            .overlay(UnevenRoundedRectangle(topLeadingRadius: Metrics.radiusSheet, topTrailingRadius: Metrics.radiusSheet)
                .stroke(Palette.lineHairline.color, lineWidth: 1))
            .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.08), radius: 15, y: -8)
            .ignoresSafeArea(edges: .bottom)
    }
}
