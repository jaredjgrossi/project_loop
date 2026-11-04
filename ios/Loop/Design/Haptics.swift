import UIKit

/// The only three things that vibrate (brief: nothing else does).
@MainActor
enum Haptics {
    private static let light = UIImpactFeedbackGenerator(style: .light)
    private static let selection = UISelectionFeedbackGenerator()
    private static let notification = UINotificationFeedbackGenerator()

    static func prepareSettle() { light.prepare() }
    /// The route settles at the provisional flag.
    static func settle() { light.impactOccurred() }

    static func prepareScrub() { selection.prepare() }
    /// Each whole mile while scrubbing the profile strip.
    static func mileTick() { selection.selectionChanged(); selection.prepare() }

    /// "Send to watch" confirms.
    static func success() { notification.notificationOccurred(.success) }
}
