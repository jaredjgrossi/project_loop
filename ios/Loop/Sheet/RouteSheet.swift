import SwiftUI

/// The route card. Collapsed (216 pt): eyebrow, distance, reason, button. Open (398 pt): adds the
/// profile strip, three whole-route stats and the signals and crowd lines. Drag between the two.
struct RouteSheet: View {
    @Bindable var model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var sheet: SheetState { model.sheet }
    @State private var readContentHeight: CGFloat = 0

    var body: some View {
        let height = sheet.height
        ZStack(alignment: .top) {
            if let r = model.rating {
                // "How was it?": the sheet turns into the rating and fits it (one motion, the sheet's).
                RatingContent(model: model, state: r)
                    .padding(.horizontal, Metrics.s24)
                    .background(GeometryReader { g in
                        Color.clear
                            .onAppear { fitRating(g.size.height) }
                            .onChange(of: g.size.height) { _, h in fitRating(h) }
                    })
                    .transition(.opacity)
            } else {
                card.transition(.opacity)
            }
        }
        .animation(reduceMotion ? nil : Motion.crossfade, value: model.rating == nil)
        .frame(height: height, alignment: .top)
        .frame(maxWidth: .infinity)
        .clipped()
        .background(sheetBackground)
        .contentShape(Rectangle())
        .gesture(drag, including: model.rating == nil ? .all : .subviews)
    }

    /// The rating sizes the sheet to its content, above the home indicator.
    private func fitRating(_ content: CGFloat) {
        let target = (content + LandingSheet.bottomInset).rounded()
        guard abs(sheet.height - target) > 0.5 else { return }
        sheet.slide(to: target, animated: !reduceMotion, duration: 0.24)
    }

    private var card: some View {
        let height = sheet.height
        let progress = sheet.progress

        return VStack(alignment: .leading, spacing: 0) {
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

            // The open content is always laid out at full size; dragging only clips and fades it,
            // so nothing is inserted mid-drag. Hidden (still laid out) when fully closed, so
            // VoiceOver doesn't find it.
            OpenSection(model: model)
                .frame(height: SheetState.open - SheetState.collapsed, alignment: .top)
                .frame(maxWidth: .infinity, alignment: .leading)
                .opacity(Double(progress))
                .frame(height: max(0, min(height, sheet.openHeight) - sheet.collapsedHeight), alignment: .top)
                .clipped()
                .accessibilityHidden(progress < 0.5)
                .hiddenWhen(progress == 0)

            ActionRow(model: model)
                .padding(.top, 12)

            // "How Loop read it": revealed past the open state, scrolling if it's long.
            ScrollViewReader { proxy in
                ScrollView(showsIndicators: false) {
                    ReadItSection(model: model)
                        .id("readit")
                        .background(GeometryReader { g in
                            Color.clear
                                .onAppear { readContentHeight = g.size.height }
                                .onChange(of: g.size.height) { _, v in readContentHeight = v }
                        })
                }
                // Scrolls only when the list is longer than the space; otherwise drags move the sheet.
                .scrollDisabled(sheet.rest != .read || readContentHeight <= (sheet.readHeight ?? 0) - sheet.openHeight + 1)
                .onChange(of: model.scrollToReadIt) { _, _ in withAnimation { proxy.scrollTo("readit", anchor: .top) } }
            }
            .frame(height: max(0, height - sheet.openHeight))
            .opacity(Double(sheet.readProgress))
            .clipped()
            .hiddenWhen(sheet.readProgress == 0)
            Spacer(minLength: 0)
        }
        .onChange(of: readContentHeight) { _, h in updateReadHeight(h) }
        .onChange(of: model.headerBottom) { _, _ in updateReadHeight(readContentHeight) }
        .padding(.horizontal, Metrics.s24)
        .overlay(alignment: .topTrailing) {
            HStack(spacing: -6) {
                if model.currentRoute != nil { BookmarkButton(saved: model.isCurrentSaved) { model.toggleSave() } }
                CloseCardButton { model.goHome() }
            }
            .padding(.top, 12).padding(.trailing, 14)
        }
    }

    /// The read rest fits the list, up to just under the header.
    private func updateReadHeight(_ content: CGFloat) {
        guard model.readOut?.hasReadIt == true, content > 0 else { sheet.readHeight = nil; return }
        let screen = UIScreen.main.bounds.height
        sheet.readHeight = min(sheet.openHeight + content, screen - model.headerBottom - 12)
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

    private var drag: some Gesture {
        DragGesture(minimumDistance: 6, coordinateSpace: .global)
            .onChanged { v in
                if !sheet.isMoving { model.touch() }
                sheet.drag(translation: v.translation.height)
            }
            .onEnded { v in
                model.sheetDragEnded(predictedTranslation: v.predictedEndTranslation.height, animated: !reduceMotion)
            }
    }
}

/// The card's close button: clears the route and goes back to the home sheet.
struct CloseCardButton: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: "xmark")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Palette.inkMuted.color)
                .frame(width: 30, height: 30)
                .background(Circle().fill(Palette.surfaceSunken.color))
                .frame(width: Metrics.minTap, height: Metrics.minTap)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Close route")
        .accessibilityHint("Clears this route and goes back home")
    }
}

extension View {
    /// `.hidden()` on a condition, keeping the view laid out either way.
    @ViewBuilder func hiddenWhen(_ hidden: Bool) -> some View {
        if hidden { self.hidden() } else { self }
    }
}

/// Profile strip, whole-route stats and the crowd line: the open state's content.
struct OpenSection: View {
    let model: MainModel

    var body: some View {
        content
    }

    @ViewBuilder private var content: some View {
        if let detail = model.shownDetail, model.cardRevealed {
            VStack(alignment: .leading, spacing: 0) {
                ProfileStrip(detail: detail, selectedMile: model.selectedMile, cursorMile: model.selectionAlongMi,
                             onScrubStart: { model.touch() },
                             onSelectMile: { model.selectMile($0) })
                    .padding(.top, 12)
                StatRow(stats: CardText.stats(detail.summary))
                    .padding(.top, 10)
                // One sentence, only when a stretch is moderate or busy; otherwise no line.
                if let crowd = CardText.crowdSentence(detail, startTime: model.data.request.startHourText) {
                    let trust = Trust(detail.summary.crowds.status)
                    TrustTap(trust: trust, source: detail.summary.crowds.source) {
                        Text(crowd)
                            .typeStyle(.body)
                            .foregroundStyle(Palette.inkSoft.color)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(.top, 10)
                    .accessibilityLabel("\(crowd) \(trust.text)")
                }
            }
        } else if model.cardRevealed, !model.liveMode {
            Text("Details for this route aren't in the saved file.")
                .typeStyle(.label)
                .foregroundStyle(Palette.inkMuted.color)
                .padding(.top, 16)
                .frame(maxWidth: .infinity, alignment: .leading)
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
                        // No trust word beside "mi": tapping the distance shows it (and the source).
                        TrustTap(trust: shown.distanceTrust, source: shown.distanceSource) {
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                Text(CardText.approx(CardText.distance(shown.distanceMi), shown.distanceTrust))
                                    .typeStyle(.numeralXL)
                                    .foregroundStyle(Palette.ink.color)
                                Text("mi")
                                    .typeStyle(.numeralL)
                                    .foregroundStyle(Palette.unitInk.color)
                            }
                        }
                        .frame(height: 56)
                        .padding(.top, 2)
                        .accessibilityLabel(["\(CardText.distance(shown.distanceMi)) miles", shown.distanceTrust?.text]
                            .compactMap { $0 }.joined(separator: ", "))

                        if let reason = shown.detail.flatMap({ CardText.reason($0.summary) }) {
                            Text(reason)
                                .typeStyle(.body)
                                .foregroundStyle(Palette.inkSoft.color)
                                .lineLimit(1)
                                .padding(.top, 4)
                        }
                        // An unmet ask, named in one line; tapping it opens "How Loop read it".
                        if let line = CardText.cantCardLine(model.readOut?.cant.map(\.gap) ?? []) {
                            Button { model.openReadIt() } label: {
                                HStack(spacing: 8) {
                                    Circle().strokeBorder(Palette.inkMuted.color, lineWidth: 1.5).frame(width: 9, height: 9)
                                    Text(line).typeStyle(.label)
                                        .foregroundStyle(Palette.inkSoft.color)
                                }
                                .frame(height: 26, alignment: .bottom)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityHint("Shows how Loop read your run")
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
        .frame(height: 96 + model.sheet.extra, alignment: .top)
    }
}

/// "How Loop read it" (UI chat, 2026-11-08; calm pass 2026-11-09): can't-do lines first, then what
/// Loop filled in in plain words (each line opens the editor), then notes (trust word on tap). What the runner said isn't repeated:
/// it's underlined in the sentence.
struct ReadItSection: View {
    let model: MainModel

    var body: some View {
        if let r = model.readOut, r.hasReadIt {
            VStack(alignment: .leading, spacing: 0) {
                Text("How Loop read it").typeStyle(.eyebrow).foregroundStyle(Palette.inkMuted.color)
                    .padding(.bottom, 4)
                    .accessibilityAddTraits(.isHeader)
                ForEach(r.cant, id: \.gap) { c in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Circle().strokeBorder(Palette.inkMuted.color, lineWidth: 1.5).frame(width: 9, height: 9)
                        Text(c.text).typeStyle(.body).foregroundStyle(Palette.ink.color)
                    }
                    .frame(minHeight: 48, alignment: .leading)
                    .overlay(alignment: .bottom) { Rectangle().fill(Palette.lineHairline.color).frame(height: 1) }
                }
                if !r.filled.isEmpty {
                    // What Loop filled in, in plain words: no heading, no source words.
                    ForEach(r.filled) { f in
                        // A clean tap only: a scroll or drag that starts on a row never opens it.
                        CleanTap(hint: "Opens the editor") { model.openEditor(.filled(f.field)) } label: {
                            HStack(spacing: 12) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(f.main).typeStyle(.body).foregroundStyle(Palette.ink.color)
                                    if !f.detail.isEmpty {
                                        Text(f.detail).typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                                    }
                                }
                                Spacer()
                                Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(Palette.inkMuted.color)
                            }
                            .frame(minHeight: 52)
                            .contentShape(Rectangle())
                            .overlay(alignment: .bottom) { Rectangle().fill(Palette.lineHairline.color).frame(height: 1) }
                        }
                    }
                }
                if !r.notes.isEmpty {
                    Text("Notes").typeStyle(.label).foregroundStyle(Palette.inkMuted.color).padding(.top, 14)
                    // Each note's trust word shows on tap, like the numbers.
                    ForEach(r.notes, id: \.key) { n in
                        TrustTap(trust: Trust(n.trust), source: nil) {
                            Text(n.text).typeStyle(.label).foregroundStyle(Palette.inkSoft.color)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(.top, 6)
                        .accessibilityLabel("\(n.text), \(Trust(n.trust).text)")
                    }
                }
            }
            .padding(.top, 22)
            .padding(.bottom, 30)
        }
    }
}

/// Value (Fraunces, tabular; "≈" for an estimate) over its label: three columns. The trust word
/// and source show on tap.
struct StatRow: View {
    let stats: [CardText.Stat]

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ForEach(stats, id: \.label) { s in
                TrustTap(trust: s.trust, source: s.source) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(s.shown).typeStyle(.numeralL).foregroundStyle(Palette.ink.color)
                        Text(s.label).typeStyle(.label).foregroundStyle(Palette.inkSoft.color)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .accessibilityLabel("\(s.value) \(s.label), \(s.trust.text)")
            }
        }
        .frame(height: 44, alignment: .top)
    }
}

/// A tap that only fires when the finger lifts without moving: unlike a Button, a scroll or a
/// sheet drag that starts on it never triggers it. VoiceOver still sees a button.
struct CleanTap<Label: View>: View {
    var hint: String = ""
    let action: () -> Void
    @ViewBuilder let label: Label

    var body: some View {
        label
            .contentShape(Rectangle())
            .onTapGesture(perform: action)
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isButton)
            .accessibilityHint(hint)
            .accessibilityAction { action() }
    }
}

/// Trust words are hidden by default (UI review, 2026-11-09): tapping a number, or a crowd or note
/// line, shows its trust word and the file's source in a small popover.
struct TrustTap<Content: View>: View {
    let trust: Trust?
    let source: String?
    @ViewBuilder let content: Content
    @State private var shown = false

    var body: some View {
        if let trust {
            CleanTap(hint: "Shows how this was worked out") { shown = true } label: { content }
                .popover(isPresented: $shown, arrowEdge: .bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(trust.text.prefix(1).uppercased() + trust.text.dropFirst())
                            .typeStyle(.label).foregroundStyle(Palette.ink.color)
                        if let source, !source.isEmpty {
                            Text(source)
                                .typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(14)
                    .frame(width: 260, alignment: .leading)
                    .presentationCompactAdaptation(.popover)
                    .presentationBackground(Palette.surfaceSheet.color)
                }
        } else {
            content
        }
    }
}

/// "I ran it" (outline, ink, with a check) beside the primary action: Share route, or "Run again"
/// for a route opened from History.
struct ActionRow: View {
    let model: MainModel
    @State private var shareItem: ShareItem?

    var body: some View {
        HStack(spacing: 10) {
            if model.currentRoute != nil {
                Button { model.ranIt() } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark").font(.system(size: 14, weight: .semibold))
                        Text("I ran it")
                    }
                    .typeStyle(.bodyStrong)
                    .foregroundStyle(Palette.ink.color)
                    .padding(.horizontal, 18)
                    .frame(height: 54)
                    .overlay(RoundedRectangle(cornerRadius: Metrics.radiusButton).strokeBorder(Palette.ink.color, lineWidth: 1.5))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint("Marks this route as run, then asks how it was")
            }
            if model.cardMode == .history {
                Button { model.runAgain() } label: {
                    Text("Run again")
                        .typeStyle(.bodyStrong)
                        .foregroundStyle(Palette.onAction.color)
                        .frame(maxWidth: .infinity)
                        .frame(height: 54)
                        .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).fill(Palette.action.color))
                }
                .buttonStyle(.plain)
            } else {
                ShareButton {
                    if let url = model.gpxFileOfShown() { shareItem = ShareItem(url: url) }
                }
            }
        }
        .sheet(item: $shareItem) { item in
            ShareSheet(url: item.url) { completed in
                shareItem = nil
                if completed { model.sharedRoute() }
            }
            .presentationDetents([.medium, .large])
        }
    }
}

/// The bookmark beside the ×: fills when the route is saved.
struct BookmarkButton: View {
    let saved: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: saved ? "bookmark.fill" : "bookmark")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(saved ? Palette.ink.color : Palette.inkMuted.color)
                .frame(width: 30, height: 30)
                .background(Circle().fill(Palette.surfaceSunken.color))
                .frame(width: Metrics.minTap, height: Metrics.minTap)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(saved ? "Saved" : "Save route")
        .accessibilityHint(saved ? "Removes it from your runs" : "Keeps it in your runs")
    }
}

/// "How was it?": Good saves with one tap; Not for me shows reasons to pick any of, then Done.
/// "Not now" leaves the run marked without a rating (it can be rated later from History).
struct RatingContent: View {
    let model: MainModel
    let state: MainModel.RatingState
    @FocusState private var noteFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Capsule().fill(Palette.grabber.color).frame(width: 36, height: 4)
                .frame(maxWidth: .infinity).padding(.top, 10)
            Text("How was it?").typeStyle(.request).foregroundStyle(Palette.ink.color)
                .padding(.top, 14).accessibilityAddTraits(.isHeader)
            Text("\(state.route.name) · \(CardText.miles(state.route.distanceMi))")
                .typeStyle(.body).foregroundStyle(Palette.inkMuted.color).padding(.top, 4)
            HStack(spacing: 10) {
                choice("Good", selected: false) { model.rateGood() }
                choice("Not for me", selected: state.notForMe) { model.chooseNotForMe() }
            }
            .padding(.top, 18)
            if state.notForMe {
                Text("What got in the way? Pick any.").typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                    .padding(.top, 18)
                FlowLayout(spacing: 8, lineSpacing: 8) {
                    ForEach(RunRating.reasonPills, id: \.key) { r in
                        let on = state.reasons.contains(r.key)
                        Button { model.toggleReason(r.key) } label: {
                            Text(r.text).typeStyle(.label)
                                .foregroundStyle(on ? Palette.surfaceSheet.color : Palette.ink.color)
                                .padding(.horizontal, 14).frame(height: 36)
                                .background(Capsule().fill(on ? Palette.ink.color : Palette.surfaceSunken.color))
                                .frame(minHeight: Metrics.minTap)
                        }
                        .buttonStyle(.plain)
                        .accessibilityAddTraits(on ? .isSelected : [])
                    }
                }
                .padding(.top, 8)
                if state.reasons.contains("other") {
                    TextField("", text: Binding(get: { model.rating?.note ?? "" }, set: { model.rating?.note = String($0.prefix(500)) }),
                              prompt: Text("Tell us more (optional)").foregroundStyle(Palette.inkMuted.color))
                        .typeStyle(.field).foregroundStyle(Palette.ink.color).tint(Palette.focusRing.color)
                        .focused($noteFocused)
                        .submitLabel(.done)
                        .padding(.horizontal, 18).frame(height: 46)
                        .background(Capsule().fill(Palette.surfaceSunken.color))
                        .padding(.top, 10)
                }
                HStack {
                    Spacer()
                    Button("Done") { noteFocused = false; model.finishNotForMe() }
                        .typeStyle(.bodyStrong).foregroundStyle(Palette.action.color)
                        .frame(minHeight: Metrics.minTap)
                }
                .padding(.top, 4)
            } else {
                Button("Not now") { model.closeRating() }
                    .typeStyle(.body).foregroundStyle(Palette.inkMuted.color)
                    .frame(maxWidth: .infinity, minHeight: Metrics.minTap)
                    .padding(.top, 6)
                    .accessibilityHint("Keeps the run marked without a rating")
            }
        }
        .padding(.bottom, 6)
    }

    private func choice(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .typeStyle(.bodyStrong)
                .foregroundStyle(selected ? Palette.surfaceSheet.color : Palette.ink.color)
                .frame(maxWidth: .infinity)
                .frame(height: 54)
                .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).fill(selected ? Palette.ink.color : .clear))
                .overlay(RoundedRectangle(cornerRadius: Metrics.radiusButton).strokeBorder(Palette.ink.color, lineWidth: 1.5))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

/// The primary action: opens the iOS share sheet with the route as a GPX file (AirDrop, Files, a
/// running app). It says nothing is sent until the runner picks a place; no confirmation of its own.
struct ShareButton: View {
    var onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 8) {
                Image(systemName: "square.and.arrow.up").font(.system(size: 15, weight: .semibold))
                Text("Share route")
            }
            .typeStyle(.bodyStrong)
            .foregroundStyle(Palette.onAction.color)
            .frame(maxWidth: .infinity)
            .frame(height: 54)
            .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).fill(Palette.action.color))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Share route")
        .accessibilityHint("Opens the share sheet with this route as a GPX file")
    }
}

/// A file ready for the share sheet.
struct ShareItem: Identifiable {
    let id = UUID()
    let url: URL
}

/// UIKit's share sheet for one file.
struct ShareSheet: UIViewControllerRepresentable {
    let url: URL
    var onDone: (Bool) -> Void

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let vc = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        vc.completionWithItemsHandler = { _, completed, _, _ in
            try? FileManager.default.removeItem(at: url)
            onDone(completed)
        }
        return vc
    }

    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
