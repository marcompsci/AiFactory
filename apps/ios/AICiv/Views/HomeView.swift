import SwiftUI

/// Home: the dashboard frame from the web app, rebuilt natively — stats bar, a live pixel map of the city, and the
/// four panels (live agent activity, conveyor flow, active projects, financial overview). Every number is from the API.
struct HomeView: View {
    @Environment(AppState.self) private var app
    @State private var overview: JSONValue?
    @State private var error: String?
    @State private var selected: District?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    header
                    if case .failed(let why) = app.connection {
                        if why.contains("Sign in") { SignInCard() } else { RetryCard(message: why) }
                    }
                    stats
                    if app.connection == .live { BriefCard().pixelPanel() }
                    LiveCityView()
                        .pixelPanel()
                    activity
                    conveyor
                    projects
                    finance
                    if let error { Text(error).font(.caption).foregroundStyle(Theme.bad) }
                }
                .padding(.horizontal, 14)
                .padding(.bottom, 24)
            }
            .background(Pixel.sky.ignoresSafeArea())
            .refreshable { await load() }
            .task(id: app.ledger.lastSequence / 5) { await load() }
            .sheet(item: $selected) { d in DistrictSheet(district: d).presentationDetents([.medium]) }
            .toolbar(.hidden, for: .navigationBar)
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 5)
                .fill(LinearGradient(colors: [Theme.violet, Theme.cyan, Color(hex: 0xFF4FB0)], startPoint: .topLeading, endPoint: .bottomTrailing))
                .frame(width: 36, height: 36)
                .overlay(Image(systemName: "triangle.fill").font(.system(size: 14, weight: .black)).foregroundStyle(Theme.ground))
            VStack(alignment: .leading, spacing: 1) {
                Text("AI CIVILIZATION").font(Pixel.title(16)).foregroundStyle(Theme.ink)
                Text("BUILD · RESEARCH · CREATE · GROW").font(Pixel.mono(8)).foregroundStyle(.secondary)
            }
            Spacer()
            ConnectionBadge()
        }
        .padding(.top, 8)
    }

    private var stats: some View {
        let f = overview?.get("finance")
        let sim: String? = f?.get("simulated")?.isTrue == true ? "simulated" : nil
        let labWaiting = overview?.get("lab_waiting")?.int ?? 0
        return LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
            StatTile(label: "Cash", value: f.map { Money.minor($0.get("cash_minor")?.int) } ?? "owner only", sub: sim, color: Color(hex: 0x3DFFB8))
            StatTile(label: "Agents", value: "\(overview?.get("agents")?.get("working")?.int ?? 0)/\(overview?.get("agents")?.get("total")?.int ?? app.agents.count)", sub: "working")
            StatTile(label: "Tasks", value: "\(overview?.get("tasks")?.get("running")?.int ?? 0)", sub: "\(overview?.get("tasks")?.get("completed_today")?.int ?? 0) done today")
            StatTile(label: "Projects", value: "\(overview?.get("projects")?.get("active")?.int ?? 0)", sub: labWaiting > 0 ? "\(labWaiting) need you" : "active")
            StatTile(label: "30-day revenue", value: f.map { Money.minor($0.get("revenue_30d_minor")?.int) } ?? "owner only", sub: sim, color: Theme.gold)
            StatTile(label: "Owner", value: "\(app.ownerWaiting)", sub: "waiting", color: app.ownerWaiting > 0 ? Theme.gold : Theme.ink)
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

    private func load() async {
        guard let api = app.api else { return }
        do { overview = try await api.overview(); error = nil } catch let e as APIError where e.status == 401 {
            overview = nil
        } catch { self.error = error.localizedDescription }
    }

    static func time(_ iso: String) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let d = f.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else { return "" }
        return d.formatted(date: .omitted, time: .shortened)
    }
}

/// A native, pixel-art isometric map of the city: districts as glowing decks, agents as pixels at their district, the
/// conveyor ring around the Nexus Spire. Tap a district for who's there. (The full 3D city is in the City tab.)
struct MiniCityView: View {
    @Environment(AppState.self) private var app
    @Binding var selected: District?

    var body: some View {
        GeometryReader { g in
            let ds = app.districts
            let proj = Projection(districts: ds, size: g.size)
            TimelineView(.animation(minimumInterval: 1.0 / 8)) { tl in
                Canvas { ctx, size in
                    let t = tl.date.timeIntervalSinceReferenceDate
                    // conveyor spokes and ring
                    let center = proj.point(0, 0)
                    for d in ds {
                        var path = Path()
                        path.move(to: center)
                        path.addLine(to: proj.point(d.x, d.z))
                        ctx.stroke(path, with: .color(Theme.cyan.opacity(0.25)), style: StrokeStyle(lineWidth: 2, dash: [4, 3], dashPhase: CGFloat(-t * 8)))
                    }
                    for d in ds.sorted(by: { $0.z < $1.z }) {
                        let p = proj.point(d.x, d.z)
                        let c = Pixel.districtColor[d.id] ?? Color(hexString: d.color)
                        let busy = app.agents.values.contains { $0.district == d.id && $0.executionState == "EXECUTING" }
                        // deck: an isometric diamond with a side face
                        let w: CGFloat = proj.scale * 9
                        let h: CGFloat = w * 0.5
                        var top = Path()
                        top.move(to: CGPoint(x: p.x, y: p.y - h)); top.addLine(to: CGPoint(x: p.x + w, y: p.y))
                        top.addLine(to: CGPoint(x: p.x, y: p.y + h)); top.addLine(to: CGPoint(x: p.x - w, y: p.y)); top.closeSubpath()
                        var side = Path()
                        side.move(to: CGPoint(x: p.x - w, y: p.y)); side.addLine(to: CGPoint(x: p.x, y: p.y + h))
                        side.addLine(to: CGPoint(x: p.x + w, y: p.y)); side.addLine(to: CGPoint(x: p.x + w, y: p.y + 5))
                        side.addLine(to: CGPoint(x: p.x, y: p.y + h + 5)); side.addLine(to: CGPoint(x: p.x - w, y: p.y + 5)); side.closeSubpath()
                        ctx.fill(side, with: .color(Color(hex: 0x3A2F58)))
                        let glow: Double = busy ? 0.55 + 0.25 * sin(t * 4) : 0.3
                        ctx.fill(top, with: .color(c.opacity(glow)))
                        ctx.stroke(top, with: .color(c), lineWidth: 1.5)
                        // tower block
                        let tall = d.id == "owners-tower" || d.id == "central-bank"
                        let bh: CGFloat = proj.scale * (tall ? 10 : 6)
                        ctx.fill(Path(CGRect(x: p.x - w * 0.25, y: p.y - h * 0.3 - bh, width: w * 0.5, height: bh)), with: .color(Color(hex: 0x141B33)))
                        ctx.stroke(Path(CGRect(x: p.x - w * 0.25, y: p.y - h * 0.3 - bh, width: w * 0.5, height: bh)), with: .color(c.opacity(0.9)), lineWidth: 1)
                        // agents as pixels
                        let here = app.agents.values.filter { ($0.district ?? $0.homeDistrict) == d.id }.sorted { $0.name < $1.name }
                        for (i, a) in here.enumerated() {
                            let col = CGFloat(i % 5), row = CGFloat(i / 5)
                            let bob: CGFloat = a.executionState == "EXECUTING" ? CGFloat(sin(t * 6 + Double(i))) * 1.5 : 0
                            let ax: CGFloat = p.x - w * 0.5 + col * (w * 0.25)
                            let ay: CGFloat = p.y + row * 5 - 2 + bob
                            ctx.fill(Path(CGRect(x: ax, y: ay, width: 4, height: 4)), with: .color(Color(hexString: a.avatar.color)))
                        }
                        ctx.draw(Text(d.name.uppercased()).font(Pixel.title(7)).foregroundStyle(.white), at: CGPoint(x: p.x, y: p.y - h - bh - 2), anchor: .bottom)
                    }
                    _ = size
                }
            }
            .contentShape(Rectangle())
            .onTapGesture { loc in selected = proj.nearest(loc, in: ds) }
            .overlay(alignment: .topLeading) { PixelHeader(text: "The city").padding(2) }
            .overlay { if ds.isEmpty { Text("Connect to see the city").font(.caption).foregroundStyle(.secondary) } }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Map of the city with \(ds.count) districts and \(app.agents.count) agents")
        }
    }

    struct Projection {
        let districts: [District]
        let size: CGSize
        var scale: CGFloat {
            let xs = districts.map { iso($0.x, $0.z).x }, ys = districts.map { iso($0.x, $0.z).y }
            let spanX = max(1, (xs.max() ?? 1) - (xs.min() ?? 0)), spanY = max(1, (ys.max() ?? 1) - (ys.min() ?? 0))
            return min((size.width - 60) / spanX, (size.height - 70) / spanY)
        }
        func iso(_ x: Double, _ z: Double) -> CGPoint { CGPoint(x: (x - z) * 0.866, y: (x + z) * 0.5) }
        func point(_ x: Double, _ z: Double) -> CGPoint {
            let xs = districts.map { iso($0.x, $0.z).x }, ys = districts.map { iso($0.x, $0.z).y }
            let cx = ((xs.max() ?? 0) + (xs.min() ?? 0)) / 2, cy = ((ys.max() ?? 0) + (ys.min() ?? 0)) / 2
            let q = iso(x, z)
            return CGPoint(x: size.width / 2 + (q.x - cx) * scale, y: size.height / 2 + 14 + (q.y - cy) * scale)
        }
        func nearest(_ loc: CGPoint, in ds: [District]) -> District? {
            ds.min { hypot(point($0.x, $0.z).x - loc.x, point($0.x, $0.z).y - loc.y) < hypot(point($1.x, $1.z).x - loc.x, point($1.x, $1.z).y - loc.y) }
        }
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
