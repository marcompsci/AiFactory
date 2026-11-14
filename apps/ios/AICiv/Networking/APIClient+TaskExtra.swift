import Foundation

/// V6.98–V6.112: brain dumps and imports, bills you track, the month calendar, "I have N minutes", the end of the day,
/// weekly goals, waiting for people, the archive, export and list styles.

struct DumpPreview: Decodable, Hashable, Identifiable {
    let title: String
    let dueLabel: String?
    let listName: String?
    let estimateMinutes: Int?
    let repeatLabel: String?
    let links: [String]?
    let source: String
    var id: String { source + title }
}

/// A preview entry with its position, so two identical lines are still two rows.
struct NumberedPreview: Identifiable, Hashable { let n: Int; let p: DumpPreview; var id: Int { n } }

struct DumpResult: Decodable {
    struct Problem: Decodable, Hashable { let line: String; let error: String }
    let added: [MyTask]
    let problems: [Problem]
}

struct Bill: Decodable, Hashable, Identifiable {
    struct Payment: Decodable, Hashable { let period: String; let paidAt: String; let amountCents: Int? }
    let id: String
    let name: String
    let amountCents: Int?
    let amount: Double?
    let currency: String
    let cadence: String
    let dueDay: Int
    let dueMonth: Int?
    let autopay: Bool
    let linkUrl: String?
    let notes: String
    let remindDays: Int
    let active: Bool
    let nextDue: String
    let daysUntil: Int
    let overdue: Bool
    let period: String
    let paidThisPeriod: Bool
    var thisPeriod: String? = nil
    var subscription: Bool? = nil
    let payments: [Payment]

    var due: Date? {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.dateFormat = "yyyy-MM-dd"
        return f.date(from: nextDue)
    }
    var amountText: String { amount.map { $0.formatted(.currency(code: currency)) } ?? "Varies" }
}

struct BillSummary: Decodable, Hashable {
    struct Soon: Decodable, Hashable, Identifiable { let id: String; let name: String; let due: String; let amount: Double?; let autopay: Bool }
    struct Late: Decodable, Hashable, Identifiable { let id: String; let name: String; let due: String }
    let month: String
    let total: Double
    let paid: Double
    let unpaidCount: Int
    let variesCount: Int
    let overdue: [Late]
    let next30Days: [Soon]
    let next30Total: Double

    enum CodingKeys: String, CodingKey {
        case month, total, paid, unpaidCount, variesCount, overdue, next30Days = "next30Days", next30Total = "next30Total"
    }
}

struct MonthView: Decodable, Hashable {
    struct DayTask: Decodable, Hashable, Identifiable { let id: String; let title: String; let stage: String; let listName: String? }
    struct DayBill: Decodable, Hashable, Identifiable { let id: String; let name: String; let amount: Double?; let autopay: Bool; let paid: Bool }
    struct Day: Decodable, Hashable { let tasks: [DayTask]; let bills: [DayBill] }
    let year: Int
    let month: Int
    let days: [String: Day]
}

struct FitResult: Decodable, Hashable {
    struct Pick: Decodable, Hashable, Identifiable {
        let taskId: String; let title: String; let minutes: Int; let estimated: Bool; let overdue: Bool; let listName: String?
        var id: String { taskId }
    }
    let minutes: Int
    let picks: [Pick]
    let leftOver: Int
}

struct DayShutdown: Decodable, Hashable {
    struct Item: Decodable, Hashable, Identifiable { let id: String; let title: String; let dueAt: String?; let overdue: Bool?; var repeats: Bool? = nil }
    let day: String
    let done: [Item]
    let stillDue: [Item]
    let tomorrow: [Item]
    let note: String
    let yesterdaysNote: String
}

struct WeekGoals: Decodable, Hashable {
    struct Goal: Decodable, Hashable, Identifiable {
        struct Linked: Decodable, Hashable, Identifiable { let id: String; let title: String; let status: String }
        let id: String; let text: String; let done: Bool; let tasks: [Linked]; let progress: Double; let tasksDone: Int
    }
    let weekStart: String
    let goals: [Goal]
}

struct ArchivedTask: Decodable, Hashable, Identifiable { let id: String; let title: String; let status: String; let closedAt: String? }

struct ListStyle: Decodable, Hashable { let color: String; let icon: String }

private struct BillsBox: Decodable { let bills: [Bill] }
private struct PreviewBox: Decodable { let preview: [DumpPreview] }
private struct ArchiveBox: Decodable { let tasks: [ArchivedTask] }
/// List styles come as an array: dictionary keys would be renamed by the snake_case decoder ("side_hustle").
private struct StylesBox: Decodable {
    struct Item: Decodable { let name: String; let color: String; let icon: String }
    let items: [Item]
    let icons: [String]?
    var styles: [String: ListStyle] { Dictionary(items.map { ($0.name, ListStyle(color: $0.color, icon: $0.icon)) }, uniquingKeysWith: { a, _ in a }) }
}

extension APIClient {
    private func enc(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "-_."))) ?? ""
    }
    private func data(_ fields: [String: Any?]) throws -> Data {
        try JSONSerialization.data(withJSONObject: fields.mapValues { $0 ?? NSNull() })
    }
    private var tzq: String { "tz=\(enc(TimeZone.current.identifier))" }

    // brain dump / import
    func dumpPreview(_ text: String, format: String = "lines") async throws -> [DumpPreview] {
        try await send(request("/api/my-tasks/dump", method: "POST",
                               body: data(["text": text, "format": format, "tz": TimeZone.current.identifier, "dry_run": true])),
                       as: PreviewBox.self).preview
    }
    func dumpAdd(_ text: String, format: String = "lines") async throws -> DumpResult {
        try await send(request("/api/my-tasks/dump", method: "POST",
                               body: data(["text": text, "format": format, "tz": TimeZone.current.identifier, "dry_run": false])),
                       as: DumpResult.self)
    }
    func promoteItem(_ id: String, item: String) async throws -> MyTask {
        try await send(request("/api/my-tasks/\(id)/items/\(item)/promote", method: "POST"), as: MyTask.self)
    }

    // bills
    func bills() async throws -> [Bill] { try await send(request("/api/bills?\(tzq)"), as: BillsBox.self).bills }
    func billSummary() async throws -> BillSummary { try await send(request("/api/bills/summary?\(tzq)"), as: BillSummary.self) }
    func saveBill(_ id: String?, fields: [String: Any?]) async throws -> Bill {
        var f = fields
        f["tz"] = TimeZone.current.identifier
        if let id { return try await send(request("/api/bills/\(id)", method: "PATCH", body: data(f)), as: Bill.self) }
        return try await send(request("/api/bills", method: "POST", body: data(f)), as: Bill.self)
    }
    func deleteBill(_ id: String) async throws { _ = try await json("/api/bills/\(id)", method: "DELETE") }
    func markBillPaid(_ id: String) async throws -> Bill {
        try await send(request("/api/bills/\(id)/paid", method: "POST", body: data(["tz": TimeZone.current.identifier])), as: Bill.self)
    }
    func unmarkBillPaid(_ id: String, period: String) async throws -> Bill {
        try await send(request("/api/bills/\(id)/paid/\(period)?\(tzq)", method: "DELETE"), as: Bill.self)
    }

    // calendar, fit, end of day
    func month(year: Int, month: Int) async throws -> MonthView {
        try await send(request("/api/my-tasks/month?year=\(year)&month=\(month)&\(tzq)"), as: MonthView.self)
    }
    func planDay(start: String, end: String, busy: [(Date, Date)]) async throws -> DayPlan {
        let f = ISO8601DateFormatter()
        let b = busy.prefix(60).map { "&busy=\(enc(f.string(from: $0.0) + "," + f.string(from: $0.1)))" }.joined()
        return try await send(request("/api/my-tasks/plan?\(tzq)&start=\(enc(start))&end=\(enc(end))\(b)"), as: DayPlan.self)
    }
    func fit(minutes: Int) async throws -> FitResult { try await send(request("/api/my-tasks/fit?minutes=\(minutes)&\(tzq)"), as: FitResult.self) }
    func shutdown() async throws -> DayShutdown { try await send(request("/api/my-tasks/shutdown?\(tzq)"), as: DayShutdown.self) }
    func closeDay(move: Bool, note: String) async throws {
        _ = try await json("/api/my-tasks/shutdown", method: "POST",
                           body: ["tz": .string(TimeZone.current.identifier), "move": .bool(move), "note": .string(note)])
    }

    // goals and waiting
    func goals() async throws -> WeekGoals { try await send(request("/api/goals?\(tzq)"), as: WeekGoals.self) }
    func addGoal(_ text: String) async throws -> WeekGoals {
        try await send(request("/api/goals", method: "POST", body: data(["text": text, "tz": TimeZone.current.identifier])), as: WeekGoals.self)
    }
    func setGoal(_ id: String, done: Bool) async throws -> WeekGoals {
        try await send(request("/api/goals/\(id)", method: "PATCH", body: data(["done": done, "tz": TimeZone.current.identifier])), as: WeekGoals.self)
    }
    func removeGoal(_ id: String) async throws -> WeekGoals {
        try await send(request("/api/goals/\(id)?\(tzq)", method: "DELETE"), as: WeekGoals.self)
    }
    func linkGoal(_ task: String, goal: String?) async throws -> MyTask {
        try await send(request("/api/my-tasks/\(task)/goal", method: "POST", body: data(["goal_id": goal, "tz": TimeZone.current.identifier])),
                       as: MyTask.self)
    }
    func setWaiting(_ task: String, person: String?, followUp: Date?) async throws -> MyTask {
        try await send(request("/api/my-tasks/\(task)/waiting", method: "POST",
                               body: data(["person": person, "follow_up_at": followUp.map { ISO8601DateFormatter().string(from: $0) }])),
                       as: MyTask.self)
    }

    // archive, export, list styles
    func archive(_ q: String) async throws -> [ArchivedTask] {
        try await send(request("/api/my-tasks/archive?q=\(enc(q))"), as: ArchiveBox.self).tasks
    }
    func exportTasks(format: String) async throws -> URL {
        let (bytes, resp) = try await URLSession.shared.data(for: request("/api/my-tasks/export?format=\(format)"))
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw APIError(status: (resp as? HTTPURLResponse)?.statusCode ?? 0, detail: "Export failed") }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("my-tasks.\(format)")
        try bytes.write(to: url, options: .atomic)
        return url
    }
    func listStyles() async throws -> (styles: [String: ListStyle], icons: [String]) {
        let b = try await send(request("/api/lists/styles"), as: StylesBox.self)
        return (b.styles, b.icons ?? [])
    }
    func setListStyle(_ name: String, color: String?, icon: String?) async throws -> [String: ListStyle] {
        try await send(request("/api/lists/\(enc(name))/style", method: "PUT", body: data(["color": color, "icon": icon])), as: StylesBox.self).styles
    }
}
