import UIKit
import XCTest
@testable import Loop

/// The About section at the foot of "You" (decision 063): the version and build, and the install id a runner
/// copies to ask for their data to be deleted. The copied string is the store's id, nothing more.
@MainActor
final class AboutTests: XCTestCase {
    func testCopyingTheInstallIdPutsTheStoresIdOnThePasteboard() {
        let store = RunStore()
        let board = UIPasteboard(name: UIPasteboard.Name("loop-about-tests-\(UUID().uuidString)"), create: true)!
        defer { UIPasteboard.remove(withName: board.name) }
        AboutInfo.copyInstallId(of: store, to: board)
        XCTAssertEqual(board.string, store.installId)
        XCTAssertNotNil(UUID(uuidString: board.string ?? ""), "the id is the bare UUID, no label around it")
    }

    func testTheInstallIdSurvivesARelaunchSoTheCopiedOneStaysValid() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("about-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        let data = try LoopData(file: RouteFile.loadBundled())
        let first = RunStore.load(data: data, url: url)
        let again = RunStore.load(data: data, url: url)
        XCTAssertEqual(again.installId, first.installId)
    }

    func testVersionLineIsVersionThenBuildInParentheses() {
        XCTAssertEqual(AboutInfo.versionLine(version: "0.1.0", build: "1"), "0.1.0 (1)")
        XCTAssertEqual(AboutInfo.versionLine(version: nil, build: nil), "")
        XCTAssertEqual(AboutInfo.versionLine(version: "0.1.0", build: nil), "0.1.0")
    }
}
