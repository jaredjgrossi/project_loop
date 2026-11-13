import Foundation

/// `GET /v1/weather/nyc` (decision 051): one city-level reading from the NWS station nearest Central
/// Park. There is no query: the phone's location never leaves the phone.
extension LoopAPI {
    struct WeatherBody: Decodable, Equatable {
        let v: Int
        let tempF: Double
        let condition: String
        let description: String?
        let observedAt: String
        let source: String?
    }

    /// The current reading. Any failure throws, and the store keeps its last reading (hidden once
    /// it is 30 minutes old).
    func weather() async throws -> WeatherStore.Reading {
        var req = URLRequest(url: base.appending(path: "v1/weather/nyc"))
        req.timeoutInterval = 10
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if !Self.installId.isEmpty { req.setValue(Self.installId, forHTTPHeaderField: "X-Loop-Install") }
        let data: Data, response: URLResponse
        do { (data, response) = try await URLSession.shared.data(for: req) } catch { throw Failure.unreachable }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 { throw Failure.unauthorized }
        guard status == 200 else { throw Failure.unreachable }
        guard let r = Self.reading(from: data) else { throw Failure.unreachable }
        return r
    }

    /// A reading from the response body, or nil when it is not a v1 body, has no usable time, or
    /// claims to be measured in the future (it would never go stale).
    static func reading(from data: Data, now: Date = Date()) -> WeatherStore.Reading? {
        guard let b = try? decoder.decode(WeatherBody.self, from: data), b.v == 1,
              b.tempF.isFinite, abs(b.tempF) < 150,
              let at = ISO8601DateFormatter().date(from: b.observedAt),
              at <= now.addingTimeInterval(120) else { return nil }
        return .init(symbol: weatherSymbol(b.condition, at: at), temperature: "\(Int(b.tempF.rounded()))°",
                     at: at, source: b.source ?? "")
    }

    /// SF Symbol for the server's condition word. Clear and partly cloudy get a night glyph outside
    /// 6 am to 6 pm New York time.
    static func weatherSymbol(_ condition: String, at: Date) -> String {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "America/New_York") ?? .current
        let hour = cal.component(.hour, from: at)
        let day = (6..<18).contains(hour)
        switch condition {
        case "clear": return day ? "sun.max" : "moon.stars"
        case "partly_cloudy": return day ? "cloud.sun" : "cloud.moon"
        case "cloudy": return "cloud"
        case "fog": return "cloud.fog"
        case "rain": return "cloud.rain"
        case "snow": return "cloud.snow"
        case "thunderstorm": return "cloud.bolt.rain"
        default: return "thermometer.medium"
        }
    }
}
