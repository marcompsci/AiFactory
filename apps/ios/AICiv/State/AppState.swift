import Foundation
import Observation
import UserNotifications

/// App-wide state. Hydrates from /api/snapshot, then follows /api/stream (SSE) with ordered, deduplicated,
/// gap-replayed application — the same contract as the web client.
@MainActor
@Observable
final class AppState {
    enum Connection: Equatable { case idle, connecting, live, reconnecting(Int), failed(String) }

    var connection: Connection = .idle
    var agents: [String: Agent] = [:]
    var districts: [District] = []
    var missions: [MissionRow] = []
    var opportunities: [OpportunitySummary] = []
    /// Mission steps waiting for the owner, and packages on the conveyor (the town draws both).
    var approvals: [ApprovalRow] = []
    var packages: [TownPackage] = []
    /// server time minus device time, so packages move by the backend's clock
    var serverOffset: TimeInterval = 0
    var executionMode: String = ""
    var health: Health?
    var ledger = EventLedger()
    var serverURL: String = UserDefaults.standard.string(forKey: "serverURL") ?? "http://localhost:8000"
    var webURL: String = UserDefaults.standard.string(forKey: "webURL") ?? "http://localhost:3000"
    var tokenSet: Bool = Keychain.load() != nil
    // Sign in with Google / GitHub (Supabase). Public values only; tokens live in the Keychain.
    var supabaseURL: String = UserDefaults.standard.string(forKey: "supabaseURL") ?? ""
    var supabaseKey: String = UserDefaults.standard.string(forKey: "supabaseKey") ?? ""
    var session: SupabaseAuth.Session? = SupabaseAuth.load()
    var authError: String?
    let finder = ServerFinder()
    /// The address was set automatically from a Mac found on the network.
    var autoConnectedTo: String?

    private var streamTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?

    var api: APIClient? {
        guard let url = URL(string: serverURL) else { return nil }
        return APIClient(baseURL: url, token: Keychain.load())
    }

    var ownerWaiting: Int { ledger.ownerQueue.count }

    /// "192.168.1.20" or "my-mac.local" → "http://192.168.1.20:8000"; a full URL is kept as typed.
    static func normalize(_ raw: String, port: Int) -> String {
        let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty || t.contains("://") { return t }
        return t.contains(":") ? "http://\(t)" : "http://\(t):\(port)"
    }

    static func isLocalhost(_ s: String) -> Bool {
        guard let h = URL(string: s)?.host else { return true }
        return h == "localhost" || h == "127.0.0.1" || h == "::1"
    }

    func saveSettings(server: String, web: String, token: String?) {
        serverURL = Self.normalize(server, port: 8000)
        var w = Self.normalize(web, port: 3000)
        // the city runs on the same computer as the API: follow the API's address unless set to somewhere else
        if (w.isEmpty || Self.isLocalhost(w)), !Self.isLocalhost(serverURL), let host = URL(string: serverURL)?.host {
            w = "http://\(host):3000"
        }
        webURL = w
        UserDefaults.standard.set(serverURL, forKey: "serverURL")
        UserDefaults.standard.set(webURL, forKey: "webURL")
        if let token { Keychain.save(token); tokenSet = !token.isEmpty }
        connect()
    }

    var auth: SupabaseAuth? {
        guard let url = URL(string: supabaseURL), url.scheme == "https", !supabaseKey.isEmpty else { return nil }
        return SupabaseAuth(supabaseURL: url, publishableKey: supabaseKey)
    }

    /// Reads the server's public sign-in settings (Supabase address and publishable key) so the owner doesn't type them.
    func loadPublicConfig() async {
        guard let api = self.api, let cfg = try? await api.publicConfig() else { return }
        let url = cfg.s("supabase_url"), key = cfg.s("supabase_publishable_key")
        if !url.isEmpty, !key.isEmpty {
            supabaseURL = url
            supabaseKey = key
            UserDefaults.standard.set(url, forKey: "supabaseURL")
            UserDefaults.standard.set(key, forKey: "supabaseKey")
        }
    }

    func signIn(provider: String) async {
        authError = nil
        if auth == nil { await loadPublicConfig() }
        guard let auth else { authError = SupabaseAuth.AuthFailure.notConfigured.localizedDescription; return }
        do {
            let s = try await auth.signIn(provider: provider)
            session = s
            SupabaseAuth.save(s)
            tokenSet = true
            connect()
        } catch {
            authError = error.localizedDescription
        }
    }

    func signOut() {
        session = nil
        SupabaseAuth.save(nil)
        tokenSet = false
        connect()
    }

    /// Refreshes the session now (the server said the token expired).
    func forceRefresh() async {
        guard let s = session, let auth else { return }
        if let fresh = try? await auth.refresh(s) {
            session = fresh
            SupabaseAuth.save(fresh)
        } else {
            session = nil
            SupabaseAuth.save(nil)
            tokenSet = false
        }
    }

    /// Refreshes the Supabase access token a minute before it expires.
    func ensureFreshToken() async {
        guard let s = session, s.expiresAt.timeIntervalSinceNow < 300, let auth else { return }
        if let fresh = try? await auth.refresh(s) {
            session = fresh
            SupabaseAuth.save(fresh)
        }
    }

    /// Look for a Mac running AI Civilization; if the app isn't pointed anywhere yet (or its Mac went away), use it.
    func startFinding() {
        finder.start()
        Task {
            for _ in 0..<120 {   // about a minute of looking each time the app opens
                try? await Task.sleep(nanoseconds: 500_000_000)
                if let pick = pickFound() { use(pick); return }
                if !Self.isLocalhost(serverURL) && connection == .live { return }
            }
        }
    }

    private func pickFound() -> ServerFinder.Found? {
        guard let first = finder.found.first else { return nil }
        if finder.found.contains(where: { $0.apiURL == serverURL }) { return nil }  // already using a Mac we found
        // switch on our own only when nothing works yet: still on localhost, or the current address can't be reached
        let stuck: Bool = {
            if Self.isLocalhost(serverURL) { return true }
            switch connection {
            case .reconnecting(let n): return n >= 3
            case .failed(let why): return !why.contains("Sign in")
            default: return false
            }
        }()
        return stuck ? first : nil
    }

    func use(_ f: ServerFinder.Found) {
        autoConnectedTo = f.name
        saveSettings(server: f.apiURL, web: f.webURL, token: nil)
    }

    func connect() {
        streamTask?.cancel()
        streamTask = Task { await self.run() }
        if refreshTask == nil {
            // keep the sign-in fresh while the app is open (sessions last an hour; the stream can outlive that)
            refreshTask = Task {
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 120 * 1_000_000_000)
                    await self.ensureFreshToken()
                }
            }
        }
    }

    func refresh() async {
        await ensureFreshToken()
        guard let api = self.api else { return }
        if let snap = try? await api.snapshot() { apply(snapshot: snap) }
        if let list = try? await api.opportunities() { opportunities = list }
        health = try? await api.health()
    }

    private func apply(snapshot snap: Snapshot) {
        agents = Dictionary(uniqueKeysWithValues: snap.agents.map { ($0.id, $0) })
        applyWorld(snap)
        if let d = snap.districts { districts = d }
        missions = snap.missions
        if let opps = snap.opportunities { opportunities = opps }
        ledger.reset(lastSequence: snap.sequence,
                     ownerQueue: (snap.opportunities ?? []).filter { $0.status == "OWNER_APPROVAL" }.map(\.id))
    }

    private func applyWorld(_ snap: Snapshot) {
        executionMode = snap.executionMode
        approvals = (snap.approvals ?? []).filter { $0.status == "PENDING" }
        if let lg = snap.logistics {
            if let t = ISODate.parse(lg.serverTime) { serverOffset = t.timeIntervalSinceNow }
            packages = (lg.packages ?? []).map {
                TownPackage(id: $0.id, type: $0.packageType, status: $0.status, origin: $0.originDistrict, destination: $0.destinationDistrict,
                            routeStartedAt: ISODate.parse($0.routeStartedAt), eta: ISODate.parse($0.eta))
            }
        }
    }

    private var worldRefresh: Task<Void, Never>?

    /// Agent states, packages and approvals change with task, package and approval events; re-read them (at most every second).
    private func refreshWorldSoon(api: APIClient) {
        guard worldRefresh == nil else { return }
        worldRefresh = Task {
            try? await Task.sleep(nanoseconds: 700_000_000)
            if let snap = try? await api.snapshot() {
                agents = Dictionary(uniqueKeysWithValues: snap.agents.map { ($0.id, $0) })
                missions = snap.missions
                applyWorld(snap)
            }
            worldRefresh = nil
        }
    }

    private func run() async {
        var attempt = 0
        var triedRefresh = false
        while !Task.isCancelled {
            await ensureFreshToken()
            guard let api = self.api else { connection = .failed("Server address is not a valid URL"); return }
            connection = attempt == 0 ? .connecting : .reconnecting(attempt)
            do {
                let snap = try await api.snapshot()
                apply(snapshot: snap)
                health = try? await api.health()
                if let list = try? await api.opportunities() { opportunities = list }
                let (bytes, response) = try await URLSession.shared.bytes(for: api.streamRequest(after: snap.sequence))
                guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw APIError(status: 0, detail: "Stream refused") }
                var parser = SSEParser()
                var line = [UInt8]()
                for try await byte in bytes {
                    if byte == UInt8(ascii: "\n") {
                        let text = String(decoding: line, as: UTF8.self)
                        line.removeAll(keepingCapacity: true)
                        guard let msg = parser.consume(line: text) else { continue }
                        if msg.event == "ready" { connection = .live; attempt = 0; continue }
                        guard msg.event == "envelope", let data = msg.data.data(using: .utf8),
                              let event = try? APIClient.decoder.decode(EventEnvelope.self, from: data),
                              event.schemaVersion == 1 else { continue }
                        await receive([event], api: api)
                    } else {
                        line.append(byte)
                    }
                }
            } catch let e as APIError where e.status == 401 && e.detail.contains("expired") && session != nil && !triedRefresh {
                // an hour-old session: refresh it once and carry on
                triedRefresh = true
                await forceRefresh()
                continue
            } catch let e as APIError where e.status == 401 || e.status == 403 {
                if e.status == 401 && session == nil && tokenSet {
                    // a token saved by hand earlier that the server no longer accepts: drop it so the app stops sending it
                    Keychain.save("")
                    tokenSet = false
                }
                connection = .failed("Sign in to connect")
                return
            } catch let e as APIError where e.status == 429 {
                connection = .failed("Too many attempts. Wait a few minutes, then sign in again.")
                return
            } catch let e as APIError where e.status == 503 {
                connection = .failed("Your Mac can't reach Supabase to check your sign-in. Check its internet connection.")
                return
            } catch {
                if Task.isCancelled { return }
            }
            attempt += 1
            connection = .reconnecting(attempt)
            try? await Task.sleep(nanoseconds: UInt64(min(15.0, 0.5 * pow(2.0, Double(min(attempt, 5)))) * 1_000_000_000))
        }
    }

    private func receive(_ events: [EventEnvelope], api: APIClient) async {
        let before = Set(ledger.ownerQueue)
        var result = ledger.ingest(events)
        if result.needsReplay, let missing = try? await api.events(after: ledger.lastSequence) {
            result = ledger.ingest(missing)
        }
        let types = Set(result.applied.map(\.eventType))
        if types.contains(where: { $0.hasPrefix("task.") || $0.hasPrefix("package.") || $0.hasPrefix("approval.") || $0.hasPrefix("agent.") || $0.hasPrefix("mission.") }) {
            refreshWorldSoon(api: api)
        }
        if !types.isDisjoint(with: ["opportunity.status_changed", "release.owner_approval_requested", "release.authorized", "mission.completed", "mission.created"]) {
            if let list = try? await api.opportunities() { opportunities = list }
            if let snap = try? await api.snapshot() { missions = snap.missions; agents = Dictionary(uniqueKeysWithValues: snap.agents.map { ($0.id, $0) }) }
        }
        for oid in Set(ledger.ownerQueue).subtracting(before) {
            let title = result.applied.first { $0.payload.get("opportunity_id")?.string == oid }?.payload.get("title")?.string
            Notifier.releaseWaiting(title: title ?? "A new release")
        }
    }
}

/// Local notifications: when a release reaches the Owner's Tower. (Remote push needs an APNs key on the server — see apps/ios/README.md.)
enum Notifier {
    static func requestPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
    }

    static func releaseWaiting(title: String) {
        let content = UNMutableNotificationContent()
        content.title = "Waiting at your tower"
        content.body = "\(title) is ready for your decision."
        content.sound = .default
        let req = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
    }
}
