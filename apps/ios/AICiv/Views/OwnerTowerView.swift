import LocalAuthentication
import SwiftUI
import WebKit

/// The Owner's Tower on iPhone: every release waiting for you, reviewed natively. Approving requires Face ID
/// (or your passcode) and sends the exact digest you are looking at; the server refuses a mismatched digest.
struct OwnerTowerView: View {
    @Environment(AppState.self) private var app

    var body: some View {
        NavigationStack {
            List {
                InboxSection()
                MissionApprovalsSection()
                RecoveryPlansSection()
                FinanceDecisionsSection()
                Section("Reliability") {
                    NavigationLink { ForecastView() } label: {
                        Label("Spend forecast: where today is heading", systemImage: "chart.line.uptrend.xyaxis")
                    }
                    NavigationLink { RecordSearchView() } label: {
                        Label("Search the records", systemImage: "magnifyingglass")
                    }
                    NavigationLink { FailureClinicView() } label: {
                        Label("Failure clinic: why agents failed, and what they learned", systemImage: "stethoscope")
                    }
                    NavigationLink { ScorecardsView() } label: {
                        Label("Agent scorecards: reliability week by week", systemImage: "chart.bar.xaxis")
                    }
                    NavigationLink { PermissionsView() } label: {
                        Label("Permissions: tools agents have but don't use", systemImage: "key")
                    }
                    NavigationLink { AuditLogView() } label: {
                        Label("Audit log: check nothing was changed", systemImage: "checkmark.shield")
                    }
                    NavigationLink { CharterView() } label: {
                        Label("Your charter: caps and quiet hours only you can change", systemImage: "scroll")
                    }
                }
                Section("App Lab") {
                    NavigationLink { AppLabView() } label: {
                        Label("Improvement proposals for your apps", systemImage: "flask")
                    }
                }
                let waiting = app.opportunities.filter { $0.status == "OWNER_APPROVAL" }
                if waiting.isEmpty {
                    ContentUnavailableView("Nothing is waiting for you",
                                           systemImage: "building.columns",
                                           description: Text("When Atlas approves a product, its release package travels here on the conveyor."))
                        .listRowBackground(Color.clear)
                }
                ForEach(waiting) { o in
                    NavigationLink(value: o.id) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(o.title).font(.headline)
                            HStack {
                                StatusPill(text: "Waiting for you", color: Theme.gold)
                                if o.dataMode == "fixture" { StatusPill(text: "Fixture research", color: Theme.warn) }
                            }
                        }
                    }
                }
                let approved = app.opportunities.filter { $0.status == "RELEASE_AUTHORIZED" }
                if !approved.isEmpty {
                    Section("Approved by you") {
                        ForEach(approved) { o in Label(o.title, systemImage: "checkmark.seal.fill").foregroundStyle(Theme.gold) }
                    }
                }
            }
            .navigationTitle("Owner's Tower")
            .navigationDestination(for: String.self) { id in ReleaseReviewView(opportunityId: id) }
            .navigationDestination(for: FinanceRoute.self) { r in FinanceDecisionView(packetId: r.packetId) }
            .refreshable { await app.refresh() }
        }
    }
}

/// Mission steps waiting for you (for example, publishing a reviewed change). Only these buttons approve anything.
struct MissionApprovalsSection: View {
    @Environment(AppState.self) private var app
    @State private var busy: String?
    @State private var error: String?
    @State private var confirming: ApprovalRow?

    var body: some View {
        Section {
            if app.approvals.isEmpty {
                Text("No mission step is waiting for you.").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(app.approvals) { a in
                VStack(alignment: .leading, spacing: 8) {
                    Text(a.summary).font(.callout)
                    Text(a.action).font(.caption.monospaced()).foregroundStyle(.secondary)
                    HStack {
                        Button("Approve") { confirming = a }.buttonStyle(.borderedProminent).tint(Theme.ok)
                        Button("Reject", role: .destructive) { Task { await decide(a, grant: false) } }.buttonStyle(.bordered)
                    }
                    .disabled(busy != nil)
                }
                .padding(.vertical, 4)
            }
            if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
        } header: {
            Text("Mission steps")
        } footer: {
            Text("Closing this screen, walking away from an agent or closing the app never counts as approval.")
        }
        .confirmationDialog("Approve this step?", isPresented: Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } }), titleVisibility: .visible) {
            if let a = confirming { Button("Approve") { Task { await decide(a, grant: true) } } }
        } message: {
            Text(confirming?.summary ?? "")
        }
    }

    private func decide(_ a: ApprovalRow, grant: Bool) async {
        guard let api = app.api else { return }
        busy = a.id
        defer { busy = nil }
        do {
            try await api.decideApproval(a.id, grant: grant)
            error = nil
            await app.refresh()
        } catch { self.error = (error as? APIError)?.detail ?? "Couldn't reach your Mac." }
    }
}

struct ReleaseReviewView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let opportunityId: String
    @State private var dossier: Dossier?
    @State private var preview: String?
    @State private var error: String?
    @State private var note = ""
    @State private var busy = false
    @State private var confirming: OwnerDecision?

    var body: some View {
        Group {
            if let d = dossier {
                content(d)
            } else if let error {
                ContentUnavailableView("Couldn't load this release", systemImage: "exclamationmark.triangle", description: Text(error))
            } else {
                ProgressView("Opening the release package")
            }
        }
        .navigationTitle(dossier?.appName ?? "Release")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func load() async {
        guard let api = app.api else { return }
        do {
            let d = try await api.dossier(opportunityId)
            dossier = d
            if let b = d.bundle { preview = try? await api.bundleFile(artifactId: b.artifactId, path: "index.html") }
        } catch {
            self.error = error.localizedDescription
        }
    }

    @ViewBuilder
    private func content(_ d: Dossier) -> some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    Text(d.tagline).foregroundStyle(.secondary)
                    if let r = d.managerReview {
                        StatusPill(text: r.verdict == "APPROVED_FOR_OWNER_REVIEW" ? "Atlas recommends you approve" : Format.human(r.verdict),
                                   color: Theme.status(r.verdict == "APPROVED_FOR_OWNER_REVIEW" ? "pass" : "warn"))
                    }
                    if d.opportunity.dataMode == "fixture" {
                        StatusPill(text: "Built on fixture research, not live market data", color: Theme.warn)
                    }
                }
            }
            if let r = d.managerReview {
                Section("Manager recommendation") {
                    Text(r.summary)
                    Text(r.method == "model" ? "Written by \(r.model ?? "the model")" : "Decided by rule").font(.caption).foregroundStyle(.secondary)
                }
            }
            if let html = preview {
                Section("Preview") {
                    PreviewWebView(html: html).frame(height: 360).listRowInsets(EdgeInsets())
                }
            }
            Section("Build") {
                if let b = d.bundle {
                    Text("sha256 \(b.digest)").font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                }
                if let t = d.testReport {
                    Label(t.summaryLine ?? "No test run", systemImage: (t.failed ?? 1) == 0 ? "checkmark.circle" : "xmark.circle")
                        .foregroundStyle((t.failed ?? 1) == 0 ? Theme.ok : Theme.bad)
                    Text(d.testedExactBundle ? "Tests ran on this exact bundle." : "Tests ran on a different bundle.")
                        .font(.caption).foregroundStyle(d.testedExactBundle ? Theme.ok : Theme.bad)
                }
            }
            Section("Release checklist") {
                ForEach(d.checklist) { c in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack {
                            Text(Format.human(c.category))
                            Spacer()
                            StatusPill(text: c.status == "warn" ? "note" : c.status, color: Theme.status(c.status))
                        }
                        Text(c.evidence).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            Section("Market research · score \(String(format: "%.2f", d.opportunity.opportunityScore))") {
                ForEach(d.findings) { f in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(f.title).font(.subheadline)
                        Text(f.summary).font(.caption)
                        Text("\(Format.human(f.measurementType)) · \(f.dataCoverage) · \(f.geographicScope) · \(f.dataMode)")
                            .font(.caption2).foregroundStyle(f.dataMode == "fixture" ? Theme.warn : .secondary)
                        Text(f.sourceUrl).font(.system(.caption2, design: .monospaced)).foregroundStyle(.secondary)
                    }
                }
            }
            Section("Costs and risks") {
                Text("Planned \(Format.usd(d.opportunity.estimatedCostUsd)), spent \(Format.usd(d.estimatedSpendUsd)) (estimates)")
                ForEach(Array(d.risks.enumerated()), id: \.offset) { _, r in Text(r).font(.caption) }
            }
            if d.awaitingOwner {
                Section {
                    TextField("Note (optional)", text: $note, axis: .vertical)
                    ForEach(OwnerDecision.allCases) { decision in
                        Button(decision.label, role: decision == .reject ? .destructive : nil) { confirming = decision }
                            .disabled(busy)
                    }
                } footer: {
                    Text("Your decision is recorded permanently against this exact bundle. If it changes later, the approval is cancelled and it comes back to you.")
                }
            }
            if let error { Section { Text(error).foregroundStyle(Theme.bad) } }
        }
        .confirmationDialog(confirming?.label ?? "", isPresented: Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } }), titleVisibility: .visible) {
            if let decision = confirming {
                Button(decision.label, role: decision == .reject ? .destructive : nil) { Task { await decide(decision, d) } }
            }
        } message: {
            Text("For bundle \(String(d.bundle?.digest.prefix(12) ?? ""))")
        }
    }

    private func decide(_ decision: OwnerDecision, _ d: Dossier) async {
        guard let api = app.api, let digest = d.bundle?.digest else { return }
        if decision == .approve {
            guard await Self.authenticate(reason: "Approve the release of \(d.appName)") else {
                error = "Approval needs Face ID or your passcode."
                return
            }
        }
        busy = true
        defer { busy = false }
        do {
            try await api.decide(opportunityId, decision: decision, digest: digest, note: note.isEmpty ? nil : note)
            await app.refresh()
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }

    static func authenticate(reason: String) async -> Bool {
        let ctx = LAContext()
        var err: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthentication, error: &err) else { return true } // simulator without enrolment
        return (try? await ctx.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: reason)) ?? false
    }
}

/// Renders the prototype with JavaScript on but every network request blocked, so it can't call out.
struct PreviewWebView: UIViewRepresentable {
    let html: String

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: config)
        let rules = #"[{"trigger":{"url-filter":"^https?://.*"},"action":{"type":"block"}}]"#
        WKContentRuleListStore.default().compileContentRuleList(forIdentifier: "block-network", encodedContentRuleList: rules) { list, _ in
            if let list { view.configuration.userContentController.add(list) }
            view.loadHTMLString(html, baseURL: nil)
        }
        return view
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
