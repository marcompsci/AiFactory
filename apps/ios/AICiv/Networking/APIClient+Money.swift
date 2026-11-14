import Foundation

/// V6.113–V6.127: money you type in — income, paydays, the planner, savings, the budget, subscriptions, credit and the
/// on-time record. Nothing here moves money.

struct IncomeSummary: Decodable, Hashable {
    struct Entry: Decodable, Hashable, Identifiable { let id: String; let amount: Double; let source: String; let day: String; let hours: Double?; let note: String }
    struct Source: Decodable, Hashable, Identifiable { let source: String; let total: Double; let hourly: Double?; var id: String { source } }
    struct Week: Decodable, Hashable, Identifiable { let weekStart: String; let total: Double; var id: String { weekStart } }
    let entries: [Entry]
    let weekTotal: Double
    let monthTotal: Double
    let weekHourly: Double?
    let monthHourly: Double?
    let bySource: [Source]
    let weeks: [Week]
}

struct PaySchedule: Decodable, Hashable, Identifiable {
    let id: String
    let name: String
    let cadence: String
    let anchorDay: String
    let amount: Double?
    let next: [String]
}

struct PayPlanner: Decodable, Hashable {
    struct DueBill: Decodable, Hashable, Identifiable {
        let billId: String; let name: String; let due: String; let amount: Double?; let autopay: Bool; let overdue: Bool
        var id: String { billId + due }
    }
    struct Period: Decodable, Hashable, Identifiable {
        let from: String; let to: String; let payday: String; let pay: Double?; let bills: [DueBill]; let needed: Double; let varies: Int; let left: Double?
        var id: String { from }
    }
    let periods: [Period]
    let hasSchedule: Bool
}

struct SavingsGoal: Decodable, Hashable, Identifiable {
    struct Deposit: Decodable, Hashable, Identifiable { let id: String; let amount: Double; let day: String }
    let id: String
    let name: String
    let target: Double
    let saved: Double
    let left: Double
    let progress: Double
    let deadline: String?
    let monthlyPlan: Double?
    let perWeekNeeded: Double?
    let pastDeadline: Bool
    let done: Bool
    let recent: [Deposit]
}

struct MonthBudget: Decodable, Hashable {
    let month: String
    let incomeLogged: Double
    let incomeExpected: Double
    let income: Double
    let bills: Double
    let billsVary: Int
    let savingsPlan: Double
    let left: Double
    let daysLeft: Int
}

struct Subscriptions: Decodable, Hashable {
    struct Sub: Decodable, Hashable, Identifiable {
        let billId: String; let name: String; let amount: Double?; let cadence: String; let yearly: Double
        let reviewedAt: String?; let reviewDue: Bool; let linkUrl: String?
        var id: String { billId }
    }
    let subscriptions: [Sub]
    let yearlyTotal: Double
}

struct OnTimeRecord: Decodable, Hashable {
    struct Month: Decodable, Hashable, Identifiable { let month: String; let onTime: Int; let late: Int; let missed: Int; let upcoming: Int; var id: String { month } }
    let months: [Month]
    let onTime: Int
    let late: Int
    let missed: Int
    let onTimeRate: Double?
}

struct CreditCardInfo: Decodable, Hashable, Identifiable {
    let id: String
    let name: String
    let limit: Double
    let balance: Double
    let utilization: Double
    let statementDay: Int?
    let band: String
    var nextStatement: String? = nil
}

struct CreditHealth: Decodable, Hashable {
    let cards: [CreditCardInfo]
    let totalLimit: Double
    let totalBalance: Double
    let utilization: Double?
    let record: OnTimeRecord
    let note: String
}

struct MoneyOverview: Decodable, Hashable {
    struct Soon: Decodable, Hashable, Identifiable { let id: String; let name: String; let due: String; let amount: Double?; let overdue: Bool; let autopay: Bool }
    struct Goal: Decodable, Hashable, Identifiable { let name: String; let progress: Double; let saved: Double; let target: Double; var id: String { name } }
    let billsDueSoon: [Soon]
    let billsDueSoonTotal: Double
    let incomeThisWeek: Double
    let incomeThisMonth: Double
    let nextPayday: String?
    let savings: [Goal]
}

struct BillHint: Decodable, Hashable { let name: String; let amount: Double?; let dueDay: Int?; let cadence: String }

private struct SchedulesBox: Decodable { let schedules: [PaySchedule] }
private struct GoalsBox: Decodable { let goals: [SavingsGoal] }

extension APIClient {
    private var tzs: String { TimeZone.current.identifier }
    private var tzq: String { "tz=\(tzs.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "-_."))) ?? "UTC")" }
    private func body(_ f: [String: Any?]) throws -> Data { try JSONSerialization.data(withJSONObject: f.mapValues { $0 ?? NSNull() }) }

    func moneyOverview() async throws -> MoneyOverview { try await send(request("/api/money/overview?\(tzq)"), as: MoneyOverview.self) }
    func income() async throws -> IncomeSummary { try await send(request("/api/money/income?\(tzq)"), as: IncomeSummary.self) }
    func logIncome(amount: Double, source: String, day: String? = nil, hours: Double? = nil) async throws {
        _ = try await send(request("/api/money/income", method: "POST",
                                   body: body(["amount": amount, "source": source, "day": day, "hours": hours, "tz": tzs])), as: JSONValue.self)
    }
    func removeIncome(_ id: String) async throws { _ = try await json("/api/money/income/\(id)", method: "DELETE") }

    func paySchedules() async throws -> [PaySchedule] { try await send(request("/api/money/pay?\(tzq)"), as: SchedulesBox.self).schedules }
    func addPaySchedule(name: String, cadence: String, anchorDay: String, amount: Double?) async throws {
        _ = try await send(request("/api/money/pay", method: "POST",
                                   body: body(["name": name, "cadence": cadence, "anchor_day": anchorDay, "amount": amount])), as: JSONValue.self)
    }
    func removePaySchedule(_ id: String) async throws { _ = try await json("/api/money/pay/\(id)", method: "DELETE") }
    func planner() async throws -> PayPlanner { try await send(request("/api/money/planner?\(tzq)"), as: PayPlanner.self) }

    func savingsGoals() async throws -> [SavingsGoal] { try await send(request("/api/money/savings?\(tzq)"), as: GoalsBox.self).goals }
    func addSavingsGoal(name: String, target: Double, deadline: String?, monthlyPlan: Double?) async throws {
        _ = try await send(request("/api/money/savings", method: "POST",
                                   body: body(["name": name, "target": target, "deadline": deadline, "monthly_plan": monthlyPlan, "tz": tzs])),
                           as: JSONValue.self)
    }
    func deposit(_ goal: String, amount: Double) async throws -> [SavingsGoal] {
        try await send(request("/api/money/savings/\(goal)/deposits", method: "POST", body: body(["amount": amount, "tz": tzs])), as: GoalsBox.self).goals
    }
    func removeSavingsGoal(_ id: String) async throws { _ = try await json("/api/money/savings/\(id)", method: "DELETE") }
    func budget() async throws -> MonthBudget { try await send(request("/api/money/budget?\(tzq)"), as: MonthBudget.self) }

    func subscriptions() async throws -> Subscriptions { try await send(request("/api/money/subscriptions?\(tzq)"), as: Subscriptions.self) }
    func setSubscription(_ bill: String, on: Bool? = nil, reviewed: Bool = false) async throws -> Subscriptions {
        try await send(request("/api/money/bills/\(bill)/subscription?\(tzq)", method: "POST", body: body(["subscription": on, "reviewed": reviewed])),
                       as: Subscriptions.self)
    }
    func findSavings(_ bill: String) async throws -> MyTask {
        try await send(request("/api/money/bills/\(bill)/find-savings?\(tzq)", method: "POST"), as: MyTask.self)
    }

    func credit() async throws -> CreditHealth { try await send(request("/api/money/credit?\(tzq)"), as: CreditHealth.self) }
    func saveCard(_ id: String?, name: String?, limit: Double?, balance: Double?, statementDay: Int?) async throws {
        var f: [String: Any?] = [:]
        if let name { f["name"] = name }
        if let limit { f["limit"] = limit }
        if let balance { f["balance"] = balance }
        f["statement_day"] = statementDay
        if let id {
            _ = try await send(request("/api/money/credit/cards/\(id)", method: "PATCH", body: body(f)), as: JSONValue.self)
        } else {
            _ = try await send(request("/api/money/credit/cards", method: "POST", body: body(f)), as: JSONValue.self)
        }
    }
    func removeCard(_ id: String) async throws { _ = try await json("/api/money/credit/cards/\(id)", method: "DELETE") }
    func onTime() async throws -> OnTimeRecord { try await send(request("/api/money/on-time?\(tzq)"), as: OnTimeRecord.self) }

    /// Mark a bill paid on a given day (default today). You paid it elsewhere; this records it.
    func markBillPaid(_ id: String, paidOn: Date?) async throws -> Bill {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.dateFormat = "yyyy-MM-dd"
        return try await send(request("/api/bills/\(id)/paid", method: "POST",
                                      body: body(["tz": tzs, "paid_on": paidOn.map { f.string(from: $0) }])), as: Bill.self)
    }
}
