import SwiftUI

/// The route card. Collapsed (216 pt): eyebrow, distance, reason, button. Open (398 pt): adds the
/// profile strip, three whole-route stats and the signals and crowd lines. Drag between the two.
struct RouteSheet: View {
    @Bindable var model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @GestureState private var dragOffset: CGFloat = 0
    @State private var sentConfirmed = false

    private let collapsed = Metrics.sheetCollapsed
    private let open = Metrics.sheetOpen

    var body: some View {
        let height = min(open + 24, max(collapsed - 24, model.sheetBaseHeight - dragOffset))
        let progress = max(0, min(1, (height - collapsed) / (open - collapsed)))

        VStack(alignment: .leading, spacing: 0) {
            Capsule()
                .fill(Palette.grabber.color)
                .frame(width: 36, height: 4)
                .padding(.top, 10)
                .frame(maxWidth: .infinity)
                .frame(height: 14, alignment: .top)
                .contentShape(Rectangle())
                .accessibilityElement()
                .accessibilityLabel(model.sheetIsOpen ? "Close route details" : "Open route details")
                .accessibilityAddTraits(.isButton)
                .accessibilityAction { model.touch(); model.setSheet(open: !model.sheetIsOpen, animated: !reduceMotion) }

            CardBlock(model: model)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 12)

            // Built only while the sheet is above its collapsed height, so a closed sheet has no
            // hidden stats for VoiceOver to find.
            Group {
                if progress > 0 {
                    openSection.accessibilityHidden(progress < 0.5)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .frame(height: max(0, height - collapsed), alignment: .top)
            .clipped()
            .opacity(Double(progress))

            SendButton(confirmed: $sentConfirmed) { model.touch() }
                .padding(.top, 12)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, Metrics.s24)
        .frame(height: height, alignment: .top)
        .frame(maxWidth: .infinity)
        .background(sheetBackground)
        .contentShape(Rectangle())
        .gesture(drag)
        .onChange(of: height) { _, h in model.sheetHeight = h }
    }

    private var sheetBackground: some View {
        UnevenRoundedRectangle(topLeadingRadius: Metrics.radiusSheet, topTrailingRadius: Metrics.radiusSheet)
            .fill(Palette.surfaceSheet.color)
            .overlay(
                UnevenRoundedRectangle(topLeadingRadius: Metrics.radiusSheet, topTrailingRadius: Metrics.radiusSheet)
                    .stroke(Palette.lineHairline.color, lineWidth: 1)
            )
            .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.08), radius: 15, y: -8)
            .ignoresSafeArea(edges: .bottom)
    }

    @ViewBuilder private var openSection: some View {
        if let detail = model.shownDetail, model.cardRevealed {
            VStack(alignment: .leading, spacing: 0) {
                ProfileStrip(detail: detail, selectedMile: model.selectedMile,
                             onScrubStart: { model.touch() },
                             onSelectMile: { model.selectMile($0) })
                    .padding(.top, 12)
                StatRow(stats: CardText.stats(detail.summary))
                    .padding(.top, 10)
                let crowd = CardText.crowdLine(detail, startTime: model.data.request.startHourText)
                VStack(alignment: .leading, spacing: 0) {
                    Text(CardText.signalsLine(detail.summary))
                    // 11 pt mono fits about 50 characters across the sheet; wrap only at " · ".
                    ForEach(Array(CardText.wrapAtSeparators(crowd, maxChars: 50).prefix(2).enumerated()), id: \.offset) {
                        Text($0.element)
                    }
                }
                .typeStyle(.data)
                .foregroundStyle(Palette.inkMuted.color)
                .lineLimit(1)
                .frame(height: Metrics.dataLinesHeight, alignment: .topLeading)
                .padding(.top, 8)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(CardText.signalsLine(detail.summary)). \(crowd)")
            }
        } else if model.cardRevealed {
            Text("Details for this route aren't in the saved file.")
                .typeStyle(.data)
                .foregroundStyle(Palette.inkMuted.color)
                .padding(.top, 16)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 6, coordinateSpace: .global)
            .updating($dragOffset) { v, state, _ in state = v.translation.height }
            .onEnded { v in
                model.touch()
                let predicted = model.sheetBaseHeight - v.predictedEndTranslation.height
                model.setSheet(open: predicted > (collapsed + open) / 2, animated: !reduceMotion)
            }
    }
}

/// Eyebrow, distance and reason: the 96 pt block shared by both states.
struct CardBlock: View {
    let model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(model.eyebrowText)
                .typeStyle(.eyebrow)
                .foregroundStyle(Palette.inkMuted.color)
                .frame(height: 14)
                .contentTransition(.opacity)
                .animation(reduceMotion ? nil : Motion.textArrive, value: model.eyebrowText)

            Group {
                if model.cardRevealed, let shown = model.shown {
                    VStack(alignment: .leading, spacing: 0) {
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text(CardText.distance(shown.distanceMi))
                                .typeStyle(.numeralXL)
                                .foregroundStyle(Palette.ink.color)
                            Text("mi")
                                .typeStyle(.unit)
                                .foregroundStyle(Palette.unitInk.color)
                            // Only the file's own label; the top 3 outlines carry none yet.
                            if let trust = shown.detail?.distanceTrust {
                                Text(trust.text)
                                    .typeStyle(.data)
                                    .foregroundStyle(Palette.inkMuted.color)
                            }
                        }
                        .frame(height: 56)
                        .padding(.top, 2)
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(["\(CardText.distance(shown.distanceMi)) miles", shown.detail?.distanceTrust.text]
                            .compactMap { $0 }.joined(separator: ", "))

                        if let detail = shown.detail {
                            Text(CardText.reason(detail.summary))
                                .typeStyle(.body)
                                .foregroundStyle(Palette.inkSoft.color)
                                .lineLimit(1)
                                .padding(.top, 4)
                        }
                    }
                    .transition(reduceMotion ? .identity : .asymmetric(
                        insertion: .opacity.combined(with: .offset(y: Motion.textRise)),
                        removal: .opacity))
                }
            }
            .animation(reduceMotion ? nil : Motion.textArrive, value: model.cardRevealed)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .frame(height: 96, alignment: .top)
    }
}

/// Value (Fraunces, tabular), label, trust label: three columns.
struct StatRow: View {
    let stats: [CardText.Stat]

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ForEach(stats, id: \.label) { s in
                VStack(alignment: .leading, spacing: 1) {
                    Text(s.value).typeStyle(.numeralL).foregroundStyle(Palette.ink.color)
                    Text(s.label).typeStyle(.label).foregroundStyle(Palette.inkSoft.color)
                    Text(s.trust.text).typeStyle(.data).foregroundStyle(Palette.inkMuted.color)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(s.value) \(s.label), \(s.trust.text)")
            }
        }
        .frame(height: 58, alignment: .top)
    }
}

/// The one primary action. Confirms at once with a success haptic and does nothing else (this slice).
struct SendButton: View {
    @Binding var confirmed: Bool
    var onTap: () -> Void

    var body: some View {
        Button {
            onTap()
            Haptics.success()
            confirmed = true
            Task { @MainActor in
                try? await Task.sleep(for: .seconds(2.5))
                confirmed = false
            }
        } label: {
            HStack(spacing: 8) {
                if confirmed { Image(systemName: "checkmark").font(.system(size: 15, weight: .semibold)) }
                Text(confirmed ? "Sent to watch" : "Send to watch")
            }
            .typeStyle(.bodyStrong)
            .foregroundStyle(Palette.onAction.color)
            .frame(maxWidth: .infinity)
            .frame(height: 54)
            .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).fill(Palette.action.color))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(confirmed ? "Sent to watch" : "Send to watch")
    }
}
