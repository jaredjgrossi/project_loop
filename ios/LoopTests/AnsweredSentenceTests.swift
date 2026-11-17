import XCTest
@testable import Loop

/// An answered question: the server's chips carry the new value over the old words' span, and the sentence follows,
/// as after the editor's Done (issue #48).
final class AnsweredSentenceTests: XCTestCase {
    private let sentence = "3 miles around Prospect Park at 7."
    /// The read-out after "Make it 4.3 mi?" is accepted, from the chips as the server sends them: the distance chip
    /// says 4.3 mi over the span of "3 miles".
    private var readOut: ReadOut {
        var r = ReadOut()
        r.understood = [
            .init(start: 8, length: 20, field: "via", title: "Through", value: "A lap of the Prospect Park drive loop, Brooklyn", chipId: "c_via_1"),
            .init(start: 0, length: 7, field: "distance", title: "Distance", value: "4.3 mi", chipId: "c_distance"),
            .init(start: 29, length: 4, field: "time", title: "Start time", value: "Today, 07:00", chipId: "c_time"),
        ]
        return r
    }

    private func words(_ text: String, _ u: ReadOut.Understood) -> String {
        (text as NSString).substring(with: NSRange(location: u.start, length: u.length))
    }

    func testTheAnsweredDistanceRewritesTheSentenceAndShiftsTheLaterPhrases() throws {
        let (text, r) = try XCTUnwrap(readOut.answered(field: "distance", sentence: sentence))
        XCTAssertEqual(text, "4.3 miles around Prospect Park at 7.")
        let distance = try XCTUnwrap(r.understood.first { $0.field == "distance" })
        XCTAssertEqual(words(text, distance), "4.3 miles", "the new words are the understood distance")
        XCTAssertEqual(distance.value, "4.3 mi")
        XCTAssertEqual(distance.chipId, "c_distance", "the chip is still the one a later edit would drop")
        XCTAssertEqual(words(text, try XCTUnwrap(r.understood.first { $0.field == "via" })), "around Prospect Park")
        XCTAssertEqual(words(text, try XCTUnwrap(r.understood.first { $0.field == "time" })), "at 7")
        XCTAssertEqual(EditableSentence.pieces(text, understood: r.understood).map(\.text).joined(), text,
                       "the header's pieces still cover the whole sentence")
    }

    func testAnAnswerThatKeepsTheWordsChangesNothing() {
        var same = readOut
        same.understood[1].value = "3 mi"
        XCTAssertNil(same.answered(field: "distance", sentence: sentence))
        XCTAssertNil(readOut.answered(field: "shape", sentence: sentence), "a field that isn't in the sentence")
    }

    func testThePhraseForAValue() {
        XCTAssertEqual(ReadOut.phrase(field: "distance", value: "4.3 mi"), "4.3 miles")
        XCTAssertEqual(ReadOut.phrase(field: "distance", value: "1 mi"), "1 mile")
        XCTAssertEqual(ReadOut.phrase(field: "distance", value: "4 mi"), "4 miles")
        XCTAssertEqual(ReadOut.phrase(field: "via", value: "Union Square"), "Union Square")
    }
}
