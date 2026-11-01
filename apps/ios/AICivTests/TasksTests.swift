import XCTest
@testable import AICiv

/// The task list (V6.43–V6.51) decodes the server's JSON, including `repeat` (a Swift keyword) and a run in progress.
final class TasksTests: XCTestCase {
    func testDecodesATaskWithItsRunAndResult() throws {
        let json = """
        {"id":"7f0c","organization_id":"o","title":"Draft the Echo blurb","notes":"","kind":"write","priority":"urgent","status":"OPEN",
         "due_at":"2026-11-07T01:00:00+00:00","repeat":"weekly","budget_usd":1.0,"repository_id":null,"mission_id":"m1","runs":1,
         "created_by":"u","created_at":"2026-11-01T21:00:00+00:00","updated_at":"2026-11-01T21:00:00+00:00","done_at":null,
         "stage":"review","overdue":false,
         "mission":{"status":"COMPLETED","execution_mode":"simulation","spent_usd_estimated":0,"budget_usd":1.0,"kind":"personal_task",
                    "plan_artifact_id":"a1","result_artifact_id":"a2"},
         "result":{"id":"a2","title":"Result: Draft the Echo blurb","content":"# Draft","created_at":"2026-11-01T21:01:00+00:00"}}
        """
        let t = try APIClient.decoder.decode(MyTask.self, from: Data(json.utf8))
        XCTAssertEqual(t.repeats, "weekly")
        XCTAssertEqual(t.stage, "review")
        XCTAssertTrue(t.simulated)
        XCTAssertEqual(t.mission?.resultArtifactId, "a2")
        XCTAssertEqual(t.result?.content, "# Draft")
        XCTAssertNotNil(t.due)
    }

    func testDecodesTheCapturePreview() throws {
        let json = #"{"title":"Call mom","due_at":null,"due_label":null,"priority":"normal","budget_usd":null,"kind":"personal","repeat":"none"}"#
        let p = try APIClient.decoder.decode(TaskPreview.self, from: Data(json.utf8))
        XCTAssertEqual(p.title, "Call mom")
        XCTAssertEqual(p.repeats, "none")
    }

    func testDueLabelsReadNaturally() {
        let now = Date()
        XCTAssertTrue(TaskTime.label(now.addingTimeInterval(60), now: now).hasPrefix("today") || Calendar.current.component(.hour, from: now) == 23)
    }
}
