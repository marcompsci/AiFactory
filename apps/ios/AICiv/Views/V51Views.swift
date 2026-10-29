import SwiftUI

// MARK: Arena — the money game

/// The agents compete on verified money: realized savings, avoided cost, attributed revenue. Simulated scores are
/// shown apart and never count toward the verified ranking.
struct ArenaView: View {
    @Environment(AppState.self) private var app
    @State private var game: JSONValue?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    let totals = game?.get("totals")
                    HStack(spacing: 8) {
                        StatTile(label: "Verified", value: Money.minor(totals?.get("verified_minor")?.int), sub: "real money", color: Color(hex: 0x3DFFB8))
                        StatTile(label: "Simulated", value: Money.minor(totals?.get("simulated_minor")?.int), sub: "doesn't count", color: Theme.warn)
                    }
                    VStack(alignment: .leading, spacing: 8) {
                        PixelHeader(text: "Leaderboard", color: Theme.gold, trailing: game?.get("season")?.s("key"))
                        let board = game?.get("leaderboard")?.list ?? []
                        if board.isEmpty { Text("No scores yet.").font(.caption).foregroundStyle(.secondary) }
                        ForEach(board) { r in
                            let rank = r.get("rank")?.int ?? 0
                            HStack(spacing: 8) {
                                Text("#\(rank)").font(Pixel.title(13)).foregroundStyle(rank == 1 ? Theme.gold : rank <= 3 ? Theme.cyan : .secondary).frame(width: 34, alignment: .leading)
                                Rectangle().fill(Pixel.districtColor[r.s("district")] ?? Theme.cyan).frame(width: 10, height: 10)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(r.s("name")).font(.subheadline.bold())
                                    Text("Lv \(r.get("level")?.int ?? 1) · \(r.get("xp")?.int ?? 0) XP · \(r.get("plays")?.int ?? 0) plays").font(Pixel.mono(9)).foregroundStyle(.secondary)
                                }
                                Spacer()
                                VStack(alignment: .trailing, spacing: 1) {
                                    Text(Money.minor(r.get("verified_minor")?.int)).font(Pixel.mono(12)).foregroundStyle(Color(hex: 0x3DFFB8))
                                    if (r.get("simulated_minor")?.int ?? 0) > 0 {
                                        Text("sim \(Money.minor(r.get("simulated_minor")?.int))").font(Pixel.mono(9)).foregroundStyle(Theme.warn)
                                    }
                                }
                            }
                        }
                    }
                    .pixelPanel(Theme.gold.opacity(0.5))
                    VStack(alignment: .leading, spacing: 6) {
                        PixelHeader(text: "Recent plays")
                        let plays = Array((game?.get("plays")?.list ?? []).prefix(15))
                        if plays.isEmpty { Text("Nothing scored yet.").font(.caption).foregroundStyle(.secondary) }
                        ForEach(plays) { p in
                            HStack {
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(p.s("agent").isEmpty ? "—" : p.s("agent")).font(.caption.bold())
                                    Text(Format.human(p.s("kind")) + " · " + Ago.text(p.s("created_at"))).font(Pixel.mono(9)).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Text(Money.minor(p.get("amount_minor")?.int, currency: p.s("currency").isEmpty ? "USD" : p.s("currency")))
                                    .font(Pixel.mono(11)).foregroundStyle(p.get("verified")?.isTrue == true ? Color(hex: 0x3DFFB8) : Theme.warn)
                            }
                        }
                    }
                    .pixelPanel()
                    if let rules = game?.s("rules"), !rules.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            PixelHeader(text: "Rules")
                            Text(rules).font(.caption).foregroundStyle(.secondary)
                        }
                        .pixelPanel()
                    }
                    if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
                }
                .padding(14)
            }
            .background(Pixel.sky.ignoresSafeArea())
            .navigationTitle("Arena")
            .refreshable { await load() }
            .task(id: app.ledger.lastSequence / 10) { await load() }
        }
    }

    private func load() async {
        guard let api = app.api else { return }
        do { game = try await api.game(); error = nil } catch { self.error = error.localizedDescription }
    }
}

// MARK: App Lab

struct AppLabView: View {
    @Environment(AppState.self) private var app
    @State private var lab: JSONValue?
    @State private var message: String?

    var body: some View {
        List {
            let waiting = (lab?.get("proposals")?.list ?? []).filter { $0.s("status") == "AWAITING_OWNER" }
            Section("Waiting for you") {
                if waiting.isEmpty { Text("No proposals waiting.").foregroundStyle(.secondary) }
                ForEach(waiting) { p in
                    NavigationLink { LabProposalView(id: p.s("id")) } label: { ProposalRow(p: p) }
                }
            }
            Section("Repositories") {
                let repos = lab?.get("repositories")?.list ?? []
                if repos.isEmpty { Text("Connect a repository from the web app (Owner → App Lab). The access token is entered there, never in chat.").font(.caption).foregroundStyle(.secondary) }
                ForEach(repos) { r in
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Text(r.s("full_name")).font(.subheadline.bold())
                            Spacer()
                            StatusPill(text: Format.human(r.s("status")), color: r.s("status") == "ACTIVE" ? Theme.ok : Theme.bad)
                        }
                        HStack {
                            Text("branch \(r.s("default_branch"))" + (r.get("autopilot")?.isTrue == true ? " · autopilot" : "")).font(Pixel.mono(10)).foregroundStyle(.secondary)
                            Spacer()
                            if r.s("status") == "ACTIVE" {
                                Button("Start cycle") { Task { await start(r.s("id")) } }.font(.caption).buttonStyle(.bordered)
                            }
                        }
                    }
                }
                if let message { Text(message).font(.caption).foregroundStyle(.secondary) }
            }
            Section("Cycles") {
                ForEach(lab?.get("cycles")?.list ?? [], id: \.self) { c in
                    HStack {
                        Text(Ago.text(c.s("created_at"))).font(.caption)
                        if c.s("data_mode") == "simulated" { Text("simulated").font(.caption2).foregroundStyle(Theme.warn) }
                        Spacer()
                        StatusPill(text: Format.human(c.s("status")), color: Theme.status(c.s("status")))
                    }
                }
            }
            Section("Earlier proposals") {
                ForEach((lab?.get("proposals")?.list ?? []).filter { $0.s("status") != "AWAITING_OWNER" }) { p in
                    NavigationLink { LabProposalView(id: p.s("id")) } label: { ProposalRow(p: p) }
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(Pixel.sky.ignoresSafeArea())
        .navigationTitle("App Lab")
        .refreshable { await load() }
        .task(id: app.ledger.lastSequence / 5) { await load() }
    }

    private func load() async {
        guard let api = app.api else { return }
        lab = try? await api.lab()
    }

    private func start(_ repo: String) async {
        guard let api = app.api else { return }
        do { try await api.labStartCycle(repo); message = "Research team dispatched. Nothing is pushed without your approval." ; await load() }
        catch { message = error.localizedDescription }
    }
}

struct ProposalRow: View {
    let p: JSONValue
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(p.s("title")).font(.subheadline).lineLimit(2)
            HStack {
                StatusPill(text: Format.human(p.s("status")), color: Theme.status(p.s("status")))
                Text(p.s("route") == "claude_issue" ? "via Claude Code" : "draft PR").font(Pixel.mono(9)).foregroundStyle(.secondary)
                if p.s("data_mode") == "simulated" { Text("simulated").font(.caption2).foregroundStyle(Theme.warn) }
            }
        }
    }
}

/// One proposal: what changes, why (the research behind it), the General Manager's review, the diff, and the
/// owner's decision. Approving needs Face ID on this phone and then the server's step-up (authenticator code).
struct LabProposalView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let id: String
    @State private var detail: JSONValue?
    @State private var code = ""
    @State private var busy = false
    @State private var message: String?
    @State private var needsCode = false

    var body: some View {
        let p = detail?.get("proposal")
        List {
            if let p {
                Section {
                    Text(p.s("title")).font(.headline)
                    Text(p.s("summary")).font(.subheadline).foregroundStyle(.secondary)
                    HStack {
                        StatusPill(text: Format.human(p.s("status")), color: Theme.status(p.s("status")))
                        if p.s("data_mode") == "simulated" { StatusPill(text: "Simulated", color: Theme.warn) }
                    }
                    LabeledContent("Repository", value: detail?.get("repository")?.s("full_name") ?? "")
                    LabeledContent("Route", value: p.s("route") == "claude_issue" ? "Issue for Claude Code" : "Draft pull request")
                    LabeledContent("Risk", value: Format.human(p.s("risk")))
                }
                if let gm = p.get("gm_review") {
                    Section("General Manager") {
                        Text(Format.human(gm.s("verdict"))).bold().foregroundStyle(gm.s("verdict") == "recommend" ? Theme.ok : Theme.warn)
                        if !gm.s("reason").isEmpty { Text(gm.s("reason")).font(.caption) }
                        ForEach(gm.get("violations")?.list ?? [], id: \.self) { v in Text("• " + (v.string ?? "")).font(.caption).foregroundStyle(Theme.bad) }
                    }
                }
                let insights = detail?.get("insights")?.list ?? []
                if !insights.isEmpty {
                    Section("Research behind it") {
                        ForEach(insights) { i in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(i.s("title")).font(.subheadline)
                                Text(i.s("why_it_works")).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                }
                let files = p.get("files")?.list ?? []
                if !files.isEmpty {
                    Section("Files") { ForEach(files, id: \.self) { f in Text(f.string ?? f.s("path")).font(Pixel.mono(11)) } }
                }
                if !p.s("patch").isEmpty {
                    Section("Change") {
                        ScrollView(.horizontal) {
                            Text(p.s("patch").split(separator: "\n", omittingEmptySubsequences: false).prefix(400).joined(separator: "\n"))
                                .font(Pixel.mono(10)).textSelection(.enabled)
                        }
                        .frame(maxHeight: 320)
                    }
                } else if !p.s("instructions").isEmpty {
                    Section("Instructions for Claude Code") { Text(p.s("instructions")).font(Pixel.mono(10)) }
                }
                if ["AWAITING_OWNER", "DEFERRED"].contains(p.s("status")) {
                    Section {
                        if needsCode {
                            TextField("6-digit authenticator code", text: $code).keyboardType(.numberPad).textContentType(.oneTimeCode)
                        }
                        Button(busy ? "Working…" : "Approve and publish") { Task { await decide("APPROVE") } }
                            .disabled(busy || p.get("gm_review")?.s("verdict") != "recommend" || (needsCode && code.count != 6))
                        Button("Not now") { Task { await decide("DEFER") } }.disabled(busy)
                        Button("Reject", role: .destructive) { Task { await decide("REJECT") } }.disabled(busy)
                    } header: {
                        Text("Your decision")
                    } footer: {
                        Text("Approving opens a draft pull request (or a Claude Code issue) on a new branch — never the default branch. Face ID, then your authenticator code.")
                    }
                }
                if let message { Section { Text(message).font(.caption) } }
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Proposal")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func load() async {
        guard let api = app.api else { return }
        do { detail = try await api.labProposal(id) } catch { message = error.localizedDescription }
    }

    private func decide(_ decision: String) async {
        guard let api = app.api, let p = detail?.get("proposal") else { return }
        busy = true
        defer { busy = false }
        var stepUp: String?
        if decision == "APPROVE" {
            guard await ReleaseReviewView.authenticate(reason: "Approve \(p.s("title"))") else { message = "Face ID didn't confirm it's you."; return }
            if needsCode {
                do { stepUp = try await api.stepUp(code: code, purpose: "lab:\(id)") } catch { message = error.localizedDescription; return }
            }
        }
        do {
            try await api.labDecide(id, decision: decision, payloadHash: p.s("payload_hash"), stepUp: stepUp)
            if decision == "APPROVE" { Haptics.success() }
            message = decision == "APPROVE" ? "Approved. The developer is publishing it now." : "Saved."
            code = ""
            needsCode = false
            await load()
        } catch let e as APIError where e.status == 401 && decision == "APPROVE" {
            needsCode = true
            message = e.detail.contains("set up") ? "Set up an authenticator in the web app (Owner → Security) first." : "Enter your authenticator code to confirm."
        } catch {
            message = error.localizedDescription
        }
    }
}

// MARK: Factories

struct FactoriesView: View {
    @Environment(AppState.self) private var app
    @State private var data: JSONValue?
    @State private var message: String?

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                meters
                codex
                claude
                github
                if let message { Text(message).font(.caption).foregroundStyle(.secondary) }
            }
            .padding(14)
        }
        .background(Pixel.sky.ignoresSafeArea())
        .navigationTitle("Factories")
        .toolbar { Button("Sync") { Task { await sync() } } }
        .refreshable { await load() }
        .task(id: app.ledger.lastSequence / 10) { await load() }
    }

    private var meters: some View {
        let u = data?.get("plan_usage")?.get("data")
        let color = Pixel.districtColor["codex-factory"]!
        return VStack(alignment: .leading, spacing: 8) {
            PixelHeader(text: "Plan meters", color: color, trailing: data?.get("plan_usage")?.get("plans_enabled")?.isTrue == true ? "agents on your plans" : "plans off")
            if let u {
                let plan = u.s("plan")
                Text(plan.isEmpty ? "No plan has usage left; tasks wait." : "Agents run on the \(plan == "codex" ? "Codex" : "Claude") plan" + (u.s("model").isEmpty ? "." : " with \(u.s("model")).")).font(.subheadline.bold())
                Text(u.s("reason")).font(.caption).foregroundStyle(.secondary)
                if u.get("owner_active")?.isTrue == true {
                    Text("You're using Claude, so agents on the Claude plan use the smallest model.").font(.caption).foregroundStyle(color)
                }
                meterRow("Codex · 5 hours", u.get("codex")?.get("primary")?.get("used_percent")?.double, color)
                meterRow("Codex · week", u.get("codex")?.get("secondary")?.get("used_percent")?.double, color)
                meterRow("Claude · 5 hours (estimate)", u.get("claude")?.get("used_percent")?.double, Pixel.districtColor["claude-code-factory"]!)
                Text("\(u.get("claude")?.get("tokens_5h")?.int ?? 0) Claude tokens in 5 hours · \(Int(u.get("settings")?.get("claude_reserve_percent")?.double ?? 40))% kept for you")
                    .font(Pixel.mono(9)).foregroundStyle(.secondary)
            } else {
                Text("The meters fill in after the first check-in.").font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .pixelPanel(color.opacity(0.6))
    }

    private func meterRow(_ label: String, _ pct: Double?, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack { Text(label).font(.caption); Spacer(); Text(pct.map { "\(Int($0))%" } ?? "?").font(Pixel.mono(11)) }
            PixelBar(progress: (pct ?? 0) / 100, color: (pct ?? 0) >= 90 ? Theme.bad : (pct ?? 0) >= 70 ? Theme.warn : color)
        }
    }

    private var codex: some View {
        let cx = data?.get("codex")
        let d = cx?.get("data")
        let color = Pixel.districtColor["codex-factory"]!
        return VStack(alignment: .leading, spacing: 8) {
            NeonSign(icon: "◎", text: "Codex Factory", color: color, sub: cx?.get("linked")?.isTrue == true ? "linked" : "not linked")
            linkToggle("codex", linked: cx?.get("linked")?.isTrue == true)
            ForEach(Array((d?.get("sessions")?.list ?? []).prefix(6))) { s in
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(s.s("title")).font(.caption.bold()).lineLimit(1)
                        if s.get("by_agents")?.isTrue == true { Text("agents").font(Pixel.mono(8)).foregroundStyle(color) }
                        Spacer()
                        Text(Ago.text(s.s("last_activity_at"))).font(Pixel.mono(9)).foregroundStyle(.secondary)
                    }
                    ForEach(Array((s.get("completed_tasks")?.list ?? []).suffix(3)), id: \.self) { t in
                        Label(t.string ?? "", systemImage: "checkmark.square.fill").font(.caption2).foregroundStyle(Theme.ok).lineLimit(1)
                    }
                }
            }
            if cx?.get("found_on_server")?.isTrue == false {
                Text("No Codex data on the server's computer.").font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .pixelPanel(color.opacity(0.6))
    }

    private var claude: some View {
        let cc = data?.get("claude_code")
        let d = cc?.get("data")
        let color = Pixel.districtColor["claude-code-factory"]!
        return VStack(alignment: .leading, spacing: 8) {
            NeonSign(icon: "›_", text: "Claude Code Factory", color: color, sub: cc?.get("linked")?.isTrue == true ? "linked" : "not linked")
            linkToggle("claude_code", linked: cc?.get("linked")?.isTrue == true)
            if let d {
                Text("\(d.get("completed_recent")?.int ?? 0) tasks completed recently · \(d.get("active")?.int ?? 0) active sessions")
                    .font(Pixel.mono(10)).foregroundStyle(.secondary)
                ForEach(Array((d.get("sessions")?.list ?? []).prefix(6))) { s in
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            Text(s.s("title")).font(.caption.bold()).lineLimit(1)
                            Spacer()
                            Text(Ago.text(s.s("last_activity_at"))).font(Pixel.mono(9)).foregroundStyle(.secondary)
                        }
                        ForEach(Array((s.get("completed_tasks")?.list ?? []).suffix(3)), id: \.self) { t in
                            Label(t.string ?? "", systemImage: "checkmark.square.fill").font(.caption2).foregroundStyle(Theme.ok).lineLimit(1)
                        }
                    }
                }
                let mem = d.get("memory")?.list ?? []
                if !mem.isEmpty {
                    PixelHeader(text: "Shared memory", color: color, trailing: "\(mem.count) files")
                    ForEach(Array(mem.prefix(5)), id: \.self) { m in
                        Text(m.s("label")).font(Pixel.mono(10)).lineLimit(1)
                    }
                    Text("Agents can search this memory to work better; it's scrubbed of secrets and treated as untrusted context.").font(.caption2).foregroundStyle(.secondary)
                }
            } else if cc?.get("found_on_server")?.isTrue == false {
                Text("No Claude Code data on the server's computer.").font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .pixelPanel(color.opacity(0.6))
    }

    private var github: some View {
        let gh = data?.get("github")
        let color = Pixel.districtColor["github-factory"]!
        return VStack(alignment: .leading, spacing: 8) {
            NeonSign(icon: "⑂", text: "GitHub Factory", color: color, sub: gh?.get("linked")?.isTrue == true ? "linked" : "not linked")
            linkToggle("github", linked: gh?.get("linked")?.isTrue == true)
            ForEach(gh?.get("data")?.get("repos")?.list ?? [], id: \.self) { r in
                VStack(alignment: .leading, spacing: 4) {
                    Text(r.s("repo")).font(.caption.bold())
                    ForEach(Array((r.get("pulls")?.list ?? []).prefix(3))) { p in
                        HStack {
                            Text("#\(p.get("number")?.int ?? 0)").font(Pixel.mono(10)).foregroundStyle(.secondary)
                            Text(p.s("title")).font(.caption2).lineLimit(1)
                            Spacer()
                            Text(p.s("state")).font(Pixel.mono(9)).foregroundStyle(p.s("state") == "merged" ? Theme.violet : Theme.ok)
                        }
                    }
                    ForEach(Array((r.get("runs")?.list ?? []).prefix(3)), id: \.self) { run in
                        HStack {
                            Circle().fill(run.s("conclusion") == "success" ? Theme.ok : run.s("conclusion") == "failure" ? Theme.bad : Theme.warn).frame(width: 7, height: 7)
                            Text(run.s("name")).font(.caption2).lineLimit(1)
                            Spacer()
                            Text(run.s("branch")).font(Pixel.mono(9)).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                }
            }
            if (gh?.get("repositories")?.list ?? []).isEmpty {
                Text("Connect a repository in App Lab to see its pull requests and workflow runs here.").font(.caption).foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .pixelPanel(color.opacity(0.6))
    }

    private func linkToggle(_ kind: String, linked: Bool) -> some View {
        Toggle("Linked", isOn: Binding(get: { linked }, set: { on in Task { await link(kind, on) } })).font(.caption)
    }

    private func load() async {
        guard let api = app.api else { return }
        do { data = try await api.factories() } catch let e as APIError where e.status == 403 {
            message = "The factories are for the owner and admins."
        } catch { message = error.localizedDescription }
    }

    private func link(_ kind: String, _ on: Bool) async {
        guard let api = app.api else { return }
        do { try await api.factoryLink(kind, enabled: on); await load() } catch { message = error.localizedDescription }
    }

    private func sync() async {
        guard let api = app.api else { return }
        do { try await api.factorySync(); message = "Sync started." } catch { message = error.localizedDescription }
    }
}

// MARK: More

struct MoreView: View {
    @Environment(AppState.self) private var app
    var body: some View {
        NavigationStack {
            List {
                Section {
                    NavigationLink { AppLabView() } label: { Label("App Lab", systemImage: "flask") }
                    NavigationLink { FactoriesView() } label: { Label("Factories and plan meters", systemImage: "gearshape.2") }
                    NavigationLink { KnowledgeView() } label: { Label("Knowledge base", systemImage: "sparkles") }
                    NavigationLink { CompanyView() } label: { Label("Company", systemImage: "person.3") }
                    NavigationLink { ActivityView() } label: { Label("Activity", systemImage: "waveform") }
                    NavigationLink { CityView().navigationTitle("3D city").navigationBarTitleDisplayMode(.inline) } label: {
                        Label("3D city (from your Mac)", systemImage: "building.2")
                    }
                }
                Section {
                    NavigationLink { SettingsView() } label: { Label("Settings and sign-in", systemImage: "gear") }
                }
            }
            .navigationTitle("More")
        }
    }
}

/// Sign in with Google or GitHub (Supabase). Shown in Settings.
struct AccountSection: View {
    @Environment(AppState.self) private var app
    var body: some View {
        Section {
            if let s = app.session {
                LabeledContent("Signed in", value: s.email ?? "yes")
                if let p = s.provider { LabeledContent("With", value: p.capitalized) }
                Button("Sign out", role: .destructive) { app.signOut() }
            } else {
                Button { Task { await app.signIn(provider: "google") } } label: { Label("Sign in with Google", systemImage: "g.circle") }
                Button { Task { await app.signIn(provider: "github") } } label: { Label("Sign in with GitHub", systemImage: "chevron.left.forwardslash.chevron.right") }
            }
            if let e = app.authError { Text(e).font(.caption).foregroundStyle(Theme.bad) }
        } header: {
            Text("Account")
        } footer: {
            Text("Sign-in opens Google or GitHub in a secure browser sheet; this app never sees your password. The session is kept in the iOS Keychain.")
        }
    }
}


// MARK: Knowledge base

/// Phoronomics and Phoronomic Studios docs and skills the agents pull from. Read here; manage them on the web.
struct KnowledgeView: View {
    @Environment(AppState.self) private var app
    @State private var data: JSONValue?
    @State private var query = ""
    @State private var company = ""
    @State private var error: String?

    var body: some View {
        List {
            Section {
                Picker("Company", selection: $company) {
                    Text("All").tag("")
                    Text("Phoronomics").tag("phoronomics")
                    Text("Phoronomic Studios").tag("phoronomic_studios")
                }
                .pickerStyle(.segmented)
            } footer: {
                Text("\(data?.get("counts")?.get("skill")?.int ?? 0) skills · \(data?.get("counts")?.get("doc")?.int ?? 0) docs. Agents get the entries that fit their task automatically. Add or upload on the web (Knowledge tab).")
            }
            ForEach(data?.get("items")?.list ?? []) { it in
                NavigationLink { KnowledgeDocView(slug: it.s("slug")) } label: {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack {
                            Text(it.s("kind") == "skill" ? "✦" : "▤").foregroundStyle(it.s("kind") == "skill" ? Theme.gold : Theme.cyan)
                            Text(it.s("title")).font(.subheadline)
                        }
                        if !it.s("description").isEmpty { Text(it.s("description")).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                        Text(it.s("company_name")).font(Pixel.mono(9)).foregroundStyle(.secondary)
                    }
                }
            }
            if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
        }
        .searchable(text: $query, prompt: "Search docs and skills")
        .navigationTitle("Knowledge base")
        .task(id: query + company) { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        guard let api = app.api else { return }
        do { data = try await api.knowledge(query: query, company: company); error = nil } catch { self.error = error.localizedDescription }
    }
}

struct KnowledgeDocView: View {
    @Environment(AppState.self) private var app
    let slug: String
    @State private var doc: JSONValue?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                if let d = doc {
                    Text(d.s("title")).font(.title3.bold())
                    Text("\(d.s("kind") == "skill" ? "Skill" : "Doc") · \(d.s("company_name"))").font(Pixel.mono(10)).foregroundStyle(.secondary)
                    if !d.s("description").isEmpty { Text(d.s("description")).font(.subheadline).foregroundStyle(.secondary) }
                    Text(d.s("body")).font(Pixel.mono(11)).textSelection(.enabled).padding(.top, 6)
                } else {
                    ProgressView()
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .navigationBarTitleDisplayMode(.inline)
        .task { doc = try? await app.api?.knowledgeDocument(slug) }
    }
}
