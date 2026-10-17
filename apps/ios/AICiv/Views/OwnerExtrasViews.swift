import Charts
import SwiftUI

// V6.21–V6.26 screens: run again and follow-ons on a mission, the weekly report, the team roster, the records export.

/// Run again (POST /api/missions/{id}/rerun) and follow-on missions (POST /api/missions/{id}/followups).
struct MissionLinksSection: View {
    @Environment(AppState.self) private var app
    let missionId: String
    let detail: JSONValue?
    var reload: () async -> Void
    @State private var message: String?
    @State private var busy = false
    @State private var topic = ""
    @State private var saveName = ""

    private var status: String { detail?.get("mission")?.s("status") ?? "" }
    private var finished: Bool { ["COMPLETED", "FAILED", "CANCELLED"].contains(status) }
    private var canFollow: Bool { !["FAILED", "CANCELLED"].contains(status) }
    private var links: JSONValue? { detail?.get("links") }

    var body: some View {
        Section {
            if let from = links?.get("started_from") {
                Label(from.s("kind") == "rerun" ? "Started again from an earlier mission" : "A follow-on of an earlier mission",
                      systemImage: "arrow.uturn.backward")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if detail?.get("can_rerun")?.bool == true {
                Button { Task { await rerun() } } label: { Label("Run again", systemImage: "arrow.clockwise") }
                    .disabled(busy)
                    .accessibilityHint("Starts the same request fresh, under your charter")
            }
            if finished {
                NavigationLink { CompareRunsView(missionId: missionId) } label: {
                    Label("Compare with the run before", systemImage: "arrow.left.arrow.right")
                }
            }
            if detail?.get("can_rerun")?.bool == true {
                HStack {
                    TextField("Name to save this request as", text: $saveName).font(.caption)
                    Button("Save") { Task { await saveRequest() } }
                        .buttonStyle(.borderless)
                        .disabled(saveName.trimmingCharacters(in: .whitespaces).count < 2 || busy)
                        .accessibilityLabel("Save this request under that name")
                }
            }
            let follow = links?.get("followups")?.list ?? []
            ForEach(follow) { f in followRow(f) }
            if canFollow {
                Menu {
                    Button("Then run the tests") { Task { await addFollowup(["kind": .string("run_tests")]) } }
                    Button("Then research the topic below") { Task { await addResearch() } }
                } label: {
                    Label(finished ? "Start a follow-on now" : "When this finishes, start…", systemImage: "arrow.turn.down.right")
                }
                .disabled(busy)
                TextField("Research topic for a follow-on (optional)", text: $topic)
                    .textInputAutocapitalization(.never)
                    .font(.caption)
            }
            if let message { Text(message).font(.caption) }
        } header: {
            Text("Next")
        } footer: {
            Text("A follow-on starts only if this mission completes; if it fails or is cancelled, the follow-on is cancelled too.")
        }
    }

    private func followRow(_ f: JSONValue) -> some View {
        let spec = f.get("spec")
        let what = spec?.s("kind") == "market_research" ? "Research \"\(spec?.get("params")?.s("query") ?? "")\"" : "Run the tests"
        let state = f.s("status").lowercased()
        let reason = f.s("reason")
        return HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(what).font(.subheadline)
                Text(reason.isEmpty ? state : "\(state): \(reason)").font(.caption2).foregroundStyle(.secondary)
            }
            Spacer()
            if f.s("status") == "WAITING" {
                Button("Cancel") { Task { await cancel(f.s("id")) } }
                    .buttonStyle(.borderless)
                    .accessibilityLabel("Cancel this follow-on")
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func rerun() async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        do {
            let r = try await api.json("/api/missions/\(missionId)/rerun", method: "POST")
            message = r.get("repeat")?.bool == true ? "Already started a moment ago." : "Started again. It's in the journal."
            await app.refresh()
            await reload()
        } catch { message = error.localizedDescription }
    }

    private func saveRequest() async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        do {
            let r = try await api.json("/api/missions/\(missionId)/save", method: "POST", body: ["name": .string(saveName)])
            message = "Saved as \"\(r.s("name"))\". Start it from Owner → Saved requests, or ask in the City."
            saveName = ""
        } catch { message = error.localizedDescription }
    }

    private func addResearch() async {
        let q = topic.trimmingCharacters(in: .whitespaces)
        guard q.count >= 2 else { message = "Type a research topic first."; return }
        let params: [String: JSONValue] = ["source": .string("apple_charts"), "query": .string(q)]
        await addFollowup(["kind": .string("market_research"), "params": .object(params)])
    }

    private func addFollowup(_ body: [String: JSONValue]) async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        do {
            let r = try await api.json("/api/missions/\(missionId)/followups", method: "POST", body: body)
            message = r.s("status") == "STARTED" ? "Started." : "It will start when this mission completes."
            topic = ""
            await reload()
        } catch { message = error.localizedDescription }
    }

    private func cancel(_ id: String) async {
        guard let api = app.api else { return }
        do { _ = try await api.json("/api/followups/\(id)", method: "DELETE") } catch { message = error.localizedDescription }
        await reload()
    }
}

/// The last seven days against the seven before (GET /api/insights/weekly).
struct WeeklyReportView: View {
    @Environment(AppState.self) private var app
    @State private var report: JSONValue?

    struct Day: Identifiable {
        let id: String
        let label: String
        let done: Int
        let failed: Int
    }

    private var days: [Day] {
        let rows = report?.get("days")?.list ?? []
        return rows.map { d in
            let date = d.s("date")
            return Day(id: date, label: Self.weekday(date), done: d.get("completed")?.int ?? 0, failed: d.get("failed")?.int ?? 0)
        }
    }

    var body: some View {
        List {
            if app.connection != .live {
                Text("Connect to your Mac and sign in to see the week.").foregroundStyle(.secondary)
            }
            if let r = report {
                Section { Text(r.s("headline")).font(.subheadline) }
                Section("Missions per day") {
                    Chart(days) { d in
                        BarMark(x: .value("Day", d.label), y: .value("Finished", d.done))
                            .foregroundStyle(Theme.cyan)
                        BarMark(x: .value("Day", d.label), y: .value("Failed", d.failed))
                            .foregroundStyle(Theme.bad)
                    }
                    .frame(height: 160)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(Self.spokenDays(days))
                }
                Section("Totals") {
                    totalRow("Finished", r.get("week")?.get("completed")?.int, r.get("previous_week")?.get("completed")?.int)
                    totalRow("Failed", r.get("week")?.get("failed")?.int, r.get("previous_week")?.get("failed")?.int)
                    let usd = r.get("week")?.get("spend_usd")?.double ?? 0
                    LabeledContent("Spend (estimated)", value: String(format: "$%.2f", usd))
                    LabeledContent("Schedule runs", value: "\(r.get("schedules")?.get("started")?.int ?? 0)")
                    LabeledContent("Run again / follow-ons", value: "\(r.get("reruns")?.int ?? 0) / \(r.get("followups_started")?.int ?? 0)")
                }
                let top = r.get("top_agents")?.list ?? []
                if !top.isEmpty {
                    Section("Busiest agents") {
                        ForEach(top) { a in LabeledContent(a.s("agent"), value: "\(a.get("tasks_completed")?.int ?? 0) tasks") }
                    }
                }
                Section { } footer: { Text("Counted from the records; days are your phone's days (\(report?.s("tz") ?? "")). Spend is the gateway's estimate, not a bill.") }
            }
        }
        .navigationTitle("This week")
        .task { await load() }
        .refreshable { await load() }
    }

    private func totalRow(_ label: String, _ now: Int?, _ before: Int?) -> some View {
        LabeledContent(label, value: "\(now ?? 0) (week before: \(before ?? 0))")
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "+&=")  // "Etc/GMT+5" must arrive with its plus sign
        let tz = TimeZone.current.identifier.addingPercentEncoding(withAllowedCharacters: allowed) ?? "UTC"
        report = try? await api.json("/api/insights/weekly?tz=\(tz)")
    }

    static func weekday(_ iso: String) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone(identifier: "UTC")  // a calendar date, read and printed in the same zone
        guard let d = f.date(from: iso) else { return iso }
        let out = DateFormatter()
        out.dateFormat = "EEE"
        out.timeZone = TimeZone(identifier: "UTC")
        return out.string(from: d)
    }

    static func spokenDays(_ days: [Day]) -> String {
        let parts = days.map { d in "\(d.label): \(d.done) finished, \(d.failed) failed" }
        return "Missions per day. " + parts.joined(separator: "; ")
    }
}

/// Who has signed in, with their role at their latest sign-in (GET /api/team, owner only).
struct TeamView: View {
    @Environment(AppState.self) private var app
    @State private var team: JSONValue?
    @State private var message: String?

    var body: some View {
        List {
            let members = team?.get("members")?.list ?? []
            Section {
                ForEach(members, id: \.self) { m in memberRow(m) }
            } footer: {
                Text(team?.s("note") ?? "")
            }
            let orphans = team?.get("schedules_to_check")?.list ?? []
            if !orphans.isEmpty {
                Section("Schedules to check") {
                    ForEach(orphans, id: \.self) { o in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(o.s("title")).font(.caption.bold())
                            Text(o.s("why")).font(.caption2).foregroundStyle(.secondary)
                        }
                        .accessibilityElement(children: .combine)
                    }
                    NavigationLink { SchedulesView() } label: { Text("Review schedules") }
                }
            }
            if let message { Text(message).font(.caption).foregroundStyle(Theme.warn) }
        }
        .navigationTitle("Team")
        .task { await load() }
        .refreshable { await load() }
    }

    private func memberRow(_ m: JSONValue) -> some View {
        let name = m.s("email").isEmpty ? "User \(m.s("user_id").prefix(8))" : m.s("email")
        let you = m.get("you")?.bool == true ? " (you)" : ""
        let seen = SchedulesView.local(m.s("last_seen"))
        let n = m.get("active_schedules")?.int ?? 0
        return VStack(alignment: .leading, spacing: 2) {
            Text(name + you).font(.subheadline.bold())
            Text("\(m.s("role").capitalized) · last signed in \(seen)" + (n > 0 ? " · \(n) schedule(s)" : ""))
                .font(.caption).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        do { team = try await api.json("/api/team"); message = nil } catch { message = error.localizedDescription }
    }
}

/// The owner's copy of the records (GET /api/export): Face ID, then a file to share or save.
struct RecordsExportView: View {
    @Environment(AppState.self) private var app
    @State private var file: URL?
    @State private var message: String?
    @State private var busy = false

    var body: some View {
        List {
            Section {
                Text("One JSON file with your missions, steps, approvals, decisions, charter, schedules, team and recent events, each event with its audit-chain link, plus a fresh check of the whole chain and a SHA-256 fingerprint of the records (bundle_sha256; how to recompute it is in the file's format notes).")
                    .font(.subheadline)
                Text("Left out on purpose: money records, stored credentials and server settings.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section {
                if let file {
                    ShareLink(item: file) { Label("Share or save the file", systemImage: "square.and.arrow.up") }
                } else {
                    Button { Task { await make() } } label: {
                        Label(busy ? "Building…" : "Build the export", systemImage: "externaldrive.badge.checkmark")
                    }
                    .disabled(busy || app.connection != .live)
                }
                if let message { Text(message).font(.caption) }
            } footer: {
                Text("One export a minute. Each export is recorded in the event log.")
            }
        }
        .navigationTitle("Export records")
    }

    private func make() async {
        guard let api = app.api else { return }
        guard await ReleaseReviewView.authenticate(reason: "Export your records") else { message = "Face ID didn't confirm it's you."; return }
        busy = true
        defer { busy = false }
        do {
            let data = try await api.rawData("/api/export")  // the server's exact bytes
            let stamp = ISO8601DateFormatter().string(from: Date()).prefix(10)
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("aiciv-records-\(stamp).json")
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            file = url
            message = nil
        } catch { message = error.localizedDescription }
    }
}


/// A mission next to the run before it (GET /api/missions/{id}/compare).
struct CompareRunsView: View {
    @Environment(AppState.self) private var app
    let missionId: String
    @State private var data: JSONValue?
    @State private var message: String?

    var body: some View {
        List {
            if let d = data {
                if d.get("before") == nil {
                    Text(d.s("note")).foregroundStyle(.secondary)
                } else {
                    Section("What changed (\(d.s("how")))") {
                        ForEach(d.get("changes")?.list ?? [], id: \.self) { c in Text(c.str).font(.subheadline) }
                    }
                    Section("This run") { runRows(d.get("this")) }
                    Section("The run before") { runRows(d.get("before")) }
                    Section { } footer: { Text("Counted from the records. Cost is the gateway's estimate, not a bill.") }
                }
            }
            if let message { Text(message).font(.caption).foregroundStyle(Theme.warn) }
        }
        .navigationTitle("Compare runs")
        .task { await load() }
    }

    @ViewBuilder private func runRows(_ r: JSONValue?) -> some View {
        let steps = r?.get("steps")
        let dur = r?.get("duration_s")?.int
        LabeledContent("Status", value: (r?.s("status") ?? "").lowercased())
        LabeledContent("Objective", value: Self.objective(r?.s("objective") ?? ""))
        LabeledContent("Estimated cost", value: String(format: "$%.2f", r?.get("cost_usd")?.double ?? 0))
        LabeledContent("Time taken", value: Self.duration(dur))
        LabeledContent("Steps", value: "\(steps?.get("completed")?.int ?? 0) of \(steps?.get("total")?.int ?? 0) done, \(steps?.get("failed")?.int ?? 0) failed")
    }

    static func duration(_ s: Int?) -> String {
        guard let s else { return "still going" }
        if s < 60 { return "\(s)s" }
        return "\(s / 60)m \(s % 60)s"
    }

    static func objective(_ s: String) -> String {
        s.isEmpty ? "not checked" : s.replacingOccurrences(of: "objective_", with: "").replacingOccurrences(of: "_", with: " ")
    }

    private func load() async {
        guard let api = app.api else { return }
        do { data = try await api.json("/api/missions/\(missionId)/compare") } catch { message = error.localizedDescription }
    }
}

/// Requests you've named, ready to start (GET/POST /api/saved-requests).
struct SavedRequestsView: View {
    @Environment(AppState.self) private var app
    @State private var list: [JSONValue] = []
    @State private var loaded = false
    @State private var message: String?

    var body: some View {
        List {
            if loaded && list.isEmpty {
                Text("Nothing saved yet. On a finished mission's page, type a name and tap Save. Then start it here, or ask anyone in the City \"start <name>\".")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            ForEach(list) { r in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(r.s("name")).font(.subheadline.bold())
                        Text(Self.detail(r)).font(.caption2).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Start") { Task { await start(r.s("id")) } }
                        .buttonStyle(.borderedProminent).tint(Theme.cyan)
                        .accessibilityLabel("Start \(r.s("name"))")
                }
                .swipeActions { Button("Delete", role: .destructive) { Task { await remove(r.s("id")) } } }
            }
            if let message { Text(message).font(.caption) }
            Section { } footer: { Text("A saved request starts as you, under your charter, like starting it by hand.") }
        }
        .navigationTitle("Saved requests")
        .task { await load() }
        .refreshable { await load() }
    }

    static func detail(_ r: JSONValue) -> String {
        let kind: String
        switch r.s("kind") {
        case "run_tests": kind = "Test run"
        case "market_research": kind = "Research"
        default: kind = "Test fix"
        }
        let uses = r.get("uses")?.int ?? 0
        return "\(kind) · \(r.s("priority")) priority · started \(uses) time(s)"
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        list = (try? await api.json("/api/saved-requests"))?.get("saved_requests")?.list ?? []
        loaded = true
    }

    private func start(_ id: String) async {
        guard let api = app.api else { return }
        do {
            let r = try await api.json("/api/saved-requests/\(id)/start", method: "POST")
            message = r.get("repeat")?.bool == true ? "Already started a moment ago." : "Started. It's in the journal."
            await app.refresh()
        } catch { message = error.localizedDescription }
        await load()
    }

    private func remove(_ id: String) async {
        guard let api = app.api else { return }
        do { _ = try await api.json("/api/saved-requests/\(id)", method: "DELETE") } catch { message = error.localizedDescription }
        await load()
    }
}
