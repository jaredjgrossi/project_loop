import CoreLocation
import MapboxMaps
import MapKit
import SwiftUI

/// The top-right button: the route L from the app icon, in the existing circle. Opens "You".
struct YouButton: View {
    let model: MainModel

    var body: some View {
        Button { model.youShown = true } label: {
            RouteLMark()
                .frame(width: 22, height: 22)
                .frame(width: Metrics.minTap, height: Metrics.minTap)
                .background(Circle().fill(Palette.surfaceSheet.color.opacity(0.92)))
                .overlay(Circle().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("You")
        .accessibilityHint("Your runs, saved routes and defaults")
    }
}

/// The app icon's route L, drawn small: riverside upright, street foot, turnaround ring, start dot.
struct RouteLMark: View {
    var body: some View {
        Canvas { ctx, size in
            let s = min(size.width, size.height) / 100
            func p(_ x: Double, _ y: Double) -> CGPoint { CGPoint(x: x * s, y: y * s) }
            var l = Path()
            l.move(to: p(36, 22))
            l.addCurve(to: p(35, 68), control1: p(32, 38), control2: p(38, 54))
            l.addQuadCurve(to: p(44, 78), control: p(34, 78))
            l.addLine(to: p(68, 78))
            ctx.stroke(l, with: .color(Palette.routeWater.color), style: StrokeStyle(lineWidth: 11 * s, lineCap: .round, lineJoin: .round))
            let ring = Path(ellipseIn: CGRect(x: 29.5 * s, y: 15.5 * s, width: 13 * s, height: 13 * s))
            ctx.fill(ring, with: .color(Palette.surfaceSheet.color))
            ctx.stroke(ring, with: .color(Palette.routeWater.color), lineWidth: 4.5 * s)
            let dot = Path(ellipseIn: CGRect(x: 60 * s, y: 70 * s, width: 16 * s, height: 16 * s))
            ctx.fill(dot, with: .color(Palette.accentStart.color))
            ctx.stroke(dot, with: .color(Palette.surfaceSheet.color), lineWidth: 3 * s)
        }
        .accessibilityHidden(true)
    }
}

/// The route type as a segmented control in the design system's style: the selected segment in ink
/// with a line-control outline on the sheet colour, the others in ink-muted (UI review, 2026-11-10).
struct RouteTypeControl: View {
    let selection: UsualShape
    var onTrack: Color = Palette.surfaceSunken.color
    let choose: (UsualShape) -> Void

    var body: some View {
        HStack(spacing: 2) {
            ForEach(UsualShape.allCases) { s in
                let on = s == selection
                Text(s.title)
                    .typeStyle(.label)
                    .lineLimit(1)
                    .minimumScaleFactor(0.9)
                    .foregroundStyle(on ? Palette.ink.color : Palette.inkMuted.color)
                    .frame(maxWidth: .infinity)
                    .frame(height: 32)
                    .background {
                        if on {
                            RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Palette.surfaceSheet.color)
                                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .strokeBorder(Palette.lineControl.color, lineWidth: 1.5))
                        }
                    }
                    .contentShape(Rectangle())
                    .onTapGesture { choose(s) }
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(s.title)
                    .accessibilityAddTraits(on ? [.isButton, .isSelected] : .isButton)
            }
        }
        .padding(2)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(onTrack))
        .frame(minHeight: Metrics.minTap)
    }
}

/// A History row: the route's shape, its name (no truncation for typical names), distance · day,
/// and a thumbs-up or -down when rated.
struct HistoryRow: View {
    let log: RunLog
    let action: () -> Void

    var body: some View {
        CleanTap(hint: "Shows this route") { action() } label: {
            HStack(spacing: 14) {
                RouteThumbnail(shape: log.route.shape, lineWidth: 1.8, dot: 0, inset: 0.06)
                    .frame(width: 26, height: 26)
                VStack(alignment: .leading, spacing: 1) {
                    Text(log.route.name)
                        .typeStyle(.body)
                        .foregroundStyle(Palette.ink.color)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("\(CardText.miles(log.route.distanceMi)) · \(RunStore.dayText(log.ranAt))")
                        .typeStyle(.label)
                        .foregroundStyle(Palette.inkMuted.color)
                }
                Spacer(minLength: 8)
                if let r = log.rating {
                    Image(systemName: r.verdict == .good ? "hand.thumbsup" : "hand.thumbsdown")
                        .font(.system(size: 15, weight: .regular))
                        .foregroundStyle(Palette.inkMuted.color)
                        .accessibilityLabel(r.verdict == .good ? "Good" : "Not for me")
                }
            }
            .padding(.vertical, 8)
            .frame(minHeight: 52)
            .overlay(alignment: .bottom) { Rectangle().fill(Palette.lineHairline.color).frame(height: 1) }
        }
    }
}

/// "You": every route run drawn over the others, the numbers, the last 8 weeks, the most-run
/// stretch, saved routes, your defaults and History. Empty until the first run is marked, apart from
/// the hero, the defaults and History.
struct YouSheet: View {
    @Bindable var model: MainModel
    @Environment(\.dismiss) private var dismiss

    private var runs: RunStore { model.runs }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    hero
                    VStack(alignment: .leading, spacing: 0) {
                        let stats = RunStats(runs: runs.runs)
                        Text(stats.count == 0 ? "Your runs will draw here"
                             : "Every route you've run · \(stats.count) run\(stats.count == 1 ? "" : "s") since \(Self.monthDay(stats.since))")
                            .typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                            .padding(.top, 4)
                        if stats.count > 0 {
                            statsRows(stats)
                            weeks(stats)
                            mostRun(stats)
                            saved
                        }
                        Text("Your defaults").typeStyle(.eyebrow).foregroundStyle(Palette.inkMuted.color)
                            .padding(.top, 26).accessibilityAddTraits(.isHeader)
                        DefaultsCard(model: model).padding(.top, 10)
                        NavigationLink {
                            HistoryList(model: model) { log in open { model.openHistory(log) } }
                        } label: {
                            HStack {
                                Text(stats.count == 0 ? "No runs yet" : "All \(stats.count) run\(stats.count == 1 ? "" : "s")")
                                    .typeStyle(.body).foregroundStyle(Palette.ink.color)
                                Spacer()
                                Text("History ›").typeStyle(.bodyStrong).foregroundStyle(Palette.action.color)
                            }
                            .frame(minHeight: Metrics.minTap)
                        }
                        .padding(.top, 14)
                    }
                    .padding(.horizontal, Metrics.s24)
                    .padding(.bottom, 32)
                }
            }
            .scrollIndicators(.hidden)
            .background(Palette.surfaceSheet.color.ignoresSafeArea())
            .toolbar(.hidden, for: .navigationBar)
        }
        .presentationDetents([.large])
        .presentationBackground(Palette.surfaceSheet.color)
    }

    /// The hero (about 250 pt): every run over the others at about 45% in route colour, so the most-run
    /// stretches build up; the start dot at home. Title and Done sit over its top edge.
    private var hero: some View {
        ZStack(alignment: .top) {
            HeroMap(lines: runs.runs.map { $0.route.shape.map { GeoPoint(lon: $0[0], lat: $0[1]) } },
                    home: homePoint)
                .frame(height: 250)
                .overlay(alignment: .top) {
                    LinearGradient(colors: [Palette.surfaceSheet.color, Palette.surfaceSheet.color.opacity(0)],
                                   startPoint: .top, endPoint: .bottom).frame(height: 76).allowsHitTesting(false)
                }
                .overlay(alignment: .bottom) {
                    LinearGradient(colors: [Palette.surfaceSheet.color.opacity(0), Palette.surfaceSheet.color],
                                   startPoint: .top, endPoint: .bottom).frame(height: 36).allowsHitTesting(false)
                }
            HStack(alignment: .firstTextBaseline) {
                Text("You").typeStyle(.request).foregroundStyle(Palette.ink.color).accessibilityAddTraits(.isHeader)
                Spacer()
                Button("Done") { dismiss() }
                    .typeStyle(.bodyStrong).foregroundStyle(Palette.action.color)
                    .frame(minHeight: Metrics.minTap)
            }
            .padding(.horizontal, Metrics.s24)
            .padding(.top, 14)
        }
    }

    private var homePoint: GeoPoint {
        if let h = runs.profile.home { return GeoPoint(lon: h.lon, lat: h.lat) }
        return model.location
    }

    private func statsRows(_ s: RunStats) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                stat(CardText.oneDecimal(s.miles), "miles run", .numeralL)
                stat("\(s.count)", "runs", .numeralL)
                stat(s.average.map(CardText.oneDecimal) ?? "", "mi average", .numeralL)
            }
            HStack(alignment: .top) {
                stat(s.longest.map(CardText.oneDecimal) ?? "", "mi longest", .numeralS)
                stat("\(s.weekStreak)", "week streak", .numeralS)
                stat(s.usualStart ?? RunStats.minutes(runs.profile.usualTime).map(RunStats.clock) ?? "", "usual start", .numeralS)
            }
        }
        .padding(.top, 18)
    }

    private func stat(_ value: String, _ caption: String, _ style: TypeStyle) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).typeStyle(style).foregroundStyle(Palette.ink.color)
            Text(caption).typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }

    private func weeks(_ s: RunStats) -> some View {
        let miles = s.lastEightWeeks
        let top = max(miles.max() ?? 1, 1)
        return VStack(alignment: .leading, spacing: 0) {
            Text("Last 8 weeks").typeStyle(.eyebrow).foregroundStyle(Palette.inkMuted.color).padding(.top, 26)
            HStack(alignment: .bottom, spacing: 8) {
                ForEach(Array(miles.enumerated()), id: \.offset) { i, m in
                    RoundedRectangle(cornerRadius: Metrics.radiusBar)
                        .fill(i == miles.count - 1 ? Palette.routeWater.color : Palette.lineHairline.color)
                        .frame(height: max(3, CGFloat(m / top) * 56))
                        .frame(maxWidth: .infinity)
                }
            }
            .frame(height: 56, alignment: .bottom)
            .padding(.top, 12)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Miles per week, last 8 weeks: " + miles.map(CardText.oneDecimal).joined(separator: ", "))
            HStack {
                Text(Self.monthDay(s.chartStart))
                Spacer()
                Text("this week · \(CardText.trimmed((miles.last ?? 0).rounded(toPlaces: 1))) mi")
            }
            .typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
            .padding(.top, 6)
        }
    }

    @ViewBuilder private func mostRun(_ s: RunStats) -> some View {
        if let m = s.mostRun {
            Text("Most run").typeStyle(.eyebrow).foregroundStyle(Palette.inkMuted.color).padding(.top, 26)
            HStack(spacing: 12) {
                let example = runs.runs.first { $0.route.stretches.contains(m.name) }
                RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Palette.surfaceSunken.color)
                    .overlay(RouteThumbnail(shape: example?.route.shape, lineWidth: 2, dot: 5, inset: 0.16))
                    .frame(width: 44, height: 44)
                VStack(alignment: .leading, spacing: 1) {
                    Text(m.name).typeStyle(.body).foregroundStyle(Palette.ink.color)
                    Text("\(m.count) of your \(s.count) run\(s.count == 1 ? "" : "s")").typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                }
            }
            .padding(.top, 10)
            .accessibilityElement(children: .combine)
        }
    }

    @ViewBuilder private var saved: some View {
        if !runs.saved.isEmpty {
            Text("Saved").typeStyle(.eyebrow).foregroundStyle(Palette.inkMuted.color).padding(.top, 26)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 12) {
                    ForEach(runs.saved) { s in
                        SavedTile(saved: s, side: 77) { open { model.openSaved(s) } }
                            .contextMenu { SavedTileMenu(model: model, saved: s) }
                    }
                }
            }
            .padding(.top, 12)
        }
    }

    /// Close "You", then draw the route on the map.
    private func open(_ action: @escaping () -> Void) {
        dismiss()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35, execute: action)
    }

    static func monthDay(_ d: Date?) -> String {
        guard let d else { return "" }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US")
        f.dateFormat = "MMM d"
        return f.string(from: d)
    }
}

private extension Double {
    func rounded(toPlaces p: Int) -> Double { (self * pow(10, Double(p))).rounded() / pow(10, Double(p)) }
}

/// A saved route's tile: its real shape, its name under it.
struct SavedTile: View {
    let saved: SavedRun
    let side: CGFloat
    let action: () -> Void

    var body: some View {
        CleanTap(hint: "Shows this route") { action() } label: {
            VStack(spacing: 6) {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Palette.surfaceSunken.color)
                    .overlay(RouteThumbnail(shape: saved.shape, lineWidth: 2.4, dot: 7)
                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous)))
                    .frame(width: side, height: side)
                // No wider than the tile: in this scrolling row a wider label was cut off at the edge.
                TileLabel(name: saved.name, side: side)
            }
        }
        .frame(width: side)
    }
}

/// Long-press on a saved tile: Rename and Remove.
struct SavedTileMenu: View {
    let model: MainModel
    let saved: SavedRun

    var body: some View {
        Button { model.renaming = saved } label: { Label("Rename", systemImage: "pencil") }
        Button(role: .destructive) { model.runs.remove(saved.id) } label: { Label("Remove", systemImage: "trash") }
    }
}

/// Every run, newest first; tapping one shows it on the map with "Run again".
struct HistoryList: View {
    let model: MainModel
    let open: (RunLog) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline) {
                    Button { dismiss() } label: { Text("‹ You").typeStyle(.bodyStrong).foregroundStyle(Palette.action.color) }
                        .frame(minHeight: Metrics.minTap)
                    Spacer()
                }
                Text("History").typeStyle(.request).foregroundStyle(Palette.ink.color).padding(.top, 4)
                    .accessibilityAddTraits(.isHeader)
                if model.runs.runs.isEmpty {
                    Text("Routes you mark as run show here.").typeStyle(.body).foregroundStyle(Palette.inkMuted.color).padding(.top, 14)
                }
                ForEach(model.runs.runs) { log in HistoryRow(log: log) { open(log) } }
                    .padding(.top, 2)
            }
            .padding(.horizontal, Metrics.s24)
            .padding(.top, 12)
        }
        .background(Palette.surfaceSheet.color.ignoresSafeArea())
        .toolbar(.hidden, for: .navigationBar)
    }
}

/// Your defaults: home, usual distance (0.5 mi steps), usual time (a time wheel) and route type.
struct DefaultsCard: View {
    @Bindable var model: MainModel
    @State private var editingTime = false
    @State private var pickingHome = false

    private var profile: RunnerProfile { model.runs.profile }

    var body: some View {
        VStack(spacing: 0) {
            row {
                Text("Home").typeStyle(.body).foregroundStyle(Palette.ink.color)
                Spacer()
                Text(profile.home?.label ?? "Not set").typeStyle(.body).foregroundStyle(Palette.inkMuted.color).lineLimit(1)
                chevron
            }
            .contentShape(Rectangle())
            .onTapGesture { pickingHome = true }
            .accessibilityAddTraits(.isButton)
            divider
            row {
                Text("Usual distance").typeStyle(.body).foregroundStyle(Palette.ink.color)
                Spacer()
                stepButton("minus", "Less") { model.runs.profile.usualDistanceMi = max(0.5, profile.usualDistanceMi - 0.5) }
                Text("\(CardText.trimmed(profile.usualDistanceMi)) mi").typeStyle(.numeralS).foregroundStyle(Palette.ink.color)
                    .frame(minWidth: 56)
                stepButton("plus", "More") { model.runs.profile.usualDistanceMi = min(30, profile.usualDistanceMi + 0.5) }
            }
            divider
            row {
                Text("Usual time").typeStyle(.body).foregroundStyle(Palette.ink.color)
                Spacer()
                Text(RunStats.minutes(profile.usualTime).map(RunStats.clock) ?? profile.usualTime)
                    .typeStyle(.body).foregroundStyle(Palette.inkMuted.color)
                chevron.rotationEffect(.degrees(editingTime ? 90 : 0))
            }
            .contentShape(Rectangle())
            .onTapGesture { withAnimation(Motion.sheetSettle) { editingTime.toggle() } }
            .accessibilityAddTraits(.isButton)
            if editingTime {
                DatePicker("", selection: timeBinding, displayedComponents: .hourAndMinute)
                    .datePickerStyle(.wheel)
                    .labelsHidden()
                    .frame(maxWidth: .infinity)
                    .tint(Palette.action.color)
            }
            divider
            VStack(alignment: .leading, spacing: 8) {
                Text("Route type").typeStyle(.body).foregroundStyle(Palette.ink.color)
                RouteTypeControl(selection: UsualShape(rawValue: profile.usualShape) ?? .any,
                                 onTrack: Palette.surfaceSheet.color) { model.runs.profile.usualShape = $0.rawValue }
            }
            .padding(.vertical, 12)
        }
        .padding(.horizontal, 14)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Palette.surfaceSunken.color))
        .sheet(isPresented: $pickingHome) { HomePicker(model: model) }
    }

    private var timeBinding: Binding<Date> {
        Binding {
            let m = RunStats.minutes(profile.usualTime) ?? 420
            return Calendar.current.date(bySettingHour: m / 60, minute: m % 60, second: 0, of: Date()) ?? Date()
        } set: { d in
            let c = Calendar.current.dateComponents([.hour, .minute], from: d)
            model.runs.profile.usualTime = String(format: "%02d:%02d", c.hour ?? 7, c.minute ?? 0)
        }
    }

    private func row<C: View>(@ViewBuilder _ content: () -> C) -> some View {
        HStack(spacing: 10) { content() }.frame(minHeight: 48)
    }

    private var divider: some View { Rectangle().fill(Palette.lineHairline.color).frame(height: 1) }
    private var chevron: some View {
        Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Palette.inkMuted.color)
    }

    private func stepButton(_ symbol: String, _ label: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 14, weight: .medium)).foregroundStyle(Palette.ink.color)
                .frame(width: 32, height: 32)
                .background(Circle().fill(Palette.surfaceSheet.color))
                .frame(width: Metrics.minTap, height: Metrics.minTap)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// Home: the current location, or an address search. Kept on the phone; sent as a saved place.
struct HomePicker: View {
    let model: MainModel
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var results: [MKMapItem] = []
    @State private var searching = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Home").typeStyle(.request).foregroundStyle(Palette.ink.color)
                Spacer()
                Button("Done") { dismiss() }.typeStyle(.bodyStrong).foregroundStyle(Palette.action.color)
            }
            HStack(spacing: 12) {
                Image(systemName: "magnifyingglass").font(.system(size: 16, weight: .semibold)).foregroundStyle(Palette.inkMuted.color)
                TextField("", text: $query, prompt: Text("Search an address").foregroundStyle(Palette.inkMuted.color))
                    .typeStyle(.field).foregroundStyle(Palette.ink.color).tint(Palette.focusRing.color)
                    .submitLabel(.search)
                    .onSubmit(search)
            }
            .padding(.horizontal, 18).frame(height: 50)
            .background(Capsule().fill(Palette.surfaceSunken.color))
            .padding(.top, 18)

            CleanTap(hint: "Sets home to where you are now") { useCurrentLocation() } label: {
                HStack(spacing: 10) {
                    Image(systemName: "location").font(.system(size: 15)).foregroundStyle(Palette.action.color)
                    Text("Use current location").typeStyle(.body).foregroundStyle(Palette.ink.color)
                    Spacer()
                }
                .frame(minHeight: 48)
                .overlay(alignment: .bottom) { Rectangle().fill(Palette.lineHairline.color).frame(height: 1) }
            }
            .padding(.top, 8)

            ForEach(results, id: \.self) { item in
                CleanTap(hint: "Sets home here") { setHome(item) } label: {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(item.name ?? "").typeStyle(.body).foregroundStyle(Palette.ink.color)
                        Text(item.placemark.title ?? "").typeStyle(.label).foregroundStyle(Palette.inkMuted.color).lineLimit(1)
                    }
                    .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
                    .overlay(alignment: .bottom) { Rectangle().fill(Palette.lineHairline.color).frame(height: 1) }
                }
            }
            Spacer()
        }
        .padding(Metrics.s24)
        .background(Palette.surfaceSheet.color.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .presentationBackground(Palette.surfaceSheet.color)
    }

    private func search() {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        let req = MKLocalSearch.Request()
        req.naturalLanguageQuery = q
        let here = model.location
        req.region = MKCoordinateRegion(center: here.coordinate, latitudinalMeters: 30_000, longitudinalMeters: 30_000)
        MKLocalSearch(request: req).start { response, _ in
            results = Array((response?.mapItems ?? []).prefix(6))
        }
    }

    private func setHome(_ item: MKMapItem) {
        let c = item.placemark.coordinate
        model.runs.profile.home = .init(label: item.name ?? "Home", lat: c.latitude, lon: c.longitude)
        dismiss()
    }

    private func useCurrentLocation() {
        guard let here = model.locationProvider.here else { return }
        let c = here.coordinate
        CLGeocoder().reverseGeocodeLocation(here) { marks, _ in
            let label = marks?.first?.name ?? "Current location"
            model.runs.profile.home = .init(label: label, lat: c.latitude, lon: c.longitude)
            dismiss()
        }
    }
}

/// The hero map on "You": Mapbox Standard in the app's quiet style, not interactive, with every run's
/// line over the others at about 45% and the start dot at home.
struct HeroMap: UIViewRepresentable {
    let lines: [[GeoPoint]]
    let home: GeoPoint
    @Environment(\.colorScheme) private var colorScheme

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> MapView {
        // A real size from the start (a zero frame renders into a corner inside a scroll view).
        let map = MapView(frame: CGRect(x: 0, y: 0, width: UIScreen.main.bounds.width, height: 250),
                          mapInitOptions: MapInitOptions(cameraOptions: CameraOptions(center: home.coordinate, zoom: 13.6)))
        map.ornaments.options.scaleBar.visibility = .hidden
        map.ornaments.options.compass.visibility = .hidden
        map.gestures.options.panEnabled = false
        map.gestures.options.pinchEnabled = false
        map.gestures.options.doubleTapToZoomInEnabled = false
        map.gestures.options.doubleTouchToZoomOutEnabled = false
        map.gestures.options.quickZoomEnabled = false
        map.gestures.options.pitchEnabled = false
        map.gestures.options.rotateEnabled = false
        map.backgroundColor = Palette.mapLand.uiColor
        map.ornaments.options.attributionButton.tintColor = Palette.inkMuted.uiColor
        let dark = colorScheme == .dark
        let c = context.coordinator
        map.mapboxMap.onStyleLoaded.observe { [weak map] _ in
            MainActor.assumeIsolated {
                guard let map else { return }
                c.styleLoaded(map, lines: lines, home: home, dark: dark)
            }
        }.store(in: &c.cancelables)
        // Fit once the map has its size and has drawn.
        map.mapboxMap.onMapLoaded.observeNext { [weak map] _ in
            MainActor.assumeIsolated {
                guard let map else { return }
                c.fit(map, lines: lines, home: home)
            }
        }.store(in: &c.cancelables)
        if MapStyle.hasToken { map.mapboxMap.styleURI = .standard } else { map.mapboxMap.styleJSON = MapStyle.blankStyleJSON(dark: dark) }
        return map
    }

    func updateUIView(_ map: MapView, context: Context) {}

    @MainActor
    final class Coordinator {
        var cancelables = Set<AnyCancelable>()

        func styleLoaded(_ view: MapView, lines: [[GeoPoint]], home: GeoPoint, dark: Bool) {
            let map = view.mapboxMap!
            if MapStyle.hasToken {
                for (key, value) in MapStyle.standardConfig(dark: dark) {
                    try? map.setStyleImportConfigProperty(for: "basemap", config: key, value: value)
                }
                try? map.setStyleImportConfigProperty(for: "basemap", config: "showRoadLabels", value: false)
            }
            var src = GeoJSONSource(id: "hero-runs")
            var features = lines.filter { $0.count >= 2 }.map { Feature(geometry: LineString($0.map(\.coordinate))) }
            var homeFeature = Feature(geometry: Point(home.coordinate))
            homeFeature.properties = ["home": .boolean(true)]
            features.append(homeFeature)
            src.data = .featureCollection(FeatureCollection(features: features))
            try? map.addSource(src)
            var line = LineLayer(id: "hero-lines", source: "hero-runs")
            line.filter = Exp(.eq) { Exp(.geometryType); "LineString" }
            line.lineColor = .constant(StyleColor(Palette.routeWater.uiColor))
            line.lineWidth = .constant(3)
            line.lineOpacity = .constant(0.45)
            line.lineCap = .constant(.round)
            line.lineJoin = .constant(.round)
            line.lineEmissiveStrength = .constant(1)
            try? map.addLayer(line)
            var dot = CircleLayer(id: "hero-home", source: "hero-runs")
            dot.filter = Exp(.eq) { Exp(.geometryType); "Point" }
            dot.circleRadius = .constant(7)
            dot.circleColor = .constant(StyleColor(Palette.accentStart.uiColor))
            dot.circleStrokeColor = .constant(StyleColor(Palette.routeCasing.uiColor))
            dot.circleStrokeWidth = .constant(2.5)
            dot.circleEmissiveStrength = .constant(1)
            try? map.addLayer(dot)
            fit(view, lines: lines, home: home)
        }

        func fit(_ view: MapView, lines: [[GeoPoint]], home: GeoPoint) {
            guard let map = view.mapboxMap, view.bounds.width > 0 else { return }
            let coords = lines.flatMap { $0 }.map(\.coordinate) + [home.coordinate]
            if lines.isEmpty {
                map.setCamera(to: CameraOptions(center: home.coordinate, padding: .zero, zoom: 14))
            } else if let cam = try? map.camera(for: coords, camera: CameraOptions(padding: .zero),
                                                coordinatesPadding: UIEdgeInsets(top: 70, left: 28, bottom: 30, right: 28),
                                                maxZoom: 15.5, offset: nil) {
                map.setCamera(to: cam)
            }
        }
    }
}
