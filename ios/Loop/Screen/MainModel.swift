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

    // Sheet: its own observable, so only views pinned to it re-render while it moves.
    let sheet = SheetState()
    var sheetIsOpen: Bool { sheet.restingOpen }

    // Selection: a point on the shown route, from a tap on the line, a mile mark, or the strip.
    struct RouteSelection: Equatable {
        /// Along-route metres on the shown route's line.
        let alongM: Double
        /// Set when a mile mark was chosen: that exact mile.
        let mile: Int?
    }
    private(set) var selection: RouteSelection?
    var selectedMile: Int? { selection?.mile }

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

    /// The overview frames the shown route only: it is the hero. The faint #2 and #3 may run off
    /// screen or under the header fade (framing all three made the hero too small).
    var overviewCoordinates: [GeoPoint] { (data.candidate(rank: 1) ?? shown)?.line.points ?? [] }

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
        selection = nil
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
        if let m = selectedMile, shownDetail?.miles.contains(where: { $0.mile == m }) == true {
            selectMile(m, pan: false)
        } else {
            selection = nil
        }
    }

    // MARK: Sheet

    func setSheet(open: Bool, animated: Bool) {
        let changed = sheet.restingOpen != open || sheet.height != (open ? SheetState.open : SheetState.collapsed)
        sheet.settle(open: open, animated: animated) { [weak self] in
            // Refit the route to the space the sheet leaves, only once it has settled.
            if changed { self?.requestCamera(.overview, animated: animated) }
        }
        sheetOpened(open)
    }

    func sheetDragEnded(predictedTranslation: CGFloat, animated: Bool) {
        let wasOpen = sheet.restingOpen
        sheet.endDrag(predictedTranslation: predictedTranslation, animated: animated) { [weak self] open in
            if open != wasOpen { self?.requestCamera(.overview, animated: animated) }
        }
        sheetOpened(sheet.restingOpen)
    }

    /// Opening the sheet with nothing selected selects mile 1 (the D artboard). Selection stays
    /// when the sheet closes: the chip shows above the sheet in either state.
    private func sheetOpened(_ open: Bool) {
        if open, selection == nil, let first = shownDetail?.miles.first { selectMile(first.mile, pan: false, tick: false) }
    }

    // MARK: Selection

    /// Select a mile: marker, chip and profile cursor go to that exact mile. The map pans only if
    /// the mile is outside the space between the header and the sheet.
    func selectMile(_ mile: Int, pan: Bool = true, tick: Bool = false) {
        guard let mark = shownDetail?.miles.first(where: { $0.mile == mile }) else { return }
        selection = RouteSelection(alongM: mark.alongM, mile: mile)
        if tick { Haptics.mileTick() }
        if pan { requestCamera(.focus(mark.point), animated: true) }
        fetchLookAround()
    }

    /// A tap within 22 pt of the line selects the nearest point on it: dot, chip, strip cursor
    /// and a selection tick. No pan, and the sheet stays as it is.
    func selectPoint(alongM: Double) {
        guard let line = shown?.line else { return }
        touch()
        selection = RouteSelection(alongM: min(max(0, alongM), line.length), mile: nil)
        Haptics.mileTick()
        fetchLookAround()
    }

    func clearSelection() { selection = nil }

    /// Where the selection sits: the file's mile point for a mile, else the point on the line.
    var selectionPoint: GeoPoint? {
        guard let sel = selection, let d = shownDetail else { return nil }
        if let m = sel.mile, let mark = d.miles.first(where: { $0.mile == m }) { return mark.point }
        return d.line.point(at: sel.alongM)
    }

    /// The selection's distance along the route in miles (the file's own value for a mile).
    var selectionAlongMi: Double? {
        guard let sel = selection, let d = shownDetail else { return nil }
        if let m = sel.mile, let mark = d.miles.first(where: { $0.mile == m }) { return mark.alongMi }
        return sel.alongM / d.line.length * d.distanceMi
    }

    var selectionStretchName: String {
        guard let mi = selectionAlongMi, let d = shownDetail else { return "" }
        return d.stretch(atMile: mi)?.name ?? ""
    }

    // MARK: Look Around

    /// Look Around answers are cached per 10 m of route.
    private var lookAroundKey: Int? { selection.map { Int(($0.alongM / 10).rounded()) } }

    private func fetchLookAround() {
        guard let key = lookAroundKey, let p = selectionPoint else { return }
        lookAround.fetch(key: key, at: p) { [weak self] in self?.lookAroundVersion += 1 }
    }

    var selectionLookAround: LookAroundAvailability {
        _ = lookAroundVersion
        guard let key = lookAroundKey else { return .unknown }
        return lookAround.availability(key: key)
    }

    /// Tapping the chip opens Look Around full screen (only offered when imagery exists).
    func openLookAround() {
        guard case let .available(scene) = selectionLookAround, let mi = selectionAlongMi else { return }
        touch()
        lookAroundTarget = LookAroundTarget(
            scene: scene, title: CardText.selectionChip(stretchName: selectionStretchName, alongMi: mi, lookAround: false))
    }

    /// Tapping a mile mark selects that exact mile, with a selection tick. The sheet stays put.
    func tapMile(_ mile: Int) {
        touch()
        selectMile(mile, tick: true)
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
        if build.outlineOpacity(at: now, peak: 1, fade: Motion.outlineFade) > 0, build.provisional { return true }
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
        let outline = reduceMotion
            ? (build.provisional ? 0 : Motion.outlinePeakOpacity)
            : build.outlineOpacity(at: now, peak: Motion.outlinePeakOpacity, fade: Motion.outlineFade)
        frame.othersOpacity = outline
        frame.others = outline > 0 ? otherRanks.compactMap { data.candidate(rank: $0)?.line.points } : []
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
            frame.casing = frame.lead.first?.points ?? []
        } else {
            let mpp = MapScale.metresPerPoint(zoom: zoom, latitude: shown.line.points[0].lat)
            let drawn = RouteFrame.route(for: shown, fraction: fraction, metresPerPoint: mpp)
            frame.casing = drawn.casing
            frame.lead = drawn.lead
        }
        return frame
    }
}
