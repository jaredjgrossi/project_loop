import MapKit
import SwiftUI

/// Whether Apple has Look Around imagery at a spot on the route. Asked once per spot and cached.
enum LookAroundAvailability {
    case unknown
    case available(MKLookAroundScene)
    case none
}

@MainActor
final class LookAroundCache {
    private var results: [Int: LookAroundAvailability] = [:]
    private var inFlight: Set<Int> = []

    func availability(key: Int) -> LookAroundAvailability { results[key] ?? .unknown }

    /// Looks up the scene for a spot on the route; calls `done` when the answer arrives.
    func fetch(key: Int, at point: GeoPoint, done: @escaping @MainActor () -> Void) {
        guard results[key] == nil, !inFlight.contains(key) else { return }
        inFlight.insert(key)
        Task { @MainActor in
            let scene = try? await MKLookAroundSceneRequest(coordinate: point.coordinate).scene
            inFlight.remove(key)
            results[key] = scene.map { .available($0) } ?? .none
            done()
        }
    }
}

/// Full-screen Apple Look Around at a mile, with a close button and its source named.
struct LookAroundScreen: View {
    let scene: MKLookAroundScene
    let title: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack(alignment: .topLeading) {
            LookAroundRepresentable(scene: scene)
                .ignoresSafeArea()
            HStack(spacing: Metrics.s12) {
                Button { dismiss() } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(Palette.ink.color)
                        .frame(width: Metrics.minTap, height: Metrics.minTap)
                        .background(Circle().fill(Palette.surfaceSheet.color))
                        .overlay(Circle().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Close street view")

                VStack(alignment: .leading, spacing: 0) {
                    Text(title).typeStyle(.label).foregroundStyle(Palette.ink.color)
                    Text("Apple Look Around imagery").typeStyle(.data).foregroundStyle(Palette.inkMuted.color)
                }
                .padding(.horizontal, Metrics.s12)
                .padding(.vertical, 6)
                .background(Capsule().fill(Palette.surfaceSheet.color))
                .accessibilityElement(children: .combine)
            }
            .padding(.horizontal, Metrics.s16)
            .padding(.top, Metrics.s8)
        }
    }
}

private struct LookAroundRepresentable: UIViewControllerRepresentable {
    let scene: MKLookAroundScene

    func makeUIViewController(context: Context) -> MKLookAroundViewController {
        let vc = MKLookAroundViewController(scene: scene)
        vc.isNavigationEnabled = true
        vc.showsRoadLabels = true
        vc.badgePosition = .bottomTrailing
        return vc
    }

    func updateUIViewController(_ vc: MKLookAroundViewController, context: Context) {
        if vc.scene !== scene { vc.scene = scene }
    }
}
