import Foundation

/// The server's `out_of_area` (decision 056): the runner named a start or end outside what Loop covers.
/// A question to answer, not a failure. The app owns the copy: it is built from `place` (the runner's own
/// word for it, imperfect, never corrected) and `covers` (the server's short name for the area), never from
/// the server's text.
struct OutOfArea: Equatable {
    var place: String?
    var covers: String?

    private static func clean(_ s: String?) -> String? {
        let t = s?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return t.isEmpty ? nil : t
    }

    /// "Loop doesn't know Tampa yet. It covers New York City for now." With no place: "Loop covers New
    /// York City for now."
    var message: String {
        let area = Self.clean(covers)
        switch (Self.clean(place), area) {
        case let (p?, a?): return "Loop doesn't know \(p) yet. It covers \(a) for now."
        case let (p?, nil): return "Loop doesn't know \(p) yet. It only covers one area for now."
        case let (nil, a?): return "Loop covers \(a) for now."
        case (nil, nil): return "Loop only covers one area for now."
        }
    }

    /// The one button: back to the sentence, with the field focused, to change the start.
    static let buttonTitle = "Change the start"
}

/// Copy for every `error` code, so "Can't reach Loop" stays for real network failures only. A code this
/// build doesn't know shows the server's own text when it sent some.
enum ErrorCopy {
    struct Notice: Equatable {
        let text: String
        let canRetry: Bool
    }

    static func notice(code: String, text: String) -> Notice {
        switch code {
        case "engine_unavailable":
            return Notice(text: "Loop's route engine isn't answering. Try again in a moment.", canRetry: true)
        case "bad_final":
            return Notice(text: "Loop's answer came back garbled. Try again.", canRetry: true)
        case "parse_failed":
            return Notice(text: "Loop couldn't read that. Try saying it another way.", canRetry: false)
        case "bad_request":
            return Notice(text: "Loop couldn't use that request. Try changing it.", canRetry: false)
        case "expired":
            return Notice(text: "That question timed out. Ask again.", canRetry: false)
        case "route_not_found":
            return Notice(text: "Loop doesn't have that route any more. Plan it again from the words.", canRetry: false)
        default:
            let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
            return Notice(text: t.isEmpty ? "Something went wrong with that request." : t, canRetry: true)
        }
    }
}
