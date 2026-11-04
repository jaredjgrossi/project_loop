import Foundation
import MapboxMaps
import UIKit

/// The quiet map. With a Mapbox token: Mapbox Standard, configured through the style-import
/// properties listed in Mapbox's Standard style reference (docs.mapbox.com/map-styles/standard/api,
/// checked 2026-11-04). Without one: a plain paper background, so the route and layout can
/// still be checked.
enum MapStyle {
    static var accessToken: String? {
        guard let t = Bundle.main.object(forInfoDictionaryKey: "MBXAccessToken") as? String,
              t.hasPrefix("pk.") else { return nil }
        return t
    }

    static var hasToken: Bool { accessToken != nil }

    static func blankStyleJSON(dark: Bool) -> String {
        """
        {"version": 8, "name": "Loop paper", "sources": {}, "layers": [
          {"id": "land", "type": "background", "paint": {"background-color": "\(Palette.mapLand.hex(dark: dark))"}}
        ]}
        """
    }

    /// Standard config: flat, few labels, no 3D, our land/water/lawn/road colors.
    static func standardConfig(dark: Bool) -> [String: Any] {
        func c(_ t: Palette.Token) -> String { t.hex(dark: dark) }
        return [
            "theme": "default",
            // "day" keeps the colors flat in both themes; the night preset relights the map.
            "lightPreset": "day",
            "show3dObjects": false,
            "showPointOfInterestLabels": false,
            "showTransitLabels": false,
            "showLandmarkIcons": false,
            "showLandmarkIconLabels": false,
            "showAdminBoundaries": false,
            "showPedestrianRoads": true,
            "showPlaceLabels": true,
            "colorLand": c(Palette.mapLand),
            "colorWater": c(Palette.mapWater),
            "colorGreenspace": c(Palette.mapLawn),
            "colorRoads": c(Palette.mapRoad),
            "colorTrunks": c(Palette.mapAvenue),
            "colorMotorways": c(Palette.mapMajor),
            "colorBuildings": c(Palette.surfaceSunken),
            "colorCommercial": c(Palette.mapLand),
            "colorEducation": c(Palette.mapLand),
            "colorMedical": c(Palette.mapLand),
            "colorIndustrial": c(Palette.mapLand),
            "colorPlaceLabels": c(Palette.mapLabelLand),
            "colorRoadLabels": c(Palette.mapLabelLand),
        ]
    }

    /// Street names only when zoomed in.
    static let roadLabelMinZoom: Double = 15.5
    /// Mile marks and start/turn labels from mid zoom.
    static let markerMinZoom: Double = 12.8
}
