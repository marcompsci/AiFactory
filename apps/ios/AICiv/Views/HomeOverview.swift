import SwiftUI

/// The command sheet's Overview tab (the website's OverviewTab): the brief, live agent activity, conveyor flow,
/// active projects and the financial overview. Every number is from the API.
struct HomeOverviewTab: View {
    @Environment(AppState.self) private var app
    let overview: JSONValue?
    let error: String?

    var body: some View {
        VStack(spacing: 12) {
            if case .failed(let why) = app.connection {
                if why.contains("Sign in") { SignInCard() } else { RetryCard(message: why) }
            }
            if let low = app.lowStorage { LowStorageCard(report: low) }
            if app.connection == .live { BriefCard().pixelPanel() }
            more
            activity
            conveyor
            projects
            finance
            if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
        }
    }

    /// The two figures the top bar has no room for on a phone (the website hides them there too).
    private var more: some View {
        let f = overview?.get("finance")
        let sim: String? = f?.get("simulated")?.isTrue == true ? "simulated" : nil
        let labWaiting = overview?.get("lab_waiting")?.int ?? 0
        return HStack(spacing: 8) {
            StatTile(label: "Projects", value: overview.map { "\($0.get("projects")?.get("active")?.int ?? 0)" } ?? "—", sub: labWaiting > 0 ? "\(labWaiting) need you" : "active")
            StatTile(label: "30-day revenue", value: f.map { Money.minor($0.get("revenue_30d_minor")?.int) } ?? "owner only", sub: sim, color: Theme.gold)
        }
    }

    private var activity: some View {
        VStack(alignment: .leading, spacing: 6) {
            PixelHeader(text: "Live agent activity")
            let items = Array(app.ledger.feed.prefix(6))
            if items.isEmpty { Text("Waiting for the agents…").font(.caption).foregroundStyle(.secondary) }
            ForEach(items) { e in
                let line = FeedText.line(e, agents: app.agents)
                HStack(alignment: .top, spacing: 6) {
                    Text(Self.time(e.occurredAt)).font(Pixel.mono(9)).foregroundStyle(.secondary).frame(width: 44, alignment: .leading)
                    if let a = e.agentId.flatMap({ app.agents[$0] }) {
                        AgentPortrait(agent: a, size: 20)
                    } else {
                        Rectangle().fill(Theme.cyan).frame(width: 9, height: 9).padding(.top, 3)
                    }
                    (Text(line.who).bold() + Text(" ") + Text(line.text).foregroundStyle(.secondary)).font(.caption).lineLimit(2)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .pixelPanel()
    }

    private var conveyor: some View {
        let stages = overview?.get("conveyor")?.list ?? []
        let colors: [String: Color] = ["research": Theme.gold, "manager": Theme.violet, "production": Color(hex: 0x4C8DFF), "qa": Color(hex: 0x3FB8FF),
                                       "bank": Color(hex: 0x3DE08A), "owner": Color(hex: 0xFF9A3D)]
        return VStack(alignment: .leading, spacing: 8) {
            PixelHeader(text: "Conveyor flow")
            HStack(spacing: 0) {
                ForEach(stages) { st in
                    let c = colors[st.s("id")] ?? Theme.cyan
                    let n = st.get("in_transit")?.int ?? 0
                    VStack(spacing: 4) {
                        Text("\(n)").font(Pixel.title(14)).foregroundStyle(n > 0 ? .white : c)
                            .frame(width: 34, height: 34)
                            .background(n > 0 ? c.opacity(0.4) : Pixel.panel, in: RoundedRectangle(cornerRadius: 3))
                            .overlay(RoundedRectangle(cornerRadius: 3).strokeBorder(c, lineWidth: 2))
                            .shadow(color: n > 0 ? c : .clear, radius: 6)
                        Text(st.s("label")).font(Pixel.mono(8)).foregroundStyle(.secondary).lineLimit(1).minimumScaleFactor(0.7)
                    }
                    .frame(maxWidth: .infinity)
                }
            }
        }
        .pixelPanel()
    }

    private var projects: some View {
        let items = overview?.get("projects")?.get("items")?.list ?? []
        return VStack(alignment: .leading, spacing: 8) {
            PixelHeader(text: "Active projects", trailing: "\(items.count)")
            if items.isEmpty { Text("No active projects. Start an App Lab cycle or send a researcher out.").font(.caption).foregroundStyle(.secondary) }
            ForEach(items) { p in
                VStack(alignment: .leading, spacing: 4) {
                    HStack { Text(p.s("title")).font(.caption).lineLimit(1); Spacer(); Text(Format.human(p.s("status"))).font(Pixel.mono(9)).foregroundStyle(.secondary) }
                    PixelBar(progress: p.get("progress")?.double ?? 0)
                }
            }
        }
        .pixelPanel()
    }

    private var finance: some View {
        VStack(alignment: .leading, spacing: 6) {
            PixelHeader(text: "Financial overview", trailing: "30 days")
            if let f = overview?.get("finance") {
                if f.get("simulated")?.isTrue == true { Text("SIMULATED DATA").font(Pixel.mono(9)).foregroundStyle(Theme.warn) }
                row("Revenue", f.get("revenue_30d_minor")?.int, Color(hex: 0x3DFFB8))
                row("Expenses", f.get("expenses_30d_minor")?.int, Theme.bad)
                row("Tax reserve (estimate)", f.get("tax_reserve_minor")?.int, Theme.gold)
                row("Operating surplus (estimate)", f.get("surplus_30d_minor")?.int, Theme.cyan)
            } else {
                Text("Financial figures are for the owner and admins.").font(.caption).foregroundStyle(.secondary)
            }
        }
        .pixelPanel()
    }

    private func row(_ label: String, _ v: Int?, _ color: Color) -> some View {
        HStack { Text(label).font(.caption).foregroundStyle(.secondary); Spacer(); Text(Money.minor(v)).font(Pixel.mono(12)).foregroundStyle(color) }
    }

    static func time(_ iso: String) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let d = f.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else { return "" }
        return d.formatted(date: .omitted, time: .shortened)
    }
}

struct DistrictSheet: View {
    @Environment(AppState.self) private var app
    let district: District

    var body: some View {
        let c = Pixel.districtColor[district.id] ?? Color(hexString: district.color)
        let here = app.agents.values.filter { ($0.district ?? $0.homeDistrict) == district.id }.sorted { $0.name < $1.name }
        VStack(alignment: .leading, spacing: 12) {
            NeonSign(icon: "◆", text: district.name, color: c)
            if let p = district.purpose { Text(p).font(.subheadline).foregroundStyle(.secondary) }
            PixelHeader(text: "Here now", color: c, trailing: "\(here.count)")
            ForEach(here) { a in
                HStack {
                    AgentPortrait(agent: a, size: 32)
                    Text(a.name).bold()
                    Text(a.role).foregroundStyle(.secondary).lineLimit(1)
                    Spacer()
                    StatusPill(text: Format.human(a.executionState), color: Theme.status(a.executionState))
                }
                .font(.subheadline)
            }
            Spacer()
        }
        .padding(20)
        .background(Theme.ground)
    }
}

/// Shown on Home when the server needs a signed-in user.
/// The connection stopped (for example after too many refused sign-ins): say why and offer the way forward.
struct RetryCard: View {
    @Environment(AppState.self) private var app
    let message: String
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PixelHeader(text: "Not connected", color: Theme.warn)
            Text(message).font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("Try again") { app.connect() }.buttonStyle(.borderedProminent)
                Button("Sign in again") { Task { await app.signIn(provider: "google") } }.buttonStyle(.bordered)
            }
            if let e = app.authError { Text(e).font(.caption).foregroundStyle(Theme.bad) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .pixelPanel(Theme.warn.opacity(0.6))
    }
}

struct SignInCard: View {
    @Environment(AppState.self) private var app
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PixelHeader(text: "Sign in", color: Theme.gold)
            if let why = app.signInReason { Text(why).font(.caption.bold()).foregroundStyle(Theme.gold) }
            Text("This server needs you to sign in. Use the same Google or GitHub account as on the web.").font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("Google") { Task { await app.signIn(provider: "google") } }.buttonStyle(.borderedProminent)
                Button("GitHub") { Task { await app.signIn(provider: "github") } }.buttonStyle(.bordered)
            }
            if let e = app.authError { Text(e).font(.caption).foregroundStyle(Theme.bad) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .pixelPanel(Theme.gold.opacity(0.6))
    }
}

/// V6.89: the phone is nearly full.
struct LowStorageCard: View {
    @Environment(AppState.self) private var app
    let report: StorageGuard.Report
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                PixelHeader(text: "iPhone almost full", color: Theme.gold)
                Spacer()
                Button { app.lowStorage = nil } label: { Image(systemName: "xmark") }.buttonStyle(.plain).accessibilityLabel("Dismiss")
            }
            Text("\(report.free) free. AI Civ cleared \(report.cleared) of its own cache; your tasks are safe on your Mac. "
                 + "Free more space in Settings › General › iPhone Storage so the app (and iOS) can keep working.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .pixelPanel(Theme.gold.opacity(0.5))
    }
}
