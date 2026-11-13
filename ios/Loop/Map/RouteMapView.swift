import MapboxMaps
import SwiftUI
import UIKit

/// Asks the map to move. Each request has a new id so the same move can be asked twice.
struct CameraRequest: Equatable {
    enum Kind: Equatable {
        /// Fit the lead route between the header and the sheet.
        case overview
        /// Put a point just above the sheet, a little right of center (room for the chip).
        case focus(GeoPoint)
        /// A center and zoom (launch, the push-in while reading; debug screenshots).
        case at(GeoPoint, zoom: Double)
        /// Fit a circle (the reach ring) between the header and the bottom.
        case circle(GeoPoint, radiusM: Double)
        /// Centre a point in the map area between the header and `bottom` points from the screen's
        /// bottom (the landing sheet and keyboard); keeps the zoom unless one is given.
        case above(GeoPoint, bottom: CGFloat, zoom: Double?)
    }
    var id = 0
    var kind: Kind = .overview
    var animated = false
    var duration: TimeInterval = Motion.mapPan
}

/// Full-bleed Mapbox map. Draws the route frames the model hands it and reports camera moves
/// so SwiftUI can place the markers. Dragging the map never selects anything.
struct RouteMapView: UIViewRepresentable {
    let model: MainModel
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeCoordinator() -> Coordinator { Coordinator(model: model) }

    func makeUIView(context: Context) -> MapView {
        let dark = colorScheme == .dark
        // Start near the route (no world-view flash), with no style yet: the coordinator
        // subscribes to style-loaded first, then sets the style, so the event can't be missed.
        let start = model.overviewCoordinates.first?.coordinate
        let options = MapInitOptions(cameraOptions: CameraOptions(center: start, zoom: 13.5), styleURI: nil)
        let mapView = MapView(frame: .zero, mapInitOptions: options)
        mapView.ornaments.options.scaleBar.visibility = .hidden
        mapView.ornaments.options.compass.visibility = .hidden
        mapView.gestures.options.pitchEnabled = false
        mapView.gestures.options.rotateEnabled = false
        mapView.backgroundColor = Palette.mapLand.uiColor
        context.coordinator.attach(mapView, dark: dark)
        return mapView
    }

    func updateUIView(_ mapView: MapView, context: Context) {
        let c = context.coordinator
        c.reduceMotion = reduceMotion
        c.setDark(colorScheme == .dark)
        c.setBottomInset(Self.ornamentInset(model))
        c.setOrnamentAlpha(Self.ornamentAlpha(model))
        c.handle(model.cameraRequest)
    }

    /// Logo and attribution ride 8 pt above whatever is at the bottom: the route sheet, or the
    /// landing sheet. Before the landing sheet first rises they already sit above its place, so they
    /// don't jump when it comes; on send they follow it down.
    @MainActor static func ornamentInset(_ model: MainModel) -> CGFloat {
        if model.sheetShown { return model.sheet.height }
        let beforeLanding = model.stage == .logo || (model.stage == .landing && !model.landingShown)
        return beforeLanding ? max(model.landing.height, model.landing.openHeight) : model.landing.height
    }

    /// Hidden while the route sheet is expanded past its open state ("How Loop read it" covers
    /// the map): they fade out over that stretch of the drag and back in below it.
    @MainActor static func ornamentAlpha(_ model: MainModel) -> CGFloat {
        model.sheetShown ? 1 - model.sheet.readProgress : 1
    }

    static func dismantleUIView(_ uiView: MapView, coordinator: Coordinator) {
        coordinator.stop()
    }

    @MainActor
    final class Coordinator: NSObject {
        private let model: MainModel
        private weak var mapView: MapView?
        private var cancelables = Set<AnyCancelable>()
        private var styleReady = false
        private var dark = false
        private var bottomInset: CGFloat = Metrics.sheetCollapsed
        private var lastCameraRequestId = -1
        private var pendingCamera: CameraRequest?
        private var lastFrame: RouteFrame?
        private var lastFrameVersion = -1
        private var lastZoomKey = -1
        private var wasAnimating = false
        private var displayLink: CADisplayLink?
        private var roadLabelsOn: Bool?
        var reduceMotion = false { didSet { if oldValue != reduceMotion { lastFrame = nil; lastFrameVersion = -1 } } }

        init(model: MainModel) { self.model = model }

        func attach(_ mapView: MapView, dark: Bool) {
            self.mapView = mapView
            self.dark = dark
            mapView.mapboxMap.onStyleLoaded.observe { [weak self] _ in
                MainActor.assumeIsolated { self?.styleLoaded() }
            }.store(in: &cancelables)
            mapView.mapboxMap.onCameraChanged.observe { [weak self] _ in
                MainActor.assumeIsolated { self?.cameraChanged() }
            }.store(in: &cancelables)
            // The logo fades into the map once the map has drawn (style and tiles loaded).
            mapView.mapboxMap.onMapIdle.observeNext { [weak self] _ in
                MainActor.assumeIsolated { self?.model.mapReady = true }
            }.store(in: &cancelables)
            // Taps only (Mapbox's tap recognizer): drags and pans never select.
            mapView.gestures.onMapTap.observe { [weak self] context in
                MainActor.assumeIsolated { self?.mapTapped(at: context.point) }
            }.store(in: &cancelables)
            // Logo and attribution ride 8 pt above the sheet on every frame, outside SwiftUI.
            model.sheet.onHeightChange = { [weak self, weak model] h in
                guard let model, model.sheetShown else { return }
                self?.setBottomInset(h)
                self?.setOrnamentAlpha(RouteMapView.ornamentAlpha(model))
                self?.bindRouteFit(sheetHeight: h)
            }
            mapView.gestures.delegate = self
            model.landing.onHeightChange = { [weak self, weak model] h in
                guard let model, !model.sheetShown else { return }
                self?.setBottomInset(RouteMapView.ornamentInset(model))
                self?.bindLandingPadding(h)
            }
            mapView.ornaments.options.attributionButton.tintColor = Palette.inkMuted.uiColor
            model.project = { [weak mapView] p in
                guard let mapView else { return nil }
                return mapView.mapboxMap.point(for: p.coordinate)
            }
            let link = CADisplayLink(target: self, selector: #selector(tick))
            link.add(to: .main, forMode: .common)
            displayLink = link
            if MapStyle.hasToken {
                mapView.mapboxMap.styleURI = .standard
            } else {
                mapView.mapboxMap.styleJSON = MapStyle.blankStyleJSON(dark: dark)
            }
        }

        func stop() {
            displayLink?.invalidate()
            displayLink = nil
        }

        // MARK: Style

        private func styleLoaded() {
            guard let map = mapView?.mapboxMap else { return }
            styleReady = true
            applyStandardConfig()
            addRouteLayers(map)
            lastFrame = nil
            tick()
            if let pending = pendingCamera { pendingCamera = nil; move(pending) }
            else { move(CameraRequest(kind: .overview)) }
        }

        /// The candidate outlines are faint on purpose, but on the Night map 30% periwinkle barely
        /// reads (device, 2026-11-09), so Night draws them at twice the opacity.
        static func candidateBoost(dark: Bool) -> Double { dark ? 2 : 1 }

        func setDark(_ value: Bool) {
            guard value != dark else { return }
            dark = value
            lastFrame = nil
            mapView?.backgroundColor = Palette.mapLand.uiColor
            guard styleReady, let map = mapView?.mapboxMap else { return }
            if MapStyle.hasToken {
                applyStandardConfig()
            } else {
                try? map.setLayerProperty(for: "land", property: "background-color",
                                          value: Palette.mapLand.hex(dark: dark))
            }
            recolorRouteLayers(map)
        }

        private func applyStandardConfig() {
            guard MapStyle.hasToken, let map = mapView?.mapboxMap else { return }
            for (key, value) in MapStyle.standardConfig(dark: dark) {
                try? map.setStyleImportConfigProperty(for: "basemap", config: key, value: value)
            }
            roadLabelsOn = nil
            updateRoadLabels()
        }

        private func updateRoadLabels() {
            guard MapStyle.hasToken, let map = mapView?.mapboxMap else { return }
            let on = !dark && map.cameraState.zoom >= MapStyle.roadLabelMinZoom
            guard on != roadLabelsOn else { return }
            roadLabelsOn = on
            try? map.setStyleImportConfigProperty(for: "basemap", config: "showRoadLabels", value: on)
        }

        // MARK: Route layers

        private enum Ids {
            static let routeSource = "loop-route"
            static let othersSource = "loop-others"
            static let others = "loop-others-dots"
            static let casing = "loop-route-casing"
            static let lead = "loop-route-lead"     // plain line, no detail yet
            static let base = "loop-route-base"
            static let pathBed = "loop-route-path-bed"
            static let waterSource = "loop-water"
            static let reachSource = "loop-reach"
            static let candidatesSource = "loop-candidates"
            static let reachDim = "loop-reach-dim"
            static let reachRing = "loop-reach-ring"
            static let warmWater = "loop-warm-water"
            static let warmPark = "loop-warm-park"
            static let candidates = "loop-candidates"
            static let waterMask = "loop-water-mask"
            static func kind(_ k: DrawKind) -> String { "loop-route-\(k.rawValue)" }
        }

        private func addRouteLayers(_ map: MapboxMap) {
            let empty = FeatureCollection(features: [])
            for id in [Ids.othersSource, Ids.routeSource, Ids.reachSource, Ids.candidatesSource] where !map.sourceExists(withId: id) {
                var s = GeoJSONSource(id: id)
                s.data = .featureCollection(empty)
                // No simplification: the route is ~140 vertices, and simplifying each feature on
                // its own bends overlapping copies (an out-and-back) apart at mid zooms.
                s.tolerance = 0
                try? map.addSource(s)
            }
            let slot: Slot? = MapStyle.hasToken ? .top : nil
            if MapStyle.hasToken { addWaterMask(map) }

            var others = LineLayer(id: Ids.others, source: Ids.othersSource)
            others.lineWidth = .constant(3)
            others.lineCap = .constant(.round)
            others.lineDasharray = .constant([0.01, 2.2])   // round dots
            others.slot = slot
            try? map.addLayer(others)

            // The wait: warm water and parks (from Mapbox Streets' own shapes, token only), the dim
            // outside the reach ring, the ring, and the candidate lines. All under the route.
            if MapStyle.hasToken {
                var warmWater = FillLayer(id: Ids.warmWater, source: Ids.waterSource)
                warmWater.sourceLayer = "water"
                warmWater.fillOpacity = .constant(0)
                warmWater.fillEmissiveStrength = .constant(1)
                warmWater.slot = .middle
                try? map.addLayer(warmWater)
                var warmPark = FillLayer(id: Ids.warmPark, source: Ids.waterSource)
                warmPark.sourceLayer = "landuse"
                warmPark.filter = Exp(.eq) { Exp(.get) { "class" }; "park" }
                warmPark.fillOpacity = .constant(0)
                warmPark.fillEmissiveStrength = .constant(1)
                warmPark.slot = .middle
                try? map.addLayer(warmPark)
            }
            var dim = FillLayer(id: Ids.reachDim, source: Ids.reachSource)
            dim.filter = Exp(.eq) { Exp(.get) { "kind" }; "dim" }
            dim.fillOpacity = .constant(0)
            dim.fillEmissiveStrength = .constant(1)
            dim.slot = slot
            try? map.addLayer(dim)
            var ring = LineLayer(id: Ids.reachRing, source: Ids.reachSource)
            ring.filter = Exp(.eq) { Exp(.get) { "kind" }; "ring" }
            ring.lineWidth = .constant(1.6)
            ring.lineDasharray = .constant([4 / 1.6, 6 / 1.6])   // 4/6 pt, in line widths
            ring.lineOpacity = .constant(0)
            ring.lineEmissiveStrength = .constant(1)
            ring.slot = slot
            try? map.addLayer(ring)
            var cands = LineLayer(id: Ids.candidates, source: Ids.candidatesSource)
            cands.lineWidth = .constant(1.4)
            cands.lineCap = .constant(.round)
            cands.lineJoin = .constant(.round)
            cands.lineOpacity = .constant(0)
            cands.lineEmissiveStrength = .constant(1)
            cands.slot = slot
            try? map.addLayer(cands)

            // The casing is one line for the whole route (feature kind "casing"), under every run.
            var casing = LineLayer(id: Ids.casing, source: Ids.routeSource)
            casing.filter = Exp(.eq) { Exp(.get) { "kind" }; "casing" }
            casing.lineWidth = .constant(Double(Metrics.routeCasing))
            casing.lineCap = .constant(.round)
            casing.lineJoin = .constant(.round)
            casing.slot = slot
            try? map.addLayer(casing)

            // The base line: the whole route as one solid line in street style, round joins and
            // caps, from the same geometry as the casing. Kind styling goes on top of it.
            var base = LineLayer(id: Ids.base, source: Ids.routeSource)
            base.filter = Exp(.eq) { Exp(.get) { "kind" }; "casing" }
            base.lineWidth = .constant(3.5)
            base.lineCap = .constant(.round)
            base.lineJoin = .constant(.round)
            base.slot = slot
            try? map.addLayer(base)

            // Kind styling, cut edge to edge from the drawn line with butt caps (no overlaps):
            // the path bed (casing colour, so dash gaps read as gaps), path dashes or solid
            // short path, and waterfront. Street needs nothing: it is the base line.
            for (id, kind, width) in [(Ids.pathBed, "pathBed", 4.5), (Ids.kind(.path), "path", 4.5),
                                      (Ids.kind(.waterfront), "waterfront", 4.5)] {
                var l = LineLayer(id: id, source: Ids.routeSource)
                l.filter = Exp(.eq) { Exp(.get) { "kind" }; kind }
                l.lineCap = .constant(.butt)
                l.lineJoin = .constant(.round)
                l.lineWidth = .constant(width)
                l.slot = slot
                try? map.addLayer(l)
            }

            var lead = LineLayer(id: Ids.lead, source: Ids.routeSource)
            lead.filter = Exp(.eq) { Exp(.get) { "kind" }; "lead" }
            lead.lineWidth = .constant(4.5)
            lead.lineCap = .constant(.round)
            lead.lineJoin = .constant(.round)
            lead.slot = slot
            try? map.addLayer(lead)
            recolorRouteLayers(map)
        }

        /// Standard has no setting for ferry routes, which it draws as dashed lines on the water.
        /// Dashes on this map mean "path" only, so Mapbox Streets' own water polygons are drawn
        /// over them in our water color, in Standard's bottom slot (above the water, below roads
        /// and labels).
        private func addWaterMask(_ map: MapboxMap) {
            if !map.sourceExists(withId: Ids.waterSource) {
                var src = VectorSource(id: Ids.waterSource)
                src.url = "mapbox://mapbox.mapbox-streets-v8"
                try? map.addSource(src)
            }
            var water = FillLayer(id: Ids.waterMask, source: Ids.waterSource)
            water.sourceLayer = "water"
            water.fillAntialias = .constant(true)
            water.fillEmissiveStrength = .constant(1)
            water.slot = .middle
            try? map.addLayer(water)
        }

        private func recolorRouteLayers(_ map: MapboxMap) {
            func set(_ id: String, _ prop: String, _ token: Palette.Token) {
                try? map.setLayerProperty(for: id, property: prop, value: token.hex(dark: dark))
            }
            // Our layers ignore the basemap's lighting, so the route is never dimmed by a light preset.
            for id in [Ids.casing, Ids.base, Ids.pathBed, Ids.lead, Ids.others] + DrawKind.allCases.map(Ids.kind) {
                try? map.setLayerProperty(for: id, property: "line-emissive-strength", value: 1.0)
            }
            set(Ids.casing, "line-color", Palette.routeCasing)
            set(Ids.lead, "line-color", Palette.routeWater)
            set(Ids.base, "line-color", Palette.routeStreet)
            set(Ids.pathBed, "line-color", Palette.routeCasing)
            set(Ids.reachRing, "line-color", Palette.action)
            set(Ids.candidates, "line-color", Palette.action)
            try? map.setLayerProperty(for: Ids.reachDim, property: "fill-color", value: Palette.reachDim.hex(dark: dark))
            try? map.setLayerProperty(for: Ids.warmWater, property: "fill-color", value: Palette.warmWater.hex(dark: dark))
            try? map.setLayerProperty(for: Ids.warmPark, property: "fill-color", value: Palette.warmPark.hex(dark: dark))
            try? map.setLayerProperty(for: Ids.waterMask, property: "fill-color", value: Palette.mapWater.hex(dark: dark))
            set(Ids.others, "line-color", Palette.routeStreet)
            for k in DrawKind.allCases { set(Ids.kind(k), "line-color", Palette.drawColor(k)) }
        }

        // MARK: Frames

        @objc private func tick() {
            guard styleReady, let mapView, let map = mapView.mapboxMap else { return }
            placeOrnaments()
            if let pending = pendingCamera, mapView.bounds.width > 0 {
                pendingCamera = nil
                move(pending)
            }
            let now = CACurrentMediaTime()
            // Idle: nothing changed and nothing is moving, so skip the frame work entirely.
            // Route detail follows the zoom, so a zoom change counts as a change.
            let zoomKey = Int((model.zoom * 20).rounded())
            if lastFrame != nil, model.frameVersion == lastFrameVersion, zoomKey == lastZoomKey,
               !model.isAnimating(now: now, reduceMotion: reduceMotion), !wasAnimating { return }
            wasAnimating = model.isAnimating(now: now, reduceMotion: reduceMotion)
            lastFrameVersion = model.frameVersion
            lastZoomKey = zoomKey
            let frame = model.frame(now: now, reduceMotion: reduceMotion)
            guard frame != lastFrame else { return }
            // Casing and runs go in one source update, so no frame shows one without the other.
            if frame.lead != lastFrame?.lead || frame.casing != lastFrame?.casing {
                var features: [Feature] = []
                if frame.casing.count >= 2 {
                    var c = Feature(geometry: LineString(frame.casing.map(\.coordinate)))
                    c.properties = ["kind": .string("casing")]
                    features.append(c)
                }
                features += frame.lead.map { seg in
                    var f = Feature(geometry: LineString(seg.points.map(\.coordinate)))
                    f.properties = ["kind": .string(seg.layerKind)]
                    return f
                }
                map.updateGeoJSONSource(withId: Ids.routeSource, geoJSON: .featureCollection(FeatureCollection(features: features)))
            }
            if frame.others != lastFrame?.others {
                let features = frame.others.filter { $0.count >= 2 }.map {
                    Feature(geometry: LineString($0.map(\.coordinate)))
                }
                map.updateGeoJSONSource(withId: Ids.othersSource, geoJSON: .featureCollection(FeatureCollection(features: features)))
            }
            if frame.reach != lastFrame?.reach { drawReach(map, frame.reach) }
            if frame.candidates != lastFrame?.candidates {
                let features = frame.candidates.map { Feature(geometry: LineString($0.map(\.coordinate))) }
                map.updateGeoJSONSource(withId: Ids.candidatesSource, geoJSON: .featureCollection(FeatureCollection(features: features)))
            }
            if frame.candidateOpacity != lastFrame?.candidateOpacity {
                try? map.setLayerProperty(for: Ids.candidates, property: "line-opacity",
                                          value: frame.candidateOpacity * Self.candidateBoost(dark: dark))
            }
            if frame.othersOpacity != lastFrame?.othersOpacity {
                try? map.setLayerProperty(for: Ids.others, property: "line-opacity", value: frame.othersOpacity)
            }
            lastFrame = frame
        }

        /// The reach ring and the dim outside it; warm water and parks fade with the ring.
        private func drawReach(_ map: MapboxMap, _ reach: RouteFrame.Reach?) {
            var features: [Feature] = []
            if let r = reach, r.radiusM > 1 {
                let circle = RouteFrame.circle(r.center, radiusM: r.radiusM).map(\.coordinate)
                let world = [(-179.9, -85.0), (179.9, -85.0), (179.9, 85.0), (-179.9, 85.0), (-179.9, -85.0)]
                    .map { CLLocationCoordinate2D(latitude: $0.1, longitude: $0.0) }
                var dim = Feature(geometry: Polygon([world, circle.reversed()]))
                dim.properties = ["kind": .string("dim")]
                var ring = Feature(geometry: LineString(circle))
                ring.properties = ["kind": .string("ring")]
                features = [dim, ring]
            }
            map.updateGeoJSONSource(withId: Ids.reachSource, geoJSON: .featureCollection(FeatureCollection(features: features)))
            try? map.setLayerProperty(for: Ids.reachDim, property: "fill-opacity", value: reach?.dimOpacity ?? 0)
            try? map.setLayerProperty(for: Ids.reachRing, property: "line-opacity", value: reach?.ringOpacity ?? 0)
            // Warm water and parks inside the ring (the dim softens them outside it).
            try? map.setLayerProperty(for: Ids.warmWater, property: "fill-opacity", value: reach?.warmOpacity ?? 0)
            try? map.setLayerProperty(for: Ids.warmPark, property: "fill-opacity", value: reach?.warmOpacity ?? 0)
        }

        // MARK: Camera

        private func cameraChanged() {
            guard let map = mapView?.mapboxMap else { return }
            model.cameraDidChange(zoom: map.cameraState.zoom)
            updateRoadLabels()
        }

        /// On the landing, the map's bottom padding is the landing sheet's live height, set every
        /// frame the sheet moves: whatever the map is centred on (the location, unless the runner
        /// panned) stays centred in the space above the sheet and glides with it. No camera
        /// animation is started, so nothing stacks or jumps.
        private func bindLandingPadding(_ sheetHeight: CGFloat) {
            guard let mapView, let map = mapView.mapboxMap, styleReady, model.landingCameraBound,
                  [.logo, .landing, .typing].contains(model.stage), mapView.bounds.height > 0 else { return }
            let top = model.headerBottom
            let bottom = max(0, min(sheetHeight, mapView.bounds.height - top - 40))
            let padding = UIEdgeInsets(top: sheetHeight > 0 ? top : 0, left: 0, bottom: bottom, right: 0)
            guard map.cameraState.padding != padding else { return }
            map.setCamera(to: CameraOptions(padding: padding))
        }

        /// The route fit: the whole route with its start, turnaround and mile marks between the
        /// header and the sheet's top, 24 pt in from each edge plus 16 pt for the marks and labels
        /// that sit beside the line, and at least 40 pt above the sheet.
        private func routeFit(_ map: MapboxMap, sheetHeight: CGFloat) -> CameraOptions? {
            let coords = model.overviewCoordinates.map(\.coordinate)
            guard coords.count >= 2 else { return nil }
            let marks: CGFloat = 16
            let padding = UIEdgeInsets(top: model.headerBottom + 24 + marks, left: 24 + marks,
                                       bottom: sheetHeight + 40 + marks, right: 24 + marks)
            return try? map.camera(for: coords, camera: CameraOptions(padding: .zero), coordinatesPadding: padding,
                                   maxZoom: 16.5, offset: nil)
        }

        /// While the route card moves (drag or settle), the fit follows its height every frame, so
        /// the route stays framed above it in one motion. Not after the runner moved the map.
        private func bindRouteFit(sheetHeight: CGFloat) {
            guard styleReady, let mapView, let map = mapView.mapboxMap, !model.routeCameraFree,
                  model.shown != nil, [.building, .settled].contains(model.stage),
                  let target = routeFit(map, sheetHeight: sheetHeight) else { return }
            mapView.camera.cancelAnimations()
            map.setCamera(to: target)
        }

        func setOrnamentAlpha(_ alpha: CGFloat) {
            guard let mapView, mapView.ornaments.logoView.alpha != alpha else { return }
            mapView.ornaments.logoView.alpha = alpha
            mapView.ornaments.attributionButton.alpha = alpha
            mapView.ornaments.attributionButton.isUserInteractionEnabled = alpha > 0.5
        }

        func setBottomInset(_ inset: CGFloat) {
            bottomInset = inset
            placeOrnaments()
        }

        private var placedOrnamentsFor: (CGFloat, CGFloat)?

        /// Mapbox's logo and attribution must stay visible: 8 pt above the sheet's top, following it.
        /// Ornament margins count from the safe area, so the home-indicator inset comes off.
        private func placeOrnaments() {
            guard let mapView else { return }
            let safe = mapView.safeAreaInsets.bottom
            if let placed = placedOrnamentsFor, placed == (bottomInset, safe) { return }
            placedOrnamentsFor = (bottomInset, safe)
            mapView.ornaments.options.logo.margins = CGPoint(x: 12, y: bottomInset + 8 - safe)
            mapView.ornaments.options.attributionButton.margins = CGPoint(x: 8, y: bottomInset + 8 - safe)
        }

        /// A tap within 22 pt of the shown route selects the nearest point on it; elsewhere it
        /// clears the selection. Mile marks and chips are SwiftUI views above the map, so their
        /// taps never get here.
        private func mapTapped(at tap: CGPoint) {
            // Typing in the landing field: a tap on the map ends editing, nothing more.
            if model.searchMode { model.endTyping(); return }
            guard let map = mapView?.mapboxMap, let line = model.shown?.line, model.shownDetail != nil else { return }
            let projected = line.points.map { map.point(for: $0.coordinate) }
            if let hit = RouteHit.nearest(to: tap, projected: projected, cumulative: line.cumulative),
               hit.distance <= RouteHit.tolerance {
                model.selectPoint(alongM: hit.alongM)
                return
            }
            // One of the other two routes (faint dots after `final`): open it.
            let nearest = model.routeChoices.filter { $0 != model.shownRank }.compactMap { rank -> (Int, Double)? in
                guard let other = model.data.candidate(rank: rank)?.line else { return nil }
                let pts = other.points.map { map.point(for: $0.coordinate) }
                return RouteHit.nearest(to: tap, projected: pts, cumulative: other.cumulative).map { (rank, $0.distance) }
            }.min { $0.1 < $1.1 }
            if let (rank, d) = nearest, d <= RouteHit.tolerance {
                model.showRoute(rank: rank)
            } else {
                model.clearSelection()
            }
        }

        func handle(_ request: CameraRequest) {
            guard request.id != lastCameraRequestId else { return }
            lastCameraRequestId = request.id
            guard styleReady else { pendingCamera = request; return }
            move(request)
        }

        private func move(_ request: CameraRequest) {
            guard let mapView, let map = mapView.mapboxMap else { return }
            let size = mapView.bounds.size
            guard size.width > 0 else { pendingCamera = request; return }
            let target: CameraOptions?
            switch request.kind {
            case .overview:
                // Clear of the header (START sits above the dot), and the route at least 40 pt
                // above the sheet's top (TURN hangs below the ring), in whichever state the sheet rests.
                // Before the card rises, fit above where it will rest (its collapsed height).
                target = routeFit(map, sheetHeight: model.sheet.restingHeight)
            case let .focus(point):
                // Pan only if the point is outside the band between the header and the sheet.
                let now = map.point(for: point.coordinate)
                let top = model.headerBottom + 28, bottom = size.height - model.sheet.restingHeight - 40
                if now.x > 60, now.x < size.width - 60, now.y > top, now.y < bottom { return }
                let goal = CGPoint(x: size.width * 0.62, y: (top + bottom) / 2)
                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let shifted = CGPoint(x: center.x + (now.x - goal.x), y: center.y + (now.y - goal.y))
                target = CameraOptions(center: map.coordinate(for: shifted), padding: .zero)
            case let .at(point, zoom):
                target = CameraOptions(center: point.coordinate, padding: .zero, zoom: zoom)
            case let .circle(center, radiusM):
                let ring = RouteFrame.circle(center, radiusM: radiusM, points: 32).map(\.coordinate)
                let padding = UIEdgeInsets(top: model.headerBottom + 20, left: 24, bottom: 60, right: 24)
                target = try? map.camera(for: ring, camera: CameraOptions(padding: .zero), coordinatesPadding: padding,
                                         maxZoom: 17, offset: nil)
            case let .above(point, bottom, zoom):
                // Camera padding moves the centre into the area left between the header and the sheet.
                let padding = UIEdgeInsets(top: model.headerBottom, left: 0, bottom: min(bottom, size.height - model.headerBottom - 40), right: 0)
                target = CameraOptions(center: point.coordinate, padding: padding, zoom: zoom.map { CGFloat($0) })
            }
            guard let target else { return }
            // A new move replaces any running one (an unfinished drift would otherwise pull the
            // camera back to where it was heading).
            mapView.camera.cancelAnimations()
            if request.animated && !reduceMotion {
                mapView.camera.ease(to: target, duration: request.duration, curve: .easeInOut)
            } else {
                map.setCamera(to: target)
            }
        }
    }
}

/// The runner panned, pinched, rotated or double-tapped the map after the route appeared: stop
/// fitting it automatically and offer "Fit route". A single tap (selecting the route) doesn't count.
extension RouteMapView.Coordinator: GestureManagerDelegate {
    nonisolated func gestureManager(_ gestureManager: GestureManager, didBegin gestureType: GestureType) {
        MainActor.assumeIsolated {
            guard gestureType != .singleTap, model.shown != nil,
                  [.building, .settled].contains(model.stage) else { return }
            model.routeCameraFree = true
        }
    }
    nonisolated func gestureManager(_ gestureManager: GestureManager, didEnd gestureType: GestureType, willAnimate: Bool) {}
    nonisolated func gestureManager(_ gestureManager: GestureManager, didEndAnimatingFor gestureType: GestureType) {}
}
