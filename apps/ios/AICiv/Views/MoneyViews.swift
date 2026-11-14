import Charts
import SwiftUI
import UserNotifications

/// V6.113–V6.127 on the phone: one Money screen with your budget and payday planner, income, savings, subscriptions
/// and credit. Everything is worked out from what you type in; nothing is connected to a bank or moves money.

private func oops(_ error: Error) -> String { (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
private func usd(_ v: Double?) -> String { v.map { $0.formatted(.currency(code: "USD")) } ?? "varies" }
private func shortDay(_ iso: String) -> String {
    let f = DateFormatter()
    f.calendar = Calendar(identifier: .gregorian)
    f.dateFormat = "yyyy-MM-dd"
    return f.date(from: iso)?.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day()) ?? iso
}
private func isoDay(_ d: Date) -> String {
    let f = DateFormatter()
    f.calendar = Calendar(identifier: .gregorian)
    f.dateFormat = "yyyy-MM-dd"
    return f.string(from: d)
}

struct MoneyView: View {
    enum Part: String, CaseIterable, Identifiable {
        case plan = "Plan", income = "Income", savings = "Savings", subs = "Subscriptions", credit = "Credit"
        var id: String { rawValue }
    }
    @State private var part: Part = .plan

    var body: some View {
        VStack(spacing: 0) {
            Picker("Section", selection: $part) { ForEach(Part.allCases) { Text($0.rawValue).tag($0) } }
                .pickerStyle(.segmented).padding(.horizontal).padding(.vertical, 6)
            switch part {
            case .plan: PlanMoneyView()
            case .income: IncomeView()
            case .savings: SavingsView()
            case .subs: SubscriptionsView()
            case .credit: CreditView()
            }
        }
    }
}

// MARK: - budget, paydays and the planner (V6.114, V6.115, V6.117)

struct PlanMoneyView: View {
    @Environment(AppState.self) private var app
    @State private var budget: MonthBudget?
    @State private var planner: PayPlanner?
    @State private var schedules: [PaySchedule] = []
    @State private var adding = false
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let b = budget {
                Section {
                    LabeledContent("Income", value: usd(b.income))
                    if b.incomeExpected > 0 { Text("\(usd(b.incomeLogged)) logged + \(usd(b.incomeExpected)) expected from your pay schedule").font(.caption2).foregroundStyle(.secondary) }
                    LabeledContent("Bills", value: usd(b.bills) + (b.billsVary > 0 ? " + \(b.billsVary) that vary" : ""))
                    LabeledContent("Planned savings", value: usd(b.savingsPlan))
                    LabeledContent("Left to spend", value: usd(b.left)).font(.headline).foregroundStyle(b.left < 0 ? Theme.bad : Theme.ok)
                } header: { Text("This month · \(b.daysLeft) days left") } footer: {
                    Text("From the income, bills and savings plans you've entered. Bills that vary aren't counted in.")
                }
            }
            if let p = planner {
                Section {
                    if !p.hasSchedule { Text("Add when you get paid below to plan by payday. Until then, this shows the next four weeks.").font(.caption).foregroundStyle(.secondary) }
                    ForEach(p.periods) { per in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text("\(shortDay(per.from)) → \(shortDay(per.to))").font(.subheadline.bold())
                                Spacer()
                                if let left = per.left { Text("left \(usd(left))").font(.caption.bold()).foregroundStyle(left < 0 ? Theme.bad : Theme.ok) }
                            }
                            if per.bills.isEmpty { Text("No bills due").font(.caption).foregroundStyle(.secondary) }
                            ForEach(per.bills) { b in
                                HStack {
                                    Text(b.name + (b.autopay ? " (autopay)" : "") + (b.paid == true ? " · paid" : "")).font(.caption)
                                        .foregroundStyle(b.overdue ? Theme.bad : b.paid == true ? .secondary : Theme.ink)
                                    Spacer()
                                    Text("\(shortDay(b.due)) · \(usd(b.amount))").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                                }
                            }
                            Text("Needs \(usd(per.needed))" + (per.varies > 0 ? " + \(per.varies) that vary" : "") + (per.pay.map { " of \(usd($0)) pay" } ?? ""))
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                        .accessibilityElement(children: .combine)
                    }
                } header: { Text("Payday planner") }
            }
            Section {
                ForEach(schedules) { s in
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(s.name) · \(label(s.cadence))\(s.amount.map { " · \(usd($0))" } ?? "")").font(.subheadline)
                        Text("Next: " + s.next.prefix(3).map(shortDay).joined(separator: ", ")).font(.caption2).foregroundStyle(.secondary)
                    }
                    .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removePaySchedule(s.id) } } } label: { Label("Delete", systemImage: "trash") } }
                }
                Button { adding = true } label: { Label("Add when you get paid", systemImage: "plus") }
            } header: { Text("Paydays") }
        }
        .sheet(isPresented: $adding) { PayScheduleEditor { await load() }.presentationDetents([.medium]) }
        .task { await load() }
        .refreshable { await load() }
    }

    private func label(_ c: String) -> String {
        ["weekly": "weekly", "biweekly": "every 2 weeks", "semimonthly": "15th and last day", "monthly": "monthly"][c] ?? c
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac first."; return }
        do {
            budget = try await api.budget()
            planner = try await api.planner()
            schedules = try await api.paySchedules()
            error = nil
        } catch { self.error = oops(error) }
    }

    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); await load() } catch { self.error = oops(error) }
    }
}

struct PayScheduleEditor: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let saved: () async -> Void
    @State private var name = "Paycheck"
    @State private var cadence = "biweekly"
    @State private var day = Date()
    @State private var amount = ""
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                TextField("Name", text: $name)
                Picker("How often", selection: $cadence) {
                    Text("Every week").tag("weekly"); Text("Every 2 weeks").tag("biweekly")
                    Text("15th and last day").tag("semimonthly"); Text("Monthly").tag("monthly")
                }
                DatePicker("A recent payday", selection: $day, displayedComponents: .date)
                TextField("Usual amount (optional)", text: $amount).keyboardType(.decimalPad)
                if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            }
            .navigationTitle("When you get paid").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { Task { await save() } } }
            }
        }
    }

    private func save() async {
        guard let api = app.api else { return }
        let a = amount.replacingOccurrences(of: ",", with: "").replacingOccurrences(of: "$", with: "").trimmingCharacters(in: .whitespaces)
        if !a.isEmpty && Double(a) == nil { error = "The amount is a number like 1250."; return }
        do { try await api.addPaySchedule(name: name, cadence: cadence, anchorDay: isoDay(day), amount: Double(a)); await saved(); dismiss() }
        catch { self.error = oops(error) }
    }
}

// MARK: - income (V6.113)

struct IncomeView: View {
    @Environment(AppState.self) private var app
    @State private var s: IncomeSummary?
    @State private var amount = ""
    @State private var source = ""
    @State private var hours = ""
    @State private var error: String?

    var body: some View {
        List {
            Section {
                TextField("Amount", text: $amount).keyboardType(.decimalPad)
                TextField("From (rideshare, paycheck, side job)", text: $source)
                TextField("Hours (optional)", text: $hours).keyboardType(.decimalPad)
                Button { Task { await log() } } label: { Label("Log it for today", systemImage: "plus.circle.fill") }
                    .disabled(Double(amount) == nil || source.trimmingCharacters(in: .whitespaces).isEmpty)
            } header: { Text("Log income") }
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let s {
                Section {
                    LabeledContent("This week", value: usd(s.weekTotal) + (s.weekHourly.map { " · \(usd($0))/hr" } ?? ""))
                    LabeledContent("This month", value: usd(s.monthTotal) + (s.monthHourly.map { " · \(usd($0))/hr" } ?? ""))
                    Chart(s.weeks) { w in BarMark(x: .value("Week", shortDay(w.weekStart)), y: .value("Income", w.total)).foregroundStyle(Theme.ok) }
                        .frame(height: 140)
                        .accessibilityLabel("Income for the last eight weeks")
                } footer: { Text("Hourly is what you logged divided by the hours you logged, before any costs.") }
                if !s.bySource.isEmpty {
                    Section("This month by source") {
                        ForEach(s.bySource) { x in LabeledContent(x.source, value: usd(x.total) + (x.hourly.map { " · \(usd($0))/hr" } ?? "")) }
                    }
                }
                Section("Entries") {
                    ForEach(s.entries) { e in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(e.source).font(.subheadline)
                                Text(shortDay(e.day) + (e.hours.map { String(format: " · %.1f h", $0) } ?? "")).font(.caption2).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(usd(e.amount)).font(.subheadline.monospacedDigit())
                        }
                        .swipeActions { Button(role: .destructive) { Task { await remove(e.id) } } label: { Label("Delete", systemImage: "trash") } }
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac first."; return }
        do { s = try await api.income(); error = nil } catch { self.error = oops(error) }
    }

    private func log() async {
        guard let api = app.api, let a = Double(amount) else { return }
        do {
            try await api.logIncome(amount: a, source: source.trimmingCharacters(in: .whitespaces), hours: Double(hours))
            amount = ""; hours = ""
            Haptics.success()
            await load()
        } catch { self.error = oops(error) }
    }

    private func remove(_ id: String) async {
        guard let api = app.api else { return }
        do { try await api.removeIncome(id); await load() } catch { self.error = oops(error) }
    }
}

// MARK: - savings goals (V6.116)

struct SavingsView: View {
    @Environment(AppState.self) private var app
    @State private var goals: [SavingsGoal] = []
    @State private var name = ""
    @State private var target = ""
    @State private var monthly = ""
    @State private var hasDeadline = false
    @State private var deadline = Calendar.current.date(byAdding: .month, value: 3, to: Date()) ?? Date()
    @State private var depositFor: SavingsGoal?
    @State private var depositText = ""
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            ForEach(goals) { g in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(g.name).font(.subheadline.bold())
                        Spacer()
                        Text("\(usd(g.saved)) of \(usd(g.target))").font(.caption.monospacedDigit())
                    }
                    ProgressView(value: g.progress).tint(g.done ? Theme.ok : Theme.gold)
                    Group {
                        if g.done { Text("Reached 🎉") }
                        else if let w = g.perWeekNeeded, let d = g.deadline { Text("\(usd(w)) a week reaches it by \(shortDay(d))") }
                        else if g.pastDeadline { Text("The deadline passed with \(usd(g.left)) to go") }
                        else { Text("\(usd(g.left)) to go") }
                    }
                    .font(.caption2).foregroundStyle(g.pastDeadline ? Theme.bad : .secondary)
                    Button("Record a deposit") { depositFor = g; depositText = "" }.font(.caption).buttonStyle(.bordered)
                }
                .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeSavingsGoal(g.id) } } } label: { Label("Delete", systemImage: "trash") } }
            }
            Section {
                TextField("Goal (Emergency fund, new laptop)", text: $name)
                TextField("Target amount", text: $target).keyboardType(.decimalPad)
                TextField("Plan to save each month (optional)", text: $monthly).keyboardType(.decimalPad)
                Toggle("By a date", isOn: $hasDeadline)
                if hasDeadline { DatePicker("Deadline", selection: $deadline, in: Date()..., displayedComponents: .date) }
                Button("Add goal") { Task { await add() } }.disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || Double(target) == nil)
            } header: { Text("New goal") } footer: {
                Text("You move the money (to savings, wherever you keep it) and record it here. Monthly plans count in the budget.")
            }
        }
        .alert("Record a deposit", isPresented: Binding(get: { depositFor != nil }, set: { if !$0 { depositFor = nil } })) {
            TextField("Amount (negative to take some out)", text: $depositText).keyboardType(.numbersAndPunctuation)
            Button("Save") {
                if let g = depositFor, let a = Double(depositText), a != 0 {
                    Task { guard let api = app.api else { return }; do { goals = try await api.deposit(g.id, amount: a); Haptics.success() } catch { self.error = oops(error) } }
                }
                depositFor = nil
            }
            Button("Cancel", role: .cancel) { depositFor = nil }
        } message: { Text(depositFor?.name ?? "") }
        .task { await load() }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac first."; return }
        do { goals = try await api.savingsGoals(); error = nil } catch { self.error = oops(error) }
    }

    private func add() async {
        guard let api = app.api, let t = Double(target) else { return }
        do {
            try await api.addSavingsGoal(name: name, target: t, deadline: hasDeadline ? isoDay(deadline) : nil, monthlyPlan: Double(monthly))
            name = ""; target = ""; monthly = ""
            await load()
        } catch { self.error = oops(error) }
    }

    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); await load() } catch { self.error = oops(error) }
    }
}

// MARK: - subscriptions (V6.118) and finding savings (V6.119)

struct SubscriptionsView: View {
    @Environment(AppState.self) private var app
    @State private var subs: Subscriptions?
    @State private var bills: [Bill] = []
    @State private var note: String?
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let note { Text(note).foregroundStyle(Theme.ok).font(.caption) }
            if let s = subs {
                Section {
                    if s.subscriptions.isEmpty { Text("Mark which bills are subscriptions below.").foregroundStyle(.secondary) }
                    ForEach(s.subscriptions) { x in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(x.name).font(.subheadline.bold())
                                Spacer()
                                Text("\(usd(x.yearly))/yr").font(.caption.monospacedDigit())
                            }
                            HStack {
                                Text(x.reviewDue ? "Not reviewed in 3 months" : "Reviewed recently").font(.caption2)
                                    .foregroundStyle(x.reviewDue ? Theme.gold : .secondary)
                                Spacer()
                                Button("Still worth it") { Task { await act { _ = try await $0.setSubscription(x.billId, reviewed: true) } } }
                                    .font(.caption).buttonStyle(.bordered)
                                Button("Find cheaper") { Task { await findSavings(x.billId, x.name) } }.font(.caption).buttonStyle(.bordered)
                            }
                        }
                    }
                } header: { Text("Subscriptions · \(usd(s.yearlyTotal)) a year") } footer: {
                    Text("Find cheaper adds a research task for the agents. It only runs if you press Do it on it, with its budget; nothing is cancelled or bought.")
                }
            }
            Section("Which bills are subscriptions?") {
                ForEach(bills) { b in
                    Toggle(b.name, isOn: Binding(get: { b.subscription ?? false }, set: { on in Task { await act { _ = try await $0.setSubscription(b.id, on: on) } } }))
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac first."; return }
        do { subs = try await api.subscriptions(); bills = try await api.bills(); error = nil } catch { self.error = oops(error) }
    }

    private func act(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); await load() } catch { self.error = oops(error) }
    }

    private func findSavings(_ id: String, _ name: String) async {
        guard let api = app.api else { return }
        do { let t = try await api.findSavings(id); note = "Added \"\(t.title)\" to your list. Open it and press Do it if you want the agents to look."; Haptics.success() }
        catch { self.error = oops(error) }
    }
}

// MARK: - credit utilization (V6.120) and the on-time record (V6.121)

struct CreditView: View {
    @Environment(AppState.self) private var app
    @State private var c: CreditHealth?
    @State private var editing: CardDraft?
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let c {
                Section {
                    if let u = c.utilization {
                        LabeledContent("Overall utilization", value: "\(Int((u * 100).rounded()))%").font(.headline)
                            .foregroundStyle(u > 0.3 ? Theme.gold : Theme.ok)
                        Text("\(usd(c.totalBalance)) of \(usd(c.totalLimit))").font(.caption).foregroundStyle(.secondary)
                    } else { Text("Add your cards' limits and balances (no card numbers).").foregroundStyle(.secondary) }
                    ForEach(c.cards) { card in
                        VStack(alignment: .leading, spacing: 4) {
                            HStack {
                                Text(card.name).font(.subheadline.bold())
                                Spacer()
                                Text("\(Int((card.utilization * 100).rounded()))% · \(card.band)").font(.caption)
                            }
                            ProgressView(value: min(1, card.utilization)).tint(card.utilization > 0.3 ? Theme.gold : Theme.ok)
                            Text("\(usd(card.balance)) of \(usd(card.limit))" + (card.nextStatement.map { " · statement \(shortDay($0))" } ?? ""))
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                        .contentShape(Rectangle())
                        .onTapGesture { editing = CardDraft(card) }
                        .swipeActions { Button(role: .destructive) { Task { await remove(card.id) } } label: { Label("Delete", systemImage: "trash") } }
                    }
                    Button { editing = CardDraft() } label: { Label("Add a card", systemImage: "plus") }
                } header: { Text("Utilization") } footer: { Text(c.note) }
                Section {
                    if let r = c.record.onTimeRate {
                        LabeledContent("Bills paid on time", value: "\(Int((r * 100).rounded()))%")
                    }
                    Chart(c.record.months) { m in
                        BarMark(x: .value("Month", String(m.month.suffix(2))), y: .value("Bills", m.onTime)).foregroundStyle(by: .value("Kind", "On time"))
                        BarMark(x: .value("Month", String(m.month.suffix(2))), y: .value("Bills", m.late)).foregroundStyle(by: .value("Kind", "Late"))
                        BarMark(x: .value("Month", String(m.month.suffix(2))), y: .value("Bills", m.missed)).foregroundStyle(by: .value("Kind", "Missed"))
                    }
                    .chartForegroundStyleScale(["On time": Theme.ok, "Late": Theme.gold, "Missed": Theme.bad])
                    .frame(height: 150)
                    .accessibilityLabel("\(c.record.onTime) on time, \(c.record.late) late, \(c.record.missed) missed over 12 months")
                } header: { Text("Your on-time record") } footer: {
                    Text("From the days you marked bills paid. When you mark a bill paid, you can pick the day you actually paid it.")
                }
            }
        }
        .sheet(item: $editing) { d in CardEditor(draft: d) { await load() }.presentationDetents([.medium]) }
        .task { await load() }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac first."; return }
        do {
            let h = try await api.credit()
            c = h
            CreditReminders.sync(h.cards)
            error = nil
        } catch { self.error = oops(error) }
    }

    private func remove(_ id: String) async {
        guard let api = app.api else { return }
        do { try await api.removeCard(id); await load() } catch { self.error = oops(error) }
    }
}

struct CardDraft: Identifiable {
    var id = UUID()
    var cardId: String?
    var name = ""
    var limit = ""
    var balance = ""
    var statementDay = 0
    init() {}
    init(_ c: CreditCardInfo) {
        cardId = c.id; name = c.name; limit = String(format: "%.2f", c.limit); balance = String(format: "%.2f", c.balance)
        statementDay = c.statementDay ?? 0
    }
}

struct CardEditor: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State var draft: CardDraft
    let saved: () async -> Void
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                TextField("Nickname (no card number)", text: $draft.name)
                TextField("Credit limit", text: $draft.limit).keyboardType(.decimalPad)
                TextField("Current balance", text: $draft.balance).keyboardType(.decimalPad)
                Picker("Statement closes on", selection: $draft.statementDay) {
                    Text("Not set").tag(0)
                    ForEach(1...31, id: \.self) { Text("Day \($0)").tag($0) }
                }
                if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            }
            .navigationTitle(draft.cardId == nil ? "New card" : "Edit card").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { Task { await save() } } }
            }
        }
    }

    private func save() async {
        guard let api = app.api else { return }
        guard let l = Double(draft.limit.replacingOccurrences(of: ",", with: "")) else { error = "The limit is a number like 2500."; return }
        let b = Double(draft.balance.replacingOccurrences(of: ",", with: "")) ?? 0
        do {
            try await api.saveCard(draft.cardId, name: draft.name, limit: l, balance: b, statementDay: draft.statementDay == 0 ? nil : draft.statementDay)
            await saved()
            dismiss()
        } catch { self.error = oops(error) }
    }
}

/// A reminder two days before each card's statement closes (9 AM, shifted out of quiet hours).
enum CreditReminders {
    static let prefix = "card-"

    static func sync(_ cards: [CreditCardInfo]) {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.dateFormat = "yyyy-MM-dd"
        let now = Date()
        var wanted: [(String, CreditCardInfo, Date)] = []
        for c in cards {
            guard let s = c.nextStatement, let d = f.date(from: s),
                  let day = Calendar.current.date(byAdding: .day, value: -2, to: d),
                  let at = Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: day) else { continue }
            let when = QuietHours.adjust(at)
            if when > now { wanted.append(("\(prefix)\(c.id)-\(s)", c, when)) }
        }
        let center = UNUserNotificationCenter.current()
        center.getPendingNotificationRequests { pending in
            let have = Set(pending.map(\.identifier).filter { $0.hasPrefix(prefix) })
            center.removePendingNotificationRequests(withIdentifiers: Array(have.subtracting(wanted.map(\.0))))
            for (id, c, at) in wanted where !have.contains(id) {
                let n = UNMutableNotificationContent()
                n.title = "\(c.name) statement closes in 2 days"
                n.body = "Balance you entered: \(usd(c.balance)) of \(usd(c.limit)) (\(Int((c.utilization * 100).rounded()))%)."
                n.sound = .default
                n.threadIdentifier = "credit"
                let parts = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: at)
                center.add(UNNotificationRequest(identifier: id, content: n, trigger: UNCalendarNotificationTrigger(dateMatching: parts, repeats: false)))
            }
        }
    }
}

// MARK: - quiet hours (V6.125)

/// No reminders between two times you choose; one that would land inside arrives when quiet hours end.
enum QuietHours {
    static let onKey = "quietOn"
    static let startKey = "quietStart"   // minutes after midnight
    static let endKey = "quietEnd"

    static var on: Bool { UserDefaults.standard.bool(forKey: onKey) }
    static var start: Int { (UserDefaults.standard.object(forKey: startKey) as? Int) ?? 22 * 60 }
    static var end: Int { (UserDefaults.standard.object(forKey: endKey) as? Int) ?? 7 * 60 }

    /// `date`, or the end of quiet hours if it falls inside them.
    static func adjust(_ date: Date, cal: Calendar = .current) -> Date {
        guard on, start != end else { return date }
        let c = cal.dateComponents([.hour, .minute], from: date)
        let m = (c.hour ?? 0) * 60 + (c.minute ?? 0)
        let inside = start < end ? (m >= start && m < end) : (m >= start || m < end)
        guard inside else { return date }
        var day = cal.startOfDay(for: date)
        if start > end && m >= start { day = cal.date(byAdding: .day, value: 1, to: day) ?? day }  // past midnight: tomorrow
        return cal.date(byAdding: .minute, value: end, to: day) ?? date
    }
}

struct QuietHoursSettings: View {
    @AppStorage(QuietHours.onKey) private var on = false
    @AppStorage(QuietHours.startKey) private var start = 22 * 60
    @AppStorage(QuietHours.endKey) private var end = 7 * 60

    private func binding(_ v: Binding<Int>) -> Binding<Date> {
        Binding(get: { Calendar.current.startOfDay(for: Date()).addingTimeInterval(TimeInterval(v.wrappedValue * 60)) },
                set: { d in let c = Calendar.current.dateComponents([.hour, .minute], from: d); v.wrappedValue = (c.hour ?? 0) * 60 + (c.minute ?? 0) })
    }

    var body: some View {
        Section {
            Toggle("Quiet hours", isOn: $on)
            if on {
                DatePicker("From", selection: binding($start), displayedComponents: .hourAndMinute)
                DatePicker("Until", selection: binding($end), displayedComponents: .hourAndMinute)
            }
        } footer: { Text("Task, bill, card and follow-up reminders that would land in these hours come when they end. Reminders already set move the next time the app updates them.") }
    }
}

// MARK: - the Home money card (V6.123)

struct MoneyCard: View {
    @Environment(AppState.self) private var app
    @State private var o: MoneyOverview?

    var body: some View {
        Group {
            if let o {
                VStack(alignment: .leading, spacing: 6) {
                    PixelHeader(text: "Money", color: Theme.ok, trailing: o.nextPayday.map { "payday \(shortDay($0))" })
                    HStack(spacing: 14) {
                        VStack(alignment: .leading) {
                            Text(usd(o.incomeThisWeek)).font(.headline.monospacedDigit())
                            Text("earned this week").font(.caption2).foregroundStyle(.secondary)
                        }
                        VStack(alignment: .leading) {
                            Text(usd(o.billsDueSoonTotal)).font(.headline.monospacedDigit()).foregroundStyle(o.billsDueSoon.contains { $0.overdue } ? Theme.bad : Theme.ink)
                            Text("bills in 7 days").font(.caption2).foregroundStyle(.secondary)
                        }
                    }
                    ForEach(o.billsDueSoon.prefix(3)) { b in
                        Text("\(b.name) · \(b.overdue ? "past due" : shortDay(b.due)) · \(usd(b.amount))\(b.autopay ? " · autopay" : "")")
                            .font(.caption).foregroundStyle(b.overdue ? Theme.bad : .secondary)
                    }
                    ForEach(o.savings) { g in
                        HStack {
                            Text(g.name).font(.caption)
                            ProgressView(value: g.progress).tint(Theme.gold)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .pixelPanel(Theme.ok.opacity(0.35))
                .accessibilityElement(children: .combine)
            }
        }
        .task(id: app.connection == .live) {
            guard app.connection == .live, let api = app.api else { return }
            o = try? await api.moneyOverview()
            if let o, o.billsDueSoon.isEmpty, o.incomeThisWeek == 0, o.savings.isEmpty { self.o = nil }  // nothing set up yet: no card
        }
    }
}
