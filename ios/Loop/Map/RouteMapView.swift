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
        c.setBottomInset(model.sheetHeight)
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
            let on = map.cameraState.zoom >= MapStyle.roadLabelMinZoom
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
            static func kind(_ k: DrawKind) -> String { "loop-route-\(k.rawValue)" }
        }

        private func addRouteLayers(_ map: MapboxMap) {
            let empty = FeatureCollection(features: [])
            for id in [Ids.othersSource, Ids.routeSource] where !map.sourceExists(withId: id) {
                var s = GeoJSONSource(id: id)
                s.data = .featureCollection(empty)
                try? map.addSource(s)
            }
            let slot: Slot? = MapStyle.hasToken ? .top : nil

            var others = LineLayer(id: Ids.others, source: Ids.othersSource)
            others.lineWidth = .constant(3)
            others.lineCap = .constant(.round)
            others.lineDasharray = .constant([0.01, 2.2])   // round dots
            others.slot = slot
            try? map.addLayer(others)

            var casing = LineLayer(id: Ids.casing, source: Ids.routeSource)
            casing.lineWidth = .constant(Double(Metrics.routeCasing))
            casing.lineCap = .constant(.round)
            casing.lineJoin = .constant(.round)
            casing.slot = slot
            try? map.addLayer(casing)

            // Street under path under waterfront under the plain lead line.
            for kind in [DrawKind.street, .path, .waterfront] {
                var l = LineLayer(id: Ids.kind(kind), source: Ids.routeSource)
                l.filter = Exp(.eq) { Exp(.get) { "kind" }; kind.rawValue }
                l.lineCap = .constant(kind == .path ? .butt : .round)
                l.lineJoin = .constant(.round)
                switch kind {
                case .waterfront: l.lineWidth = .constant(4.5)
                case .path:
                    l.lineWidth = .constant(4.5)
                    l.lineDasharray = .constant([9 / 4.5, 6 / 4.5])   // 9/6 pt, in line widths
                case .street: l.lineWidth = .constant(3.5)
                }
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

        private func recolorRouteLayers(_ map: MapboxMap) {
            func set(_ id: String, _ prop: String, _ token: Palette.Token) {
                try? map.setLayerProperty(for: id, property: prop, value: token.hex(dark: dark))
            }
            set(Ids.casing, "line-color", Palette.routeCasing)
            set(Ids.lead, "line-color", Palette.routeWater)
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
            if lastFrame != nil, model.frameVersion == lastFrameVersion,
               !model.isAnimating(now: now, reduceMotion: reduceMotion), !wasAnimating { return }
            wasAnimating = model.isAnimating(now: now, reduceMotion: reduceMotion)
            lastFrameVersion = model.frameVersion
            let frame = model.frame(now: now, reduceMotion: reduceMotion)
            guard frame != lastFrame else { return }
            if frame.lead != lastFrame?.lead {
                let features: [Feature] = frame.lead.map { seg in
                    var f = Feature(geometry: LineString(seg.points.map(\.coordinate)))
                    f.properties = ["kind": .string(seg.kind?.rawValue ?? "lead")]
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

        /// Mapbox's logo and attribution must stay visible: keep them just above the sheet.
        /// Ornament margins count from the safe area, so the home-indicator inset comes off.
        private func placeOrnaments() {
            guard let mapView else { return }
            let safe = mapView.safeAreaInsets.bottom
            if let placed = placedOrnamentsFor, placed == (bottomInset, safe) { return }
            placedOrnamentsFor = (bottomInset, safe)
            mapView.ornaments.options.logo.margins = CGPoint(x: 12, y: bottomInset + 6 - safe)
            mapView.ornaments.options.attributionButton.margins = CGPoint(x: 8, y: bottomInset + 4 - safe)
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
                let coords = model.overviewCoordinates.map(\.coordinate)
                let padding = UIEdgeInsets(top: model.headerBottom + 44, left: 44,
                                           bottom: Metrics.sheetCollapsed + 36, right: 44)
                target = try? map.camera(for: coords, camera: CameraOptions(), coordinatesPadding: padding,
                                         maxZoom: 16, offset: nil)
            case let .focus(point):
                // Put the point at (62% of the width, 64 pt above the open sheet), same zoom,
                // which keeps the chip clear of the Mapbox logo just above the sheet.
                let goal = CGPoint(x: size.width * 0.62, y: size.height - Metrics.sheetOpen - 64)
                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let now = map.point(for: point.coordinate)
                let shifted = CGPoint(x: center.x + (now.x - goal.x), y: center.y + (now.y - goal.y))
                target = CameraOptions(center: map.coordinate(for: shifted))
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
