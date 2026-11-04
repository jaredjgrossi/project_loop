import XCTest
@testable import Loop

/// Every text/background pair the screen uses meets 4.5:1 in Paper and Night (WCAG AA, normal
/// text), and the route kinds and markers meet 3:1 against the land they sit on (non-text).
final class ContrastTests: XCTestCase {
    typealias T = Palette.Token

    private let textPairs: [(String, T, T)] = [
        ("ink on sheet", Palette.ink, Palette.surfaceSheet),
        ("ink-soft on sheet", Palette.inkSoft, Palette.surfaceSheet),
        ("ink-muted on sheet", Palette.inkMuted, Palette.surfaceSheet),
        ("unit on sheet", Palette.unitInk, Palette.surfaceSheet),
        ("ink on land (header)", Palette.ink, Palette.mapLand),
        ("ink-muted on land (provenance)", Palette.inkMuted, Palette.mapLand),
        ("ink-muted on sunken", Palette.inkMuted, Palette.surfaceSunken),
        ("on-action on action (button)", Palette.onAction, Palette.action),
        ("sheet on ink (selected marker)", Palette.surfaceSheet, Palette.ink),
        ("map label on land", Palette.mapLabelLand, Palette.mapLand),
        ("map label on water", Palette.mapLabelWater, Palette.mapWater),
    ]

    private let graphicPairs: [(String, T, T)] = [
        ("waterfront on land", Palette.routeWater, Palette.mapLand),
        ("waterfront on water", Palette.routeWater, Palette.mapWater),
        ("path on land", Palette.routePath, Palette.mapLand),
        ("street on land", Palette.routeStreet, Palette.mapLand),
        ("start dot on land", Palette.accentStart, Palette.mapLand),
        ("turnaround ring on land", Palette.ink, Palette.mapLand),
        ("street bar on sheet (strip)", Palette.routeStreet, Palette.surfaceSheet),
    ]

    func testTextContrastBothThemes() {
        for dark in [false, true] {
            for (name, fg, bg) in textPairs {
                let r = Contrast.ratio(dark ? fg.night : fg.paper, dark ? bg.night : bg.paper)
                XCTAssertGreaterThanOrEqual(r, 4.5, "\(name) \(dark ? "Night" : "Paper"): \(String(format: "%.2f", r))")
            }
        }
    }

    func testGraphicContrastBothThemes() {
        for dark in [false, true] {
            for (name, fg, bg) in graphicPairs {
                let r = Contrast.ratio(dark ? fg.night : fg.paper, dark ? bg.night : bg.paper)
                XCTAssertGreaterThanOrEqual(r, 3, "\(name) \(dark ? "Night" : "Paper"): \(String(format: "%.2f", r))")
            }
        }
    }

    func testRatioFormula() {
        XCTAssertEqual(Contrast.ratio(0x000000, 0xFFFFFF), 21, accuracy: 0.01)
        XCTAssertEqual(Contrast.ratio(0x777777, 0x777777), 1, accuracy: 0.001)
    }
}
