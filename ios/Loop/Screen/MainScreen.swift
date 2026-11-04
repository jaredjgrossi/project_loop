import SwiftUI

struct MainScreen: View {
    let data: LoopData

    var body: some View {
        ZStack(alignment: .top) {
            Palette.mapLand.color.ignoresSafeArea()
            HeaderView(request: data.request)
        }
    }
}
