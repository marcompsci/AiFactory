import SwiftUI

/// Cost reviews from the AI Central Bank that are waiting at the Owner's Tower.
struct FinanceDecisionsSection: View {
    @Environment(AppState.self) private var app
    @State private var packets: [FinancePacket] = []
    @State private var unavailable = false

    var body: some View {
        Section {
            if unavailable {
                Text("Financial decisions need an owner or admin account.").font(.caption).foregroundStyle(.secondary)
            } else if packets.isEmpty {
                Text("Nothing financial is waiting. Paid-tool requests and fee reviews arrive here from the AI Central Bank.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            ForEach(packets) { p in
                NavigationLink(value: FinanceRoute(packetId: p.id)) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(p.origin == "purchase_request" ? "Paid tool: \(p.vendor)" : "Fee review: \(p.vendor)").font(.headline)
                        Text(p.summary ?? p.item).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                        HStack {
                            StatusPill(text: "Waiting for you", color: Theme.gold)
                            if p.isSimulated { StatusPill(text: "Simulated data", color: Theme.warn) }
                        }
                    }
                }
            }
        } header: {
            Text("Financial decisions")
        } footer: {
            Text("No money moves without your approval, Face ID, and a code from your authenticator app.")
        }
        .task(id: app.ledger.lastSequence) { await load() }
    }

    private func load() async {
        guard let api = app.api else { return }
        do {
            packets = try await api.financePackets().filter { $0.status == "OWNER_DECISION" }
            unavailable = false
        } catch let e as APIError where e.status == 403 {
            unavailable = true
        } catch {}
    }
}

struct FinanceRoute: Hashable { let packetId: String }

struct FinanceDecisionView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let packetId: String
    @State private var detail: FinancePacketDetail?
    @State private var approving: FinanceApproval?
    @State private var code = ""
    @State private var note = ""
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        List {
            if let d = detail {
                Section {
                    Text("\(d.packet.vendor): \(d.packet.item)").font(.headline)
                    if let s = d.packet.summary { Text(s).font(.subheadline) }
                    if let reason = d.packet.classificationReason { Text(reason).font(.caption).foregroundStyle(.secondary) }
                    if let gm = d.packet.gmDecision.get("outcome")?.string {
                        Text("General Manager: \(Format.human(gm))").font(.caption).foregroundStyle(.secondary)
                    }
                    if d.packet.isSimulated {
                        Text("Simulated data: approving records a simulated purchase. No real money moves.").font(.caption).foregroundStyle(Theme.warn)
                    }
                }
                let open = d.approvals.filter { $0.status == "REQUESTED" }
                ForEach(open) { a in
                    Section(a.option == "recommended" ? "Recommended option" : "As requested") {
                        LabeledContent("Amount", value: Format.money(a.amountMinor, currency: a.currency) + (a.billingInterval.map { $0 == "one_time" ? "" : " per \($0)" } ?? ""))
                        LabeledContent("To", value: a.recipient + (a.itemName.map { " (\($0))" } ?? ""))
                        LabeledContent("From", value: a.accountLabel)
                        LabeledContent("Expires", value: a.expiresAt.prefix(16).replacingOccurrences(of: "T", with: " "))
                        LabeledContent("Fingerprint", value: String(a.payloadHash.prefix(16))).font(.system(.caption, design: .monospaced))
                        Button("Approve exactly this") { Task { await beginApproval(a) } }
                            .foregroundStyle(Theme.ok).disabled(busy)
                    }
                }
                if open.isEmpty {
                    Section {
                        Text("No purchase to approve: this is a recommendation. Any change is yours to make.").font(.caption)
                    }
                }
                Section {
                    TextField("Note (optional)", text: $note)
                    if open.isEmpty {
                        Button("Acknowledge") { Task { await decide("ACKNOWLEDGE") } }
                    } else {
                        Button("Reject", role: .destructive) { Task { await decide("REJECT") } }
                    }
                    Button("Defer two weeks") { Task { await decide("DEFER", deferDays: 14) } }
                    if d.packet.researchRounds < 3 { Button("Ask for more research") { Task { await decide("MORE_RESEARCH") } } }
                }
                if let error { Section { Text(error).foregroundStyle(Theme.bad) } }
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Cost review")
        .task { await load() }
        .sheet(item: $approving) { a in
            NavigationStack {
                Form {
                    Section {
                        Text("Approving \(Format.money(a.amountMinor, currency: a.currency)) to \(a.recipient).")
                        TextField("6-digit code", text: $code).keyboardType(.numberPad).textContentType(.oneTimeCode)
                            .font(.system(.title3, design: .monospaced))
                    } footer: {
                        Text("Enter the current code from your authenticator app. It confirms this one approval for five minutes.")
                    }
                    if let error { Text(error).foregroundStyle(Theme.bad) }
                }
                .navigationTitle("Confirm it's you")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel") { approving = nil } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Approve") { Task { await approve(a) } }.disabled(code.count != 6 || busy)
                    }
                }
            }
            .presentationDetents([.medium])
        }
    }

    private func load() async {
        guard let api = app.api else { return }
        do { detail = try await api.financePacket(packetId) } catch { self.error = error.localizedDescription }
    }

    private func beginApproval(_ a: FinanceApproval) async {
        // Face ID (or the passcode) on this phone first, then the authenticator code checked by the server.
        guard await ReleaseReviewView.authenticate(reason: "Approve \(Format.money(a.amountMinor, currency: a.currency)) to \(a.recipient)") else {
            error = "Face ID was not confirmed."
            return
        }
        code = ""
        error = nil
        approving = a
    }

    private func approve(_ a: FinanceApproval) async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        do {
            let token = try await api.stepUp(code: code, purpose: a.id)
            try await api.decidePacket(packetId, PacketDecisionRequest(decision: "APPROVE", approvalId: a.id, payloadHash: a.payloadHash,
                                                                        note: note.isEmpty ? nil : note, deferDays: nil), stepUpToken: token)
            approving = nil
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func decide(_ decision: String, deferDays: Int? = nil) async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        do {
            try await api.decidePacket(packetId, PacketDecisionRequest(decision: decision, approvalId: nil, payloadHash: nil,
                                                                        note: note.isEmpty ? nil : note, deferDays: deferDays))
            if decision == "ACKNOWLEDGE" { Haptics.success() }
            dismiss()
        } catch {
            Haptics.warning()
            self.error = error.localizedDescription
        }
    }
}
