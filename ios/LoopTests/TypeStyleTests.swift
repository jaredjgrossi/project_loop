import XCTest
@testable import Loop

/// The twelve type styles: the brief's ("Type styles", ios-build-brief-v1) less data and
/// data-strong (no JetBrains Mono, calm pass), plus field and numeral-s (UI review, 2026-11-09). Views can only use these: TypeStyle's initializer is
/// private to Typography.swift.
final class TypeStyleTests: XCTestCase {
    func testStylesMatchTheBrief() {
        typealias Spec = (TypeStyle, FontFamily, CGFloat, CGFloat, CGFloat)
        let specs: [(String, Spec)] = [
            ("numeral-xl", (.numeralXL, .fraunces, 56, 56, 380)),
            ("numeral-l", (.numeralL, .fraunces, 24, 26, 400)),
            ("numeral-s", (.numeralS, .fraunces, 18, 22, 400)),
            ("field", (.field, .fraunces, 18, 24, 400)),
            ("request", (.request, .fraunces, 27, 31, 400)),
            ("wordmark", (.wordmark, .fraunces, 22, 26, 600)),
            ("body", (.body, .instrumentSans, 16, 22, 400)),
            ("body-strong", (.bodyStrong, .instrumentSans, 16, 22, 600)),
            ("label", (.label, .instrumentSans, 12.5, 16, 500)),
            ("eyebrow", (.eyebrow, .instrumentSans, 11.5, 14, 600)),
            ("stretch-name", (.stretchName, .instrumentSans, 12, 16, 600)),
            ("map-label", (.mapLabel, .instrumentSans, 11, 14, 500)),
        ]
        for (name, (style, family, size, line, weight)) in specs {
            XCTAssertEqual(style.family, family, name)
            XCTAssertEqual(style.size, size, name)
            XCTAssertEqual(style.lineHeight, line, name)
            XCTAssertEqual(style.weight, weight, name)
        }
        XCTAssertEqual(specs.count, 12)
        // The temperature reads quieter than the wordmark.
        XCTAssertLessThan(TypeStyle.numeralS.size, TypeStyle.wordmark.size)
        XCTAssertLessThan(TypeStyle.numeralS.weight, TypeStyle.wordmark.weight)
        XCTAssertEqual(TypeStyle.eyebrow.tracking, 0.12)
        XCTAssertTrue(TypeStyle.eyebrow.uppercase)
        XCTAssertEqual(TypeStyle.mapLabel.tracking, 0.22)
        XCTAssertTrue(TypeStyle.mapLabel.uppercase)
    }
}
