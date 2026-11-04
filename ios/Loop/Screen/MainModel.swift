import Foundation
import MapKit
import Observation
import QuartzCore
import SwiftUI

/// State of the main screen: which route is shown, the sheet, the selected mile, the camera.
@Observable
@MainActor
final class MainModel {
    let data: LoopData

    // Route
    var shownRank: Int = 1
    var otherRanks: [Int] = [2, 3]
    var cardRevealed = true
    var showsCount = true
    /// Bumped when the route settles, to send one ring out from the turnaround.
    private(set) var pulseID = 0
    /// How much of the shown route is drawn, 0...1 (markers appear as the line passes them).
    private(set) var drawnFraction: Double = 1

    // Sheet
    /// Where the sheet rests (216 or 398); the live height while dragging is `sheetHeight`.
    var sheetBaseHeight: CGFloat = Metrics.sheetCollapsed
    var sheetHeight: CGFloat = Metrics.sheetCollapsed
    var sheetIsOpen: Bool { sheetBaseHeight == Metrics.sheetOpen }

    // Selection
    var selectedMile: Int?

    // Look Around
    @ObservationIgnored private let lookAround = LookAroundCache()
    private var lookAroundVersion = 0
    struct LookAroundTarget: Identifiable {
        let scene: MKLookAroundScene
        let title: String
        var id: ObjectIdentifier { ObjectIdentifier(scene) }
    }
    var lookAroundTarget: LookAroundTarget?

    // Camera and projection (set by the map)
    var cameraRequest = CameraRequest()
    var zoom: Double = 14
    /// Bumped on every camera move so marker overlays re-place themselves.
    private(set) var cameraTick = 0
    @ObservationIgnored var project: ((GeoPoint) -> CGPoint?)?
    var headerBottom: CGFloat = 230

    init(data: LoopData) {
        self.data = data
    }

    var shown: Candidate? { data.candidate(rank: shownRank) }
    var shownDetail: RouteDetail? { shown?.detail }

    var overviewCoordinates: [GeoPoint] { shown?.line.points ?? [] }

    var eyebrowText: String {
        CardText.eyebrow(kind: shown?.kindText ?? "", bestOf: showsCount ? data.bestOf : nil)
    }

    // MARK: Interaction

    /// The runner touched the route or the card. (Used by the build replay.)
    func touch() {}

    func setSheet(open: Bool, animated: Bool) {
        let target = open ? Metrics.sheetOpen : Metrics.sheetCollapsed
        withAnimation(animated ? Motion.sheetSettle : nil) { sheetBaseHeight = target }
        if open {
            if selectedMile == nil, let first = shownDetail?.miles.first { selectMile(first.mile) }
        } else if selectedMile != nil {
            selectedMile = nil
            requestCamera(.overview, animated: animated)
        }
    }

    /// Select a mile: moves the marker, the chip and the profile cursor; pans so it sits above the sheet.
    func selectMile(_ mile: Int) {
        guard let mark = shownDetail?.miles.first(where: { $0.mile == mile }) else { return }
        selectedMile = mile
        requestCamera(.focus(mark.point), animated: true)
        lookAround.fetch(mile: mile, at: mark.point) { [weak self] in self?.lookAroundVersion += 1 }
    }

    func lookAroundAvailability(mile: Int) -> LookAroundAvailability {
        _ = lookAroundVersion
        return lookAround.availability(mile: mile)
    }

    /// Tapping the chip opens Look Around full screen (only offered when imagery exists).
    func openLookAround(mile: Int, title: String) {
        guard case let .available(scene) = lookAroundAvailability(mile: mile) else { return }
        touch()
        lookAroundTarget = LookAroundTarget(scene: scene, title: title)
    }

    /// Tapping a mile mark on the map opens the sheet on that mile.
    func tapMile(_ mile: Int) {
        touch()
        selectMile(mile)
        if !sheetIsOpen { setSheet(open: true, animated: true) }
    }

    // MARK: Map

    func cameraDidChange(zoom: Double) {
        self.zoom = zoom
        cameraTick &+= 1
    }

    func requestCamera(_ kind: CameraRequest.Kind, animated: Bool) {
        cameraRequest = CameraRequest(id: cameraRequest.id + 1, kind: kind, animated: animated)
    }

    func screenPoint(_ p: GeoPoint) -> CGPoint? {
        _ = cameraTick
        return project?(p)
    }

    func isDrawn(alongM: Double) -> Bool {
        guard let len = shown?.line.length, len > 0 else { return false }
        return drawnFraction * len >= alongM - 1
    }

    /// The map frame for this moment.
    func frame(now: CFTimeInterval, reduceMotion: Bool) -> RouteFrame {
        var frame = RouteFrame()
        if let shown { frame.lead = RouteFrame.segments(for: shown, fraction: drawnFraction) }
        frame.others = otherRanks.compactMap { data.candidate(rank: $0)?.line.points }
        return frame
    }
}
