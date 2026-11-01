import SceneKit
import SwiftUI
import UIKit
import simd

/// What the user tapped in the 3D city.
enum CityTap: Equatable {
    case agent(String), district(String), package(String), nothing
}

/// Where each sign, name tag, bubble and board sits on screen this moment, worked out from the 3D anchors 15 times a
/// second (the website does the same with drei's <Html>: HTML placed over the canvas at projected 3D points).
@MainActor
@Observable
final class CityPins {
    struct Pin: Equatable { var point: CGPoint; var depth: Float }
    var pins: [String: Pin] = [:]
}

extension CityScene {
    /// The screen point (in the view's points) and distance of a world point, or nil when it's behind the camera or
    /// well off screen.
    func project(_ w: SIMD3<Float>, size: CGSize) -> CityPins.Pin? {
        guard size.width > 0, size.height > 0 else { return nil }
        let p = cameraNode.simdWorldTransform.inverse * SIMD4<Float>(w.x, w.y, w.z, 1)
        guard p.z < -0.5 else { return nil }
        let t = tan(Float(22.5) * .pi / 180)
        let aspect = Float(size.width / size.height)
        let nx = (p.x / -p.z) / (t * aspect), ny = (p.y / -p.z) / t
        guard abs(nx) < 1.25, abs(ny) < 1.25 else { return nil }
        return CityPins.Pin(point: CGPoint(x: CGFloat((nx + 1) / 2) * size.width, y: CGFloat((1 - ny) / 2) * size.height), depth: -p.z)
    }

    func updatePins(_ model: CityPins, size: CGSize) {
        var out: [String: CityPins.Pin] = [:]
        for (id, n) in anchors {
            if let p = project(n.simdWorldPosition, size: size) { out[id] = p }
        }
        if out != model.pins { model.pins = out }
    }
}

/// The SceneKit view: rendered at half resolution and scaled up without smoothing, like the website's dpr 0.5
/// pixelated canvas. One finger orbits (Fly: moves), two fingers pan, pinch zooms, tap picks.
struct CitySceneView: UIViewRepresentable {
    let city: CityScene
    let pins: CityPins
    var paused = false
    let onTap: (CityTap) -> Void

    func makeUIView(context: Context) -> SCNView {
        let v = SCNView(frame: .zero, options: nil)
        v.scene = city.scene
        v.pointOfView = city.cameraNode
        v.backgroundColor = UIColor(hex: 0x121A44)
        // V6.53: full resolution with smoothed edges (the light mode renders a little softer to stay cool)
        v.antialiasingMode = city.lowQuality ? .none : .multisampling4X
        v.contentScaleFactor = city.lowQuality ? min(2, UIScreen.main.scale) : UIScreen.main.scale
        v.isJitteringEnabled = false
        v.preferredFramesPerSecond = 30
        v.rendersContinuously = true
        v.isPlaying = true
        v.allowsCameraControl = false
        let c = context.coordinator
        let orbit = UIPanGestureRecognizer(target: c, action: #selector(Coordinator.orbit(_:)))
        orbit.maximumNumberOfTouches = 1
        let pan = UIPanGestureRecognizer(target: c, action: #selector(Coordinator.pan(_:)))
        pan.minimumNumberOfTouches = 2
        let pinch = UIPinchGestureRecognizer(target: c, action: #selector(Coordinator.pinch(_:)))
        let tap = UITapGestureRecognizer(target: c, action: #selector(Coordinator.tap(_:)))
        for g in [orbit, pan, pinch, tap] as [UIGestureRecognizer] {
            g.delegate = c
            v.addGestureRecognizer(g)
        }
        c.view = v
        c.start()
        return v
    }

    func updateUIView(_ v: SCNView, context: Context) {
        context.coordinator.onTap = onTap
        v.rendersContinuously = !paused
        v.isPlaying = !paused
        city.paused = paused
    }

    static func dismantleUIView(_ v: SCNView, coordinator: Coordinator) { coordinator.stop() }

    func makeCoordinator() -> Coordinator { Coordinator(city: city, pins: pins, onTap: onTap) }

    @MainActor
    final class Coordinator: NSObject, UIGestureRecognizerDelegate {
        let city: CityScene
        let pins: CityPins
        var onTap: (CityTap) -> Void
        weak var view: SCNView?
        private var last = CGPoint.zero
        private var startDistance: Float = 0
        private var timer: Timer?

        init(city: CityScene, pins: CityPins, onTap: @escaping (CityTap) -> Void) {
            self.city = city
            self.pins = pins
            self.onTap = onTap
        }

        func start() {
            timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 15, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated {
                    guard let self, let v = self.view, !self.city.paused else { return }
                    let s = v.bounds.size
                    if s.height > 0 { self.city.aspect = Float(s.width / s.height) }
                    self.city.updatePins(self.pins, size: s)
                }
            }
        }

        func stop() { timer?.invalidate(); timer = nil }

        func gestureRecognizer(_ g: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith o: UIGestureRecognizer) -> Bool {
            (g is UIPinchGestureRecognizer && o is UIPanGestureRecognizer) || (g is UIPanGestureRecognizer && o is UIPinchGestureRecognizer)
        }

        @objc func orbit(_ g: UIPanGestureRecognizer) {
            guard let v = view else { return }
            let t = g.translation(in: v)
            if g.state == .began { last = .zero }
            city.drag(dx: Float(t.x - last.x), dy: Float(t.y - last.y), height: Float(v.bounds.height))
            last = t
        }

        @objc func pan(_ g: UIPanGestureRecognizer) {
            guard let v = view else { return }
            let t = g.translation(in: v)
            if g.state == .began { last = .zero }
            city.pan(dx: Float(t.x - last.x), dy: Float(t.y - last.y), height: Float(v.bounds.height))
            last = t
        }

        @objc func pinch(_ g: UIPinchGestureRecognizer) {
            if g.state == .began { startDistance = city.distance }
            city.dolly(Float(g.scale), from: startDistance)
        }

        @objc func tap(_ g: UITapGestureRecognizer) {
            guard let v = view else { return }
            let hits = v.hitTest(g.location(in: v), options: [.searchMode: SCNHitTestSearchMode.all.rawValue, .ignoreHiddenNodes: true])
            var district: String?
            for h in hits {
                var n: SCNNode? = h.node
                while let node = n {
                    if let name = node.name {
                        if name.hasPrefix("agent:") { onTap(.agent(String(name.dropFirst(6)))); return }
                        if name.hasPrefix("package:") { onTap(.package(String(name.dropFirst(8)))); return }
                        if district == nil, name.hasPrefix("district:") { district = String(name.dropFirst(9)) }
                    }
                    n = node.parent
                }
            }
            onTap(district.map { .district($0) } ?? .nothing)
        }
    }
}

/// Everything the website draws as HTML over the 3D city: district signs, the Knowledge Base and Logistics Network
/// signs, agents' name tags and bubbles, a district's "what's happening" speech bubble, the factory boards, and the
/// label of a package you tapped.
struct CityOverlay: View {
    @Environment(AppState.self) private var app
    let city: CityScene
    let pins: CityPins
    let districts: [District]
    var selectedAgent: String?
    var selectedPackage: String?
    var factories: JSONValue?
    var knowledge: (skills: Int, docs: Int)?
    let onTap: (CityTap) -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { tl in
            let now = tl.date
            ZStack(alignment: .topLeading) {
                ForEach(districts) { d in districtPins(d, now: now) }
                hubAndKB
                ForEach(agentsOnScreen(), id: \.id) { a in agentPin(a, now: now) }
                if let id = selectedPackage, let p = app.packages.first(where: { $0.id == id }), let pin = pins.pins["pkg:\(id)"] {
                    Tag(pin.point) {
                        speech("\(TownRules.packageLabel[p.type] ?? Format.human(p.type)): \(Town.name(of: p.origin)) → \(Town.name(of: p.destination)) · \(Format.human(p.status).lowercased())",
                               color: Color(hexString: WorldMap.packageColor[p.type] ?? "#EAF2FF"))
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    @ViewBuilder private func districtPins(_ d: District, now: Date) -> some View {
        let c = Color(hexString: d.color)
        if let p = pins.pins["sign:\(d.id)"] {
            let sub = d.id == "nexus-spire" ? Self.managerModel.map { "AI Manager (\($0))" } : nil
            Button { onTap(.district(d.id)) } label: { NeonSign(icon: WorldMap.signIcon[d.id] ?? "◆", text: d.name, color: c, sub: sub) }
                .buttonStyle(.plain)
                .scaleEffect(signScale(p.depth))
                .position(p.point)
                .accessibilityLabel(d.name)
                .accessibilityHint("Shows what's happening in this building")
        }
        if let p = pins.pins["bubble:\(d.id)"], let text = bubbleText(d, now: now) {
            Tag(p.point) { speech(text.count > 70 ? String(text.prefix(68)) + "…" : text, color: c) }
                .allowsHitTesting(false)
        }
        if let p = pins.pins["board:\(d.id)"], let b = board(d) {
            FactoryBoard(title: b.title, lines: b.lines, color: c).position(p.point).allowsHitTesting(false)
                .scaleEffect(signScale(p.depth) * 0.95)
        }
    }

    @ViewBuilder private var hubAndKB: some View {
        if let p = pins.pins["hub"] {
            NeonSign(icon: "▣", text: "Logistics Network", color: Color(hex: 0xF4D58D)).scaleEffect(signScale(p.depth)).position(p.point).allowsHitTesting(false)
        }
        if let p = pins.pins["kb"] {
            let counts = knowledge.map { " · \($0.skills) skills, \($0.docs) docs" } ?? ""
            NeonSign(icon: "✦", text: "Knowledge Base", color: Color(hex: 0x9BE7FF), sub: "Phoronomics · Phoronomic Studios" + counts)
                .scaleEffect(signScale(p.depth)).position(p.point).allowsHitTesting(false)
        }
    }

    private func signScale(_ depth: Float) -> CGFloat { depth > 160 ? 0.82 : depth > 90 ? 0.9 : 1 }

    private struct OnScreen { let id: String; let name: String; let color: Color; let pin: CityPins.Pin }

    private func agentsOnScreen() -> [OnScreen] {
        let all = app.agents.isEmpty ? Roster.bundled : Array(app.agents.values)
        // name tags get crowded in the overview: show them once you're closer, or for the agent you picked
        let close = city.distance < 120
        return all.compactMap { a in
            guard let p = pins.pins["agent:\(a.id)"] else { return nil }
            let talking = app.world.indicators[a.id] != nil
            guard close || talking || a.id == selectedAgent else { return nil }
            return OnScreen(id: a.id, name: a.name, color: Color(hexString: a.avatar.color), pin: p)
        }
        .sorted { $0.pin.depth > $1.pin.depth }
    }

    @ViewBuilder private func agentPin(_ a: OnScreen, now: Date) -> some View {
        let ind = app.world.indicators[a.id]
        let fresh = ind.map { $0.kind == "approval" || now.timeIntervalSince($0.at) < 4.5 } ?? false
        Tag(a.pin.point) {
            VStack(spacing: 3) {
                if let ind, fresh {
                    let b = CityWorld.bubble(ind.kind)
                    let text = ind.kind == "message" ? (ind.text.count > 90 ? String(ind.text.prefix(88)) + "…" : ind.text) : ind.text.replacingOccurrences(of: "_", with: " ")
                    VStack(alignment: .leading, spacing: 1) {
                        Text(b.label.uppercased()).font(Pixel.sign(9)).foregroundStyle(Color(hex: b.color))
                        Text(text).font(.system(size: 11, weight: .medium)).foregroundStyle(.white).lineLimit(3)
                    }
                    .frame(maxWidth: 190, alignment: .leading)
                    .padding(.horizontal, 7).padding(.vertical, 5)
                    .background(Color(hex: 0x0B1226).opacity(0.94), in: RoundedRectangle(cornerRadius: 6))
                    .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color(hex: b.color).opacity(0.7), lineWidth: 1.5))
                    .transition(.opacity.combined(with: .scale(scale: 0.96, anchor: .bottom)))
                }
                Text(a.name).font(Pixel.sign(11)).foregroundStyle(a.color)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(Color(red: 7 / 255, green: 11 / 255, blue: 24 / 255).opacity(0.7), in: Capsule())
                    .overlay(Capsule().strokeBorder(a.id == selectedAgent ? a.color : .clear, lineWidth: 1.5))
            }
            .fixedSize()
            .onTapGesture { onTap(.agent(a.id)) }
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
    }

    private func speech(_ text: String, color: Color) -> some View {
        Text(text).font(.system(size: 11, weight: .medium)).foregroundStyle(.white).lineLimit(2)
            .frame(maxWidth: 200, alignment: .leading).fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, 8).padding(.vertical, 5)
            .background(Color(hex: 0x0B1226).opacity(0.94), in: RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(color.opacity(0.6), lineWidth: 1.5))
            .overlay(alignment: .bottomLeading) {
                Triangle().fill(Color(hex: 0x0B1226)).frame(width: 12, height: 7).offset(x: 14, y: 7)
            }
            .padding(.bottom, 8)
    }

    /// The tool running at one of the district's desks, or failing that what someone there just said.
    private func bubbleText(_ d: District, now: Date) -> String? {
        if let tool = (d.workstations ?? []).lazy.compactMap({ app.world.active[$0.id] }).first {
            return "\(CityWorld.toolTalk[tool] ?? tool.replacingOccurrences(of: "_", with: " "))…"
        }
        let all = app.agents.isEmpty ? Roster.bundled : Array(app.agents.values)
        let here = all.filter { (app.world.places[$0.id]?.district ?? $0.district ?? $0.homeDistrict) == d.id }
        return here.compactMap { app.world.indicators[$0.id] }
            .filter { $0.kind == "message" && now.timeIntervalSince($0.at) < 8 }
            .max { $0.at < $1.at }?.text
    }

    /// The factory wall board (District.tsx FactoryBoard): owners and admins only — the API refuses everyone else.
    private func board(_ d: District) -> (title: String, lines: [String])? {
        guard let data = factories else { return nil }
        var lines: [String] = []
        var title = ""
        if d.id == "claude-code-factory" {
            guard let cc = data.get("claude_code"), cc.get("linked")?.isTrue == true else { return nil }
            let info = cc.get("data")
            let active = info?.get("active")?.int ?? 0
            title = Self.present(info) ? "\(active > 0 ? "\(active) active · " : "")finished recently" : "waiting for first check-in"
            let sessions = info?.get("sessions")?.list ?? []
            lines = Array(sessions.flatMap { s in (s.get("completed_tasks")?.list ?? []).suffix(2).map { "✓ \($0.string ?? "")" } }.prefix(4))
            if lines.isEmpty { lines = sessions.prefix(3).map { "• \($0.s("title"))" } }
        } else if d.id == "codex-factory" {
            let u = data.get("plan_usage")?.get("data")
            let cx = data.get("codex")
            let hasUsage = Self.present(u)
            guard hasUsage || cx?.get("linked")?.isTrue == true else { return nil }
            if let u, hasUsage {
                let p = u.get("codex")?.get("primary")?.get("used_percent")?.int
                let w = u.get("codex")?.get("secondary")?.get("used_percent")?.int
                let cl = u.get("claude")
                let plan = u.s("plan")
                title = plan.isEmpty ? "no plan usage left" : "agents on \(plan == "codex" ? "Codex" : "Claude")\(u.s("model").isEmpty ? "" : " · \(u.s("model"))")"
                lines.append("Codex \(p.map { String($0) } ?? "?")% of 5h\(w.map { " · \($0)% week" } ?? "")")
                if let used = cl?.get("used_percent")?.int {
                    lines.append("Claude ~\(used)% of 5h (est.)")
                } else {
                    lines.append("Claude \(Int(((cl?.get("tokens_5h")?.double ?? 0) / 1000).rounded()))k tokens 5h (est.)")
                }
                if u.get("owner_active")?.isTrue == true { lines.append("You're on Claude → agents on smallest model") }
            } else { title = "waiting for first check-in" }
            for s in cx?.get("data")?.get("sessions")?.list ?? [] where s.get("by_agents")?.isTrue != true {
                lines += (s.get("completed_tasks")?.list ?? []).suffix(1).map { "✓ \($0.string ?? "")" }
            }
            lines = Array(lines.prefix(4))
        } else {
            guard let gh = data.get("github"), gh.get("linked")?.isTrue == true else { return nil }
            let info = gh.get("data")
            title = Self.present(info) ? "latest on GitHub" : "waiting for first check-in"
            for r in info?.get("repos")?.list ?? [] {
                for p in (r.get("pulls")?.list ?? []).prefix(2) {
                    let state = p.s("state") == "merged" ? "⇣ merged" : p.get("draft")?.isTrue == true ? "◌ draft" : "◉ open"
                    lines.append("\(state) #\(p.get("number")?.int ?? 0) \(p.s("title"))")
                }
                for x in (r.get("runs")?.list ?? []).prefix(1) {
                    let c = x.s("conclusion")
                    lines.append("\(c == "success" ? "✓" : c.isEmpty ? "…" : "✗") \(x.s("name"))")
                }
            }
            lines = Array(lines.prefix(4))
        }
        return (title, lines)
    }

    static func present(_ v: JSONValue?) -> Bool {
        guard let v else { return false }
        if case .null = v { return false }
        return true
    }

    static let managerModel: String? = {
        // the General Manager's model from the bundled cast, e.g. "claude-opus-5-5" → "OPUS 5.5"
        guard let m = Roster.bundled.first(where: { $0.key == "general_manager" })?.modelName else { return nil }
        return WorldMap.managerModel(m)
    }()
}

/// Pins a view so its bottom centre sits on a projected point (an agent's head, a district's bubble spot).
struct Tag<Content: View>: View {
    let point: CGPoint
    @ViewBuilder let content: () -> Content
    init(_ point: CGPoint, @ViewBuilder content: @escaping () -> Content) { self.point = point; self.content = content }
    var body: some View {
        Color.clear.frame(width: 1, height: 1)
            .overlay(alignment: .bottom) { content().fixedSize() }
            .position(point)
    }
}

struct Triangle: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.minY))
        p.addLine(to: CGPoint(x: r.maxX, y: r.minY))
        p.addLine(to: CGPoint(x: r.midX, y: r.maxY))
        p.closeSubpath()
        return p
    }
}

/// The CRT board on a factory's wall (the website's `.factory-board`: 230 px, mono 10 px, neon frame).
struct FactoryBoard: View {
    let title: String
    let lines: [String]
    let color: Color
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title.uppercased()).font(Pixel.sign(9)).foregroundStyle(color).lineLimit(1)
            if lines.isEmpty { Text("nothing yet").opacity(0.6) }
            ForEach(Array(lines.enumerated()), id: \.offset) { _, l in Text(l).lineLimit(1).truncationMode(.tail) }
        }
        .font(.system(size: 10, design: .monospaced)).foregroundStyle(Color(hex: 0xCFF6FF))
        .frame(width: 210, alignment: .leading)
        .padding(7)
        .background(Color(hex: 0x050A16).opacity(0.92), in: RoundedRectangle(cornerRadius: 4))
        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(color.opacity(0.8), lineWidth: 2))
        .shadow(color: color.opacity(0.4), radius: 6)
    }
}
