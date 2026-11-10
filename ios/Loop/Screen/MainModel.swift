import Foundation
import MapKit
import Observation
import QuartzCore
import SwiftUI

/// State of the main screen: which route is shown, the sheet, the selected mile, the camera.
@Observable
@MainActor
final class MainModel {
    /// The routes on screen: the bundled file, or a live build's (replaced as events arrive).
    var data: LoopData { didSet { resampled = [:] } }
    /// The bundled route file, for builds without the server and the debug replays.
    let fixtureData: LoopData

    // Route: the build replay decides what is shown.
    var build: BuildState
    @ObservationIgnored private var playback: Task<Void, Never>?
    @ObservationIgnored private var resampled: [Int: [GeoPoint]] = [:]
    /// Bumped whenever what the map draws changes outside of time-based animation.
    var frameVersion = 0
    /// Bumped when the route settles, to send one ring out from the turnaround.
    private(set) var pulseID = 0
    /// How much of the shown route is drawn, 0...1 (markers appear as the line passes them).
    var drawnFraction: Double = 1

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

    // Launch and the wait (loop-launch-and-wait-v1): logo, landing sheet, reading, reach, candidates, build.
    enum Stage: Equatable { case logo, landing, typing, reading, building, settled }
    var stage: Stage = .settled
    /// The runner's sentence, shown as the whole header once sent.
    var requestText: String?
    /// The example the landing field types in its placeholder colour at launch.
    var fieldExample = ""
    /// What the runner has typed in the landing field (kept when editing ends, cleared by Cancel).
    var fieldText = ""
    /// While true, the map's bottom padding follows the landing sheet's live height every frame, so
    /// the location glides with the sheet. Off during a one-off camera ease (going home).
    var landingCameraBound = true
    /// Bumped to focus the landing field (debug screenshots).
    var focusFieldRequest = 0
    /// The on-screen keyboard's height over the screen bottom (0 when hidden).
    var keyboardHeight: CGFloat = 0
    /// The runner is typing in the landing field: the sheet shows matching recent and saved runs.
    var searchMode: Bool { stage == .typing && !demoTyping }
    /// Recent requests and saved runs under the field, filtered by what's typed.
    var fieldMatches: [RunMatch] { runs.matches(fieldText) }
    /// The logo covering the map at launch.
    var logoShown = false
    /// The landing sheet is up (it rises at launch and slides away on send).
    var landingShown = false
    /// The landing sheet's height, frame by frame (its own observable, like the route sheet).
    let landing = SheetState(collapsed: 300, open: 300)
    /// While the landing sheet rises or slides away it moves whole, anchored at this height.
    var landingAnchor: CGFloat?
    /// Saved runs and recent routes, on the phone.
    let runs: RunStore
    /// The request whose route goes to Recent once it settles (sent requests only).
    @ObservationIgnored var recordOnSettle: String?
    /// The sheet is hidden while Loop reads and slides up at the settle.
    var sheetShown = true
    /// The location pulses until the leader starts drawing.
    var locationPulsing = false
    /// How Loop read the request (understood words, filled in, can't-do, notes).
    var readOut: ReadOut? { didSet { applyReadOutToSheet() } }
    /// Edit mode: the sentence is editable and its understood words open the editor.
    var editMode = false
    /// The sentence as editable text (after tapping a word that isn't underlined).
    var editingText = false
    enum EditTarget: Equatable { case understood(String), filled(String) }
    var editing: EditTarget?
    /// Bumped to scroll the sheet to "How Loop read it".
    var scrollToReadIt = 0

    /// The map has drawn its first full frame (style and tiles): the logo fades only after this.
    var mapReady = false
    /// The debug demo plays "you tap and send" without bringing up the keyboard.
    var demoTyping = false
    @ObservationIgnored var reachStart: CFTimeInterval?
    @ObservationIgnored var reachFadeStart: CFTimeInterval?
    @ObservationIgnored var candidatesStart: CFTimeInterval?
    @ObservationIgnored var flow: Task<Void, Never>?
    /// The runner's location: Core Location (when-in-use) when this build talks to the server;
    /// otherwise, and until a fix arrives, the bundled file's public start (Kips Bay Library).
    var location: GeoPoint {
        if LoopAPI.baseURL != nil, let h = locationProvider.here {
            return GeoPoint(lon: h.coordinate.longitude, lat: h.coordinate.latitude)
        }
        return fixtureStart
    }
    @ObservationIgnored let fixtureStart: GeoPoint
    let locationProvider = LocationProvider()
    /// How far the runner can go from the start: the server's `reach_m` on a live build, else half
    /// the bundled route's distance (out and back).
    var reachMetres: Double {
        liveReachM ?? (fixtureData.candidate(rank: 1)?.detail?.distanceMi ?? 3) / 2 * Units.metresPerMile
    }

    // Live builds (Phase 3 server; LiveFlow.swift).
    @ObservationIgnored var liveTask: Task<Void, Never>?
    /// This build streams from the server.
    var liveMode = false
    @ObservationIgnored var liveReachM: Double?
    /// A stable integer key per server route id, so morphs and the build state work by key.
    @ObservationIgnored var liveKeys: [String: Int] = [:]
    @ObservationIgnored var liveSentAt: CFTimeInterval = 0
    /// The last line from the stream (an event or a ping), for the watchdog.
    @ObservationIgnored var liveLastActivity: CFTimeInterval = 0
    @ObservationIgnored var liveWatchdog: Task<Void, Never>?
    /// The launch health check failed: the landing sheet says so, with Try again.
    var serverDown = false
    @ObservationIgnored var liveParsedAt: CFTimeInterval?
    @ObservationIgnored var liveSentence = ""
    @ObservationIgnored var liveParseId: String?
    @ObservationIgnored var liveExpiredRetried = false
    /// The automatic resend after `expired` is under way (it mustn't reset the once-only guard).
    @ObservationIgnored var liveResending = false
    @ObservationIgnored var liveRouteId: String?
    /// The latest parse's constraints: a chip edit changes one field and sends them back.
    @ObservationIgnored var liveConstraints: JSONValue?
    /// The last request body, so Try again repeats a chip edit too, not just the text.
    @ObservationIgnored var liveLastBody: RunRequest?
    /// Outlines of the routes the engine tries, with when each arrived (drawn in over 0.7 s).
    @ObservationIgnored var liveOutlines: [(points: [GeoPoint], at: CFTimeInterval)] = []
    /// A question from the parser or the engine, waiting for the runner.
    var pendingQuestion: ServerEvent.Question?
    /// A plain message instead of a spinner: the server is unreachable, or an error event.
    var liveNotice: LiveNotice?
    /// The token screen is up (no token yet, or the server said it's wrong).
    var needsToken = false
    var tokenMessage: String?

    // Camera and projection (set by the map)
    var cameraRequest = CameraRequest()
    var zoom: Double = 14
    /// Bumped on every camera move so marker overlays re-place themselves.
    private(set) var cameraTick = 0
    @ObservationIgnored var project: ((GeoPoint) -> CGPoint?)?
    var headerBottom: CGFloat = 230

    init(data: LoopData, runs: RunStore) {
        self.data = data
        self.fixtureData = data
        self.fixtureStart = data.candidate(rank: 1)?.detail?.start ?? data.candidates[0].line.points[0]
        self.needsToken = LoopAPI.baseURL != nil && TokenStore.load() == nil
        self.runs = runs
        build = .settled(top3: data.candidates.map(\.rank))
        landing.slide(to: 0, animated: false)
    }

    var shown: Candidate? { shownRank.flatMap { data.candidate(rank: $0) } }
    var shownDetail: RouteDetail? { shown?.detail }

    /// The overview frames the shown route only: it is the hero. The faint #2 and #3 may run off
    /// screen or under the header fade (framing all three made the hero too small).
    var overviewCoordinates: [GeoPoint] {
        guard let c = shown ?? data.candidates.first else { return [] }
        return Self.fitPoints(c)
    }

    /// What a route fit frames: the line (simplified), its start, turnaround and every mile mark.
    static func fitPoints(_ c: Candidate) -> [GeoPoint] {
        var pts = DisplayLine.simplify(c.line.points, tolerance: 4).map { c.line.points[$0] }
        if let d = c.detail {
            pts.append(d.start)
            if let t = d.turnaround { pts.append(t.point) }
            pts += d.miles.map(\.point)
        }
        return pts
    }

    /// The runner panned or zoomed after the route appeared: no automatic refits until "Fit route".
    var routeCameraFree = false

    /// Glide to fit the route above the sheet, unless the runner has moved the map.
    func autoFitRoute(duration: TimeInterval) {
        guard !routeCameraFree, shown != nil else { return }
        requestCamera(.overview, animated: true, duration: duration)
    }

    /// "Fit route": back to the framed route, and automatic fits resume.
    func fitRoute() {
        routeCameraFree = false
        requestCamera(.overview, animated: true, duration: 0.5)
    }

    var eyebrowText: String {
        CardText.eyebrow(kind: data.request.mode.uppercased(), bestOf: showsCount ? data.bestOf : nil)
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

    func receiveEvent(_ event: BuildEvent, at t: CFTimeInterval) { receive(event, at: t) }
    func playbackCancel() { playback?.cancel() }

    private func receive(_ event: BuildEvent, at t: CFTimeInterval) {
        let wasSettled = build.settleAt
        let wasShown = build.shownRank
        let wasBounds = shown.map { Self.fitPoints($0) }.map(GeoBounds.init)
        build.apply(event, at: t)
        frameVersion += 1
        // A new leader, the flag, or a final that changed the route: glide to fit it again.
        switch event {
        case .top3:
            if wasShown != nil, build.shownRank != wasShown { autoFitRoute(duration: 0.6) }
        case .provisional:
            autoFitRoute(duration: SheetState.settleDuration)
        case .final:
            let now = shown.map { Self.fitPoints($0) }.map(GeoBounds.init)
            if build.shownRank != wasShown || now?.differs(from: wasBounds) == true { autoFitRoute(duration: 0.5) }
        }
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

    // MARK: Read-out, edit mode and the editor

    func applyReadOutToSheet() {
        sheet.extra = (readOut?.cant.isEmpty ?? true) ? 0 : 26
        if !(readOut?.hasReadIt ?? false) { sheet.readHeight = nil }
        sheet.refreshRest()
    }

    /// The card's can't-do line: open the sheet straight to "How Loop read it".
    func openReadIt() {
        touch()
        sheet.settle(rest: sheet.readHeight == nil ? .open : .read, animated: true)
        scrollToReadIt += 1
    }

    func enterEditMode() { guard stage == .settled, requestText != nil else { return }; editMode = true; editing = nil }
    func exitEditMode() { editMode = false; editingText = false; editing = nil }
    func openEditor(_ target: EditTarget) { touch(); editing = target }

    /// Done in the editor. Until the app is wired to the server this updates the sentence and the
    /// list locally; with the server it resends the constraints (no Claude) and rebuilds.
    func applyEdit(field: String, value: String, phrase: String?, constraint: (key: String, value: JSONValue)? = nil) {
        // Live: resend the parse's constraints with this one change; the route rebuilds.
        if liveMode {
            editing = nil
            if let constraint, rebuildLive(field: field, key: constraint.key, value: constraint.value) {
                updateSentence(field: field, value: value, phrase: phrase)
            }
            return
        }
        updateSentence(field: field, value: value, phrase: phrase)
    }

    /// The sentence and the read-out after an edit: the edited words replace the runner's.
    private func updateSentence(field: String, value: String, phrase: String?) {
        guard var r = readOut else { editing = nil; return }
        if let i = r.understood.firstIndex(where: { $0.field == field }) {
            let u = r.understood[i]
            if let phrase, let text = requestText {
                let ns = text as NSString
                let new = ns.replacingCharacters(in: NSRange(location: u.start, length: u.length), with: phrase)
                let delta = (phrase as NSString).length - u.length
                requestText = new
                for j in r.understood.indices where r.understood[j].start > u.start {
                    let x = r.understood[j]
                    r.understood[j] = .init(start: x.start + delta, length: x.length, field: x.field, title: x.title, value: x.value)
                }
                r.understood[i] = .init(start: u.start, length: (phrase as NSString).length, field: u.field, title: u.title, value: value)
            }
        }
        readOut = r
        editing = nil
    }

    // MARK: Sheet

    func setSheet(open: Bool, animated: Bool) {
        // The route fit follows the sheet's height frame by frame (RouteMapView), so no refit here.
        sheet.settle(open: open, animated: animated)
        sheetOpened(open)
    }

    func sheetDragEnded(predictedTranslation: CGFloat, animated: Bool) {
        // Swiped down past collapsed: dismiss the card and go home.
        if sheet.isDismissSwipe(predictedTranslation: predictedTranslation) {
            goHome()
            return
        }
        sheet.endDrag(predictedTranslation: predictedTranslation, animated: animated) { _ in }
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

    func requestCamera(_ kind: CameraRequest.Kind, animated: Bool, duration: TimeInterval = Motion.mapPan) {
        cameraRequest = CameraRequest(id: cameraRequest.id + 1, kind: kind, animated: animated, duration: duration)
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
        if waitIsMoving(now: now, reduceMotion: reduceMotion) { return true }
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
        frame.reach = reachFrame(now: now, reduceMotion: reduceMotion)
        (frame.candidates, frame.candidateOpacity) = candidateFrame(now: now, reduceMotion: reduceMotion)
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
