import BackgroundTasks
import SwiftUI

@main
struct AICivApp: App {
    @State private var app = AppState()
    @Environment(\.scenePhase) private var phase

    init() {
        BackgroundRefresh.register()
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(app)
                .preferredColorScheme(.dark)
                .tint(Theme.cyan)
                .task {
                    // CI screenshot runs (-screenshots YES) skip the permission prompts so the town is visible
                    let shots = UserDefaults.standard.bool(forKey: "screenshots")
                    if !shots { Notifier.requestPermission() }
                    app.connect()
                    if !shots { app.startFinding() }
                }
        }
        .onChange(of: phase) { _, newPhase in
            if newPhase == .background { BackgroundRefresh.schedule() }
            if newPhase == .active, app.connection != .live { app.connect(); app.startFinding() }
        }
    }
}

struct RootView: View {
    @Environment(AppState.self) private var app
    @State private var tab = UserDefaults.standard.string(forKey: "startTab") ?? "home"

    var body: some View {
        TabView(selection: $tab) {
            HomeView().tabItem { Label("Home", systemImage: "square.grid.2x2") }.tag("home")
            CityGameView().tabItem { Label("City", systemImage: "gamecontroller.fill") }.tag("city")
            ArenaView().tabItem { Label("Arena", systemImage: "trophy") }.tag("arena")
            OwnerTowerView()
                .tabItem { Label("Owner", systemImage: "building.columns") }
                .badge(app.ownerWaiting + app.approvals.count)
                .tag("owner")
            MoreView().tabItem { Label("More", systemImage: "ellipsis.circle") }.tag("more")
        }
        .onChange(of: app.openTab) { _, t in if let t { tab = t; app.openTab = nil } }
    }
}

/// While the app is in the background, iOS occasionally lets it check whether a release reached the tower.
enum BackgroundRefresh {
    static let id = "ai.civilization.refresh"

    static func register() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: id, using: nil) { task in
            schedule()
            let work = Task {
                let server = UserDefaults.standard.string(forKey: "serverURL") ?? "http://localhost:8000"
                guard let url = URL(string: server) else { return }
                let api = APIClient(baseURL: url, token: Keychain.load())
                let waiting = (try? await api.opportunities())?.filter { $0.status == "OWNER_APPROVAL" } ?? []
                let seen = Set(UserDefaults.standard.stringArray(forKey: "notifiedReleases") ?? [])
                for o in waiting where !seen.contains(o.id) { Notifier.releaseWaiting(title: o.title) }
                UserDefaults.standard.set(Array(seen.union(waiting.map(\.id))), forKey: "notifiedReleases")
                task.setTaskCompleted(success: true)
            }
            task.expirationHandler = { work.cancel() }
        }
    }

    static func schedule() {
        let req = BGAppRefreshTaskRequest(identifier: id)
        req.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(req)
    }
}
