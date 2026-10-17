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
                    if b.get("quiet_now")?.bool == true {
                        Label("Quiet hours: scheduled work is waiting", systemImage: "moon.zzz.fill").font(.caption).foregroundStyle(Theme.gold)
                    }
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Daily brief. \(b.s("headline"))")
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
            let bundle = try await api.json("/api/insights/audit/missions/\(missionId)")
            let data = try JSONEncoder().encode(bundle)
            let url = FileManager.default.temporaryDirectory.appendingPathComponent("mission-\(missionId.prefix(8))-audit.json")
            try data.write(to: url, options: .atomic)
            file = url
        } catch { failed = true }
    }
}
