import SwiftUI

/// Least-privilege review (GET /api/permissions/review): tools each agent may use but hasn't. Revoking is one tap
/// (after Face ID); restoring widens what an agent can do, so it also asks for your authenticator code.
struct PermissionsView: View {
    @Environment(AppState.self) private var app
    @State private var data: JSONValue?
    @State private var showAll = false
    @State private var message: String?
    @State private var busy = false
    @State private var needsCode: String?   // revocation id waiting for a code
    @State private var code = ""

    var body: some View {
        List {
            if app.connection != .live {
                Text("Connect to your Mac and sign in to review permissions.").foregroundStyle(.secondary)
            } else if let d = data {
                Section {
                    Text(d.get("enough_history")?.bool == true
                         ? "\(d.get("suggestions")?.int ?? 0) grant(s) unused for \(d.get("days")?.int ?? 30) days that no plan or pipeline needs."
                         : "Suggestions start after \(d.get("days")?.int ?? 30) days of records.")
                        .font(.subheadline)
                    Toggle("Show every grant", isOn: $showAll)
                    if let message { Text(message).font(.caption) }
                } footer: { Text(d.s("note")) }
                ForEach(d.get("agents")?.list ?? []) { a in
                    let grants = (a.get("grants")?.list ?? []).filter { showAll || $0.s("suggestion") == "revoke" }
                    let revoked = a.get("revoked")?.list ?? []
                    if !grants.isEmpty || !revoked.isEmpty {
                        Section(a.s("agent") + " · " + a.s("role")) {
                            ForEach(grants) { g in grantRow(a, g) }
                            ForEach(revoked) { r in revokedRow(r) }
                        }
                    }
                }
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Permissions")
        .task { await load() }
        .refreshable { await load() }
    }

    private func grantRow(_ a: JSONValue, _ g: JSONValue) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(g.s("tool")).font(Pixel.mono(13))
                Text(g.s("why")).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if g.s("suggestion") == "revoke" || showAll {
                Button("Revoke") { Task { await revoke(a.s("agent_id"), g.s("tool"), inPlan: g.get("in_plan")?.bool == true) } }
                    .buttonStyle(.bordered).tint(Theme.bad).disabled(busy)
                    .accessibilityLabel("Revoke \(g.s("tool")) from \(a.s("agent"))")
            }
        }
    }

    private func revokedRow(_ r: JSONValue) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Label(r.s("tool_name"), systemImage: "lock.fill").font(Pixel.mono(13))
                Spacer()
                Button("Restore") { Task { await restore(r.s("id")) } }.buttonStyle(.bordered).disabled(busy)
            }
            Text("Revoked \(String(r.s("revoked_at").prefix(10)))" + (r.s("reason").isEmpty ? "" : ": \(r.s("reason"))"))
                .font(.caption2).foregroundStyle(.secondary)
            if needsCode == r.s("id") {
                TextField("Authenticator code", text: $code).keyboardType(.numberPad).textContentType(.oneTimeCode)
                Button("Confirm restore") { Task { await restore(r.s("id")) } }.disabled(code.count < 6 || busy)
            }
        }
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        data = try? await api.json("/api/permissions/review")
    }

    private func revoke(_ agent: String, _ tool: String, inPlan: Bool) async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        guard await ReleaseReviewView.authenticate(reason: "Revoke \(tool)") else { message = "Face ID didn't confirm it's you."; return }
        do {
            let r = try await api.json("/api/permissions/revoke", method: "POST",
                                       body: ["agent_id": .string(agent), "tool": .string(tool), "reason": .string("least-privilege review")])
            message = r.get("warning")?.str ?? "Revoked \(tool)."
            await load()
        } catch { message = error.localizedDescription }
    }

    private func restore(_ id: String) async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        var stepUp: String?
        if needsCode == id {
            guard await ReleaseReviewView.authenticate(reason: "Restore a permission") else { message = "Face ID didn't confirm it's you."; return }
            do { stepUp = try await api.stepUp(code: code, purpose: "permissions") } catch { message = error.localizedDescription; return }
        }
        do {
            _ = try await api.json("/api/permissions/restore", method: "POST", body: ["revocation_id": .string(id)], stepUp: stepUp)
            message = "Restored."
            needsCode = nil
            code = ""
            await load()
        } catch let e as APIError where e.status == 401 {
            needsCode = id
            message = e.detail.contains("set up") ? "Set up an authenticator in the web app (Owner → Security) first." : "Enter your authenticator code to restore it."
        } catch { message = error.localizedDescription }
    }
}
