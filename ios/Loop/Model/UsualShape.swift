import Foundation

/// The route type: in "You" -> Your defaults (sent as `profile.usual_shape`) and in the row under the
/// request field while typing (sent as the request's `shape`, which beats the words; decision 043).
enum UsualShape: String, CaseIterable, Identifiable, Codable {
    case any
    case loop
    case outAndBack = "out_and_back"
    case oneWay = "one_way"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .any: return "Any"
        case .loop: return "Loop"
        case .outAndBack: return "Out and back"
        case .oneWay: return "One way"
        }
    }

    /// The setting from before the profile moved into the run store (read once, to carry it over).
    static var legacy: UsualShape? {
        UserDefaults.standard.string(forKey: "usualShape").flatMap(UsualShape.init(rawValue:))
    }
}
