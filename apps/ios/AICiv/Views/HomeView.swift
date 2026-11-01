import SwiftUI

/// Home is the city, full screen, the way the website opens: the 3D civilization behind a compact top bar (AI Civ,
/// connection, Cash / Agents / Tasks), camera modes, the approval call, a district card when you pick a building,
/// and the command sheet at the bottom (Overview, Tasks, Agents, Activity, Owner). With no server it plays the
/// website's labelled demo mission.
struct HomeView: View {
    @Environment(AppState.self) private var app
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityVoiceOverEnabled) private var voiceOver
    private var city: CityScene { app.city }
    @State private var pins = CityPins()
    @State private var overview: JSONValue?
    @State private var error: String?
    @State private var camera: CameraMode = .overview
    @State private var selectedAgent: String?
    @State private var focused: String?
    @State private var selectedPackage: String?
    @State private var detail: HomeDetail?
    @State private var factories: JSONValue?
    @State private var knowledge: KBCounts?
    @State private var sheet = SheetDetent(rawValue: UserDefaults.standard.string(forKey: "homeSheet") ?? "") ?? .peek
    @State private var tab = CommandTab(rawValue: UserDefaults.standard.string(forKey: "homeTab") ?? "") ?? .overview
    @State private var listMode = UserDefaults.standard.bool(forKey: "cityList")

    struct KBCounts: Equatable { let skills: Int; let docs: Int }

    private var districts: [District] { app.districts.isEmpty ? Roster.districts : app.districts }

    var body: some View {
        GeometryReader { geo in
            let peek = SheetDetent.peekHeight
            let fullHeight = geo.size.height + geo.safeAreaInsets.top
            ZStack(alignment: .top) {
                // The city is taller than the screen and shifted up by the sheet's peek (the website's ViewFit), so it
                // centres in the part the sheet doesn't cover. It hangs in an overlay so it never sizes the layout.
                Color.clear
                    .frame(width: geo.size.width, height: geo.size.height)
                    .overlay(alignment: .top) {
                        cityLayer(width: geo.size.width, height: fullHeight + peek)
                            .offset(y: -peek - geo.safeAreaInsets.top)
                    }
                VStack(alignment: .leading, spacing: 8) {
                    HUDBar(overview: overview)
                    HStack(alignment: .top) {
                        cards
                        Spacer(minLength: 8)
                        cameraChips
                    }
                    approvalCall
                }
                .padding(.horizontal, 10)
                .padding(.top, 4)
                VStack(spacing: 0) {
                    Spacer()
                    CommandSheet(detent: $sheet, tab: $tab, maxHeight: geo.size.height - 64,
                                 accessory: AnyView(pills.padding(.horizontal, 10))) { t in sheetContent(t) }
                }
            }
        }
        .background(Color(hex: 0x121A44).ignoresSafeArea())
        .onAppear {
            city.app = app
            city.reduceMotion = reduceMotion
            city.onMode = { m in if camera != m { camera = m } }
            city.sync(districts: districts)
        }
        .onChange(of: app.districts) { city.sync(districts: districts) }
        .onChange(of: reduceMotion) { city.reduceMotion = reduceMotion }
        .onChange(of: camera) { _, m in
            if m == .follow, let id = selectedAgent { city.follow(id) } else if city.mode != m { city.mode = m }
        }
        .task(id: app.ledger.lastSequence / 5) { await load() }
        .task(id: app.connection == .live) { await poll() }
        .task(id: app.connection == .live) {
            // no server after a few seconds: play the website's demo mission on the bundled cast
            guard app.connection != .live else { return }
            try? await Task.sleep(for: .seconds(3))
            app.startDemoIfOffline()
        }
        .onChange(of: knowledge) { _, k in city.setKnowledge(skills: k?.skills ?? 0, docs: k?.docs ?? 0) }
        .sheet(item: $detail) { d in
            switch d {
            case .district(let x): DistrictActivitySheet(district: x).presentationDetents([.medium, .large])
            case .agent(let id): AgentStatusSheet(agentId: id).presentationDetents([.medium, .large])
            case .mission(let m): NavigationStack { MissionDetailView(mission: m) }.presentationDetents([.medium, .large])
            case .clinic: NavigationStack { FailureClinicView() }
            }
        }
    }

    // MARK: the city

    @ViewBuilder private func cityLayer(width: CGFloat, height: CGFloat) -> some View {
        let hidden = voiceOver || listMode
        ZStack(alignment: .topLeading) {
            CitySceneView(city: city, pins: pins, paused: hidden) { handle($0) }
                .accessibilityHidden(true)
            if !hidden {
                CityOverlay(city: city, pins: pins, districts: districts, selectedAgent: selectedAgent, selectedPackage: selectedPackage,
                            factories: factories, knowledge: knowledge.map { (skills: $0.skills, docs: $0.docs) }) { handle($0) }
            }
            if hidden {
                // the same city as a list, for VoiceOver and for anyone who prefers it
                AccessibleCityList(districts: districts) { s in
                    switch s {
                    case .district(let d): detail = .district(d)
                    case .agent(let id): detail = .agent(id)
                    }
                }
                .padding(.top, SheetDetent.peekHeight + 150).padding(.bottom, SheetDetent.peekHeight * 2 + 20)
            }
        }
        .frame(width: width, height: height)
    }

    private func handle(_ t: CityTap) {
        switch t {
        case .agent(let id):
            if selectedAgent == id { detail = .agent(id); return }
            selectedAgent = id
            focused = nil
            Haptics.light()
        case .district(let id):
            focused = id
            selectedAgent = nil
            city.focus(id)
            Haptics.light()
        case .package(let id):
            selectedPackage = id
            Task {
                try? await Task.sleep(for: .seconds(6))
                if selectedPackage == id { selectedPackage = nil }
            }
        case .nothing:
            selectedPackage = nil
        }
    }

    // MARK: the controls over the city

    private var cameraChips: some View {
        VStack(alignment: .trailing, spacing: 6) {
            HStack(spacing: 2) {
                ForEach(CameraMode.allCases) { m in
                    let disabled = m == .follow && selectedAgent == nil
                    Button {
                        if m == .overview { city.showOverview(); focused = nil }
                        camera = m
                    } label: {
                        Text(m.label).font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(camera == m ? Color(hex: 0x080C1C) : Theme.ink.opacity(0.8))
                            .padding(.horizontal, 10).padding(.vertical, 6)
                            .background(camera == m ? Theme.cyan : .clear, in: RoundedRectangle(cornerRadius: 10))
                    }
                    .buttonStyle(PressableStyle())
                    .disabled(disabled).opacity(disabled ? 0.3 : 1)
                    .accessibilityAddTraits(camera == m ? .isSelected : [])
                }
            }
            .padding(3)
            .background(Color(hex: 0x0A1022).opacity(0.82), in: RoundedRectangle(cornerRadius: 13))
            .opacity(voiceOver || listMode ? 0 : 1)
            Button {
                listMode.toggle()
                UserDefaults.standard.set(listMode, forKey: "cityList")
            } label: { Image(systemName: listMode ? "cube" : "list.bullet") }
                .buttonStyle(CityChip())
                .accessibilityLabel(listMode ? "Show the 3D city" : "Show the city as a list")
                .opacity(voiceOver ? 0 : 1)
        }
    }

    /// The district card (Shell.tsx DistrictCard), or the card for the agent you picked.
    @ViewBuilder private var cards: some View {
        if let id = focused, let d = districts.first(where: { $0.id == id }) {
            DistrictCard(district: d, onClose: { focused = nil; city.showOverview() }, onDetails: { detail = .district(d) },
                         onAgent: { a in selectedAgent = a; focused = nil })
                .transition(.fromEdge(.leading, reduce: reduceMotion))
        } else if let id = selectedAgent, let a = app.agents[id] ?? Roster.bundled.first(where: { $0.id == id }) {
            AgentCard(agent: a, following: camera == .follow,
                      onFollow: { camera = camera == .follow ? .orbit : .follow },
                      onDetails: { detail = .agent(id) },
                      onClose: { selectedAgent = nil; if camera == .follow { camera = .orbit } })
                .transition(.fromEdge(.leading, reduce: reduceMotion))
        }
    }

    /// The amber call to the owner (the website's ApprovalCall): the demo's approval with its two buttons, or what's
    /// waiting for you. Real approvals open the Owner tab, where each one is confirmed on its own.
    @ViewBuilder private var approvalCall: some View {
        if let ask = app.world.demoApproval {
            VStack(alignment: .leading, spacing: 6) {
                Text("DEMO · NEEDS YOUR APPROVAL").font(Pixel.sign(10)).foregroundStyle(Color(hex: 0x2A1A00))
                Text(ask).font(.system(size: 13, weight: .semibold)).foregroundStyle(Color(hex: 0x1A1000))
                HStack(spacing: 8) {
                    Button("Approve") { Haptics.success(); app.decideDemo(granted: true) }
                        .buttonStyle(AmberButton(filled: true))
                    Button("Reject") { app.decideDemo(granted: false) }
                        .buttonStyle(AmberButton(filled: false))
                }
            }
            .padding(10)
            .frame(maxWidth: 340, alignment: .leading)
            .background(Color(hex: 0xFFBD69), in: RoundedRectangle(cornerRadius: 12))
            .shadow(color: Color(hex: 0xFFBD69).opacity(0.5), radius: 10)
            .transition(.fromEdge(.top, reduce: reduceMotion))
        } else if app.connection == .live, app.approvals.count + app.ownerWaiting > 0 {
            let n = app.approvals.count + app.ownerWaiting
            Button {
                tab = .owner
                if sheet == .peek { sheet = .half }
            } label: {
                HStack(spacing: 6) {
                    Circle().fill(Color(hex: 0x2A1A00)).frame(width: 7, height: 7)
                    Text("\(Plural.of(n, "thing")) waiting for your approval").font(.system(size: 13, weight: .semibold))
                    Image(systemName: "chevron.right").font(.system(size: 11, weight: .bold))
                }
                .foregroundStyle(Color(hex: 0x1A1000))
                .padding(.horizontal, 12).padding(.vertical, 7)
                .background(Color(hex: 0xFFBD69), in: Capsule())
                .shadow(color: Color(hex: 0xFFBD69).opacity(0.5), radius: 8)
            }
            .buttonStyle(PressableStyle())
            .accessibilityHint("Opens the Owner tab")
        }
    }

    /// "Play the town" and "Failure clinic" (the website's two pills above the sheet).
    private var pills: some View {
        HStack(spacing: 8) {
            Button { app.openTab = "city" } label: { Label("Play the town", systemImage: "gamecontroller.fill") }
                .buttonStyle(TownPill())
                .accessibilityHint("Opens the City tab, where you walk around and talk to agents")
            if app.connection == .live {
                Button { detail = .clinic } label: { Label("Failure clinic", systemImage: "cross.case.fill") }
                    .buttonStyle(TownPill())
            }
            Spacer()
        }
        .opacity(sheet == .full ? 0 : 1)
    }

    // MARK: the command sheet

    @ViewBuilder private func sheetContent(_ t: CommandTab) -> some View {
        switch t {
        case .overview: HomeOverviewTab(overview: overview, error: error)
        case .tasks:
            VStack(alignment: .leading, spacing: 18) {
                MyTasksTab()
                TasksTab { detail = .mission($0) }
            }
        case .agents: AgentsTab(selected: selectedAgent) { id in
                selectedAgent = id
                focused = nil
                camera = .follow
                city.follow(id)
                if sheet != .peek { sheet = .peek }
            } details: { detail = .agent($0) }
        case .activity: ActivityTab()
        case .owner: OwnerTab()
        }
    }

    // MARK: data

    private func load() async {
        guard let api = app.api, app.connection == .live else { return }
        do { overview = try await api.overview(); error = nil } catch let e as APIError where e.status == 401 {
            overview = nil
        } catch { self.error = error.localizedDescription }
    }

    /// The factory boards and the Knowledge Base counts, refreshed while connected.
    private func poll() async {
        guard app.connection == .live else { factories = nil; knowledge = nil; return }
        while !Task.isCancelled {
            if let api = app.api {
                factories = try? await api.factories()
                if let k = try? await api.knowledge() {
                    let c = k.get("counts")
                    knowledge = KBCounts(skills: c?.get("skill")?.int ?? 0, docs: c?.get("doc")?.int ?? 0)
                }
            }
            try? await Task.sleep(for: .seconds(30))
        }
    }
}

enum HomeDetail: Identifiable {
    case district(District), agent(String), mission(MissionRow), clinic
    var id: String {
        switch self {
        case .district(let d): return "d:" + d.id
        case .agent(let a): return "a:" + a
        case .mission(let m): return "m:" + m.id
        case .clinic: return "clinic"
        }
    }
}

// MARK: - the top bar

/// The website's StatsBar: "AI Civ", the connection, and Cash / Agents / Tasks.
struct HUDBar: View {
    @Environment(AppState.self) private var app
    let overview: JSONValue?

    var body: some View {
        let st = status
        let f = overview?.get("finance")
        HStack(spacing: 8) {
            Text("AI Civ").font(Pixel.sign(13)).foregroundStyle(Theme.cyan)
            HStack(spacing: 5) {
                Circle().fill(st.color).frame(width: 7, height: 7)
                    .modifier(Breathe(on: app.connection == .connecting || app.connection == .idle))
                Text(st.text).font(.system(size: 11)).foregroundStyle(Theme.ink.opacity(0.75)).lineLimit(1)
                if app.connection == .live && app.executionMode == "simulation" {
                    Text("Sim").font(.system(size: 10, weight: .semibold)).foregroundStyle(Theme.warn)
                        .padding(.horizontal, 5).background(Theme.warn.opacity(0.15), in: RoundedRectangle(cornerRadius: 3))
                }
            }
            .fixedSize()
            .accessibilityElement(children: .combine)
            HStack(spacing: 0) {
                stat("Cash", cash(f),
                     sub: f?.get("simulated")?.isTrue == true ? "simulated" : nil, color: Color(hex: 0x3DFFB8))
                divider
                stat("Agents", overview.map { "\($0.get("agents")?.get("working")?.int ?? 0)/\($0.get("agents")?.get("total")?.int ?? 0)" }
                         ?? "\(app.agents.isEmpty ? Roster.bundled.count : app.agents.count)", sub: "working")
                divider
                stat("Tasks", overview.map { "\($0.get("tasks")?.get("running")?.int ?? 0)" } ?? "—",
                     sub: overview.map { "\($0.get("tasks")?.get("completed_today")?.int ?? 0) done today" })
            }
            .frame(maxWidth: .infinity)
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .background(Pixel.panel.opacity(0.88), in: RoundedRectangle(cornerRadius: 4))
        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Pixel.rim, lineWidth: 2))
    }

    private func cash(_ f: JSONValue?) -> String {
        guard let f else { return "owner only" }
        guard let v = f.get("cash_minor"), CityOverlay.present(v) else { return "—" }
        return Money.minor(v.int)
    }

    private var divider: some View { Rectangle().fill(.white.opacity(0.1)).frame(width: 1, height: 26) }

    private func stat(_ label: String, _ value: String, sub: String?, color: Color = Theme.ink) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label.uppercased()).font(.system(size: 8, weight: .semibold)).foregroundStyle(.secondary)
            Text(value).font(Pixel.sign(13)).foregroundStyle(color).lineLimit(1).minimumScaleFactor(0.6).monospacedDigit()
            if let sub { Text(sub).font(.system(size: 8)).foregroundStyle(.secondary).lineLimit(1) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.leading, 6)
        .accessibilityElement(children: .combine)
    }

    private var status: (text: String, color: Color) {
        if app.connection != .live && app.world.demo { return ("Demo, no server", Color(hex: 0xFFBD69)) }
        switch app.connection {
        case .live: return ("Live", Color(hex: 0x5BF2A5))
        case .connecting, .idle: return ("Connecting", Color(hex: 0x8FA8FF))
        case .reconnecting: return ("Reconnecting", Color(hex: 0xFFBD69))
        case .failed(let why):
            if why.contains("Sign in") { return ("Sign in to connect", Color(hex: 0xFFD36B)) }
            return ("Demo, no server", Color(hex: 0xFFBD69))
        }
    }
}

struct Breathe: ViewModifier {
    let on: Bool
    @State private var dim = false
    @Environment(\.accessibilityReduceMotion) private var reduce
    func body(content: Content) -> some View {
        content.opacity(on && dim ? 0.35 : 1)
            .onAppear { if on && !reduce { withAnimation(.easeInOut(duration: 1.1).repeatForever()) { dim = true } } }
    }
}

// MARK: - cards and pills

struct DistrictCard: View {
    @Environment(AppState.self) private var app
    let district: District
    let onClose: () -> Void
    let onDetails: () -> Void
    let onAgent: (String) -> Void

    var body: some View {
        let c = Color(hexString: district.color)
        let all = app.agents.isEmpty ? Roster.bundled : Array(app.agents.values)
        let here = all.filter { (app.world.places[$0.id]?.district ?? (app.agents.isEmpty ? $0.homeDistrict : ($0.district ?? $0.homeDistrict))) == district.id }
            .sorted { $0.name < $1.name }
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(district.name).font(Pixel.sign(14)).foregroundStyle(c)
                    if let p = district.purpose { Text(p).font(.caption).foregroundStyle(.secondary).lineLimit(3) }
                }
                Spacer()
                Button("Close", action: onClose).font(.caption).foregroundStyle(.secondary)
            }
            ForEach(district.workstations ?? [], id: \.id) { w in
                let tool = app.world.active[w.id]
                HStack(spacing: 6) {
                    Circle().fill(tool != nil ? c : Color(hex: 0x2A3A5E)).frame(width: 7, height: 7)
                    Text(w.label).font(.caption)
                    Spacer()
                    Text(tool.map { $0.replacingOccurrences(of: "_", with: " ") } ?? "idle").font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            FlowChips(items: here.map { a in (id: a.id, text: chip(a), color: Color(hexString: a.avatar.color)) },
                      empty: "No agents here right now.", onTap: onAgent)
            Button(action: onDetails) { Text("What's happening here").frame(maxWidth: .infinity) }
                .buttonStyle(CityChip())
        }
        .padding(10)
        .frame(width: 250)
        .background(Pixel.panel.opacity(0.94), in: RoundedRectangle(cornerRadius: 4))
        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(c.opacity(0.6), lineWidth: 2))
    }
}

extension DistrictCard {
    fileprivate func chip(_ a: Agent) -> String {
        let state = app.world.states[a.id] ?? (app.agents.isEmpty ? "IDLE" : a.executionState)
        return "\(a.name), \(Format.human(state).lowercased())"
    }
}

struct AgentCard: View {
    @Environment(AppState.self) private var app
    let agent: Agent
    let following: Bool
    let onFollow: () -> Void
    let onDetails: () -> Void
    let onClose: () -> Void

    var body: some View {
        let c = Color(hexString: agent.avatar.color)
        let state = app.world.states[agent.id] ?? (app.agents.isEmpty ? "IDLE" : agent.executionState)
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                AgentPortrait(agent: agent, size: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(agent.name).font(Pixel.sign(13)).foregroundStyle(c)
                    Text(agent.role).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                Button("Close", action: onClose).font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 6) {
                Circle().fill(Color(hexString: WorldMap.stateColor[state] ?? "#8FA8FF")).frame(width: 7, height: 7)
                Text(Format.human(state)).font(.caption)
            }
            HStack(spacing: 6) {
                Button(following ? "Stop following" : "Follow", action: onFollow).buttonStyle(CityChip())
                Button("Details", action: onDetails).buttonStyle(CityChip())
            }
        }
        .padding(10)
        .frame(width: 230)
        .background(Pixel.panel.opacity(0.94), in: RoundedRectangle(cornerRadius: 4))
        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(c.opacity(0.6), lineWidth: 2))
    }
}

/// Wrapping chips (agents in a district).
struct FlowChips: View {
    let items: [(id: String, text: String, color: Color)]
    let empty: String
    let onTap: (String) -> Void
    var body: some View {
        if items.isEmpty {
            Text(empty).font(.caption2).foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(items, id: \.id) { i in
                    Button { onTap(i.id) } label: {
                        Text(i.text).font(.caption2).foregroundStyle(i.color).lineLimit(1)
                            .padding(.horizontal, 8).padding(.vertical, 3)
                            .background(i.color.opacity(0.12), in: Capsule())
                    }
                    .buttonStyle(PressableStyle())
                }
            }
        }
    }
}

/// The website's town pills: cream 2 px border on deep violet.
struct TownPill: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(Pixel.sign(12)).foregroundStyle(Color(hex: 0xF3E9D2))
            .padding(.horizontal, 12).padding(.vertical, 7)
            .background(Color(hex: 0x191430), in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color(hex: 0xF3E9D2), lineWidth: 2))
            .pressFeedback(configuration.isPressed)
    }
}

struct AmberButton: ButtonStyle {
    let filled: Bool
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.system(size: 13, weight: .bold))
            .foregroundStyle(filled ? Color(hex: 0xFFBD69) : Color(hex: 0x1A1000))
            .padding(.horizontal, 14).padding(.vertical, 6)
            .background(filled ? Color(hex: 0x1A1000) : .clear, in: Capsule())
            .overlay(Capsule().strokeBorder(Color(hex: 0x1A1000), lineWidth: 1.5))
            .pressFeedback(configuration.isPressed)
    }
}
