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
        /// A fixed center and zoom (debug and screenshots).
        case at(GeoPoint, zoom: Double)
    }
    var id = 0
    var kind: Kind = .overview
    var animated = false
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
        c.handle(model.cameraRequest)
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
            // Taps only (Mapbox's tap recognizer): drags and pans never select.
            mapView.gestures.onMapTap.observe { [weak self] context in
                MainActor.assumeIsolated { self?.mapTapped(at: context.point) }
            }.store(in: &cancelables)
            // Logo and attribution ride 8 pt above the sheet on every frame, outside SwiftUI.
            model.sheet.onHeightChange = { [weak self] h in self?.setBottomInset(h) }
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

        func setDark(_ value: Bool) {
            guard value != dark else { return }
            dark = value
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
            static let waterMask = "loop-water-mask"
            static func kind(_ k: DrawKind) -> String { "loop-route-\(k.rawValue)" }
        }

        private func addRouteLayers(_ map: MapboxMap) {
            let empty = FeatureCollection(features: [])
            for id in [Ids.othersSource, Ids.routeSource] where !map.sourceExists(withId: id) {
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
            if frame.othersOpacity != lastFrame?.othersOpacity {
                try? map.setLayerProperty(for: Ids.others, property: "line-opacity", value: frame.othersOpacity)
            }
            lastFrame = frame
        }

        // MARK: Camera

        private func cameraChanged() {
            guard let map = mapView?.mapboxMap else { return }
            model.cameraDidChange(zoom: map.cameraState.zoom)
            updateRoadLabels()
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
            guard let map = mapView?.mapboxMap, let line = model.shown?.line, model.shownDetail != nil else { return }
            let projected = line.points.map { map.point(for: $0.coordinate) }
            if let hit = RouteHit.nearest(to: tap, projected: projected, cumulative: line.cumulative),
               hit.distance <= RouteHit.tolerance {
                model.selectPoint(alongM: hit.alongM)
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
                let coords = model.overviewCoordinates.map(\.coordinate)
                let padding = UIEdgeInsets(top: model.headerBottom + 28, left: 44,
                                           bottom: model.sheet.restingHeight + 40 + 22, right: 44)
                target = try? map.camera(for: coords, camera: CameraOptions(), coordinatesPadding: padding,
                                         maxZoom: 16, offset: nil)
            case let .focus(point):
                // Pan only if the point is outside the band between the header and the sheet.
                let now = map.point(for: point.coordinate)
                let top = model.headerBottom + 28, bottom = size.height - model.sheet.restingHeight - 40
                if now.x > 60, now.x < size.width - 60, now.y > top, now.y < bottom { return }
                let goal = CGPoint(x: size.width * 0.62, y: (top + bottom) / 2)
                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let shifted = CGPoint(x: center.x + (now.x - goal.x), y: center.y + (now.y - goal.y))
                target = CameraOptions(center: map.coordinate(for: shifted))
            case let .at(point, zoom):
                target = CameraOptions(center: point.coordinate, zoom: zoom)
            }
            guard let target else { return }
            if request.animated && !reduceMotion {
                mapView.camera.ease(to: target, duration: Motion.mapPan, curve: .easeInOut)
            } else {
                map.setCamera(to: target)
            }
        }
    }
}
