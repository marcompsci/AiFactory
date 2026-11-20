import Charts
import LocalAuthentication
import SwiftUI
import UserNotifications

/// V6.158–V6.187 on the phone: the assistant section of Money → More (to-dos, the week, can I afford it, setup) plus
/// paying on time, credit watch and earning-and-keeping tools. From numbers you type in; nothing moves money and none
/// of it is financial, tax or credit advice.

private func oops(_ error: Error) -> String { (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
private func usd(_ v: Double?) -> String { v.map { $0.formatted(.currency(code: "USD")) } ?? "varies" }
private func num(_ s: String) -> Double? { Double(s.replacingOccurrences(of: ",", with: "").replacingOccurrences(of: "$", with: "").trimmingCharacters(in: .whitespaces)) }
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
private func isoDay(_ d: Date) -> String {
    let f = DateFormatter()
    f.calendar = Calendar(identifier: .gregorian)
    f.dateFormat = "yyyy-MM-dd"
    return f.string(from: d)
}

/// The rows Money → More adds for this round.
struct MoneyAssistantSections: View {
    var body: some View {
        Section {
            NavigationLink { MoneyTodosView() } label: { Label("What to do next", systemImage: "list.bullet.clipboard") }
            NavigationLink { WeeklyCheckInView() } label: { Label("This week", systemImage: "calendar") }
            NavigationLink { AffordView() } label: { Label("Can I afford it?", systemImage: "questionmark.circle") }
            NavigationLink { MoneySetupView() } label: { Label("Setup checklist", systemImage: "checklist") }
        } header: { Text("Assistant") }
        Section {
            NavigationLink { PasteBillView() } label: { Label("Paste a bill", systemImage: "doc.on.clipboard") }
            NavigationLink { MoneyForecastView() } label: { Label("30-day forecast", systemImage: "chart.xyaxis.line") }
            NavigationLink { DueDateMovesView() } label: { Label("Move a due date", systemImage: "calendar.badge.clock") }
            NavigationLink { SetAsidesView() } label: { Label("Set-asides for yearly bills", systemImage: "tray.and.arrow.down") }
        } header: { Text("Paying on time") }
        Section {
            NavigationLink { CreditWatchView() } label: { Label("Credit reports, freezes and disputes", systemImage: "shield.lefthalf.filled") }
            NavigationLink { CreditHabitsView() } label: { Label("Credit habits", systemImage: "checkmark.seal") }
        } header: { Text("Credit") }
        Section {
            NavigationLink { IncomeGoalView() } label: { Label("Income goal and best days", systemImage: "target") }
            NavigationLink { WinsView() } label: { Label("Money you've saved", systemImage: "trophy") }
            NavigationLink { SellingView() } label: { Label("Things to sell", systemImage: "tag") }
            NavigationLink { OwedView() } label: { Label("Money owed to you", systemImage: "arrow.down.circle") }
            NavigationLink { KeepMoreView() } label: { Label("Round-ups and no-spend days", systemImage: "leaf") }
            NavigationLink { ProjectionsView() } label: { Label("When you'll reach your goals", systemImage: "flag.checkered") }
        } header: { Text("Earn and keep more") }
        Section {
            ExportMoneyRow()
            MoneyLockToggle()
        } header: { Text("Your data") }
    }
}

// MARK: - V6.180 to-dos

struct MoneyTodosView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<MoneyTodos>()

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                if v.items.isEmpty { Label("Nothing needs you right now.", systemImage: "checkmark.circle").foregroundStyle(Theme.ok) }
                ForEach(v.items) { i in
                    NavigationLink { destination(i.destination) } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 6) {
                                Circle().fill(i.rank == 0 ? Theme.bad : i.rank <= 2 ? Theme.gold : .secondary).frame(width: 8, height: 8).accessibilityHidden(true)
                                Text(i.title).font(.subheadline.bold())
                            }
                            Text(i.detail).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle("What to do next")
        .task { await s.load(app) { try await $0.moneyTodos() } }
        .refreshable { await s.load(app) { try await $0.moneyTodos() } }
    }

    @ViewBuilder private func destination(_ w: String) -> some View {
        switch w {
        case "safe": SafeToSpendView()
        case "checks": BillChecksView()
        case "forecast": MoneyForecastView()
        case "accounts": AccountsView()
        case "paydown": PaydownView()
        case "credit": CreditWatchView()
        case "owed": OwedView()
        case "moves": DueDateMovesView()
        case "subs", "plan", "bills": MoneyView()
        default: MoneyMoreView()
        }
    }
}

// MARK: - V6.179 weekly check-in

struct WeeklyCheckInView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<WeeklyCheckIn>()

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    if v.bills.isEmpty { Text("No bills in the next 7 days.").foregroundStyle(.secondary) }
                    ForEach(v.bills) { b in
                        LabeledContent(b.name + (b.autopay ? " (autopay)" : ""), value: "\(b.overdue ? "past due" : shortDay(b.due)) · \(usd(b.amount))")
                            .foregroundStyle(b.overdue ? Theme.bad : Theme.ink)
                    }
                } header: { Text("Bills this week · \(usd(v.billsTotal))") }
                Section {
                    if let s = v.safePerDay { LabeledContent("Safe to spend", value: "\(usd(s)) a day") }
                    if let g = v.incomeGoal.goal { LabeledContent("Income goal", value: "\(usd(v.incomeGoal.earned)) of \(usd(g))") }
                    if v.owedToYou > 0 { LabeledContent("Owed to you", value: usd(v.owedToYou)) }
                }
                if !v.todos.isEmpty {
                    Section("Top to-dos") { ForEach(v.todos) { t in VStack(alignment: .leading) { Text(t.title).font(.subheadline); Text(t.detail).font(.caption2).foregroundStyle(.secondary) } } }
                }
            }
        }
        .navigationTitle("This week")
        .task { await s.load(app) { try await $0.weeklyCheckIn() } }
    }
}

/// V6.179: a local reminder every Sunday at 6pm to look at the week ahead.
enum WeeklyCheckInReminder {
    static func schedule() {
        var c = DateComponents()
        c.weekday = 1
        c.hour = 18
        let content = UNMutableNotificationContent()
        content.title = "Your money week ahead"
        content.body = "Bills due this week, safe to spend, and what to do next."
        content.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: "money.weekly", content: content,
                                                                     trigger: UNCalendarNotificationTrigger(dateMatching: c, repeats: true)))
    }
}

// MARK: - V6.181 can I afford it?

struct AffordView: View {
    @Environment(AppState.self) private var app
    @State private var amount = ""
    @State private var r: Affordability?
    @State private var error: String?

    var body: some View {
        List {
            Section {
                TextField("How much?", text: $amount).keyboardType(.decimalPad)
                Button("Check") { Task { await check() } }.disabled((num(amount) ?? 0) <= 0)
            } footer: { Text("Checks the price against what's safe to spend before payday and your 30-day forecast.") }
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let r {
                if !r.ready { Text(r.reason ?? "").font(.callout) } else {
                    Section {
                        Label(r.verdict == "fits" ? "It fits" : r.verdict == "tight" ? "It's tight" : "It doesn't fit right now",
                              systemImage: r.verdict == "fits" ? "checkmark.circle.fill" : r.verdict == "tight" ? "exclamationmark.circle.fill" : "xmark.circle.fill")
                            .font(.title3.bold()).foregroundStyle(r.verdict == "fits" ? Theme.ok : r.verdict == "tight" ? Theme.gold : Theme.bad)
                        Text(r.why ?? "")
                        LabeledContent("Per day until payday", value: "\(usd(r.perDayBefore)) → \(usd(r.perDayAfter))")
                        if let low = r.lowAfter { LabeledContent("Lowest forecast day after", value: usd(low)).foregroundStyle(low < 0 ? Theme.bad : Theme.ink) }
                    } footer: { Text((r.note ?? "") + " Whether to buy it is your call.") }
                }
            }
        }
        .navigationTitle("Can I afford it?")
    }

    private func check() async {
        guard let api = app.api, let a = num(amount) else { return }
        do { r = try await api.afford(a); error = nil } catch { self.error = oops(error) }
    }
}

// MARK: - V6.185 setup checklist

struct MoneySetupView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<MoneySetup>()

    var body: some View {
        List {
            if let v = s.value {
                Section {
                    ProgressView(value: Double(v.done), total: Double(max(v.total, 1))).tint(Theme.ok)
                        .accessibilityLabel("\(v.done) of \(v.total) steps done")
                    ForEach(v.steps) { st in
                        Label(st.title, systemImage: st.done ? "checkmark.circle.fill" : "circle").foregroundStyle(st.done ? Theme.ok : Theme.ink)
                    }
                } header: { Text("\(v.done) of \(v.total) done") } footer: { Text("Each step makes the planner, safe to spend and the forecast more useful.") }
            }
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
        }
        .navigationTitle("Setup")
        .task { await s.load(app) { try await $0.moneySetup() } }
    }
}

// MARK: - V6.158 paste a bill

struct PasteBillView: View {
    @Environment(AppState.self) private var app
    @State private var text = ""
    @State private var parsed: ParsedBill?
    @State private var name = ""
    @State private var amount = ""
    @State private var dueDay = 1
    @State private var autopay = false
    @State private var cadence = "monthly"
    @State private var dueMonth = 1
    @State private var added = false
    @State private var error: String?

    var body: some View {
        Form {
            Section {
                TextEditor(text: $text).frame(minHeight: 140).accessibilityLabel("Bill text")
                HStack {
                    Button("Paste") { text = UIPasteboard.general.string ?? text }
                    Spacer()
                    Button("Read it") { Task { await parse() } }.disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            } header: { Text("Paste the bill's email or text") } footer: { Text("Read on your Mac; the text isn't saved. Account numbers are ignored.") }
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let p = parsed {
                Section {
                    TextField("Name", text: $name)
                    TextField("Amount (empty if it varies)", text: $amount).keyboardType(.decimalPad)
                    Stepper("Due on the \(dueDay)\(suffix(dueDay))", value: $dueDay, in: 1...31)
                    Toggle("Autopay", isOn: $autopay)
                    Picker("How often", selection: $cadence) { Text("Monthly").tag("monthly"); Text("Yearly").tag("yearly") }
                    if cadence == "yearly" { Stepper("In \(Calendar.current.monthSymbols[dueMonth - 1])", value: $dueMonth, in: 1...12) }
                    Button(added ? "Added" : "Add this bill") { Task { await add() } }.disabled(added || name.trimmingCharacters(in: .whitespaces).isEmpty)
                } header: { Text("Check before adding") } footer: { Text(p.note) }
            }
        }
        .navigationTitle("Paste a bill")
    }

    private func suffix(_ n: Int) -> String { (11...13).contains(n % 100) ? "th" : [1: "st", 2: "nd", 3: "rd"][n % 10] ?? "th" }

    private func parse() async {
        guard let api = app.api else { return }
        do {
            let p = try await api.parseBill(text)
            parsed = p; name = p.name; amount = p.amount.map { String(format: "%.2f", $0) } ?? ""; dueDay = p.dueDay ?? 1; autopay = p.autopay
            cadence = p.cadence; dueMonth = p.dueMonth ?? Calendar.current.component(.month, from: .now); added = false; error = nil
        } catch { self.error = oops(error) }
    }

    private func add() async {
        guard let api = app.api else { return }
        do {
            var f: [String: JSONValue] = ["name": .string(name.trimmingCharacters(in: .whitespaces)), "due_day": .number(Double(dueDay)),
                                          "autopay": .bool(autopay), "cadence": .string(cadence), "tz": .string(TimeZone.current.identifier),
                                          "amount": num(amount).map { .number($0) } ?? .null]
            if cadence == "yearly" { f["due_month"] = .number(Double(dueMonth)) }
            _ = try await api.json("/api/bills", method: "POST", body: f)
            added = true
            Haptics.success()
        } catch { self.error = oops(error) }
    }
}

// MARK: - V6.163/V6.164 forecast

struct MoneyForecastView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<MoneyForecast>()

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                if !v.ready { Section { Text(v.reason ?? ""); NavigationLink("Add an account") { AccountsView() } } }
                if v.ready, let days = v.days, let low = v.low {
                    Section {
                        Chart(days) { d in
                            LineMark(x: .value("Day", d.day), y: .value("Balance", d.balance)).foregroundStyle(Theme.ok)
                            RuleMark(y: .value("Zero", 0)).foregroundStyle(Theme.bad.opacity(0.5))
                        }
                        .chartXAxis(.hidden)
                        .frame(height: 170)
                        .accessibilityLabel("Projected balance for 30 days; lowest \(usd(low.balance)) on \(shortDay(low.day))")
                        LabeledContent("Lowest day", value: "\(shortDay(low.day)) · \(usd(low.balance))").foregroundStyle(low.balance < 0 ? Theme.bad : Theme.ink)
                        if let z = v.belowZero, let first = z.first { Label("Below zero on \(z.count) day\(z.count == 1 ? "" : "s"), first \(shortDay(first))", systemImage: "exclamationmark.triangle.fill").foregroundStyle(Theme.bad) }
                        else if let b = v.belowBuffer, !b.isEmpty { Label("Under \(usd(v.buffer)) on \(b.count) day\(b.count == 1 ? "" : "s")", systemImage: "exclamationmark.circle").foregroundStyle(Theme.gold) }
                        LabeledContent("Average spending", value: "\(usd(v.dailySpending)) a day")
                    } footer: { Text(v.note) }
                    Section("Coming up") {
                        ForEach(days.filter { !$0.events.isEmpty }) { d in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack { Text(shortDay(d.day)).font(.subheadline.bold()); Spacer(); Text(usd(d.balance)).monospacedDigit().foregroundStyle(d.balance < 0 ? Theme.bad : .secondary) }
                                ForEach(Array(d.events.enumerated()), id: \.offset) { _, e in
                                    Text("\(e.kind == "pay" ? "+" : "−") \(e.name)\(e.varies ? " (varies)" : " \(usd(abs(e.amount)))")").font(.caption)
                                        .foregroundStyle(e.kind == "pay" ? Theme.ok : Theme.ink)
                                }
                            }
                            .accessibilityElement(children: .combine)
                        }
                    }
                }
            }
        }
        .navigationTitle("Forecast")
        .task { await s.load(app) { try await $0.moneyForecast() } }
        .refreshable { await s.load(app) { try await $0.moneyForecast() } }
    }
}

// MARK: - V6.159 move a due date

struct DueDateMovesView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<DueDateMoves>()

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                if !v.ready { Text(v.reason ?? "") }
                if v.ready && v.moves.isEmpty { Label("None of your bills land right before payday.", systemImage: "checkmark.circle").foregroundStyle(Theme.ok) }
                ForEach(v.moves) { m in
                    Section {
                        LabeledContent("Due now", value: "the \(m.dueDay)\(m.dueDay.ordinalSuffix)")
                        LabeledContent("Payday", value: shortDay(m.payday))
                        LabeledContent("Ask for", value: "the \(m.suggestedDueDay)\(m.suggestedDueDay.ordinalSuffix)").font(.headline)
                        Text(m.script).font(.callout).textSelection(.enabled)
                        ShareLink(item: m.script) { Label("Copy or share", systemImage: "square.and.arrow.up") }
                    } header: { Text("\(m.name) · \(usd(m.amount))") }
                }
                if let n = v.note { Section { } footer: { Text(n) } }
            }
        }
        .navigationTitle("Move a due date")
        .task { await s.load(app) { try await $0.dueDateMoves() } }
    }
}

extension Int {
    var ordinalSuffix: String { (11...13).contains(self % 100) ? "th" : [1: "st", 2: "nd", 3: "rd"][self % 10] ?? "th" }
}

// MARK: - V6.161/V6.162 bill history and confirmation numbers

struct BillHistoryView: View {
    @Environment(AppState.self) private var app
    let bill: Bill
    @State private var s = Loader<BillHistory>()
    @State private var editing: BillHistory.Row?
    @State private var conf = ""
    @State private var method = ""
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                if v.payments.count >= 2 {
                    Section {
                        Chart(v.payments.reversed().filter { $0.amount != nil }) { r in BarMark(x: .value("Period", r.period), y: .value("Paid", r.amount ?? 0)).foregroundStyle(r.onTime ? Theme.ok : Theme.bad) }
                            .frame(height: 140).accessibilityLabel("Amounts paid by period")
                        LabeledContent("Average", value: usd(v.average))
                        LabeledContent("Range", value: "\(usd(v.lowest)) – \(usd(v.highest))")
                    }
                }
                Section {
                    if v.payments.isEmpty { Text("Mark this bill paid to start its history.").foregroundStyle(.secondary) }
                    ForEach(v.payments) { r in
                        Button { editing = r; conf = r.confirmation; method = r.method } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                HStack {
                                    Text(r.period).foregroundStyle(Theme.ink)
                                    Spacer()
                                    Text(usd(r.amount)).monospacedDigit().foregroundStyle(Theme.ink)
                                }
                                Text("Paid \(shortDay(r.paidOn)) · \(r.onTime ? "on time" : "late")" + (r.confirmation.isEmpty ? "" : " · #\(r.confirmation)") + (r.method.isEmpty ? "" : " · \(r.method)"))
                                    .font(.caption2).foregroundStyle(r.onTime ? .secondary : Theme.bad)
                            }
                        }
                        .accessibilityHint("Add a confirmation number")
                    }
                } header: { Text("Payments") } footer: { Text("Tap a payment to save its confirmation number. Never enter a card number.") }
            }
        }
        .navigationTitle(bill.name)
        .alert("Payment for \(editing?.period ?? "")", isPresented: Binding(get: { editing != nil }, set: { if !$0 { editing = nil } })) {
            TextField("Confirmation number", text: $conf)
            TextField("How you paid (bank app, website…)", text: $method)
            Button("Save") { if let r = editing { Task { await save(r.period) } } }
            Button("Cancel", role: .cancel) {}
        }
        .task { await load() }
    }

    private func load() async { await s.load(app) { [id = bill.id] api in try await api.billHistory(id) } }
    private func save(_ period: String) async {
        guard let api = app.api else { return }
        do { try await api.setPaymentNote(bill.id, period: period, confirmation: conf, method: method); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.178 set-asides

struct SetAsidesView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<SetAsides>()
    @State private var made: Set<String> = []
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                if v.funds.isEmpty { Text("Yearly bills with an amount show here (insurance, registration, memberships).").foregroundStyle(.secondary) }
                if !v.funds.isEmpty {
                    Section { LabeledContent("Set aside each month", value: usd(v.perMonthTotal)).font(.headline) }
                }
                ForEach(v.funds) { f in
                    Section {
                        LabeledContent("Due", value: "\(shortDay(f.due)) · \(usd(f.amount))")
                        LabeledContent("Each month", value: "\(usd(f.perMonth)) for \(f.months) month\(f.months == 1 ? "" : "s")")
                        Button(made.contains(f.billId) ? "Savings goal made" : "Make it a savings goal") { Task { await goal(f.billId) } }.disabled(made.contains(f.billId))
                    } header: { Text(f.name) }
                }
            }
        }
        .navigationTitle("Set-asides")
        .task { await s.load(app) { try await $0.setAsides() } }
    }

    private func goal(_ bid: String) async {
        guard let api = app.api else { return }
        do { try await api.setAsideGoal(bid); made.insert(bid); error = nil } catch { self.error = oops(error) }
    }
}

// MARK: - V6.165–V6.167 credit watch

struct CreditWatchView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<CreditWatch>()
    @State private var bureau = "equifax"
    @State private var item = ""
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    if let u = URL(string: v.reportsUrl) { Link("Get your free reports", destination: u) }
                    ForEach(v.bureaus) { b in
                        HStack {
                            VStack(alignment: .leading) {
                                Text(b.bureau.capitalized).font(.subheadline.bold())
                                Text(b.checkedAt == nil ? "Not checked yet" : "Checked \(b.daysSince ?? 0) day\(b.daysSince == 1 ? "" : "s") ago").font(.caption2).foregroundStyle(b.due ? Theme.gold : .secondary)
                            }
                            Spacer()
                            Button("Checked") { Task { await run { try await $0.markBureau("report", b.bureau, on: true) } } }.buttonStyle(.bordered)
                        }
                    }
                } header: { Text("Free credit reports") }
                Section {
                    if let u = URL(string: v.freezeUrl) { Link("How to freeze with each bureau", destination: u) }
                    ForEach(v.bureaus) { b in
                        Toggle("\(b.bureau.capitalized) frozen", isOn: Binding(get: { b.frozen }, set: { on in Task { await run { try await $0.markBureau("freeze", b.bureau, on: on) } } }))
                    }
                } header: { Text("Credit freezes") } footer: { Text("A freeze stops new credit being opened in your name until you lift it. You freeze and unfreeze on each bureau's site; this only records it.") }
                Section {
                    ForEach(v.disputes) { d in
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(d.bureau.capitalized): \(d.item)").font(.subheadline)
                            Text("Sent \(shortDay(d.sentOn)) · \(d.status)" + (d.followUpDue ? " · follow up" : d.status == "open" ? " · follow up \(shortDay(d.followUpOn))" : ""))
                                .font(.caption2).foregroundStyle(d.followUpDue ? Theme.gold : .secondary)
                        }
                        .swipeActions {
                            Button("Fixed") { Task { await run { try await $0.updateDispute(d.id, status: "fixed") } } }.tint(Theme.ok)
                            Button("Denied") { Task { await run { try await $0.updateDispute(d.id, status: "denied") } } }
                            Button(role: .destructive) { Task { await run { try await $0.removeDispute(d.id) } } } label: { Label("Delete", systemImage: "trash") }
                        }
                    }
                    Picker("Bureau", selection: $bureau) { ForEach(["equifax", "experian", "transunion", "other"], id: \.self) { Text($0.capitalized).tag($0) } }
                    TextField("What's wrong (no account numbers)", text: $item)
                    Button("Add a dispute you sent") { Task { await add() } }.disabled(item.trimmingCharacters(in: .whitespaces).isEmpty)
                } header: { Text("Disputes") } footer: { Text(v.note) }
            }
        }
        .navigationTitle("Credit watch")
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async { await s.load(app) { try await $0.creditWatch() } }
    private func add() async {
        await run { [bureau, item] api in try await api.addDispute(bureau: bureau, item: item.trimmingCharacters(in: .whitespaces)) }
        if error == nil { item = "" }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.168/V6.169 credit habits and utilization history; V6.170 card payments as bills

struct CreditHabitsView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<CreditHabits>()
    @State private var hist: UtilizationHistory?
    @State private var cards: [CreditCardInfo] = []
    @State private var links: [String: String] = [:]
    @State private var billFor: CreditCardInfo?
    @State private var day = 15
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    ForEach(v.items) { i in
                        Label {
                            VStack(alignment: .leading, spacing: 2) { Text(i.title).font(.subheadline.bold()); Text(i.detail).font(.caption).foregroundStyle(.secondary) }
                        } icon: {
                            Image(systemName: i.state == "good" ? "checkmark.circle.fill" : i.state == "attention" ? "exclamationmark.circle.fill" : i.state == "info" ? "info.circle" : "questionmark.circle")
                                .foregroundStyle(i.state == "good" ? Theme.ok : i.state == "attention" ? Theme.gold : .secondary)
                        }
                    }
                } footer: { Text(v.note) }
            }
            if let h = hist, h.points.count >= 2 {
                Section("Utilization over time") {
                    Chart(h.points) { p in
                        LineMark(x: .value("Day", p.day), y: .value("Used", p.utilization)).foregroundStyle(Theme.gold)
                        RuleMark(y: .value("30%", 0.3)).foregroundStyle(Color.secondary.opacity(0.5))
                    }
                    .chartYAxis {
                        AxisMarks { value in
                            AxisGridLine()
                            AxisValueLabel { if let d = value.as(Double.self) { Text("\(Int((d * 100).rounded()))%") } }
                        }
                    }
                    .chartXAxis(.hidden)
                    .frame(height: 150).accessibilityLabel("Overall utilization over time")
                }
            }
            if !cards.isEmpty {
                Section {
                    ForEach(cards) { c in
                        Button { billFor = c; day = 15 } label: {
                            LabeledContent(c.name, value: links[c.id] != nil ? "a bill · change day" : "make it a bill")
                        }
                    }
                } header: { Text("Card payments as bills") } footer: { Text("Get the same reminders as your other bills, and count the payment in your on-time record.") }
            }
        }
        .navigationTitle("Credit habits")
        .sheet(item: $billFor) { c in
            NavigationStack {
                Form {
                    Stepper("Payment due on the \(day)\(day.ordinalSuffix)", value: $day, in: 1...31)
                    Button("Save") { Task { await makeBill(c.id) } }
                }
                .navigationTitle(c.name)
            }
            .presentationDetents([.height(220)])
        }
        .task { await load() }
    }

    private func load() async {
        await s.load(app) { try await $0.creditHabits() }
        hist = try? await app.api?.utilizationHistory()
        cards = (try? await app.api?.credit().cards) ?? cards
        links = (try? await app.api?.cardBillLinks()) ?? links
    }
    private func makeBill(_ cid: String) async {
        guard let api = app.api else { return }
        do { try await api.cardBill(cid, dueDay: day); billFor = nil; error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.171/V6.172 income goal and best days

struct IncomeGoalView: View {
    @Environment(AppState.self) private var app
    @State private var g = Loader<IncomeGoal>()
    @State private var days: BestDays?
    @State private var goalText = ""
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? g.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            Section {
                if let v = g.value, let goal = v.goal {
                    ProgressView(value: min(v.progress ?? 0, 1)).tint(v.reached == true ? Theme.ok : Theme.gold).accessibilityLabel("Income goal progress")
                    LabeledContent("Earned this month", value: "\(usd(v.earned)) of \(usd(goal))")
                    if v.reached == true { Label("Goal reached", systemImage: "star.fill").foregroundStyle(Theme.ok) } else {
                        LabeledContent("To go", value: "\(usd(v.left)) · \(usd(v.perDay)) a day for \(v.daysLeft) days")
                        if let h = v.hoursNeeded, let r = v.hourly { LabeledContent("About", value: String(format: "%.0f hours at %@/hr", h, usd(r))) }
                    }
                }
                TextField("Monthly income goal", text: $goalText).keyboardType(.decimalPad)
                Button("Save goal") { Task { await save() } }
            } header: { Text("Income goal") }
            if let d = days {
                Section {
                    Chart(d.days) { x in BarMark(x: .value("Day", String(x.weekday.prefix(3))), y: .value("Per hour", x.hourly ?? 0)).foregroundStyle(d.best.contains(x.weekday) ? Theme.ok : Theme.gold.opacity(0.6)) }
                        .frame(height: 150).accessibilityLabel("Earnings per hour by weekday")
                    if !d.best.isEmpty { Text("Best per hour: \(d.best.joined(separator: " and ")).").font(.callout) }
                    ForEach(d.days.filter { $0.entries > 0 }) { x in
                        LabeledContent(x.weekday, value: usd(x.earned) + (x.hourly.map { " · \(usd($0))/hr" } ?? ""))
                    }
                } header: { Text("Best earning days · last 90 days") } footer: { Text(d.note + " Log hours with income to see per-hour.") }
            }
        }
        .navigationTitle("Income goal")
        .task { await load() }
    }

    private func load() async {
        await g.load(app) { try await $0.incomeGoal() }
        if goalText.isEmpty, let v = g.value?.goal { goalText = String(format: "%.0f", v) }
        days = try? await app.api?.bestDays()
    }
    private func save() async {
        guard let api = app.api else { return }
        do { try await api.setIncomeGoal(num(goalText)); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.173 wins

struct WinsView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<MoneyWins>()
    @State private var title = ""
    @State private var amount = ""
    @State private var monthly = false
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    LabeledContent("Saved this year", value: usd(v.thisYear)).font(.headline).foregroundStyle(Theme.ok)
                    if v.perMonthOngoing > 0 { LabeledContent("Ongoing", value: "\(usd(v.perMonthOngoing)) a month") }
                }
                Section {
                    ForEach(v.wins) { w in
                        LabeledContent(w.title, value: usd(w.amount) + (w.monthly ? "/mo" : ""))
                            .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeWin(w.id) } } } label: { Label("Delete", systemImage: "trash") } }
                    }
                }
            }
            Section("Add a win") {
                TextField("What (lowered internet, waived fee)", text: $title)
                TextField("Amount", text: $amount).keyboardType(.decimalPad)
                Toggle("Saves this every month", isOn: $monthly)
                Button("Add") { Task { await add() } }.disabled(title.trimmingCharacters(in: .whitespaces).isEmpty || (num(amount) ?? 0) <= 0)
            }
        }
        .navigationTitle("Money you've saved")
        .task { await load() }
    }

    private func load() async { await s.load(app) { try await $0.moneyWins() } }
    private func add() async {
        guard let a = num(amount) else { return }
        await run { [title, monthly] api in try await api.addWin(title: title.trimmingCharacters(in: .whitespaces), amount: a, monthly: monthly) }
        if error == nil { title = ""; amount = ""; monthly = false; Haptics.success() }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.174 selling

struct SellingView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<Selling>()
    @State private var name = ""
    @State private var asking = ""
    @State private var whereListed = ""
    @State private var selling: Selling.Item?
    @State private var price = ""
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section {
                    LabeledContent("Sold this year", value: usd(v.soldThisYear)).font(.headline)
                    LabeledContent("Listed", value: "\(v.listed) · \(usd(v.listedValue))")
                }
                Section {
                    ForEach(v.items) { i in
                        Button { if i.sold == nil { selling = i; price = i.asking.map { String(format: "%.0f", $0) } ?? "" } } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                HStack { Text(i.name).foregroundStyle(Theme.ink); Spacer(); Text(i.sold.map { "sold \(usd($0))" } ?? usd(i.asking)).monospacedDigit().foregroundStyle(i.sold != nil ? Theme.ok : .secondary) }
                                Text((i.whereListed.isEmpty ? "" : "\(i.whereListed) · ") + (i.soldOn.map { "sold \(shortDay($0))" } ?? "listed \(i.daysListed) days")).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                        .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeSellItem(i.id) } } } label: { Label("Delete", systemImage: "trash") } }
                    }
                } footer: { Text("Tap an item when it sells.") }
            }
            Section("Add something to sell") {
                TextField("Item", text: $name)
                TextField("Asking price", text: $asking).keyboardType(.decimalPad)
                TextField("Where it's listed (optional)", text: $whereListed)
                Button("Add") { Task { await add() } }.disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .navigationTitle("Things to sell")
        .alert("Sold \(selling?.name ?? "") for", isPresented: Binding(get: { selling != nil }, set: { if !$0 { selling = nil } })) {
            TextField("Price", text: $price).keyboardType(.decimalPad)
            Button("Save") { if let i = selling, let p = num(price) { Task { await run { try await $0.markSold(i.id, price: p) } } } }
            Button("Cancel", role: .cancel) {}
        }
        .task { await load() }
    }

    private func load() async { await s.load(app) { try await $0.selling() } }
    private func add() async {
        await run { [name, asking, whereListed] api in try await api.addSellItem(name: name.trimmingCharacters(in: .whitespaces), asking: num(asking), whereListed: whereListed) }
        if error == nil { name = ""; asking = ""; whereListed = "" }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.175 owed to you

struct OwedView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<OwedToMe>()
    @State private var who = ""
    @State private var amount = ""
    @State private var why = ""
    @State private var hasDate = false
    @State private var expected = Date()
    @State private var error: String?

    var body: some View {
        List {
            if let e = error ?? s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                Section { LabeledContent("Outstanding", value: usd(v.outstanding)).font(.headline) }
                Section {
                    ForEach(v.items) { o in
                        Toggle(isOn: Binding(get: { o.receivedOn != nil }, set: { on in Task { await run { try await $0.markOwed(o.id, received: on) } } })) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(o.who) · \(usd(o.amount))")
                                Text([o.why.isEmpty ? nil : o.why, o.receivedOn.map { "got it \(shortDay($0))" } ?? o.expectedOn.map { (o.late ? "late, expected " : "expected ") + shortDay($0) }]
                                    .compactMap { $0 }.joined(separator: " · ")).font(.caption2).foregroundStyle(o.late ? Theme.gold : .secondary)
                            }
                        }
                        .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeOwed(o.id) } } } label: { Label("Delete", systemImage: "trash") } }
                    }
                } footer: { Text("Switch one on when you get the money. You collect it; the app doesn't contact anyone.") }
            }
            Section("Add") {
                TextField("Who (a first name or company)", text: $who)
                TextField("Amount", text: $amount).keyboardType(.decimalPad)
                TextField("What for (optional)", text: $why)
                Toggle("Expected by a date", isOn: $hasDate)
                if hasDate { DatePicker("Expected", selection: $expected, displayedComponents: .date) }
                Button("Add") { Task { await add() } }.disabled(who.trimmingCharacters(in: .whitespaces).isEmpty || (num(amount) ?? 0) <= 0)
            }
        }
        .navigationTitle("Owed to you")
        .task { await load() }
    }

    private func load() async { await s.load(app) { try await $0.owedToMe() } }
    private func add() async {
        guard let a = num(amount) else { return }
        await run { [who, why, hasDate, expected] api in try await api.addOwed(who: who.trimmingCharacters(in: .whitespaces), amount: a, why: why, expectedOn: hasDate ? isoDay(expected) : nil) }
        if error == nil { who = ""; amount = ""; why = ""; hasDate = false }
    }
    private func run(_ f: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        do { try await f(api); error = nil; await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.176/V6.177 round-ups and no-spend days

struct KeepMoreView: View {
    @Environment(AppState.self) private var app
    @State private var r: RoundUps?
    @State private var n: NoSpend?
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let n {
                Section {
                    Toggle("Today is a no-spend day", isOn: Binding(get: { n.today }, set: { on in Task { await set(on) } }))
                    LabeledContent("This month", value: "\(n.thisMonth) day\(n.thisMonth == 1 ? "" : "s")")
                    LabeledContent("In a row", value: "\(n.streak)")
                    if !n.conflicts.isEmpty { Text("Spending is logged on \(n.conflicts.map(shortDay).joined(separator: ", ")), which you marked no-spend.").font(.caption).foregroundStyle(Theme.gold) }
                } header: { Text("No-spend days") }
            }
            if let r {
                Section {
                    LabeledContent("Round-ups this month", value: usd(r.roundUps)).font(.headline)
                    Text("From \(r.purchases) purchase\(r.purchases == 1 ? "" : "s") you logged, each rounded up to the next dollar.").font(.caption)
                } header: { Text("Round-ups") } footer: { Text(r.note) }
            }
        }
        .navigationTitle("Keep more")
        .task { await load() }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac first."; return }
        do { r = try await api.roundUps(); n = try await api.noSpend(); error = nil } catch { self.error = oops(error) }
    }
    private func set(_ on: Bool) async {
        guard let api = app.api else { return }
        do { try await api.setNoSpend(on: on); await load() } catch { self.error = oops(error) }
    }
}

// MARK: - V6.182 goal projections

struct ProjectionsView: View {
    @Environment(AppState.self) private var app
    @State private var s = Loader<GoalProjections>()

    var body: some View {
        List {
            if let e = s.error { Text(e).foregroundStyle(Theme.bad).font(.caption) }
            if let v = s.value {
                if v.goals.isEmpty { Text("Open savings goals show here.").foregroundStyle(.secondary) }
                ForEach(v.goals) { g in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(g.name).font(.subheadline.bold())
                        if let reach = g.reach {
                            Text("At \(usd(g.pacePerMonth))/month (\(g.paceFrom == "plan" ? "your plan" : "your recent deposits")): reached \(monthName(reach))").font(.caption)
                        } else {
                            Text("\(usd(g.left)) to go. Add deposits or a monthly plan to see when.").font(.caption).foregroundStyle(.secondary)
                        }
                        if let dl = g.deadline, let ok = g.onTrack {
                            Text(ok ? "On track for \(shortDay(dl))" : "Behind for \(shortDay(dl))").font(.caption2).foregroundStyle(ok ? Theme.ok : Theme.gold)
                        }
                    }
                    .accessibilityElement(children: .combine)
                }
                Section { } footer: { Text(v.note) }
            }
        }
        .navigationTitle("Goal projections")
        .task { await s.load(app) { try await $0.goalProjections() } }
    }
}

// MARK: - V6.183 export, V6.184 Face ID lock

struct ExportMoneyRow: View {
    @Environment(AppState.self) private var app
    @State private var file: URL?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading) {
            if let file { ShareLink(item: file) { Label("Share your money data (JSON)", systemImage: "square.and.arrow.up") } }
            else { Button { Task { await make() } } label: { Label("Export your money data", systemImage: "square.and.arrow.down") } }
            if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
        }
    }

    private func make() async {
        guard let api = app.api else { return }
        do {
            let data = try await api.moneyExport()
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("money-export.json")
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            file = url
        } catch { self.error = oops(error) }
    }
}

struct MoneyLockToggle: View {
    @AppStorage("money.lock") private var locked = false
    var body: some View {
        Toggle(isOn: $locked) { Label("Lock Money with Face ID", systemImage: "faceid") }
    }
}

/// Covers Money until Face ID (or your passcode) unlocks it, when the lock is on. Locks again when the app goes to
/// the background.
struct MoneyLockGate<Content: View>: View {
    @AppStorage("money.lock") private var locked = false
    @Environment(\.scenePhase) private var phase
    @State private var open = false
    @ViewBuilder let content: () -> Content

    var body: some View {
        Group {
            if !locked || open { content() } else {
                VStack(spacing: 14) {
                    Image(systemName: "lock.fill").font(.largeTitle).foregroundStyle(Theme.gold).accessibilityHidden(true)
                    Text("Money is locked").font(.headline)
                    Button("Unlock") { Task { await unlock() } }.buttonStyle(.borderedProminent)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .task { if phase == .active { await unlock() } }
            }
        }
        .onChange(of: phase) {
            if phase == .background { open = false }
            if phase == .active && locked && !open { Task { await unlock() } }
        }
    }

    private func unlock() async {
        let ctx = LAContext()
        var err: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &err) else { open = true; return }
        open = (try? await ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: "Unlock Money")) ?? false
    }
}
