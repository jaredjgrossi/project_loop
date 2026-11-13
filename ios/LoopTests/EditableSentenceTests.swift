import XCTest
@testable import Loop

/// The edit-mode sentence: one underline per understood phrase, and the same pieces for VoiceOver.
final class EditableSentenceTests: XCTestCase {
    private let sentence = "3 miles from the Kips Bay Library at 7 am."
    private var understood: [ReadOut.Understood] {
        [
            .init(start: 8, length: 25, field: "start", title: "Start", value: "the Kips Bay Library"),
            .init(start: 0, length: 7, field: "distance", title: "Distance", value: "3 mi"),
            .init(start: 34, length: 7, field: "time", title: "Time", value: "7 am"),
        ]
    }

    func testPiecesAreThePhrasesWholeAndNothingIsLost() {
        let pieces = EditableSentence.pieces(sentence, understood: understood)
        XCTAssertEqual(pieces.map(\.text).joined(), sentence)
        XCTAssertEqual(pieces.filter { $0.field != nil }.map(\.text),
                       ["3 miles", "from the Kips Bay Library", "at 7 am"], "a phrase is one piece, spaces included")
        XCTAssertEqual(pieces.compactMap(\.field), ["distance", "start", "time"], "in reading order")
    }

    func testEachPhraseIsOneUnderlinedRun() {
        let text = EditableSentence.attributed(EditableSentence.pieces(sentence, understood: understood))
        let links = text.runs.filter { $0.link != nil }
        XCTAssertEqual(links.count, 3, "three phrases, three runs: not one per word")
        XCTAssertEqual(links.map { String(text[$0.range].characters) }, ["3 miles", "from the Kips Bay Library", "at 7 am"])
        XCTAssertEqual(String(text.characters), sentence)
    }

    func testVoiceOverGetsThePhrasesAndSkipsBareSpacesAndStops() {
        let spoken = EditableSentence.spoken(EditableSentence.pieces(sentence, understood: understood))
        XCTAssertEqual(spoken.map(\.text), ["3 miles", "from the Kips Bay Library", "at 7 am"])
        let mixed = EditableSentence.spoken(EditableSentence.pieces("An easy 3 miles, please.", understood: [
            .init(start: 8, length: 7, field: "distance", title: "Distance", value: "3 mi"),
        ]))
        XCTAssertEqual(mixed.map(\.text), ["An easy", "3 miles", ", please."])
        XCTAssertEqual(mixed.map(\.field), [nil, "distance", nil])
    }

    func testAPhraseThatOverlapsOrRunsPastTheEndStaysPlain() {
        let pieces = EditableSentence.pieces("3 miles", understood: [
            .init(start: 0, length: 7, field: "distance", title: "Distance", value: "3 mi"),
            .init(start: 2, length: 5, field: "time", title: "Time", value: ""),
            .init(start: 5, length: 40, field: "start", title: "Start", value: ""),
        ])
        XCTAssertEqual(pieces, [EditableSentence.Piece(id: 0, text: "3 miles", field: "distance")])
    }
}
