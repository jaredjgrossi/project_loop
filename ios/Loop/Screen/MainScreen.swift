import SwiftUI

struct MainScreen: View {
    @State private var model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase

    init(data: LoopData) {
        _model = State(initialValue: MainModel(data: data, runs: Self.makeRunStore(data)))
    }

    /// Saved runs and recents from the phone. Debug `-LoopNewUser` shows a new runner's landing
    /// (suggestions only) from an in-memory store, leaving the real file alone.
    private static func makeRunStore(_ data: LoopData) -> RunStore {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-LoopNewUser") { return RunStore() }
        if ProcessInfo.processInfo.arguments.contains("-LoopDemoData") { return RunStore.demo(data: data) }
        #endif
        return RunStore.load(data: data)
    }

    var body: some View {
        ZStack(alignment: .top) {
            RouteMapView(model: model)
                .ignoresSafeArea()

            // Top fade so the header reads over the map: opaque, so no basemap label shows through, down
            // to the provenance line, then gone 48 pt below it (the mockup's 230 pt, measured here).
            let fadeHeight = model.headerBottom + 48
            LinearGradient(stops: [
                .init(color: Palette.mapLand.color, location: 0),
                .init(color: Palette.mapLand.color, location: (model.headerBottom + 6) / fadeHeight),
                .init(color: Palette.mapLand.color.opacity(0), location: 1),
            ], startPoint: .top, endPoint: .bottom)
                .frame(height: fadeHeight)
                .ignoresSafeArea()
                .allowsHitTesting(false)
                .frame(maxHeight: .infinity, alignment: .top)

            // Our markers sit above the fade (START sits just under the provenance line).
            // Markers never draw over the header: masked from the provenance line down.
            // They fade out as the sheet rises to "How Loop read it", so none peek out in the gap
            // between the header and the sheet.
            MarkerLayer(model: model)
            .ignoresSafeArea()
            .mask(alignment: .top) {
                VStack(spacing: 0) {
                    Color.clear.frame(height: model.headerBottom + 2)
                    Color.black
                }
                .ignoresSafeArea()
            }

            // The runner's location pulses while Loop waits (a public stand-in until location is wired).
            if model.stage != .settled, let p = model.screenPoint(model.location) {
                LocationPulse(pulsing: model.locationPulsing && !reduceMotion)
                    .position(p)
                    .ignoresSafeArea()
            }

            HeaderView(model: model, trailing: debugTrailing)
                .background(GeometryReader { g in
                    Color.clear
                        .onAppear { model.headerBottom = g.frame(in: .global).maxY }
                        .onChange(of: g.frame(in: .global).maxY) { _, v in model.headerBottom = v }
                })

            BetterRouteLayer(model: model)
            FitRouteLayer(model: model)

            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("-LoopPinchTarget") {
                // Recording aid: a see-through square over the map for UI-test pinches, so both
                // fingers land on the map (not the sheet). Touches pass through to the map.
                Color.clear
                    .frame(width: 220, height: 220)
                    .accessibilityElement()
                    .accessibilityIdentifier("pinchTarget")
                    .allowsHitTesting(false)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .offset(y: -40)
            }
            #endif

            // The bottom sheets hang from clear layers that take the screen's size (above the home
            // indicator), so a sheet taller than the room left never resizes this ZStack; that
            // re-centred everything and moved the header. Each sheet then moves down by the home
            // indicator's inset to reach the screen's edge: an ignoresSafeArea inside an overlay is
            // honoured in the simulator but not on the phone, so it's done by offset, the same on
            // both. The app ignores the keyboard (RootView); a sheet on the keyboard lifts itself.
            Color.clear
                .overlay(alignment: .bottom) {
                    RouteSheet(model: model)
                        // The rating's note field lifts the sheet onto the keyboard.
                        .offset(y: LandingSheet.bottomInset + (model.sheetShown ? 0 : Metrics.sheetOpen + 60)
                                - (model.rating != nil ? model.keyboardHeight : 0))
                        .animation(reduceMotion ? nil : .easeOut(duration: 0.25), value: model.keyboardHeight)
                        .allowsHitTesting(model.sheetShown)
                }

            // The landing sheet: rises at launch, slides away on send. Its own height grows with
            // the keyboard on the keyboard's curve, so nothing else moves it.
            Color.clear
                .overlay(alignment: .bottom) {
                    LandingSheet(model: model)
                        .offset(y: LandingSheet.bottomInset)
                        .allowsHitTesting(model.landingShown)
                        .accessibilityHidden(!model.landingShown)
                }

            // Edit mode: tapping the map leaves it.
            if model.editMode && model.editing == nil && !model.editingText {
                Color.clear.contentShape(Rectangle())
                    .padding(.top, model.headerBottom + 8)
                    .ignoresSafeArea()
                    .onTapGesture { model.exitEditMode() }
            }

            // A question from the server, or a plain message (no spinners): at the bottom, like a sheet.
            Group {
                if let q = model.pendingQuestion {
                    QuestionCard(model: model, question: q)
                        .id(q.id + (q.parseId ?? ""))
                        .transition(reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity))
                } else if let n = model.liveNotice {
                    NoticeCard(model: model, notice: n)
                        .transition(reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity))
                }
            }
            .frame(maxHeight: .infinity, alignment: .bottom)
            // Typing an answer lifts the card onto the keyboard (it sits above the home indicator's
            // inset already).
            .offset(y: model.pendingQuestion != nil ? -max(0, model.keyboardHeight - LandingSheet.bottomInset) : 0)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.25), value: model.keyboardHeight)
            .animation(reduceMotion ? nil : Motion.sheetSettle, value: model.pendingQuestion?.id)
            .animation(reduceMotion ? nil : Motion.sheetSettle, value: model.liveNotice)

            if let target = model.editing {
                EditorPanel(model: model, target: target)
                    .padding(.top, target.isUnderstood ? model.headerBottom + 10 : 0)
                    .frame(maxHeight: .infinity, alignment: target.isUnderstood ? .top : .center)
                    .ignoresSafeArea(edges: .top)
                    .transition(.opacity)
            }

            if model.logoShown {
                LaunchLogo()
                    .transition(.opacity.combined(with: .scale(scale: 0.96)))
                    .zIndex(10)
            }
        }
        .background(Palette.mapLand.color)
        .fullScreenCover(item: $model.lookAroundTarget) { target in
            LookAroundScreen(scene: target.scene, title: target.title)
        }
        .sheet(isPresented: $model.youShown) { YouSheet(model: model) }
        // Back in the foreground on the home sheet: the return prompt, if a route is waiting.
        .onChange(of: scenePhase) { _, phase in
            if phase == .active, model.stage == .landing, model.returnPrompt == nil {
                withAnimation(reduceMotion ? nil : Motion.crossfade) { model.checkReturnPrompt(openedAt: Date()) }
            }
        }
        .alert("Rename", isPresented: Binding(get: { model.renaming != nil }, set: { if !$0 { model.renaming = nil } })) {
            RenameField(model: model)
        }
        .overlay {
            // One-time token paste (and again after a 401). Covers everything until saved or skipped.
            if model.needsToken {
                TokenScreen(model: model).transition(.opacity)
            }
        }
        // The first location fix: put it in the space above the landing sheet.
        .onChange(of: model.locationProvider.here == nil) { _, missing in
            guard !missing, [.logo, .landing, .typing].contains(model.stage) else { return }
            model.requestCamera(.above(model.location, bottom: model.landing.height, zoom: nil),
                                animated: !reduceMotion, duration: 0.6)
        }
        .task { await start() }
        // The keyboard's height, so the landing sheet sits on it and the map re-centres above both.
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillChangeFrameNotification)) { note in
            guard let end = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
            let duration = note.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double ?? 0.25
            let height = max(0, UIScreen.main.bounds.height - end.minY)
            model.keyboardChanged(height: height, duration: reduceMotion ? 0 : duration)
        }
    }

    /// The replay button exists only in Debug builds.
    private var debugTrailing: AnyView? {
        #if DEBUG
        AnyView(PlayBuildButton(model: model))
        #else
        nil
        #endif
    }

    /// Launch: the logo fades into the map and the bar types an example. Debug launch arguments
    /// that need a finished route (-LoopSettled, -LoopMile, -LoopZoomAt ...) skip straight to it.
    private func start() async {
        if LoopAPI.baseURL != nil {
            model.locationProvider.start()
            model.checkHealth()
        }
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        if args.contains("-LoopSampleWeather") { WeatherStore.shared.useSample() }
        let settledArgs = ["-LoopSettled", "-LoopMile", "-LoopSelectAt", "-LoopZoomAt", "-LoopZoomEsplanade", "-LoopPlay", "-LoopPinchTarget", "-LoopCant", "-LoopEdit", "-LoopReadIt"]
        if args.contains(where: settledArgs.contains) {
            model.requestText = model.data.request.text
            var read = ReadOut.simulated(model.data.request.text, data: model.data, file: nil)
            // -LoopCant G9[,G8]: show can't-do lines for screenshots.
            if let i = args.firstIndex(of: "-LoopCant"), i + 1 < args.count {
                let texts = ["G9": "Can't plan around street lighting yet", "G8": "Can't build repeats into a route yet"]
                read.cant = args[i + 1].split(separator: ",").map { ReadOut.Cant(gap: String($0), text: texts[String($0)] ?? String($0)) }
            }
            model.readOut = read
            model.currentRoute = model.identityOfShown(archive: RouteArchive.fixture, routeId: nil)
            await applyLaunchArguments()
            return
        }
        model.checkReturnPrompt(openedAt: Date())
        model.runLaunch(reduceMotion: reduceMotion, autoSend: args.contains("-LoopDemo"))
        if args.contains("-LoopYou") {
            // Screenshots: open "You" once the landing sheet is up.
            while model.landingAnchor != nil || !model.landingShown { try? await Task.sleep(for: .seconds(0.2)) }
            try? await Task.sleep(for: .seconds(0.6))
            model.youShown = true
        }
        if args.contains("-LoopFocusField") {
            // Screenshots: focus the field once the sheet has risen; `-LoopType text` types into it.
            while model.landingAnchor != nil || !model.landingShown { try? await Task.sleep(for: .seconds(0.2)) }
            try? await Task.sleep(for: .seconds(1.0))
            model.focusFieldRequest += 1
            if let i = args.firstIndex(of: "-LoopType"), i + 1 < args.count {
                try? await Task.sleep(for: .seconds(0.8))
                model.fieldText = args[i + 1]
            }
        }
        if args.contains("-LoopCollapsed") {
            // Screenshots: collapse the landing sheet once it has risen and typed its example.
            while model.landingAnchor != nil || !model.landingShown { try? await Task.sleep(for: .seconds(0.2)) }
            try? await Task.sleep(for: .seconds(2.5))
            model.landing.settle(rest: .collapsed, animated: true)
        }
        #else
        model.checkReturnPrompt(openedAt: Date())
        model.runLaunch(reduceMotion: reduceMotion, autoSend: false)
        #endif
    }

    #if DEBUG
    /// Debug/screenshot hooks: `-LoopMile 1` opens the sheet on mile 1.
    private func applyLaunchArguments() async {
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "-LoopZoomAt"), i + 2 < args.count,
           let mi = Double(args[i + 1]), let z = Double(args[i + 2]), let d = model.shownDetail {
            // Center on a distance along the route at a zoom (debug, recordings).
            try? await Task.sleep(for: .seconds(1.5))
            model.requestCamera(.at(d.line.point(at: mi / d.distanceMi * d.line.length), zoom: z), animated: false)
        }
        if args.contains("-LoopZoomEsplanade"), let d = model.shownDetail {
            // Close on the esplanade's path pieces, south of mile 1.
            try? await Task.sleep(for: .seconds(1.5))
            let along = (d.drawn.first { $0.kind == .path }.map { ($0.fromM + $0.toM) / 2 }) ?? d.line.length / 3
            model.requestCamera(.at(d.line.point(at: along), zoom: 16.6), animated: false)
        }
        if args.contains("-LoopEdit") {
            try? await Task.sleep(for: .seconds(1.5))
            model.enterEditMode()
            if args.contains("-LoopEditor") { try? await Task.sleep(for: .seconds(0.4)); model.openEditor(.understood("distance")) }
        }
        if args.contains("-LoopRate") || args.contains("-LoopRateNo") {
            // Screenshots: "I ran it" on the card; -LoopRateNo also picks Not for me and two reasons.
            // Waits for the map: a change made before the first frames are up can be lost.
            while !model.mapReady { try? await Task.sleep(for: .seconds(0.2)) }
            try? await Task.sleep(for: .seconds(1.0))
            model.ranIt()
            if args.contains("-LoopRateNo") {
                try? await Task.sleep(for: .seconds(0.6))
                model.chooseNotForMe()
                model.toggleReason("crowded")
                model.toggleReason("other")
            }
        }
        if args.contains("-LoopShapeMiss") {
            // Screenshots: the card's note for a route type that wasn't found (final.shape.met false).
            while !model.mapReady { try? await Task.sleep(for: .seconds(0.2)) }
            model.shapeNote = CardText.shapeNote(.init(requested: "loop", met: false, shown: ["out_and_back"]))
            model.applyReadOutToSheet()
        }
        if args.contains("-LoopSaved") {
            try? await Task.sleep(for: .seconds(1.0))
            model.toggleSave()
        }
        if args.contains("-LoopReadIt") {
            try? await Task.sleep(for: .seconds(2.0))
            model.openReadIt()
        }
        if args.contains("-LoopPlay") {
            try? await Task.sleep(for: .seconds(1.5))
            model.play(args.contains("-LoopLate") ? .lateBetterRoute : .standard)
            if let i = args.firstIndex(of: "-LoopTouchAt"), i + 1 < args.count, let t = Double(args[i + 1]) {
                try? await Task.sleep(for: .seconds(t))
                model.touch()
            }
        }
        if let i = args.firstIndex(of: "-LoopMile"), i + 1 < args.count, let mile = Int(args[i + 1]) {
            try? await Task.sleep(for: .seconds(1.2))
            model.setSheet(open: true, animated: false)
            model.selectMile(mile, pan: false)
            if args.contains("-LoopLookAround") {
                try? await Task.sleep(for: .seconds(3))
                model.openLookAround()
            }
        }
        if let i = args.firstIndex(of: "-LoopSelectAt"), i + 1 < args.count, let mi = Double(args[i + 1]),
           let d = model.shownDetail {
            // Same as tapping the route at that distance.
            try? await Task.sleep(for: .seconds(1.5))
            model.selectPoint(alongM: mi / d.distanceMi * d.line.length)
        }
    }
    #endif
}

#if DEBUG
/// Debug: replays a build. Tap for the standard schedule; hold for the late-better-route one.
struct PlayBuildButton: View {
    let model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Menu {
            Button("Replay launch") { model.runLaunch(reduceMotion: reduceMotion, autoSend: true) }
            Button(BuildScript.standard.name) { model.play(.standard) }
            Button(BuildScript.lateBetterRoute.name) { model.play(.lateBetterRoute) }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "play.fill").font(.system(size: 11, weight: .semibold))
                Text("Replay build").typeStyle(.label)
            }
            .foregroundStyle(Palette.inkMuted.color)
            .padding(.horizontal, 12)
            .frame(height: 30)
            .overlay(Capsule().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
            .frame(height: Metrics.minTap)
            .contentShape(Rectangle())
        } primaryAction: {
            model.send(MainModel.exampleRequest, reduceMotion: reduceMotion)
        }
        .accessibilityLabel("Replay build, debug")
        .accessibilityHint("Replays how a live build arrives. Hold for more.")
        .padding(.trailing, Metrics.s8)
    }
}

#endif

/// Shown when a better #1 arrives after the runner touched the route, or after the flag.
struct BetterRouteChip: View {
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text("A better route came in")
                .typeStyle(.label)
                .foregroundStyle(Palette.ink.color)
                .padding(.horizontal, 14)
                .frame(height: 34)
                .background(Capsule().fill(Palette.surfaceSheet.color))
                .overlay(Capsule().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
                .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.10), radius: 7, y: 4)
                .frame(height: Metrics.minTap)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHint("Switches to the new route")
    }
}

/// "A better route came in", pinned 10 pt above the sheet; reads the live sheet height.
private struct BetterRouteLayer: View {
    let model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            if model.betterRouteAvailable {
                BetterRouteChip { model.acceptBetterRoute() }
                    .transition(.opacity)
            }
        }
        .frame(maxHeight: .infinity, alignment: .bottom)
        .padding(.bottom, model.sheet.height + 10)
        .ignoresSafeArea(edges: .bottom)
        .animation(reduceMotion ? nil : Motion.textArrive, value: model.betterRouteAvailable)
    }
}

/// "Fit route": once the runner has panned or zoomed after the route appeared, the camera stops
/// fitting it on its own; this small button, 10 pt above the sheet at the right, brings it back.
private struct FitRouteLayer: View {
    let model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let shows = model.routeCameraFree && model.sheetShown && model.shown != nil && model.sheet.readProgress == 0
        ZStack {
            if shows {
                Button { model.fitRoute() } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "arrow.up.left.and.arrow.down.right").font(.system(size: 11, weight: .semibold))
                        Text("Fit route").typeStyle(.label)
                    }
                    .foregroundStyle(Palette.ink.color)
                    .padding(.horizontal, 12)
                    .frame(height: 32)
                    .background(Capsule().fill(Palette.surfaceSheet.color))
                    .overlay(Capsule().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
                    .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.10), radius: 7, y: 4)
                    .frame(height: Metrics.minTap)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint("Frames the whole route again")
                .transition(.opacity)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
        .padding(.trailing, 16)
        // Above the Mapbox attribution button, which rides 8 pt above the sheet at the right.
        .padding(.bottom, model.sheet.height + 36)
        .ignoresSafeArea(edges: .bottom)
        .animation(reduceMotion ? nil : Motion.textArrive, value: shows)
    }
}

/// The Rename alert's field: starts with the current name.
private struct RenameField: View {
    let model: MainModel
    @State private var name = ""

    var body: some View {
        TextField("Name", text: $name)
            .onAppear { name = model.renaming?.name ?? "" }
        Button("Cancel", role: .cancel) { model.renaming = nil }
        Button("Save") {
            if let s = model.renaming { model.runs.rename(s.id, to: name) }
            model.renaming = nil
        }
    }
}

/// Markers and the selection. Its own view so only it re-renders while the sheet moves
/// (it reads the sheet's read progress); the rest of the screen doesn't.
private struct MarkerLayer: View {
    let model: MainModel
    var body: some View {
        ZStack(alignment: .top) {
            MarkerOverlay(model: model)
            SelectionOverlay(model: model)
        }
        .opacity(1 - model.sheet.readProgress)
    }
}
