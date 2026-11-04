import SwiftUI

struct MainScreen: View {
    @State private var model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(data: LoopData) {
        _model = State(initialValue: MainModel(data: data))
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
            MarkerOverlay(model: model)
                .ignoresSafeArea()

            SelectionOverlay(model: model)
                .ignoresSafeArea()

            HeaderView(request: model.data.request, trailing: debugTrailing)
                .background(GeometryReader { g in
                    Color.clear.onAppear { model.headerBottom = g.frame(in: .global).maxY }
                })

            if model.betterRouteAvailable {
                BetterRouteChip { model.acceptBetterRoute() }
                    .frame(maxHeight: .infinity, alignment: .bottom)
                    .padding(.bottom, model.sheetHeight + 10)
                    .ignoresSafeArea(edges: .bottom)
                    .transition(.opacity)
            }

            RouteSheet(model: model)
                .frame(maxHeight: .infinity, alignment: .bottom)
                .ignoresSafeArea(edges: .bottom)
        }
        .background(Palette.mapLand.color)
        .fullScreenCover(item: $model.lookAroundTarget) { target in
            LookAroundScreen(scene: target.scene, title: target.title)
        }
        .animation(reduceMotion ? nil : Motion.textArrive, value: model.betterRouteAvailable)
        #if DEBUG
        .task { await applyLaunchArguments() }
        #endif
    }

    /// The replay button exists only in Debug builds.
    private var debugTrailing: AnyView? {
        #if DEBUG
        AnyView(PlayBuildButton(model: model))
        #else
        nil
        #endif
    }

    #if DEBUG
    /// Debug/screenshot hooks: `-LoopMile 1` opens the sheet on mile 1.
    private func applyLaunchArguments() async {
        let args = ProcessInfo.processInfo.arguments
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
                if let detail = model.shownDetail, let mark = detail.miles.first(where: { $0.mile == mile }) {
                    let name = detail.stretch(atMile: mark.alongMi)?.name ?? ""
                    model.openLookAround(mile: mile, title: CardText.mileChip(mile: mile, stretchName: name))
                }
            }
        }
    }
    #endif
}

#if DEBUG
/// Debug: replays a build. Tap for the standard schedule; hold for the late-better-route one.
struct PlayBuildButton: View {
    let model: MainModel

    var body: some View {
        Menu {
            Button(BuildScript.standard.name) { model.play(.standard) }
            Button(BuildScript.lateBetterRoute.name) { model.play(.lateBetterRoute) }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "play.fill").font(.system(size: 11, weight: .semibold))
                Text("build").typeStyle(.data)
            }
            .foregroundStyle(Palette.inkMuted.color)
            .padding(.horizontal, 12)
            .frame(height: 30)
            .overlay(Capsule().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
            .frame(height: Metrics.minTap)
            .contentShape(Rectangle())
        } primaryAction: {
            model.play(.standard)
        }
        .accessibilityLabel("Play the build, debug")
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
