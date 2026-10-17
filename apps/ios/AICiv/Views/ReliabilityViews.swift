import SwiftUI

/// Why agents failed, sorted into the MAST failure categories by plain rules (GET /api/insights/failures), and what
/// each agent has learned from its own runs (GET /api/insights/lessons).
struct FailureClinicView: View {
    @Environment(AppState.self) private var app
    @State private var data: JSONValue?
    @State private var lessons: JSONValue?
    @State private var days = 30
    @State private var failed = false

    var body: some View {
        List {
            if app.connection != .live {
                Text("Connect to your Mac and sign in to see the failure clinic.").foregroundStyle(.secondary)
            } else if let d = data {
                let total = d.get("total")?.int ?? 0
                Section {
                    Picker("Period", selection: $days) {
                        Text("7 days").tag(7)
                        Text("30 days").tag(30)
                        Text("90 days").tag(90)
                    }.pickerStyle(.segmented)
                    if total == 0 {
                        Label("No failures in this period.", systemImage: "checkmark.seal.fill").foregroundStyle(Theme.ok)
                    } else {
                        VStack(alignment: .leading, spacing: 4) {
                            let incidents = d.get("incidents")?.int ?? total
                            Text("\(incidents) problem\(incidents == 1 ? "" : "s")").font(.title2.bold())
                            Text("Counting every failed attempt: \(total)")
                                .font(.caption).foregroundStyle(.secondary)
                            Text(d.s("advice")).font(.subheadline)
                        }
                    }
                } footer: {
                    Text("Sorted by rules into the categories from \(d.s("reference")). Nothing here is judged by a model.")
                }
                let cats = d.get("by_category")?.list ?? []
                if !cats.isEmpty {
                    Section("By kind") {
                        ForEach(Array(cats.enumerated()), id: \.offset) { _, c in
                            let n = c.get("count")?.int ?? 0
                            VStack(alignment: .leading, spacing: 4) {
                                HStack { Text(c.s("name")).bold(); Spacer(); Text("\(n)").font(Pixel.mono(13)) }
                                GeometryReader { g in
                                    Capsule().fill(color(c.s("category")))
                                        .frame(width: max(6, g.size.width * CGFloat(n) / CGFloat(max(1, total))))
                                }.frame(height: 6)
                                Text(c.s("fix")).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                let agents = d.get("by_agent")?.list ?? []
                if !agents.isEmpty {
                    Section("By agent") {
                        ForEach(Array(agents.enumerated()), id: \.offset) { _, a in
                            HStack { Text(a.s("agent")); Spacer(); Text("\(a.get("count")?.int ?? 0)").font(Pixel.mono(13)) }
                        }
                    }
                }
                let labels = d.get("labels")?.list ?? []
                if !labels.isEmpty {
                    Section("Recent") {
                        ForEach(Array(labels.prefix(40).enumerated()), id: \.offset) { _, l in
                            VStack(alignment: .leading, spacing: 3) {
                                HStack(spacing: 6) {
                                    Text(l.s("mode")).font(Pixel.mono(10)).padding(.horizontal, 5).padding(.vertical, 2)
                                        .background(color(l.s("category")).opacity(0.25), in: Capsule())
                                    Text(l.s("name")).font(.subheadline.bold())
                                }
                                Text([l.s("agent"), l.s("task"), l.s("mission")].filter { !$0.isEmpty }.joined(separator: " · "))
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                if !l.s("evidence").isEmpty { Text(l.s("evidence")).font(Pixel.mono(10)).foregroundStyle(.secondary).lineLimit(3) }
                            }
                        }
                    }
                }
                let learned = lessons?.get("agents")?.list ?? []
                Section("What agents have learned") {
                    if learned.isEmpty { Text("No lessons yet. Agents write one when a task struggles.").foregroundStyle(.secondary) }
                    ForEach(Array(learned.enumerated()), id: \.offset) { _, a in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(a.s("agent")).bold()
                            ForEach(a.get("lessons")?.list ?? []) { l in
                                Text("• " + l.s("lesson")).font(.caption)
                            }
                        }
                    }
                }
            } else if failed {
                Text("Couldn't load the failure clinic.").foregroundStyle(.secondary)
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Failure clinic")
        .task(id: days) { await load() }
        .refreshable { await load() }
    }

    private func color(_ category: String) -> Color {
        switch category {
        case "specification": return Theme.warn
        case "misalignment": return Color(hex: 0xB38CFF)
        case "verification": return Theme.bad
        case "resources": return Theme.gold
        case "infrastructure": return Theme.cyan
        default: return .gray
        }
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        do {
            data = try await api.json("/api/insights/failures?days=\(days)")
            lessons = try? await api.json("/api/insights/lessons")
            failed = false
        } catch { failed = true }
    }
}

/// The objective check a finished mission gets: did every step produce what the plan promised?
struct ObjectiveRow: View {
    let objective: JSONValue
    var body: some View {
        let status = objective.s("status")
        let met = objective.get("met")?.bool ?? false
        let partly = status == "objective_partly_met"
        VStack(alignment: .leading, spacing: 4) {
            Label(met ? "Objective met" : partly ? "Objective partly met" : "Objective not met",
                  systemImage: met ? "checkmark.seal.fill" : partly ? "circle.lefthalf.filled" : "exclamationmark.triangle.fill")
                .foregroundStyle(met ? Theme.ok : partly ? Theme.gold : Theme.warn).font(.subheadline.bold())
            ForEach(Array((objective.get("findings")?.list ?? []).enumerated()), id: \.offset) { _, f in
                Text(f.str).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

/// Everything that happened in one mission, in order (GET /api/insights/missions/{id}/trace).
struct MissionTraceView: View {
    @Environment(AppState.self) private var app
    let missionId: String
    @State private var data: JSONValue?
    @State private var only: String?
    @State private var failed = false

    struct Kind: Identifiable {
        let id: String
        let label: String
        let color: Color
    }

    static let kinds: [Kind] = [
        Kind(id: "step", label: "Steps", color: Theme.cyan), Kind(id: "tool", label: "Tools", color: Color(hex: 0x8FA8FF)),
        Kind(id: "model", label: "AI calls", color: Color(hex: 0xA66BFF)), Kind(id: "message", label: "Messages", color: Color(hex: 0x9CC8FF)),
        Kind(id: "approval", label: "Approvals", color: Theme.gold), Kind(id: "decision", label: "Manager", color: Theme.warn),
        Kind(id: "check", label: "Checks", color: Theme.ok), Kind(id: "lesson", label: "Lessons", color: Color(hex: 0x9CC8FF)),
        Kind(id: "mission", label: "Mission", color: Theme.ink),
    ]

    var body: some View {
        List {
            if let d = data {
                let t = d.get("totals")
                Section {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 10) {
                        stat("Time", Self.duration(t?.get("wall_ms")?.int))
                        stat("AI cost (est.)", String(format: "$%.4f", t?.get("cost_usd")?.double ?? 0))
                        stat("Tool calls", "\(t?.get("tool_calls")?.int ?? 0)")
                        stat("Failed steps", "\(t?.get("failed_steps")?.int ?? 0)")
                    }
                }
                let per = d.get("by_agent")?.list ?? []
                if !per.isEmpty {
                    Section("By agent") {
                        ForEach(Array(per.enumerated()), id: \.offset) { _, a in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(a.s("agent")).bold()
                                Text("\(a.get("steps")?.int ?? 0) steps · \(a.get("tool_calls")?.int ?? 0) tools · \(a.get("model_calls")?.int ?? 0) AI calls · busy \(Self.duration(a.get("busy_ms")?.int))")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                Section {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            chip(nil, "All")
                            ForEach(Self.kinds) { k in chip(k.id, k.label) }
                        }
                    }
                    let items = (d.get("items")?.list ?? []).filter { only == nil || $0.s("kind") == only }
                    ForEach(Array(items.suffix(400).enumerated()), id: \.offset) { _, i in row(i) }
                    if items.count > 400 || d.get("truncated")?.bool == true {
                        Text("Showing the most recent entries; the web trace has the full list.").font(.caption2).foregroundStyle(.secondary)
                    }
                } header: { Text("Timeline") } footer: { Text("AI costs are the gateway's estimates.") }
                Section { AuditExportButton(missionId: missionId) } footer: {
                    Text("The audit file holds this mission's record, trace, checks and chained events, with a hash of the whole file.")
                }
            } else if failed {
                Text(app.connection == .live ? "Couldn't load the trace." : "Connect to your Mac and sign in to see the trace.").foregroundStyle(.secondary)
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Trace")
        .task {
            do { data = try await app.api?.json("/api/insights/missions/\(missionId)/trace"); failed = data == nil } catch { failed = true }
        }
    }

    private func stat(_ k: String, _ v: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(k).font(.caption2).foregroundStyle(.secondary)
            Text(v).font(Pixel.mono(14))
        }
    }

    private func chip(_ kind: String?, _ label: String) -> some View {
        Button { only = kind } label: {
            Text(label).font(.caption).padding(.horizontal, 8).padding(.vertical, 4)
                .background(only == kind ? Theme.cyan : Color(hex: 0x141B33), in: Capsule())
                .foregroundStyle(only == kind ? Theme.ground : Theme.ink)
        }.buttonStyle(.plain)
    }

    private func row(_ i: JSONValue) -> some View {
        let kind = Self.kinds.first { $0.id == i.s("kind") }
        return VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Circle().fill(kind?.color ?? .gray).frame(width: 7, height: 7)
                Text(i.s("title")).font(.subheadline.bold()).lineLimit(2)
                Spacer()
                if !i.s("status").isEmpty {
                    Text(i.s("status").lowercased()).font(.caption2).foregroundStyle(i.s("status") == "FAILED" ? Theme.bad : .secondary)
                }
            }
            let meta = [Self.time(i.s("at")), i.s("agent"), Self.duration(i.get("duration_ms")?.int),
                        i.get("cost_usd")?.double.map { String(format: "$%.4f", $0) } ?? ""].filter { !$0.isEmpty }
            Text(meta.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
            if !i.s("detail").isEmpty { Text(i.s("detail")).font(Pixel.mono(10)).foregroundStyle(.secondary).lineLimit(4) }
        }
    }

    static func duration(_ ms: Int?) -> String {
        guard let ms else { return "" }
        if ms < 1000 { return "\(ms) ms" }
        if ms < 60_000 { return String(format: "%.1f s", Double(ms) / 1000) }
        return "\(ms / 60_000) min \((ms % 60_000) / 1000) s"
    }

    static func time(_ iso: String) -> String {
        guard let d = ISO8601DateFormatter.flexible(iso) else { return "" }
        return d.formatted(date: .omitted, time: .standard)
    }
}

extension ISO8601DateFormatter {
    /// Server timestamps carry microseconds; the formatter reads at most milliseconds.
    static func flexible(_ raw: String) -> Date? {
        let s = raw.replacingOccurrences(of: #"(\.\d{3})\d+"#, with: "$1", options: .regularExpression)
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: s)
    }
}

/// The General Manager's recovery plans for failed missions (GET /api/recovery). Nothing runs until you approve one.
struct RecoveryPlansSection: View {
    @Environment(AppState.self) private var app
    @State private var plans: [JSONValue] = []

    var body: some View {
        let pending = plans.filter { $0.s("status") == "PENDING" }
        Section {
            if pending.isEmpty {
                Text(app.connection == .live ? "No recovery plans waiting." : "Connect to see recovery plans.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            ForEach(pending) { p in RecoveryPlanRow(plan: p) { await load() } }
        } header: { Text("Recovery plans") } footer: {
            Text("Atlas drafts one when a mission fails. Approving starts a new mission with the same safety rules; a plan lapses after a week.")
        }
        .task(id: app.connection == .live) { await load() }
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { plans = []; return }
        plans = (try? await api.json("/api/recovery"))?.get("plans")?.list ?? []
    }
}

struct RecoveryPlanRow: View {
    @Environment(AppState.self) private var app
    let plan: JSONValue
    var onChange: () async -> Void = {}
    @State private var busy = false
    @State private var message: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(plan.s("mission_title")).font(.caption).foregroundStyle(.secondary)
            Text(plan.s("summary")).font(.subheadline.bold())
            Text(plan.s("rationale")).font(.caption)
            HStack(spacing: 6) {
                Text(plan.s("failure_mode")).font(Pixel.mono(10)).padding(.horizontal, 5).padding(.vertical, 2)
                    .background(Theme.warn.opacity(0.25), in: Capsule())
                Text(plan.s("mode_name")).font(.caption2).foregroundStyle(.secondary)
            }
            if plan.s("status") == "PENDING" && plan.get("actionable")?.bool == true {
                HStack {
                    Button("Approve") { Task { await decide(true) } }.buttonStyle(.borderedProminent).tint(Theme.ok)
                    Button("Decline", role: .destructive) { Task { await decide(false) } }.buttonStyle(.bordered)
                }.disabled(busy)
            } else {
                Text(plan.s("status") == "INFO" ? "Nothing to run: this is a note." : "This plan is \(plan.s("status").lowercased()).")
                    .font(.caption2).foregroundStyle(.secondary)
            }
            if let message { Text(message).font(.caption) }
        }
    }

    private func decide(_ approve: Bool) async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        if approve {
            guard await ReleaseReviewView.authenticate(reason: "Start the recovery mission") else { message = "Face ID didn't confirm it's you."; return }
        }
        do {
            _ = try await api.json("/api/recovery/\(plan.s("id"))/\(approve ? "approve" : "decline")", method: "POST")
            message = approve ? "Started. It's in your missions." : "Declined."
            await onChange()
        } catch { message = error.localizedDescription }
    }
}

/// Atlas's daily brief on the Home screen (GET /api/insights/brief): counted from the records, money estimated.
struct BriefCard: View {
    @Environment(AppState.self) private var app
    @State private var brief: JSONValue?

    var body: some View {
        Group {
            if let b = brief {
                VStack(alignment: .leading, spacing: 8) {
                    PixelHeader(text: "Daily brief", trailing: "Atlas")
                    Text(b.s("headline")).font(.subheadline.bold()).fixedSize(horizontal: false, vertical: true)
                    let failed = b.get("failed")?.list ?? []
                    if !failed.isEmpty {
                        Text("Failed: " + failed.prefix(3).map { $0.s("title") }.joined(separator: "; "))
                            .font(.caption).foregroundStyle(Theme.bad).fixedSize(horizontal: false, vertical: true)
                    }
                    let w = b.get("waiting")
                    HStack(spacing: 12) {
                        stat("\(w?.get("approvals")?.int ?? 0)", "approvals")
                        stat("\(w?.get("recovery_plans")?.list.count ?? 0)", "recovery plans")
                        stat(String(format: "$%.2f", b.get("spend")?.get("today_usd")?.double ?? 0), "spent today (est.)")
                    }
                    if let l = b.get("lessons")?.list.first {
                        Text("\(l.s("agent")) learned: \(l.s("lesson"))").font(.caption).foregroundStyle(.secondary).lineLimit(3)
                    }
                    ForEach(Array((b.get("forecast_warnings")?.list ?? []).prefix(2).enumerated()), id: \.offset) { _, w in
                        Label("At today's pace \(w.s("agent")) hits a cap around \(ForecastView.clock(w.s("hits_cap_at")))",
                              systemImage: "exclamationmark.triangle.fill").font(.caption).foregroundStyle(Theme.warn)
                    }
                    if b.get("quiet_now")?.bool == true {
                        Label("Quiet hours: scheduled work is waiting", systemImage: "moon.zzz.fill").font(.caption).foregroundStyle(Theme.gold)
                    }
                }
                .accessibilityElement(children: .combine)
            }
        }
        .task(id: app.connection == .live) {
            guard app.connection == .live, let api = app.api else { brief = nil; return }
            brief = try? await api.json("/api/insights/brief")
        }
    }

    private func stat(_ v: String, _ k: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(v).font(Pixel.mono(15)).foregroundStyle(Theme.ink)
            Text(k).font(.caption2).foregroundStyle(.secondary)
        }
    }
}

/// Week-by-week reliability for every agent (GET /api/insights/scorecards).
struct ScorecardsView: View {
    @Environment(AppState.self) private var app
    @State private var data: JSONValue?

    var body: some View {
        List {
            if let d = data {
                let agents = d.get("agents")?.list ?? []
                if agents.isEmpty { Text("No task runs yet in these weeks.").foregroundStyle(.secondary) }
                ForEach(agents) { a in ScorecardRow(card: a) }
                Section { } footer: { Text("Counted from task runs. Trend: \(d.s("trend_rule")). Costs are estimates.") }
            } else if app.connection != .live {
                Text("Connect to your Mac and sign in to see scorecards.").foregroundStyle(.secondary)
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Agent scorecards")
        .task { data = try? await app.api?.json("/api/insights/scorecards") }
    }
}

struct ScorecardRow: View {
    let card: JSONValue

    var body: some View {
        let t = card.get("total")
        let weeks = card.get("weeks")?.list ?? []
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(card.s("agent")).bold()
                Text(card.s("role")).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                Spacer()
                Text(card.s("trend")).font(.caption2.bold()).foregroundStyle(Self.trendColor(card.s("trend")))
            }
            HStack(alignment: .bottom, spacing: 4) {
                ForEach(Array(weeks.enumerated()), id: \.offset) { _, w in
                    let rate = w.get("success_rate")?.double
                    VStack(spacing: 2) {
                        RoundedRectangle(cornerRadius: 2)
                            .fill(Self.barColor(rate))
                            .frame(width: 22, height: Self.barHeight(rate))
                        Text(String(w.s("week").suffix(5))).font(.system(size: 8)).foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(Self.weekLabel(w.s("week"), rate))
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text("\(t?.get("finished")?.int ?? 0) done · \(t?.get("failed")?.int ?? 0) failed").font(.caption)
                    if let f = t?.get("first_try_rate")?.double {
                        Text("\(Int(f * 100))% first try").font(.caption2).foregroundStyle(.secondary)
                    }
                    if !card.s("top_failure").isEmpty {
                        Text("most often: \(card.s("top_failure"))").font(.caption2).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    static func barColor(_ rate: Double?) -> Color {
        guard let rate else { return Color.gray.opacity(0.3) }
        if rate >= 0.8 { return Theme.ok }
        return rate >= 0.5 ? Theme.warn : Theme.bad
    }

    static func barHeight(_ rate: Double?) -> CGFloat {
        let r: Double = rate ?? 0
        return max(3, CGFloat(r * 30))
    }

    static func weekLabel(_ week: String, _ rate: Double?) -> String {
        guard let rate else { return "Week of \(week): no tasks" }
        return "Week of \(week): \(Int(rate * 100)) percent of tasks finished"
    }

    static func trendColor(_ t: String) -> Color {
        switch t {
        case "improving": return Theme.ok
        case "slipping": return Theme.bad
        case "steady": return Theme.cyan
        default: return .secondary
        }
    }
}

/// Check the tamper-evident event log (GET /api/insights/audit/verify).
struct AuditLogView: View {
    @Environment(AppState.self) private var app
    @State private var result: JSONValue?
    @State private var busy = false

    var body: some View {
        List {
            Section {
                Button(busy ? "Checking…" : "Verify the log") { Task { await check() } }.disabled(busy || app.connection != .live)
            } footer: {
                Text("Every event is chained to the one before it with SHA-256. Changing, deleting or reordering any event breaks the chain from that point, and this check says where.")
            }
            if let r = result {
                Section {
                    Label(r.get("ok")?.bool == true ? "The log is intact" : "The log was altered",
                          systemImage: r.get("ok")?.bool == true ? "checkmark.shield.fill" : "exclamationmark.shield.fill")
                        .foregroundStyle(r.get("ok")?.bool == true ? Theme.ok : Theme.bad).font(.headline)
                    Text(r.s("note")).font(.subheadline)
                    Text("\(r.get("checked")?.int ?? 0) events checked").font(.caption).foregroundStyle(.secondary)
                    if !r.s("latest_hash").isEmpty {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Latest link").font(.caption2).foregroundStyle(.secondary)
                            Text(r.s("latest_hash")).font(Pixel.mono(10)).textSelection(.enabled)
                        }
                        .accessibilityLabel("Latest link hash, starts with \(String(r.s("latest_hash").prefix(8)))")
                    }
                } footer: { Text("Note the latest link somewhere else now and then: if it ever stops matching, the history was rewritten.") }
            }
        }
        .navigationTitle("Audit log")
    }

    private func check() async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        result = try? await api.json("/api/insights/audit/verify")
    }
}

/// Saves a mission's audit file (GET /api/insights/audit/missions/{id}) so you can share or keep it.
struct AuditExportButton: View {
    @Environment(AppState.self) private var app
    let missionId: String
    @State private var file: URL?
    @State private var failed = false

    var body: some View {
        Group {
            if let file {
                ShareLink(item: file) { Label("Share the audit file", systemImage: "square.and.arrow.up") }
            } else {
                Button { Task { await make() } } label: { Label(failed ? "Couldn't build the audit file. Try again" : "Build the audit file", systemImage: "doc.badge.gearshape") }
            }
        }
    }

    private func make() async {
        guard let api = app.api else { return }
        do {
            let data = try await api.rawData("/api/insights/audit/missions/\(missionId)")  // the server's exact bytes, so the hash checks out
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("mission-\(missionId.prefix(8))-audit.json")
            try data.write(to: url, options: .atomic)
            file = url
        } catch { failed = true }
    }
}

extension APIClient {
    /// A response's raw bytes (for files that must stay byte-for-byte what the server sent).
    func rawData(_ path: String) async throws -> Data {
        let (data, resp) = try await URLSession.shared.data(for: request(path))
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIError(status: status, detail: detail ?? HTTPURLResponse.localizedString(forStatusCode: status))
        }
        return data
    }
}

/// Everything waiting for you, at the top of the Owner tab (GET /api/insights/inbox).
struct InboxSection: View {
    @Environment(AppState.self) private var app
    @State private var box: JSONValue?

    var body: some View {
        let items = box?.get("items")?.list ?? []
        Section {
            if items.isEmpty {
                Text(app.connection == .live ? "Nothing is waiting for you." : "Connect to see what's waiting.").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(Array(items.prefix(12).enumerated()), id: \.offset) { _, i in
                if i.s("kind") == "permissions" {
                    NavigationLink { PermissionsView() } label: { row(i) }
                } else if i.s("kind") == "schedule" {
                    NavigationLink { SchedulesView() } label: { row(i) }
                } else {
                    row(i)
                }
            }
        } header: {
            Text("Waiting for you (\(box?.get("total")?.int ?? 0))")
        } footer: {
            Text("Soonest to expire first, then oldest. Decide each one in its section below.")
        }
        .task(id: "\(app.connection == .live)-\(app.inboxTotal)") {
            guard app.connection == .live, let api = app.api else { box = nil; return }
            box = try? await api.json("/api/insights/inbox")
        }
    }

    private func row(_ i: JSONValue) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: Self.icon(i.s("kind"))).foregroundStyle(i.get("urgent")?.bool == true ? Theme.bad : Theme.cyan).frame(width: 20)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(i.s("title")).font(.subheadline.bold()).lineLimit(2)
                if !i.s("detail").isEmpty { Text(i.s("detail")).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                Text(Self.when(i)).font(.caption2).foregroundStyle(i.get("urgent")?.bool == true ? Theme.bad : .secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }

    static func icon(_ kind: String) -> String {
        switch kind {
        case "approval": return "checkmark.seal"
        case "recovery_plan": return "arrow.triangle.2.circlepath"
        case "release": return "shippingbox"
        case "money": return "dollarsign.circle"
        case "permissions": return "key"
        case "schedule": return "calendar.badge.exclamationmark"
        default: return "tray"
        }
    }

    static func when(_ i: JSONValue) -> String {
        var parts: [String] = []
        if let m = i.get("age_minutes")?.int { parts.append(m < 60 ? "waiting \(m) min" : m < 1440 ? "waiting \(m / 60) h" : "waiting \(m / 1440) d") }
        if let h = i.get("hours_left")?.double { parts.append(h <= 0 ? "expired" : h < 24 ? "expires in \(Int(h)) h" : "expires in \(Int(h / 24)) d") }
        return parts.joined(separator: " · ")
    }
}

/// Search the records (GET /api/insights/search): missions, steps, messages, lessons, decisions, artifacts.
struct RecordSearchView: View {
    @Environment(AppState.self) private var app
    @State private var query = ""
    @State private var result: JSONValue?

    var body: some View {
        List {
            if app.connection != .live {
                Text("Connect to your Mac and sign in to search.").foregroundStyle(.secondary)
            } else if let r = result {
                let items = r.get("results")?.list ?? []
                if items.isEmpty && query.count >= 2 { Text("Nothing in the records matches \"\(query)\".").foregroundStyle(.secondary) }
                ForEach(Array(items.enumerated()), id: \.offset) { _, x in
                    if !x.s("mission_id").isEmpty {
                        NavigationLink { MissionTraceView(missionId: x.s("mission_id")) } label: { row(x) }
                    } else {
                        row(x)
                    }
                }
            } else {
                Text("Search missions, steps, what agents said, lessons, manager decisions and files.").font(.caption).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Search")
        .searchable(text: $query, prompt: "Search the records")
        .task(id: query) {
            guard query.count >= 2, let api = app.api else { result = nil; return }
            try? await Task.sleep(for: .milliseconds(300))  // wait for typing to pause
            if Task.isCancelled { return }
            var allowed = CharacterSet.urlQueryAllowed
            allowed.remove(charactersIn: "&+=?#")  // so "R&D" or "C++" reach the server whole
            let q = query.addingPercentEncoding(withAllowedCharacters: allowed) ?? query
            result = try? await api.json("/api/insights/search?q=\(q)")
        }
    }

    private func row(_ x: JSONValue) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(x.s("kind")).font(Pixel.mono(10)).padding(.horizontal, 5).padding(.vertical, 1)
                    .background(Theme.cyan.opacity(0.2), in: Capsule())
                Text(x.s("title")).font(.subheadline.bold()).lineLimit(1)
            }
            Text(x.s("snippet")).font(.caption).foregroundStyle(.secondary).lineLimit(3)
            Text(String(x.s("at").prefix(16)).replacingOccurrences(of: "T", with: " ")).font(.caption2).foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }
}

/// Where today's estimated spend is heading (GET /api/insights/forecast).
struct ForecastView: View {
    @Environment(AppState.self) private var app
    @State private var data: JSONValue?

    var body: some View {
        List {
            if let d = data {
                let warnings = d.get("warnings")?.list ?? []
                if !warnings.isEmpty {
                    Section("Heading for a cap today") {
                        ForEach(Array(warnings.enumerated()), id: \.offset) { _, w in
                            Label("\(w.s("agent")) around \(Self.clock(w.s("hits_cap_at")))", systemImage: "exclamationmark.triangle.fill")
                                .foregroundStyle(Theme.warn)
                        }
                    }
                }
                let t = d.get("total")
                Section("Everyone") {
                    line("Spent so far", t?.get("spent")?.double)
                    line("At this pace by midnight UTC", t?.get("projected")?.double)
                    line("Daily budget", t?.get("daily_budget_usd")?.double)
                }
                Section("By agent") {
                    let agents = d.get("agents")?.list ?? []
                    if agents.isEmpty { Text("No AI calls yet today.").foregroundStyle(.secondary) }
                    ForEach(agents) { a in
                        VStack(alignment: .leading, spacing: 2) {
                            HStack {
                                Text(a.s("agent")).bold()
                                Spacer()
                                Text(String(format: "$%.2f", a.get("spent")?.double ?? 0)).font(Pixel.mono(13))
                            }
                            Text(a.get("enough_data")?.bool == true
                                 ? String(format: "about $%.2f by midnight · $%.3f an hour", a.get("projected")?.double ?? 0, a.get("per_hour")?.double ?? 0)
                                 : "Not enough calls today to project").font(.caption).foregroundStyle(.secondary)
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
                Section { } footer: { Text("An estimate: \(d.s("method")). The cap per agent comes from your charter.") }
            } else if app.connection != .live {
                Text("Connect to your Mac and sign in to see the forecast.").foregroundStyle(.secondary)
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Spend forecast")
        .task { data = try? await app.api?.json("/api/insights/forecast") }
        .refreshable { data = try? await app.api?.json("/api/insights/forecast") }
    }

    private func line(_ k: String, _ v: Double?) -> some View {
        HStack { Text(k); Spacer(); Text(v.map { String(format: "$%.2f", $0) } ?? "—").font(Pixel.mono(13)) }
    }

    static func clock(_ iso: String) -> String {
        guard let d = ISO8601DateFormatter.flexible(iso) else { return "later today" }
        return d.formatted(date: .omitted, time: .shortened)
    }
}

/// Scheduled missions (GET /api/schedules): pause, resume or delete. New ones are set up by asking in the City
/// ("every Monday at 9 run the tests") and confirming.
struct SchedulesView: View {
    @Environment(AppState.self) private var app
    @State private var list: [JSONValue] = []
    @State private var loaded = false
    @State private var message: String?
    @State private var budgetFor: String?
    @State private var budgetText = ""

    var body: some View {
        List {
            if app.connection != .live {
                Text("Connect to your Mac and sign in to see schedules.").foregroundStyle(.secondary)
            } else if loaded && list.isEmpty {
                Text("No schedules yet. In the City, ask Sentry \"every weekday at 9 run the tests\" or Lumen \"every day research budgeting apps\", then confirm.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            ForEach(list) { s in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(s.s("title")).font(.subheadline.bold()).lineLimit(2)
                        Spacer()
                        Toggle("", isOn: Binding(get: { s.get("enabled")?.int == 1 }, set: { on in Task { await toggle(s.s("id"), on) } }))
                            .labelsHidden()
                            .accessibilityLabel(s.get("enabled")?.int == 1 ? "Pause this schedule" : "Resume this schedule")
                    }
                    Text(s.s("when")).font(.caption)
                    Text(s.get("enabled")?.int == 1 ? "Next: \(Self.local(s.s("next_run_at")))" : "Paused")
                        .font(.caption).foregroundStyle(.secondary)
                    if !s.s("paused_reason").isEmpty && s.get("enabled")?.int != 1 {
                        Text("Why: \(s.s("paused_reason"))")
                            .font(.caption2).foregroundStyle(Theme.warn)
                    }
                    Text("\(s.get("runs")?.int ?? 0) run(s)" + (s.s("last_error").isEmpty ? "" : " · last try: \(s.s("last_error"))"))
                        .font(.caption2).foregroundStyle(s.s("last_error").isEmpty ? Color.secondary : Theme.warn)
                    Text(Self.costLine(s)).font(.caption2).foregroundStyle(.secondary)
                }
                .swipeActions {
                    Button("Delete", role: .destructive) { Task { await remove(s.s("id")) } }
                    if s.get("enabled")?.int == 1 {
                        Button("Skip next") { Task { await post(s.s("id"), "skip", done: "Skipped the next run.") } }.tint(Theme.warn)
                    }
                }
                .swipeActions(edge: .leading) {
                    Button("Run now") { Task { await post(s.s("id"), "run-now", done: "Started. It's in the journal.") } }.tint(Theme.cyan)
                    Button("Budget") { budgetFor = s.s("id"); budgetText = s.get("budget_usd")?.double.map { String(format: "%.2f", $0) } ?? "" }
                        .tint(Theme.gold)
                }
                .accessibilityAction(named: "Set a budget per run") {
                    budgetFor = s.s("id"); budgetText = s.get("budget_usd")?.double.map { String(format: "%.2f", $0) } ?? ""
                }
                .accessibilityAction(named: "Run now") { Task { await post(s.s("id"), "run-now", done: "Started. It's in the journal.") } }
                .accessibilityAction(named: s.get("enabled")?.int == 1 ? "Skip next run" : "Skip next run (resume it first)") {
                    Task { await post(s.s("id"), "skip", done: "Skipped the next run.") }
                }
            }
            if let message { Text(message).font(.caption) }
            Section { } footer: { Text("Each run follows your charter, quiet hours and the emergency stop. Only test runs and research can be scheduled. Three failed runs in a row pause a schedule. Swipe right to run now or set a budget, left to skip the next run. Costs are estimates.") }
        }
        .navigationTitle("Schedules")
        .alert("Budget per run", isPresented: Binding(get: { budgetFor != nil }, set: { if !$0 { budgetFor = nil } })) {
            TextField("Dollars, e.g. 0.50 (empty: default)", text: $budgetText).keyboardType(.decimalPad)
            Button("Save") { Task { await saveBudget() } }
            Button("Cancel", role: .cancel) { budgetFor = nil }
        } message: {
            Text("Each run's mission budget. Your charter's cap still applies.")
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        list = (try? await api.json("/api/schedules"))?.get("schedules")?.list ?? []
        loaded = true
    }

    /// The next run in this phone's time zone (the server stores UTC).
    static func local(_ iso: String) -> String {
        guard let d = ISO8601DateFormatter.flexible(iso) else { return iso }
        return d.formatted(date: .abbreviated, time: .shortened)
    }

    private func toggle(_ id: String, _ on: Bool) async {
        guard let api = app.api else { return }
        do { _ = try await api.json("/api/schedules/\(id)/enabled", method: "POST", body: ["enabled": .bool(on)]) } catch { message = error.localizedDescription }
        await load()
    }

    static func costLine(_ s: JSONValue) -> String {
        let c = s.get("cost")
        var parts: [String] = []
        if let per = c?.get("per_run_usd")?.double {
            let month = c?.get("monthly_usd")?.double ?? 0
            parts.append(String(format: "About $%.2f a run, ~$%.2f a month (estimated)", per, month))
        } else {
            parts.append("No cost yet: it hasn't run")
        }
        if let b = s.get("budget_usd")?.double { parts.append(String(format: "budget $%.2f a run", b)) }
        return parts.joined(separator: " · ")
    }

    private func saveBudget() async {
        guard let api = app.api, let id = budgetFor else { return }
        budgetFor = nil
        let t = budgetText.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: "$", with: "")
        let value: JSONValue = t.isEmpty ? .null : .number(Double(t) ?? -1)
        do {
            _ = try await api.json("/api/schedules/\(id)/budget", method: "POST", body: ["budget_usd": value])
            message = t.isEmpty ? "Back to the default budget." : "Budget saved."
        } catch { message = error.localizedDescription }
        await load()
    }

    private func post(_ id: String, _ action: String, done: String) async {
        guard let api = app.api else { return }
        do {
            _ = try await api.json("/api/schedules/\(id)/\(action)", method: "POST")
            message = done
        } catch { message = error.localizedDescription }
        await load()
    }

    private func remove(_ id: String) async {
        guard let api = app.api else { return }
        guard await ReleaseReviewView.authenticate(reason: "Delete this schedule") else { message = "Face ID didn't confirm it's you."; return }
        do { _ = try await api.json("/api/schedules/\(id)", method: "DELETE") } catch { message = error.localizedDescription }
        await load()
    }
}

/// Urgent / normal / low (POST /api/missions/{id}/priority): which waiting mission starts first when all slots are busy.
struct PriorityPicker: View {
    @Environment(AppState.self) private var app
    let missionId: String
    @State var priority: String
    @State private var note: String?
    @State private var saved = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Picker("Priority", selection: $priority) {
                Text("Urgent").tag("urgent")
                Text("Normal").tag("normal")
                Text("Low").tag("low")
            }
            .pickerStyle(.segmented)
            .onChange(of: priority) { _, new in if new != saved { Task { await save(new) } } }
            .onAppear { if saved.isEmpty { saved = priority } }
            Text(note ?? "When more missions are waiting than can run at once, urgent ones start first.")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }

    private func save(_ p: String) async {
        guard let api = app.api else { return }
        do {
            let r = try await api.json("/api/missions/\(missionId)/priority", method: "POST", body: ["priority": .string(p)])
            let waiting = r.get("waiting")?.list.count ?? 0
            note = waiting > 0 ? "Saved. \(waiting) mission(s) waiting for a free slot." : "Saved."
            saved = p
        } catch {
            note = error.localizedDescription
            priority = saved  // show what's really stored
        }
    }
}
