import CoreSpotlight
import SwiftUI
import UIKit
import UniformTypeIdentifiers
import UserNotifications

/// V6.81: reminder notifications you can act on without opening the app. Done asks for Face ID / passcode first
/// (iOS unlocks the phone before running it), Snooze 1h snoozes it on your Mac, Open shows the task.
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    static let taskCategory = "TASK_DUE"

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        // V6.97: long-press the app icon
        application.shortcutItems = [
            UIApplicationShortcutItem(type: "add-task", localizedTitle: "Add a task", localizedSubtitle: nil,
                                      icon: UIApplicationShortcutIcon(systemImageName: "plus.circle"), userInfo: nil),
            UIApplicationShortcutItem(type: "plan", localizedTitle: "Plan my day", localizedSubtitle: nil,
                                      icon: UIApplicationShortcutIcon(systemImageName: "calendar.day.timeline.left"), userInfo: nil),
        ]
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        let done = UNNotificationAction(identifier: "done", title: "Done", options: [.authenticationRequired])
        let snooze = UNNotificationAction(identifier: "snooze1h", title: "Snooze 1 hour", options: [])
        let open = UNNotificationAction(identifier: "open", title: "Open", options: [.foreground])
        center.setNotificationCategories([UNNotificationCategory(identifier: Self.taskCategory, actions: [done, snooze, open],
                                                                 intentIdentifiers: [], options: [])])
        return true
    }

    func application(_ application: UIApplication, configurationForConnecting connectingSceneSession: UISceneSession,
                     options: UIScene.ConnectionOptions) -> UISceneConfiguration {
        let config = UISceneConfiguration(name: nil, sessionRole: connectingSceneSession.role)
        config.delegateClass = QuickActionSceneDelegate.self
        return config
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .sound, .list]
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        guard let id = response.notification.request.content.userInfo["task_id"] as? String else { return }
        switch response.actionIdentifier {
        case "done": await TaskActions.run(id: id, action: "done")
        case "snooze1h": await TaskActions.run(id: id, action: "snooze1h")
        default: await MainActor.run { TaskActions.pendingOpen = id; NotificationCenter.default.post(name: TaskActions.openNote, object: id) }
        }
    }
}

/// Runs a reminder's action straight against your Mac, the same way background refresh does. If the Mac can't be
/// reached the action waits in the outbox and runs the next time the app connects; nothing is lost or guessed.
enum TaskActions {
    static let openNote = Notification.Name("openTask")
    static let quickNote = Notification.Name("quickAction")
    @MainActor static var pendingOpen: String?
    @MainActor static var pendingQuick: String?

    static func client() async -> APIClient? { await SupabaseAuth.backgroundClient() }

    static func run(id: String, action: String) async {
        let tz = TimeZone.current.identifier
        do {
            guard let api = await client() else { throw APIError(status: 0, detail: "no server") }
            if action == "done" { try await api.finishTask(id, tz: tz) }
            else { _ = try await api.snoozeTask(id, preset: nil, until: Date().addingTimeInterval(3600), tz: tz) }
        } catch let e as APIError where TaskOutbox.isFinal(e) {
            return  // the task changed or went away on your Mac: nothing to retry
        } catch {
            await TaskOutbox.queue(.init(kind: action, taskId: id, text: nil))
        }
    }
}

/// V6.82: what you do while your Mac is out of reach waits here (on this phone only) and goes through when you
/// reconnect, oldest first. One send at a time; each entry leaves the queue only once the Mac has it (or refused it for
/// good), and an add carries its own id so the Mac makes one task even if it arrives twice.
@MainActor
enum TaskOutbox {
    struct Entry: Codable, Hashable {
        let kind: String      // add, done, snooze1h
        let taskId: String?
        let text: String?
        var at = Date()
        var ref = UUID().uuidString
    }
    private static let key = "taskOutbox"
    private static var flushing = false

    nonisolated static var count: Int { read().count }

    nonisolated private static func read() -> [Entry] {
        guard let d = UserDefaults.standard.data(forKey: key) else { return [] }
        return (try? JSONDecoder().decode([Entry].self, from: d)) ?? []
    }

    private static func save(_ e: [Entry]) {
        UserDefaults.standard.set(try? JSONEncoder().encode(Array(e.suffix(100))), forKey: key)
    }

    static func queue(_ e: Entry) { save(read() + [e]) }

    /// Refused for good (the task is gone, changed, or the request can never succeed): don't retry. Sign-in problems,
    /// rate limits and server errors are not final; those wait for the next try.
    nonisolated static func isFinal(_ e: APIError) -> Bool { [400, 404, 409, 422].contains(e.status) }

    /// Sends what's waiting, oldest first, stopping at the first thing the Mac can't take yet. Returns how many went through.
    @discardableResult
    static func flush(_ api: APIClient) async -> Int {
        guard !flushing else { return 0 }
        flushing = true
        defer { flushing = false }
        let tz = TimeZone.current.identifier
        var sent = 0
        for e in read() {
            do {
                switch e.kind {
                case "add": if let t = e.text { _ = try await api.addTask(text: t, tz: tz, clientRef: e.ref) }
                case "done": if let id = e.taskId { try await api.finishTask(id, tz: tz) }
                default:  // snooze1h: an hour from when you pressed it, or a few minutes from now if that's passed
                    if let id = e.taskId {
                        let until = max(e.at.addingTimeInterval(3600), Date().addingTimeInterval(300))
                        _ = try await api.snoozeTask(id, preset: nil, until: until, tz: tz)
                    }
                }
                sent += 1
            } catch let x as APIError where isFinal(x) {
                // refused for good: let it go rather than retry forever
            } catch {
                break  // the Mac can't take it yet (offline, signed out, busy): keep this and the rest for next time
            }
            save(read().filter { $0.ref != e.ref })
        }
        return sent
    }
}

/// V6.85: open tasks in Spotlight, so searching the phone finds them. Titles only; nothing leaves the phone.
enum TaskSpotlight {
    static let domain = "ai.civilization.tasks"
    static let prefix = "task:"

    static func index(_ tasks: [MyTask]) {
        let index = CSSearchableIndex.default()
        let open = tasks.filter { $0.isOpen }
        let items: [CSSearchableItem] = open.prefix(200).map { t in
            let a = CSSearchableItemAttributeSet(contentType: .text)
            a.title = t.title
            var bits: [String] = []
            if let l = t.listName { bits.append("#\(l)") }
            if let d = t.due { bits.append("due \(TaskTime.label(d))") }
            a.contentDescription = bits.isEmpty ? "On your task list" : bits.joined(separator: " · ")
            a.keywords = ["task", t.kind] + (t.listName.map { [$0] } ?? [])
            return CSSearchableItem(uniqueIdentifier: prefix + t.id, domainIdentifier: domain, attributeSet: a)
        }
        index.deleteSearchableItems(withDomainIdentifiers: [domain]) { _ in
            index.indexSearchableItems(items, completionHandler: nil)
        }
    }

    static func taskId(from activity: NSUserActivity) -> String? {
        guard let id = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String, id.hasPrefix(prefix) else { return nil }
        return String(id.dropFirst(prefix.count))
    }
}

/// V6.75: a calendar file for the day's plan, to share into Calendar or anywhere else. Made on the phone.
enum DayPlanCalendar {
    static func ics(_ plan: DayPlan) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyyMMdd'T'HHmmss'Z'"
        let stamp = f.string(from: Date())
        func esc(_ s: String) -> String {
            s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: ";", with: "\\;")
                .replacingOccurrences(of: ",", with: "\\,").replacingOccurrences(of: "\r\n", with: "\\n")
                .replacingOccurrences(of: "\r", with: "\\n").replacingOccurrences(of: "\n", with: "\\n")
        }
        var lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AI Civilization//Plan my day//EN", "CALSCALE:GREGORIAN"]
        for b in plan.blocks {
            guard let s = b.startDate, let e = b.endDate else { continue }
            lines += ["BEGIN:VEVENT", "UID:\(b.taskId)-\(f.string(from: s))@aiciv", "DTSTAMP:\(stamp)",
                      "DTSTART:\(f.string(from: s))", "DTEND:\(f.string(from: e))",
                      "SUMMARY:\(esc("\(b.verb): \(b.title)"))",
                      "DESCRIPTION:\(esc(b.estimated ? "\(b.minutes) minutes (a default length, not your estimate)" : "\(b.minutes) minutes"))",
                      "END:VEVENT"]
        }
        lines.append("END:VCALENDAR")
        return lines.map(fold).joined(separator: "\r\n") + "\r\n"
    }

    /// RFC 5545: lines longer than 75 bytes continue on the next line after a space, never splitting a character.
    static func fold(_ line: String) -> String {
        var out: [String] = []
        var cur = ""
        var bytes = 0
        for ch in line {
            let n = String(ch).utf8.count
            if bytes + n > (out.isEmpty ? 75 : 74) {
                out.append(cur)
                cur = ""
                bytes = 0
            }
            cur.append(ch)
            bytes += n
        }
        out.append(cur)
        return out.joined(separator: "\r\n ")
    }

    static func file(_ plan: DayPlan) -> URL? {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("plan-my-day.ics")
        do { try ics(plan).write(to: url, atomically: true, encoding: .utf8); return url } catch { return nil }
    }
}

/// Home Screen quick actions (V6.97): handed to the app as it opens, or while it's running. SwiftUI still builds the
/// window; this only passes the action along.
final class QuickActionSceneDelegate: NSObject, UIWindowSceneDelegate {
    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        if let item = connectionOptions.shortcutItem { Task { @MainActor in TaskActions.pendingQuick = item.type } }
    }

    func windowScene(_ windowScene: UIWindowScene, performActionFor shortcutItem: UIApplicationShortcutItem,
                     completionHandler: @escaping (Bool) -> Void) {
        let type = shortcutItem.type
        Task { @MainActor in
            TaskActions.pendingQuick = type
            NotificationCenter.default.post(name: TaskActions.quickNote, object: type)
            completionHandler(true)
        }
    }
}
