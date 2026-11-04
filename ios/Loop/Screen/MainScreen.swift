import SwiftUI

struct MainScreen: View {
    @State private var model: MainModel

    init(data: LoopData) {
        _model = State(initialValue: MainModel(data: data))
    }

    var body: some View {
        ZStack(alignment: .top) {
            RouteMapView(model: model)
                .ignoresSafeArea()

            MarkerOverlay(model: model)
                .ignoresSafeArea()

            SelectionOverlay(model: model)
                .ignoresSafeArea()

            // Top fade so the header reads over the map.
            LinearGradient(stops: [
                .init(color: Palette.mapLand.color.opacity(0.96), location: 0),
                .init(color: Palette.mapLand.color.opacity(0.88), location: 0.55),
                .init(color: Palette.mapLand.color.opacity(0), location: 1),
            ], startPoint: .top, endPoint: .bottom)
                .frame(height: 230)
                .ignoresSafeArea(edges: .top)
                .allowsHitTesting(false)
                .frame(maxHeight: .infinity, alignment: .top)

            HeaderView(request: model.data.request)
                .background(GeometryReader { g in
                    Color.clear.onAppear { model.headerBottom = g.frame(in: .global).maxY }
                })

            RouteSheet(model: model)
                .frame(maxHeight: .infinity, alignment: .bottom)
                .ignoresSafeArea(edges: .bottom)
        }
        .background(Palette.mapLand.color)
        .task { await applyLaunchArguments() }
    }

    /// Debug/screenshot hooks: `-LoopMile 1` opens the sheet on mile 1.
    private func applyLaunchArguments() async {
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "-LoopMile"), i + 1 < args.count, let mile = Int(args[i + 1]) {
            try? await Task.sleep(for: .seconds(1.2))
            model.setSheet(open: true, animated: false)
            model.selectMile(mile)
        }
    }
}
