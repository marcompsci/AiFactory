import Foundation

/// The owner's task list (V6.43–V6.49): /api/my-tasks.
struct MyTask: Decodable, Identifiable, Hashable {
    struct Run: Decodable, Hashable {
        let status: String
        var executionMode: String? = nil
        var spentUsdEstimated: Double? = nil
        var budgetUsd: Double? = nil
        var kind: String? = nil
        var planArtifactId: String? = nil
        var resultArtifactId: String? = nil
    }
    struct Doc: Decodable, Hashable {
        let id: String
        let title: String
        let content: String
    }
    let id: String
    let title: String
    let notes: String
    let kind: String
    let priority: String
    let status: String
    let dueAt: String?
    let repeats: String
    let budgetUsd: Double?
    let repositoryId: String?
    let missionId: String?
    let runs: Int
    let stage: String
    let overdue: Bool
    let mission: Run?
    let createdAt: String
    let doneAt: String?
    var plan: Doc? = nil
    var result: Doc? = nil
    // V6.68+: lists, estimates, snooze, waiting-on, the checklist, ratings and focus time
    var listName: String? = nil
    var estimateMinutes: Int? = nil
    var snoozedUntil: String? = nil
    var blockedBy: String? = nil
    var blockedByTitle: String? = nil
    var itemsTotal: Int? = nil
    var itemsDone: Int? = nil
    var items: [TaskItem]? = nil
    var feedback: TaskFeedback? = nil
    var focusMinutes: Int? = nil

    enum CodingKeys: String, CodingKey {
        case id, title, notes, kind, priority, status, dueAt, repeats = "repeat", budgetUsd, repositoryId, missionId, runs, stage, overdue,
             mission, createdAt, doneAt, plan, result, listName, estimateMinutes, snoozedUntil, blockedBy, blockedByTitle,
             itemsTotal, itemsDone, items, feedback, focusMinutes
    }

    var due: Date? { ISODate.parse(dueAt) }
    var isOpen: Bool { status == "OPEN" }
    var simulated: Bool { mission?.executionMode == "simulation" }
    var snoozed: Date? { ISODate.parse(snoozedUntil) }
}

struct TaskItem: Decodable, Identifiable, Hashable {
    let id: String
    let text: String
    let done: Bool
    var fromAgents: Bool = false
}

struct TaskFeedback: Decodable, Hashable {
    let rating: Int
    let reason: String?
    let agent: String?
}

/// What quick capture reads from a line of text (exactly what adding it would save).
struct TaskPreview: Decodable, Hashable {
    let title: String
    let dueAt: String?
    let dueLabel: String?
    let priority: String
    let budgetUsd: Double?
    let kind: String
    let repeats: String
    var listName: String? = nil
    var estimateMinutes: Int? = nil

    enum CodingKeys: String, CodingKey { case title, dueAt, dueLabel, priority, budgetUsd, kind, repeats = "repeat", listName, estimateMinutes }
}

private struct TaskList: Decodable { let tasks: [MyTask] }
private struct Completed: Decodable { let task: MyTask; let next: MyTask? }

extension APIClient {
    private func body(_ fields: [String: Any?]) throws -> Data {
        try JSONSerialization.data(withJSONObject: fields.compactMapValues { $0 })
    }

    func myTasks() async throws -> [MyTask] { try await send(request("/api/my-tasks"), as: TaskList.self).tasks }
    func myTask(_ id: String) async throws -> MyTask { try await send(request("/api/my-tasks/\(id)"), as: MyTask.self) }

    func previewTask(_ text: String, tz: String) async throws -> TaskPreview {
        var c = URLComponents()
        c.queryItems = [URLQueryItem(name: "text", value: text), URLQueryItem(name: "tz", value: tz)]
        // URLComponents leaves "+" alone, which a server reads as a space: encode it
        let q = (c.percentEncodedQuery ?? "").replacingOccurrences(of: "+", with: "%2B")
        return try await send(request("/api/my-tasks/parse?\(q)"), as: TaskPreview.self)
    }

    func addTask(text: String, tz: String) async throws -> MyTask {
        try await send(request("/api/my-tasks", method: "POST", body: body(["text": text, "tz": tz])), as: MyTask.self)
    }

    func editTask(_ id: String, _ fields: [String: Any?]) async throws -> MyTask {
        try await send(request("/api/my-tasks/\(id)", method: "PATCH", body: body(fields)), as: MyTask.self)
    }

    func doTask(_ id: String) async throws -> MyTask { try await send(request("/api/my-tasks/\(id)/do", method: "POST"), as: MyTask.self) }

    func redoTask(_ id: String, note: String) async throws -> MyTask {
        try await send(request("/api/my-tasks/\(id)/redo", method: "POST", body: body(["note": note])), as: MyTask.self)
    }

    /// Mark done; returns the next occurrence of a repeating task, if one was queued.
    @discardableResult
    func finishTask(_ id: String, tz: String) async throws -> MyTask? {
        try await send(request("/api/my-tasks/\(id)/done", method: "POST", body: body(["tz": tz])), as: Completed.self).next
    }

    func reopenTask(_ id: String) async throws -> MyTask { try await send(request("/api/my-tasks/\(id)/reopen", method: "POST"), as: MyTask.self) }
    func dropTask(_ id: String) async throws -> MyTask { try await send(request("/api/my-tasks/\(id)/drop", method: "POST"), as: MyTask.self) }
    func deleteTask(_ id: String) async throws { _ = try await json("/api/my-tasks/\(id)", method: "DELETE") }

    func todayTasks(tz: String) async throws -> JSONValue {
        let q = tz.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "/_-"))) ?? "UTC"
        return try await json("/api/my-tasks/today?tz=\(q)")
    }
}
