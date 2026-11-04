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

    // Route: the build replay decides what is shown.
    private(set) var build: BuildState
    @ObservationIgnored private var playback: Task<Void, Never>?
    @ObservationIgnored private var resampled: [Int: [GeoPoint]] = [:]
    /// Bumped whenever what the map draws changes outside of time-based animation.
    private(set) var frameVersion = 0
    /// Bumped when the route settles, to send one ring out from the turnaround.
    private(set) var pulseID = 0
    /// How much of the shown route is drawn, 0...1 (markers appear as the line passes them).
    private(set) var drawnFraction: Double = 1

    var shownRank: Int? { build.shownRank }
    var otherRanks: [Int] { build.otherRanks }
    var cardRevealed: Bool { build.cardRevealed }
    var showsCount: Bool { build.showsCount }
    var betterRouteAvailable: Bool { build.betterRank != nil }

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
        build = .settled(top3: data.candidates.map(\.rank))
    }

    var shown: Candidate? { shownRank.flatMap { data.candidate(rank: $0) } }
    var shownDetail: RouteDetail? { shown?.detail }

    var overviewCoordinates: [GeoPoint] { shown?.line.points ?? [] }

    var eyebrowText: String {
        CardText.eyebrow(kind: shown?.kindText ?? "", bestOf: showsCount ? data.bestOf : nil)
    }

    // MARK: Interaction

    /// The runner touched the route or the card. Before the flag this cancels the settle beat
    /// and freezes the shown route.
    func touch() {
        guard !build.touched, !build.final else { return }
        build.touch()
    }

    // MARK: Build replay

    /// Replays a build from the saved file's top 3 on the fake schedule.
    func play(_ script: BuildScript) {
        playback?.cancel()
        selectedMile = nil
        setSheet(open: false, animated: true)
        build = BuildState()
        drawnFraction = 0
        frameVersion += 1
        Haptics.prepareSettle()
        let t0 = CACurrentMediaTime()
        playback = Task { @MainActor [weak self] in
            for timed in script.events {
                let wait = t0 + timed.at - CACurrentMediaTime()
                if wait > 0 { try? await Task.sleep(for: .seconds(wait)) }
                guard let self, !Task.isCancelled else { return }
                self.receive(timed.event, at: t0 + timed.at)
            }
        }
    }

    private func receive(_ event: BuildEvent, at t: CFTimeInterval) {
        let wasSettled = build.settleAt
        build.apply(event, at: t)
        frameVersion += 1
        if build.settleAt != nil, wasSettled == nil {
            pulseID += 1
            Haptics.settle()
        }
    }

    /// "A better route came in" → switch, morphing from the route on screen.
    func acceptBetterRoute() {
        build.acceptBetterRoute(at: CACurrentMediaTime())
        frameVersion += 1
        if let m = selectedMile {
            if shownDetail?.miles.contains(where: { $0.mile == m }) == true { selectMile(m) } else { selectedMile = nil }
        }
    }

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

    /// True while the route is still drawing or morphing (the map redraws every frame).
    func isAnimating(now: CFTimeInterval, reduceMotion: Bool) -> Bool {
        guard !reduceMotion, let shown else { return false }
        if build.morphProgress(at: now, duration: Motion.morphDuration) != nil { return true }
        return build.drawnFraction(at: now, length: shown.line.length,
                                   metresPerSecond: Motion.drawMetresPerSecond) < 1
    }

    private func points(rank: Int) -> [GeoPoint] {
        if let hit = resampled[rank] { return hit }
        let pts = data.candidate(rank: rank)?.line.resampled(count: 256) ?? []
        resampled[rank] = pts
        return pts
    }

    /// The map frame for this moment. Constant-speed draw; a new leader before the flag morphs
    /// point by point from the line on screen (no redraw from scratch). Reduce Motion: drawn whole.
    func frame(now: CFTimeInterval, reduceMotion: Bool) -> RouteFrame {
        var frame = RouteFrame()
        frame.others = otherRanks.compactMap { data.candidate(rank: $0)?.line.points }
        frame.othersOpacity = build.provisional ? 0.5 : 0.3
        guard let shown else {
            if drawnFraction != 0 { drawnFraction = 0 }
            return frame
        }
        let fraction = reduceMotion ? 1 : build.drawnFraction(
            at: now, length: shown.line.length, metresPerSecond: Motion.drawMetresPerSecond)
        if fraction != drawnFraction { drawnFraction = fraction }

        if !reduceMotion, let p = build.morphProgress(at: now, duration: Motion.morphDuration),
           let morph = build.morph {
            let eased = p * p * (3 - 2 * p)
            frame.lead = RouteFrame.plain(blend(points(rank: morph.from), points(rank: morph.to), eased),
                                          fraction: fraction)
        } else {
            frame.lead = RouteFrame.segments(for: shown, fraction: fraction)
        }
        return frame
    }
}
