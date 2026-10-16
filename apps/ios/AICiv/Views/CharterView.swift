import SwiftUI

/// The owner's charter (GET/PUT /api/charter): rules only you amend. They can only make the town stricter than the
/// built-in safety; loosening one asks for Face ID and your authenticator code. Every amendment is listed.
struct CharterView: View {
    @Environment(AppState.self) private var app
    @State private var data: JSONValue?
    @State private var dailyOn = false
    @State private var daily = 1.0
    @State private var capOn = false
    @State private var cap = 5.0
    @State private var quietOn = false
    @State private var quietStart = CharterView.clock("22:00")
    @State private var quietEnd = CharterView.clock("07:00")
    @State private var note = ""
    @State private var needsCode = false
    @State private var code = ""
    @State private var message: String?
    @State private var busy = false

    var body: some View {
        Form {
            if app.connection != .live {
                Text("Connect to your Mac and sign in to read or amend your charter.").foregroundStyle(.secondary)
            } else if let d = data {
                if d.get("quiet_now")?.bool == true {
                    Label("Quiet hours now: scheduled work is waiting.", systemImage: "moon.zzz.fill").foregroundStyle(Theme.gold)
                }
                Section {
                    Toggle("Daily cap per agent", isOn: $dailyOn)
                    if dailyOn {
                        Stepper(value: $daily, in: 0.25...50, step: 0.25) { Text(String(format: "$%.2f a day, estimated", daily)) }
                    }
                } footer: { Text("When an agent reaches it, its mission pauses until tomorrow or until you raise the cap.") }
                Section {
                    Toggle("Cap on each mission's budget", isOn: $capOn)
                    if capOn {
                        Stepper(value: $cap, in: 0.5...50, step: 0.5) { Text(String(format: "$%.2f per mission", cap)) }
                    }
                } footer: { Text("Larger budgets are refused, and the default budget is held to the cap.") }
                Section {
                    Toggle("Quiet hours", isOn: $quietOn)
                    if quietOn {
                        DatePicker("From", selection: $quietStart, displayedComponents: .hourAndMinute)
                        DatePicker("Until", selection: $quietEnd, displayedComponents: .hourAndMinute)
                        Text("Time zone: \(TimeZone.current.identifier)").font(.caption).foregroundStyle(.secondary)
                    }
                } footer: { Text("Scheduled research, finance, App Lab and factory check-ins wait. Missions you start still run.") }
                Section {
                    TextField("Why (optional)", text: $note)
                    if needsCode {
                        TextField("Authenticator code", text: $code).keyboardType(.numberPad).textContentType(.oneTimeCode)
                    }
                    Button(busy ? "Saving…" : "Amend the charter") { Task { await save() } }.disabled(busy)
                    if let message { Text(message).font(.caption) }
                } footer: { Text("Making a rule stricter saves right away. Loosening one asks for Face ID and your authenticator code.") }
                Section("Always on (not in the charter, so no amendment can change them)") {
                    ForEach(Array((d.get("locked")?.list ?? []).enumerated()), id: \.offset) { _, r in
                        Label(r.str, systemImage: "lock.fill").font(.caption)
                    }
                }
                let history = d.get("amendments")?.list ?? []
                if !history.isEmpty {
                    Section("Amendments") {
                        ForEach(history) { a in
                            VStack(alignment: .leading, spacing: 3) {
                                HStack {
                                    Text("Version \(a.get("version")?.int ?? 0)").bold()
                                    if a.get("loosened")?.int == 1 { Text("loosened · \(a.s("step_up_method"))").font(.caption2).foregroundStyle(Theme.warn) }
                                    Spacer()
                                    Text(String(a.s("created_at").prefix(10))).font(.caption2).foregroundStyle(.secondary)
                                }
                                Text(Self.describe(a.get("changes"))).font(.caption)
                                if !a.s("note").isEmpty { Text(a.s("note")).font(.caption).foregroundStyle(.secondary) }
                            }
                        }
                    }
                }
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Your charter")
        .task { await load() }
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        guard let d = try? await api.json("/api/charter") else { message = "Couldn't load the charter."; return }
        data = d
        let r = d.get("rules")
        if let v = r?.get("agent_daily_usd")?.double { dailyOn = true; daily = v } else { dailyOn = false }
        if let v = r?.get("mission_budget_cap_usd")?.double { capOn = true; cap = v } else { capOn = false }
        if let q = r?.get("quiet_hours") {
            quietOn = true
            quietStart = Self.clock(q.s("start"))
            quietEnd = Self.clock(q.s("end"))
        } else { quietOn = false }
    }

    private func save() async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        var body: [String: JSONValue] = ["note": .string(note)]
        if dailyOn { body["agent_daily_usd"] = .number(daily) }
        if capOn { body["mission_budget_cap_usd"] = .number(cap) }
        if quietOn {
            body["quiet_hours"] = .object(["start": .string(Self.hhmm(quietStart)), "end": .string(Self.hhmm(quietEnd)),
                                           "tz": .string(TimeZone.current.identifier)])
        }
        var stepUp: String?
        if needsCode {
            guard await ReleaseReviewView.authenticate(reason: "Loosen your charter") else { message = "Face ID didn't confirm it's you."; return }
            do { stepUp = try await api.stepUp(code: code, purpose: "charter") } catch { message = error.localizedDescription; return }
        }
        do {
            data = try await api.json("/api/charter", method: "PUT", body: body, stepUp: stepUp)
            message = "Saved. The charter is now version \(data?.get("version")?.int ?? 0)."
            needsCode = false
            code = ""
            note = ""
            await load()
        } catch let e as APIError where e.status == 401 {
            needsCode = true
            message = e.detail.contains("set up") ? "Set up an authenticator in the web app (Owner → Security) first."
                : "That loosens a rule. Enter your authenticator code, then tap Amend again."
        } catch {
            message = error.localizedDescription
        }
    }

    static func describe(_ changes: JSONValue?) -> String {
        guard case .object(let o)? = changes else { return "" }
        let names = ["agent_daily_usd": "Daily cap per agent", "mission_budget_cap_usd": "Mission budget cap", "quiet_hours": "Quiet hours"]
        return o.keys.sorted().map { k in
            let v = o[k]
            func show(_ x: JSONValue?) -> String {
                switch x {
                case .number(let n)?: return String(format: "$%.2f", n)
                case .object(let q)?: return "\(q["start"]?.str ?? "")–\(q["end"]?.str ?? "")"
                default: return "off"
                }
            }
            return "\(names[k] ?? k): \(show(v?.get("from"))) → \(show(v?.get("to")))"
        }.joined(separator: "\n")
    }

    static func clock(_ hhmm: String) -> Date {
        let p = hhmm.split(separator: ":").compactMap { Int($0) }
        return Calendar.current.date(bySettingHour: p.first ?? 22, minute: p.count > 1 ? p[1] : 0, second: 0, of: Date()) ?? Date()
    }

    static func hhmm(_ d: Date) -> String {
        let c = Calendar.current.dateComponents([.hour, .minute], from: d)
        return String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0)
    }
}
