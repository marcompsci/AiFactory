import SceneKit
import SwiftUI
import UIKit

struct CityFlow: Equatable {
    let from: String
    let to: String
    let weight: Int
}

enum CitySelection: Identifiable {
    case district(District)
    case agent(String)
    var id: String {
        switch self {
        case .district(let d): return "d:" + d.id
        case .agent(let a): return "a:" + a
        }
    }
}

struct CityChip: ButtonStyle {
    var fill = Color(hex: 0x0E1326).opacity(0.9)
    var ink = Theme.ink
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(Pixel.title(12)).foregroundStyle(ink)
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(fill, in: RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Theme.cyan.opacity(0.4)))
            .pressFeedback(configuration.isPressed)
    }
}

extension Roster {
    /// The districts shipped with the app (packages/world-engine/src/districts.json), for the city before you connect.
    static let districts: [District] = {
        struct File: Decodable { let districts: [District] }
        guard let url = Bundle.main.url(forResource: "districts", withExtension: "json"), let data = try? Data(contentsOf: url),
              let f = try? APIClient.decoder.decode(File.self, from: data) else { return [] }
        return f.districts
    }()
}

// MARK: - sheets

/// What's running in a building right now (GET /api/play/districts/{id}).
struct DistrictActivitySheet: View {
    @Environment(AppState.self) private var app
    let district: District
    @State private var data: JSONValue?
    @State private var failed = false

    var body: some View {
        let c = Pixel.districtColor[district.id] ?? Color(hexString: district.color)
        NavigationStack {
            List {
                Section {
                    NeonSign(icon: "◆", text: district.name, color: c)
                    if let p = district.purpose { Text(p).font(.subheadline).foregroundStyle(.secondary) }
                }
                if app.connection != .live {
                    Text("Connect to your Mac and sign in to see what's running here.").foregroundStyle(.secondary)
                } else if let d = data {
                    Section("In progress here") {
                        let tasks = d.get("tasks")?.list ?? []
                        if tasks.isEmpty { Text("Nothing is running in this building right now.").foregroundStyle(.secondary) }
                        ForEach(tasks) { t in
                            VStack(alignment: .leading, spacing: 3) {
                                HStack {
                                    Text(t.s("title")).font(.subheadline.bold())
                                    Spacer()
                                    StatusPill(text: t.s("status").lowercased().replacingOccurrences(of: "_", with: " "), color: Theme.status(t.s("status")))
                                }
                                Text("\(t.s("agent")) · \(t.s("mission"))\(t.s("execution_mode") == "simulation" ? " · simulation" : "")")
                                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                            }
                        }
                    }
                    Section("Here now") {
                        ForEach(d.get("agents")?.list ?? []) { a in
                            HStack {
                                Text(a.s("name")).bold()
                                Text(a.s("role")).foregroundStyle(.secondary).lineLimit(1)
                                Spacer()
                                StatusPill(text: Format.human(a.s("execution_state")), color: Theme.status(a.s("execution_state")))
                            }.font(.subheadline)
                        }
                    }
                    let pk = d.get("packages")?.list ?? []
                    if !pk.isEmpty {
                        Section("On the conveyor") {
                            ForEach(pk) { p in
                                Text("\(TownRules.packageLabel[p.s("package_type")] ?? Format.human(p.s("package_type"))): \(Town.name(of: p.s("origin_district"))) → \(Town.name(of: p.s("destination_district"))) · \(p.s("status").lowercased().replacingOccurrences(of: "_", with: " "))")
                                    .font(.caption)
                            }
                        }
                    }
                    let recent = d.get("recent")?.list ?? []
                    if !recent.isEmpty {
                        Section("Recently finished") {
                            ForEach(recent) { t in Text("\(t.s("title")) · \(t.s("agent")) · \(Format.human(t.s("status")).lowercased())").font(.caption) }
                        }
                    }
                } else if failed {
                    Text("Couldn't load this building's activity.").foregroundStyle(.secondary)
                } else {
                    ProgressView()
                }
            }
            .navigationTitle("Building").navigationBarTitleDisplayMode(.inline)
            .task { await load() }
            .refreshable { await load() }
        }
    }

    private func load() async {
        guard app.connection == .live, let api = app.api else { return }
        do { data = try await api.json("/api/play/districts/\(district.id)") } catch { failed = true }
    }
}

/// What one agent is doing (GET /api/agents/{id}).
struct AgentStatusSheet: View {
    @Environment(AppState.self) private var app
    @Environment(\.dismiss) private var dismiss
    let agentId: String
    @State private var data: JSONValue?
    @State private var net: JSONValue?
    @State private var score: JSONValue?

    var body: some View {
        let a = app.agents[agentId] ?? Roster.bundled.first { $0.id == agentId }
        NavigationStack {
            List {
                if let a {
                    Section {
                        HStack(spacing: 12) {
                            SpriteFace(outfit: a.avatar.look.map { PixelSprites.outfit($0) } ?? PixelSprites.outfit(PlayerLook(shirt: a.avatar.color)), size: 56)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(a.name).font(.title3.bold())
                                Text(a.role).font(.subheadline).foregroundStyle(.secondary)
                                if app.connection == .live {
                                    StatusPill(text: Format.human(a.executionState), color: Theme.status(a.executionState))
                                }
                            }
                        }
                        Text("At the \(Town.name(of: a.district ?? a.homeDistrict))").font(.caption).foregroundStyle(.secondary)
                    }
                }
                if app.connection != .live {
                    Text("Connect to your Mac and sign in to see what this agent is doing.").foregroundStyle(.secondary)
                } else if let d = data {
                    let tasks = d.get("tasks")?.list ?? []
                    Section("Working on") {
                        let active = tasks.filter { ["RUNNING", "WAITING_FOR_APPROVAL", "PENDING"].contains($0.s("status")) }
                        if active.isEmpty { Text("No task right now.").foregroundStyle(.secondary) }
                        ForEach(active) { t in
                            HStack { Text(t.s("title")); Spacer(); StatusPill(text: t.s("status").lowercased().replacingOccurrences(of: "_", with: " "), color: Theme.status(t.s("status"))) }
                        }
                    }
                    let done = tasks.filter { ["COMPLETED", "FAILED"].contains($0.s("status")) }.prefix(5)
                    if !done.isEmpty {
                        Section("Recently") { ForEach(Array(done)) { t in Text("\(t.s("title")) · \(Format.human(t.s("status")).lowercased())").font(.caption) } }
                    }
                    let lessons = d.get("lessons")?.list ?? []
                    if !lessons.isEmpty {
                        Section {
                            ForEach(lessons) { l in Text(l.s("lesson")).font(.caption) }
                        } header: { Text("What I've learned") } footer: {
                            Text("Written from my own task runs; each cites the run it came from. Hints, not facts.")
                        }
                    }
                    if let card = (score?.get("agents")?.list ?? []).first(where: { $0.s("agent_id") == agentId }) {
                        Section("Track record (4 weeks)") { ScorecardRow(card: card) }
                    }
                    let partners = net?.get("partners")?.get(agentId)?.list ?? []
                    if !partners.isEmpty {
                        Section("Works most with") {
                            ForEach(partners) { p in
                                HStack {
                                    Text(p.s("name")).bold()
                                    Text(p.s("role")).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                    Spacer()
                                    Text("\(p.get("handoffs")?.int ?? 0) handoffs · \(p.get("messages")?.int ?? 0) msgs").font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                    let msgs = (d.get("messages")?.list ?? []).prefix(3)
                    if !msgs.isEmpty {
                        Section("Said lately") { ForEach(Array(msgs)) { m in Text(m.s("body")).font(.caption).lineLimit(3) } }
                    }
                    if let u = d.get("usage") {
                        Text("Estimated AI cost so far: $\(String(format: "%.2f", u.get("estimated_cost_usd")?.double ?? 0)) (an estimate)")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                } else {
                    ProgressView()
                }
                Section {
                    Button { dismiss(); app.openTab = "city" } label: { Label("Talk to them in the City", systemImage: "gamecontroller.fill") }
                }
            }
            .navigationTitle("Agent").navigationBarTitleDisplayMode(.inline)
            .task {
                data = try? await app.api?.json("/api/agents/\(agentId)")
                net = try? await app.api?.json("/api/insights/collaboration")
                score = try? await app.api?.json("/api/insights/scorecards")
            }
        }
    }
}

/// The home city as a list, for VoiceOver and for anyone who prefers it: every building with who's there and what
/// they're doing. Each row opens the same sheet a tap in the 3D city does.
struct AccessibleCityList: View {
    @Environment(AppState.self) private var app
    let districts: [District]
    let onSelect: (CitySelection) -> Void

    var body: some View {
        let agents = app.agents.isEmpty ? Roster.bundled : Array(app.agents.values)
        let live = !app.agents.isEmpty
        let here = Dictionary(grouping: agents) { live ? ($0.district ?? $0.homeDistrict) : $0.homeDistrict }
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(districts) { d in
                    let people = (here[d.id] ?? []).sorted { $0.name < $1.name }
                    let busy = people.filter { live && Self.working($0.executionState) }.count
                    VStack(alignment: .leading, spacing: 4) {
                        Button { onSelect(.district(d)) } label: {
                            HStack {
                                Text(d.name).font(.headline).foregroundStyle(Theme.ink)
                                Spacer()
                                Text(Self.summary(people.count, busy, live)).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .accessibilityLabel("\(d.name). \(Self.summary(people.count, busy, live))")
                        .accessibilityHint("Shows the work going on in this building")
                        ForEach(people) { a in
                            Button { onSelect(.agent(a.id)) } label: {
                                HStack(spacing: 6) {
                                    Text(a.name).font(.subheadline)
                                    Text(a.role).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                    Spacer()
                                    if live { Text(Format.human(a.executionState)).font(.caption).foregroundStyle(Theme.status(a.executionState)) }
                                }
                            }
                            .padding(.leading, 12)
                            .accessibilityLabel("\(a.name), \(a.role)" + (live ? ", \(Format.human(a.executionState))" : ""))
                            .accessibilityHint("Shows what \(a.name) is doing")
                        }
                    }
                    .padding(8)
                    .background(Color(hex: 0x0E1326).opacity(0.85), in: RoundedRectangle(cornerRadius: 6))
                }
                if !live {
                    Text("Offline: agents are shown at their home buildings.").font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 10)
        }
        .background(Pixel.sky)
    }

    static func working(_ s: String) -> Bool { ["EXECUTING", "ASSIGNED", "PLANNING", "REVIEWING", "WAITING_FOR_TOOL"].contains(s) }

    static func summary(_ n: Int, _ busy: Int, _ live: Bool) -> String {
        let who = n == 0 ? "nobody here" : "\(n) agent\(n == 1 ? "" : "s")"
        return live && busy > 0 ? "\(who), \(busy) working" : who
    }
}
