import SwiftUI
import UIKit

/// The landing sheet (UI chat, 2026-11-09; modeled on Apple Maps' home sheet, minimal): the request
/// field, "Your runs" tiles, and "Recent". Three rests on the route card's `SheetState`: collapsed
/// (just the field, the map takes the rest), open (field, runs, first recent row: how it arrives),
/// and, with more recents, a taller rest showing them. It rises at launch and slides away on send.
/// Design-system tokens only; no data (mono) styling on this screen.
struct LandingSheet: View {
    let model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var sheet: SheetState { model.landing }
    private var runs: RunStore { model.runs }
    /// This drag began while typing: it only dismisses the keyboard.
    @State private var keyboardDrag = false

    var body: some View {
        let height = sheet.height
        // Rising or sliding away, the sheet moves whole (anchored at its rest); otherwise it is
        // clipped to its height, and below the collapsed rest it moves down whole.
        let anchor = model.landingAnchor
        let frameHeight = anchor ?? max(height, sheet.collapsedHeight)
        let offset = max(0, (anchor ?? sheet.collapsedHeight) - height)
        let expanded = Double(sheet.progress)
        let searching = model.searchMode

        VStack(alignment: .leading, spacing: 0) {
            Capsule()
                .fill(Palette.grabber.color)
                .frame(width: 36, height: 4)
                .padding(.top, 10)
                .frame(maxWidth: .infinity)
                .frame(height: 24, alignment: .top)
                .contentShape(Rectangle())
                .onTapGesture { toggle() }
                .accessibilityElement()
                .accessibilityLabel(sheet.restingOpen ? "Hide your runs" : "Show your runs")
                .accessibilityAddTraits(.isButton)
                .accessibilityAction { toggle() }

            // "Did you run the … route this morning?": once per route, within 24 h, above the field.
            if let v = model.returnPrompt, !searching {
                ReturnPrompt(model: model, viewed: v)
                    .padding(.bottom, 16)
                    .transition(.opacity)
            }

            RequestField(model: model)
                .background(bottomReader { setCollapsed($0) })

            // The launch health check failed: one plain line, never a spinner.
            if model.serverDown {
                HStack(spacing: 10) {
                    Text(MainModel.LiveCopy.unreachable)
                        .typeStyle(.label)
                        .foregroundStyle(Palette.inkSoft.color)
                    Spacer(minLength: 8)
                    Button("Try again") { model.checkHealth() }
                        .typeStyle(.label)
                        .foregroundStyle(Palette.action.color)
                        .frame(minHeight: Metrics.minTap)
                }
                .padding(.top, 2)
                .transition(.opacity)
            }

            // Outside the covered area (checked on the phone): one quiet line, with the area's own name.
            if let name = model.outsideCoverageName, !model.serverDown {
                Text("Loop covers \(name) for now.")
                    .typeStyle(.label)
                    .foregroundStyle(Palette.inkSoft.color)
                    .padding(.top, 10)
                    .transition(.opacity)
            }

            // Runs and Recent, or the typing list: both in place under the field, crossfading (200 ms).
            ZStack(alignment: .top) {
                if searching {
                    VStack(alignment: .leading, spacing: 0) {
                        // The route type before sending: preselected from your defaults; a pick here
                        // beats the words and goes as the request's shape. The sentence stays as typed.
                        RouteTypeControl(selection: model.pickedShape) { s in
                            model.pickedShape = s
                            model.shapeTouched = true
                        }
                        .padding(.top, 10)
                        MatchList(model: model)
                    }
                    .background(bottomReader { model.searchListMeasured($0) })
                    .transition(.opacity)
                }

                if !searching {
                VStack(alignment: .leading, spacing: 0) {
                    VStack(alignment: .leading, spacing: 0) {
                        // Until the runner has saved or run a route, the tiles are Loop's suggestions.
                        Text(runs.saved.isEmpty && runs.runs.isEmpty ? "Try one" : "Your runs")
                            .typeStyle(.eyebrow)
                            .foregroundStyle(Palette.inkMuted.color)
                            .padding(.top, 22)
                            .accessibilityAddTraits(.isHeader)

                        TileRow(model: model, hidden: searching || expanded < 0.5)
                            .padding(.top, 12)
                            .background(bottomReader { if runs.runs.isEmpty { setOpen($0) } })

                        // History (replaces Recent): routes marked as run, newest first.
                        if let first = runs.runs.first {
                            Text("History")
                                .typeStyle(.eyebrow)
                                .foregroundStyle(Palette.inkMuted.color)
                                .padding(.top, 20)
                                .accessibilityAddTraits(.isHeader)
                            HistoryRow(log: first) { model.openHistory(first) }
                                .padding(.top, 2)
                                .accessibilityHidden(expanded < 0.5)
                                .background(bottomReader { setOpen($0) })
                        }
                    }
                    .opacity(expanded)
                    .accessibilityHidden(expanded < 0.5 || searching)

                    // The full list, revealed by pulling the sheet up past the open rest.
                    ForEach(runs.runs.dropFirst()) { log in
                        HistoryRow(log: log) { model.openHistory(log) }
                            .opacity(Double(sheet.readProgress))
                            .accessibilityHidden(sheet.readProgress < 0.5)
                            .allowsHitTesting(sheet.readProgress > 0.5)
                    }
                }
                .transition(.opacity)
                }
            }
            .animation(reduceMotion ? nil : Motion.crossfade, value: searching)
        }
        // Measured in the content's own space, inside the slide offset (else each measurement
        // would move the sheet and feed the next).
        .coordinateSpace(name: "landing")
        .padding(.horizontal, Metrics.s24)
        .background(GeometryReader { g in
            Color.clear
                .onAppear { setFull(g.size.height) }
                .onChange(of: g.size.height) { _, h in setFull(h) }
        })
        .frame(height: frameHeight, alignment: .top)
        .frame(maxWidth: .infinity)
        // Everything stays inside the sheet's shape while it resizes.
        .clipShape(UnevenRoundedRectangle(topLeadingRadius: Metrics.radiusSheet, topTrailingRadius: Metrics.radiusSheet))
        .background(sheetBackground)
        .offset(y: offset)
        .contentShape(Rectangle())
        // A tap on any part of the sheet that isn't a control ends editing.
        .onTapGesture { model.endTyping() }
        .gesture(drag)
    }

    /// Tapping the handle: collapsed opens; open (or taller) collapses. While typing it only ends editing.
    private func toggle() {
        if model.searchMode { model.endTyping(); return }
        sheet.settle(rest: sheet.restingOpen ? .collapsed : .open, animated: !reduceMotion)
    }

    private func bottomReader(_ report: @escaping (CGFloat) -> Void) -> some View {
        GeometryReader { g in
            Color.clear
                .onAppear { report(g.frame(in: .named("landing")).maxY) }
                .onChange(of: g.frame(in: .named("landing")).maxY) { _, y in report(y) }
        }
    }

    /// Collapsed: just the field.
    private func setCollapsed(_ fieldBottom: CGFloat) {
        model.landingFieldBottom = fieldBottom
        let h = (fieldBottom + 12 + Self.bottomInset).rounded()
        guard abs(sheet.baseCollapsed - h) > 0.5 else { return }
        sheet.baseCollapsed = h
        refresh()
    }

    /// Open: down to the first recent row (or the tiles, with no recents).
    private func setOpen(_ contentBottom: CGFloat) {
        let h = (contentBottom + 14 + Self.bottomInset).rounded()
        guard abs(sheet.baseOpen - h) > 0.5 else { return }
        sheet.baseOpen = h
        refresh()
    }

    /// Taller: every recent row, up to three quarters of the screen; none with one recent.
    private func setFull(_ contentHeight: CGFloat) {
        guard !model.searchMode else { return }
        let full = min((contentHeight + 14 + Self.bottomInset).rounded(), UIScreen.main.bounds.height * 0.75)
        let read: CGFloat? = runs.runs.count > 1 && full > sheet.baseOpen + 1 ? full : nil
        guard read != sheet.readHeight else { return }
        sheet.readHeight = read
        refresh()
    }

    private func refresh() {
        if model.landingShown, model.landingAnchor == nil, !model.searchMode { sheet.refreshRest() }
    }

    static var bottomInset: CGFloat {
        let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene
        return scene?.keyWindow?.safeAreaInsets.bottom ?? 34
    }

    private var sheetBackground: some View {
        UnevenRoundedRectangle(topLeadingRadius: Metrics.radiusSheet, topTrailingRadius: Metrics.radiusSheet)
            .fill(Palette.surfaceSheet.color)
            .overlay(
                UnevenRoundedRectangle(topLeadingRadius: Metrics.radiusSheet, topTrailingRadius: Metrics.radiusSheet)
                    .stroke(Palette.lineHairline.color, lineWidth: 1)
            )
            .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.08), radius: 15, y: -8)
    }

    /// Same as the route card: 1:1 under the finger, then the 320 ms settle to the nearest rest.
    /// While typing, a drag down only dismisses the keyboard (the list under the field takes it
    /// interactively); the next drag moves the sheet.
    private var drag: some Gesture {
        DragGesture(minimumDistance: 6, coordinateSpace: .global)
            .onChanged { v in
                if model.searchMode || keyboardDrag {
                    keyboardDrag = true
                    if model.searchMode, v.translation.height > 12 { model.endTyping() }
                    return
                }
                guard model.landingAnchor == nil else { return }
                sheet.drag(translation: v.translation.height)
            }
            .onEnded { v in
                if keyboardDrag { keyboardDrag = false; return }
                guard model.landingAnchor == nil else { return }
                sheet.endDrag(predictedTranslation: v.predictedEndTranslation.height, animated: !reduceMotion) { _ in }
            }
    }
}

/// The request field at the top of the landing sheet: sunken, Fraunces placeholder. At launch it
/// types an example in the placeholder colour; once the runner focuses it, the example stops and
/// the field is empty with a static "Describe your run" until they type. While focused, "Cancel"
/// sits to its right (ends editing, clears the field). Go sends.
struct RequestField: View {
    @Bindable var model: MainModel
    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let style = TypeStyle.field
    /// "Cancel" in body plus its 14 pt gap.
    private static let cancelWidth: CGFloat = 72

    var body: some View {
        let typing = model.stage == .typing
        let editing = model.searchMode
        HStack(spacing: 0) {
            HStack(spacing: 12) {
                Image(systemName: "magnifyingglass")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Palette.inkMuted.color)
                ZStack(alignment: .leading) {
                    if model.fieldText.isEmpty {
                        // The launch example (placeholder colour) until focused, then the static placeholder.
                        Text(editing || model.fieldExample.isEmpty ? "Describe your run" : model.fieldExample)
                            .typeStyle(Self.style)
                            .foregroundStyle(Palette.inkMuted.color)
                            .lineLimit(1)
                            .accessibilityHidden(true)
                    }
                    TextField("", text: $model.fieldText)
                        .typeStyle(Self.style)
                        .foregroundStyle(Palette.ink.color)
                        .tint(Palette.focusRing.color)
                        .focused($focused)
                        .submitLabel(.go)
                        .onSubmit { model.send(model.fieldText, reduceMotion: reduceMotion) }
                        .accessibilityLabel("Describe your run")
                }
            }
            .padding(.horizontal, 18)
            .frame(height: 50)
            .background(Capsule().fill(Palette.surfaceSunken.color))
            .overlay(Capsule().strokeBorder(Palette.focusRing.color, lineWidth: 1.5).opacity(typing ? 1 : 0))
            .contentShape(Capsule())
            .onTapGesture { focused = true }

            // Cancel fades in beside the same field (the field narrows to make room); never a copy.
            ZStack(alignment: .leading) {
                if editing {
                    Button("Cancel") { model.cancelTyping() }
                        .typeStyle(.body)
                        .foregroundStyle(Palette.ink.color)
                        .fixedSize()
                        .frame(minHeight: Metrics.minTap)
                        .padding(.leading, 14)
                        .transition(.opacity)
                }
            }
            .frame(width: editing ? Self.cancelWidth : 0, alignment: .leading)
            .clipped()
        }
        .animation(reduceMotion ? nil : Motion.crossfade, value: editing)
        .onChange(of: focused) { _, isFocused in
            if isFocused { model.beginTyping() } else if model.searchMode { model.endTyping() }
        }
        .onChange(of: model.stage) { _, stage in
            if stage == .typing, model.demoTyping {
                // The debug demo "taps and sends" the example itself, without the keyboard.
                model.fieldText = model.fieldExample
            } else if stage != .typing {
                focused = false
            }
        }
        .onChange(of: model.focusFieldRequest) { _, _ in focused = true }
    }
}

/// While typing: recent requests and saved runs matching the text when typing started, newest
/// first, up to four; they stay put as the runner types. A tap fills the field and sends.
/// Dragging the list down takes the keyboard with the finger.
private struct MatchList: View {
    let model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let matches = model.fieldMatches
        ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                ForEach(matches) { m in
                    RecentRow(title: m.title, date: m.date, shape: m.shape, hidden: !model.searchMode) {
                        model.fieldText = m.request
                        model.send(m.request, reduceMotion: reduceMotion)
                    }
                }
            }
        }
        .scrollDismissesKeyboard(.interactively)
        .frame(height: CGFloat(matches.count) * 40)
        .padding(.top, matches.isEmpty ? 0 : 6)
    }
}

/// "Your runs": the runner's runs, then suggestions, then a dashed Save tile.
private struct TileRow: View {
    let model: MainModel
    /// Faded out (typing, or the sheet collapsed): hidden from VoiceOver and taps.
    var hidden = false

    var body: some View {
        GeometryReader { g in
            let side = ((g.size.width - 3 * 12) / 4).rounded(.down)
            HStack(alignment: .top, spacing: 12) {
                // Saved routes, their real shape; long-press for Rename and Remove.
                ForEach(model.runs.saved.prefix(3)) { run in
                    RunTile(side: side, name: run.name, detail: nil, shape: run.shape, hidden: hidden) {
                        model.openSaved(run)
                    }
                    .contextMenu { SavedTileMenu(model: model, saved: run) }
                }
                ForEach(model.runs.suggestedTiles(outsideCoverage: model.outsideCoverageName != nil)) { s in
                    RunTile(side: side, name: s.name, detail: nil, shape: nil, glyph: s.glyph, hidden: hidden) {
                        model.send(s.request, reduceMotion: false)
                    }
                }
                SaveTile(side: side, hidden: hidden)
            }
        }
        .frame(height: Self.height(width: UIScreen.main.bounds.width - 2 * Metrics.s24))
    }

    /// The tile, then two label lines (a name and distance, or a two-line suggestion).
    static func height(width: CGFloat) -> CGFloat { ((width - 36) / 4).rounded(.down) + 6 + 36 }
}

private struct RunTile: View {
    let side: CGFloat
    let name: String
    let detail: String?
    let shape: [[Double]]?
    var glyph: SuggestedRun.Glyph? = nil
    var hidden = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 6) {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Palette.surfaceSunken.color)
                    .overlay(RouteThumbnail(shape: shape, glyph: glyph, lineWidth: 2.4, dot: 7)
                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous)))
                    .frame(width: side, height: side)
                VStack(spacing: 0) {
                    TileLabel(name: name, side: side, overhang: detail == nil ? 5 : 0)
                    if let detail {
                        Text(detail)
                            .typeStyle(.label)
                            .foregroundStyle(Palette.inkMuted.color)
                    }
                }
                .lineLimit(detail == nil ? 2 : 1)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(width: side + 10)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .frame(width: side)
        .accessibilityLabel(detail.map { "\(name), \($0)" } ?? name)
        .accessibilityHint(shape == nil ? "Sends this request" : "Shows this route")
        .accessibilityHidden(hidden)
        .allowsHitTesting(!hidden)
    }
}

/// The name under a tile. As wide as the tile, so a long name wraps inside it and never runs
/// into its neighbour or off the edge of a scrolling row. A name that fits on one line with up
/// to `overhang` points to spare on each side keeps its line ("3 mi from here" is a hair wider
/// than its tile). A long unbreakable word tightens, then shrinks a little, before it truncates.
struct TileLabel: View {
    let name: String
    let side: CGFloat
    var overhang: CGFloat = 0

    var body: some View {
        let name = CardText.unbroken(name)
        ViewThatFits(in: .horizontal) {
            Text(name)
                .typeStyle(.label)
                .lineLimit(1)
                .fixedSize()
            Text(name)
                .typeStyle(.label)
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .allowsTightening(true)
                .minimumScaleFactor(0.88)
                .fixedSize(horizontal: false, vertical: true)
                .frame(width: side)
        }
        .foregroundStyle(Palette.ink.color)
        .frame(width: side + 2 * overhang)
    }
}

/// The dashed last tile. What it does from here is still open, so it isn't a button yet.
private struct SaveTile: View {
    let side: CGFloat
    var hidden = false

    var body: some View {
        VStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Palette.lineControl.color.opacity(0.7), style: StrokeStyle(lineWidth: 1.2, dash: [4, 4]))
                .overlay(Image(systemName: "plus").font(.system(size: 18, weight: .regular)).foregroundStyle(Palette.inkMuted.color))
                .frame(width: side, height: side)
            Text("Save")
                .typeStyle(.label)
                .foregroundStyle(Palette.inkMuted.color)
        }
        .frame(width: side)
        .accessibilityElement(children: .combine)
        .accessibilityHidden(hidden)
    }
}

private struct RecentRow: View {
    let title: String
    let date: Date
    let shape: [[Double]]
    var hidden = false
    let action: () -> Void

    init(recent: RecentRoute, hidden: Bool = false, action: @escaping () -> Void) {
        self.init(title: RunStore.sentence(recent.request), date: recent.date, shape: recent.shape, hidden: hidden, action: action)
    }

    init(title: String, date: Date, shape: [[Double]], hidden: Bool = false, action: @escaping () -> Void) {
        self.title = title; self.date = date; self.shape = shape; self.hidden = hidden; self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                RouteThumbnail(shape: shape, lineWidth: 1.8, dot: 0, inset: 0.06)
                    .frame(width: 26, height: 26)
                Text(CardText.unbroken(title))
                    .typeStyle(.body)
                    .foregroundStyle(Palette.ink.color)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(RunStore.dayText(date))
                    .typeStyle(.label)
                    .foregroundStyle(Palette.inkMuted.color)
            }
            .frame(height: 40)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHidden(hidden)
        .allowsHitTesting(!hidden)
    }
}

/// A route's own shape as a small line drawing: route-water line, vermilion start dot. A suggestion
/// (no route yet) draws its glyph in the same style instead. Never an empty placeholder.
struct RouteThumbnail: View {
    let shape: [[Double]]?
    var glyph: SuggestedRun.Glyph? = nil
    var lineWidth: CGFloat = 2.4
    var dot: CGFloat = 7
    /// Margin as a share of the side.
    var inset: CGFloat = 0.22

    var body: some View {
        Canvas { ctx, size in
            let side = min(size.width, size.height)
            let box = CGRect(x: (size.width - side) / 2 + side * inset, y: (size.height - side) / 2 + side * inset,
                             width: side * (1 - 2 * inset), height: side * (1 - 2 * inset))
            let line: Path, start: CGPoint
            if let pts = shape.map(Self.project), pts.count >= 2 {
                let fitted = Self.fit(pts, in: box)
                var path = Path()
                path.addLines(fitted)
                line = path; start = fitted[0]
            } else if let glyph {
                (line, start) = Self.glyph(glyph, in: box, ctx: ctx)
            } else {
                return
            }
            ctx.stroke(line, with: .color(Palette.routeWater.color),
                       style: StrokeStyle(lineWidth: lineWidth, lineCap: .round, lineJoin: .round))
            if dot > 0 {
                ctx.fill(Path(ellipseIn: CGRect(x: start.x - dot / 2, y: start.y - dot / 2, width: dot, height: dot)),
                         with: .color(Palette.accentStart.color))
            }
        }
        .accessibilityHidden(true)
    }

    /// The suggestion glyphs, drawn in the unit box. Returns the route-style line and its start.
    static func glyph(_ glyph: SuggestedRun.Glyph, in box: CGRect, ctx: GraphicsContext) -> (Path, CGPoint) {
        func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: box.minX + x * box.width, y: box.minY + y * box.height) }
        switch glyph {
        case .loop:
            // Out from the dot, round a small loop, and back to the dot.
            var path = Path()
            path.move(to: p(0.30, 0.86))
            path.addCurve(to: p(0.88, 0.58), control1: p(0.56, 0.98), control2: p(0.90, 0.80))
            path.addCurve(to: p(0.50, 0.08), control1: p(0.86, 0.32), control2: p(0.72, 0.08))
            path.addCurve(to: p(0.10, 0.44), control1: p(0.26, 0.08), control2: p(0.08, 0.24))
            path.addCurve(to: p(0.30, 0.86), control1: p(0.12, 0.64), control2: p(0.18, 0.80))
            return (path, p(0.30, 0.86))
        case .water:
            // Water to the right of a wavy shoreline (the map's shore colour) out to the tile's
            // edges (the tile clips it), the line running alongside on the land side, from the dot up.
            func shore(_ y: CGFloat) -> CGFloat { 0.72 + 0.07 * sin(y * .pi * 2.4) }
            let steps = 40
            var water = Path()
            water.move(to: p(shore(-0.6), -0.6))
            for i in 0...steps {
                let y = -0.6 + 2.2 * CGFloat(i) / CGFloat(steps)
                water.addLine(to: p(shore(y), y))
            }
            water.addLine(to: p(2, 1.6))
            water.addLine(to: p(2, -0.6))
            water.closeSubpath()
            ctx.fill(water, with: .color(Palette.mapShore.color))
            var path = Path()
            for i in 0...steps {
                let y = 0.92 - 0.84 * CGFloat(i) / CGFloat(steps)
                let pt = p(shore(y) - 0.24, y)
                if i == 0 { path.move(to: pt) } else { path.addLine(to: pt) }
            }
            return (path, p(shore(0.92) - 0.24, 0.92))
        }
    }

    /// Lon/lat to local metres (equirectangular), y up.
    static func project(_ shape: [[Double]]) -> [CGPoint] {
        guard let first = shape.first, first.count == 2 else { return [] }
        let mx = 111_320 * cos(first[1] * .pi / 180), my = 110_574.0
        return shape.compactMap { p in p.count == 2 ? CGPoint(x: (p[0] - first[0]) * mx, y: (p[1] - first[1]) * my) : nil }
    }

    /// Scales and centres the points in the box, keeping the aspect ratio (y flips to screen).
    static func fit(_ pts: [CGPoint], in box: CGRect) -> [CGPoint] {
        let xs = pts.map(\.x), ys = pts.map(\.y)
        let minX = xs.min()!, maxX = xs.max()!, minY = ys.min()!, maxY = ys.max()!
        let w = max(maxX - minX, 1), h = max(maxY - minY, 1)
        let k = min(box.width / w, box.height / h)
        let ox = box.midX - (minX + w / 2) * k, oy = box.midY + (minY + h / 2) * k
        return pts.map { CGPoint(x: ox + $0.x * k, y: oy - $0.y * k) }
    }
}

/// Under the wordmark on the landing: a weather glyph, the temperature (Fraunces), "· Mon 7:02"
/// (Instrument Sans, ink-muted). The time updates every minute. The temperature refreshes by
/// `WeatherStore`'s rules and is hidden, with its glyph, when there is no fresh reading.
struct WeatherLine: View {
    @Environment(\.scenePhase) private var scenePhase
    private let store = WeatherStore.shared

    var body: some View {
        TimelineView(.everyMinute) { context in
            let r = store.visible(at: context.date)
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                if let r {
                    Image(systemName: r.symbol)
                        .symbolRenderingMode(.monochrome)
                        .font(.system(size: 14, weight: .regular))
                        .foregroundStyle(Palette.inkMuted.color)
                    Text(r.temperature)
                        .typeStyle(.numeralS)
                        .foregroundStyle(Palette.inkSoft.color)
                }
                Text((r == nil ? "" : "· ") + Self.dayTime(context.date))
                    .typeStyle(.body)
                    .foregroundStyle(Palette.inkMuted.color)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(r.map { "\($0.temperature), \(Self.dayTime(context.date))" } ?? Self.dayTime(context.date))
            .accessibilityHint(r.map { $0.source } ?? "")
        }
        .task { await store.run() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await store.refresh() } }
        }
    }

    static func dayTime(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US")
        f.dateFormat = "EEE h:mm"
        return f.string(from: date)
    }
}

/// The return prompt: the route's own thumbnail, "Did you run the … route this morning?", Not today
/// and I ran it (which draws the route and opens the rating).
struct ReturnPrompt: View {
    let model: MainModel
    let viewed: ViewedRoute

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 12) {
                RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Palette.surfaceSheet.color)
                    .overlay(RouteThumbnail(shape: viewed.route.shape, lineWidth: 2, dot: 5, inset: 0.14))
                    .frame(width: 44, height: 44)
                Text(CardText.unbroken(MainModel.promptText(viewed)))
                    .typeStyle(.body).foregroundStyle(Palette.ink.color)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Palette.surfaceSunken.color))
            .accessibilityElement(children: .combine)
            HStack(spacing: 10) {
                Button { model.dismissReturnPrompt() } label: {
                    Text("Not today").typeStyle(.bodyStrong).foregroundStyle(Palette.ink.color)
                        .frame(maxWidth: .infinity).frame(height: 44)
                        .overlay(RoundedRectangle(cornerRadius: Metrics.radiusButton).strokeBorder(Palette.controlBorder.color, lineWidth: 1.5))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                Button { model.ranItFromPrompt() } label: {
                    Text("I ran it").typeStyle(.bodyStrong).foregroundStyle(Palette.onAction.color)
                        .frame(maxWidth: .infinity).frame(height: 44)
                        .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).fill(Palette.action.color))
                }
                .buttonStyle(.plain)
            }
        }
    }
}
