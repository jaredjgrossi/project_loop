import SwiftUI
import UIKit

/// Design-system color tokens, Paper (light) and Night (dark). Each follows the system setting.
/// Values are the brief's table. The four marked "mockup" come from the D artboards (Paper);
/// their Night values are first picks to tune on the device.
enum Palette {
    struct Token {
        let paper: UInt32
        let night: UInt32

        var uiColor: UIColor {
            UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: night) : UIColor(hex: paper) }
        }
        var color: Color { Color(uiColor: uiColor) }
        func hex(dark: Bool) -> String { String(format: "#%06X", dark ? night : paper) }
    }

    static let mapLand = Token(paper: 0xF4EDDD, night: 0x1C1915)
    static let surfaceSheet = Token(paper: 0xFBF6EA, night: 0x26221C)
    static let surfaceSunken = Token(paper: 0xEFE6D2, night: 0x2F2A23)
    static let lineHairline = Token(paper: 0xE3D8C0, night: 0x3A342B)
    static let lineControl = Token(paper: 0x8A7B66, night: 0x8F8470)
    static let ink = Token(paper: 0x2B2620, night: 0xF1E9DA)
    static let inkSoft = Token(paper: 0x3A322A, night: 0xDDD3C0)
    static let inkMuted = Token(paper: 0x6B5F52, night: 0xB3A793)
    /// Primary button. One token, so indigo vs ink is a one-line change.
    static let action = Token(paper: 0x2C3A8F, night: 0x9AA8F0)
    static let onAction = Token(paper: 0xFBF6EA, night: 0x14182E)
    static let routeWater = Token(paper: 0x2C3A8F, night: 0x9AA8F0)
    static let routePath = Token(paper: 0x5B6FBF, night: 0x7C8DE0)
    static let routeStreet = Token(paper: 0x8A7862, night: 0xB3A18B)
    static let routeCasing = Token(paper: 0xFBF6EA, night: 0x1C1915)
    static let accentStart = Token(paper: 0xD2492A, night: 0xF0764F)
    static let alert = Token(paper: 0xB23A1B, night: 0xFF8A66)
    static let focusRing = Token(paper: 0x2C3A8F, night: 0x9AA8F0)
    static let mapStreet = Token(paper: 0xE8DECA, night: 0x28231C)
    static let mapAvenue = Token(paper: 0xDFD3BA, night: 0x302A22)
    static let mapMajor = Token(paper: 0xDDD0B4, night: 0x383128)
    static let mapRoad = Token(paper: 0xE9E0CC, night: 0x26231D)
    static let mapLawn = Token(paper: 0xE4E8D0, night: 0x212A20)
    static let mapWater = Token(paper: 0xD9E1DE, night: 0x202B2E)
    static let mapShore = Token(paper: 0xC5D1CC, night: 0x33423F)
    static let mapLabelLand = Token(paper: 0x6E6252, night: 0xA89C86)
    static let mapLabelWater = Token(paper: 0x566660, night: 0x98ADA7)

    // From the mockup (not in the brief's table).
    /// Borders of the round preferences button and the look-around chip.
    static let controlBorder = Token(paper: 0xD5C9AF, night: 0x4A4237)
    /// Rule under the request text.
    static let requestRule = Token(paper: 0xCFC3A9, night: 0x4A4237)
    /// Sheet grabber.
    static let grabber = Token(paper: 0xD8CDB5, night: 0x4A4237)
    /// The "mi" after the distance.
    static let unitInk = Token(paper: 0x4A3F33, night: 0xCFC5B2)

    static func drawColor(_ kind: DrawKind) -> Token {
        switch kind {
        case .waterfront: return routeWater
        case .path: return routePath
        case .street: return routeStreet
        }
    }
}

extension UIColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255,
                  green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: alpha)
    }
}

/// WCAG 2.x contrast, for the contrast tests.
enum Contrast {
    static func luminance(_ hex: UInt32) -> Double {
        func channel(_ v: UInt32) -> Double {
            let c = Double(v) / 255
            return c <= 0.03928 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * channel((hex >> 16) & 0xFF) + 0.7152 * channel((hex >> 8) & 0xFF) + 0.0722 * channel(hex & 0xFF)
    }

    static func ratio(_ a: UInt32, _ b: UInt32) -> Double {
        let la = luminance(a), lb = luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    }
}
