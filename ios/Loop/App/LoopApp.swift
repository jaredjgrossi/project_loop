import SwiftUI

@main
struct LoopApp: App {
    init() {
        #if DEBUG
        DemoMode.configure()
        #endif
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .preferredColorScheme(Self.forcedScheme)
        }
    }

    /// Debug: `-LoopTheme light|dark` forces Paper or Night (device screenshots of both themes).
    private static var forcedScheme: ColorScheme? {
        #if DEBUG
        if DemoMode.active { return .light }   // the demo records the Paper theme
        let args = ProcessInfo.processInfo.arguments
        if let i = args.firstIndex(of: "-LoopTheme"), i + 1 < args.count {
            return args[i + 1] == "dark" ? .dark : args[i + 1] == "light" ? .light : nil
        }
        #endif
        return nil
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
            // No automatic keyboard avoidance anywhere: on the phone it shifted the whole screen to
            // keep the focused field in view. Sheets that sit on the keyboard place themselves
            // from the keyboard's height (MainModel.keyboardHeight).
            MainScreen(data: data)
                .ignoresSafeArea(.keyboard)
        case let .failure(error):
            Text("Couldn't read the saved route: \(error.localizedDescription)")
                .typeStyle(.body)
                .foregroundStyle(Palette.ink.color)
                .padding(Metrics.s24)
        }
    }
}
