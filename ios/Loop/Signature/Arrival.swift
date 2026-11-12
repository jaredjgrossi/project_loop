import SwiftUI
import UIKit

/// Signature moment F, "The run joins your map" (signature-moments-v1). Behind the lab switch.
///
/// After "I ran it" and a rating, the screen turns to paper. Every run so far is there as faint
/// ink; the one just run draws itself over them in the route's colour. When it lands, the totals
/// roll forward (miles, runs, this week) and the phone plays one long rise and a round finish.
/// It is the moment the app says "that counted", and it gets better with every run.
///
/// The wildcard (F+) lets the runner keep it: a poster of every run as line art on paper, with the
/// miles set large, ready for the share sheet. Each run's first and last 200 m are left off the
/// poster (decision 011: a shared picture never shows a front door).
struct ArrivalState: Identifiable, Equatable {
    /// The run's id in the store.
    let id: String
}

/// The geometry of the runs, for drawing them as line art: one shared frame, north up.
struct RunsInk {
    let lines: [[CGPoint]]   // unit space, y down, aspect kept
    let aspect: CGFloat      // width / height of the runs' bounding box

    init(runs: [[GeoPoint]]) {
        let all = runs.flatMap { $0 }
        guard let first = all.first else { lines = []; aspect = 1; return }
        var minLon = first.lon, maxLon = first.lon, minLat = first.lat, maxLat = first.lat
        for p in all {
            minLon = min(minLon, p.lon); maxLon = max(maxLon, p.lon)
            minLat = min(minLat, p.lat); maxLat = max(maxLat, p.lat)
        }
        // Equirectangular at this latitude is plenty at a city's scale.
        let kx = cos((minLat + maxLat) / 2 * .pi / 180)
        let w = max((maxLon - minLon) * kx, 1e-6), h = max(maxLat - minLat, 1e-6)
        aspect = CGFloat(w / h)
        lines = runs.map { run in
            run.map { CGPoint(x: (($0.lon - minLon) * kx) / w, y: (maxLat - $0.lat) / h) }
        }
    }

    /// A line with its first and last `metres` left off (decision 011), or nothing if too short.
    static func trimmed(_ points: [GeoPoint], metres: Double = 200) -> [GeoPoint] {
        guard points.count >= 2 else { return [] }
        let line = Polyline(points)
        guard line.length > 2 * metres + 100 else { return [] }
        return line.slice(from: metres, to: line.length - metres)
    }
}

/// One run as a shape in a rect (aspect-fit, centred), so `trim` can draw it in.
struct RunShape: Shape {
    let points: [CGPoint]
    let aspect: CGFloat

    func path(in rect: CGRect) -> Path {
        var p = Path()
        guard points.count >= 2 else { return p }
        var w = rect.width, h = rect.width / aspect
        if h > rect.height { h = rect.height; w = h * aspect }
        let ox = rect.midX - w / 2, oy = rect.midY - h / 2
        p.move(to: CGPoint(x: ox + points[0].x * w, y: oy + points[0].y * h))
        for q in points.dropFirst() { p.addLine(to: CGPoint(x: ox + q.x * w, y: oy + q.y * h)) }
        return p
    }
}

/// Every run as faint ink, darker where they overlap, and one run in the route's colour.
struct RunsInkView: View {
    let ink: RunsInk
    /// Which line is the featured run (drawn last, in colour), and how much of it is drawn.
    let featured: Int?
    var drawn: CGFloat = 1
    var pastWidth: CGFloat = 2
    var featuredWidth: CGFloat = 3.5

    var body: some View {
        ZStack {
            ForEach(Array(ink.lines.enumerated()), id: \.offset) { i, pts in
                if i != featured {
                    RunShape(points: pts, aspect: ink.aspect)
                        .stroke(Palette.ink.color.opacity(0.16), style: StrokeStyle(lineWidth: pastWidth, lineCap: .round, lineJoin: .round))
                }
            }
            if let f = featured, ink.lines.indices.contains(f) {
                RunShape(points: ink.lines[f], aspect: ink.aspect)
                    .trim(from: 0, to: drawn)
                    .stroke(Palette.routeCasing.color, style: StrokeStyle(lineWidth: featuredWidth + 4, lineCap: .round, lineJoin: .round))
                RunShape(points: ink.lines[f], aspect: ink.aspect)
                    .trim(from: 0, to: drawn)
                    .stroke(Palette.routeWater.color, style: StrokeStyle(lineWidth: featuredWidth, lineCap: .round, lineJoin: .round))
            }
        }
        .drawingGroup()
    }
}

/// A number that rolls from one value to another.
struct RollingValue: View, Animatable {
    var value: Double
    var decimals = 1
    var style: TypeStyle = .numeralL
    var animatableData: Double {
        get { value }
        set { value = newValue }
    }

    var body: some View {
        Text(String(format: "%.\(decimals)f", value))
            .typeStyle(style)
            .monospacedDigit()
            .foregroundStyle(Palette.ink.color)
    }
}

struct ArrivalView: View {
    let model: MainModel
    let state: ArrivalState
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var drawn: CGFloat = 0
    @State private var landed = false
    @State private var posterShown = false

    private static let drawTime: TimeInterval = 1.9
    private static let beat: TimeInterval = 0.45

    private var all: [RunLog] { model.runs.runs }
    private var before: RunStats { RunStats(runs: all.filter { $0.id != state.id }) }
    private var after: RunStats { RunStats(runs: all) }
    private var run: RunLog? { all.first { $0.id == state.id } }

    private func geo(_ log: RunLog) -> [GeoPoint] { log.route.shape.map { GeoPoint(lon: $0[0], lat: $0[1]) } }

    var body: some View {
        let ink = RunsInk(runs: all.map(geo))
        let featured = all.firstIndex { $0.id == state.id }
        let b = before, a = after
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline) {
                Text("Run \(a.count)")
                    .typeStyle(.eyebrow)
                    .foregroundStyle(Palette.inkMuted.color)
                Spacer()
                Button("Done") { dismiss() }
                    .typeStyle(.bodyStrong)
                    .foregroundStyle(Palette.action.color)
                    .frame(minHeight: Metrics.minTap)
            }
            // The total, set large: the one number that only ever goes up.
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                RollingValue(value: landed ? a.miles : b.miles, style: .display)
                Text("miles").typeStyle(.numeralL).foregroundStyle(Palette.unitInk.color)
            }
            .padding(.top, 2)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(CardText.oneDecimal(a.miles)) miles in all")
            Text(a.since.map { "since \(YouSheet.monthDay($0))" } ?? "")
                .typeStyle(.body)
                .foregroundStyle(Palette.inkMuted.color)

            RunsInkView(ink: ink, featured: featured, drawn: drawn)
                .padding(.vertical, 20)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityLabel("Every route you've run, with this one drawn over them")

            if let run {
                Text(run.route.name)
                    .typeStyle(.request)
                    .foregroundStyle(Palette.ink.color)
                    .lineLimit(2)
                    .opacity(landed ? 1 : 0)
                    .offset(y: landed ? 0 : 6)
            }
            HStack(alignment: .top, spacing: 10) {
                total(landed ? Double(a.count) : Double(b.count), 0, "runs")
                total(landed ? (a.lastEightWeeks.last ?? 0) : (b.lastEightWeeks.last ?? 0), 1, "mi this week")
                total(landed ? Double(a.weekStreak) : Double(b.weekStreak), 0, "week streak")
            }
            .padding(.top, 14)

            if DesignLab.shared.isOn(.arrivalWild) {
                Button { posterShown = true } label: {
                    Text("Make a poster")
                        .typeStyle(.bodyStrong)
                        .foregroundStyle(Palette.ink.color)
                        .frame(maxWidth: .infinity)
                        .frame(height: 54)
                        .overlay(RoundedRectangle(cornerRadius: Metrics.radiusButton).strokeBorder(Palette.ink.color, lineWidth: 1.5))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.top, 22)
                .opacity(landed ? 1 : 0)
                .accessibilityHint("Every run as a picture you can share")
            }
        }
        .padding(.horizontal, Metrics.s24)
        .padding(.top, 8)
        .padding(.bottom, 20)
        .background(Palette.surfaceSheet.color.ignoresSafeArea())
        .overlay { if DesignLab.shared.isOn(.inkWild) || DesignLab.shared.isOn(.arrivalWild) { PaperGrain() } }
        .sheet(isPresented: $posterShown) {
            PosterSheet(runs: all.map(geo), miles: a.miles, count: a.count, since: a.since)
        }
        .task { await play() }
    }

    private func total(_ value: Double, _ decimals: Int, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            RollingValue(value: value, decimals: decimals)
            Text(label).typeStyle(.label).foregroundStyle(Palette.inkSoft.color)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// A beat of stillness, the run draws, the totals roll: one move, with one pattern in the hand.
    private func play() async {
        if reduceMotion {
            drawn = 1
            landed = true
            return
        }
        try? await Task.sleep(for: .seconds(Self.beat))
        InkHaptics.shared.playArrival(draw: Self.drawTime, totalsAt: Self.drawTime + 0.05)
        withAnimation(.timingCurve(0.35, 0, 0.2, 1, duration: Self.drawTime)) { drawn = 1 }
        try? await Task.sleep(for: .seconds(Self.drawTime))
        withAnimation(.timingCurve(0.2, 0, 0, 1, duration: 0.9)) { landed = true }
    }
}

// MARK: F+ wildcard: the poster

/// Every run as line art on paper, the miles set large. 4:5, made for a share sheet.
struct PosterView: View {
    let ink: RunsInk
    let miles: Double
    let count: Int
    let since: Date?
    /// Forced Paper: a poster is printed, whatever the phone's theme.
    private let paper = Color(red: 0xFB / 255, green: 0xF6 / 255, blue: 0xEA / 255)
    private let inkColor = Color(red: 0x2B / 255, green: 0x26 / 255, blue: 0x20 / 255)
    private let route = Color(red: 0x2C / 255, green: 0x3A / 255, blue: 0x8F / 255)

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ZStack {
                ForEach(Array(ink.lines.enumerated()), id: \.offset) { _, pts in
                    RunShape(points: pts, aspect: ink.aspect)
                        .stroke(route.opacity(0.42), style: StrokeStyle(lineWidth: 1.6, lineCap: .round, lineJoin: .round))
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.bottom, 18)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(CardText.oneDecimal(miles)).typeStyle(.display).foregroundStyle(inkColor)
                Text("miles").typeStyle(.numeralL).foregroundStyle(inkColor.opacity(0.7))
            }
            HStack(alignment: .firstTextBaseline) {
                Text("\(count) run\(count == 1 ? "" : "s")\(since.map { " since \(YouSheet.monthDay($0))" } ?? "") · New York")
                    .typeStyle(.body).foregroundStyle(inkColor.opacity(0.75))
                Spacer()
                Text("Loop").typeStyle(.wordmark).foregroundStyle(inkColor)
            }
            .padding(.top, 2)
        }
        .padding(28)
        .frame(width: 360, height: 450)
        .background(paper)
        .overlay { PaperGrain() }
    }

    @MainActor func image() -> UIImage? {
        let r = ImageRenderer(content: self)
        r.scale = 3
        return r.uiImage
    }
}

struct PosterSheet: View {
    let runs: [[GeoPoint]]
    let miles: Double
    let count: Int
    let since: Date?
    @Environment(\.dismiss) private var dismiss
    @State private var shared: UIImage?

    var body: some View {
        // Decision 011: the first and last 200 m of every run stay off a picture that leaves the phone.
        let poster = PosterView(ink: RunsInk(runs: runs.map { RunsInk.trimmed($0) }.filter { !$0.isEmpty }),
                                miles: miles, count: count, since: since)
        VStack(spacing: 20) {
            HStack {
                Text("Your runs, on paper").typeStyle(.request).foregroundStyle(Palette.ink.color)
                Spacer()
                Button("Done") { dismiss() }.typeStyle(.bodyStrong).foregroundStyle(Palette.action.color)
                    .frame(minHeight: Metrics.minTap)
            }
            poster
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.18), radius: 18, y: 10)
                .scaleEffect(0.86)
                .frame(height: 400)
            Text("The first and last 200 m of each run are left off.")
                .typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
            if let shared {
                ShareLink(item: Image(uiImage: shared), preview: SharePreview("My runs", image: Image(uiImage: shared))) {
                    Text("Share")
                        .typeStyle(.bodyStrong)
                        .foregroundStyle(Palette.onAction.color)
                        .frame(maxWidth: .infinity)
                        .frame(height: 54)
                        .background(RoundedRectangle(cornerRadius: Metrics.radiusButton).fill(Palette.action.color))
                }
            }
            Spacer(minLength: 0)
        }
        .padding(Metrics.s24)
        .presentationBackground(Palette.surfaceSheet.color)
        .task { shared = poster.image() }
    }
}
