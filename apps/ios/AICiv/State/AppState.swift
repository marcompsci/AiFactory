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
    var missions: [MissionRow] = []
    var opportunities: [OpportunitySummary] = []
    var health: Health?
    var ledger = EventLedger()
    var serverURL: String = UserDefaults.standard.string(forKey: "serverURL") ?? "http://localhost:8000"
    var webURL: String = UserDefaults.standard.string(forKey: "webURL") ?? "http://localhost:3000"
    var tokenSet: Bool = Keychain.load() != nil

    private var streamTask: Task<Void, Never>?

    var api: APIClient? {
        guard let url = URL(string: serverURL) else { return nil }
        return APIClient(baseURL: url, token: Keychain.load())
    }

    var ownerWaiting: Int { ledger.ownerQueue.count }

    func saveSettings(server: String, web: String, token: String?) {
        serverURL = server.trimmingCharacters(in: .whitespacesAndNewlines)
        webURL = web.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(serverURL, forKey: "serverURL")
        UserDefaults.standard.set(webURL, forKey: "webURL")
        if let token { Keychain.save(token); tokenSet = !token.isEmpty }
        connect()
    }

    func connect() {
        streamTask?.cancel()
        streamTask = Task { await self.run() }
    }

    func refresh() async {
        guard let api = self.api else { return }
        if let snap = try? await api.snapshot() { apply(snapshot: snap) }
        if let list = try? await api.opportunities() { opportunities = list }
        health = try? await api.health()
    }

    private func apply(snapshot snap: Snapshot) {
        agents = Dictionary(uniqueKeysWithValues: snap.agents.map { ($0.id, $0) })
        missions = snap.missions
        if let opps = snap.opportunities { opportunities = opps }
        ledger.reset(lastSequence: snap.sequence,
                     ownerQueue: (snap.opportunities ?? []).filter { $0.status == "OWNER_APPROVAL" }.map(\.id))
    }

    private func run() async {
        var attempt = 0
        while !Task.isCancelled {
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
