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
            // Markers never draw over the header: masked from the provenance line down.
            Group {
                MarkerOverlay(model: model)
                SelectionOverlay(model: model)
            }
            .ignoresSafeArea()
            .mask(alignment: .top) {
                VStack(spacing: 0) {
                    Color.clear.frame(height: model.headerBottom + 2)
                    Color.black
                }
                .ignoresSafeArea()
            }

            HeaderView(request: model.data.request, trailing: debugTrailing)
                .background(GeometryReader { g in
                    Color.clear.onAppear { model.headerBottom = g.frame(in: .global).maxY }
                })

            BetterRouteLayer(model: model)

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

            RouteSheet(model: model)
                .frame(maxHeight: .infinity, alignment: .bottom)
                .ignoresSafeArea(edges: .bottom)
        }
        .background(Palette.mapLand.color)
        .fullScreenCover(item: $model.lookAroundTarget) { target in
            LookAroundScreen(scene: target.scene, title: target.title)
        }
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

    var body: some View {
        Menu {
            Button(BuildScript.standard.name) { model.play(.standard) }
            Button(BuildScript.lateBetterRoute.name) { model.play(.lateBetterRoute) }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "play.fill").font(.system(size: 11, weight: .semibold))
                Text("Replay build").typeStyle(.data)
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
