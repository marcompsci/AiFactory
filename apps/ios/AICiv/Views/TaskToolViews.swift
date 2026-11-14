import Charts
import SwiftUI
import UserNotifications

/// The task list's tools (V6.74–V6.84): plan my day, the weekly review, results, insights and templates.
enum TaskTool: String, CaseIterable, Identifiable {
    case plan, review, habits, digest, results, insights, templates
    var id: String { rawValue }
    var label: String {
        switch self {
        case .plan: return "Plan my day"
        case .review: return "Weekly review"
        case .habits: return "Habits"
        case .digest: return "Morning digest"
        case .results: return "Results"
        case .insights: return "Insights"
        case .templates: return "Templates"
        }
    }
    var icon: String {
        switch self {
        case .plan: return "calendar.day.timeline.left"
        case .review: return "checklist.checked"
        case .habits: return "flame"
        case .digest: return "sun.horizon"
        case .results: return "books.vertical"
        case .insights: return "chart.bar.xaxis"
        case .templates: return "square.on.square"
        }
    }
}

struct TaskToolSheet: View {
    let tool: TaskTool
    let changed: () async -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                switch tool {
                case .plan: PlanDayView(changed: changed)
                case .review: ReviewView(changed: changed)
                case .habits: HabitsView()
                case .digest: DigestSettingsView()
                case .results: ResultsLibraryView()
                case .insights: InsightsView()
                case .templates: TemplatesView(changed: changed)
                }
            }
            .navigationTitle(tool.label).navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Close") { dismiss() } } }
        }
    }
}

private func failure(_ error: Error) -> String { (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
private var phoneTZ: String { TimeZone.current.identifier }

// MARK: - plan my day (V6.74, V6.75)

struct PlanDayView: View {
    @Environment(AppState.self) private var app
    let changed: () async -> Void
    @State private var plan: DayPlan?
    @State private var start = Calendar.current.date(bySettingHour: 9, minute: 0, second: 0, of: Date()) ?? Date()
    @State private var end = Calendar.current.date(bySettingHour: 18, minute: 0, second: 0, of: Date()) ?? Date()
    @State private var error: String?
    @State private var focusOn: MyTask?
    @State private var icsURL: URL?

    var body: some View {
        List {
            Section {
                DatePicker("Start", selection: $start, displayedComponents: .hourAndMinute)
                DatePicker("End", selection: $end, displayedComponents: .hourAndMinute)
            } footer: {
                Text("What needs you comes first, then results to review, then overdue, due today and the rest by priority, each for its time estimate. Blocks marked \"default\" use a length by kind because you haven't set one.")
            }
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let p = plan {
                Section {
                    if p.blocks.isEmpty { Text("Nothing to plan for the rest of the day.").foregroundStyle(.secondary) }
                    ForEach(p.blocks) { b in
                        HStack(alignment: .top, spacing: 10) {
                            VStack(alignment: .trailing, spacing: 2) {
                                Text(b.startDate?.formatted(date: .omitted, time: .shortened) ?? "").font(.caption.monospacedDigit().bold())
                                Text(TaskTime.minutes(b.minutes)).font(.caption2).foregroundStyle(.secondary)
                            }
                            .frame(width: 70, alignment: .trailing)
                            RoundedRectangle(cornerRadius: 2).fill(MyTasksTab.kindColor(b.kind)).frame(width: 4)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(b.title).font(.subheadline)
                                HStack(spacing: 6) {
                                    Chip(text: b.verb, color: b.verb == "Decide" ? Theme.gold : b.verb == "Review" ? Theme.ok : Theme.cyan)
                                    if b.overdue { Chip(text: "overdue", color: Theme.bad) }
                                    if b.estimated { Chip(text: "default length", color: .secondary) }
                                    if let l = b.listName { Text("#\(l)").font(.caption2).foregroundStyle(Theme.gold) }
                                }
                            }
                            Spacer(minLength: 0)
                            if b.verb == "Do" {
                                Button { Task { focusOn = try? await app.api?.myTask(b.taskId) } } label: { Image(systemName: "timer") }
                                    .buttonStyle(.borderless).accessibilityLabel("Focus on \(b.title)")
                            }
                        }
                        .accessibilityElement(children: .combine)
                    }
                } header: {
                    Text("\(TaskTime.minutes(max(p.plannedMinutes, 0))) planned · \(TaskTime.minutes(max(p.freeMinutes, 0))) free")
                }
                if !p.later.isEmpty {
                    Section("Doesn't fit today") {
                        ForEach(p.later) { l in LabeledContent(l.title, value: TaskTime.minutes(l.minutes)) }
                    }
                }
                if !p.blocks.isEmpty, let url = icsURL {
                    Section {
                        ShareLink(item: url) { Label("Add to Calendar (.ics)", systemImage: "calendar.badge.plus") }
                    } footer: { Text("Makes a calendar file on this phone. Nothing is added until you open it in Calendar and confirm.") }
                }
            } else if error == nil {
                ProgressView()
            }
        }
        .task(id: "\(Int(start.timeIntervalSince1970 / 60))-\(Int(end.timeIntervalSince1970 / 60))") { await load() }
        .sheet(item: $focusOn) { t in FocusView(task: t) { await load(); await changed() }.presentationDetents([.medium]) }
    }

    private func hhmm(_ d: Date) -> String {
        let c = Calendar.current.dateComponents([.hour, .minute], from: d)
        return String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac to plan the day."; return }
        do {
            let p = try await api.planDay(tz: phoneTZ, start: hhmm(start), end: hhmm(end))
            plan = p
            icsURL = p.blocks.isEmpty ? nil : DayPlanCalendar.file(p)  // written once per plan, not on every redraw
            error = nil
        }
        catch { self.error = failure(error) }
    }
}

// MARK: - focus timer (V6.76)

struct FocusView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let task: MyTask
    let changed: () async -> Void
    @State private var length = 25
    @State private var startedAt: Date?
    @State private var saved: String?
    @State private var error: String?

    var body: some View {
        VStack(spacing: 16) {
            Text(task.title).font(.headline).multilineTextAlignment(.center)
            if let s = startedAt {
                TimelineView(.periodic(from: s, by: 1)) { ctx in
                    let left = max(0, Double(length * 60) - ctx.date.timeIntervalSince(s))
                    VStack(spacing: 6) {
                        Text(Duration.seconds(left).formatted(.time(pattern: .minuteSecond)))
                            .font(.system(size: 54, weight: .bold, design: .rounded).monospacedDigit())
                            .contentTransition(.numericText())
                            .accessibilityLabel("\(Int(left / 60)) minutes left")
                        ProgressView(value: min(1, ctx.date.timeIntervalSince(s) / Double(length * 60))).tint(Theme.cyan)
                    }
                }
                Button { Task { await stop() } } label: { Label("Stop and log the time", systemImage: "stop.circle").frame(maxWidth: .infinity) }
                    .buttonStyle(.borderedProminent)
            } else {
                Picker("Length", selection: $length) {
                    ForEach([15, 25, 45, 60, 90], id: \.self) { Text(TaskTime.minutes($0)).tag($0) }
                }
                .pickerStyle(.segmented)
                Button { startedAt = Date(); saved = nil; Haptics.light() } label: { Label("Start focusing", systemImage: "play.circle").frame(maxWidth: .infinity) }
                    .buttonStyle(.borderedProminent)
            }
            if let saved { Text(saved).font(.caption).foregroundStyle(Theme.ok) }
            if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
            Text("The timer runs on this phone. When you stop, the minutes you spent (up to the length you picked) are logged on the task.")
                .font(.caption2).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding()
    }

    private func stop() async {
        guard let s = startedAt, let api = app.api else { return }
        let mins = min(length, Int(Date().timeIntervalSince(s) / 60))
        startedAt = nil
        guard mins >= 1 else { saved = "Under a minute, so nothing was logged."; return }
        do {
            let total = try await api.logFocus(task.id, minutes: mins, startedAt: s)
            saved = "Logged \(TaskTime.minutes(mins)). \(TaskTime.minutes(total)) on this task so far."
            Haptics.success()
            await changed()
        } catch { self.error = failure(error) }
    }
}

// MARK: - estimate before Do it (V6.78)

struct EstimateLine: View {
    let e: TaskEstimate
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            if let c = e.costUsd {
                Text("Estimate: about $\(String(format: "%.2f", c.typical)) (up to $\(String(format: "%.2f", c.high)))"
                     + (e.minutes.map { ", about \(TaskTime.minutes(max(1, Int($0.typical.rounded()))))" } ?? ""))
                    .font(.caption.bold())
            }
            Text(e.note + (e.budgetUsd.map { " Budget cap $\(String(format: "%.2f", $0))." } ?? "")).font(.caption2).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: - weekly review and bulk actions (V6.84)

struct ReviewView: View {
    @Environment(AppState.self) private var app
    let changed: () async -> Void
    @State private var r: WeeklyReview?
    @State private var picked: Set<String> = []
    @State private var error: String?
    @State private var note: String?
    @State private var busy = false

    var body: some View {
        List(selection: $picked) {
            if let r {
                Section { Text(r.summary).font(.subheadline) } footer: {
                    Text("Tap Select to pick tasks, then mark them done, drop them, or push them to next week in one go.")
                }
                group("Slipped", r.slipped, Theme.bad)
                group("Sitting for two weeks or more", r.stale, Theme.gold)
                group("Due in the next seven days", r.upcoming, Theme.cyan)
                if !r.done.isEmpty {
                    Section("Done this week (\(r.done.count))") {
                        ForEach(r.done) { t in Label(t.title, systemImage: "checkmark.circle.fill").foregroundStyle(.secondary).selectionDisabled() }
                    }
                }
            } else if error == nil { ProgressView() }
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let note { Text(note).foregroundStyle(Theme.ok).font(.caption) }
        }
        .environment(\.editMode, .constant(picked.isEmpty ? .inactive : .active))
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                if let r, picked.isEmpty {
                    Button("Select") { picked = Set((r.slipped + r.stale).map(\.id)) }
                        .disabled((r.slipped + r.stale).isEmpty)
                } else if !picked.isEmpty {
                    Button("Clear") { picked = [] }
                }
            }
            ToolbarItemGroup(placement: .bottomBar) {
                if !picked.isEmpty {
                    Button("Done") { Task { await bulk("done") } }
                    Spacer()
                    Button("Next week") { Task { await bulk("next_week") } }
                    Spacer()
                    Button("Drop", role: .destructive) { Task { await bulk("drop") } }
                }
            }
        }
        .disabled(busy)
        .task { await load() }
    }

    @ViewBuilder private func group(_ name: String, _ tasks: [MyTask], _ color: Color) -> some View {
        if !tasks.isEmpty {
            Section {
                ForEach(tasks) { t in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(t.title)
                        HStack(spacing: 6) {
                            if let d = t.due { Text(TaskTime.label(d)).font(.caption2).foregroundStyle(t.overdue ? Theme.bad : .secondary) }
                            if let l = t.listName { Text("#\(l)").font(.caption2).foregroundStyle(Theme.gold) }
                        }
                    }
                    .tag(t.id)
                }
            } header: { Text("\(name) (\(tasks.count))").foregroundStyle(color) }
        }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac for the weekly review."; return }
        do { r = try await api.weeklyReview(tz: phoneTZ); error = nil } catch { self.error = failure(error) }
    }

    private func bulk(_ action: String) async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        do {
            let out = try await api.bulkTasks(Array(picked), action: action, tz: phoneTZ)
            note = "\(Plural.of(out.changed.count, "task")) updated" + (out.errors.isEmpty ? "." : "; \(out.errors.count) couldn't be changed.")
            picked = []
            Haptics.success()
            await load()
            await changed()
        } catch { self.error = failure(error) }
    }
}

// MARK: - results library (V6.80)

struct ResultsLibraryView: View {
    @Environment(AppState.self) private var app
    @State private var q = ""
    @State private var results: [TaskResult] = []
    @State private var loaded = false
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if loaded && results.isEmpty {
                Text(q.isEmpty ? "No results yet. When the agents finish a task, what they wrote is kept here." : "Nothing matches \"\(q)\".")
                    .foregroundStyle(.secondary)
            }
            ForEach(results) { r in
                NavigationLink { ResultReader(r: r) } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(r.taskTitle ?? r.title).font(.subheadline.bold()).lineLimit(1)
                        Text(r.excerpt).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        HStack(spacing: 6) {
                            Chip(text: r.kind == "personal" ? "other" : r.kind, color: MyTasksTab.kindColor(r.kind))
                            if r.simulated { Chip(text: "simulation", color: Theme.gold) }
                            if let x = r.rating { Image(systemName: x > 0 ? "hand.thumbsup.fill" : "hand.thumbsdown.fill").font(.caption2).foregroundStyle(x > 0 ? Theme.ok : Theme.bad) }
                            if let d = ISODate.parse(r.createdAt) { Text(d.formatted(.relative(presentation: .named))).font(.caption2).foregroundStyle(.secondary) }
                        }
                    }
                }
            }
        }
        .searchable(text: $q, prompt: "Search what the agents wrote")
        .task(id: q) {
            try? await Task.sleep(for: .milliseconds(250))
            guard !Task.isCancelled, let api = app.api else { if app.api == nil { error = "Connect to your Mac to see results." }; return }
            do { results = try await api.taskResults(q: q); loaded = true; error = nil } catch { self.error = failure(error) }
        }
    }
}

private struct ResultReader: View {
    let r: TaskResult
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if r.simulated {
                    Text("Simulation: no AI model was connected, so this is a template, not finished work.").font(.caption).foregroundStyle(Theme.gold)
                }
                Text((try? AttributedString(markdown: r.content, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(r.content))
                    .font(.callout).textSelection(.enabled)
            }
            .padding()
        }
        .navigationTitle(r.taskTitle ?? r.title).navigationBarTitleDisplayMode(.inline)
        .toolbar { ShareLink(item: r.content) }
    }
}

// MARK: - insights (V6.83) with each agent's record (V6.79)

struct InsightsView: View {
    @Environment(AppState.self) private var app
    @State private var i: TaskInsights?
    @State private var agents: [AgentQuality] = []
    @State private var days = 14
    @State private var error: String?

    var body: some View {
        List {
            Picker("Period", selection: $days) { Text("2 weeks").tag(14); Text("30 days").tag(30); Text("60 days").tag(60) }
                .pickerStyle(.segmented)
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let i {
                Section { Text(i.headline).font(.headline) }
                Section("Done and added each day") {
                    Chart(i.series) { d in
                        if let date = d.date {
                            BarMark(x: .value("Day", date, unit: .day), y: .value("Tasks", d.done))
                                .foregroundStyle(by: .value("Series", "Done"))
                            LineMark(x: .value("Day", date, unit: .day), y: .value("Tasks", d.added))
                                .foregroundStyle(by: .value("Series", "Added"))
                                .interpolationMethod(.monotone)
                        }
                    }
                    .chartForegroundStyleScale(["Done": Theme.ok, "Added": Theme.cyan])
                    .frame(height: 180)
                    .accessibilityLabel("\(i.done) done and \(i.added) added over \(i.days) days")
                }
                if i.focusMinutes > 0 {
                    Section("Focus minutes") {
                        Chart(i.series) { d in
                            if let date = d.date { BarMark(x: .value("Day", date, unit: .day), y: .value("Minutes", d.focusMinutes)).foregroundStyle(Theme.violet) }
                        }
                        .frame(height: 120)
                    }
                }
                Section("Numbers") {
                    LabeledContent("Done", value: "\(i.done)")
                    LabeledContent("Added", value: "\(i.added)")
                    LabeledContent("Open now", value: "\(i.open)")
                    LabeledContent("On time", value: i.onTimeRate.map { "\(Int($0 * 100))%" } ?? "No due dates yet")
                    LabeledContent("Focused", value: TaskTime.minutes(i.focusMinutes))
                    LabeledContent("Agent runs", value: "\(i.runs.completed) finished, \(i.runs.failed) failed" + (i.runs.simulated > 0 ? " (\(i.runs.simulated) simulated)" : ""))
                }
            } else if error == nil { ProgressView() }
            if !agents.isEmpty {
                Section {
                    ForEach(agents) { a in
                        VStack(alignment: .leading, spacing: 3) {
                            HStack {
                                Text(a.name).font(.subheadline.bold())
                                Spacer()
                                Label("\(a.up)", systemImage: "hand.thumbsup").foregroundStyle(Theme.ok)
                                Label("\(a.down)", systemImage: "hand.thumbsdown").foregroundStyle(Theme.bad)
                            }
                            .font(.caption)
                            if !a.recentReasons.isEmpty {
                                Text(a.recentReasons.joined(separator: " · ")).font(.caption2).foregroundStyle(.secondary).lineLimit(2)
                            }
                        }
                        .accessibilityElement(children: .combine)
                    }
                } header: { Text("Your ratings by agent") } footer: { Text("Only your own thumbs up and down; nothing is scored automatically.") }
            }
        }
        .task(id: days) { await load() }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac to see insights."; return }
        do {
            i = try await api.taskInsights(tz: phoneTZ, days: days)
            agents = (try? await api.agentQuality()) ?? []
            error = nil
        } catch { self.error = failure(error) }
    }
}

// MARK: - templates (V6.72)

struct TemplatesView: View {
    @Environment(AppState.self) private var app
    let changed: () async -> Void
    @State private var templates: [TaskTemplate] = []
    @State private var loaded = false
    @State private var error: String?
    @State private var note: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let note { Text(note).foregroundStyle(Theme.ok).font(.caption) }
            if loaded && templates.isEmpty {
                Text("No templates yet. Open a task and choose Save as a template to reuse its checklist, list and estimate.")
                    .foregroundStyle(.secondary)
            }
            ForEach(templates) { t in
                HStack {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(t.name).font(.subheadline.bold())
                        HStack(spacing: 6) {
                            Text(t.title).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            if let l = t.listName { Text("#\(l)").font(.caption2).foregroundStyle(Theme.gold) }
                            if let m = t.estimateMinutes { Text(TaskTime.minutes(m)).font(.caption2).foregroundStyle(.secondary) }
                            if !t.items.isEmpty { Label("\(t.items.count)", systemImage: "checklist").font(.caption2).foregroundStyle(.secondary) }
                        }
                    }
                    Spacer()
                    Button("Start a copy") { Task { await use(t) } }.buttonStyle(.bordered)
                }
                .swipeActions {
                    Button(role: .destructive) { Task { await remove(t) } } label: { Label("Delete", systemImage: "trash") }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        guard let api = app.api else { error = "Connect to your Mac to use templates."; return }
        do { templates = try await api.taskTemplates(); loaded = true; error = nil } catch { self.error = failure(error) }
    }

    private func use(_ t: TaskTemplate) async {
        guard let api = app.api else { return }
        do { let task = try await api.useTemplate(t.id); note = "Added \"\(task.title)\" to your list."; Haptics.success(); await changed() }
        catch { self.error = failure(error) }
    }

    private func remove(_ t: TaskTemplate) async {
        guard let api = app.api else { return }
        do { try await api.deleteTemplate(t.id); await load() } catch { self.error = failure(error) }
    }
}

// MARK: - task history (V6.92)

struct TaskHistoryView: View {
    @Environment(AppState.self) private var app
    let taskId: String
    let title: String
    @State private var entries: [TaskHistoryEntry]?
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let entries {
                ForEach(entries) { e in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: Self.icon(e.kind)).foregroundStyle(Self.color(e.kind)).frame(width: 20)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(e.text).font(.subheadline)
                            if let d = e.date {
                                Text(d.formatted(date: .abbreviated, time: .shortened)).font(.caption2).foregroundStyle(.secondary)
                            }
                        }
                    }
                    .accessibilityElement(children: .combine)
                }
            } else if error == nil { ProgressView() }
        }
        .navigationTitle("History").navigationBarTitleDisplayMode(.inline)
        .task {
            guard let api = app.api else { error = "Connect to your Mac to see the history."; return }
            do { entries = try await api.taskHistory(taskId) } catch { self.error = failure(error) }
        }
    }

    static func icon(_ kind: String) -> String {
        switch kind {
        case "created": return "plus.circle"
        case "completed": return "checkmark.circle.fill"
        case "started": return "sparkles"
        case "rated": return "hand.thumbsup"
        case "run_completed": return "flag.checkered"
        case "run_failed", "run_rejected": return "exclamationmark.triangle"
        case "run_cancelled": return "stop.circle"
        default: return "pencil"
        }
    }

    static func color(_ kind: String) -> Color {
        switch kind {
        case "completed", "run_completed": return Theme.ok
        case "run_failed", "run_rejected": return Theme.bad
        case "started": return Theme.violet
        default: return .secondary
        }
    }
}

// MARK: - habits: streaks on repeating tasks (V6.95)

struct HabitsView: View {
    @Environment(AppState.self) private var app
    @State private var habits: [Habit]?
    @State private var error: String?

    var body: some View {
        List {
            if let error { Text(error).foregroundStyle(Theme.bad).font(.caption) }
            if let habits, habits.isEmpty {
                Text("No repeating tasks yet. Add one like \"stretch every day\" or \"pay rent on the 1st of every month\".")
                    .foregroundStyle(.secondary)
            }
            ForEach(habits ?? []) { h in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(h.title).font(.subheadline.bold()).lineLimit(1)
                        Spacer()
                        Label("\(h.current)", systemImage: "flame.fill").font(.caption.bold())
                            .foregroundStyle(h.current > 0 ? Theme.gold : .secondary)
                    }
                    HStack(spacing: 3) {
                        ForEach(Array(h.recent.enumerated()), id: \.offset) { _, o in
                            RoundedRectangle(cornerRadius: 2).fill(Self.color(o.outcome)).frame(width: 14, height: 14)
                                .overlay { if o.outcome == "open" { RoundedRectangle(cornerRadius: 2).stroke(Theme.cyan, lineWidth: 1) } }
                        }
                    }
                    .accessibilityHidden(true)
                    Text("\(h.repeatLabel.capitalizedFirst) · best \(h.best) in a row"
                         + (h.onTimeRate.map { " · \(Int($0 * 100))% on time" } ?? ""))
                        .font(.caption2).foregroundStyle(.secondary)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("\(h.title), \(h.repeatLabel). Streak \(h.current), best \(h.best).")
            }
            if habits?.isEmpty == false {
                Section {} footer: {
                    Text("Green: done by its day. Yellow: done late. Red: dropped. Outlined: the one coming up. Late or dropped starts the count again.")
                }
            }
        }
        .task {
            guard let api = app.api else { error = "Connect to your Mac to see your habits."; return }
            do { habits = try await api.habits(tz: phoneTZ) } catch { self.error = failure(error) }
        }
    }

    static func color(_ outcome: String) -> Color {
        switch outcome {
        case "done": return Theme.ok
        case "late": return Theme.gold
        case "missed": return Theme.bad
        default: return Color.white.opacity(0.08)
        }
    }
}

extension String {
    var capitalizedFirst: String { prefix(1).uppercased() + dropFirst() }
}

// MARK: - morning digest (V6.96)

struct DigestSettingsView: View {
    @Environment(AppState.self) private var app
    @AppStorage(DigestScheduler.enabledKey) private var enabled = false
    @AppStorage(DigestScheduler.minutesKey) private var minutes = 7 * 60 + 30
    @State private var preview: DayDigest?
    @State private var note: String?

    private var time: Binding<Date> {
        Binding(get: { Calendar.current.startOfDay(for: Date()).addingTimeInterval(TimeInterval(minutes * 60)) },
                set: { d in let c = Calendar.current.dateComponents([.hour, .minute], from: d); minutes = (c.hour ?? 7) * 60 + (c.minute ?? 30) })
    }

    var body: some View {
        List {
            Section {
                Toggle("Morning digest", isOn: $enabled)
                if enabled { DatePicker("Time", selection: time, displayedComponents: .hourAndMinute) }
            } footer: {
                Text("One notification a day with what's due, what's overdue and what's waiting for you. It's worked out from your list each time the app updates, so it can be a few hours old; nothing is sent anywhere else.")
            }
            if let p = preview {
                Section("What it would say now") {
                    Text(p.title).font(.subheadline.bold())
                    Text(p.body).font(.caption)
                }
            }
            if let note { Text(note).font(.caption).foregroundStyle(.secondary) }
        }
        .task(id: "\(enabled)-\(minutes)") {
            guard let api = app.api else { note = "Connect to your Mac to set up the digest."; return }
            preview = try? await api.dayDigest(tz: phoneTZ, day: DigestScheduler.nextDay(minutes: minutes))
            note = await DigestScheduler.schedule(api)
        }
    }
}

/// Keeps one pending digest notification, for the next time you chose, with the latest counts.
enum DigestScheduler {
    static let enabledKey = "digestEnabled"
    static let minutesKey = "digestMinutes"
    static let id = "morning-digest"

    static var enabled: Bool { UserDefaults.standard.bool(forKey: enabledKey) }
    static var minutes: Int { (UserDefaults.standard.object(forKey: minutesKey) as? Int) ?? 7 * 60 + 30 }

    /// "today" if the chosen time is still ahead today, otherwise "tomorrow".
    static func nextDay(minutes: Int, now: Date = Date()) -> String {
        let c = Calendar.current.dateComponents([.hour, .minute], from: now)
        return (c.hour ?? 0) * 60 + (c.minute ?? 0) < minutes ? "today" : "tomorrow"
    }

    /// Refreshes the pending digest at most every 15 minutes (called as the list loads and from background refresh).
    static func refreshIfDue(_ api: APIClient) async {
        guard enabled else { return }
        let last = UserDefaults.standard.double(forKey: "digestScheduledAt")
        guard Date().timeIntervalSince1970 - last > 15 * 60 else { return }
        await schedule(api)
    }

    /// Replaces the pending digest. Returns a short status line for the settings screen.
    @discardableResult
    static func schedule(_ api: APIClient) async -> String? {
        let center = UNUserNotificationCenter.current()
        guard enabled else { center.removePendingNotificationRequests(withIdentifiers: [id]); return nil }
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: "digestScheduledAt")
        let m = minutes
        let day = nextDay(minutes: m)
        guard let d = try? await api.dayDigest(tz: TimeZone.current.identifier, day: day) else { return "Couldn't reach your Mac; the last digest stays scheduled." }
        let content = UNMutableNotificationContent()
        content.title = d.title
        content.body = d.body
        content.sound = .default
        content.threadIdentifier = "digest"
        var parts = DateComponents()
        parts.hour = m / 60
        parts.minute = m % 60
        let base = Calendar.current.date(byAdding: .day, value: day == "today" ? 0 : 1, to: Date()) ?? Date()
        let ymd = Calendar.current.dateComponents([.year, .month, .day], from: base)
        parts.year = ymd.year; parts.month = ymd.month; parts.day = ymd.day
        center.removePendingNotificationRequests(withIdentifiers: [id])
        try? await center.add(UNNotificationRequest(identifier: id, content: content,
                                                    trigger: UNCalendarNotificationTrigger(dateMatching: parts, repeats: false)))
        return "Next digest: \(day) at \(String(format: "%d:%02d", m / 60, m % 60))."
    }
}
