import AppIntents
import Foundation

/// Siri and the Shortcuts app (V6.51): "Add a task in AI Civ" and "What's on my list in AI Civ". They talk to the same
/// server as the app, signed in the same way; nothing else is involved.
enum IntentAPI {
    static func client() async -> APIClient? { await SupabaseAuth.backgroundClient() }

    static func problem(_ error: Error) -> String {
        if let e = error as? APIError, e.status == 401 || e.status == 403 { return "Open AI Civ and sign in first." }
        return "I couldn't reach your Mac. Make sure the AI Civ server is running and you're on the same network."
    }
}

struct AddTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "Add a task"
    static var description = IntentDescription("Adds a task to your AI Civ list. Say it the way you would to a person: \"draft the Echo blurb by Friday\".")

    @Parameter(title: "Task", requestValueDialog: "What's the task?")
    var text: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let api = await IntentAPI.client() else { return .result(dialog: "AI Civ isn't set up with a server yet.") }
        do {
            let t = try await api.addTask(text: text, tz: TimeZone.current.identifier)
            let due = t.due.map { ", due \(TaskTime.label($0))" } ?? ""
            return .result(dialog: "Added \(t.title)\(due).")
        } catch {
            return .result(dialog: "\(IntentAPI.problem(error))")
        }
    }
}

struct ListTasksIntent: AppIntent {
    static var title: LocalizedStringResource = "What's on my list"
    static var description = IntentDescription("Reads what needs you today from your AI Civ task list.")

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let api = await IntentAPI.client() else { return .result(dialog: "AI Civ isn't set up with a server yet.") }
        do {
            let t = try await api.todayTasks(tz: TimeZone.current.identifier)
            return .result(dialog: "\(t.s("spoken"))")
        } catch {
            return .result(dialog: "\(IntentAPI.problem(error))")
        }
    }
}

// MARK: - V6.97: finish, snooze and plan by voice

/// The open task a spoken name points at (the best search match), or nil.
private func spokenTask(_ api: APIClient, _ name: String) async throws -> MyTask? {
    let filler: Set<String> = ["the", "a", "an", "my", "task", "to", "for", "of", "on", "and", "that", "one", "thing"]
    let words = name.lowercased().split { !$0.isLetter && !$0.isNumber }.map(String.init).filter { !filler.contains($0) }
    if let t = try await api.searchTasks(words.joined(separator: " ")).first(where: { $0.isOpen }) { return t }
    // no task has every word: take the open task that shares the most words with what was said
    let open = try await api.myTasks().filter { $0.isOpen }
    let scored = open.map { t -> (MyTask, Int) in
        let title = Set(t.title.lowercased().split { !$0.isLetter && !$0.isNumber }.map(String.init))
        return (t, words.filter { title.contains($0) }.count)
    }
    return scored.filter { $0.1 > 0 }.max { $0.1 < $1.1 }?.0
}

struct CompleteTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "Mark a task done"
    static var description = IntentDescription("Marks one of your AI Civ tasks done, after you confirm. Your iPhone has to be unlocked.")
    static var authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

    @Parameter(title: "Task", requestValueDialog: "Which task?")
    var name: String

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let api = await IntentAPI.client() else { return .result(dialog: "AI Civ isn't set up with a server yet.") }
        do {
            guard let t = try await spokenTask(api, name) else { return .result(dialog: "I couldn't find an open task called \(name).") }
            try await requestConfirmation(result: .result(dialog: "Mark \"\(t.title)\" done?"))
            let next = try await api.finishTask(t.id, tz: TimeZone.current.identifier)
            let more = next?.due.map { " The next one is \(TaskTime.label($0))." } ?? ""
            return .result(dialog: "Done: \(t.title).\(more)")
        } catch let e as APIError {
            return .result(dialog: "\(IntentAPI.problem(e))")
        } catch let e as URLError {
            return .result(dialog: "\(IntentAPI.problem(e))")
        }
    }
}

enum SnoozeChoice: String, AppEnum {
    case later, tonight, tomorrow, nextWeek = "next_week"
    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Snooze until"
    static var caseDisplayRepresentations: [SnoozeChoice: DisplayRepresentation] = [
        .later: "Later today", .tonight: "Tonight", .tomorrow: "Tomorrow morning", .nextWeek: "Next week",
    ]
}

struct SnoozeTaskIntent: AppIntent {
    static var title: LocalizedStringResource = "Snooze a task"
    static var description = IntentDescription("Sets one of your AI Civ tasks aside until later today, tonight, tomorrow or next week.")

    @Parameter(title: "Task", requestValueDialog: "Which task?")
    var name: String
    @Parameter(title: "Until", default: .tomorrow)
    var until: SnoozeChoice

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let api = await IntentAPI.client() else { return .result(dialog: "AI Civ isn't set up with a server yet.") }
        do {
            guard let t = try await spokenTask(api, name) else { return .result(dialog: "I couldn't find an open task called \(name).") }
            let s = try await api.snoozeTask(t.id, preset: until.rawValue, tz: TimeZone.current.identifier)
            let when = s.snoozed.map { TaskTime.label($0) } ?? "later"
            return .result(dialog: "Snoozed \(t.title) until \(when).")
        } catch {
            return .result(dialog: "\(IntentAPI.problem(error))")
        }
    }
}

struct PlanMyDayIntent: AppIntent {
    static var title: LocalizedStringResource = "Plan my day"
    static var description = IntentDescription("Tells you what's due today, what's overdue and what's waiting for you.")

    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let api = await IntentAPI.client() else { return .result(dialog: "AI Civ isn't set up with a server yet.") }
        do {
            let d = try await api.dayDigest(tz: TimeZone.current.identifier, day: "today")
            return .result(dialog: "\(d.title). \(d.body)")
        } catch {
            return .result(dialog: "\(IntentAPI.problem(error))")
        }
    }
}

struct AICivShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: AddTaskIntent(), phrases: ["Add a task in \(.applicationName)", "Add to my \(.applicationName) list"],
                    shortTitle: "Add a task", systemImageName: "plus.circle")
        AppShortcut(intent: ListTasksIntent(), phrases: ["What's on my list in \(.applicationName)", "My tasks in \(.applicationName)"],
                    shortTitle: "My tasks", systemImageName: "checklist")
        AppShortcut(intent: CompleteTaskIntent(), phrases: ["Mark a task done in \(.applicationName)", "Finish a task in \(.applicationName)"],
                    shortTitle: "Mark done", systemImageName: "checkmark.circle")
        AppShortcut(intent: SnoozeTaskIntent(), phrases: ["Snooze a task in \(.applicationName)"],
                    shortTitle: "Snooze a task", systemImageName: "moon.zzz")
        AppShortcut(intent: PlanMyDayIntent(), phrases: ["Plan my day in \(.applicationName)", "What's my day in \(.applicationName)"],
                    shortTitle: "Plan my day", systemImageName: "sun.horizon")
    }
}
