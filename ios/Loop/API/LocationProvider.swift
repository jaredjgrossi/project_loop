import CoreLocation
import Observation

/// The runner's location, when-in-use. Sent with each request (never logged) and used for the
/// pulsing dot. nil when off or denied: the server then starts from Home or asks where to start.
@Observable
@MainActor
final class LocationProvider: NSObject, CLLocationManagerDelegate {
    private(set) var here: CLLocation?
    @ObservationIgnored private let manager = CLLocationManager()

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
    }

    #if DEBUG
    /// Demo mode (decision 060): a fixed location at a public start. Core Location is never started, and a fix it
    /// delivers on its own (the manager starts updates on an authorized phone the moment it exists) is ignored.
    private var simulated = false
    func simulate(_ p: GeoPoint) {
        simulated = true
        manager.stopUpdatingLocation()
        here = CLLocation(latitude: p.lat, longitude: p.lon)
    }
    #endif

    func start() {
        #if DEBUG
        if simulated { return }
        #endif
        switch manager.authorizationStatus {
        case .notDetermined: manager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways: manager.startUpdatingLocation()
        default: here = nil
        }
    }

    var requestLocation: RunRequest.Location? {
        guard let h = here, h.horizontalAccuracy >= 0 else { return nil }
        return RunRequest.Location(lat: h.coordinate.latitude, lon: h.coordinate.longitude,
                                   accuracyM: (h.horizontalAccuracy * 10).rounded() / 10)
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        MainActor.assumeIsolated {
            #if DEBUG
            // Demo mode: an authorized phone would start real updates here and overwrite the stand-in.
            if simulated { return }
            #endif
            switch manager.authorizationStatus {
            case .authorizedWhenInUse, .authorizedAlways: manager.startUpdatingLocation()
            default: self.here = nil
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let last = locations.last else { return }
        MainActor.assumeIsolated {
            #if DEBUG
            if simulated { return }
            #endif
            self.here = last
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {}
}
