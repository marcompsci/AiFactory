import Foundation

/// V6.158–V6.187: money, round 3 — paying on time, credit, earning and keeping more, and the assistant pieces.
/// Everything is typed in; nothing moves money.

struct ParsedBill: Decodable, Hashable {
    let name: String; let amount: Double?; let dueDate: String?; let dueDay: Int?; let dueMonth: Int?; let cadence: String; let autopay: Bool; let note: String
}

struct DueDateMoves: Decodable, Hashable {
    struct Move: Decodable, Hashable, Identifiable { let billId: String; let name: String; let amount: Double?; let dueDay: Int; let payday: String; let suggestedDueDay: Int; let script: String; var id: String { billId } }
    let ready: Bool; var reason: String? = nil; let moves: [Move]; var note: String? = nil
}

struct BillHistory: Decodable, Hashable {
    struct Row: Decodable, Hashable, Identifiable { let period: String; let due: String; let paidOn: String; let onTime: Bool; let amount: Double?; let confirmation: String; let method: String; var id: String { period } }
    let billId: String; let name: String; let payments: [Row]; let average: Double?; let highest: Double?; let lowest: Double?
}

struct MoneyForecast: Decodable, Hashable {
    struct Event: Decodable, Hashable { let kind: String; let name: String; let amount: Double; let varies: Bool }
    struct Day: Decodable, Hashable, Identifiable { let day: String; let balance: Double; let events: [Event]; var id: String { day } }
    let ready: Bool
    var reason: String? = nil
    var start: Double? = nil
    var dailySpending: Double? = nil
    var days: [Day]? = nil
    var low: Day? = nil
    var belowZero: [String]? = nil
    var belowBuffer: [String]? = nil
    var buffer: Double? = nil
    let note: String
}

struct CreditWatch: Decodable, Hashable {
    struct Bureau: Decodable, Hashable, Identifiable { let bureau: String; let checkedAt: String?; let daysSince: Int?; let due: Bool; let frozen: Bool; let frozenAt: String?; var id: String { bureau } }
    struct Dispute: Decodable, Hashable, Identifiable { let id: String; let bureau: String; let item: String; let sentOn: String; let status: String; let note: String; let closedOn: String?; let followUpOn: String; let followUpDue: Bool }
    let bureaus: [Bureau]; let disputes: [Dispute]; let reportsUrl: String; let freezeUrl: String; let note: String
}

struct CreditHabits: Decodable, Hashable {
    struct Item: Decodable, Hashable, Identifiable { let key: String; let title: String; let state: String; let detail: String; var id: String { key } }
    let items: [Item]; let note: String
}

struct UtilizationHistory: Decodable, Hashable {
    struct Point: Decodable, Hashable, Identifiable { let day: String; let utilization: Double; let balance: Double; let limit: Double; var id: String { day } }
    let points: [Point]
}

struct IncomeGoal: Decodable, Hashable {
    let goal: Double?; let earned: Double; let daysLeft: Int
    var left: Double? = nil; var progress: Double? = nil; var perDay: Double? = nil; var hourly: Double? = nil; var hoursNeeded: Double? = nil; var reached: Bool? = nil
}

struct BestDays: Decodable, Hashable {
    struct Day: Decodable, Hashable, Identifiable { let weekday: String; let earned: Double; let hours: Double; let entries: Int; let hourly: Double?; var id: String { weekday } }
    let days: [Day]; let best: [String]; let sources: [String]; let note: String
}

struct MoneyWins: Decodable, Hashable {
    struct Win: Decodable, Hashable, Identifiable { let id: String; let title: String; let amount: Double; let monthly: Bool; let day: String }
    let wins: [Win]; let thisYear: Double; let perMonthOngoing: Double
}

struct Selling: Decodable, Hashable {
    struct Item: Decodable, Hashable, Identifiable { let id: String; let name: String; let asking: Double?; let sold: Double?; let whereListed: String; let listedOn: String; let soldOn: String?; let daysListed: Int }
    let items: [Item]; let listed: Int; let listedValue: Double; let soldThisYear: Double
}

struct OwedToMe: Decodable, Hashable {
    struct Item: Decodable, Hashable, Identifiable { let id: String; let who: String; let amount: Double; let why: String; let expectedOn: String?; let receivedOn: String?; let late: Bool }
    let items: [Item]; let outstanding: Double; let late: Int
}

struct RoundUps: Decodable, Hashable { let month: String; let purchases: Int; let roundUps: Double; let note: String }
struct NoSpend: Decodable, Hashable { let thisMonth: Int; let streak: Int; let today: Bool; let days: [String]; let conflicts: [String] }

struct SetAsides: Decodable, Hashable {
    struct Fund: Decodable, Hashable, Identifiable { let billId: String; let name: String; let amount: Double; let due: String; let months: Int; let perMonth: Double; var id: String { billId } }
    let funds: [Fund]; let perMonthTotal: Double
}

struct MoneyTodos: Decodable, Hashable {
    struct Item: Decodable, Hashable, Identifiable {
        let rank: Int; let key: String; let title: String; let detail: String; let destination: String
        var id: String { key }
        enum CodingKeys: String, CodingKey { case rank, key, title, detail, destination = "where" }
    }
    let items: [Item]; let count: Int
}

struct WeeklyCheckIn: Decodable, Hashable {
    struct Due: Decodable, Hashable, Identifiable { let id: String; let name: String; let due: String; let amount: Double?; let overdue: Bool; let autopay: Bool }
    let weekOf: String; let bills: [Due]; let billsTotal: Double; let safePerDay: Double?; let incomeGoal: IncomeGoal; let owedToYou: Double; let todos: [MoneyTodos.Item]
}

struct Affordability: Decodable, Hashable {
    let ready: Bool
    var reason: String? = nil
    var amount: Double? = nil
    var verdict: String? = nil
    var why: String? = nil
    var leftBefore: Double? = nil
    var leftAfter: Double? = nil
    var perDayBefore: Double? = nil
    var perDayAfter: Double? = nil
    var days: Int? = nil
    var lowAfter: Double? = nil
    var note: String? = nil
}

struct GoalProjections: Decodable, Hashable {
    struct Goal: Decodable, Hashable, Identifiable { let goalId: String; let name: String; let left: Double; let pacePerMonth: Double; let paceFrom: String?; let months: Int?; let reach: String?; let deadline: String?; let onTrack: Bool?; var id: String { goalId } }
    let goals: [Goal]; let note: String
}

struct MoneySetup: Decodable, Hashable {
    struct Step: Decodable, Hashable, Identifiable { let key: String; let title: String; let done: Bool; var id: String { key } }
    let steps: [Step]; let done: Int; let total: Int
}

private struct LinksBox: Decodable { let links: [String: String] }

extension APIClient {
    private var tz3: String { TimeZone.current.identifier }
    private var tzq3: String { "tz=\(tz3.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "-_."))) ?? "UTC")" }
    private func body3(_ f: [String: Any?]) throws -> Data { try JSONSerialization.data(withJSONObject: f.mapValues { $0 ?? NSNull() }) }
    private func put3(_ path: String, _ method: String, _ f: [String: Any?] = [:]) async throws {
        _ = try await send(request(path, method: method, body: body3(f)), as: JSONValue.self)
    }
    private func get3<T: Decodable>(_ path: String, _ t: T.Type) async throws -> T {
        try await send(request(path + (path.contains("?") ? "&" : "?") + tzq3), as: T.self)
    }

    func parseBill(_ text: String) async throws -> ParsedBill {
        try await send(request("/api/money/bills/parse", method: "POST", body: body3(["text": text, "tz": tz3])), as: ParsedBill.self)
    }
    func dueDateMoves() async throws -> DueDateMoves { try await get3("/api/money/due-date-moves", DueDateMoves.self) }
    func billHistory(_ id: String) async throws -> BillHistory { try await get3("/api/money/bills/\(id)/history", BillHistory.self) }
    func setPaymentNote(_ bill: String, period: String, confirmation: String, method: String) async throws {
        try await put3("/api/money/bills/\(bill)/payment-note", "PUT", ["period": period, "confirmation": confirmation, "method": method])
    }
    func moneyForecast() async throws -> MoneyForecast { try await get3("/api/money/forecast", MoneyForecast.self) }

    func creditWatch() async throws -> CreditWatch { try await get3("/api/money/credit-watch", CreditWatch.self) }
    func markBureau(_ kind: String, _ bureau: String, on: Bool) async throws { try await put3("/api/money/credit-watch/\(kind)/\(bureau)", "PUT", ["on": on]) }
    func addDispute(bureau: String, item: String) async throws { try await put3("/api/money/disputes", "POST", ["bureau": bureau, "item": item, "tz": tz3]) }
    func updateDispute(_ id: String, status: String) async throws { try await put3("/api/money/disputes/\(id)", "PATCH", ["status": status, "tz": tz3]) }
    func removeDispute(_ id: String) async throws { _ = try await json("/api/money/disputes/\(id)", method: "DELETE") }
    func creditHabits() async throws -> CreditHabits { try await get3("/api/money/credit-habits", CreditHabits.self) }
    func utilizationHistory() async throws -> UtilizationHistory { try await get3("/api/money/utilization-history", UtilizationHistory.self) }
    func cardBill(_ card: String, dueDay: Int) async throws { try await put3("/api/money/credit/cards/\(card)/bill", "PUT", ["due_day": dueDay, "tz": tz3]) }
    func cardBillLinks() async throws -> [String: String] { try await send(request("/api/money/card-bills"), as: LinksBox.self).links }

    func incomeGoal() async throws -> IncomeGoal { try await get3("/api/money/income-goal", IncomeGoal.self) }
    func setIncomeGoal(_ monthly: Double?) async throws { try await put3("/api/money/income-goal", "PUT", ["monthly": monthly]) }
    func bestDays() async throws -> BestDays { try await get3("/api/money/best-days", BestDays.self) }

    func moneyWins() async throws -> MoneyWins { try await get3("/api/money/wins", MoneyWins.self) }
    func addWin(title: String, amount: Double, monthly: Bool) async throws { try await put3("/api/money/wins", "POST", ["title": title, "amount": amount, "monthly": monthly, "tz": tz3]) }
    func removeWin(_ id: String) async throws { _ = try await json("/api/money/wins/\(id)", method: "DELETE") }
    func selling() async throws -> Selling { try await get3("/api/money/selling", Selling.self) }
    func addSellItem(name: String, asking: Double?, whereListed: String) async throws {
        try await put3("/api/money/selling", "POST", ["name": name, "asking": asking, "where_listed": whereListed, "tz": tz3])
    }
    func markSold(_ id: String, price: Double?) async throws { try await put3("/api/money/selling/\(id)", "PATCH", ["sold": price, "tz": tz3]) }
    func removeSellItem(_ id: String) async throws { _ = try await json("/api/money/selling/\(id)", method: "DELETE") }
    func owedToMe() async throws -> OwedToMe { try await get3("/api/money/owed", OwedToMe.self) }
    func addOwed(who: String, amount: Double, why: String, expectedOn: String?) async throws {
        try await put3("/api/money/owed", "POST", ["who": who, "amount": amount, "why": why, "expected_on": expectedOn])
    }
    func markOwed(_ id: String, received: Bool) async throws { try await put3("/api/money/owed/\(id)/received", "PUT", ["received": received, "tz": tz3]) }
    func removeOwed(_ id: String) async throws { _ = try await json("/api/money/owed/\(id)", method: "DELETE") }

    func roundUps() async throws -> RoundUps { try await get3("/api/money/round-ups", RoundUps.self) }
    func noSpend() async throws -> NoSpend { try await get3("/api/money/no-spend", NoSpend.self) }
    func setNoSpend(on: Bool, day: String? = nil) async throws { try await put3("/api/money/no-spend", "PUT", ["on": on, "day": day, "tz": tz3]) }
    func setAsides() async throws -> SetAsides { try await get3("/api/money/set-asides", SetAsides.self) }
    func setAsideGoal(_ bill: String) async throws { try await put3("/api/money/set-asides/\(bill)/goal", "POST", ["tz": tz3]) }

    func moneyTodos() async throws -> MoneyTodos { try await get3("/api/money/todos", MoneyTodos.self) }
    func weeklyCheckIn() async throws -> WeeklyCheckIn { try await get3("/api/money/weekly", WeeklyCheckIn.self) }
    func afford(_ amount: Double) async throws -> Affordability { try await get3("/api/money/afford?amount=\(amount)", Affordability.self) }
    func goalProjections() async throws -> GoalProjections { try await get3("/api/money/projections", GoalProjections.self) }
    func moneyExport() async throws -> Data {
        let (data, resp) = try await session.data(for: request("/api/money/export"))
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw APIError(status: (resp as? HTTPURLResponse)?.statusCode ?? 0, detail: "Couldn't export.") }
        return data
    }
    func moneySetup() async throws -> MoneySetup { try await get3("/api/money/setup", MoneySetup.self) }
}
