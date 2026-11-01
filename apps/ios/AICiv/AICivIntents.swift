import AppIntents
import Foundation

/// Siri and the Shortcuts app (V6.51): "Add a task in AI Civ" and "What's on my list in AI Civ". They talk to the same
/// server as the app, signed in the same way; nothing else is involved.
enum IntentAPI {
    static func client() -> APIClient? {
        let server = UserDefaults.standard.string(forKey: "serverURL") ?? "http://localhost:8000"
        guard let url = URL(string: server) else { return nil }
        return APIClient(baseURL: url, token: Keychain.load())
    }

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
        guard let api = IntentAPI.client() else { return .result(dialog: "AI Civ isn't set up with a server yet.") }
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
        guard let api = IntentAPI.client() else { return .result(dialog: "AI Civ isn't set up with a server yet.") }
        do {
            let t = try await api.todayTasks(tz: TimeZone.current.identifier)
            return .result(dialog: "\(t.s("spoken"))")
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
    }
}
