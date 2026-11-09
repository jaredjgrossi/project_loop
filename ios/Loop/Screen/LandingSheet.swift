import SwiftUI
import UIKit

/// The landing sheet (UI chat, 2026-11-09; modeled on Apple Maps' home sheet, minimal): the request
/// field, "Your runs" tiles, and "Recent". It rises at launch, slides away on send, and drags up for
/// more recent rows. Design-system tokens only; no data (mono) styling on this screen.
struct LandingSheet: View {
    let model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var sheet: SheetState { model.landing }
    private var runs: RunStore { model.runs }

    var body: some View {
        let height = sheet.height
        let rest = sheet.collapsedHeight
        VStack(alignment: .leading, spacing: 0) {
            Capsule()
                .fill(Palette.grabber.color)
                .frame(width: 36, height: 4)
                .padding(.top, 10)
                .frame(maxWidth: .infinity)
                .frame(height: 14, alignment: .top)
                .accessibilityHidden(runs.recents.count < 2)
                .accessibilityElement()
                .accessibilityLabel(sheet.restingOpen ? "Show fewer recent runs" : "Show more recent runs")
                .accessibilityAddTraits(.isButton)
                .accessibilityAction { sheet.settle(open: !sheet.restingOpen, animated: !reduceMotion) }

            RequestField(model: model)
                .padding(.top, 10)

            Text("Your runs")
                .typeStyle(.eyebrow)
                .foregroundStyle(Palette.inkMuted.color)
                .padding(.top, 22)
                .accessibilityAddTraits(.isHeader)

            TileRow(model: model)
                .padding(.top, 12)
                .background(rowBottom(isLast: runs.recents.isEmpty))

            if let first = runs.recents.first {
                Text("Recent")
                    .typeStyle(.eyebrow)
                    .foregroundStyle(Palette.inkMuted.color)
                    .padding(.top, 20)
                    .accessibilityAddTraits(.isHeader)
                RecentRow(recent: first) { model.openRun(request: first.request) }
                    .padding(.top, 4)
                    .background(rowBottom(isLast: true))
                // More rows, revealed by dragging up.
                ForEach(runs.recents.dropFirst()) { recent in
                    RecentRow(recent: recent) { model.openRun(request: recent.request) }
                        .opacity(Double(sheet.progress))
                        .accessibilityHidden(sheet.progress < 0.5)
                }
            }
        }
        // Measured in the content's own space, inside the slide offset (else each measurement
        // would move the sheet and feed the next).
        .coordinateSpace(name: "landing")
        .padding(.horizontal, Metrics.s24)
        .background(GeometryReader { g in
            Color.clear
                .onAppear { setOpen(g.size.height) }
                .onChange(of: g.size.height) { _, h in setOpen(h) }
        })
        .frame(height: max(height, rest), alignment: .top)
        .frame(maxWidth: .infinity)
        .background(sheetBackground)
        .clipped()
        .offset(y: max(0, rest - height))
        .contentShape(Rectangle())
        .gesture(drag)
    }

    /// The collapsed rest ends just under the first recent row (or the tiles, with no recents).
    private func rowBottom(isLast: Bool) -> some View {
        GeometryReader { g in
            Color.clear
                .onAppear { if isLast { setCollapsed(g.frame(in: .named("landing")).maxY) } }
                .onChange(of: g.frame(in: .named("landing")).maxY) { _, y in if isLast { setCollapsed(y) } }
        }
    }

    private func setCollapsed(_ contentBottom: CGFloat) {
        let h = (contentBottom + 14 + Self.bottomInset).rounded()
        guard abs(h - sheet.baseCollapsed) > 0.5 else { return }
        let wasOpen = sheet.baseOpen
        sheet.baseCollapsed = h
        sheet.baseOpen = max(h, wasOpen)
        if model.landingShown { sheet.refreshRest() }
    }

    /// Dragged up, the sheet shows every recent row, up to three quarters of the screen.
    private func setOpen(_ contentHeight: CGFloat) {
        let full = (contentHeight + 14 + Self.bottomInset).rounded()
        sheet.baseOpen = max(sheet.baseCollapsed, min(full, UIScreen.main.bounds.height * 0.75))
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

    private var drag: some Gesture {
        DragGesture(minimumDistance: 6, coordinateSpace: .global)
            .onChanged { v in sheet.drag(translation: v.translation.height) }
            .onEnded { v in sheet.endDrag(predictedTranslation: v.predictedEndTranslation.height, animated: !reduceMotion) { _ in } }
    }
}

/// The request field at the top of the landing sheet: sunken, Fraunces placeholder. At launch it
/// types an example in the placeholder colour; tapped, it takes the runner's words, and go sends.
struct RequestField: View {
    let model: MainModel
    @State private var draft = ""
    @FocusState private var focused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private static let style = TypeStyle(family: .fraunces, size: 20, lineHeight: 24, weight: 400)

    var body: some View {
        let typing = model.stage == .typing
        HStack(spacing: 12) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(Palette.inkMuted.color)
            ZStack(alignment: .leading) {
                if !typing || (draft.isEmpty && !model.demoTyping) {
                    Text(model.fieldExample.isEmpty ? "Describe your run" : model.fieldExample)
                        .typeStyle(Self.style)
                        .foregroundStyle(Palette.inkMuted.color)
                        .lineLimit(1)
                        .accessibilityHidden(true)
                }
                TextField("", text: $draft)
                    .typeStyle(Self.style)
                    .foregroundStyle(Palette.ink.color)
                    .tint(Palette.focusRing.color)
                    .focused($focused)
                    .submitLabel(.go)
                    .onSubmit { model.send(draft, reduceMotion: reduceMotion); draft = ""; focused = false }
                    .opacity(typing ? 1 : 0.011)
                    .accessibilityLabel("Describe your run")
            }
        }
        .padding(.horizontal, 18)
        .frame(height: 50)
        .background(Capsule().fill(Palette.surfaceSunken.color))
        .overlay(Capsule().strokeBorder(Palette.focusRing.color, lineWidth: 1.5).opacity(typing ? 1 : 0))
        .contentShape(Capsule())
        .onTapGesture { model.beginTyping(); focused = true }
        .onChange(of: model.stage) { _, stage in
            guard stage == .typing else { return }
            // The debug demo "taps and sends" the example itself, without the keyboard.
            if model.demoTyping { draft = model.fieldExample } else { focused = true }
        }
    }
}

/// "Your runs": the runner's runs, then suggestions, then a dashed Save tile.
private struct TileRow: View {
    let model: MainModel

    var body: some View {
        GeometryReader { g in
            let side = ((g.size.width - 3 * 12) / 4).rounded(.down)
            HStack(alignment: .top, spacing: 12) {
                ForEach(model.runs.saved.prefix(3)) { run in
                    RunTile(side: side, name: run.name, detail: CardText.miles(run.distanceMi), shape: run.shape) {
                        model.openRun(request: run.request)
                    }
                }
                ForEach(model.runs.suggestedTiles) { s in
                    RunTile(side: side, name: s.name, detail: nil, shape: nil) {
                        model.send(s.request, reduceMotion: false)
                    }
                }
                SaveTile(side: side)
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
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 6) {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Palette.surfaceSunken.color)
                    .overlay(RouteThumbnail(shape: shape, lineWidth: 2.4, dot: 7))
                    .frame(width: side, height: side)
                VStack(spacing: 0) {
                    Text(name)
                        .typeStyle(TypeStyle(family: .instrumentSans, size: 14, lineHeight: 18, weight: 500))
                        .foregroundStyle(Palette.ink.color)
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
    }
}

/// The dashed last tile. What it does from here is still open, so it isn't a button yet.
private struct SaveTile: View {
    let side: CGFloat

    var body: some View {
        VStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Palette.lineControl.color.opacity(0.7), style: StrokeStyle(lineWidth: 1.2, dash: [4, 4]))
                .overlay(Image(systemName: "plus").font(.system(size: 18, weight: .regular)).foregroundStyle(Palette.inkMuted.color))
                .frame(width: side, height: side)
            Text("Save")
                .typeStyle(TypeStyle(family: .instrumentSans, size: 14, lineHeight: 18, weight: 500))
                .foregroundStyle(Palette.inkMuted.color)
        }
        .frame(width: side)
        .accessibilityElement(children: .combine)
    }
}

private struct RecentRow: View {
    let recent: RecentRoute
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                RouteThumbnail(shape: recent.shape, lineWidth: 1.8, dot: 0, inset: 0.06)
                    .frame(width: 26, height: 26)
                Text(Self.sentence(recent.request))
                    .typeStyle(.body)
                    .foregroundStyle(Palette.ink.color)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(RunStore.dayText(recent.date))
                    .typeStyle(TypeStyle(family: .instrumentSans, size: 14, lineHeight: 18, weight: 400))
                    .foregroundStyle(Palette.inkMuted.color)
            }
            .frame(height: 40)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    /// The request as the runner typed it, without the full stop the header adds.
    static func sentence(_ s: String) -> String { s.hasSuffix(".") ? String(s.dropLast()) : s }
}

/// A route's own shape as a small line drawing: route-water line, vermilion start dot. With no
/// route yet (a suggestion), a neutral dashed loop.
struct RouteThumbnail: View {
    let shape: [[Double]]?
    var lineWidth: CGFloat = 2.4
    var dot: CGFloat = 7
    /// Margin as a share of the side.
    var inset: CGFloat = 0.22

    var body: some View {
        Canvas { ctx, size in
            let side = min(size.width, size.height)
            let box = CGRect(x: (size.width - side) / 2 + side * inset, y: (size.height - side) / 2 + side * inset,
                             width: side * (1 - 2 * inset), height: side * (1 - 2 * inset))
            guard let pts = shape.map(Self.project), pts.count >= 2 else {
                let ring = Path(ellipseIn: box.insetBy(dx: box.width * 0.08, dy: box.height * 0.08))
                ctx.stroke(ring, with: .color(Palette.lineControl.color.opacity(0.8)),
                           style: StrokeStyle(lineWidth: 1.6, lineCap: .round, dash: [3, 4.5]))
                return
            }
            let fitted = Self.fit(pts, in: box)
            var path = Path()
            path.addLines(fitted)
            ctx.stroke(path, with: .color(Palette.routeWater.color),
                       style: StrokeStyle(lineWidth: lineWidth, lineCap: .round, lineJoin: .round))
            if dot > 0, let s = fitted.first {
                ctx.fill(Path(ellipseIn: CGRect(x: s.x - dot / 2, y: s.y - dot / 2, width: dot, height: dot)),
                         with: .color(Palette.accentStart.color))
            }
        }
        .accessibilityHidden(true)
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
/// (Instrument Sans, ink-muted). WeatherKit needs the paid developer program, so Debug builds
/// show fixed sample weather and Release builds show nothing until it's wired.
struct WeatherLine: View {
    struct Reading { let symbol: String; let temperature: String }

    static var reading: Reading? {
        #if DEBUG
        Reading(symbol: "cloud.sun", temperature: "48°")
        #else
        nil
        #endif
    }

    var body: some View {
        if let r = Self.reading {
            TimelineView(.everyMinute) { context in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: r.symbol)
                        .symbolRenderingMode(.monochrome)
                        .font(.system(size: 14, weight: .regular))
                        .foregroundStyle(Palette.inkMuted.color)
                    Text(r.temperature)
                        .typeStyle(TypeStyle(family: .fraunces, size: 18, lineHeight: 22, weight: 400))
                        .foregroundStyle(Palette.inkSoft.color)
                    Text("· " + Self.dayTime(context.date))
                        .typeStyle(TypeStyle(family: .instrumentSans, size: 15, lineHeight: 20, weight: 400))
                        .foregroundStyle(Palette.inkMuted.color)
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(r.temperature), sample weather, \(Self.dayTime(context.date))")
            }
        }
    }

    static func dayTime(_ date: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US")
        f.dateFormat = "EEE h:mm"
        return f.string(from: date)
    }
}
