import SwiftUI

/// A pixel portrait cut from the character sprite, so faces match the game.
struct SpriteFace: View {
    let outfit: Outfit
    var size: CGFloat = 46
    var body: some View {
        Group {
            if let img = PixelSprites.image(outfit, .down, .stand, 0) {
                Image(decorative: img, scale: 1).interpolation(.none).resizable().aspectRatio(contentMode: .fit)
            } else { Color.clear }
        }
        .frame(width: size, height: size * 1.5)
        .frame(width: size, height: size, alignment: .top)
        .clipped()
        .background(Color(hex: 0x141B33), in: RoundedRectangle(cornerRadius: 8))
    }
}

/// RPG dialogue with an agent. Everything they say comes from the backend (POST /api/play/talk), which answers from
/// real records. A request comes back as an offer with Confirm / Not now; walking away leaves it unconfirmed.
struct DialogueView: View {
    @Environment(AppState.self) private var app
    let game: GameModel
    let agent: TownAgent
    @State private var messages: [JSONValue] = []
    @State private var proposals: [String: JSONValue] = [:]
    @State private var suggestions: [String] = []
    @State private var text = ""
    @State private var busy = false
    @State private var error: String?
    @State private var fresh: String?

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                SpriteFace(outfit: agent.look.map(PixelSprites.outfit) ?? PixelSprites.outfit(PlayerLook()))
                VStack(alignment: .leading, spacing: 2) {
                    Text(agent.name).font(Pixel.title(17)).foregroundStyle(GameStyle.cream)
                    Text("\(agent.role) · \(TownRules.statusLabel(agent))").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                Button("Walk away") { game.talk(nil) }.font(Pixel.title(12)).padding(.horizontal, 10).padding(.vertical, 6)
                    .background(GameStyle.button, in: RoundedRectangle(cornerRadius: 6)).foregroundStyle(GameStyle.cream)
            }
            .padding(12)
            Divider().overlay(GameStyle.cream.opacity(0.25))
            if app.connection != .live {
                Text(app.agents.isEmpty
                     ? "This is the offline town: \(agent.name) is shown as set up, not doing live work. Connect to your Mac and sign in to talk to your team."
                     : "Reconnecting to your Mac… you can talk again once the town is live.")
                    .font(.callout).foregroundStyle(GameStyle.cream).padding(14).frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 10) {
                            ForEach(messages) { m in bubble(m).id(m.s("id")) }
                            if busy { Text("…").font(Pixel.title(16)).foregroundStyle(GameStyle.cream.opacity(0.6)).id("busy") }
                            if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
                        }
                        .padding(12)
                    }
                    .frame(maxHeight: 280)
                    .onChange(of: messages.count) { if let id = messages.last?.s("id") { withAnimation { proxy.scrollTo(id, anchor: .bottom) } } }
                }
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 6) {
                        ForEach(chips, id: \.self) { s in
                            Button(s) { Task { await send(s) } }.font(.caption).padding(.horizontal, 10).padding(.vertical, 6)
                                .overlay(Capsule().strokeBorder(GameStyle.cream.opacity(0.35))).foregroundStyle(GameStyle.cream)
                        }
                    }
                    .padding(.horizontal, 12)
                }
                HStack(spacing: 8) {
                    TextField("Ask, or give a request…", text: $text)
                        .textFieldStyle(.plain).padding(10).background(Color(hex: 0x0F0C1F), in: RoundedRectangle(cornerRadius: 6))
                        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(GameStyle.cream.opacity(0.3)))
                        .submitLabel(.send).onSubmit { Task { await send(text) } }
                    Button("Say") { Task { await send(text) } }.font(Pixel.title(13)).padding(.horizontal, 14).padding(.vertical, 10)
                        .background(GameStyle.go, in: RoundedRectangle(cornerRadius: 6)).foregroundStyle(GameStyle.ink)
                        .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty || busy)
                }
                .padding(12)
            }
        }
        .gamePanel()
        .padding(.horizontal, 8)
        .padding(.bottom, 8)
        .task(id: agent.id) { await load() }
    }

    private var chips: [String] {
        suggestions.isEmpty ? ["What are you working on?", "What needs my approval?", "Show everything in progress"] : suggestions
    }

    @ViewBuilder private func bubble(_ m: JSONValue) -> some View {
        let mine = m.s("speaker") == "owner"
        VStack(alignment: .leading, spacing: 6) {
            Text(m.s("text")).font(.callout).foregroundStyle(mine ? Theme.ink : GameStyle.cream)
            if let pid = m.get("proposal_id")?.string, let p = proposals[pid] { offer(p) }
        }
        .padding(mine ? 10 : 0)
        .background(mine ? GameStyle.button : .clear, in: RoundedRectangle(cornerRadius: 8))
        .frame(maxWidth: .infinity, alignment: mine ? .trailing : .leading)
    }

    @ViewBuilder private func offer(_ p: JSONValue) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("REQUEST").font(Pixel.title(10)).foregroundStyle(Theme.gold)
            Text(p.s("summary")).font(.callout).foregroundStyle(Theme.ink)
            if p.s("status") == "PENDING" {
                HStack(spacing: 8) {
                    Button("Confirm") { Task { await decide(p.s("id"), yes: true) } }.font(Pixel.title(12)).padding(.horizontal, 12).padding(.vertical, 6)
                        .background(GameStyle.go, in: RoundedRectangle(cornerRadius: 6)).foregroundStyle(GameStyle.ink)
                    Button("Not now") { Task { await decide(p.s("id"), yes: false) } }.font(Pixel.title(12)).padding(.horizontal, 12).padding(.vertical, 6)
                        .background(GameStyle.button, in: RoundedRectangle(cornerRadius: 6)).foregroundStyle(GameStyle.cream)
                }
                .disabled(busy)
                Text("Nothing starts until you confirm.").font(.caption2).foregroundStyle(.secondary)
            } else {
                Text(["CONFIRMED": "Confirmed", "DECLINED": "Declined", "EXPIRED": "Expired (ask again to redo)", "FAILED": "Couldn't start"][p.s("status")] ?? p.s("status"))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .background(Theme.gold.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Theme.gold.opacity(0.7), lineWidth: 2))
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        do {
            let c = try await api.conversation(agent.id)
            apply(c)
            if messages.isEmpty { await send("", force: true) }
        } catch { self.error = describe(error) }
    }

    private func apply(_ c: JSONValue) {
        messages = c.get("messages")?.list ?? []
        if case .object(let o)? = c.get("proposals") { proposals = o } else { proposals = [:] }
    }

    private func send(_ raw: String, force: Bool = false) async {
        let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (force || !t.isEmpty), !busy, let api = app.api else { return }
        busy = true
        error = nil
        text = ""
        defer { busy = false }
        do {
            let r = try await api.talk(agent.id, t)
            suggestions = (r.get("suggestions")?.list ?? []).compactMap(\.string)
            apply(try await api.conversation(agent.id))
        } catch { self.error = describe(error) }
    }

    private func decide(_ id: String, yes: Bool) async {
        guard let api = app.api else { return }
        busy = true
        defer { busy = false }
        do {
            if yes { _ = try await api.confirmProposal(id) } else { try await api.declineProposal(id) }
            if yes { Haptics.success() }
            apply(try await api.conversation(agent.id))
            await app.refresh()
        } catch { Haptics.warning(); self.error = describe(error) }
    }

    private func describe(_ e: Error) -> String {
        if let a = e as? APIError {
            if a.status == 403 { return "Your account can't do that. The owner, an admin or an operator can." }
            if a.status == 401 { return "Sign in to talk to your agents." }
            return a.detail
        }
        return "Couldn't reach your Mac."
    }
}

/// Missions and research findings, from the server's records.
struct JournalView: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    @State var startOnFindings: Bool
    @State private var tab = 0

    var body: some View {
        NavigationStack {
            List {
                Picker("Show", selection: $tab) {
                    Text("Missions").tag(0)
                    Text("Findings").tag(1)
                }
                .pickerStyle(.segmented)
                .listRowBackground(Color.clear)
                if app.connection != .live && app.missions.isEmpty {
                    Text("Connect to your Mac and sign in to see your missions.").foregroundStyle(.secondary)
                } else if tab == 0 {
                    if app.missions.isEmpty { Text("No missions yet. Talk to Lumen at the Research Observatory or Kade at the Code Forge.").foregroundStyle(.secondary) }
                    ForEach(app.missions) { m in
                        NavigationLink { MissionDetailView(mission: m) } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(m.title).font(.headline).lineLimit(2)
                                HStack {
                                    StatusPill(text: m.status.lowercased().replacingOccurrences(of: "_", with: " "), color: Theme.status(m.status))
                                    if m.executionMode == "simulation" { StatusPill(text: "Simulation", color: Theme.violet) }
                                }
                            }
                        }
                    }
                } else {
                    if app.opportunities.isEmpty { Text("No research findings yet.").foregroundStyle(.secondary) }
                    ForEach(app.opportunities) { o in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(o.title).font(.headline)
                            Text("Score \(String(format: "%.2f", o.opportunityScore)) · \(o.confidence) confidence · \(o.status.lowercased().replacingOccurrences(of: "_", with: " "))\(o.dataMode == "live" ? "" : " · fixture data")")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            .navigationTitle("Mission journal")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .refreshable { await app.refresh() }
            .onAppear { tab = startOnFindings ? 1 : 0 }
        }
    }
}

struct MissionDetailView: View {
    @Environment(AppState.self) private var app
    let mission: MissionRow
    @State private var detail: JSONValue?

    var body: some View {
        List {
            Section {
                Text(mission.title).font(.headline)
                Text(mission.executionMode == "simulation" ? "Simulation: no AI model connected, so this run is a rehearsal." : "Live run")
                    .font(.caption).foregroundStyle(.secondary)
                if let f = mission.failureReason { Text(f).font(.caption).foregroundStyle(Theme.bad) }
                if let o = detail?.get("objective") { ObjectiveRow(objective: o) }
                if let d = detail, !["COMPLETED", "FAILED", "CANCELLED"].contains(d.get("mission")?.s("status") ?? "") {
                    PriorityPicker(missionId: mission.id, priority: d.s("priority").isEmpty ? "normal" : d.s("priority"))
                        .id(d.s("priority"))  // a reloaded mission resets the picker to what's stored
                }
            }
            let plans = detail?.get("recovery")?.list ?? []
            if !plans.isEmpty {
                Section("Recovery plan") {
                    ForEach(plans) { p in RecoveryPlanRow(plan: p) { detail = try? await app.api?.missionDetail(mission.id) } }
                }
            }
            MissionLinksSection(missionId: mission.id, detail: detail) { detail = try? await app.api?.missionDetail(mission.id) }
            Section {
                NavigationLink { MissionTraceView(missionId: mission.id) } label: {
                    Label("Full trace: every step, tool and AI call", systemImage: "list.bullet.rectangle")
                }
            }
            Section("Steps") {
                ForEach(detail?.get("tasks")?.list ?? []) { t in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(t.s("title"))
                            Text(app.agents[t.s("agent_id")]?.name ?? "").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        StatusPill(text: t.s("status").lowercased(), color: Theme.status(t.s("status")))
                    }
                }
            }
            let arts = detail?.get("artifacts")?.list ?? []
            if !arts.isEmpty {
                Section("What it produced") {
                    ForEach(arts) { a in Label("\(a.s("title")) (\(a.s("kind")))", systemImage: "doc.text") }
                }
            }
        }
        .navigationTitle("Mission")
        .task { detail = try? await app.api?.missionDetail(mission.id) }
    }
}

/// Pick how you look in town. Saved to your account.
struct AvatarEditor: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let game: GameModel
    @State private var draft = PlayerLook()
    @State private var name = ""
    @State private var saving = false

    private let skins = ["#FFDBB4", "#F1C27D", "#E8B48A", "#C68642", "#8D5524", "#5C3A21"]
    private let hairs = ["#1E1B22", "#4A2E1F", "#8E5BE8", "#C9CED8", "#E8862E", "#3CCB7F", "#3F8CFF", "#FF6FAE"]
    private let shirts = ["#B8BCC6", "#24345C", "#C2553A", "#4F8A62", "#7A5CD6", "#F2F2F2", "#F4D58D", "#1E1E26"]
    private let pants = ["#25252E", "#33415C", "#5A6275", "#6B4B2E", "#2D4A3E"]
    private let styles = ["spiky", "short", "buzz", "curly", "long", "bun", "afro", "bald"]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack(spacing: 18) {
                        Spacer()
                        ForEach([Dir.down, .left, .up], id: \.self) { d in
                            if let img = PixelSprites.image(PixelSprites.outfit(draft), d, .stand, 0) {
                                Image(decorative: img, scale: 1).interpolation(.none).resizable().frame(width: 64, height: 96)
                            }
                        }
                        Spacer()
                    }
                    .padding(.vertical, 8)
                    .listRowBackground(Color(hex: 0x5FAE4C))
                }
                Section("Name") { TextField("Name", text: $name) }
                Section("Hair") {
                    Picker("Style", selection: $draft.hairStyle) { ForEach(styles, id: \.self) { Text($0.capitalized).tag($0) } }
                    swatches("Color", hairs, $draft.hair)
                }
                Section("Look") {
                    swatches("Skin", skins, $draft.skin)
                    swatches("Shirt", shirts, $draft.shirt)
                    swatches("Pants", pants, $draft.pants)
                    Toggle("Glasses", isOn: $draft.glasses)
                }
                if app.connection != .live { Text("Connect and sign in to keep your character between visits.").font(.caption).foregroundStyle(.secondary) }
            }
            .navigationTitle("Your character")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button(saving ? "Saving" : "Save") { Task { await save() } }.disabled(saving) }
            }
            .onAppear { draft = game.look; name = game.name }
        }
    }

    private func swatches(_ label: String, _ colors: [String], _ value: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 8) {
                ForEach(colors, id: \.self) { c in
                    Button { value.wrappedValue = c } label: {
                        RoundedRectangle(cornerRadius: 6).fill(Color(hexString: c)).frame(width: 30, height: 30)
                            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(value.wrappedValue.uppercased() == c.uppercased() ? Color.white : Color.black.opacity(0.6), lineWidth: 2))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(label) \(c)")
                }
            }
        }
    }

    private func save() async {
        game.look = draft
        game.name = name.isEmpty ? "Owner" : String(name.prefix(24))
        saving = true
        defer { saving = false }
        if app.connection == .live, let api = app.api {
            let p = game.player
            try? await api.savePlay(name: game.name, look: draft, map: p.map, x: p.x, y: p.y, facing: p.facing)
        }
        dismiss()
    }
}
