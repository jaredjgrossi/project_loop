import SwiftUI
import UIKit

/// The two bundled variable fonts (SIL OFL 1.1; licence files ship in the app bundle). JetBrains
/// Mono was removed in the calm pass (UI review, 2026-11-09).
enum FontFamily {
    case fraunces, instrumentSans

    var postScriptName: String {
        switch self {
        case .fraunces: return "Fraunces-Regular"
        case .instrumentSans: return "InstrumentSans-Regular"
        }
    }
}

/// One named type style from the design system. Sizes are fixed for now; `scale` is the
/// single place Dynamic Type would plug in later.
struct TypeStyle {
    let family: FontFamily
    let size: CGFloat
    let lineHeight: CGFloat
    let weight: CGFloat
    var tracking: CGFloat = 0      // in em
    var uppercase = false
    var tabularNumerals = false

    /// Only the design system's twelve styles exist (below): the initializer is private to this
    /// file, so a view can't make an off-list size or family.
    fileprivate init(family: FontFamily, size: CGFloat, lineHeight: CGFloat, weight: CGFloat,
                     tracking: CGFloat = 0, uppercase: Bool = false, tabularNumerals: Bool = false) {
        self.family = family
        self.size = size
        self.lineHeight = lineHeight
        self.weight = weight
        self.tracking = tracking
        self.uppercase = uppercase
        self.tabularNumerals = tabularNumerals
    }

    static var scale: CGFloat = 1

    var pointSize: CGFloat { size * Self.scale }
    var trackingPoints: CGFloat { tracking * pointSize }

    @MainActor private static var cache: [String: UIFont] = [:]

    var uiFont: UIFont {
        let key = "\(family)-\(pointSize)-\(weight)-\(tabularNumerals)"
        if let hit = MainActor.assumeIsolated({ Self.cache[key] }) { return hit }
        let font = makeFont()
        MainActor.assumeIsolated { Self.cache[key] = font }
        return font
    }

    private func makeFont() -> UIFont {
        // Variation axes by 4-char tag: wght, opsz (Fraunces), SOFT and WONK (Fraunces, off).
        func tag(_ s: String) -> NSNumber {
            NSNumber(value: s.unicodeScalars.reduce(UInt32(0)) { ($0 << 8) | $1.value })
        }
        var axes: [NSNumber: NSNumber] = [tag("wght"): NSNumber(value: Double(weight))]
        if family == .fraunces {
            // Optical size follows the point size, as browsers do with font-optical-sizing: auto.
            axes[tag("opsz")] = NSNumber(value: Double(min(144, max(9, pointSize))))
            axes[tag("SOFT")] = 0
            axes[tag("WONK")] = 0
        }
        var attributes: [UIFontDescriptor.AttributeName: Any] = [
            .name: family.postScriptName,
            UIFontDescriptor.AttributeName(rawValue: kCTFontVariationAttribute as String): axes,
        ]
        if tabularNumerals {
            attributes[.featureSettings] = [[
                UIFontDescriptor.FeatureKey.type: kNumberSpacingType,
                UIFontDescriptor.FeatureKey.selector: kMonospacedNumbersSelector,
            ]]
        }
        return UIFont(descriptor: UIFontDescriptor(fontAttributes: attributes), size: pointSize)
    }

    var font: Font { Font(uiFont as CTFont) }

    /// Extra space between lines so the line height matches the spec.
    var lineSpacing: CGFloat { max(0, lineHeight * Self.scale - uiFont.lineHeight) }
}

/// The design system's twelve type styles: the brief's ("Type styles", ios-build-brief-v1) less
/// data and data-strong (no mono in the app), plus field and numeral-s (UI review, 2026-11-09).
/// Tracking on numeral-xl, wordmark and body-strong is the D mockup's.
extension TypeStyle {
    static let numeralXL = TypeStyle(family: .fraunces, size: 56, lineHeight: 56, weight: 380, tracking: -0.02, tabularNumerals: true)
    static let numeralL = TypeStyle(family: .fraunces, size: 24, lineHeight: 26, weight: 400, tabularNumerals: true)
    /// Small numerals (the landing's temperature): quieter than the wordmark.
    static let numeralS = TypeStyle(family: .fraunces, size: 18, lineHeight: 22, weight: 400, tabularNumerals: true)
    /// The landing field's example, placeholder and typed text.
    static let field = TypeStyle(family: .fraunces, size: 18, lineHeight: 24, weight: 400)
    static let request = TypeStyle(family: .fraunces, size: 27, lineHeight: 31, weight: 400)
    static let wordmark = TypeStyle(family: .fraunces, size: 22, lineHeight: 26, weight: 600, tracking: -0.01)
    static let body = TypeStyle(family: .instrumentSans, size: 16, lineHeight: 22, weight: 400)
    static let bodyStrong = TypeStyle(family: .instrumentSans, size: 16, lineHeight: 22, weight: 600, tracking: 0.01)
    static let label = TypeStyle(family: .instrumentSans, size: 12.5, lineHeight: 16, weight: 500)
    static let eyebrow = TypeStyle(family: .instrumentSans, size: 11.5, lineHeight: 14, weight: 600, tracking: 0.12, uppercase: true)
    static let stretchName = TypeStyle(family: .instrumentSans, size: 12, lineHeight: 16, weight: 600)
    static let mapLabel = TypeStyle(family: .instrumentSans, size: 11, lineHeight: 14, weight: 500, tracking: 0.22, uppercase: true)
}

extension View {
    func typeStyle(_ style: TypeStyle) -> some View {
        self.font(style.font)
            .tracking(style.trackingPoints)
            .lineSpacing(style.lineSpacing)
            .textCase(style.uppercase ? .uppercase : nil)
    }
}

/// Spacing, radius and size tokens.
enum Metrics {
    static let s4: CGFloat = 4, s8: CGFloat = 8, s12: CGFloat = 12, s16: CGFloat = 16
    static let s24: CGFloat = 24, s32: CGFloat = 32, s52: CGFloat = 52
    static let radiusBar: CGFloat = 3, radiusThumb: CGFloat = 8, radiusButton: CGFloat = 14, radiusSheet: CGFloat = 24
    static let sheetCollapsed: CGFloat = 216
    static let sheetOpen: CGFloat = 398
    static let selectedMileMarker: CGFloat = 30
    static let routeCasing: CGFloat = 10
    static let minTap: CGFloat = 44
}

/// Motion tokens (proposals from the brief, to tune on the device).
enum Motion {
    /// Text arrives: 200 ms, cubic-bezier(0.2, 0, 0, 1), 6 pt rise.
    static let textArrive = Animation.timingCurve(0.2, 0, 0, 1, duration: 0.2)
    static let textRise: CGFloat = 6
    static let sheetSettle = Animation.timingCurve(0.2, 0, 0, 1, duration: 0.32)
    /// Swapping content in place (the landing sheet's runs and typing list): 200 ms crossfade.
    static let crossfade = Animation.timingCurve(0.2, 0, 0, 1, duration: 0.2)
    static let mapPan: TimeInterval = 0.4
    /// Route draw speed, metres of route per second (constant, linear).
    static let drawMetresPerSecond: Double = 2_500
    static let morphDuration: TimeInterval = 0.6
    /// Candidate outlines: faint while building, gone 500 ms after the provisional flag.
    static let outlinePeakOpacity: Double = 0.3
    static let outlineFade: TimeInterval = 0.5
}
