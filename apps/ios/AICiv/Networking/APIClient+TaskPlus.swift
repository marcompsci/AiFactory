import Foundation

/// V6.68–V6.87: checklists, snooze, templates, plan my day, focus, estimates, feedback, the results library,
/// the weekly review, bulk actions and insights.

struct TaskTemplate: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let title: String
    let kind: String
    let priority: String
    let listName: String?
    let estimateMinutes: Int?
    let budgetUsd: Double?
    let items: [String]
}

struct DayPlan: Decodable, Hashable {
    struct Block: Decodable, Hashable, Identifiable {
        let taskId: String
        let title: String
        let verb: String
        let minutes: Int
        let kind: String
        let priority: String
        let overdue: Bool
        let listName: String?
        let estimated: Bool
        let start: String
        let end: String
        var id: String { taskId + start }
        var startDate: Date? { ISODate.parse(start) }
        var endDate: Date? { ISODate.parse(end) }
    }
    struct Later: Decodable, Hashable, Identifiable {
        let taskId: String
        let title: String
        let minutes: Int
        var id: String { taskId }
    }
    let blocks: [Block]
    let later: [Later]
    let plannedMinutes: Int
    let freeMinutes: Int
}

struct TaskEstimate: Decodable, Hashable {
    struct Range: Decodable, Hashable { let typical: Double; let high: Double }
    let label: String
    let runs: Int
    let about: String
    let costUsd: Range?
    let minutes: Range?
    let budgetUsd: Double?
    let note: String
}

struct TaskResult: Decodable, Hashable, Identifiable {
    let artifactId: String
    let title: String
    let taskId: String?
    let taskTitle: String?
    let kind: String
    let createdAt: String
    let simulated: Bool
    let rating: Int?
    let excerpt: String
    let content: String
    var id: String { artifactId }
}

struct WeeklyReview: Decodable, Hashable {
    let weekOf: String
    let done: [MyTask]
    let slipped: [MyTask]
    let stale: [MyTask]
    let upcoming: [MyTask]
    let summary: String
}

struct TaskInsights: Decodable, Hashable {
    struct Day: Decodable, Hashable, Identifiable {
        let day: String
        let done: Int
        let added: Int
        let focusMinutes: Int
        var id: String { day }
        var date: Date? {
            let f = DateFormatter()
            f.calendar = Calendar(identifier: .gregorian)
            f.dateFormat = "yyyy-MM-dd"
            return f.date(from: day)
        }
    }
    struct Runs: Decodable, Hashable { let completed: Int; let failed: Int; let cancelled: Int; let simulated: Int }
    struct Ratings: Decodable, Hashable { let up: Int; let down: Int }
    let days: Int
    let series: [Day]
    let done: Int
    let added: Int
    let open: Int
    let onTimeRate: Double?
    let focusMinutes: Int
    let runs: Runs
    let ratings: Ratings
    let headline: String
}

struct AgentQuality: Decodable, Hashable, Identifiable {
    let agent: String
    let name: String
    let up: Int
    let down: Int
    let score: Double?
    let recentReasons: [String]
    var id: String { agent }
}

struct BulkOutcome: Decodable {
    struct Problem: Decodable { let taskId: String; let error: String? }
    let changed: [String]
    let errors: [Problem]
}

private struct Items: Decodable { let items: [TaskItem] }
private struct Templates: Decodable { let templates: [TaskTemplate] }
private struct Results: Decodable { let results: [TaskResult] }
private struct Agents: Decodable { let agents: [AgentQuality] }
private struct FocusLogged: Decodable { let minutes: Int; let taskTotalMinutes: Int }

extension APIClient {
    private func payload(_ fields: [String: Any?]) throws -> Data {
        try JSONSerialization.data(withJSONObject: fields.compactMapValues { $0 })
    }

    private func query(_ items: [String: String?]) -> String {
        var c = URLComponents()
        c.queryItems = items.compactMap { k, v in v.map { URLQueryItem(name: k, value: $0) } }
        return (c.percentEncodedQuery ?? "").replacingOccurrences(of: "+", with: "%2B")
    }

    // checklist
    func addItems(_ id: String, _ texts: [String]) async throws -> [TaskItem] {
        try await send(request("/api/my-tasks/\(id)/items", method: "POST", body: payload(["texts": texts])), as: Items.self).items
    }
    func setItem(_ id: String, item: String, done: Bool? = nil, text: String? = nil) async throws -> [TaskItem] {
        try await send(request("/api/my-tasks/\(id)/items/\(item)", method: "PATCH", body: payload(["done": done, "text": text])), as: Items.self).items
    }
    func removeItem(_ id: String, item: String) async throws -> [TaskItem] {
        try await send(request("/api/my-tasks/\(id)/items/\(item)", method: "DELETE"), as: Items.self).items
    }

    // snooze: later, tonight, tomorrow, next_week, wake, or until an exact time
    func snoozeTask(_ id: String, preset: String?, until: Date? = nil, tz: String) async throws -> MyTask {
        let at = until.map { ISO8601DateFormatter().string(from: $0) }
        return try await send(request("/api/my-tasks/\(id)/snooze", method: "POST", body: payload(["preset": preset, "until": at, "tz": tz])),
                              as: MyTask.self)
    }

    // templates
    func taskTemplates() async throws -> [TaskTemplate] { try await send(request("/api/my-tasks/templates"), as: Templates.self).templates }
    func saveTemplate(_ id: String, name: String) async throws -> TaskTemplate {
        try await send(request("/api/my-tasks/\(id)/template", method: "POST", body: payload(["name": name])), as: TaskTemplate.self)
    }
    func useTemplate(_ tmpl: String) async throws -> MyTask {
        try await send(request("/api/my-tasks/templates/\(tmpl)/use", method: "POST", body: payload([:])), as: MyTask.self)
    }
    func deleteTemplate(_ tmpl: String) async throws { _ = try await json("/api/my-tasks/templates/\(tmpl)", method: "DELETE") }

    // plan, review, bulk, results, insights
    func planDay(tz: String, start: String = "09:00", end: String = "18:00") async throws -> DayPlan {
        try await send(request("/api/my-tasks/plan?\(query(["tz": tz, "start": start, "end": end]))"), as: DayPlan.self)
    }
    func weeklyReview(tz: String) async throws -> WeeklyReview {
        try await send(request("/api/my-tasks/review?\(query(["tz": tz]))"), as: WeeklyReview.self)
    }
    func bulkTasks(_ ids: [String], action: String, tz: String) async throws -> BulkOutcome {
        try await send(request("/api/my-tasks/bulk", method: "POST", body: payload(["ids": ids, "action": action, "tz": tz])), as: BulkOutcome.self)
    }
    func taskResults(q: String?) async throws -> [TaskResult] {
        let t = q?.trimmingCharacters(in: .whitespaces)
        return try await send(request("/api/my-tasks/results?\(query(["q": (t?.isEmpty ?? true) ? nil : t]))"), as: Results.self).results
    }
    func taskInsights(tz: String, days: Int = 14) async throws -> TaskInsights {
        try await send(request("/api/insights/tasks?\(query(["tz": tz, "days": String(days)]))"), as: TaskInsights.self)
    }
    func agentQuality() async throws -> [AgentQuality] { try await send(request("/api/insights/agent-quality"), as: Agents.self).agents }

    // focus, estimate, feedback
    @discardableResult
    func logFocus(_ id: String, minutes: Int, startedAt: Date) async throws -> Int {
        try await send(request("/api/my-tasks/\(id)/focus", method: "POST",
                               body: payload(["minutes": minutes, "started_at": ISO8601DateFormatter().string(from: startedAt)])),
                       as: FocusLogged.self).taskTotalMinutes
    }
    func taskEstimate(_ id: String) async throws -> TaskEstimate { try await send(request("/api/my-tasks/\(id)/estimate"), as: TaskEstimate.self) }
    func rateResult(_ id: String, rating: Int, reason: String?) async throws {
        _ = try await send(request("/api/my-tasks/\(id)/feedback", method: "POST", body: payload(["rating": rating, "reason": reason])),
                           as: TaskFeedback.self)
    }
}
