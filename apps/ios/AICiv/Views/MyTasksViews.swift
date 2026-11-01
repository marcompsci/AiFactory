import SwiftUI
import UserNotifications

/// Your task list (V6.51) in the command sheet's Tasks tab: type a task the way you'd say it, see what will be saved,
/// then hand it to the agents with Do it and review what comes back. Only you mark a task done.
struct MyTasksTab: View {
    @Environment(AppState.self) private var app
    @State private var tasks: [MyTask] = []
    @State private var loaded = false
    @State private var text = ""
    @State private var preview: TaskPreview?
    @State private var adding = false
    @State private var busy: String?
    @State private var error: String?
    @State private var open: MyTask?
    @State private var showDone = false
    @FocusState private var typing: Bool

    private var tz: String { TimeZone.current.identifier }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if app.connection != .live {
                VStack(alignment: .leading, spacing: 6) {
                    PixelHeader(text: "My tasks", color: Theme.gold)
                    Text("Your task list lives on your Mac. Connect to it to add tasks and hand them to the agents.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .pixelPanel(Theme.gold.opacity(0.4))
            } else {
                capture
                if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
                list
            }
        }
        .task(id: app.connection == .live ? app.ledger.lastSequence / 3 : -1) { await load() }
        .sheet(item: $open) { t in
            TaskDetailView(taskId: t.id) { await load() }.presentationDetents([.medium, .large])
        }
    }

    // MARK: quick capture

    private var capture: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                TextField("Add a task: draft the Echo blurb by Friday $1", text: $text)
                    .font(.subheadline).focused($typing).submitLabel(.done)
                    .onSubmit { Task { await add() } }
                    .padding(.horizontal, 10).padding(.vertical, 8)
                    .background(Color.black.opacity(0.28), in: RoundedRectangle(cornerRadius: 8))
                Button { Task { await add() } } label: { Image(systemName: adding ? "hourglass" : "plus") }
                    .buttonStyle(CityChip(fill: Theme.cyan.opacity(0.3)))
                    .disabled(adding || text.trimmingCharacters(in: .whitespaces).count < 2)
                    .accessibilityLabel("Add the task")
            }
            if let p = preview, !text.isEmpty {
                HStack(spacing: 6) {
                    Text(p.title).font(.caption.bold()).lineLimit(1)
                    if let d = p.dueLabel { Chip(text: d, color: Theme.cyan) }
                    Chip(text: p.kind, color: Self.kindColor(p.kind))
                    if p.priority != "normal" { Chip(text: p.priority, color: p.priority == "urgent" ? Theme.bad : .secondary) }
                    if let b = p.budgetUsd { Chip(text: String(format: "$%.2f", b), color: Theme.ok) }
                    if p.repeats != "none" { Chip(text: p.repeats, color: Theme.violet) }
                }
                .transition(.opacity)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Will add: \(p.title)\(p.dueLabel.map { ", due \($0)" } ?? "")")
            }
        }
        .task(id: text) {
            let t = text.trimmingCharacters(in: .whitespaces)
            guard t.count >= 2, let api = app.api else { preview = nil; return }
            try? await Task.sleep(for: .milliseconds(300))  // wait for a pause in typing
            guard !Task.isCancelled else { return }
            preview = try? await api.previewTask(t, tz: tz)
        }
    }

    private func add() async {
        let t = text.trimmingCharacters(in: .whitespaces)
        guard t.count >= 2, let api = app.api else { return }
        adding = true
        defer { adding = false }
        do {
            let task = try await api.addTask(text: t, tz: tz)
            text = ""
            preview = nil
            error = nil
            Haptics.light()
            tasks.insert(task, at: 0)
            await load()
        } catch { self.error = (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
    }

    // MARK: the list

    @ViewBuilder private var list: some View {
        let live = tasks.filter { $0.stage != "done" && $0.stage != "dropped" }
        let now = Date()
        let endOfDay = Calendar.current.startOfDay(for: now).addingTimeInterval(86_400)
        let pending = live.filter { $0.stage == "open" || $0.stage == "working" }
        let groups: [TaskGroup] = [
            TaskGroup(name: "Needs you", color: Theme.gold, tasks: live.filter { $0.stage == "needs_you" }),
            TaskGroup(name: "Ready to review", color: Theme.ok, tasks: live.filter { $0.stage == "review" || $0.stage == "problem" }),
            TaskGroup(name: "Overdue", color: Theme.bad, tasks: pending.filter { $0.overdue }),
            TaskGroup(name: "Today", color: Theme.cyan, tasks: pending.filter { t in !t.overdue && (t.due.map { $0 < endOfDay } ?? false) }),
            TaskGroup(name: "Coming up", color: Theme.ink, tasks: pending.filter { t in t.due.map { $0 >= endOfDay } ?? false }),
            TaskGroup(name: "Anytime", color: Theme.ink.opacity(0.7), tasks: pending.filter { $0.due == nil }),
        ]
        if loaded && live.isEmpty {
            Text("Nothing on your list. Add something above, or say \"add a task\" to any agent in the City.")
                .font(.caption).foregroundStyle(.secondary)
        }
        ForEach(groups.filter { !$0.tasks.isEmpty }) { g in
            VStack(alignment: .leading, spacing: 4) {
                PixelHeader(text: g.name, color: g.color, trailing: "\(g.tasks.count)")
                ForEach(g.tasks) { t in row(t) }
            }
        }
        let done = tasks.filter { $0.stage == "done" }
        if !done.isEmpty {
            DisclosureGroup(isExpanded: $showDone) {
                ForEach(done.prefix(20)) { t in row(t) }
            } label: {
                Text("Done (\(done.count))").font(.caption.bold()).foregroundStyle(.secondary)
            }
            .tint(.secondary)
        }
    }

    private func row(_ t: MyTask) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Button { Task { await finish(t) } } label: {
                Image(systemName: t.stage == "done" ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 20)).foregroundStyle(t.stage == "done" ? Theme.ok : Theme.ink.opacity(0.5))
            }
            .buttonStyle(PressableStyle())
            .disabled(t.stage == "done" || busy == t.id)
            .accessibilityLabel(t.stage == "done" ? "Done" : "Mark \(t.title) done")
            VStack(alignment: .leading, spacing: 3) {
                Text(t.title).font(.subheadline).foregroundStyle(t.stage == "done" ? .secondary : Theme.ink)
                    .strikethrough(t.stage == "done").lineLimit(2)
                HStack(spacing: 6) {
                    StageChip(stage: t.stage, simulated: t.simulated)
                    if let d = t.due { Text(TaskTime.label(d)).font(.caption2).foregroundStyle(t.overdue ? Theme.bad : .secondary) }
                    if t.repeats != "none" { Image(systemName: "repeat").font(.caption2).foregroundStyle(.secondary) }
                    if t.priority == "urgent" { Image(systemName: "exclamationmark").font(.caption2.bold()).foregroundStyle(Theme.bad) }
                }
            }
            Spacer(minLength: 4)
            if t.isOpen && (t.stage == "open" || t.stage == "problem") {
                Button(busy == t.id ? "…" : "Do it") { Task { await doIt(t) } }
                    .buttonStyle(CityChip(fill: Theme.cyan.opacity(0.22)))
                    .disabled(busy != nil)
                    .accessibilityHint("Hands the task to the agents. They bring the result back for you to review.")
            } else if t.stage == "review" {
                Button("Review") { open = t }.buttonStyle(CityChip(fill: Theme.ok.opacity(0.25)))
            }
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
        .onTapGesture { open = t }
        .accessibilityElement(children: .contain)
    }

    // MARK: actions

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        if let list = try? await api.myTasks() {
            withAnimation(Motion.ui) { tasks = list }
            loaded = true
            TaskReminders.sync(list)
        }
    }

    private func finish(_ t: MyTask) async {
        guard let api = app.api else { return }
        busy = t.id
        defer { busy = nil }
        do {
            try await api.finishTask(t.id, tz: tz)
            Haptics.success()
            await load()
        } catch { self.error = (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
    }

    private func doIt(_ t: MyTask) async {
        guard let api = app.api else { return }
        busy = t.id
        defer { busy = nil }
        do {
            _ = try await api.doTask(t.id)
            Haptics.light()
            await load()
        } catch { Haptics.warning(); self.error = (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
    }

    static func kindColor(_ k: String) -> Color {
        switch k {
        case "code": return Color(hex: 0xFF9A3D)
        case "research": return Color(hex: 0x5B8CFF)
        case "write": return Color(hex: 0xFF4FB0)
        default: return Theme.violet
        }
    }
}

struct TaskGroup: Identifiable {
    let name: String
    let color: Color
    let tasks: [MyTask]
    var id: String { name }
}

struct Chip: View {
    let text: String
    let color: Color
    var body: some View {
        Text(text).font(.caption2.weight(.semibold)).foregroundStyle(color)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(color.opacity(0.14), in: Capsule())
    }
}

struct StageChip: View {
    let stage: String
    var simulated = false
    var body: some View {
        let (text, color): (String, Color) = {
            switch stage {
            case "working": return ("Working", Theme.cyan)
            case "needs_you": return ("Needs you", Theme.gold)
            case "review": return (simulated ? "Template ready" : "Ready to review", Theme.ok)
            case "problem": return ("Run stopped", Theme.bad)
            case "done": return ("Done", .secondary)
            case "dropped": return ("Dropped", .secondary)
            default: return ("To do", Theme.ink.opacity(0.6))
            }
        }()
        Chip(text: text, color: color)
    }
}

enum TaskTime {
    /// "today 5:00 PM", "tomorrow 9:00 AM", "Fri 5:00 PM", "Nov 14", in this phone's time zone.
    static func label(_ d: Date, now: Date = Date()) -> String {
        let cal = Calendar.current
        let time = d.formatted(date: .omitted, time: .shortened)
        if cal.isDateInToday(d) { return "today \(time)" }
        if cal.isDateInTomorrow(d) { return "tomorrow \(time)" }
        if cal.isDateInYesterday(d) { return "yesterday \(time)" }
        let days = cal.dateComponents([.day], from: cal.startOfDay(for: now), to: cal.startOfDay(for: d)).day ?? 0
        if days > 0 && days < 7 { return "\(d.formatted(.dateTime.weekday(.abbreviated))) \(time)" }
        return d.formatted(.dateTime.month(.abbreviated).day())
    }
}

/// One task: what it is, when it's due, the plan and the result the agents wrote, and what you can do next.
struct TaskDetailView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let taskId: String
    let changed: () async -> Void
    @State private var t: MyTask?
    @State private var notes = ""
    @State private var redoNote = ""
    @State private var due = Date()
    @State private var hasDue = false
    @State private var busy = false
    @State private var error: String?
    @State private var confirmDelete = false

    private var tz: String { TimeZone.current.identifier }

    var body: some View {
        NavigationStack {
            Form {
                if let t {
                    Section {
                        Text(t.title).font(.headline)
                        HStack(spacing: 6) {
                            StageChip(stage: t.stage, simulated: t.simulated)
                            Chip(text: t.kind, color: MyTasksTab.kindColor(t.kind))
                            if t.runs > 0 { Text(Plural.of(t.runs, "run")).font(.caption2).foregroundStyle(.secondary) }
                        }
                        if let m = t.mission, let spent = m.spentUsdEstimated {
                            Text("Latest run: \(Format.human(m.status).lowercased()) · est. $\(String(format: "%.2f", spent)) of $\(String(format: "%.2f", m.budgetUsd ?? 0))")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if t.isOpen {
                        Section("Details") {
                            Picker("Priority", selection: Binding(get: { t.priority }, set: { v in Task { await edit(["priority": v]) } })) {
                                Text("Urgent").tag("urgent"); Text("Normal").tag("normal"); Text("Low").tag("low")
                            }
                            Picker("Kind", selection: Binding(get: { t.kind }, set: { v in Task { await edit(["kind": v]) } })) {
                                Text("Write").tag("write"); Text("Research").tag("research"); Text("Code").tag("code"); Text("Other").tag("personal")
                            }
                            Picker("Repeats", selection: Binding(get: { t.repeats }, set: { v in Task { await edit(["repeat": v]) } })) {
                                Text("Never").tag("none"); Text("Every day").tag("daily"); Text("Weekdays").tag("weekdays"); Text("Every week").tag("weekly")
                            }
                            Toggle("Due date", isOn: Binding(get: { hasDue }, set: { on in
                                hasDue = on
                                Task { await edit(on ? ["due_at": ISO8601DateFormatter().string(from: due)] : ["clear_due": true]) }
                            }))
                            if hasDue {
                                DatePicker("Due", selection: $due).onChange(of: due) { _, d in
                                    Task { await edit(["due_at": ISO8601DateFormatter().string(from: d)]) }
                                }
                            }
                            TextField("Notes for the agents", text: $notes, axis: .vertical).lineLimit(2...6)
                                .onSubmit { Task { await edit(["notes": notes]) } }
                            if notes != t.notes {
                                Button("Save notes") { Task { await edit(["notes": notes]) } }
                            }
                        }
                    }
                    if let r = t.result {
                        Section {
                            Text(markdown(r.content)).font(.callout).textSelection(.enabled)
                            ShareLink(item: r.content) { Label("Share or copy", systemImage: "square.and.arrow.up") }
                        } header: { Text("Result") } footer: {
                            Text(t.simulated ? "Simulation: no AI model is connected, so this is a template, not finished work."
                                             : "Written by the agents. Check facts before you use it; nothing has been sent or published.")
                        }
                    }
                    if let p = t.plan {
                        Section("Plan") { Text(markdown(p.content)).font(.caption) }
                    }
                    actions(t)
                    if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
                } else {
                    ProgressView()
                }
            }
            .navigationTitle("Task").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Close") { dismiss() } } }
            .task { await load() }
            .task(id: t?.stage == "working" ? app.ledger.lastSequence : -1) { if t?.stage == "working" { await load() } }
            .confirmationDialog("Delete this task?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete", role: .destructive) { Task { await run { try await $0.deleteTask(taskId); dismiss() } } }
            } message: { Text("This removes it from your list. Any run already finished stays in the records.") }
        }
    }

    @ViewBuilder private func actions(_ t: MyTask) -> some View {
        Section {
            switch t.stage {
            case "open", "problem":
                Button { Task { await run { _ = try await $0.doTask(taskId) } } } label: {
                    Label(t.stage == "problem" ? "Try again" : "Do it for me", systemImage: "sparkles")
                }
                .disabled(busy)
            case "review":
                Button { Task { await run { try await $0.finishTask(taskId, tz: tz); dismiss() } } } label: {
                    Label("Accept and mark done", systemImage: "checkmark.circle")
                }
                TextField("What should change?", text: $redoNote, axis: .vertical).lineLimit(1...4)
                Button { Task { await run { _ = try await $0.redoTask(taskId, note: redoNote); redoNote = "" } } } label: {
                    Label("Redo with this note", systemImage: "arrow.clockwise")
                }
                .disabled(busy || redoNote.trimmingCharacters(in: .whitespaces).isEmpty)
            case "needs_you":
                Button { dismiss(); app.openTab = "owner" } label: { Label("Open the Owner tab to decide", systemImage: "building.columns") }
            case "working":
                Label("The agents are on it", systemImage: "gearshape.2").foregroundStyle(.secondary)
            default:
                EmptyView()
            }
            if t.isOpen && t.stage != "review" {
                Button { Task { await run { try await $0.finishTask(taskId, tz: tz); dismiss() } } } label: {
                    Label("Mark done", systemImage: "checkmark")
                }
            }
            if t.isOpen {
                Button { Task { await run { _ = try await $0.dropTask(taskId) } } } label: { Label("Drop it", systemImage: "xmark.circle") }
            } else {
                Button { Task { await run { _ = try await $0.reopenTask(taskId) } } } label: { Label("Reopen", systemImage: "arrow.uturn.backward") }
            }
            Button(role: .destructive) { confirmDelete = true } label: { Label("Delete", systemImage: "trash") }
        } footer: {
            Text("Do it starts one run under your charter, with the task's budget or the default. Nothing is sent, bought or published without you.")
        }
    }

    private func markdown(_ s: String) -> AttributedString {
        (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s)
    }

    private func load() async {
        guard let api = app.api else { return }
        do {
            let x = try await api.myTask(taskId)
            t = x
            notes = x.notes
            hasDue = x.due != nil
            if let d = x.due { due = d }
        } catch { self.error = (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
    }

    private func edit(_ fields: [String: Any?]) async {
        await run { _ = try await $0.editTask(taskId, fields) }
    }

    private func run(_ action: (APIClient) async throws -> Void) async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        do {
            try await action(api)
            error = nil
            Haptics.light()
            await load()
            await changed()
        } catch { Haptics.warning(); self.error = (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
    }
}

/// Local reminders at each open task's due time (scheduled on this phone; nothing is sent anywhere).
enum TaskReminders {
    static let prefix = "task-"

    static func sync(_ tasks: [MyTask]) {
        let now = Date()
        let wanted: [(String, MyTask, Date)] = tasks.compactMap { t in
            guard t.isOpen, t.stage == "open" || t.stage == "working", let d = t.due, d > now, d < now.addingTimeInterval(30 * 86_400) else { return nil }
            return ("\(prefix)\(t.id)-\(Int(d.timeIntervalSince1970))", t, d)
        }
        .sorted { $0.2 < $1.2 }
        .prefix(40).map { $0 }
        let center = UNUserNotificationCenter.current()
        center.getPendingNotificationRequests { pending in
            let have = Set(pending.map(\.identifier).filter { $0.hasPrefix(prefix) })
            let want = Set(wanted.map(\.0))
            center.removePendingNotificationRequests(withIdentifiers: Array(have.subtracting(want)))
            for (id, t, d) in wanted where !have.contains(id) {
                let c = UNMutableNotificationContent()
                c.title = t.priority == "urgent" ? "Due now (urgent)" : "Due now"
                c.body = t.title
                c.sound = .default
                let parts = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: d)
                center.add(UNNotificationRequest(identifier: id, content: c, trigger: UNCalendarNotificationTrigger(dateMatching: parts, repeats: false)))
            }
        }
    }
}
