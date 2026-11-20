import Charts
import SwiftUI
import UserNotifications

/// V6.128–V6.157 on the phone: the "More" part of Money. Every screen works from numbers you type in; nothing is
/// connected to a bank, nothing moves money, and nothing here is financial, tax or credit advice.

private func oops(_ error: Error) -> String { (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
private func usd(_ v: Double?) -> String { v.map { $0.formatted(.currency(code: "USD")) } ?? "varies" }
private func pct(_ v: Double?) -> String { v.map { ($0).formatted(.percent.precision(.fractionLength(0))) } ?? "—" }
private func shortDay(_ iso: String) -> String {
    let f = DateFormatter()
    f.calendar = Calendar(identifier: .gregorian)
    f.dateFormat = "yyyy-MM-dd"
    return f.date(from: iso)?.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day()) ?? iso
}
private func monthName(_ ym: String) -> String {
    let f = DateFormatter()
    f.calendar = Calendar(identifier: .gregorian)
    f.dateFormat = "yyyy-MM"
    return f.date(from: ym)?.formatted(.dateTime.month(.wide).year()) ?? ym
}
private func num(_ s: String) -> Double? { Double(s.replacingOccurrences(of: ",", with: "").replacingOccurrences(of: "$", with: "")) }

/// Loads with the API, shows a load error inline. Every screen below uses it.
@MainActor @Observable final class Loader<T> {
    var value: T?
    var error: String?
    func load(_ app: AppState, _ f: @escaping (APIClient) async throws -> T) async {
        guard let api = app.api else { error = "Connect to your Mac first."; return }
        do { value = try await f(api); error = nil } catch { self.error = oops(error) }
    }
}

struct MoneyMoreView: View {
    var body: some View {
        List {
            MoneyAssistantSections()
            Section {
                NavigationLink { SafeToSpendView() } label: { Label("Safe to spend", systemImage: "gauge.with.dots.needle.33percent") }
                NavigationLink { SpendingView() } label: { Label("Spending and limits", systemImage: "cart") }
                NavigationLink { AccountsView() } label: { Label("Account balances", systemImage: "building.columns") }
            } header: { Text("Day to day") }
            Section {
                NavigationLink { DebtsView() } label: { Label("Debts and payoff plan", systemImage: "chart.line.downtrend.xyaxis") }
                NavigationLink { PaydownView() } label: { Label("Card paydown targets", systemImage: "creditcard") }
                NavigationLink { BillChecksView() } label: { Label("Bill checks", systemImage: "checklist.checked") }
                NavigationLink { SplitsView() } label: { Label("Split bills", systemImage: "person.2") }
                CalendarExportRow()
            } header: { Text("Bills and credit") }
            Section {
                NavigationLink { GigsView() } label: { Label("Side gigs and tax set-aside", systemImage: "car") }
                NavigationLink { CashbackView() } label: { Label("Cashback", systemImage: "gift") }
                NavigationLink { ChecklistView() } label: { Label("Find unclaimed money", systemImage: "magnifyingglass.circle") }
            } header: { Text("Make more") }
            Section {
                NavigationLink { EmergencyView() } label: { Label("Emergency fund", systemImage: "lifepreserver") }
                NavigationLink { NetWorthView() } label: { Label("Net worth", systemImage: "chart.bar") }
                NavigationLink { MoneyReviewView() } label: { Label("Monthly review", systemImage: "calendar.badge.checkmark") }
            } header: { Text("Progress") } footer: {
                Text("Everything here is worked out from numbers you enter. Nothing is connected to a bank or moves money, and none of it is financial advice.")
            }
        }
    }
}

// MARK: - V6.132/V6.133 safe to spend, V6.154 paycheck split

struct SafeToSpendView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<SafeToSpend>()
    @State private var split = Loader<PaycheckSplit>()

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                if !v.ready {
                    Section { Text(v.reason ?? "").font(.callout); NavigationLink("Add an account") { AccountsView() } }
                } else {
                    Section {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(usd(v.perDay)).font(.largeTitle.bold().monospacedDigit()).foregroundStyle(v.short == true ? Theme.bad : Theme.ok)
                            Text("a day for \(v.days) day\(v.days == 1 ? "" : "s")" + (v.nextPayday.map { ", until payday \(shortDay($0))" } ?? ", until the end of the month"))
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        .accessibilityElement(children: .combine)
                        if let w = v.warning { Label(w, systemImage: "exclamationmark.triangle.fill").font(.callout).foregroundStyle(Theme.bad) }
                        LabeledContent("Balance you entered", value: usd(v.balance))
                        if (v.spentSince ?? 0) > 0 { LabeledContent("Spent since then", value: "−" + usd(v.spentSince)) }
                        LabeledContent("Bills before payday", value: "−" + usd(v.billsTotal) + ((v.billsVary ?? 0) > 0 ? " + \(v.billsVary!) that vary" : ""))
                        if (v.savingsSetAside ?? 0) > 0 { LabeledContent("Savings plans", value: "−" + usd(v.savingsSetAside)) }
                        LabeledContent("Left", value: usd(v.left)).font(.headline)
                        if let age = v.balanceAgeDays, age >= 3 { Text("Your balance is \(age) days old. Update it for a better figure.").font(.caption).foregroundStyle(Theme.gold) }
                    } footer: { Text(v.note) }
                    if let due = v.billsBeforePayday, !due.isEmpty {
                        Section("Bills before payday") {
                            ForEach(due) { b in
                                LabeledContent(b.name + (b.autopay ? " (autopay)" : ""), value: "\(b.overdue ? "past due" : shortDay(b.due)) · \(usd(b.amount))")
                                    .foregroundStyle(b.overdue ? Theme.bad : Theme.ink)
                            }
                        }
                    }
                }
            }
            if let p = split.value {
                Section {
                    if p.ready, let parts = p.parts {
                        Chart(parts) { x in
                            BarMark(x: .value("Amount", x.amount), y: .value("Paycheck", "Pay")).foregroundStyle(by: .value("Part", x.label))
                        }
                        .chartForegroundStyleScale(["Bills": Theme.bad, "Savings": Theme.gold, "Spending": Theme.ok])
                        .frame(height: 50)
                        .accessibilityLabel("Paycheck split: bills \(usd(p.bills)), savings \(usd(p.savings)), spending \(usd(p.spending))")
                        LabeledContent("Paycheck", value: usd(p.pay))
                        LabeledContent("Bills until the next one", value: usd(p.bills))
                        LabeledContent("Savings plans", value: usd(p.savings))
                        LabeledContent("To spend", value: usd(p.spending) + (p.perDay.map { " · \(usd($0))/day" } ?? "")).font(.headline)
                            .foregroundStyle(p.short == true ? Theme.bad : Theme.ink)
                    } else {
                        Text(p.reason ?? "").font(.caption).foregroundStyle(.secondary)
                    }
                } header: { Text("Paycheck split" + (p.from.map { " · \(shortDay($0)) → \(shortDay(p.to ?? $0))" } ?? "")) }
            }
        }
        .navigationTitle("Safe to spend")
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        await s.load(app) { try await $0.safeToSpend() }
        await split.load(app) { try await $0.paycheckSplit() }
    }
}

// MARK: - V6.129/V6.130 spending and category limits

struct SpendingView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<SpendingMonth>()
    @State private var amount = ""
    @State private var category = "Groceries"
    @State private var note = ""
    @State private var limitFor: SpendingMonth.Category?
    @State private var limitText = ""
    @State private var error: String?

    var body: some View {
        List {
            Section {
                TextField("Amount", text: $amount).keyboardType(.decimalPad)
                Picker("Category", selection: $category) {
                    ForEach(categories, id: \.self) { Text($0).tag($0) }
                }
                TextField("Note (optional)", text: $note)
                Button { Task { await log() } } label: { Label("Log it for today", systemImage: "plus.circle.fill") }
                    .disabled(num(amount) == nil)
            } header: { Text("Log spending") }
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    LabeledContent("Spent this month", value: usd(v.total) + (v.limitTotal.map { " of \(usd($0))" } ?? ""))
                    if let pace = v.pace { Text("At this pace, about \(usd(pace)) by month end.").font(.caption).foregroundStyle(.secondary) }
                    ForEach(v.categories) { c in
                        Button { limitFor = c; limitText = c.limit.map { String(format: "%.0f", $0) } ?? "" } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                HStack {
                                    Text(c.category).foregroundStyle(Theme.ink)
                                    Spacer()
                                    Text(usd(c.spent) + (c.limit.map { " / \(usd($0))" } ?? "")).monospacedDigit().foregroundStyle(c.over ? Theme.bad : .secondary)
                                }.font(.subheadline)
                                if let p = c.progress { ProgressView(value: min(p, 1)).tint(c.over ? Theme.bad : p > 0.8 ? Theme.gold : Theme.ok) }
                            }
                        }
                        .accessibilityHint("Set a monthly limit")
                    }
                } header: { Text(monthName(v.month)) } footer: { Text("Tap a category to set a monthly limit.") }
                Section("Entries") {
                    ForEach(v.entries) { e in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(e.category).font(.subheadline)
                                Text(shortDay(e.day) + (e.note.isEmpty ? "" : " · \(e.note)")).font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(usd(e.amount)).monospacedDigit()
                        }
                        .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeExpense(e.id) } } } label: { Label("Delete", systemImage: "trash") } }
                    }
                }
            }
        }
        .navigationTitle("Spending")
        .alert("Monthly limit for \(limitFor?.category ?? "")", isPresented: Binding(get: { limitFor != nil }, set: { if !$0 { limitFor = nil } })) {
            TextField("Amount (empty for none)", text: $limitText).keyboardType(.decimalPad)
            Button("Save") { if let c = limitFor { Task { await run { try await $0.setCategoryLimit(c.category, limit: num(limitText)) } } } }
            Button("Cancel", role: .cancel) {}
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private var categories: [String] {
        let used = s.value?.categories.map(\.category) ?? []
        return Array(NSOrderedSet(array: (s.value?.suggestedCategories ?? ["Groceries", "Other"]) + used)) as? [String] ?? ["Groceries"]
    }

    private func load() async { await s.load(app) { try await $0.spending() } }

    private func log() async {
        guard let a = num(amount) else { return }
        await run { try await $0.logExpense(amount: a, category: category, note: note.isEmpty ? nil : note) }
        if error == nil { amount = ""; note = ""; Haptics.success() }
    }

    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.131 account balances

struct AccountsView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<[CashAccount]>()
    @State private var name = ""
    @State private var kind = "checking"
    @State private var balance = ""
    @State private var updating: CashAccount?
    @State private var newBalance = ""
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            Section {
                ForEach(s.value ?? []) { a in
                    Button { updating = a; newBalance = "" } label: {
                        HStack {
                            VStack(alignment: .leading) {
                                Text(a.name).foregroundStyle(Theme.ink)
                                Text(a.kind.capitalized + (a.asOf.map { " · as of \(shortDay($0))" } ?? " · no balance yet")).font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(usd(a.balance)).monospacedDigit().foregroundStyle((a.balance ?? 0) < 0 ? Theme.bad : Theme.ink)
                        }
                    }
                    .accessibilityHint("Update the balance")
                    .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeCashAccount(a.id) } } } label: { Label("Delete", systemImage: "trash") } }
                }
            } header: { Text("Your accounts") } footer: { Text("Check your bank app and type the balance in. Tap an account to update it. Nicknames only: no account numbers.") }
            Section("Add an account") {
                TextField("Nickname (Everyday checking)", text: $name)
                Picker("Kind", selection: $kind) { Text("Checking").tag("checking"); Text("Savings").tag("savings"); Text("Cash").tag("cash") }
                TextField("Balance today (optional)", text: $balance).keyboardType(.numbersAndPunctuation)
                Button("Add") { Task { await add() } }.disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .navigationTitle("Balances")
        .alert("Balance today for \(updating?.name ?? "")", isPresented: Binding(get: { updating != nil }, set: { if !$0 { updating = nil } })) {
            TextField("Balance", text: $newBalance).keyboardType(.numbersAndPunctuation)
            Button("Save") { if let a = updating, let b = num(newBalance) { Task { await run { try await $0.checkIn(a.id, balance: b) } } } }
            Button("Cancel", role: .cancel) {}
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async { await s.load(app) { try await $0.cashAccounts() } }
    private func add() async {
        await run { try await $0.addCashAccount(name: name.trimmingCharacters(in: .whitespaces), kind: kind, balance: num(balance)) }
        if error == nil { name = ""; balance = "" }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.134–V6.137 debts and the payoff plan

struct DebtDraft: Identifiable {
    var id: String?
    var name = ""
    var kind = "card"
    var balance = ""
    var apr = ""
    var minPayment = ""
    var cardId: String?
}

struct DebtsView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<DebtsBox>()
    @State private var extra: Double = 0
    @State private var draft: DebtDraft?
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    ForEach(v.debts) { d in
                        Button { draft = DebtDraft(id: d.id, name: d.name, kind: d.kind, balance: String(format: "%.2f", d.balance), apr: String(d.apr),
                                                   minPayment: String(format: "%.2f", d.minPayment), cardId: d.cardId) } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                HStack { Text(d.name).foregroundStyle(Theme.ink); Spacer(); Text(usd(d.balance)).monospacedDigit() }
                                Text("\(String(format: "%.2f", d.apr))% APR · min \(usd(d.minPayment)) · about \(usd(d.monthlyInterest)) interest a month")
                                    .font(.caption2).foregroundStyle(d.minCoversInterest ? .secondary : Theme.bad)
                            }
                        }
                        .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeDebt(d.id) } } } label: { Label("Delete", systemImage: "trash") } }
                    }
                    Button { draft = DebtDraft() } label: { Label("Add a debt", systemImage: "plus") }
                } header: { Text("Debts") }
                let p = v.payoff
                if p.debts > 0 {
                    Section {
                        VStack(alignment: .leading) {
                            Text("Extra each month: \(usd(extra))").font(.subheadline)
                            Slider(value: $extra, in: 0...1000, step: 25) { Text("Extra each month") } onEditingChanged: { if !$0 { Task { await load() } } }
                        }
                        if let names = p.notCoveringInterest, !names.isEmpty {
                            Label("The minimum on \(names.joined(separator: ", ")) doesn't cover its interest, so the balance grows.", systemImage: "exclamationmark.triangle")
                                .font(.caption).foregroundStyle(Theme.bad)
                        }
                        runView(p.avalanche, title: "Avalanche · highest APR first")
                        runView(p.snowball, title: "Snowball · smallest balance first")
                        if let m = p.minimumsOnly { runView(m, title: "Minimums only") }
                        if let saved = p.interestSavedByExtra, extra > 0 {
                            Text("Paying \(usd(extra)) extra saves about \(usd(saved)) of interest" + (p.monthsSavedByExtra.map { " and \($0) months" } ?? "") + ".")
                                .font(.callout).foregroundStyle(Theme.ok)
                        }
                    } header: { Text("Payoff plan") } footer: { Text(p.note + " Which method to use is your call.") }
                }
            }
        }
        .navigationTitle("Debts")
        .sheet(item: $draft) { d in DebtEditor(draft: d) { await load() }.presentationDetents([.medium, .large]) }
        .task { await load() }
        .refreshable { await load() }
    }

    @ViewBuilder private func runView(_ r: PayoffRun?, title: String) -> some View {
        if let r {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.subheadline.bold())
                if r.never {
                    Text("Not paid off at this payment.").font(.caption).foregroundStyle(Theme.bad)
                } else {
                    Text("Debt-free \(r.finishes.map(monthName) ?? "") · \(r.months ?? 0) months · about \(usd(r.interest)) interest").font(.caption)
                    Text(r.order.compactMap { s in s.paidOff.map { "\(s.name) \(monthName($0))" } }.joined(separator: " → ")).font(.caption2).foregroundStyle(.secondary)
                }
            }
            .accessibilityElement(children: .combine)
        }
    }

    private func load() async {
        let e = extra
        await s.load(app) { try await $0.debts(extra: e) }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

struct DebtEditor: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State var draft: DebtDraft
    @State private var cards: [CreditCardInfo] = []
    @State private var error: String?
    let saved: () async -> Void

    var body: some View {
        NavigationStack {
            Form {
                TextField("Name (no account numbers)", text: $draft.name)
                Picker("Kind", selection: $draft.kind) { Text("Card").tag("card"); Text("Loan").tag("loan"); Text("Other").tag("other") }
                TextField("Balance", text: $draft.balance).keyboardType(.decimalPad)
                TextField("APR %", text: $draft.apr).keyboardType(.decimalPad)
                TextField("Minimum payment", text: $draft.minPayment).keyboardType(.decimalPad)
                if draft.kind == "card", !cards.isEmpty {
                    Picker("Same as card", selection: $draft.cardId) {
                        Text("None").tag(String?.none)
                        ForEach(cards) { Text($0.name).tag(Optional($0.id)) }
                    }
                }
                if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            }
            .navigationTitle(draft.id == nil ? "Add a debt" : "Edit debt")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save() } }
                        .disabled(draft.name.trimmingCharacters(in: .whitespaces).isEmpty || num(draft.balance) == nil || num(draft.minPayment) == nil)
                }
            }
            .task { cards = (try? await app.api?.credit().cards) ?? [] }
        }
    }

    private func save() async {
        guard let api = app.api, let b = num(draft.balance), let m = num(draft.minPayment) else { return }
        do {
            try await api.saveDebt(draft.id, name: draft.name.trimmingCharacters(in: .whitespaces), kind: draft.kind, balance: b,
                                   apr: num(draft.apr) ?? 0, minPayment: m, cardId: draft.kind == "card" ? draft.cardId : nil)
            await saved()
            dismiss()
        } catch { self.error = oops(error) }
    }
}

// MARK: - V6.138/V6.139 card paydown targets

struct PaydownView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<Paydown>()

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                if v.cards.isEmpty { Text("Add your cards under Money → Credit first.").foregroundStyle(.secondary) }
                if !v.cards.isEmpty {
                    Section {
                        LabeledContent("Overall utilization", value: pct(v.utilization))
                        LabeledContent("To get under 30%", value: usd(v.overallTo30))
                        LabeledContent("To get under 10%", value: usd(v.overallTo10))
                    }
                }
                ForEach(v.cards) { c in
                    Section {
                        LabeledContent("Balance", value: "\(usd(c.balance)) of \(usd(c.limit)) · \(pct(c.utilization))")
                        if c.payTo30 > 0 { LabeledContent("Pay to get under 30%", value: usd(c.payTo30)) } else { Text("Under 30% already").font(.caption).foregroundStyle(Theme.ok) }
                        if c.payTo10 > 0 { LabeledContent("Pay to get under 10%", value: usd(c.payTo10)) }
                        if let i = c.monthlyInterest { LabeledContent("Interest at this balance", value: "about \(usd(i)) a month") }
                        if let d = c.nextStatement { Text("Statement closes \(shortDay(d)). Paying before then lowers the balance that usually gets reported.").font(.caption2).foregroundStyle(.secondary) }
                    } header: { Text(c.name) }
                }
                Section { } footer: { Text(v.note) }
            }
        }
        .navigationTitle("Paydown targets")
        .task { await s.load(app) { try await $0.paydown() } }
        .refreshable { await s.load(app) { try await $0.paydown() } }
    }
}

// MARK: - V6.140 calendar export

struct CalendarExportRow: View {
    @Environment(AppState.self) private var app
    @State private var file: URL?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading) {
            if let file {
                ShareLink(item: file) { Label("Share bills and paydays to Calendar", systemImage: "calendar.badge.plus") }
            } else {
                Button { Task { await make() } } label: { Label("Bills and paydays calendar", systemImage: "calendar.badge.plus") }
            }
            if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
        }
        .accessibilityHint("Makes a calendar file of the next 12 months of bills and paydays")
    }

    private func make() async {
        guard let api = app.api else { return }
        do {
            let data = try await api.billCalendar()
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("bills-and-paydays.ics")
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            file = url
        } catch { self.error = oops(error) }
    }
}

// MARK: - V6.141–V6.143 bill checks, V6.147 call script

struct BillChecksView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<BillChecks>()
    @State private var bills: [Bill] = []
    @State private var accounts: [CashAccount] = []
    @State private var editing: Bill?
    @State private var scriptFor: Bill?
    @State private var historyFor: Bill?

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    if v.autopay.isEmpty { Text("No autopay bills before payday.").font(.caption).foregroundStyle(.secondary) }
                    ForEach(v.autopay) { c in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Text(c.account).font(.subheadline.bold())
                                Spacer()
                                if c.covered == false { Text("short \(usd(c.shortBy))").font(.caption.bold()).foregroundStyle(Theme.bad) }
                                else if c.covered == true { Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.ok).accessibilityLabel("Covered") }
                            }
                            Text("\(usd(c.needed)) of autopay due · balance \(usd(c.balance))").font(.caption)
                            Text(c.bills.map { "\($0.name) \(shortDay($0.due))" }.joined(separator: ", ")).font(.caption2).foregroundStyle(.secondary)
                        }
                        .accessibilityElement(children: .combine)
                    }
                } header: { Text("Autopay before payday (\(shortDay(v.nextPayday)))") } footer: { Text("Checked against the last balance you entered.") }
                if !v.amountChanges.isEmpty {
                    Section("Amount changes") {
                        ForEach(v.amountChanges) { c in
                            LabeledContent(c.name, value: "\(usd(c.before)) → \(usd(c.last)) (\(c.change > 0 ? "+" : "")\(pct(c.change)))")
                                .foregroundStyle(c.change > 0 ? Theme.bad : Theme.ok)
                        }
                    }
                }
                if !v.late.isEmpty {
                    Section {
                        ForEach(v.late) { l in
                            VStack(alignment: .leading) {
                                Text(l.name).font(.subheadline.bold()).foregroundStyle(Theme.bad)
                                Text("Due \(shortDay(l.due)), \(l.daysLate) day\(l.daysLate == 1 ? "" : "s") ago" + (l.lateFee.map { " · late fee \(usd($0))" } ?? "")
                                     + (l.inGrace ? " · grace period ends \(shortDay(l.graceEnds))" : "")).font(.caption)
                            }
                        }
                    } header: { Text("Past due") } footer: { if v.lateFeesAtRisk > 0 { Text("Late fees at stake: \(usd(v.lateFeesAtRisk)).") } }
                }
                Section {
                    ForEach(bills) { b in
                        let x = v.extras[b.id]
                        HStack {
                            VStack(alignment: .leading) {
                                Text(b.name)
                                Text([x?.lateFee.map { "late fee \(usd($0))" }, x?.graceDays.map { "\($0) grace days" },
                                      x?.autopayAccountId.flatMap { id in accounts.first { $0.id == id }?.name }.map { "autopay from \($0)" }]
                                    .compactMap { $0 }.joined(separator: " · ")).font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Menu {
                                Button("Late fee and autopay") { editing = b }
                                Button("Script to lower this bill") { scriptFor = b }
                                Button("Payment history") { historyFor = b }
                            } label: { Image(systemName: "ellipsis.circle").accessibilityLabel("Options for \(b.name)") }
                        }
                    }
                } header: { Text("Your bills") }
            }
        }
        .navigationTitle("Bill checks")
        .sheet(item: $editing) { b in BillExtrasEditor(bill: b, accounts: accounts, extra: s.value?.extras[b.id]) { await load() }.presentationDetents([.medium]) }
        .sheet(item: $scriptFor) { b in CallScriptView(bill: b).presentationDetents([.large]) }
        .sheet(item: $historyFor) { b in NavigationStack { BillHistoryView(bill: b) }.presentationDetents([.large]) }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        await s.load(app) { try await $0.billChecks() }
        bills = (try? await app.api?.bills()) ?? bills
        accounts = (try? await app.api?.cashAccounts()) ?? accounts
    }
}

struct BillExtrasEditor: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let bill: Bill
    let accounts: [CashAccount]
    let extra: BillChecks.Extra?
    let saved: () async -> Void
    @State private var fee = ""
    @State private var grace = ""
    @State private var account: String?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                TextField("Late fee", text: $fee).keyboardType(.decimalPad)
                TextField("Grace days", text: $grace).keyboardType(.numberPad)
                if bill.autopay {
                    Picker("Autopay from", selection: $account) {
                        Text("Not set").tag(String?.none)
                        ForEach(accounts) { Text($0.name).tag(Optional($0.id)) }
                    }
                }
                if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            }
            .navigationTitle(bill.name)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { Task { await save() } } }
            }
            .onAppear {
                fee = extra?.lateFee.map { String(format: "%.2f", $0) } ?? ""
                grace = extra?.graceDays.map(String.init) ?? ""
                account = extra?.autopayAccountId
            }
        }
    }

    private func save() async {
        guard let api = app.api else { return }
        do {
            try await api.setBillExtras(bill.id, autopayAccountId: account, lateFee: num(fee), graceDays: Int(grace))
            await saved()
            dismiss()
        } catch { self.error = oops(error) }
    }
}

struct CallScriptView: View {
    @Environment(AppState.self) private var app
    let bill: Bill
    @State private var years = ""
    @State private var price = ""
    @State private var script: CallScript?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Years as a customer (optional)", text: $years).keyboardType(.numberPad)
                    TextField("A lower price you've seen (optional)", text: $price).keyboardType(.decimalPad)
                    Button("Write the script") { Task { await make() } }
                }
                if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
                if let script {
                    Section {
                        ForEach(Array(script.lines.enumerated()), id: \.offset) { i, l in Text("\(i + 1). \(l)").textSelection(.enabled) }
                        ShareLink(item: script.lines.joined(separator: "\n\n")) { Label("Copy or share", systemImage: "square.and.arrow.up") }
                    } footer: { Text(script.note) }
                }
            }
            .navigationTitle("Lower \(bill.name)")
            .task { await make() }
        }
    }

    private func make() async {
        guard let api = app.api else { return }
        do { script = try await api.callScript(bill.id, years: Int(years), competitorPrice: num(price)); error = nil } catch { self.error = oops(error) }
    }
}

// MARK: - V6.153 split bills

struct SplitsView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<BillSplits>()
    @State private var bills: [Bill] = []
    @State private var bill: String?
    @State private var person = ""
    @State private var share = ""
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                if v.owedToYou > 0 { Section { LabeledContent("Owed to you this period", value: usd(v.owedToYou)).font(.headline) } }
                ForEach(v.bills) { b in
                    Section {
                        ForEach(b.people) { x in
                            Toggle(isOn: Binding(get: { x.receivedAt != nil },
                                                 set: { on in Task { await run { try await $0.markReceived(x.id, period: b.period, received: on) } } })) {
                                VStack(alignment: .leading) {
                                    Text(x.person)
                                    Text(usd(x.share) + (x.receivedAt != nil ? " · paid you" : " · not yet")).font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                            .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeSplit(x.id) } } } label: { Label("Remove", systemImage: "trash") } }
                        }
                        if let mine = b.yourShare { LabeledContent("Your share", value: usd(mine)) }
                    } header: { Text("\(b.name) · \(usd(b.amount)) · \(b.period)") }
                }
            }
            Section {
                Picker("Bill", selection: $bill) {
                    Text("Pick a bill").tag(String?.none)
                    ForEach(bills) { Text($0.name).tag(Optional($0.id)) }
                }
                TextField("Who (a first name)", text: $person)
                TextField("Their share each time", text: $share).keyboardType(.decimalPad)
                Button("Add") { Task { await add() } }.disabled(bill == nil || person.trimmingCharacters(in: .whitespaces).isEmpty || num(share) == nil)
            } header: { Text("Split a bill") } footer: { Text("A record of who owes you. You collect it yourself; the app doesn't request or move money.") }
        }
        .navigationTitle("Split bills")
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        await s.load(app) { try await $0.splits() }
        bills = (try? await app.api?.bills()) ?? bills
    }
    private func add() async {
        guard let b = bill, let v = num(share) else { return }
        await run { try await $0.addSplit(b, person: person.trimmingCharacters(in: .whitespaces), share: v) }
        if error == nil { person = ""; share = "" }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.144/V6.145 side gigs and the tax set-aside

struct GigsView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<Gigs>()
    @State private var settings: MoneySettings?
    @State private var newGig = ""
    @State private var rate = ""
    @State private var tax = ""
    @State private var costGig = ""
    @State private var cost = ""
    @State private var miles = ""
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                ForEach(v.gigs) { g in
                    Section {
                        LabeledContent("Earned", value: usd(g.recent.earned))
                        LabeledContent("Costs + miles", value: "−" + usd(g.recent.costs + g.recent.mileage) + (g.recent.miles > 0 ? " (\(String(format: "%.0f", g.recent.miles)) mi)" : ""))
                        LabeledContent("Kept", value: usd(g.recent.net)).font(.headline)
                        if let gh = g.recent.hourlyGross, let nh = g.recent.hourlyNet {
                            LabeledContent("Per hour", value: "\(usd(gh)) before, \(usd(nh)) after costs").foregroundStyle(nh < gh * 0.7 ? Theme.gold : Theme.ink)
                        }
                        Text("This year: \(usd(g.year.net)) kept of \(usd(g.year.earned))").font(.caption2).foregroundStyle(.secondary)
                    } header: { Text("\(g.source) · last \(v.days) days") }
                }
                Section {
                    LabeledContent("Gig profit this year", value: usd(v.yearProfit))
                    if let t = v.taxSetAside { LabeledContent("Set aside (\(String(format: "%.0f", v.taxPct ?? 0))%)", value: usd(t)).font(.headline) }
                    TextField("Percent to set aside", text: $tax).keyboardType(.decimalPad)
                    TextField("Your mileage rate ($ a mile)", text: $rate).keyboardType(.decimalPad)
                    Button("Save") { Task { await run { try await $0.saveMoneySettings(["tax_pct": num(tax), "mileage_rate": num(rate)]) } } }
                } header: { Text("Tax set-aside") } footer: { Text(v.note) }
                Section {
                    Picker("Gig", selection: $costGig) { ForEach(v.gigs) { Text($0.source).tag($0.source) } }
                    TextField("Cost (gas, supplies, fees)", text: $cost).keyboardType(.decimalPad)
                    TextField("Miles", text: $miles).keyboardType(.decimalPad)
                    Button("Log for today") { Task { await logCost() } }.disabled(costGig.isEmpty || (num(cost) == nil && num(miles) == nil))
                } header: { Text("Log a cost or miles") }
                if !v.costs.isEmpty {
                    Section("Recent costs") {
                        ForEach(v.costs) { c in
                            LabeledContent("\(c.source) · \(shortDay(c.day))", value: [c.amount > 0 ? usd(c.amount) : nil, c.miles > 0 ? "\(String(format: "%.0f", c.miles)) mi" : nil].compactMap { $0 }.joined(separator: " · "))
                                .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeGigCost(c.id) } } } label: { Label("Delete", systemImage: "trash") } }
                        }
                    }
                }
            }
            Section {
                ForEach(settings?.gigSources ?? [], id: \.self) { g in
                    Text(g).swipeActions { Button(role: .destructive) { Task { await setGigs((settings?.gigSources ?? []).filter { $0 != g }) } } label: { Label("Remove", systemImage: "trash") } }
                }
                HStack {
                    TextField("Income source that's a gig (DoorDash)", text: $newGig)
                    Button("Add") { Task { await setGigs((settings?.gigSources ?? []) + [newGig.trimmingCharacters(in: .whitespaces)]); newGig = "" } }
                        .disabled(newGig.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            } header: { Text("Your gigs") } footer: { Text("Use the same name you log income under (Money → Income), so earnings and costs line up.") }
        }
        .navigationTitle("Side gigs")
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        await s.load(app) { try await $0.gigs() }
        settings = try? await app.api?.moneySettings()
        if tax.isEmpty { tax = settings?.taxPct.map { String(format: "%.0f", $0) } ?? "" }
        if rate.isEmpty { rate = settings?.mileageRate.map { String(format: "%.2f", $0) } ?? "" }
        if costGig.isEmpty { costGig = s.value?.gigs.first?.source ?? "" }
    }
    private func setGigs(_ g: [String]) async { await run { try await $0.saveMoneySettings(["gig_sources": g]) } }
    private func logCost() async {
        await run { try await $0.logGigCost(source: costGig, amount: num(cost), miles: num(miles)) }
        if error == nil { cost = ""; miles = "" }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.148 cashback

struct CashbackView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<Cashback>()
    @State private var card = ""
    @State private var amount = ""
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            Section("Log cashback or rewards") {
                TextField("Card nickname", text: $card)
                TextField("Amount", text: $amount).keyboardType(.decimalPad)
                Button("Log for today") { Task { await log() } }.disabled(card.trimmingCharacters(in: .whitespaces).isEmpty || num(amount) == nil)
            }
            if let v = s.value {
                Section {
                    LabeledContent("Earned in \(String(v.year))", value: usd(v.yearTotal)).font(.headline)
                    ForEach(v.byCard) { LabeledContent($0.card, value: usd($0.total)) }
                }
                Section("Entries") {
                    ForEach(v.entries) { e in
                        LabeledContent("\(e.card) · \(shortDay(e.day))", value: usd(e.amount))
                            .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeCashback(e.id) } } } label: { Label("Delete", systemImage: "trash") } }
                    }
                }
            }
        }
        .navigationTitle("Cashback")
        .task { await load() }
    }

    private func load() async { await s.load(app) { try await $0.cashback() } }
    private func log() async {
        guard let a = num(amount) else { return }
        await run { try await $0.logCashback(card: card.trimmingCharacters(in: .whitespaces), amount: a) }
        if error == nil { amount = "" }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.146 unclaimed money checklist

struct ChecklistView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<MoneyChecklist>()

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    ForEach(v.items) { i in
                        HStack(alignment: .top) {
                            Button { Task { await toggle(i) } } label: {
                                Image(systemName: i.doneAt != nil ? "checkmark.circle.fill" : "circle").foregroundStyle(i.doneAt != nil ? Theme.ok : .secondary)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel(i.doneAt != nil ? "Done" : "Not done")
                            VStack(alignment: .leading, spacing: 3) {
                                Text(i.title).font(.subheadline.bold())
                                Text(i.detail).font(.caption).foregroundStyle(.secondary)
                                if let u = i.url, let url = URL(string: u) { Link(url.host() ?? u, destination: url).font(.caption) }
                            }
                        }
                    }
                } footer: { Text(v.note) }
            }
        }
        .navigationTitle("Unclaimed money")
        .task { await s.load(app) { try await $0.moneyChecklist() } }
    }

    private func toggle(_ i: MoneyChecklist.Item) async {
        guard let api = app.api else { return }
        try? await api.checkItem(i.key, done: i.doneAt == nil)
        await s.load(app) { try await $0.moneyChecklist() }
    }
}

// MARK: - V6.149 emergency fund

struct EmergencyView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<EmergencyFund>()
    @State private var goals: [SavingsGoal] = []

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            Section {
                Picker("Emergency fund goal", selection: Binding(get: { s.value?.goalId }, set: { id in Task { await pick(id) } })) {
                    Text("None").tag(String?.none)
                    ForEach(goals) { Text($0.name).tag(Optional($0.id)) }
                }
            } footer: { if goals.isEmpty { Text("Make a savings goal first (Money → Savings).") } }
            if let v = s.value, v.goalId != nil {
                Section {
                    VStack(alignment: .leading) {
                        Text(v.monthsCovered.map { String(format: "%.1f months", $0) } ?? "—").font(.largeTitle.bold()).foregroundStyle((v.monthsCovered ?? 0) >= 3 ? Theme.ok : Theme.gold)
                        Text("of bills and spending covered").font(.caption).foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    ProgressView(value: min((v.monthsCovered ?? 0) / 6, 1)).tint(Theme.ok).accessibilityLabel("Progress toward six months")
                    LabeledContent("Saved", value: usd(v.saved))
                    LabeledContent("A month of bills", value: usd(v.monthlyBills))
                    LabeledContent("A month of spending", value: usd(v.monthlySpending))
                    if let a = v.for3Months, a > 0 { LabeledContent("To reach 3 months", value: usd(a)) }
                    if let a = v.for6Months, a > 0 { LabeledContent("To reach 6 months", value: usd(a)) }
                } footer: { Text(v.note + " Spending is your average over the last 90 days of what you logged.") }
            }
        }
        .navigationTitle("Emergency fund")
        .task { await load() }
    }

    private func load() async {
        await s.load(app) { try await $0.emergencyFund() }
        goals = (try? await app.api?.savingsGoals()) ?? goals
    }
    private func pick(_ id: String?) async {
        try? await app.api?.saveMoneySettings(["emergency_goal_id": id])
        await load()
    }
}

// MARK: - V6.150 net worth

struct NetWorthView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<NetWorth>()
    @State private var name = ""
    @State private var value = ""
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    VStack(alignment: .leading) {
                        Text(usd(v.net)).font(.largeTitle.bold().monospacedDigit()).foregroundStyle(v.net < 0 ? Theme.bad : Theme.ok)
                        Text("\(usd(v.assets)) owned − \(usd(v.debts)) owed").font(.caption).foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    if v.snapshots.count >= 2 {
                        Chart(v.snapshots) { x in LineMark(x: .value("Day", x.day), y: .value("Net worth", x.net)).foregroundStyle(Theme.ok) }
                            .frame(height: 140).accessibilityLabel("Net worth over time")
                    }
                    Button { Task { await run { try await $0.snapshotNetWorth() } } } label: { Label("Save today's snapshot", systemImage: "camera") }
                } footer: { Text("Save one a month to watch it move.") }
                Section("What you own") {
                    ForEach(v.own) { l in
                        LabeledContent(l.name + (l.kind == "account" ? " (balance)" : ""), value: usd(l.value))
                            .swipeActions { if let id = l.assetId { Button(role: .destructive) { Task { await run { try await $0.removeAsset(id) } } } label: { Label("Delete", systemImage: "trash") } } }
                    }
                    TextField("Something you own (car, equipment)", text: $name)
                    TextField("What it's worth", text: $value).keyboardType(.decimalPad)
                    Button("Add") { Task { await add() } }.disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || num(value) == nil)
                }
                Section("What you owe") {
                    if v.owe.isEmpty { Text("Debts and card balances you add show here.").font(.caption).foregroundStyle(.secondary) }
                    ForEach(v.owe) { LabeledContent($0.name, value: usd($0.value)) }
                }
            }
        }
        .navigationTitle("Net worth")
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async { await s.load(app) { try await $0.netWorth() } }
    private func add() async {
        guard let v = num(value) else { return }
        await run { try await $0.saveAsset(nil, name: name.trimmingCharacters(in: .whitespaces), value: v) }
        if error == nil { name = ""; value = "" }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.151 monthly review, V6.152 streak

struct MoneyReviewView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<MoneyReview>()
    @State private var monthOffset = 1  // 1 = last month

    var body: some View {
        List {
            Section {
                Stepper(value: $monthOffset, in: 0...23) { Text(s.value.map { monthName($0.month) } ?? "…") }
                    .onChange(of: monthOffset) { Task { await load() } }
            }
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    ForEach(v.highlights, id: \.self) { Text($0) }
                    if v.highlights.isEmpty { Text("Nothing logged this month.").foregroundStyle(.secondary) }
                }
                Section {
                    LabeledContent("Income", value: usd(v.income))
                    LabeledContent("Spending", value: usd(v.spending))
                    LabeledContent("Kept", value: usd(v.kept)).font(.headline).foregroundStyle(v.kept < 0 ? Theme.bad : Theme.ok)
                    if v.saved != 0 { LabeledContent("Toward savings", value: usd(v.saved)) }
                    if let nw = v.netWorthChange { LabeledContent("Net worth change", value: (nw >= 0 ? "+" : "") + usd(nw)) }
                }
                if let b = v.bills {
                    Section("Bills") {
                        LabeledContent("On time", value: "\(b.onTime)")
                        LabeledContent("Late", value: "\(b.late)")
                        LabeledContent("Missed", value: "\(b.missed)")
                    }
                }
                Section {
                    LabeledContent("On time in a row", value: "\(v.streak.current)")
                    LabeledContent("Best run", value: "\(v.streak.best)")
                } header: { Text("Streak") } footer: { Text("Counted from the days you marked bills paid.") }
            }
        }
        .navigationTitle("Monthly review")
        .task { await load() }
    }

    private func load() async {
        let d = Calendar(identifier: .gregorian).date(byAdding: .month, value: -monthOffset, to: .now) ?? .now
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.dateFormat = "yyyy-MM"
        let m = f.string(from: d)
        await s.load(app) { try await $0.moneyReview(month: m) }
    }
}

/// V6.151: a local notification on the 1st of each month at 9am (after quiet hours) to look at last month's review.
enum MonthlyReviewReminder {
    static let id = "money.monthly-review"
    static func schedule() {
        var c = DateComponents()
        c.day = 1
        c.hour = 9
        let content = UNMutableNotificationContent()
        content.title = "Your money review is ready"
        content.body = "Last month's income, spending and bills, in one place."
        content.sound = .default
        let req = UNNotificationRequest(identifier: id, content: content, trigger: UNCalendarNotificationTrigger(dateMatching: c, repeats: true))
        UNUserNotificationCenter.current().add(req)
    }
}
