import SwiftUI

@main
struct LoopApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}

/// Loads the saved route file. A file that fails to load shows why, never a blank screen.
struct RootView: View {
    private let loaded: Result<LoopData, Error> = Result {
        try LoopData(file: RouteFile.loadBundled())
    }

    var body: some View {
        switch loaded {
        case let .success(data):
            MainScreen(data: data)
        case let .failure(error):
            Text("Couldn't read the saved route: \(error.localizedDescription)")
                .typeStyle(.body)
                .foregroundStyle(Palette.ink.color)
                .padding(Metrics.s24)
        }
    }
}
