import SceneKit
import SwiftUI
import UIKit

/// The live city on the home screen: floating islands with neon buildings, conveyors to the Nexus Spire, your agents
/// standing where the backend says they are, and packages riding the belts. Drag to move around, pinch to zoom, tap a
/// building to see what's running there or an agent to see what they're doing. Play happens in the City tab.
struct LiveCityView: View {
    @Environment(AppState.self) private var app
    @State private var city = CityScene()
    @State private var selection: CitySelection?
    @State private var focus = 0
    @State private var listMode = UserDefaults.standard.bool(forKey: "cityList")  // -cityList YES opens the list view
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.accessibilityVoiceOverEnabled) private var voiceOver

    var body: some View {
        let districts = app.districts.isEmpty ? Roster.districts : app.districts
        ZStack(alignment: .top) {
            if voiceOver || listMode {
                // the same city as a list: every building and agent, each opening the same sheet as a tap in 3D
                AccessibleCityList(districts: districts) { selection = $0 }
                    .padding(.top, 46).padding(.bottom, 58)
            }
            CitySceneView(city: city) { selection = $0 }
                .opacity(voiceOver || listMode ? 0 : 1)
                .allowsHitTesting(!(voiceOver || listMode))
                .accessibilityHidden(true)
                .onAppear { city.reduceMotion = reduceMotion; sync(districts) }
                .onChange(of: reduceMotion) { city.reduceMotion = reduceMotion }
                .onChange(of: app.agents) { sync(districts) }
                .onChange(of: app.packages) { sync(districts) }
                .onChange(of: app.districts) { sync(districts) }
                .task(id: app.connection == .live) { await loadFlows() }
            HStack {
                PixelHeader(text: "The city")
                Spacer()
                Button { listMode.toggle() } label: { Image(systemName: listMode ? "cube" : "list.bullet") }
                    .buttonStyle(CityChip())
                    .accessibilityLabel(listMode ? "Show the 3D city" : "Show the city as a list")
                    .opacity(voiceOver ? 0 : 1)
                Text(app.connection == .live ? (app.executionMode == "simulation" ? "LIVE · SIMULATION" : "LIVE") : "OFFLINE")
                    .font(Pixel.title(10)).padding(.horizontal, 8).padding(.vertical, 4)
                    .background(app.connection == .live ? Theme.ok : Theme.warn, in: Capsule()).foregroundStyle(Theme.ground)
            }
            .padding(10)
            VStack {
                Spacer()
                HStack(spacing: 8) {
                    Button { step(-1, districts) } label: { Image(systemName: "chevron.left") }.buttonStyle(CityChip())
                        .accessibilityLabel("Previous building")
                    if !districts.isEmpty {
                        let d = districts[focus % districts.count]
                        Button { city.fly(to: d.id); selection = .district(d) } label: { Text(d.name).lineLimit(1) }.buttonStyle(CityChip())
                    }
                    Button { step(1, districts) } label: { Image(systemName: "chevron.right") }.buttonStyle(CityChip())
                        .accessibilityLabel("Next building")
                    Spacer()
                    Button { app.openTab = "city" } label: { Label("Enter", systemImage: "gamecontroller.fill") }
                        .buttonStyle(CityChip(fill: GameStyle.go, ink: GameStyle.ink))
                        .accessibilityLabel("Enter the city game")
                        .accessibilityHint("Opens the City tab, where you walk around and talk to agents")
                }
                .padding(10)
            }
        }
        .frame(height: 440)
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .sheet(item: $selection) { s in
            switch s {
            case .district(let d): DistrictActivitySheet(district: d).presentationDetents([.medium, .large])
            case .agent(let id): AgentStatusSheet(agentId: id).presentationDetents([.medium, .large])
            }
        }
    }

    private func sync(_ districts: [District]) {
        let agents = app.agents.isEmpty ? Roster.bundled : Array(app.agents.values)
        city.sync(districts: districts, agents: agents, live: !app.agents.isEmpty, packages: app.packages, serverOffset: app.serverOffset)
    }

    /// Who sends whom work (GET /api/insights/collaboration), drawn as glowing arcs; refreshed every minute while live.
    private func loadFlows() async {
        while !Task.isCancelled {
            if app.connection == .live, let api = app.api, let net = try? await api.json("/api/insights/collaboration?days=7") {
                let flows = (net.get("flows")?.list ?? []).prefix(12).map {
                    CityFlow(from: $0.s("from"), to: $0.s("to"), weight: $0.get("weight")?.int ?? 1)
                }
                city.setFlows(Array(flows))
            } else if app.connection != .live {
                city.setFlows([])
            }
            try? await Task.sleep(for: .seconds(60))
        }
    }

    private func step(_ d: Int, _ districts: [District]) {
        guard !districts.isEmpty else { return }
        focus = (focus + d + districts.count) % districts.count
        city.fly(to: districts[focus].id)
    }
}

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
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

struct CitySceneView: UIViewRepresentable {
    let city: CityScene
    let onSelect: (CitySelection) -> Void

    func makeUIView(context: Context) -> SCNView {
        let v = SCNView()
        v.scene = city.scene
        v.pointOfView = city.camera
        v.backgroundColor = .clear
        v.antialiasingMode = .multisampling4X
        v.preferredFramesPerSecond = 30
        v.rendersContinuously = true
        v.allowsCameraControl = false
        let pan = UIPanGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.pan(_:)))
        let pinch = UIPinchGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.pinch(_:)))
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.tap(_:)))
        for g in [pan, pinch, tap] as [UIGestureRecognizer] { v.addGestureRecognizer(g) }
        context.coordinator.view = v
        return v
    }

    func updateUIView(_ v: SCNView, context: Context) { context.coordinator.onSelect = onSelect }

    func makeCoordinator() -> Coordinator { Coordinator(city: city, onSelect: onSelect) }

    final class Coordinator: NSObject {
        let city: CityScene
        var onSelect: (CitySelection) -> Void
        weak var view: SCNView?
        private var lastPan = CGPoint.zero
        private var startScale: Double = 0

        init(city: CityScene, onSelect: @escaping (CitySelection) -> Void) { self.city = city; self.onSelect = onSelect }

        @objc func pan(_ g: UIPanGestureRecognizer) {
            guard let v = view else { return }
            let t = g.translation(in: v)
            if g.state == .began { lastPan = .zero }
            city.pan(dx: Double(t.x - lastPan.x), dy: Double(t.y - lastPan.y), viewHeight: Double(v.bounds.height))
            lastPan = t
        }

        @objc func pinch(_ g: UIPinchGestureRecognizer) {
            if g.state == .began { startScale = city.zoom }
            city.zoom = min(95, max(18, startScale / Double(g.scale)))
        }

        @objc func tap(_ g: UITapGestureRecognizer) {
            guard let v = view else { return }
            let hits = v.hitTest(g.location(in: v), options: [.searchMode: SCNHitTestSearchMode.all.rawValue, .ignoreHiddenNodes: true])
            var district: String?
            for h in hits {
                var n: SCNNode? = h.node
                while let node = n {
                    if let name = node.name, name.hasPrefix("agent:") { onSelect(.agent(String(name.dropFirst(6)))); return }
                    if district == nil, let name = node.name, name.hasPrefix("district:") { district = String(name.dropFirst(9)) }
                    n = node.parent
                }
            }
            if let id = district, let d = city.district(id) {
                city.fly(to: id)
                onSelect(.district(d))
            }
        }
    }
}

// MARK: - the scene

final class CityScene {
    let scene = SCNScene()
    let camera = SCNNode()
    private let rig = SCNNode()
    private var districtNodes: [String: SCNNode] = [:]
    private var districts: [String: District] = [:]
    private var agentNodes: [String: SCNNode] = [:]
    private var packageNodes: [String: SCNNode] = [:]
    private var packages: [TownPackage] = []
    private var serverOffset: TimeInterval = 0
    private var timer: Timer?
    private var phase: Double = 0
    private var builtFor: [String] = []
    /// Reduce Motion: the belts, beads, bobbing and spinning stay still, and the camera jumps instead of flying.
    var reduceMotion = false {
        didSet { scene.rootNode.enumerateChildNodes { n, _ in if n.name == "spin" { n.isPaused = reduceMotion } } }
    }
    private var agentStates: [String: String] = [:]
    private var flowNodes: [SCNNode] = []
    private var flowKey = ""
    private var pulses: [(node: SCNNode, points: [SCNVector3], speed: Double)] = []
    private var belts: [(node: SCNNode, scale: Float)] = []

    var zoom: Double {
        get { camera.camera?.orthographicScale ?? 55 }
        set { camera.camera?.orthographicScale = newValue }
    }

    init() {
        scene.background.contents = Self.sky()
        let cam = SCNCamera()
        cam.usesOrthographicProjection = true
        cam.orthographicScale = 58
        cam.zNear = 1
        cam.zFar = 1000
        camera.camera = cam
        camera.position = SCNVector3(110, 120, 110)
        camera.constraints = [SCNLookAtConstraint(target: rig)]
        scene.rootNode.addChildNode(rig)
        rig.addChildNode(camera)
        rig.position = SCNVector3(0, 0, 6)

        let ambient = SCNNode()
        ambient.light = SCNLight()
        ambient.light?.type = .ambient
        ambient.light?.color = UIColor(red: 0.62, green: 0.58, blue: 0.85, alpha: 1)
        scene.rootNode.addChildNode(ambient)
        let sun = SCNNode()
        sun.light = SCNLight()
        sun.light?.type = .directional
        sun.light?.intensity = 650
        sun.eulerAngles = SCNVector3(-0.9, 0.6, 0)
        scene.rootNode.addChildNode(sun)
        buildSkyline()

        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 15, repeats: true) { [weak self] _ in self?.tick() }
    }

    deinit { timer?.invalidate() }

    func district(_ id: String) -> District? { districts[id] }

    func pan(dx: Double, dy: Double, viewHeight: Double) {
        let k = 2 * zoom / max(1, viewHeight)
        let r = (x: 0.7071, z: -0.7071), u = (x: -0.7071, z: -0.7071)
        var p = rig.position
        p.x += Float(-r.x * dx * k + u.x * dy * k / 0.62)
        p.z += Float(-r.z * dx * k + u.z * dy * k / 0.62)
        p.x = max(-90, min(90, p.x)); p.z = max(-80, min(90, p.z))
        rig.position = p
    }

    func fly(to id: String) {
        guard let n = districtNodes[id] else { return }
        SCNTransaction.begin()
        SCNTransaction.animationDuration = reduceMotion ? 0 : 0.6
        SCNTransaction.animationTimingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        rig.position = SCNVector3(n.position.x, 0, n.position.z)
        if zoom > 40 { zoom = 34 }
        SCNTransaction.commit()
    }

    // MARK: sync with the backend

    func sync(districts list: [District], agents: [Agent], live: Bool, packages: [TownPackage], serverOffset: TimeInterval) {
        let ids = list.map(\.id).sorted()
        if ids != builtFor { build(list); builtFor = ids }
        self.packages = packages
        self.serverOffset = serverOffset

        let byDistrict = Dictionary(grouping: agents) { live ? ($0.district ?? $0.homeDistrict) : $0.homeDistrict }
        var seen = Set<String>()
        for (did, group) in byDistrict {
            guard let d = districts[did] else { continue }
            let sorted = group.sorted { $0.name < $1.name }
            for (i, a) in sorted.enumerated() {
                seen.insert(a.id)
                let angle = Double.pi / 4 + (Double(i) - Double(sorted.count - 1) / 2) * 0.42
                let radius = Self.islandRadius(d) * 0.66
                let target = SCNVector3(Float(d.x + cos(angle) * radius), 0.7, Float(d.z + sin(angle) * radius))
                let state = live ? a.executionState : "IDLE"
                if let n = agentNodes[a.id] {
                    if n.position.distance(to: target) > 0.5 { n.runAction(.move(to: target, duration: 1.4)) }
                    update(agent: n, a, state: state)
                } else {
                    let n = makeAgent(a)
                    n.position = target
                    scene.rootNode.addChildNode(n)
                    agentNodes[a.id] = n
                    update(agent: n, a, state: state)
                }
            }
        }
        for (id, n) in agentNodes where !seen.contains(id) { n.removeFromParentNode(); agentNodes[id] = nil }
    }

    // MARK: building the city

    private func build(_ list: [District]) {
        districtNodes.values.forEach { $0.removeFromParentNode() }
        districtNodes = [:]
        districts = Dictionary(uniqueKeysWithValues: list.map { ($0.id, $0) })
        belts.forEach { $0.node.removeFromParentNode() }
        belts = []
        for d in list {
            let root = SCNNode()
            root.name = "district:\(d.id)"
            root.position = SCNVector3(Float(d.x), 0, Float(d.z))
            buildIsland(root, d)
            buildBuilding(root, d)
            let top = Self.buildingHeight(d) + 6
            let label = Self.labelNode(d.name, color: Self.color(d), width: 15)
            label.position = SCNVector3(0, Float(top), 0)
            root.addChildNode(label)
            scene.rootNode.addChildNode(root)
            districtNodes[d.id] = root
        }
        // conveyors: every district to the Nexus Spire
        if let hub = list.first(where: { $0.id == "nexus-spire" }) {
            for d in list where d.id != hub.id {
                let belt = Self.belt(from: SCNVector3(Float(hub.x), 0, Float(hub.z)), to: SCNVector3(Float(d.x), 0, Float(d.z)),
                                     trim: Self.islandRadius(hub) * 0.8, trimEnd: Self.islandRadius(d) * 0.8)
                belt.name = "belt"
                scene.rootNode.addChildNode(belt)
                belts.append((belt, Float((belt.geometry as? SCNBox)?.width ?? 6) / 6))
            }
        }
    }

    static func islandRadius(_ d: District) -> Double { d.architecture == "bank" ? 15 : d.architecture == "spire" ? 12 : 13 }

    static func buildingHeight(_ d: District) -> Double {
        switch d.architecture {
        case "spire": return 30
        case "tower": return 36
        case "bank": return 30
        case "twisted": return 18
        case "dome": return 12
        case "factory": return 9
        default: return 15
        }
    }

    static func color(_ d: District) -> UIColor { UIColor(Pixel.districtColor[d.id] ?? Color(hexString: d.color)) }

    private func buildIsland(_ root: SCNNode, _ d: District) {
        let r = CGFloat(Self.islandRadius(d))
        let grass = SCNCylinder(radius: r, height: 1.2)
        grass.radialSegmentCount = 9
        grass.firstMaterial = Self.flat(UIColor(red: 0.30, green: 0.62, blue: 0.40, alpha: 1))
        let g = SCNNode(geometry: grass)
        g.position.y = -0.6
        root.addChildNode(g)
        let rock = SCNCone(topRadius: r * 0.98, bottomRadius: 1.2, height: r * 0.95)
        rock.radialSegmentCount = 9
        rock.firstMaterial = Self.flat(UIColor(red: 0.33, green: 0.27, blue: 0.43, alpha: 1))
        let rn = SCNNode(geometry: rock)
        rn.position.y = Float(-1.2 - r * 0.475)
        root.addChildNode(rn)
        // neon deck ring and plaza
        let ring = SCNTube(innerRadius: r * 0.86, outerRadius: r * 0.9, height: 0.12)
        ring.radialSegmentCount = 9
        ring.firstMaterial = Self.glow(Self.color(d))
        let rg = SCNNode(geometry: ring)
        rg.position.y = 0.08
        root.addChildNode(rg)
        let plaza = SCNCylinder(radius: r * 0.55, height: 0.1)
        plaza.radialSegmentCount = 9
        plaza.firstMaterial = Self.flat(UIColor(red: 0.58, green: 0.58, blue: 0.62, alpha: 1))
        let pn = SCNNode(geometry: plaza)
        pn.position.y = 0.05
        root.addChildNode(pn)
        // a few trees (pink blossoms and green)
        var rnd = TownRandom(UInt32(d.id.unicodeScalars.reduce(UInt32(7)) { ($0 &* 31 &+ $1.value) % 1_000_003 }))
        for i in 0..<5 {
            let a = Double(i) * 1.3 + rnd.next() * 0.5, rad = Double(r) * (0.62 + rnd.next() * 0.22)
            let pink = rnd.next() < 0.45
            let crown = SCNSphere(radius: 1.1)
            crown.segmentCount = 6
            crown.firstMaterial = Self.flat(pink ? UIColor(red: 0.92, green: 0.45, blue: 0.68, alpha: 1) : UIColor(red: 0.2, green: 0.5, blue: 0.32, alpha: 1))
            let t = SCNNode(geometry: crown)
            t.position = SCNVector3(Float(cos(a) * rad), 1.9, Float(sin(a) * rad))
            let trunk = SCNNode(geometry: SCNBox(width: 0.3, height: 1.3, length: 0.3, chamferRadius: 0))
            trunk.geometry?.firstMaterial = Self.flat(UIColor(red: 0.35, green: 0.22, blue: 0.16, alpha: 1))
            trunk.position = SCNVector3(t.position.x, 0.7, t.position.z)
            root.addChildNode(trunk)
            root.addChildNode(t)
        }
    }

    private func box(_ root: SCNNode, _ w: Double, _ h: Double, _ l: Double, at p: SCNVector3, color: UIColor, rotate: Double = 0) {
        let b = SCNBox(width: CGFloat(w), height: CGFloat(h), length: CGFloat(l), chamferRadius: 0)
        b.firstMaterial = Self.neon(color)
        let n = SCNNode(geometry: b)
        n.position = SCNVector3(p.x, p.y + Float(h / 2), p.z)
        n.eulerAngles.y = Float(rotate)
        root.addChildNode(n)
    }

    private func buildBuilding(_ root: SCNNode, _ d: District) {
        let c = Self.color(d)
        let h = Self.buildingHeight(d)
        switch d.architecture {
        case "spire":
            box(root, 6, h, 6, at: SCNVector3(0, 0, 0), color: c)
            box(root, 9, 3, 9, at: SCNVector3(0, 0, 0), color: c)
            let crystal = SCNPyramid(width: 4, height: 6, length: 4)
            crystal.firstMaterial = Self.glow(UIColor.white.withAlphaComponent(0.9))
            let cn = SCNNode(geometry: crystal)
            cn.position = SCNVector3(0, Float(h + 1), 0)
            cn.name = "spin"
            cn.runAction(.repeatForever(.rotateBy(x: 0, y: .pi * 2, z: 0, duration: 12)))
            cn.isPaused = reduceMotion
            root.addChildNode(cn)
        case "tower":
            box(root, 5, h, 5, at: SCNVector3(0, 0, 0), color: c)
            box(root, 7, 2, 7, at: SCNVector3(0, Float(h * 0.4), 0), color: c)
        case "blocks":
            let blocks: [[Double]] = [[-3, -2, 4, 15], [2.5, -2.5, 4.5, 11], [-2, 3, 4, 9], [3, 2.5, 3.5, 13]]
            for b in blocks { box(root, b[2], b[3], b[2], at: SCNVector3(Float(b[0]), 0, Float(b[1])), color: c) }
        case "fortress":
            box(root, 11, 9, 9, at: SCNVector3(0, 0, 0), color: c)
            for p in [[-5.5, -4.5], [5.5, -4.5], [-5.5, 4.5], [5.5, 4.5]] { box(root, 2.5, 13, 2.5, at: SCNVector3(Float(p[0]), 0, Float(p[1])), color: c) }
        case "twisted":
            for i in 0..<6 { box(root, 6, 3, 6, at: SCNVector3(0, Float(i) * 3, 0), color: c, rotate: Double(i) * 0.22) }
        case "dome":
            box(root, 10, 4, 10, at: SCNVector3(0, 0, 0), color: c)
            let dome = SCNSphere(radius: 5)
            dome.segmentCount = 16
            dome.firstMaterial = Self.neon(c)
            let dn = SCNNode(geometry: dome)
            dn.position.y = 4
            root.addChildNode(dn)
        case "vault":
            box(root, 10, 8, 10, at: SCNVector3(0, 0, 0), color: c)
            box(root, 6, 4, 6, at: SCNVector3(0, 8, 0), color: c)
        case "bank":
            box(root, 9, h, 9, at: SCNVector3(0, 0, 0), color: c)
            box(root, 13, 6, 12, at: SCNVector3(0, 0, 0), color: c)
        case "factory":
            box(root, 14, 6, 10, at: SCNVector3(0, 0, 0), color: c)
            for i in 0..<4 { box(root, 3.2, 2.5, 10, at: SCNVector3(Float(-5 + i * 3), 6, 0), color: c, rotate: 0) }
            box(root, 1.5, 10, 1.5, at: SCNVector3(5, 0, -3.5), color: c)
        default:
            box(root, 8, h, 8, at: SCNVector3(0, 0, 0), color: c)
        }
    }

    private func buildSkyline() {
        var rnd = TownRandom(42)
        for i in 0..<34 {
            let w = 5 + rnd.next() * 7, h = 25 + rnd.next() * 60
            let x = -150 + Double(i) * 9 + rnd.next() * 4
            let z = -130 - rnd.next() * 40
            let b = SCNBox(width: CGFloat(w), height: CGFloat(h), length: CGFloat(w), chamferRadius: 0)
            b.firstMaterial = Self.windows(rnd.next() < 0.5 ? UIColor(red: 0.95, green: 0.55, blue: 0.85, alpha: 1) : UIColor(red: 0.55, green: 0.75, blue: 1, alpha: 1))
            let n = SCNNode(geometry: b)
            n.position = SCNVector3(Float(x + z * 0.4), Float(h / 2 - 30), Float(z - x * 0.3))
            scene.rootNode.addChildNode(n)
        }
    }

    // MARK: agents and packages

    private func makeAgent(_ a: Agent) -> SCNNode {
        let n = SCNNode()
        n.name = "agent:\(a.id)"
        let body = SCNNode(geometry: SCNPlane(width: 3.2, height: 4.8))
        body.name = "body"
        body.position.y = 2.4
        let b = SCNBillboardConstraint()
        b.freeAxes = .Y
        body.constraints = [b]
        n.addChildNode(body)
        let label = Self.labelNode(a.name, color: UIColor(white: 1, alpha: 0.25), width: 5.5, small: true)
        label.position.y = 6
        n.addChildNode(label)
        let dot = SCNNode(geometry: SCNSphere(radius: 0.45))
        dot.name = "status"
        dot.position.y = 7.6
        n.addChildNode(dot)
        return n
    }

    private func update(agent n: SCNNode, _ a: Agent, state: String) {
        let working = ["EXECUTING", "ASSIGNED", "PLANNING", "REVIEWING", "WAITING_FOR_TOOL"].contains(state)
        let outfit = a.avatar.look.map { PixelSprites.outfit($0) } ?? PixelSprites.outfit(PlayerLook(shirt: a.avatar.color))
        let frame = working ? Int(phase * 3) % 2 : 0
        if let body = n.childNode(withName: "body", recursively: false), let img = PixelSprites.image(outfit, .down, working ? .work : .stand, frame) {
            let m = body.geometry?.firstMaterial ?? SCNMaterial()
            m.diffuse.contents = img
            m.diffuse.magnificationFilter = .nearest
            m.lightingModel = .constant
            m.isDoubleSided = true
            m.transparencyMode = .aOne
            body.geometry?.firstMaterial = m
        }
        let dot = n.childNode(withName: "status", recursively: false)
        var c: UIColor?
        if state == "FAILED" { c = UIColor(Theme.bad) } else if state.hasPrefix("WAITING") { c = UIColor(Theme.warn) }
        else if working { c = UIColor(Theme.ok) } else if state == "COMPLETED" { c = UIColor(Theme.gold) }
        dot?.isHidden = c == nil
        if let c { dot?.geometry?.firstMaterial = Self.glow(c) }
        if let id = n.name { agentStates[id] = state }
    }

    /// Arcs between districts that sent each other work this week: thicker and brighter for more traffic.
    func setFlows(_ flows: [CityFlow]) {
        let key = flows.map { "\($0.from)>\($0.to):\($0.weight)" }.joined(separator: ",")
        guard key != flowKey else { return }
        flowKey = key
        flowNodes.forEach { $0.removeFromParentNode() }
        flowNodes = []
        pulses = []
        let top = Double(flows.map(\.weight).max() ?? 1)
        for f in flows {
            guard let a = districts[f.from], let b = districts[f.to] else { continue }
            let strength = max(0.25, Double(f.weight) / top)
            let p0 = SCNVector3(Float(a.x), Float(Self.buildingHeight(a) * 0.6), Float(a.z))
            let p2 = SCNVector3(Float(b.x), Float(Self.buildingHeight(b) * 0.6), Float(b.z))
            let span = Float(hypot(b.x - a.x, b.z - a.z))
            let midX: Float = (p0.x + p2.x) / 2
            let midZ: Float = (p0.z + p2.z) / 2
            let lift: Float = max(p0.y, p2.y) + span * 0.35
            let p1 = SCNVector3(midX, lift, midZ)
            let pts = (0...16).map { i in Self.bezier(p0, p1, p2, Float(i) / 16) }
            let arc = SCNNode()
            arc.name = "flow"
            let color = Self.color(a).withAlphaComponent(CGFloat(0.35 + 0.5 * strength))
            for i in 0..<(pts.count - 1) {
                arc.addChildNode(Self.segment(pts[i], pts[i + 1], radius: CGFloat(0.12 + 0.28 * strength), color: color))
            }
            scene.rootNode.addChildNode(arc)
            flowNodes.append(arc)
            let dot = SCNNode(geometry: SCNSphere(radius: CGFloat(0.5 + 0.4 * strength)))
            dot.geometry?.firstMaterial = Self.glow(Self.color(a))
            scene.rootNode.addChildNode(dot)
            flowNodes.append(dot)
            pulses.append((dot, pts, 0.15 + 0.25 * strength))
        }
    }

    /// A point on the quadratic curve p0 → p2 bent toward p1.
    static func bezier(_ p0: SCNVector3, _ p1: SCNVector3, _ p2: SCNVector3, _ t: Float) -> SCNVector3 {
        let u: Float = 1 - t
        let a: Float = u * u
        let b: Float = 2 * u * t
        let c: Float = t * t
        let x: Float = a * p0.x + b * p1.x + c * p2.x
        let y: Float = a * p0.y + b * p1.y + c * p2.y
        let z: Float = a * p0.z + b * p1.z + c * p2.z
        return SCNVector3(x, y, z)
    }

    static func segment(_ a: SCNVector3, _ b: SCNVector3, radius: CGFloat, color: UIColor) -> SCNNode {
        let d = SCNVector3(b.x - a.x, b.y - a.y, b.z - a.z)
        let sq: Float = d.x * d.x + d.y * d.y + d.z * d.z
        let len = CGFloat(sqrtf(sq))
        let c = SCNCylinder(radius: radius, height: len)
        c.radialSegmentCount = 6
        let m = glow(color)
        m.transparencyMode = .aOne
        m.blendMode = .add
        c.firstMaterial = m
        let n = SCNNode(geometry: c)
        let mx: Float = (a.x + b.x) / 2
        let my: Float = (a.y + b.y) / 2
        let mz: Float = (a.z + b.z) / 2
        n.position = SCNVector3(mx, my, mz)
        n.look(at: b, up: SCNVector3(0, 1, 0), localFront: SCNVector3(0, 1, 0))
        return n
    }

    private func tick() {
        phase += 1.0 / 15
        for p in pulses {  // a bead of light travels each arc, from sender to receiver (parked mid-arc with Reduce Motion)
            let f = reduceMotion ? Double(p.points.count - 1) / 2 : (phase * p.speed).truncatingRemainder(dividingBy: 1) * Double(p.points.count - 1)
            let i = min(p.points.count - 2, Int(f)), t = Float(f - Double(i))
            let a = p.points[i], b = p.points[i + 1]
            let x: Float = a.x + (b.x - a.x) * t
            let y: Float = a.y + (b.y - a.y) * t
            let z: Float = a.z + (b.z - a.z) * t
            p.node.position = SCNVector3(x, y, z)
        }
        for b in belts where !reduceMotion {
            guard let m = b.node.geometry?.firstMaterial else { continue }
            let t = SCNMatrix4Translate(SCNMatrix4MakeScale(b.scale, 1, 1), Float(-phase * 0.8), 0, 0)
            m.diffuse.contentsTransform = t
            m.emission.contentsTransform = t
        }
        // animate working agents
        if Int(phase * 15) % 5 == 0 {
            for (_, n) in agentNodes {
                guard let state = agentStates[n.name ?? ""], ["EXECUTING", "PLANNING", "REVIEWING"].contains(state),
                      let body = n.childNode(withName: "body", recursively: false) else { continue }
                body.position.y = reduceMotion ? 2.4 : 2.4 + Float(sin(phase * 6)) * 0.12
            }
        }
        // packages along the belts: origin → Nexus Spire → destination, by the server's route clock
        let now = Date().addingTimeInterval(serverOffset)
        var seen = Set<String>()
        for p in packages where ["QUEUED", "IN_TRANSIT", "ARRIVED", "DELIVERY_FAILED"].contains(p.status) {
            guard let o = districts[p.origin] ?? districts["nexus-spire"], let dst = districts[p.destination] ?? districts["nexus-spire"] else { continue }
            seen.insert(p.id)
            var t = 0.0
            if p.status == "ARRIVED" { t = 1 } else if p.status == "IN_TRANSIT", let s = p.routeStartedAt, let e = p.eta, e > s {
                t = min(1, max(0, now.timeIntervalSince(s) / e.timeIntervalSince(s)))
            }
            let pts = [(o.x, o.z), (0.0, 0.0), (dst.x, dst.z)]
            let seg = t < 0.5 ? 0 : 1, f = t < 0.5 ? t * 2 : (t - 0.5) * 2
            let a = pts[seg], b = pts[seg + 1]
            let pos = SCNVector3(Float(a.0 + (b.0 - a.0) * f), 1.3, Float(a.1 + (b.1 - a.1) * f))
            let n = packageNodes[p.id] ?? {
                let box = SCNBox(width: 1.6, height: 1.6, length: 1.6, chamferRadius: 0.2)
                box.firstMaterial = Self.glow(UIColor(Color(hexString: PixelArt.packageColor[p.type] ?? "#F4D58D")))
                let n = SCNNode(geometry: box)
                n.name = "package"
                scene.rootNode.addChildNode(n)
                packageNodes[p.id] = n
                return n
            }()
            n.position = pos
            n.eulerAngles.y = Float(phase)
        }
        for (id, n) in packageNodes where !seen.contains(id) { n.removeFromParentNode(); packageNodes[id] = nil }
    }

    // MARK: materials and pieces

    static func flat(_ c: UIColor) -> SCNMaterial {
        let m = SCNMaterial()
        m.diffuse.contents = c
        m.lightingModel = .lambert
        return m
    }

    static func glow(_ c: UIColor) -> SCNMaterial {
        let m = SCNMaterial()
        m.diffuse.contents = c
        m.emission.contents = c
        m.lightingModel = .constant
        return m
    }

    private static var neonCache: [String: UIImage] = [:]

    /// Dark faces with glowing edges and a few lit windows: the city's neon look.
    static func neon(_ c: UIColor) -> SCNMaterial {
        let key = c.description
        let img = neonCache[key] ?? {
            let size = CGSize(width: 64, height: 64)
            let img = UIGraphicsImageRenderer(size: size).image { ctx in
                UIColor(red: 0.06, green: 0.05, blue: 0.12, alpha: 1).setFill()
                ctx.fill(CGRect(origin: .zero, size: size))
                c.withAlphaComponent(0.55).setFill()
                var r = TownRandom(UInt32(key.unicodeScalars.reduce(UInt32(5)) { ($0 &* 31 &+ $1.value) % 1_000_003 }))
                for y in stride(from: 8, to: 56, by: 8) { for x in stride(from: 8, to: 56, by: 10) where r.next() < 0.35 { ctx.fill(CGRect(x: x, y: y, width: 4, height: 3)) } }
                c.setStroke()
                ctx.cgContext.setLineWidth(5)
                ctx.cgContext.stroke(CGRect(x: 2.5, y: 2.5, width: 59, height: 59))
            }
            neonCache[key] = img
            return img
        }()
        let m = SCNMaterial()
        m.diffuse.contents = img
        m.emission.contents = img
        m.diffuse.magnificationFilter = .nearest
        m.lightingModel = .constant
        return m
    }

    static func windows(_ c: UIColor) -> SCNMaterial {
        let img = UIGraphicsImageRenderer(size: CGSize(width: 32, height: 64)).image { ctx in
            UIColor(red: 0.08, green: 0.07, blue: 0.2, alpha: 1).setFill()
            ctx.fill(CGRect(x: 0, y: 0, width: 32, height: 64))
            var r = TownRandom(9)
            for y in stride(from: 3, to: 62, by: 5) { for x in stride(from: 3, to: 30, by: 6) where r.next() < 0.5 {
                (r.next() < 0.5 ? c : UIColor(red: 1, green: 0.85, blue: 0.5, alpha: 1)).setFill()
                ctx.fill(CGRect(x: x, y: y, width: 3, height: 2))
            } }
        }
        let m = SCNMaterial()
        m.diffuse.contents = img
        m.emission.contents = img
        m.emission.intensity = 0.7
        m.diffuse.magnificationFilter = .nearest
        m.lightingModel = .constant
        return m
    }

    static func belt(from a: SCNVector3, to b: SCNVector3, trim: Double, trimEnd: Double) -> SCNNode {
        let dx = Double(b.x - a.x), dz = Double(b.z - a.z), len = hypot(dx, dz)
        let ux = dx / len, uz = dz / len
        let s = (x: Double(a.x) + ux * trim, z: Double(a.z) + uz * trim)
        let e = (x: Double(b.x) - ux * trimEnd, z: Double(b.z) - uz * trimEnd)
        let l = max(1, hypot(e.x - s.x, e.z - s.z))
        let box = SCNBox(width: CGFloat(l), height: 0.5, length: 2.4, chamferRadius: 0)
        let img = UIGraphicsImageRenderer(size: CGSize(width: 32, height: 8)).image { ctx in
            UIColor(red: 0.13, green: 0.11, blue: 0.2, alpha: 1).setFill(); ctx.fill(CGRect(x: 0, y: 0, width: 32, height: 8))
            UIColor(red: 0.2, green: 0.85, blue: 1, alpha: 0.9).setFill()
            for x in stride(from: 0, to: 32, by: 8) { ctx.fill(CGRect(x: x, y: 2, width: 3, height: 4)) }
        }
        let m = SCNMaterial()
        m.diffuse.contents = img
        m.emission.contents = img
        m.diffuse.wrapS = .repeat
        m.emission.wrapS = .repeat
        m.diffuse.contentsTransform = SCNMatrix4MakeScale(Float(l / 6), 1, 1)
        m.lightingModel = .constant
        box.firstMaterial = m
        let n = SCNNode(geometry: box)
        n.position = SCNVector3(Float((s.x + e.x) / 2), 0.3, Float((s.z + e.z) / 2))
        n.eulerAngles.y = Float(-atan2(e.z - s.z, e.x - s.x))
        return n
    }

    /// A sign that always faces you: dark plate, colored rim, name in caps.
    static func labelNode(_ text: String, color: UIColor, width: CGFloat, small: Bool = false) -> SCNNode {
        let font = UIFont.monospacedSystemFont(ofSize: small ? 30 : 34, weight: .heavy)
        let str = (small ? text : text.uppercased()) as NSString
        let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: UIColor.white]
        let ts = str.size(withAttributes: attrs)
        let size = CGSize(width: ts.width + 44, height: ts.height + 22)
        let img = UIGraphicsImageRenderer(size: size).image { _ in
            let r = CGRect(origin: .zero, size: size).insetBy(dx: 3, dy: 3)
            let p = UIBezierPath(roundedRect: r, cornerRadius: small ? r.height / 2 : 8)
            UIColor(red: 0.05, green: 0.07, blue: 0.15, alpha: 0.9).setFill(); p.fill()
            color.setStroke(); p.lineWidth = small ? 2 : 5; p.stroke()
            str.draw(at: CGPoint(x: 22, y: 11), withAttributes: attrs)
        }
        let aspect = size.height / size.width
        let w = small ? min(width, CGFloat(text.count) * 0.75 + 1.6) : min(width * 1.6, CGFloat(text.count) * 0.85 + 3)
        let plane = SCNPlane(width: w, height: w * aspect)
        let m = SCNMaterial()
        m.diffuse.contents = img
        m.lightingModel = .constant
        m.isDoubleSided = true
        m.readsFromDepthBuffer = false
        plane.firstMaterial = m
        let n = SCNNode(geometry: plane)
        n.renderingOrder = 100
        n.constraints = [SCNBillboardConstraint()]
        return n
    }

    static func sky() -> UIImage {
        UIGraphicsImageRenderer(size: CGSize(width: 4, height: 256)).image { ctx in
            let colors = [UIColor(red: 0.09, green: 0.08, blue: 0.22, alpha: 1).cgColor, UIColor(red: 0.27, green: 0.2, blue: 0.42, alpha: 1).cgColor,
                          UIColor(red: 0.35, green: 0.28, blue: 0.5, alpha: 1).cgColor]
            let g = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors as CFArray, locations: [0, 0.6, 1])!
            ctx.cgContext.drawLinearGradient(g, start: .zero, end: CGPoint(x: 0, y: 256), options: [])
        }
    }
}

private extension SCNVector3 {
    func distance(to o: SCNVector3) -> Float { sqrtf((x - o.x) * (x - o.x) + (y - o.y) * (y - o.y) + (z - o.z) * (z - o.z)) }
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
                            ForEach(recent) { t in Text("\(t.s("title")) · \(t.s("agent")) · \(t.s("status").lowercased())").font(.caption) }
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
                        Section("Recently") { ForEach(Array(done)) { t in Text("\(t.s("title")) · \(t.s("status").lowercased())").font(.caption) } }
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
