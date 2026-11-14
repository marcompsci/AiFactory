import EventKit
import SwiftUI
import UniformTypeIdentifiers
import UserNotifications

/// V6.98–V6.112 on the phone: brain dump, bills, the month, "I have N minutes", end of day, weekly goals, the archive
/// with export and import, list colors, and your calendar's busy times for Plan my day.

private func problem(_ error: Error) -> String { (error as? APIError)?.detail ?? "Couldn't reach your Mac." }

// MARK: - brain dump (V6.98) and import (V6.109)

struct BrainDumpView: View {
    @Environment(AppState.self) private var app
    let changed: () async -> Void
    @State private var text = ""
    @State private var format = "lines"
    @State private var preview: [DumpPreview] = []
    @State private var note: String?
    @State private var error: String?
    @State private var importing = false
    @State private var busy = false

    var body: some View {
        List {
            Section {
                Picker("Format", selection: $format) { Text("One per line").tag("lines"); Text("CSV").tag("csv") }
                    .pickerStyle(.segmented)
                TextEditor(text: $text).frame(minHeight: 140).font(.callout)
                    .accessibilityLabel(format == "csv" ? "CSV text" : "Tasks, one per line")
                Button { importing = true } label: { Label("Import a file", systemImage: "doc.badge.plus") }
            } footer: {
                Text(format == "csv"
                     ? "A header row with title, and optionally list, due, notes, priority and estimate (minutes)."
                     : "Each line becomes a task, read like quick capture: \"call the bank tomorrow #money 15m\". Bullets and numbers are ignored. Up to 50.")
            }
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let note { Text(note).foregroundStyle(Theme.ok).font(.caption) }
            if !preview.isEmpty {
                Section("Will add \(preview.count)") {
                    ForEach(preview.enumerated().map { NumberedPreview(n: $0.offset, p: $0.element) }) { row in
                        let p = row.p
                        VStack(alignment: .leading, spacing: 2) {
                            Text(p.title).font(.subheadline)
                            HStack(spacing: 6) {
                                if let d = p.dueLabel { Chip(text: d, color: Theme.cyan) }
                                if let l = p.listName { Chip(text: "#\(l)", color: Theme.gold) }
                                if let m = p.estimateMinutes { Chip(text: TaskTime.minutes(m), color: .secondary) }
                                if let r = p.repeatLabel, !r.isEmpty { Chip(text: r, color: Theme.violet) }
                                if let n = p.links?.count, n > 0 { Chip(text: n == 1 ? "1 link" : "\(n) links", color: Theme.cyan) }
                            }
                        }
                        .accessibilityElement(children: .combine)
                    }
                    Button { Task { await add() } } label: { Label("Add all \(preview.count)", systemImage: "plus.circle.fill") }
                        .disabled(busy)
                }
            }
        }
        .task(id: "\(format)|\(text)") {
            guard text.trimmingCharacters(in: .whitespacesAndNewlines).count >= 2, let api = app.api else { preview = []; return }
            try? await Task.sleep(for: .milliseconds(400))
            guard !Task.isCancelled else { return }
            do { preview = try await api.dumpPreview(text, format: format); error = nil } catch { self.error = problem(error) }
        }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.commaSeparatedText, .plainText, .text]) { result in
            guard case .success(let url) = result else { return }
            let ok = url.startAccessingSecurityScopedResource()
            defer { if ok { url.stopAccessingSecurityScopedResource() } }
            if let s = try? String(contentsOf: url, encoding: .utf8) {
                text = String(s.prefix(40_000))
                format = url.pathExtension.lowercased() == "csv" ? "csv" : "lines"
            } else { error = "That file isn't plain text." }
        }
    }

    private func add() async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        do {
            let r = try await api.dumpAdd(text, format: format)
            note = "Added \(Plural.of(r.added.count, "task"))." + (r.problems.isEmpty ? "" : " \(r.problems.count) couldn't be added: \(r.problems.map(\.line).prefix(3).joined(separator: "; ")).")
            text = ""
            preview = []
            Haptics.success()
            await changed()
        } catch { self.error = problem(error) }
    }
}

// MARK: - bills (V6.100–V6.101): tracked here, paid wherever you pay them

struct BillsView: View {
    @Environment(AppState.self) private var app
    @State private var bills: [Bill] = []
    @State private var summary: BillSummary?
    @State private var editing: BillDraft?
    @State private var error: String?
    @State private var loaded = false
    @State private var paidOnFor: Bill?
    @State private var paidOn = Date()
    @State private var note: String?

    var body: some View {
        List {
            if let s = summary {
                Section {
                    LabeledContent("This month", value: s.total.formatted(.currency(code: "USD")) + (s.variesCount > 0 ? " + \(s.variesCount) that vary" : ""))
                    LabeledContent("Marked paid", value: s.paid.formatted(.currency(code: "USD")))
                    LabeledContent("Next 30 days", value: s.next30Total.formatted(.currency(code: "USD")))
                    if !s.overdue.isEmpty {
                        Label("\(Plural.of(s.overdue.count, "bill")) past due: \(s.overdue.map(\.name).joined(separator: ", "))",
                              systemImage: "exclamationmark.triangle.fill").foregroundStyle(Theme.bad).font(.caption)
                    }
                } footer: { Text("AI Civ doesn't pay bills or move money. Pay wherever you normally do, then mark it paid here.") }
            }
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let note { Text(note).foregroundStyle(Theme.ok).font(.caption) }
            if loaded && bills.isEmpty { Text("No bills yet. Add the ones you pay each month or year.").foregroundStyle(.secondary) }
            ForEach(bills) { b in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(b.name).font(.subheadline.bold())
                        if b.autopay { Chip(text: "autopay", color: Theme.ok) }
                        Spacer()
                        Text(b.amountText).font(.subheadline.monospacedDigit())
                    }
                    HStack(spacing: 6) {
                        Text(dueText(b)).font(.caption).foregroundStyle(b.overdue ? Theme.bad : b.daysUntil <= 3 ? Theme.gold : .secondary)
                        Spacer()
                        if let u = b.linkUrl, let url = URL(string: u) {
                            Link(destination: url) { Label("Pay page", systemImage: "arrow.up.right.square").font(.caption) }
                                .accessibilityHint("Opens the payment page in Safari")
                        }
                        Button(b.paidThisPeriod && !b.overdue ? "Paid ✓" : "Mark paid") { Task { await paid(b) } }
                            .buttonStyle(.bordered).font(.caption).disabled(b.paidThisPeriod && !b.overdue)
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture { editing = BillDraft(b) }
                .contextMenu {
                    Button { paidOn = Date(); paidOnFor = b } label: { Label("Paid on a different day…", systemImage: "calendar") }
                    Button { Task { await findCheaper(b) } } label: { Label("Find a cheaper option", systemImage: "magnifyingglass") }
                }
                .swipeActions {
                    Button(role: .destructive) { Task { await remove(b) } } label: { Label("Delete", systemImage: "trash") }
                    if b.paidThisPeriod, let per = b.thisPeriod {
                        Button { Task { await unpaid(b, per) } } label: { Label("Undo paid", systemImage: "arrow.uturn.backward") }
                    }
                }
                .accessibilityElement(children: .contain)
            }
        }
        .toolbar { ToolbarItem(placement: .topBarLeading) { Button { editing = BillDraft() } label: { Label("Add a bill", systemImage: "plus") } } }
        .sheet(item: $editing) { d in BillEditor(draft: d) { await load() }.presentationDetents([.large]) }
        .sheet(item: $paidOnFor) { b in
            NavigationStack {
                Form {
                    DatePicker("I paid \(b.name) on", selection: $paidOn, in: (Calendar.current.date(byAdding: .day, value: -60, to: Date()) ?? Date())...Date(),
                               displayedComponents: .date)
                    Text("This records it for \(b.period). The day counts toward your on-time record.").font(.caption).foregroundStyle(.secondary)
                }
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel") { paidOnFor = nil } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Save") { let bill = b; paidOnFor = nil; Task { await paid(bill, on: paidOn) } }
                    }
                }
            }
            .presentationDetents([.medium])
        }
        .task { await load() }
    }

    private func dueText(_ b: Bill) -> String {
        if b.overdue { return "Was due \(b.nextDue) (not marked paid)" }
        switch b.daysUntil {
        case 0: return "Due today"
        case 1: return "Due tomorrow"
        default: return "Due in \(b.daysUntil) days (\(b.due?.formatted(.dateTime.month(.abbreviated).day()) ?? b.nextDue))"
        }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac to see your bills."; return }
        do {
            bills = try await api.bills()
            summary = try? await api.billSummary()
            loaded = true
            error = nil
            BillReminders.sync(bills)
        } catch { self.error = problem(error) }
    }

    private func paid(_ b: Bill, on day: Date? = nil) async {
        guard let api = app.api else { return }
        do { _ = try await api.markBillPaid(b.id, paidOn: day); Haptics.success(); await load() } catch { self.error = problem(error) }
    }

    private func findCheaper(_ b: Bill) async {
        guard let api = app.api else { return }
        do { let t = try await api.findSavings(b.id); note = "Added \"\(t.title)\" to your list. It only starts if you press Do it." }
        catch { self.error = problem(error) }
    }

    private func unpaid(_ b: Bill, _ period: String) async {
        guard let api = app.api else { return }
        do { _ = try await api.unmarkBillPaid(b.id, period: period); await load() } catch { self.error = problem(error) }
    }

    private func remove(_ b: Bill) async {
        guard let api = app.api else { return }
        do { try await api.deleteBill(b.id); await load() } catch { self.error = problem(error) }
    }
}

struct BillDraft: Identifiable {
    var id = UUID()
    var billId: String?
    var name = ""
    var amount = ""
    var yearly = false
    var dueDay = 1
    var dueMonth = 1
    var autopay = false
    var link = ""
    var remindDays = 3

    init() {}
    /// V6.122: from quick capture ("phone bill $54.99 on the 15th every month").
    init(hint h: BillHint) {
        name = h.name; amount = h.amount.map { String(format: "%.2f", $0) } ?? ""
        yearly = h.cadence == "yearly"; dueDay = h.dueDay ?? 1; dueMonth = h.dueMonth ?? Calendar.current.component(.month, from: Date())
    }
    init(_ b: Bill) {
        billId = b.id; name = b.name; amount = b.amount.map { String(format: "%.2f", $0) } ?? ""
        yearly = b.cadence == "yearly"; dueDay = b.dueDay; dueMonth = b.dueMonth ?? 1; autopay = b.autopay
        link = b.linkUrl ?? ""; remindDays = b.remindDays
    }
}

struct BillEditor: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State var draft: BillDraft
    let saved: () async -> Void
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                TextField("Name (Rent, Phone, Car insurance)", text: $draft.name)
                TextField("Amount (leave empty if it varies)", text: $draft.amount).keyboardType(.decimalPad)
                Toggle("Once a year", isOn: $draft.yearly)
                if draft.yearly {
                    Picker("Month", selection: $draft.dueMonth) {
                        ForEach(1...12, id: \.self) { Text(Calendar.current.monthSymbols[$0 - 1]).tag($0) }
                    }
                }
                Picker("Due on the", selection: $draft.dueDay) {
                    ForEach(1...31, id: \.self) { d in Text(d == 31 ? "31st (or the last day)" : ordinal(d)).tag(d) }
                }
                Toggle("Autopay", isOn: $draft.autopay)
                Stepper("Remind \(draft.remindDays == 0 ? "on the day" : "\(draft.remindDays) day\(draft.remindDays == 1 ? "" : "s") before")",
                        value: $draft.remindDays, in: 0...14)
                TextField("Payment page link (optional)", text: $draft.link)
                    .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            }
            .navigationTitle(draft.billId == nil ? "New bill" : "Edit bill").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { Task { await save() } }.disabled(draft.name.trimmingCharacters(in: .whitespaces).isEmpty) }
            }
        }
    }

    private func ordinal(_ n: Int) -> String {
        let f = NumberFormatter()
        f.numberStyle = .ordinal
        return f.string(from: NSNumber(value: n)) ?? "\(n)"
    }

    private func save() async {
        guard let api = app.api else { return }
        let amt = draft.amount.replacingOccurrences(of: "$", with: "").replacingOccurrences(of: ",", with: "").trimmingCharacters(in: .whitespaces)
        if !amt.isEmpty && Double(amt) == nil { error = "The amount is a number like 54.99."; return }
        let fields: [String: Any?] = [
            "name": draft.name, "amount": amt.isEmpty ? nil : Double(amt), "cadence": draft.yearly ? "yearly" : "monthly",
            "due_day": draft.dueDay, "due_month": draft.yearly ? draft.dueMonth : nil, "autopay": draft.autopay,
            "remind_days": draft.remindDays, "link_url": draft.link.trimmingCharacters(in: .whitespaces).isEmpty ? nil : draft.link.trimmingCharacters(in: .whitespaces),
        ]
        do { _ = try await api.saveBill(draft.billId, fields: fields); Haptics.success(); await saved(); dismiss() }
        catch { self.error = problem(error) }
    }
}

/// Local reminders for bills: some days before (or, for autopay, on the day to check it went through), 9 AM.
enum BillReminders {
    static let prefix = "bill-"

    static func sync(_ bills: [Bill]) {
        let cal = Calendar.current
        let now = Date()
        var wanted: [(String, Bill, Date)] = []
        for b in bills where b.active && !(b.paidThisPeriod && !b.overdue) {
            guard let due = b.due else { continue }
            let day = cal.date(byAdding: .day, value: b.autopay ? 0 : -b.remindDays, to: due) ?? due
            guard let nine = cal.date(bySettingHour: 9, minute: 0, second: 0, of: day) else { continue }
            let at = QuietHours.adjust(nine)
            guard at > now else { continue }
            wanted.append(("\(prefix)\(b.id)-\(b.period)-\(b.autopay ? "a" : "\(b.remindDays)")", b, at))
        }
        let center = UNUserNotificationCenter.current()
        center.getPendingNotificationRequests { pending in
            let have = Set(pending.map(\.identifier).filter { $0.hasPrefix(prefix) })
            let want = Set(wanted.map(\.0))
            center.removePendingNotificationRequests(withIdentifiers: Array(have.subtracting(want)))
            for (id, b, at) in wanted where !have.contains(id) {
                let c = UNMutableNotificationContent()
                c.title = b.autopay ? "\(b.name) autopays today" : "\(b.name) is due \(b.remindDays == 0 ? "today" : b.remindDays == 1 ? "tomorrow" : "in \(b.remindDays) days")"
                c.body = b.autopay ? "Check that it went through (\(b.amountText))." : "\(b.amountText). Pay it where you usually do, then mark it paid in AI Civ."
                c.sound = .default
                c.threadIdentifier = "bills"
                let parts = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: at)
                center.add(UNNotificationRequest(identifier: id, content: c, trigger: UNCalendarNotificationTrigger(dateMatching: parts, repeats: false)))
            }
        }
    }
}

// MARK: - the month (V6.102)

struct MonthCalendarView: View {
    @Environment(AppState.self) private var app
    @State private var shown = Calendar.current.dateComponents([.year, .month], from: Date())
    @State private var data: MonthView?
    @State private var picked: String?
    @State private var error: String?

    private var first: Date { Calendar.current.date(from: shown) ?? Date() }

    var body: some View {
        List {
            HStack {
                Button { step(-1) } label: { Image(systemName: "chevron.left") }.accessibilityLabel("Previous month")
                Spacer()
                Text(first.formatted(.dateTime.month(.wide).year())).font(.headline)
                Spacer()
                Button { step(1) } label: { Image(systemName: "chevron.right") }.accessibilityLabel("Next month")
            }
            .buttonStyle(.borderless)
            grid
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let key = picked, let day = data?.days[key] {
                Section(key) {
                    ForEach(day.bills) { b in
                        Label("\(b.name)\(b.amount.map { " · " + $0.formatted(.currency(code: "USD")) } ?? "")\(b.paid ? " · paid" : "")",
                              systemImage: "dollarsign.circle").foregroundStyle(b.paid ? .secondary : Theme.gold)
                    }
                    ForEach(day.tasks) { t in
                        Label(t.title, systemImage: t.stage == "done" ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(t.stage == "done" ? .secondary : Theme.ink)
                    }
                }
            }
        }
        .task(id: "\(shown.year ?? 0)-\(shown.month ?? 0)") { await load() }
    }

    private var grid: some View {
        let cal = Calendar.current
        let days = cal.range(of: .day, in: .month, for: first)?.count ?? 30
        let lead = (cal.component(.weekday, from: first) - cal.firstWeekday + 7) % 7
        let cells: [Int?] = Array(repeating: nil, count: lead) + (1...days).map { Optional($0) }
        let symbols = cal.veryShortWeekdaySymbols
        let ordered = Array(symbols[(cal.firstWeekday - 1)...] + symbols[..<(cal.firstWeekday - 1)])
        return LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 4), count: 7), spacing: 4) {
            ForEach(Array(ordered.enumerated()), id: \.offset) { _, s in Text(s).font(.caption2).foregroundStyle(.secondary) }
            ForEach(Array(cells.enumerated()), id: \.offset) { _, d in
                if let d {
                    let key = String(format: "%04d-%02d-%02d", shown.year ?? 0, shown.month ?? 0, d)
                    let info = data?.days[key]
                    Button { picked = key } label: {
                        VStack(spacing: 2) {
                            Text("\(d)").font(.caption.monospacedDigit())
                            HStack(spacing: 2) {
                                if let n = info?.tasks.count, n > 0 { Circle().fill(Theme.cyan).frame(width: 5, height: 5) }
                                if let b = info?.bills, !b.isEmpty { Circle().fill(b.allSatisfy(\.paid) ? Color.secondary : Theme.gold).frame(width: 5, height: 5) }
                            }
                            .frame(height: 6)
                        }
                        .frame(maxWidth: .infinity, minHeight: 36)
                        .background(picked == key ? Theme.cyan.opacity(0.18) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(d): \(info?.tasks.count ?? 0) tasks, \(info?.bills.count ?? 0) bills")
                } else {
                    Color.clear.frame(height: 36)
                }
            }
        }
    }

    private func step(_ n: Int) {
        if let d = Calendar.current.date(byAdding: .month, value: n, to: first) {
            shown = Calendar.current.dateComponents([.year, .month], from: d)
            picked = nil
        }
    }

    private func load() async {
        guard let api = app.api, let y = shown.year, let m = shown.month else { error = "Connect to your Mac to see the month."; return }
        do { data = try await api.month(year: y, month: m); error = nil } catch { self.error = problem(error) }
    }
}

// MARK: - "I have N minutes" (V6.104)

struct FitView: View {
    @Environment(AppState.self) private var app
    @State private var minutes = 30
    @State private var result: FitResult?
    @State private var focusOn: MyTask?
    @State private var error: String?

    var body: some View {
        List {
            Section {
                Picker("I have", selection: $minutes) {
                    ForEach([15, 30, 45, 60, 90, 120], id: \.self) { Text(TaskTime.minutes($0)).tag($0) }
                }
                .pickerStyle(.segmented)
            } footer: { Text("Overdue and due-today come first, then priority. Tasks without your own estimate use a default length, marked so.") }
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let r = result {
                if r.picks.isEmpty { Text("Nothing on your list fits in \(TaskTime.minutes(r.minutes)).").foregroundStyle(.secondary) }
                ForEach(r.picks) { p in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(p.title).font(.subheadline)
                            Text(TaskTime.minutes(p.minutes) + (p.estimated ? " (default length)" : "") + (p.overdue ? " · overdue" : ""))
                                .font(.caption2).foregroundStyle(p.overdue ? Theme.bad : .secondary)
                        }
                        Spacer()
                        Button { Task { focusOn = try? await app.api?.myTask(p.taskId) } } label: { Image(systemName: "timer") }
                            .buttonStyle(.borderless).accessibilityLabel("Focus on \(p.title)")
                    }
                }
                if r.leftOver >= 5 && !r.picks.isEmpty { Text("\(TaskTime.minutes(r.leftOver)) to spare.").font(.caption).foregroundStyle(.secondary) }
            }
        }
        .task(id: minutes) {
            guard let api = app.api else { error = "Connect to your Mac first."; return }
            do { result = try await api.fit(minutes: minutes); error = nil } catch { self.error = problem(error) }
        }
        .sheet(item: $focusOn) { t in FocusView(task: t) {}.presentationDetents([.medium]) }
    }
}

// MARK: - end of the day (V6.105)

struct EndOfDayView: View {
    @Environment(AppState.self) private var app
    let changed: () async -> Void
    @State private var s: DayShutdown?
    @State private var note = ""
    @State private var move = true
    @State private var done: String?
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let s {
                if !s.yesterdaysNote.isEmpty { Section("Your note from yesterday") { Text(s.yesterdaysNote) } }
                Section("Done today (\(s.done.count))") {
                    if s.done.isEmpty { Text("Nothing marked done yet today.").foregroundStyle(.secondary) }
                    ForEach(s.done) { t in Label(t.title, systemImage: "checkmark.circle.fill").foregroundStyle(Theme.ok) }
                }
                if !s.stillDue.isEmpty {
                    Section {
                        ForEach(s.stillDue) { t in
                            Label(t.title + (t.repeats == true ? " (repeats, keeps its schedule)" : ""),
                                  systemImage: t.overdue == true ? "exclamationmark.circle" : "circle")
                        }
                        Toggle("Move these to tomorrow", isOn: $move)
                    } header: { Text("Still due (\(s.stillDue.count))") } footer: {
                        Text("Same time tomorrow. Nothing is marked done or dropped.")
                    }
                }
                if !s.tomorrow.isEmpty {
                    Section("Tomorrow") { ForEach(s.tomorrow) { t in Text(t.title) } }
                }
                Section("A note for tomorrow") {
                    TextField("Start with…", text: $note, axis: .vertical).lineLimit(2...5)
                }
                Button { Task { await close() } } label: { Label("Close the day", systemImage: "moon.stars").frame(maxWidth: .infinity) }
                    .buttonStyle(.borderedProminent)
                if let done { Text(done).font(.caption).foregroundStyle(Theme.ok) }
            } else if error == nil { ProgressView() }
        }
        .task { await load() }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac first."; return }
        do { s = try await api.shutdown(); note = s?.note ?? ""; error = nil } catch { self.error = problem(error) }
    }

    private func close() async {
        guard let api = app.api, let s else { return }
        do {
            try await api.closeDay(move: move && !s.stillDue.isEmpty, note: note)
            done = move && !s.stillDue.isEmpty ? "Moved \(Plural.of(s.stillDue.count, "task")) to tomorrow. Good night." : "Day closed. Good night."
            Haptics.success()
            await load()
            await changed()
        } catch { self.error = problem(error) }
    }
}

// MARK: - weekly goals (V6.106)

struct GoalsView: View {
    @Environment(AppState.self) private var app
    @State private var g: WeekGoals?
    @State private var text = ""
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let g {
                Section {
                    if g.goals.isEmpty { Text("No goals yet this week.").foregroundStyle(.secondary) }
                    ForEach(g.goals) { goal in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Button { Task { await run { try await $0.setGoal(goal.id, done: !goal.done) } } } label: {
                                    Image(systemName: goal.done ? "checkmark.circle.fill" : "circle").foregroundStyle(goal.done ? Theme.ok : .secondary)
                                }
                                .buttonStyle(.plain).accessibilityLabel(goal.done ? "Reached: \(goal.text)" : "Mark reached: \(goal.text)")
                                Text(goal.text).font(.subheadline.bold()).strikethrough(goal.done)
                            }
                            ProgressView(value: goal.progress).tint(Theme.gold)
                                .accessibilityLabel("\(Int(goal.progress * 100)) percent")
                            if !goal.tasks.isEmpty {
                                Text("\(goal.tasksDone) of \(goal.tasks.count) linked tasks done").font(.caption2).foregroundStyle(.secondary)
                            } else {
                                Text("Link tasks to this goal from a task's details.").font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                        .swipeActions { Button(role: .destructive) { Task { await run { try await $0.removeGoal(goal.id) } } } label: { Label("Remove", systemImage: "trash") } }
                    }
                } header: { Text("Week of \(g.weekStart)") }
                if g.goals.count < 3 {
                    Section {
                        HStack {
                            TextField("A goal for this week", text: $text).onSubmit { add() }
                            Button("Add") { add() }.disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                    } footer: { Text("Up to three, so each one matters.") }
                }
            } else if error == nil { ProgressView() }
        }
        .task { await run { try await $0.goals() } }
    }

    private func add() {
        let t = text.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return }
        text = ""
        Task { await run { try await $0.addGoal(t) } }
    }

    private func run(_ f: (APIClient) async throws -> WeekGoals) async {
        guard let api = app.api else { error = "Connect to your Mac first."; return }
        do { g = try await f(api); error = nil } catch { self.error = problem(error) }
    }
}

// MARK: - archive, export and import (V6.108–V6.109)

struct ArchiveView: View {
    @Environment(AppState.self) private var app
    let changed: () async -> Void
    @State private var q = ""
    @State private var items: [ArchivedTask] = []
    @State private var file: URL?
    @State private var error: String?
    @State private var note: String?

    var body: some View {
        List {
            Section {
                HStack {
                    Button("Export JSON") { Task { await export("json") } }
                    Spacer()
                    Button("Export CSV") { Task { await export("csv") } }
                }
                .buttonStyle(.borderless)
                if let file { ShareLink(item: file) { Label("Share \(file.lastPathComponent)", systemImage: "square.and.arrow.up") } }
            } header: { Text("Export") } footer: {
                Text("Every task, archived ones too, with lists, checklists and links. To import, use Brain dump › Import a file.")
            }
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let note { Text(note).foregroundStyle(Theme.ok).font(.caption) }
            Section {
                ForEach(items) { t in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(t.title).font(.subheadline).lineLimit(1)
                            Text("\(t.status == "DONE" ? "Done" : "Dropped") \(ISODate.parse(t.closedAt)?.formatted(date: .abbreviated, time: .omitted) ?? "")")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Restore") { Task { await restore(t) } }.buttonStyle(.bordered).font(.caption)
                    }
                }
                if items.isEmpty { Text(q.isEmpty ? "Nothing archived yet. Tasks closed more than 30 days ago land here." : "Nothing matches.").foregroundStyle(.secondary) }
            } header: { Text("Archive") }
        }
        .searchable(text: $q, prompt: "Search the archive")
        .task(id: q) {
            try? await Task.sleep(for: .milliseconds(250))
            guard !Task.isCancelled, let api = app.api else { return }
            do { items = try await api.archive(q); error = nil } catch { self.error = problem(error) }
        }
    }

    private func export(_ format: String) async {
        guard let api = app.api else { return }
        do { file = try await api.exportTasks(format: format) } catch { self.error = problem(error) }
    }

    private func restore(_ t: ArchivedTask) async {
        guard let api = app.api else { return }
        do {
            _ = try await api.reopenTask(t.id)
            note = "\"\(t.title)\" is back on your list."
            items.removeAll { $0.id == t.id }
            await changed()
        } catch { self.error = problem(error) }
    }
}

// MARK: - list colors and icons (V6.110)

struct ListStyleSheet: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let name: String
    let current: ListStyle?
    let icons: [String]
    let saved: ([String: ListStyle]) -> Void
    @State private var color: Color = Theme.gold
    @State private var icon = "tag"
    @State private var error: String?

    static let palette: [String] = ["#FFBD69", "#5BF2A5", "#32D8FF", "#A66BFF", "#FF6B9D", "#FF6B6B", "#9AA5C8", "#F5E663"]
    @State private var hex = "#FFBD69"

    var body: some View {
        NavigationStack {
            Form {
                Section("Color") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 8)) {
                        ForEach(Self.palette, id: \.self) { h in
                            Circle().fill(Color(hexString: h)).frame(width: 28, height: 28)
                                .overlay { if h == hex { Circle().stroke(.white, lineWidth: 2) } }
                                .onTapGesture { hex = h }
                                .accessibilityLabel("Color \(h)").accessibilityAddTraits(h == hex ? .isSelected : [])
                        }
                    }
                }
                Section("Icon") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 6)) {
                        ForEach(icons, id: \.self) { i in
                            Image(systemName: i).font(.title3).frame(width: 36, height: 36)
                                .background(i == icon ? Color(hexString: hex).opacity(0.3) : .clear, in: RoundedRectangle(cornerRadius: 8))
                                .onTapGesture { icon = i }
                                .accessibilityLabel(i.replacingOccurrences(of: ".", with: " ")).accessibilityAddTraits(i == icon ? .isSelected : [])
                        }
                    }
                }
                if current != nil { Button("Remove the style", role: .destructive) { Task { await save(clear: true) } } }
                if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            }
            .navigationTitle("#\(name)").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { Task { await save(clear: false) } } }
            }
            .onAppear { if let c = current { hex = c.color; icon = c.icon } }
        }
    }

    private func save(clear: Bool) async {
        guard let api = app.api else { return }
        do {
            let s = try await api.setListStyle(name, color: clear ? nil : hex, icon: clear ? nil : icon)
            saved(s)
            dismiss()
        } catch { self.error = problem(error) }
    }
}

// MARK: - your calendar's busy times (V6.103), read on the phone

enum CalendarBusy {
    /// Today's busy times between `start` and `end` from your calendars. Only start and end leave this function: no
    /// titles, places or people. Returns nil when you haven't allowed calendar access.
    static func today(from start: Date, to end: Date) async -> [(Date, Date)]? {
        let store = EKEventStore()
        let granted: Bool
        if EKEventStore.authorizationStatus(for: .event) == .fullAccess {
            granted = true
        } else {
            granted = (try? await store.requestFullAccessToEvents()) ?? false
        }
        guard granted else { return nil }
        let events = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: nil))
        return events
            .filter { !$0.isAllDay && $0.availability != .free && $0.status != .canceled }
            .map { (max($0.startDate, start), min($0.endDate, end)) }
            .filter { $0.1 > $0.0 }
            .sorted { $0.0 < $1.0 }
    }
}
