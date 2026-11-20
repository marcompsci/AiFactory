import Foundation

/// V6.128–V6.157: money, round 2 — spending, balances, safe to spend, debts, paydown targets, bill checks, gigs,
/// cashback, emergency fund, net worth, the monthly review, split bills. Everything is typed in; nothing moves money.

struct SpendingMonth: Decodable, Hashable {
    struct Category: Decodable, Hashable, Identifiable {
        let category: String; let spent: Double; let limit: Double?; let budgetId: String?; let left: Double?; let over: Bool; let progress: Double?
        var id: String { category }
    }
    struct Entry: Decodable, Hashable, Identifiable { let id: String; let amount: Double; let category: String; let day: String; let note: String }
    let month: String
    let total: Double
    let categories: [Category]
    let limitTotal: Double?
    let pace: Double?
    let entries: [Entry]
    let suggestedCategories: [String]
}

struct CashAccount: Decodable, Hashable, Identifiable {
    struct Point: Decodable, Hashable { let balance: Double; let day: String }
    let id: String; let name: String; let kind: String; let balance: Double?; let asOf: String?; let history: [Point]
}

struct SafeToSpend: Decodable, Hashable {
    struct Due: Decodable, Hashable, Identifiable { let billId: String; let name: String; let due: String; let amount: Double?; let autopay: Bool; let overdue: Bool; var id: String { billId + due } }
    let ready: Bool
    var reason: String? = nil
    let nextPayday: String?
    let until: String
    let days: Int
    var balance: Double? = nil
    var spentSince: Double? = nil
    var billsBeforePayday: [Due]? = nil
    var billsTotal: Double? = nil
    var billsVary: Int? = nil
    var savingsSetAside: Double? = nil
    var left: Double? = nil
    var perDay: Double? = nil
    var balanceAgeDays: Int? = nil
    var short: Bool? = nil
    var shortfall: Double? = nil
    var warning: String? = nil
    let note: String
}

struct PaycheckSplit: Decodable, Hashable {
    struct Part: Decodable, Hashable, Identifiable { let label: String; let amount: Double; var id: String { label } }
    let ready: Bool
    var reason: String? = nil
    var from: String? = nil
    var to: String? = nil
    var pay: Double? = nil
    var bills: Double? = nil
    var savings: Double? = nil
    var spending: Double? = nil
    var perDay: Double? = nil
    var days: Int? = nil
    var parts: [Part]? = nil
    var short: Bool? = nil
}

struct Debt: Decodable, Hashable, Identifiable {
    let id: String; let name: String; let kind: String; let balance: Double; let apr: Double; let minPayment: Double
    let cardId: String?; let monthlyInterest: Double; let minCoversInterest: Bool
}

struct PayoffRun: Decodable, Hashable {
    struct Step: Decodable, Hashable, Identifiable { let id: String; let name: String; let paidOffMonth: Int?; let paidOff: String? }
    let method: String; let months: Int?; let finishes: String?; let interest: Double?; let monthlyPayment: Double; let order: [Step]; let never: Bool
}

struct Payoff: Decodable, Hashable {
    let debts: Int
    var total: Double? = nil
    var extra: Double? = nil
    var minimumsOnly: PayoffRun? = nil
    var avalanche: PayoffRun? = nil
    var snowball: PayoffRun? = nil
    var interestSavedByExtra: Double? = nil
    var monthsSavedByExtra: Int? = nil
    var notCoveringInterest: [String]? = nil
    let note: String
}

struct DebtsBox: Decodable, Hashable { let debts: [Debt]; let payoff: Payoff }

struct Paydown: Decodable, Hashable {
    struct Card: Decodable, Hashable, Identifiable {
        let id: String; let name: String; let balance: Double; let limit: Double; let utilization: Double
        let payTo30: Double; let payTo10: Double; let nextStatement: String?; let monthlyInterest: Double?; let apr: Double?
    }
    let cards: [Card]; let overallTo30: Double; let overallTo10: Double; let utilization: Double?; let note: String
}

struct BillChecks: Decodable, Hashable {
    struct Due: Decodable, Hashable, Identifiable { let billId: String; let name: String; let due: String; let amount: Double?; var id: String { billId + due } }
    struct Cover: Decodable, Hashable, Identifiable {
        let accountId: String?; let account: String; let balance: Double?; let bills: [Due]; let needed: Double; let covered: Bool?; let shortBy: Double?
        var id: String { accountId ?? "all" }
    }
    struct Change: Decodable, Hashable, Identifiable { let billId: String; let name: String; let last: Double; let before: Double; let change: Double; let period: String; var id: String { billId } }
    struct Late: Decodable, Hashable, Identifiable { let billId: String; let name: String; let due: String; let lateFee: Double?; let graceEnds: String; let inGrace: Bool; let daysLate: Int; var id: String { billId } }
    struct Extra: Decodable, Hashable { let autopayAccountId: String?; let lateFee: Double?; let graceDays: Int? }
    let nextPayday: String
    let autopay: [Cover]
    let amountChanges: [Change]
    let late: [Late]
    let lateFeesAtRisk: Double
    let extras: [String: Extra]
}

struct CallScript: Decodable, Hashable { let billId: String; let name: String; let lines: [String]; let note: String }

struct MoneySettings: Decodable, Hashable { let mileageRate: Double?; let taxPct: Double?; let emergencyGoalId: String?; let gigSources: [String] }

struct Gigs: Decodable, Hashable {
    struct Figures: Decodable, Hashable { let earned: Double; let costs: Double; let miles: Double; let mileage: Double; let net: Double; let hours: Double; let hourlyGross: Double?; let hourlyNet: Double? }
    struct Gig: Decodable, Hashable, Identifiable { let source: String; let recent: Figures; let year: Figures; var id: String { source } }
    struct Cost: Decodable, Hashable, Identifiable { let id: String; let source: String; let day: String; let amount: Double; let miles: Double; let note: String }
    let gigs: [Gig]; let days: Int; let mileageRate: Double?; let taxPct: Double?; let yearProfit: Double; let taxSetAside: Double?; let costs: [Cost]; let note: String
}

struct MoneyChecklist: Decodable, Hashable {
    struct Item: Decodable, Hashable, Identifiable { let key: String; let title: String; let detail: String; let url: String?; let doneAt: String?; var id: String { key } }
    let items: [Item]; let note: String
}

struct Cashback: Decodable, Hashable {
    struct ByCard: Decodable, Hashable, Identifiable { let card: String; let total: Double; var id: String { card } }
    struct Entry: Decodable, Hashable, Identifiable { let id: String; let card: String; let amount: Double; let day: String }
    let year: Int; let yearTotal: Double; let byCard: [ByCard]; let entries: [Entry]
}

struct EmergencyFund: Decodable, Hashable {
    let goalId: String?; let goal: String?; let saved: Double; let monthlyBills: Double; let monthlySpending: Double; let monthlyNeed: Double
    let monthsCovered: Double?; let for3Months: Double?; let for6Months: Double?; let note: String
}

struct NetWorth: Decodable, Hashable {
    struct Line: Decodable, Hashable, Identifiable { var id: String { (assetId ?? "") + name + kind }; let name: String; let value: Double; let kind: String; var assetId: String? = nil
        enum CodingKeys: String, CodingKey { case name, value, kind, assetId = "id" }
    }
    struct Snap: Decodable, Hashable, Identifiable { let day: String; let assets: Double; let debts: Double; let net: Double; var id: String { day } }
    let assets: Double; let debts: Double; let net: Double; let own: [Line]; let owe: [Line]; let snapshots: [Snap]
}

struct MoneyStreak: Decodable, Hashable { let current: Int; let best: Int; let counted: Int }

struct MoneyReview: Decodable, Hashable {
    let month: String; let income: Double; let spending: Double; let categories: [SpendingMonth.Category]; let overLimit: [String]
    let bills: OnTimeRecord.Month?; let saved: Double; let kept: Double; let netWorthChange: Double?; let highlights: [String]; let streak: MoneyStreak
}

struct BillSplits: Decodable, Hashable {
    struct Person: Decodable, Hashable, Identifiable { let id: String; let person: String; let share: Double; let receivedAt: String? }
    struct Entry: Decodable, Hashable, Identifiable { let billId: String; let name: String; let amount: Double?; let period: String; let people: [Person]; let yourShare: Double?; var id: String { billId } }
    let bills: [Entry]; let owedToYou: Double
}

private struct AccountsBox: Decodable { let accounts: [CashAccount] }

extension APIClient {
    private var tz2: String { TimeZone.current.identifier }
    private var tzq2: String { "tz=\(tz2.addingPercentEncoding(withAllowedCharacters: .alphanumerics.union(CharacterSet(charactersIn: "-_."))) ?? "UTC")" }
    private func body2(_ f: [String: Any?]) throws -> Data { try JSONSerialization.data(withJSONObject: f.mapValues { $0 ?? NSNull() }) }
    private func post(_ path: String, _ method: String = "POST", _ f: [String: Any?] = [:]) async throws {
        _ = try await send(request(path, method: method, body: body2(f)), as: JSONValue.self)
    }

    // spending (V6.129, V6.130)
    func spending(month: String? = nil) async throws -> SpendingMonth {
        try await send(request("/api/money/spending?\(tzq2)" + (month.map { "&month=\($0)" } ?? "")), as: SpendingMonth.self)
    }
    func logExpense(amount: Double, category: String, note: String? = nil) async throws {
        try await post("/api/money/spending", "POST", ["amount": amount, "category": category, "note": note, "tz": tz2])
    }
    func removeExpense(_ id: String) async throws { _ = try await json("/api/money/spending/\(id)", method: "DELETE") }
    func setCategoryLimit(_ category: String, limit: Double?) async throws {
        try await post("/api/money/spending/limits", "PUT", ["category": category, "limit": limit])
    }

    // accounts (V6.131), safe to spend (V6.132/133), paycheck split (V6.154)
    func cashAccounts() async throws -> [CashAccount] { try await send(request("/api/money/accounts"), as: AccountsBox.self).accounts }
    func addCashAccount(name: String, kind: String, balance: Double?) async throws {
        try await post("/api/money/accounts", "POST", ["name": name, "kind": kind, "balance": balance, "tz": tz2])
    }
    func checkIn(_ id: String, balance: Double) async throws { try await post("/api/money/accounts/\(id)/balance", "POST", ["balance": balance, "tz": tz2]) }
    func removeCashAccount(_ id: String) async throws { _ = try await json("/api/money/accounts/\(id)", method: "DELETE") }
    func safeToSpend() async throws -> SafeToSpend { try await send(request("/api/money/safe-to-spend?\(tzq2)"), as: SafeToSpend.self) }
    func paycheckSplit() async throws -> PaycheckSplit { try await send(request("/api/money/paycheck-split?\(tzq2)"), as: PaycheckSplit.self) }

    // debts (V6.134–V6.137), paydown (V6.138/139)
    func debts(extra: Double = 0) async throws -> DebtsBox { try await send(request("/api/money/debts?\(tzq2)&extra=\(extra)"), as: DebtsBox.self) }
    func saveDebt(_ id: String?, name: String, kind: String, balance: Double, apr: Double, minPayment: Double, cardId: String?) async throws {
        let f: [String: Any?] = ["name": name, "kind": kind, "balance": balance, "apr": apr, "min_payment": minPayment, "card_id": cardId]
        if let id { try await post("/api/money/debts/\(id)", "PATCH", f) } else { try await post("/api/money/debts", "POST", f) }
    }
    func removeDebt(_ id: String) async throws { _ = try await json("/api/money/debts/\(id)", method: "DELETE") }
    func paydown() async throws -> Paydown { try await send(request("/api/money/paydown?\(tzq2)"), as: Paydown.self) }

    // calendar (V6.140): the .ics file to share into Calendar
    func billCalendar() async throws -> Data {
        var r = request("/api/money/calendar.ics?\(tzq2)")
        r.setValue("text/calendar", forHTTPHeaderField: "Accept")
        let (data, resp) = try await session.data(for: r)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw APIError(status: (resp as? HTTPURLResponse)?.statusCode ?? 0, detail: "Couldn't make the calendar file.") }
        return data
    }

    // bill checks (V6.141–V6.143), call script (V6.147), splits (V6.153)
    func billChecks() async throws -> BillChecks { try await send(request("/api/money/bill-checks?\(tzq2)"), as: BillChecks.self) }
    func setBillExtras(_ bill: String, autopayAccountId: String?, lateFee: Double?, graceDays: Int?) async throws {
        try await post("/api/money/bills/\(bill)/extras", "PUT", ["autopay_account_id": autopayAccountId, "late_fee": lateFee, "grace_days": graceDays])
    }
    func callScript(_ bill: String, years: Int?, competitorPrice: Double?) async throws -> CallScript {
        var q = "/api/money/bills/\(bill)/call-script?\(tzq2)"
        if let years { q += "&years=\(years)" }
        if let competitorPrice { q += "&competitor_price=\(competitorPrice)" }
        return try await send(request(q), as: CallScript.self)
    }
    func splits() async throws -> BillSplits { try await send(request("/api/money/splits?\(tzq2)"), as: BillSplits.self) }
    func addSplit(_ bill: String, person: String, share: Double) async throws { try await post("/api/money/bills/\(bill)/splits", "POST", ["person": person, "share": share]) }
    func removeSplit(_ id: String) async throws { _ = try await json("/api/money/splits/\(id)", method: "DELETE") }
    func markReceived(_ id: String, period: String, received: Bool) async throws {
        try await post("/api/money/splits/\(id)/received", "PUT", ["period": period, "received": received])
    }

    // gigs and settings (V6.144/V6.145)
    func moneySettings() async throws -> MoneySettings { try await send(request("/api/money/settings"), as: MoneySettings.self) }
    func saveMoneySettings(_ f: [String: Any?]) async throws { try await post("/api/money/settings", "PATCH", f) }
    func gigs() async throws -> Gigs { try await send(request("/api/money/gigs?\(tzq2)"), as: Gigs.self) }
    func logGigCost(source: String, amount: Double?, miles: Double?) async throws {
        try await post("/api/money/gigs/costs", "POST", ["source": source, "amount": amount, "miles": miles, "tz": tz2])
    }
    func removeGigCost(_ id: String) async throws { _ = try await json("/api/money/gigs/costs/\(id)", method: "DELETE") }

    // checklist (V6.146), cashback (V6.148)
    func moneyChecklist() async throws -> MoneyChecklist { try await send(request("/api/money/checklist"), as: MoneyChecklist.self) }
    func checkItem(_ key: String, done: Bool) async throws { try await post("/api/money/checklist/\(key)", "PUT", ["done": done]) }
    func cashback() async throws -> Cashback { try await send(request("/api/money/cashback?\(tzq2)"), as: Cashback.self) }
    func logCashback(card: String, amount: Double) async throws { try await post("/api/money/cashback", "POST", ["card": card, "amount": amount, "tz": tz2]) }
    func removeCashback(_ id: String) async throws { _ = try await json("/api/money/cashback/\(id)", method: "DELETE") }

    // emergency fund (V6.149), net worth (V6.150), review (V6.151), streak (V6.152)
    func emergencyFund() async throws -> EmergencyFund { try await send(request("/api/money/emergency?\(tzq2)"), as: EmergencyFund.self) }
    func netWorth() async throws -> NetWorth { try await send(request("/api/money/net-worth?\(tzq2)"), as: NetWorth.self) }
    func saveAsset(_ id: String?, name: String, value: Double) async throws {
        if let id { try await post("/api/money/net-worth/assets/\(id)", "PUT", ["name": name, "value": value]) }
        else { try await post("/api/money/net-worth/assets", "POST", ["name": name, "value": value]) }
    }
    func removeAsset(_ id: String) async throws { _ = try await json("/api/money/net-worth/assets/\(id)", method: "DELETE") }
    func snapshotNetWorth() async throws { _ = try await send(request("/api/money/net-worth/snapshot?\(tzq2)", method: "POST"), as: JSONValue.self) }
    func moneyReview(month: String? = nil) async throws -> MoneyReview {
        try await send(request("/api/money/review?\(tzq2)" + (month.map { "&month=\($0)" } ?? "")), as: MoneyReview.self)
    }
}
