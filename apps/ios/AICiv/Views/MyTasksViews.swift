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
    @State private var listFilter: String?
    @State private var tool: TaskTool?
    @State private var queued = TaskOutbox.count
    @FocusState private var typing: Bool

    private var tz: String { TimeZone.current.identifier }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if app.connection != .live {
                VStack(alignment: .leading, spacing: 6) {
                    PixelHeader(text: "My tasks", color: Theme.gold, trailing: queued > 0 ? "\(queued) waiting" : nil)
                    Text("Your task list lives on your Mac. Add tasks here and they wait on this phone until you reconnect.")
                        .font(.caption).foregroundStyle(.secondary)
                    HStack(spacing: 8) {
                        TextField("Add a task for later", text: $text)
                            .font(.subheadline).submitLabel(.done).onSubmit { queueOffline() }
                            .padding(.horizontal, 10).padding(.vertical, 8)
                            .background(Color.black.opacity(0.28), in: RoundedRectangle(cornerRadius: 8))
                        Button { queueOffline() } label: { Image(systemName: "tray.and.arrow.down") }
                            .buttonStyle(CityChip(fill: Theme.gold.opacity(0.3)))
                            .disabled(text.trimmingCharacters(in: .whitespaces).count < 2)
                            .accessibilityLabel("Keep the task on this phone until you reconnect")
                    }
                }
                .pixelPanel(Theme.gold.opacity(0.4))
            } else {
                capture
                if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
                tools
                listChips
                list
            }
        }
        .task(id: app.connection == .live ? app.ledger.lastSequence / 3 : -1) { await load() }
        .sheet(item: $open) { t in
            TaskDetailView(taskId: t.id) { await load() }.presentationDetents([.medium, .large])
        }
        .sheet(item: $tool) { k in
            TaskToolSheet(tool: k) { await load() }.presentationDetents([.large])
        }
        .task(id: "\(app.openTaskId ?? "")|\(app.connection == .live)") { await openRequested() }
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
                    if let l = p.listName { Chip(text: "#\(l)", color: Theme.gold) }
                    if let m = p.estimateMinutes { Chip(text: TaskTime.minutes(m), color: .secondary) }
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
        let ref = UUID().uuidString  // if the reply is lost and the outbox sends it again, the Mac still makes one task
        do {
            let task = try await api.addTask(text: t, tz: tz, clientRef: ref)
            text = ""
            preview = nil
            error = nil
            Haptics.light()
            tasks.insert(task, at: 0)
            await load()
        } catch let e as APIError {
            self.error = e.detail
        } catch {
            TaskOutbox.queue(.init(kind: "add", taskId: nil, text: t, ref: ref))  // the Mac didn't answer: keep it for later
            queued = TaskOutbox.count
            text = ""
            preview = nil
            self.error = "Your Mac didn't answer, so the task is waiting on this phone. It's added when you reconnect."
        }
    }

    private func queueOffline() {
        let t = text.trimmingCharacters(in: .whitespaces)
        guard t.count >= 2 else { return }
        TaskOutbox.queue(.init(kind: "add", taskId: nil, text: t))
        queued = TaskOutbox.count
        text = ""
        Haptics.light()
    }

    // MARK: tools and lists

    private var tools: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(TaskTool.allCases) { k in
                    Button { tool = k } label: { Label(k.label, systemImage: k.icon).font(.caption.weight(.semibold)) }
                        .buttonStyle(CityChip(fill: Theme.violet.opacity(0.22)))
                }
            }
        }
    }

    @ViewBuilder private var listChips: some View {
        let names = Array(Set(tasks.compactMap { $0.isOpen ? $0.listName : nil })).sorted()
        if !names.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    Button("All") { withAnimation(Motion.ui) { listFilter = nil } }
                        .buttonStyle(CityChip(fill: listFilter == nil ? Theme.gold.opacity(0.35) : Color.black.opacity(0.25)))
                    ForEach(names, id: \.self) { n in
                        Button("#\(n)") { withAnimation(Motion.ui) { listFilter = listFilter == n ? nil : n } }
                            .buttonStyle(CityChip(fill: listFilter == n ? Theme.gold.opacity(0.35) : Color.black.opacity(0.25)))
                            .accessibilityAddTraits(listFilter == n ? .isSelected : [])
                    }
                }
            }
        }
    }

    // MARK: the list

    @ViewBuilder private var list: some View {
        let shown = listFilter.map { f in tasks.filter { $0.listName == f } } ?? tasks
        let live = shown.filter { $0.stage != "done" && $0.stage != "dropped" }
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
            TaskGroup(name: "Waiting on something", color: Theme.violet, tasks: live.filter { $0.stage == "blocked" }),
            TaskGroup(name: "Snoozed", color: .secondary, tasks: live.filter { $0.stage == "snoozed" }),
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
        let done = shown.filter { $0.stage == "done" }
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
                    if let l = t.listName, listFilter == nil { Text("#\(l)").font(.caption2).foregroundStyle(Theme.gold) }
                    if let m = t.estimateMinutes { Text(TaskTime.minutes(m)).font(.caption2).foregroundStyle(.secondary) }
                    if let n = t.itemsTotal, n > 0 {
                        Label("\(t.itemsDone ?? 0)/\(n)", systemImage: "checklist").font(.caption2).foregroundStyle(.secondary)
                            .accessibilityLabel("\(t.itemsDone ?? 0) of \(n) steps done")
                    }
                    if t.stage == "snoozed", let d = t.snoozed { Text("until \(TaskTime.label(d))").font(.caption2).foregroundStyle(.secondary) }
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
        .contextMenu { if t.isOpen { menu(t) } }
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder private func menu(_ t: MyTask) -> some View {
        Button { Task { await finish(t) } } label: { Label("Mark done", systemImage: "checkmark") }
        if t.stage == "open" || t.stage == "problem" {
            Button { Task { await doIt(t) } } label: { Label("Do it for me", systemImage: "sparkles") }
        }
        Menu {
            ForEach(Snooze.allCases) { s in Button(s.label) { Task { await snooze(t, s.rawValue) } } }
            if t.stage == "snoozed" { Button("Wake it now") { Task { await snooze(t, "wake") } } }
        } label: { Label("Snooze", systemImage: "moon.zzz") }
        Button(role: .destructive) { Task { await drop(t) } } label: { Label("Drop it", systemImage: "xmark.circle") }
    }

    // MARK: actions

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        if TaskOutbox.count > 0, await TaskOutbox.flush(api) > 0 { Haptics.light() }
        queued = TaskOutbox.count
        if let list = try? await api.myTasks() {
            withAnimation(Motion.ui) { tasks = list }
            loaded = true
            TaskReminders.sync(list)
            TaskSpotlight.index(list)
        }
    }

    /// Spotlight or a reminder asked for one task: show it (fetched if it isn't in the list yet).
    private func openRequested() async {
        guard let id = app.openTaskId else { return }
        if let t = tasks.first(where: { $0.id == id }) {
            open = t
        } else if let api = app.api, let t = try? await api.myTask(id) {
            open = t
        } else if app.connection != .live {
            return  // not connected yet: try again when the connection (and this task) changes
        }
        if app.openTaskId == id { app.openTaskId = nil }  // cleared only after it's shown, so the fetch isn't cancelled
    }

    private func snooze(_ t: MyTask, _ preset: String) async {
        guard let api = app.api else { return }
        do { _ = try await api.snoozeTask(t.id, preset: preset, tz: tz); Haptics.light(); await load() }
        catch { self.error = (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
    }

    private func drop(_ t: MyTask) async {
        guard let api = app.api else { return }
        do { _ = try await api.dropTask(t.id); await load() }
        catch { self.error = (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
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
            case "blocked": return ("Waiting", Theme.violet)
            case "snoozed": return ("Snoozed", .secondary)
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

    /// "30m", "1h", "1h 30m".
    static func minutes(_ m: Int) -> String {
        m < 60 ? "\(m)m" : (m % 60 == 0 ? "\(m / 60)h" : "\(m / 60)h \(m % 60)m")
    }
}

enum Snooze: String, CaseIterable, Identifiable {
    case later, tonight, tomorrow, next_week
    var id: String { rawValue }
    var label: String {
        switch self {
        case .later: return "Later today (3 hours)"
        case .tonight: return "Tonight"
        case .tomorrow: return "Tomorrow morning"
        case .next_week: return "Next week"
        }
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
    @State private var newItem = ""
    @State private var listText = ""
    @State private var estimate: TaskEstimate?
    @State private var others: [MyTask] = []
    @State private var focusing = false
    @State private var naming = false
    @State private var templateName = ""
    @State private var reason = ""
    @State private var note: String?

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
                                if on && due <= Date() { due = Self.nextFivePM() }  // a fresh due date starts ahead, never already overdue
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
                    checklist(t)
                    if t.isOpen { organize(t) }
                    if let r = t.result {
                        Section {
                            Text(markdown(r.content)).font(.callout).textSelection(.enabled)
                            ShareLink(item: r.content) { Label("Share or copy", systemImage: "square.and.arrow.up") }
                        } header: { Text("Result") } footer: {
                            Text(t.simulated ? "Simulation: no AI model is connected, so this is a template, not finished work."
                                             : "Written by the agents. Check facts before you use it; nothing has been sent or published.")
                        }
                    }
                    if t.result != nil, t.mission?.status == "COMPLETED" { rating(t) }
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
            .sheet(isPresented: $focusing) {
                if let t { FocusView(task: t) { await load(); await changed() }.presentationDetents([.medium]) }
            }
            .alert("Save as a template", isPresented: $naming) {
                TextField("Name", text: $templateName)
                Button("Save") { Task { await run { _ = try await $0.saveTemplate(taskId, name: templateName); note = "Saved. Start a copy from Templates." } } }
                Button("Cancel", role: .cancel) {}
            } message: { Text("Keeps the title, list, estimate, budget and checklist so you can start a copy any time.") }
            .confirmationDialog("Delete this task?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete", role: .destructive) { Task { await run { try await $0.deleteTask(taskId); dismiss() } } }
            } message: { Text("This removes it from your list. Any run already finished stays in the records.") }
        }
    }

    @ViewBuilder private func actions(_ t: MyTask) -> some View {
        Section {
            switch t.stage {
            case "open", "problem":
                if let e = estimate { EstimateLine(e: e) }
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
                Button { focusing = true } label: { Label("Focus on it", systemImage: "timer") }
                Button { templateName = t.title; naming = true } label: { Label("Save as a template", systemImage: "square.on.square") }
                Button { Task { await run { _ = try await $0.dropTask(taskId) } } } label: { Label("Drop it", systemImage: "xmark.circle") }
            } else {
                Button { Task { await run { _ = try await $0.reopenTask(taskId) } } } label: { Label("Reopen", systemImage: "arrow.uturn.backward") }
            }
            Button(role: .destructive) { confirmDelete = true } label: { Label("Delete", systemImage: "trash") }
            if let note { Text(note).font(.caption).foregroundStyle(Theme.ok) }
        } footer: {
            Text("Do it starts one run under your charter, with the task's budget or the default. Nothing is sent, bought or published without you.")
        }
    }

    // MARK: checklist (V6.68): yours, or the agents' plan steps once they've planned it

    @ViewBuilder private func checklist(_ t: MyTask) -> some View {
        let items = t.items ?? []
        if !items.isEmpty || t.isOpen {
            Section {
                ForEach(items) { i in
                    HStack {
                        Button { Task { await run { _ = try await $0.setItem(taskId, item: i.id, done: !i.done) } } } label: {
                            Image(systemName: i.done ? "checkmark.square.fill" : "square").foregroundStyle(i.done ? Theme.ok : .secondary)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(i.done ? "Done: \(i.text)" : "Tick \(i.text)")
                        Text(i.text).strikethrough(i.done).foregroundStyle(i.done ? .secondary : Theme.ink)
                        Spacer()
                        if i.fromAgents { Image(systemName: "sparkles").font(.caption2).foregroundStyle(.secondary).accessibilityLabel("From the agents' plan") }
                    }
                    .swipeActions { Button(role: .destructive) { Task { await run { _ = try await $0.removeItem(taskId, item: i.id) } } } label: { Label("Remove", systemImage: "trash") } }
                }
                if t.isOpen {
                    HStack {
                        TextField("Add a step", text: $newItem).onSubmit { addStep() }
                        Button("Add") { addStep() }.disabled(newItem.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            } header: {
                Text(items.isEmpty ? "Checklist" : "Checklist \(items.filter(\.done).count)/\(items.count)")
            } footer: {
                if items.contains(where: \.fromAgents) { Text("Steps marked ✦ came from the agents' plan. Only you tick them.") }
            }
        }
    }

    private func addStep() {
        let s = newItem.trimmingCharacters(in: .whitespaces)
        guard !s.isEmpty else { return }
        newItem = ""
        Task { await run { _ = try await $0.addItems(taskId, [s]) } }
    }

    // MARK: list, estimate, waiting on, snooze (V6.69–V6.71, V6.73)

    @ViewBuilder private func organize(_ t: MyTask) -> some View {
        Section("Organize") {
            HStack {
                Text("List")
                TextField("#home", text: $listText).multilineTextAlignment(.trailing)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .onSubmit { Task { await edit(["list_name": listText.trimmingCharacters(in: .whitespaces)]) } }
            }
            Picker("Time it takes", selection: Binding(get: { t.estimateMinutes ?? 0 }, set: { v in Task { await edit(["estimate_minutes": v == 0 ? NSNull() as Any : v as Any]) } })) {
                Text("Not set").tag(0)
                ForEach([15, 30, 45, 60, 90, 120, 180, 240], id: \.self) { m in Text(TaskTime.minutes(m)).tag(m) }
                if let m = t.estimateMinutes, ![15, 30, 45, 60, 90, 120, 180, 240].contains(m) { Text(TaskTime.minutes(m)).tag(m) }
            }
            Picker("Waiting on", selection: Binding(get: { t.blockedBy ?? "" }, set: { v in Task { await edit(["blocked_by": v.isEmpty ? NSNull() as Any : v as Any]) } })) {
                Text("Nothing").tag("")
                if let b = t.blockedBy, !others.contains(where: { $0.id == b }) { Text(t.blockedByTitle ?? "Another task").tag(b) }
                ForEach(others) { o in Text(o.title).lineLimit(1).tag(o.id) }
            }
            Menu {
                ForEach(Snooze.allCases) { s in Button(s.label) { Task { await run { _ = try await $0.snoozeTask(taskId, preset: s.rawValue, tz: tz) } } } }
                if t.stage == "snoozed" { Button("Wake it now") { Task { await run { _ = try await $0.snoozeTask(taskId, preset: "wake", tz: tz) } } } }
            } label: {
                if let d = t.snoozed { Label("Snoozed until \(TaskTime.label(d))", systemImage: "moon.zzz") }
                else { Label("Snooze", systemImage: "moon.zzz") }
            }
            if let m = t.focusMinutes, m > 0 { LabeledContent("Focused so far", value: TaskTime.minutes(m)) }
        }
    }

    // MARK: rating (V6.79)

    @ViewBuilder private func rating(_ t: MyTask) -> some View {
        Section {
            if let f = t.feedback {
                Label(f.rating > 0 ? "You rated this useful" : "You rated this not useful\(f.reason.map { ": \($0)" } ?? "")",
                      systemImage: f.rating > 0 ? "hand.thumbsup.fill" : "hand.thumbsdown.fill")
                    .foregroundStyle(f.rating > 0 ? Theme.ok : Theme.bad)
            }
            TextField("Why? (optional)", text: $reason)
            HStack {
                Button { Task { await rate(1) } } label: { Label("Useful", systemImage: "hand.thumbsup") }.buttonStyle(.bordered)
                Button { Task { await rate(-1) } } label: { Label("Not useful", systemImage: "hand.thumbsdown") }.buttonStyle(.bordered)
            }
        } header: { Text("Rate the result") } footer: {
            Text("Ratings count toward each agent's record in Insights. They don't change the result or start anything.")
        }
    }

    private func rate(_ r: Int) async {
        let why = reason.trimmingCharacters(in: .whitespaces)
        await run { try await $0.rateResult(taskId, rating: r, reason: why.isEmpty ? nil : why) }
        reason = ""
    }

    static func nextFivePM(after now: Date = Date()) -> Date {
        let cal = Calendar.current
        let today = cal.date(bySettingHour: 17, minute: 0, second: 0, of: now) ?? now.addingTimeInterval(3600)
        return today > now ? today : cal.date(byAdding: .day, value: 1, to: today) ?? today
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
            listText = x.listName.map { "#\($0)" } ?? ""
            hasDue = x.due != nil
            if let d = x.due { due = d }
            if x.isOpen && (x.stage == "open" || x.stage == "problem") { estimate = try? await api.taskEstimate(taskId) }
            if x.isOpen, others.isEmpty {
                others = ((try? await api.myTasks()) ?? []).filter { $0.isOpen && $0.id != taskId }.prefix(40).map { $0 }
            }
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
            return ("\(prefix)v2-\(t.id)-\(Int(d.timeIntervalSince1970))", t, d)
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
                c.categoryIdentifier = AppDelegate.taskCategory  // Done (after unlocking), Snooze 1 hour, Open
                c.userInfo = ["task_id": t.id]
                let parts = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: d)
                center.add(UNNotificationRequest(identifier: id, content: c, trigger: UNCalendarNotificationTrigger(dateMatching: parts, repeats: false)))
            }
        }
    }
}
