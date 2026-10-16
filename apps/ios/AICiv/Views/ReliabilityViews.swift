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
                            Text("\(total) failure\(total == 1 ? "" : "s")").font(.title2.bold())
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
        let met = objective.get("met")?.bool ?? false
        VStack(alignment: .leading, spacing: 4) {
            Label(met ? "Objective met" : "Objective not met", systemImage: met ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(met ? Theme.ok : Theme.warn).font(.subheadline.bold())
            ForEach(Array((objective.get("findings")?.list ?? []).enumerated()), id: \.offset) { _, f in
                Text(f.str).font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}
