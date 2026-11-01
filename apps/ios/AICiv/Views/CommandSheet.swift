import SwiftUI

enum SheetDetent: String {
    case peek, half, full
    static let peekHeight: CGFloat = 150
}

enum CommandTab: String, CaseIterable, Identifiable {
    case overview, tasks, agents, activity, owner
    var id: String { rawValue }
    var label: String {
        switch self {
        case .overview: return "Overview"
        case .tasks: return "Tasks"
        case .agents: return "Agents"
        case .activity: return "Activity"
        case .owner: return "Owner"
        }
    }
}

/// The website's command sheet on a phone: a panel over the bottom of the city that rests at a peek, half or full
/// height. Drag the handle (or tap it) to resize; the tabs switch what it shows. It slides on a transform, as the
/// website's does, rather than changing its height every frame.
struct CommandSheet<Content: View>: View {
    @Binding var detent: SheetDetent
    @Binding var tab: CommandTab
    let maxHeight: CGFloat
    /// Rides on top of the sheet and moves with it (the "Play the town" and "Failure clinic" pills).
    var accessory = AnyView(EmptyView())
    @ViewBuilder let content: (CommandTab) -> Content
    @GestureState private var drag: CGFloat = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(AppState.self) private var app

    private func shown(_ d: SheetDetent) -> CGFloat {
        switch d {
        case .peek: return SheetDetent.peekHeight
        case .half: return min(maxHeight, max(SheetDetent.peekHeight + 120, maxHeight * 0.55))
        case .full: return maxHeight
        }
    }

    var body: some View {
        let hidden = maxHeight - shown(detent)
        VStack(spacing: 0) {
            VStack(spacing: 6) {
                Capsule().fill(.white.opacity(0.22)).frame(width: 44, height: 5).padding(.top, 7)
                    .accessibilityElement()
                    .accessibilityLabel("Resize panel, now \(detent.rawValue)")
                    .accessibilityAddTraits(.isButton)
                    .accessibilityAction { cycle() }
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 2) {
                        ForEach(CommandTab.allCases) { t in
                            Button {
                                tab = t
                                if detent == .peek { set(.half) }
                            } label: {
                                HStack(spacing: 4) {
                                    Text(t.label)
                                    if t == .owner, app.ownerWaiting + app.approvals.count > 0 {
                                        Text("\(app.ownerWaiting + app.approvals.count)").font(.system(size: 10, weight: .bold))
                                            .foregroundStyle(Color(hex: 0x1A1000))
                                            .padding(.horizontal, 5).background(Color(hex: 0xFFBD69), in: Capsule())
                                    }
                                }
                                .font(.system(size: 13, weight: tab == t ? .semibold : .regular))
                                .foregroundStyle(tab == t ? Theme.ink : Theme.ink.opacity(0.6))
                                .padding(.horizontal, 10).padding(.vertical, 7)
                                .background(tab == t ? Color.white.opacity(0.1) : .clear, in: RoundedRectangle(cornerRadius: 10))
                            }
                            .buttonStyle(PressableStyle())
                            .accessibilityAddTraits(tab == t ? .isSelected : [])
                        }
                    }
                    .padding(.horizontal, 8)
                }
            }
            .frame(maxWidth: .infinity)
            .contentShape(Rectangle())
            .onTapGesture { cycle() }
            .gesture(
                DragGesture(minimumDistance: 4)
                    .updating($drag) { v, s, _ in s = v.translation.height }
                    .onEnded { v in settle(hidden: hidden, by: v.predictedEndTranslation.height) }
            )
            Divider().opacity(0.4)
            ScrollView {
                content(tab)
                    .padding(.horizontal, 12).padding(.top, 10)
                    .padding(.bottom, hidden + 24)  // keep the end of the list reachable at every height
            }
            .scrollDisabled(detent == .peek)
        }
        .frame(height: maxHeight, alignment: .top)
        .background(Color(hex: 0x0A1022).opacity(0.96), in: UnevenRoundedRectangle(topLeadingRadius: 14, topTrailingRadius: 14))
        .overlay(UnevenRoundedRectangle(topLeadingRadius: 14, topTrailingRadius: 14).stroke(Pixel.rim, lineWidth: 1))
        .overlay(alignment: .top) { accessory.alignmentGuide(.top) { $0[.bottom] + 8 } }
        .offset(y: max(0, min(maxHeight - SheetDetent.peekHeight, hidden + drag)))
        .animation(reduceMotion ? .easeOut(duration: 0.18) : .spring(duration: 0.35, bounce: 0), value: detent)
    }

    private func set(_ d: SheetDetent) { detent = d }

    private func cycle() { set(detent == .peek ? .half : detent == .half ? .full : .peek) }

    /// Snap to the nearest height after a drag, with the throw speed counted in.
    private func settle(hidden: CGFloat, by dy: CGFloat) {
        let target = maxHeight - (hidden + dy)  // shown height after the throw
        let options: [SheetDetent] = [.peek, .half, .full]
        set(options.min { abs(shown($0) - target) < abs(shown($1) - target) } ?? .peek)
    }
}

// MARK: - Tasks

/// Start a mission and see the recent ones (the website's Missions console).
struct TasksTab: View {
    @Environment(AppState.self) private var app
    let open: (MissionRow) -> Void
    @State private var prompt = "Inspect the sample project, find a failing test, implement a fix, rerun the tests, and prepare a reviewable code change."
    @State private var budget = "1.00"
    @State private var sending = false
    @State private var error: String?
    @FocusState private var editing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if app.connection != .live {
                VStack(alignment: .leading, spacing: 6) {
                    PixelHeader(text: "Demo mission", color: Theme.warn)
                    Text("No server is connected, so the city is playing the website's scripted demo: a mission to fix a failing test. Nothing here is real. Connect to your Mac to send real missions.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .pixelPanel(Theme.warn.opacity(0.5))
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    PixelHeader(text: "New mission")
                    TextField("Tell the city what to do", text: $prompt, axis: .vertical)
                        .lineLimit(3...6).font(.subheadline).focused($editing)
                        .padding(8).background(Color.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 6))
                    HStack {
                        Text("Budget $").font(.caption).foregroundStyle(.secondary)
                        TextField("1.00", text: $budget).keyboardType(.decimalPad).frame(width: 64).font(.subheadline.monospacedDigit())
                            .padding(.horizontal, 6).padding(.vertical, 4).background(Color.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 5))
                            .accessibilityLabel("Mission budget in US dollars")
                        Spacer()
                        Button(sending ? "Sending" : "Send to the city") { Task { await send() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(sending || prompt.trimmingCharacters(in: .whitespacesAndNewlines).count < 8)
                    }
                    Text(app.executionMode == "simulation"
                         ? "No model key on the server: tools and tests run for real, but the fix comes from a labelled fixture."
                         : "Agents run real tools in a sandbox. Publishing always waits for your approval.")
                        .font(.caption2).foregroundStyle(.secondary)
                    if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
                }
                .pixelPanel()
            }
            VStack(alignment: .leading, spacing: 6) {
                PixelHeader(text: "Missions", trailing: app.missions.isEmpty ? nil : "\(app.missions.count) recent")
                if app.missions.isEmpty {
                    Text(app.connection == .live ? "No missions yet. Send one above and watch the agents walk to work." : "Connect to see your missions.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                ForEach(app.missions) { m in
                    Button { open(m) } label: {
                        VStack(alignment: .leading, spacing: 3) {
                            HStack {
                                Text(m.title).font(.subheadline).foregroundStyle(Theme.ink).lineLimit(1)
                                Spacer()
                                StatusPill(text: Format.human(m.status), color: Theme.status(m.status))
                            }
                            Text("\(m.executionMode == "simulation" ? "simulation" : "live") · est. $\(String(format: "%.2f", m.spentUsdEstimated)) of $\(String(format: "%.2f", m.budgetUsd))")
                                .font(.caption2).foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 4)
                    }
                    .buttonStyle(PressableStyle())
                }
            }
        }
    }

    private func send() async {
        guard let api = app.api else { return }
        editing = false
        sending = true
        defer { sending = false }
        var body: [String: JSONValue] = ["prompt": .string(prompt.trimmingCharacters(in: .whitespacesAndNewlines)),
                                         "idempotency_key": .string(UUID().uuidString)]
        if let b = Double(budget.replacingOccurrences(of: ",", with: ".")), b > 0 { body["budget_usd"] = .number(b) }
        do {
            _ = try await api.json("/api/missions", method: "POST", body: body)
            error = nil
            Haptics.success()
            await app.refresh()
        } catch {
            Haptics.warning()
            self.error = (error as? APIError)?.detail ?? "Couldn't reach your Mac."
        }
    }
}

// MARK: - Agents

struct AgentsTab: View {
    @Environment(AppState.self) private var app
    let selected: String?
    let follow: (String) -> Void
    let details: (String) -> Void

    var body: some View {
        let all = (app.agents.isEmpty ? Roster.bundled : Array(app.agents.values)).sorted { $0.name < $1.name }
        VStack(alignment: .leading, spacing: 4) {
            PixelHeader(text: "Agents", trailing: "\(all.count)")
            ForEach(all) { a in
                let state = app.world.states[a.id] ?? (app.agents.isEmpty ? "IDLE" : a.executionState)
                HStack(spacing: 10) {
                    AgentPortrait(agent: a, size: 30)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(a.name).font(.subheadline.bold()).foregroundStyle(Color(hexString: a.avatar.color))
                        Text(a.role).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer()
                    Text(Format.human(state)).font(.caption2).foregroundStyle(Color(hexString: WorldMap.stateColor[state] ?? "#8FA8FF"))
                    Button { follow(a.id) } label: { Image(systemName: "scope") }
                        .buttonStyle(CityChip(fill: selected == a.id ? Theme.cyan.opacity(0.3) : Color(hex: 0x0E1326).opacity(0.9)))
                        .accessibilityLabel("Follow \(a.name) in the city")
                }
                .contentShape(Rectangle())
                .onTapGesture { details(a.id) }
                .accessibilityElement(children: .combine)
                .accessibilityAction(named: "Details") { details(a.id) }
                .padding(.vertical, 3)
            }
        }
    }
}

// MARK: - Activity

struct ActivityTab: View {
    @Environment(AppState.self) private var app
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            PixelHeader(text: "Live agent activity")
            let items = Array(app.ledger.feed.prefix(40))
            if items.isEmpty { Text("Waiting for the agents…").font(.caption).foregroundStyle(.secondary) }
            ForEach(items) { e in
                let line = FeedText.line(e, agents: app.agents.isEmpty ? Dictionary(Roster.bundled.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a }) : app.agents)
                HStack(alignment: .top, spacing: 6) {
                    Text(HomeOverviewTab.time(e.occurredAt)).font(Pixel.mono(9)).foregroundStyle(.secondary).frame(width: 44, alignment: .leading)
                    (Text(line.who).bold() + Text(" ") + Text(line.text).foregroundStyle(.secondary)).font(.caption).lineLimit(3)
                    Spacer(minLength: 0)
                    if e.isSimulation { Text("sim").font(.caption2).foregroundStyle(Theme.warn) }
                }
            }
        }
    }
}

// MARK: - Owner

/// What's waiting for you. Approving happens in the Owner tab, one confirmed decision at a time.
struct OwnerTab: View {
    @Environment(AppState.self) private var app
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if app.world.demoApproval != nil {
                Text("Demo: the agents are waiting on the approval shown at the top of the city.").font(.caption).foregroundStyle(Theme.warn)
            }
            PixelHeader(text: "Waiting for you", color: Theme.gold, trailing: "\(app.approvals.count + app.ownerWaiting)")
            if app.connection != .live {
                Text("Connect to your Mac to see approvals and releases.").font(.caption).foregroundStyle(.secondary)
            } else if app.approvals.isEmpty && app.ownerWaiting == 0 {
                Text("Nothing is waiting for your approval.").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(app.approvals) { a in
                VStack(alignment: .leading, spacing: 2) {
                    Text(a.summary).font(.subheadline).lineLimit(3)
                    Text(Format.human(a.action)).font(.caption2).foregroundStyle(.secondary)
                }
                .padding(.vertical, 2)
            }
            if app.ownerWaiting > 0 {
                Text("\(Plural.of(app.ownerWaiting, "release")) at the Owner's Tower").font(.subheadline)
            }
            Button { app.openTab = "owner" } label: { Label("Open the Owner's Tower", systemImage: "building.columns").frame(maxWidth: .infinity) }
                .buttonStyle(CityChip(fill: Theme.gold.opacity(0.25)))
            Text("Closing a screen, walking away or closing the app never counts as approval.").font(.caption2).foregroundStyle(.secondary)
        }
    }
}
