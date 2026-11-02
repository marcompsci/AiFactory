import SceneKit
import SwiftUI
import UIKit
import simd

/// The website's camera modes (Frame.tsx CameraChips): City (the overview), Orbit, Follow (an agent) and Fly.
enum CameraMode: String, CaseIterable, Identifiable {
    case overview, orbit, follow, fly
    var id: String { rawValue }
    var label: String {
        switch self {
        case .overview: return "City"
        case .orbit: return "Orbit"
        case .follow: return "Follow"
        case .fly: return "Fly"
        }
    }
}

/// The 3D city, built the way the website builds it (apps/web/components/world): the same camera, sky, skyline,
/// islands, decks, buildings with neon edges, desks, walkways, belts, packages, agents walking their routes, the
/// floating Knowledge Base and the Owner's Tower beacon. The labels, signs and bubbles are SwiftUI views placed over
/// it (CityOverlay), the way the website places HTML over its canvas.
@MainActor
final class CityScene {
    let scene = SCNScene()
    let cameraNode = SCNNode()
    weak var app: AppState?

    // camera (perspective, fov 45, like the website's)
    private(set) var eye = SIMD3<Float>(50, 108, 166)
    private(set) var target = SIMD3<Float>(0, -12, -30)
    private var goal: (eye: SIMD3<Float>, target: SIMD3<Float>)?
    var aspect: Float = 0.46 { didSet { if mode == .overview && abs(aspect - oldValue) > 0.001 { goal = overview() } } }
    var mode: CameraMode = .overview {
        didSet {
            if mode == .overview { goal = overview() }
            if mode != oldValue { onMode?(mode) }
        }
    }
    /// Told when the camera switches mode by itself (dragging the overview starts orbiting).
    var onMode: ((CameraMode) -> Void)?
    var followId: String?
    var reduceMotion = false
    var paused = false

    // what is drawn
    private var districts: [String: District] = [:]
    private var districtList: [District] = []
    private var builtFor: [String] = []
    private var districtRoots: [String: SCNNode] = [:]
    private var pads: [String: SCNNode] = [:]
    private var padLevel: [String: Double] = [:]
    private var seenActivity: [String: Double] = [:]
    private var deskTops: [String: (top: SCNNode, beam: SCNNode, color: UIColor)] = [:]
    private var bankFloors: [(id: String, node: SCNNode, color: UIColor)] = []
    private var beacon: SCNNode?
    private var plazaRing: SCNNode?
    private var belts: [String: (rails: [SCNNode], slats: SCNNode, length: Float)] = [:]
    private var beltGraphKey = ""
    private var segIndex: [String: (from: SIMD3<Float>, to: SIMD3<Float>, length: Float)] = [:]
    private var beltRoot = SCNNode()
    private var packageNodes: [String: SCNNode] = [:]
    private var agentNodes: [String: SCNNode] = [:]
    private var walks: [String: (route: [WorldMap.V3], start: Date, length: Double, key: String)] = [:]
    private var kb = SCNNode()
    private var kbRing = SCNNode()
    private var kbTiles = 0
    private var falls: [SCNMaterial] = []
    private var islets: [(node: SCNNode, y: Float)] = []
    private var cars: [(node: SCNNode, r: Float, h: Float, speed: Float, phase: Float, dir: Float)] = []
    private var groundCars: [(node: SCNNode, r: Float, speed: Float, phase: Float)] = []
    private var drones: [(node: SCNNode, center: SIMD3<Float>, r: Float, speed: Float, phase: Float)] = []
    private var blinks: [SCNNode] = []
    private var clouds: [SCNNode] = []
    private var globe: SCNNode?
    private var sun = SCNNode()
    /// High: full resolution, soft shadows, ambient occlusion and particles. Low (set when the phone runs hot, or
    /// with -cityQuality low): no shadows, occlusion or particles.
    private(set) var lowQuality = UserDefaults.standard.string(forKey: "cityQuality") == "low"
    private var phase: Double = 0
    private var last = Date()
    nonisolated(unsafe) private var timer: Timer?

    /// Where the SwiftUI overlay pins its signs, name tags, bubbles and boards (id → node).
    private(set) var anchors: [String: SCNNode] = [:]

    init() {
        scene.background.contents = Self.sky
        scene.lightingEnvironment.contents = Self.sky   // glass and metal reflect the dusk sky
        scene.lightingEnvironment.intensity = 1.1
        scene.fogColor = UIColor(hex: 0x2A1E4A)          // haze: far islands and the skyline fade into the dusk
        scene.fogStartDistance = 480
        scene.fogEndDistance = 1100
        scene.fogDensityExponent = 1.3
        let cam = SCNCamera()
        cam.fieldOfView = 45
        cam.projectionDirection = .vertical
        cam.zNear = 0.5
        cam.zFar = 1600
        cam.wantsHDR = true
        cam.wantsExposureAdaptation = false
        cam.exposureOffset = -0.15
        cam.bloomIntensity = 0.65
        cam.bloomThreshold = 0.85
        cam.bloomBlurRadius = 10
        cam.vignettingIntensity = 0.35
        cam.vignettingPower = 0.9
        cam.saturation = 1.08
        cam.contrast = 0.06
        cameraNode.camera = cam
        scene.rootNode.addChildNode(cameraNode)
        lights()
        buildSkyline()
        buildIslets()
        buildCars()
        buildDrones()
        buildCloudSea()
        scene.rootNode.addChildNode(beltRoot)
        let motes = SCNNode()
        motes.name = "motes"
        motes.position = SCNVector3(0, 22, 0)
        motes.addParticleSystem(CityArt.motes())
        scene.rootNode.addChildNode(motes)
        applyQuality()
        NotificationCenter.default.addObserver(forName: ProcessInfo.thermalStateDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                let state = ProcessInfo.processInfo.thermalState
                if (state == .serious || state == .critical) && self?.lowQuality == false { self?.setLowQuality(true) }
            }
        }
        let o = overview()
        eye = o.eye
        target = o.target
        placeCamera()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
    }

    deinit { timer?.invalidate() }

    func district(_ id: String) -> District? { districts[id] }

    // MARK: camera

    private func overview() -> (eye: SIMD3<Float>, target: SIMD3<Float>) {
        let k: Float = aspect < 1 ? min(2.1, 1.05 / max(0.2, aspect)) : 1
        return (SIMD3<Float>(50, 108, 166) * k, SIMD3<Float>(0, -12, -30))
    }

    func showOverview() { mode = .overview; goal = overview() }

    /// Fly to a district the way the website does: 30 out from the centre toward the outside, 24 up.
    func focus(_ id: String) {
        guard let d = districts[id] else { return }
        let c = SIMD3<Float>(Float(d.x), 0, Float(d.z))
        var out = SIMD3<Float>(c.x, 0, c.z)
        if simd_length(out) < 0.001 { out = SIMD3<Float>(0, 0, 1) }
        out = simd_normalize(out)
        var e = c + out * 40  // a little further out than the website: the whole district fits a phone screen
        e.y = 30
        goal = (e, SIMD3<Float>(c.x, 4, c.z))
        if mode == .overview { mode = .orbit }
    }

    func follow(_ agentId: String) { followId = agentId; mode = .follow; goal = nil }

    /// One-finger drag: orbit round the target (Fly: move across the screen).
    func drag(dx: Float, dy: Float, height: Float) {
        goal = nil
        if mode == .overview { mode = .orbit }
        if mode == .fly { pan(dx: dx, dy: dy, height: height, screenSpace: true); return }
        var off = eye - target
        let r = simd_length(off)
        var theta = atan2(off.x, off.z)
        var phi = acos(max(-1, min(1, off.y / max(0.001, r))))
        theta -= 2 * .pi * dx / max(1, height)
        phi -= 2 * .pi * dy / max(1, height)
        phi = max(0.05, min(.pi / 2.08, phi))
        off = SIMD3<Float>(r * sin(phi) * sin(theta), r * cos(phi), r * sin(phi) * cos(theta))
        eye = target + off
        placeCamera()
    }

    /// Two-finger drag: move across the ground (Fly: across the screen).
    func pan(dx: Float, dy: Float, height: Float, screenSpace: Bool = false) {
        goal = nil
        if mode == .overview { mode = .orbit }
        let off = eye - target
        let dist = simd_length(off)
        let perPoint = 2 * dist * tan(Float(22.5) * .pi / 180) / max(1, height)
        let fwd = simd_normalize(-off)
        let right = simd_normalize(simd_cross(fwd, SIMD3<Float>(0, 1, 0)))
        var move = -right * dx * perPoint
        if screenSpace || mode == .fly {
            let up = simd_normalize(simd_cross(right, fwd))
            move += up * dy * perPoint
        } else {
            let ground = simd_normalize(SIMD3<Float>(fwd.x, 0, fwd.z))
            move += ground * dy * perPoint
        }
        eye += move
        target += move
        placeCamera()
    }

    func dolly(_ scale: Float, from startDistance: Float) {
        goal = nil
        if mode == .overview { mode = .orbit }
        let off = eye - target
        let d = max(4, min(340, startDistance / max(0.05, scale)))
        eye = target + simd_normalize(off) * d
        placeCamera()
    }

    var distance: Float { simd_length(eye - target) }

    private func placeCamera() {
        cameraNode.simdPosition = eye
        cameraNode.simdLook(at: target, up: SIMD3<Float>(0, 1, 0), localFront: SIMD3<Float>(0, 0, -1))
    }

    private func updateCamera(dt: Float) {
        let k: Float = reduceMotion ? 1 : 1 - pow(0.02, dt)
        if mode == .follow, let id = followId, let n = agentNodes[id] {
            let p = n.simdPosition + SIMD3<Float>(0, 1.5, 0)
            var off = eye - target
            if simd_length(off) > 26 || simd_length(off) < 8 { off = simd_normalize(off) * 16 }
            if off.y < 6 { off.y = 8 }
            target += (p - target) * k
            eye += (p + off - eye) * k
            placeCamera()
        } else if let g = goal {
            eye += (g.eye - eye) * k
            target += (g.target - target) * k
            if simd_distance(eye, g.eye) < 0.3 { goal = nil }
            placeCamera()
        }
    }

    // MARK: building the city

    func sync(districts list: [District]) {
        let ids = list.map(\.id).sorted()
        guard ids != builtFor else { return }
        builtFor = ids
        scene.rootNode.childNode(withName: "city", recursively: false)?.removeFromParentNode()
        beacon = nil
        districtRoots.values.forEach { $0.removeFromParentNode() }
        districtRoots = [:]
        pads = [:]
        deskTops = [:]
        bankFloors = []
        blinks = []
        anchors = anchors.filter { !$0.key.hasPrefix("sign:") && !$0.key.hasPrefix("bubble:") && !$0.key.hasPrefix("board:") }
        districts = Dictionary(list.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        districtList = list
        let root = SCNNode()
        root.name = "city"
        buildPlaza(root)
        for (i, d) in list.enumerated() {
            let dn = SCNNode()
            dn.name = "district:\(d.id)"
            dn.position = SCNVector3(Float(d.x), 0, Float(d.z))
            let toPlaza: Float = d.x == 0 && d.z == 0 ? 0 : Float(atan2(-d.x, -d.z))
            buildIsland(dn, r: WorldMap.islandRadius(d), depth: 16 + Double(i % 3) * 6, seed: Double(i) * 1.7,
                        clear: Float(WorldMap.deckSize(d) / 2), road: toPlaza)
            buildDeck(dn, d)
            buildDistrict(dn, d)
            root.addChildNode(dn)
            districtRoots[d.id] = dn
            buildWalkway(root, d)
            anchor("sign:\(d.id)", in: dn, at: SCNVector3(0, Float(WorldMap.signHeight(d)), -1))
            anchor("bubble:\(d.id)", in: dn, at: SCNVector3(3, Float(min((d.height ?? 16) * 0.45 + 3, 11)), 6))
            if d.architecture == "factory" {
                anchor("board:\(d.id)", in: dn, at: SCNVector3(d.x < 0 ? 7 : d.x > 0 ? -7 : 9, 21, -3))
            }
        }
        buildWaterfalls(root, list)
        buildHub(root)
        buildKnowledgeBase(root)
        scene.rootNode.addChildNode(root)
        beltGraphKey = ""
        setKnowledge(skills: knowledgeCounts.skills, docs: knowledgeCounts.docs)
    }

    private func anchor(_ id: String, in parent: SCNNode, at p: SCNVector3) {
        let n = SCNNode()
        n.position = p
        parent.addChildNode(n)
        anchors[id] = n
    }

    /// A low warm sun from the far side (soft shadows), a cool sky fill, a violet rim, and the sky itself for
    /// reflections (scene.lightingEnvironment).
    private func lights() {
        let l = SCNLight()
        l.type = .directional
        l.color = UIColor(hex: 0xFFD2A0)
        l.intensity = 1900
        l.castsShadow = true
        l.shadowMode = .deferred
        l.shadowSampleCount = 8
        l.shadowRadius = 3.5
        l.shadowMapSize = CGSize(width: 2048, height: 2048)
        l.shadowColor = UIColor(white: 0, alpha: 0.5)
        l.automaticallyAdjustsShadowProjection = false
        l.orthographicScale = 130
        l.zNear = 10
        l.zFar = 520
        sun.light = l
        sun.simdPosition = SIMD3<Float>(-120, 150, -170)
        sun.simdLook(at: SIMD3<Float>(0, 0, 10), up: SIMD3<Float>(0, 1, 0), localFront: SIMD3<Float>(0, 0, -1))
        scene.rootNode.addChildNode(sun)
        func add(_ type: SCNLight.LightType, _ color: UInt32, _ intensity: CGFloat, from p: SIMD3<Float>? = nil) {
            let n = SCNNode()
            n.light = SCNLight()
            n.light?.type = type
            n.light?.color = UIColor(hex: color)
            n.light?.intensity = intensity
            if let p {
                n.simdPosition = p
                n.simdLook(at: .zero, up: SIMD3<Float>(0, 1, 0), localFront: SIMD3<Float>(0, 0, -1))
            }
            scene.rootNode.addChildNode(n)
        }
        add(.ambient, 0x6F78B8, 260)
        add(.directional, 0x7FB8FF, 520, from: SIMD3<Float>(60, 90, 140))   // cool fill from the camera's side
        add(.directional, 0xA66BFF, 420, from: SIMD3<Float>(-80, 30, 60))   // violet rim
    }

    func setLowQuality(_ low: Bool) {
        lowQuality = low
        applyQuality()
    }

    private func applyQuality() {
        sun.light?.castsShadow = !lowQuality
        cameraNode.camera?.screenSpaceAmbientOcclusionIntensity = lowQuality ? 0 : 0.8
        cameraNode.camera?.screenSpaceAmbientOcclusionRadius = 2.5
        cameraNode.camera?.screenSpaceAmbientOcclusionBias = 0.05
        scene.rootNode.childNode(withName: "motes", recursively: false)?.isHidden = lowQuality
        for d in drones { d.node.isHidden = lowQuality }
    }

    /// The plaza: pale stone in the middle with the monument and its pool, a ring road with lane markings and
    /// glowing curbs, ground cars on it, and lamps.
    private func buildPlaza(_ root: SCNNode) {
        buildIsland(root, r: WorldMap.plazaRadius + 3.6, depth: 22, seed: 0.7, clear: 0, road: nil, flora: false)
        let stone = SCNNode(geometry: SCNCylinder(radius: CGFloat(WorldMap.plazaRadius - 0.2), height: 0.06))
        stone.geometry?.firstMaterial = CityArt.pbr(0x3A3F55, rough: 0.55, metal: 0.1)
        (stone.geometry as? SCNCylinder)?.radialSegmentCount = 64
        stone.position.y = 0.33
        root.addChildNode(stone)
        let roadRing = SCNNode(geometry: SCNTube(innerRadius: CGFloat(WorldMap.plazaRadius - 0.1), outerRadius: CGFloat(WorldMap.plazaRadius + 3.2), height: 0.08))
        roadRing.geometry?.firstMaterial = CityArt.pbr(0x1B1F2A, rough: 0.85, metal: 0.05)
        (roadRing.geometry as? SCNTube)?.radialSegmentCount = 72
        roadRing.position.y = 0.3
        root.addChildNode(roadRing)
        let lanes = SCNNode()
        for i in 0..<44 {
            let a = Float(i) / 44 * 2 * .pi
            let dash = SCNNode(geometry: SCNBox(width: 0.1, height: 0.02, length: 0.8, chamferRadius: 0))
            dash.geometry?.firstMaterial = Self.glow(0xE8EEFF, alpha: 0.5)
            let r = Float(WorldMap.plazaRadius) + 1.55
            dash.position = SCNVector3(sin(a) * r, 0.35, cos(a) * r)
            dash.eulerAngles.y = a + .pi / 2
            lanes.addChildNode(dash)
        }
        root.addChildNode(lanes.flattenedClone())
        let outer = SCNNode(geometry: SCNTube(innerRadius: CGFloat(WorldMap.plazaRadius + 3.1), outerRadius: CGFloat(WorldMap.plazaRadius + 3.3), height: 0.14))
        outer.geometry?.firstMaterial = Self.glow(0x32D8FF, alpha: 0.5)
        (outer.geometry as? SCNTube)?.radialSegmentCount = 72
        outer.position.y = 0.36
        root.addChildNode(outer)
        let ring = SCNTube(innerRadius: CGFloat(WorldMap.plazaRadius - 0.25), outerRadius: CGFloat(WorldMap.plazaRadius), height: 0.16)
        ring.radialSegmentCount = 72
        ring.firstMaterial = Self.glow(0x32D8FF, alpha: 0.8)
        let rn = SCNNode(geometry: ring)
        rn.position.y = 0.36
        root.addChildNode(rn)
        plazaRing = rn
        let m = CityArt.monument()
        m.position.y = 0.33
        root.addChildNode(m)
        globe = m.childNode(withName: "globe", recursively: true)
        for i in 0..<6 {  // lamps round the inside of the ring
            let a = Float(i) / 6 * 2 * .pi + 0.26
            let r = Float(WorldMap.plazaRadius) - 1.2
            let lamp = CityArt.lamp(at: SIMD3<Float>(sin(a) * r, 0.33, cos(a) * r), facing: 1)
            lamp.eulerAngles.y = a - .pi / 2
            root.addChildNode(lamp)
        }
        groundCars = []
        let paints: [UInt32] = [0xE9EEF6, 0x2B3550, 0xC23B4E, 0x3C7CF0, 0xF4D58D, 0x1C1F2A]
        for i in 0..<6 {
            let car = CityArt.hoverCar(paint: paints[i], glow: i % 2 == 0 ? 0x32D8FF : 0xFF6FD8)
            car.scale = SCNVector3(0.75, 0.75, 0.75)
            root.addChildNode(car)
            let lane: Float = i % 2 == 0 ? 0.8 : 2.3
            let speed: Float = i % 2 == 0 ? 0.32 : -0.27
            groundCars.append((car, Float(WorldMap.plazaRadius) + lane, speed, Float(i) * 1.05))
        }
    }

    /// A floating island (CityArt.island) with its trees, bushes and rocks.
    private func buildIsland(_ parent: SCNNode, r: Double, depth: Double, seed: Double, clear: Float = 0, road: Float? = nil, flora: Bool = true) {
        let rock = CityArt.island(radius: Float(r), depth: Float(depth), seed: Float(seed))
        rock.eulerAngles.y = Float(seed)
        parent.addChildNode(rock)
        if flora {
            parent.addChildNode(CityArt.flora(radius: Float(r), clear: clear, road: road, seed: "\(seed)", density: lowQuality ? 0.5 : 1))
        }
    }

    /// The district's raised stone deck: tiled floor, glowing rim, a wall of screens, desks with monitors, corner trees.
    private func buildDeck(_ dn: SCNNode, _ d: District) {
        let W = WorldMap.deckSize(d)
        guard W > 0 else { return }
        let c = Self.color(d)
        let h = Float(W / 2)
        let slab = SCNBox(width: CGFloat(W), height: 3.4, length: CGFloat(W), chamferRadius: 0)
        slab.firstMaterial = CityArt.pbr(0x3E3A55, rough: 0.6, metal: 0.15)
        let sn = SCNNode(geometry: slab)
        sn.position.y = -1.7
        dn.addChildNode(sn)
        let floor = SCNPlane(width: CGFloat(W - 0.6), height: CGFloat(W - 0.6))
        floor.firstMaterial = Self.tiles(c)
        let fn = SCNNode(geometry: floor)
        fn.eulerAngles.x = -.pi / 2
        fn.position.y = 0.03
        dn.addChildNode(fn)
        for (i, o) in [(Float(0), h), (0, -h), (h, 0), (-h, 0)].enumerated() {
            let bar = SCNBox(width: CGFloat(W), height: 0.2, length: 0.25, chamferRadius: 0)
            bar.firstMaterial = Self.glow(c)
            let bn = SCNNode(geometry: bar)
            bn.position = SCNVector3(o.0, 0.1, o.1)
            bn.eulerAngles.y = i < 2 ? 0 : .pi / 2
            dn.addChildNode(bn)
        }
        let wall = SCNBox(width: CGFloat(W - 1), height: 3.2, length: 0.5, chamferRadius: 0)
        wall.firstMaterial = Self.lit(0x141B33)
        let wn = SCNNode(geometry: wall)
        wn.position = SCNVector3(0, 1.6, -h + 0.4)
        dn.addChildNode(wn)
        for sx in [-7.5, -2.5, 2.5, 7.5] as [Float] {
            let screen = SCNPlane(width: 3.6, height: 1.8)
            screen.firstMaterial = Self.glow(c, alpha: 0.55)
            let n = SCNNode(geometry: screen)
            n.position = SCNVector3(sx, 1.9, -h + 0.7)
            dn.addChildNode(n)
        }
        var i = 0
        for z in [2.5, 5.5] as [Float] {
            for x in [-8.5, -5.5, 5.5, 8.5] as [Float] {
                let desk = SCNBox(width: 2.2, height: 0.9, length: 1.1, chamferRadius: 0)
                desk.firstMaterial = Self.lit(0x3A2F52)
                let n = SCNNode(geometry: desk)
                n.position = SCNVector3(x, 0.45, z)
                dn.addChildNode(n)
                let mon = SCNBox(width: 1.3, height: 0.85, length: 0.08, chamferRadius: 0)
                mon.firstMaterial = Self.lit(0x0B1020)
                let mn = SCNNode(geometry: mon)
                mn.position = SCNVector3(x, 1.35, z - 0.35)
                dn.addChildNode(mn)
                let glass = SCNPlane(width: 1.15, height: 0.7)
                glass.firstMaterial = i % 3 != 0 ? Self.glow(c) : Self.glow(0x9FE8FF)
                let gn = SCNNode(geometry: glass)
                gn.position = SCNVector3(x, 1.35, z - 0.3)
                dn.addChildNode(gn)
                i += 1
            }
        }
        var rng = WorldMap.Rng("deck" + d.id)
        for p in [(-h + 1.6, -h + 1.6), (h - 1.6, -h + 1.6), (-h + 1.6, h - 1.6), (h - 1.6, h - 1.6)] {
            let t = CityArt.tree(&rng, scale: 0.9)
            t.position = SCNVector3(p.0, 0, p.1)
            dn.addChildNode(t)
        }
    }

    private func buildDistrict(_ dn: SCNNode, _ d: District) {
        let c = Self.color(d)
        let pad = SCNPlane(width: 24, height: 24)  // a soft pool of the district's light, brighter while it's busy
        pad.firstMaterial = CityArt.light(c, image: CityArt.dot, alpha: 1)
        let pn = SCNNode(geometry: pad)
        pn.eulerAngles.x = -.pi / 2
        pn.castsShadow = false
        pn.position.y = 0.08
        dn.addChildNode(pn)
        pads[d.id] = pn
        let warm = d.color.uppercased() == "#F4D58D"
        for t in WorldMap.towers(d) {
            let n = CityArt.tower(t, color: c, warm: warm)
            n.position = SCNVector3(Float(t.pos.x), Float(t.pos.y), Float(t.pos.z))
            n.eulerAngles.y = Float(t.rot)
            dn.addChildNode(n)
            if let b = n.childNode(withName: "blink", recursively: true) { blinks.append(b) }
        }
        for w in d.workstations ?? [] {
            let wn = SCNNode()
            wn.position = SCNVector3(Float(w.offset[0]), 0, Float(w.offset[2]))
            let desk = SCNBox(width: 2.2, height: 1, length: 1.1, chamferRadius: 0)
            desk.firstMaterial = CityArt.pbr(0x232B40, rough: 0.35, metal: 0.7)
            let dk = SCNNode(geometry: desk)
            dk.position.y = 0.5
            wn.addChildNode(dk)
            let top = SCNNode(geometry: SCNPlane(width: 2, height: 0.9))
            top.geometry?.firstMaterial = Self.glow(0x1F2C4A)
            top.eulerAngles.x = -.pi / 2
            top.position.y = 1.02
            wn.addChildNode(top)
            let beam = SCNNode(geometry: SCNCone(topRadius: 0.25, bottomRadius: 0.6, height: 10))
            beam.geometry?.firstMaterial = Self.glow(c, alpha: 1)
            beam.geometry?.firstMaterial?.writesToDepthBuffer = false
            beam.position.y = 6
            beam.opacity = 0
            wn.addChildNode(beam)
            let ring = SCNNode(geometry: SCNTube(innerRadius: 1.6, outerRadius: 1.75, height: 0.01))
            ring.geometry?.firstMaterial = Self.glow(c, alpha: 0.4)
            ring.position.y = 0.01
            wn.addChildNode(ring)
            dn.addChildNode(wn)
            deskTops[w.id] = (top, beam, UIColor(hex: c))
            if let f = w.floor, d.architecture == "bank" {
                let band = SCNNode(geometry: SCNBox(width: 8.6, height: 0.35, length: 8.6, chamferRadius: 0))
                band.geometry?.firstMaterial = Self.glow(0x7A6A3A, alpha: 1)
                band.opacity = 0.18
                band.position = SCNVector3(2, Float(f) * 4.6 + 2.2, 0)
                dn.addChildNode(band)
                bankFloors.append((w.id, band, UIColor(hex: c)))
            }
        }
        if d.id == "owners-tower" {
            let b = SCNNode(geometry: SCNCone(topRadius: 0.6, bottomRadius: 1.6, height: 30))
            b.geometry?.firstMaterial = Self.glow(c, alpha: 1)
            b.geometry?.firstMaterial?.writesToDepthBuffer = false
            b.position = SCNVector3(0, Float((d.height ?? 40) + 18), -2)
            b.isHidden = true
            dn.addChildNode(b)
            beacon = b
        }
    }

    /// A paved road from the plaza's ring road to the district's gate, with lamps.
    private func buildWalkway(_ root: SCNNode, _ d: District) {
        let g = WorldMap.gate(d)
        let len = hypot(g.x, g.z)
        let start = WorldMap.plazaRadius + 3.2
        let walk = len - start
        guard walk > 0.5 else { return }
        let mid = (start + walk / 2) / len
        let n = CityArt.road(length: Float(walk), color: Self.color(d))
        n.position = SCNVector3(Float(g.x * mid), 0.2, Float(g.z * mid))
        n.eulerAngles.y = Float(atan2(g.x, g.z))
        root.addChildNode(n)
    }

    private func buildHub(_ root: SCNNode) {
        let hub = SCNNode()
        hub.position = SCNVector3(0, 0, 21)
        let base = SCNNode(geometry: Self.prism(top: 4, bottom: 4.4, height: 0.4, segments: 8))
        base.geometry?.firstMaterial = Self.lit(0x2B2342)
        base.position.y = 0.2
        hub.addChildNode(base)
        let ring = SCNNode(geometry: SCNTube(innerRadius: 3.2, outerRadius: 3.6, height: 0.02))
        ring.geometry?.firstMaterial = Self.glow(0xF4D58D)
        ring.position.y = 0.42
        hub.addChildNode(ring)
        root.addChildNode(hub)
        anchor("hub", in: hub, at: SCNVector3(0, 4, 0))
    }

    /// The company knowledge base floating over the plaza (KnowledgeBase.tsx): rock, deck, two library wings, a core
    /// crystal, and an orbiting tile per skill or doc.
    private func buildKnowledgeBase(_ root: SCNNode) {
        kb = SCNNode()
        kb.name = "kb"
        kb.position = SCNVector3(0, 34, 16)
        kb.scale = SCNVector3(1.5, 1.5, 1.5)
        let rn = CityArt.island(radius: 9, depth: 9, seed: 4.2)
        rn.position.y = -0.8
        kb.addChildNode(rn)
        let deck = Self.prism(top: 9.2, bottom: 9.2, height: 0.8, segments: 7)
        deck.firstMaterial = CityArt.pbr(0x2A2F4D, rough: 0.4, metal: 0.4)
        let dk = SCNNode(geometry: deck)
        dk.position.y = -0.4
        kb.addChildNode(dk)
        let ring = SCNNode(geometry: SCNTube(innerRadius: 8.6, outerRadius: 9.2, height: 0.02))
        ring.geometry?.firstMaterial = Self.glow(0x9BE7FF)
        ring.position.y = 0.05
        kb.addChildNode(ring)
        for (x, c) in [(Float(-3.2), UInt32(0x9BE7FF)), (3.2, 0xC9A3FF)] {
            let wing = SCNNode(geometry: SCNBox(width: 4, height: 5.2, length: 4, chamferRadius: 0))
            wing.geometry?.firstMaterial = CityArt.glass(c, alpha: 0.45, glow: 0.12)
            wing.position = SCNVector3(x, 2.6, 0)
            kb.addChildNode(wing)
            for y in [0.9, 2.1, 3.3, 4.5] as [Float] {
                let shelf = SCNNode(geometry: SCNBox(width: 3.2, height: 0.5, length: 0.05, chamferRadius: 0))
                shelf.geometry?.firstMaterial = Self.glow(c)
                shelf.position = SCNVector3(x, y, 2.02)
                kb.addChildNode(shelf)
            }
        }
        let core = SCNNode(geometry: Self.octahedron(1.9))
        core.geometry?.firstMaterial = CityArt.glass(0xBFF3FF, alpha: 0.8, glow: 0.9)
        core.position.y = 8.2
        kb.addChildNode(core)
        kbRing = SCNNode()
        kbRing.position.y = 7
        kb.addChildNode(kbRing)
        root.addChildNode(kb)
        anchor("kb", in: kb, at: SCNVector3(0, 13, 0))
        kbTiles = -1
    }

    /// One orbiting tile per doc or skill (gold for skills), as on the website.
    private var knowledgeCounts = (skills: 0, docs: 0)

    func setKnowledge(skills: Int, docs: Int) {
        knowledgeCounts = (skills, docs)
        let n = min(28, skills + docs)
        guard n != kbTiles else { return }
        kbTiles = n
        kbRing.childNodes.forEach { $0.removeFromParentNode() }
        for i in 0..<n {
            let a = Float(i) / Float(max(1, n)) * 2 * .pi
            let r: Float = 6 + Float(i % 2) * 1.2
            let t = SCNNode(geometry: SCNBox(width: 0.9, height: 1.2, length: 0.12, chamferRadius: 0))
            t.geometry?.firstMaterial = Self.glow(i < skills ? 0xF4D58D : i % 2 == 1 ? 0xC9A3FF : 0x9BE7FF)
            t.position = SCNVector3(cos(a) * r, sin(Float(i) * 1.7) * 0.8, sin(a) * r)
            t.eulerAngles.y = -a
            kbRing.addChildNode(t)
        }
    }

    private func buildWaterfalls(_ root: SCNNode, _ list: [District]) {
        falls = []
        for (i, d) in list.enumerated() where i % 2 == 0 {
            let k = i / 2
            var ox = d.x, oz = d.z
            if ox == 0 && oz == 0 { ox = 0.5; oz = 1 }
            let len = hypot(ox, oz)
            ox /= len; oz /= len
            let r = WorldMap.islandRadius(d) * 0.98
            let side: Double = k % 2 == 1 ? 1 : -1
            let ang = side * 0.6
            let dx = ox * cos(ang) + oz * sin(ang), dz = -ox * sin(ang) + oz * cos(ang)
            let height = 18 + Double(k % 3) * 5, width = 2.4 + Double(k % 2)
            let n = SCNNode()
            n.position = SCNVector3(Float(d.x + dx * r), 0, Float(d.z + dz * r))
            n.eulerAngles.y = Float(atan2(dx, dz))
            let sheet = SCNPlane(width: CGFloat(width), height: CGFloat(height))
            let m = Self.waterMaterial(repeatY: Float(height / 2))
            sheet.firstMaterial = m
            falls.append(m)
            let sn = SCNNode(geometry: sheet)
            sn.position.y = Float(-height / 2 - 0.2)
            n.addChildNode(sn)
            let pool = SCNNode(geometry: SCNPlane(width: CGFloat(width * 3), height: CGFloat(width * 3)))
            pool.geometry?.firstMaterial = CityArt.light(0x5FD8FF, image: CityArt.dot, alpha: 0.55)
            pool.eulerAngles.x = -.pi / 2
            pool.position.y = Float(-height - 0.2)
            n.addChildNode(pool)
            if !lowQuality {
                let mist = SCNNode()
                mist.position.y = Float(-height - 0.2)
                mist.addParticleSystem(CityArt.mist(width: Float(width)))
                n.addChildNode(mist)
            }
            root.addChildNode(n)
        }
    }

    private func buildIslets() {
        let spots: [(Float, Float, Float, Float)] = [(-78, 8, -40, 5), (70, 12, -52, 4), (86, 6, 30, 6), (-80, 14, 46, 4), (20, 18, 72, 3.5), (-24, 10, -74, 4.5)]
        for (i, s) in spots.enumerated() {
            let n = SCNNode()
            n.position = SCNVector3(s.0, s.1, s.2)
            buildIsland(n, r: Double(s.3), depth: Double(s.3) * 2.2, seed: Double(i) * 3.1)
            scene.rootNode.addChildNode(n)
            islets.append((n, s.1))
        }
    }

    /// Hover cars in flight lanes at several heights, each banking into its turn.
    private func buildCars() {
        let paints: [UInt32] = [0xE9EEF6, 0x22283A, 0xC23B4E, 0x3C7CF0, 0xF4D58D, 0x6E7A96, 0x0E0F14]
        let glows: [UInt32] = [0x32D8FF, 0xFF6FD8, 0x5BF2A5, 0xFFBD69, 0xA66BFF]
        for i in 0..<28 {
            let car = CityArt.hoverCar(paint: paints[i % paints.count], glow: glows[i % glows.count])
            scene.rootNode.addChildNode(car)
            let lane = i % 4
            let radius = 30 + Float(lane) * 12 + Float(i % 3) * 1.6
            let height = 15 + Float(lane) * 6
            let speed = 0.05 + Float(i % 5) * 0.012
            let start = (Float(i) * 2.399).truncatingRemainder(dividingBy: 2 * .pi)
            let dir: Float = lane % 2 == 0 ? 1 : -1
            cars.append((car, radius, height, speed, start, dir))
        }
    }

    /// A sea of soft clouds far below the islands, lit pink and gold by the low sun, drifting slowly.
    private func buildCloudSea() {
        for (i, y) in [Float(-52), -38].enumerated() {
            let plane = SCNPlane(width: 1500, height: 1500)
            plane.firstMaterial = CityArt.cloudLayer(i)
            let n = SCNNode(geometry: plane)
            n.name = "clouds\(i)"
            n.eulerAngles.x = -.pi / 2
            n.position.y = y
            n.castsShadow = false
            scene.rootNode.addChildNode(n)
            clouds.append(n)
        }
    }

    /// Delivery drones circling between the towers.
    private func buildDrones() {
        let spots: [SIMD3<Float>] = [SIMD3(-40, 22, -20), SIMD3(40, 26, -24), SIMD3(0, 30, -50), SIMD3(-56, 20, 20), SIMD3(52, 24, 18), SIMD3(0, 18, 40)]
        for (i, c) in spots.enumerated() {
            let d = CityArt.drone()
            scene.rootNode.addChildNode(d)
            let speed: Float = i % 2 == 0 ? 0.5 : -0.42
            drones.append((d, c, 7 + Float(i % 3) * 3, speed, Float(i) * 1.3))
        }
    }

    private func buildSkyline() {
        let group = SCNNode()
        let windows = Self.skylineWindows()
        for i in 0..<110 {
            let a = Double(i) / 110 * 2 * .pi + sin(Double(i) * 7.1) * 0.02
            if sin(a) > 0.55 { continue }  // keep the view toward the camera (south) open
            let r = 300 + Double((i * 37) % 60)
            let w = 6 + Double(i % 5) * 2, h = 25 + Double((i * 53) % 45)
            let box = SCNBox(width: CGFloat(w), height: CGFloat(h), length: CGFloat(w), chamferRadius: 0)
            box.firstMaterial = windows
            let n = SCNNode(geometry: box)
            n.position = SCNVector3(Float(cos(a) * r), Float(-60 + h / 2), Float(sin(a) * r))
            group.addChildNode(n)
            if i % 9 == 0 {
                let tip = SCNNode(geometry: Self.prism(top: 0.01, bottom: Float(w * 0.35), height: 20, segments: 4))
                tip.geometry?.firstMaterial = Self.glow(0xC86BFF)
                tip.position = SCNVector3(Float(cos(a) * r), Float(-60 + h + 10), Float(sin(a) * r))
                group.addChildNode(tip)
            }
        }
        scene.rootNode.addChildNode(group.flattenedClone())
    }

    // MARK: belts and packages

    private func syncBelts() {
        guard let app else { return }
        var nodes: [WorldMap.BeltNode] = []
        var segs: [WorldMap.BeltSegment] = []
        var speed = 8.0
        if let lg = app.logistics, let ns = lg.nodes, let rs = lg.routes, !ns.isEmpty {
            nodes = ns.map { WorldMap.BeltNode(id: $0.id, district: $0.district, kind: $0.kind, x: $0.position.first ?? 0, z: $0.position.count > 2 ? $0.position[2] : 0) }
            segs = rs.map { WorldMap.BeltSegment(id: $0.id, from: $0.fromNode, to: $0.toNode, status: $0.status, load: $0.load ?? 0) }
            speed = lg.beltSpeed ?? 8
        } else {
            let fallback = WorldMap.logistics(districtList)
            nodes = fallback.nodes
            segs = fallback.segments
        }
        beltSpeed = Float(speed)
        let key = segs.map { "\($0.id)\($0.status)\($0.load >= 2)" }.joined(separator: "|") + "\(nodes.count)"
        guard key != beltGraphKey else { return }
        beltGraphKey = key
        beltRoot.childNodes.forEach { $0.removeFromParentNode() }
        belts = [:]
        segIndex = [:]
        let pos = Dictionary(nodes.map { ($0.id, SIMD3<Float>(Float($0.x), Float(WorldMap.beltHeight), Float($0.z))) }, uniquingKeysWith: { a, _ in a })
        for s in segs {
            guard var a = pos[s.from], var b = pos[s.to] else { continue }
            if s.from.hasPrefix("junction:") && s.to.hasPrefix("junction:") {  // the two directions of a ring belt side by side
                let d = b - a
                let n = max(0.0001, simd_length(SIMD2<Float>(d.x, d.z)))
                let off = SIMD3<Float>(d.z / n * 0.55, 0, -d.x / n * 0.55)
                a += off; b += off
            }
            let len = simd_length(SIMD2<Float>(b.x - a.x, b.z - a.z))
            segIndex[s.id] = (a, b, len)
            let color: UInt32 = s.status == "DOWN" ? 0xFF6178 : s.load >= 2 ? 0xFFBD69 : 0x32D8FF
            let g = SCNNode()
            g.position = SCNVector3((a.x + b.x) / 2, a.y - 0.2, (a.z + b.z) / 2)
            g.eulerAngles.y = atan2(b.x - a.x, b.z - a.z)
            let base = SCNNode(geometry: SCNBox(width: 0.9, height: 0.18, length: CGFloat(len), chamferRadius: 0))
            base.geometry?.firstMaterial = CityArt.pbr(0x1A2236, rough: 0.4, metal: 0.7)
            base.opacity = s.status == "DOWN" ? 0.45 : 1
            g.addChildNode(base)
            var rails: [SCNNode] = []
            for x in [-0.47, 0.47] as [Float] {
                let r = SCNNode(geometry: SCNBox(width: 0.05, height: 0.05, length: CGFloat(len), chamferRadius: 0))
                r.geometry?.firstMaterial = Self.glow(color, alpha: s.status == "DOWN" ? 0.9 : 0.55)
                r.position = SCNVector3(x, 0.1, 0)
                g.addChildNode(r)
                rails.append(r)
            }
            let slats = SCNNode(geometry: SCNPlane(width: 0.8, height: CGFloat(len)))
            slats.geometry?.firstMaterial = Self.slatMaterial(length: len)
            slats.eulerAngles.x = -.pi / 2
            slats.position.y = 0.1
            slats.isHidden = s.status != "UP"
            g.addChildNode(slats)
            if s.status != "DOWN" { g.addChildNode(CityArt.tube(length: len)) }
            beltRoot.addChildNode(g)
            belts[s.id] = (rails, slats, len)
        }
        for n in nodes where n.kind != "junction" {  // terminals: a gantry with a light bar
            let t = SCNNode()
            t.position = SCNVector3(Float(n.x), 0, Float(n.z))
            for x in [-0.7, 0.7] as [Float] {
                let post = SCNNode(geometry: SCNBox(width: 0.12, height: 2.2, length: 0.12, chamferRadius: 0))
                post.geometry?.firstMaterial = Self.lit(0x1A2742, roughMetal: true)
                post.position = SCNVector3(x, 1.1, 0)
                t.addChildNode(post)
            }
            let bar = SCNNode(geometry: SCNBox(width: 1.6, height: 0.16, length: 0.5, chamferRadius: 0))
            bar.geometry?.firstMaterial = Self.glow(n.kind == "dispatch" ? 0x32D8FF : 0x5BF2A5)
            bar.position.y = 2.25
            t.addChildNode(bar)
            beltRoot.addChildNode(t)
        }
    }

    private var beltSpeed: Float = 8

    private func packagePosition(_ route: [String], elapsed: Float) -> (SIMD3<Float>, Bool)? {
        var remaining = max(0, elapsed) * beltSpeed
        var last: SIMD3<Float>?
        for id in route {
            guard let s = segIndex[id] else { continue }
            last = s.to
            if remaining <= s.length {
                let t = s.length > 0 ? remaining / s.length : 1
                return (s.from + (s.to - s.from) * t, false)
            }
            remaining -= s.length
        }
        return last.map { ($0, true) }
    }

    private func updatePackages(now: Date) {
        guard let app else { return }
        var seen = Set<String>()
        for p in app.packages where ["QUEUED", "IN_TRANSIT", "ARRIVED", "DELIVERY_FAILED"].contains(p.status) {
            guard let start = p.routeStartedAt, !p.route.isEmpty else { continue }
            let elapsed = Float(now.addingTimeInterval(app.serverOffset).timeIntervalSince(start))
            let delivered = p.status != "IN_TRANSIT" && p.status != "QUEUED"
            guard let at = packagePosition(p.route, elapsed: delivered ? 1e9 : elapsed) else { continue }
            let pos = at.0, done = at.1
            seen.insert(p.id)
            let n: SCNNode
            if let existing = packageNodes[p.id] {
                n = existing
            } else {
                n = SCNNode(geometry: SCNBox(width: 0.95, height: 0.95, length: 0.95, chamferRadius: 0))
                n.name = "package:\(p.id)"
                n.geometry?.firstMaterial = Self.glow(Self.hex(WorldMap.packageColor[p.type] ?? "#EAF2FF"), alpha: 0.85)
                scene.rootNode.addChildNode(n)
                packageNodes[p.id] = n
                anchors["pkg:\(p.id)"] = n
            }
            n.simdPosition = pos + SIMD3<Float>(0, 0.55, 0)
            n.eulerAngles.y = reduceMotion ? 0 : Float(phase * 0.8)
            // reached the end before the backend says ARRIVED: wait there and pulse
            n.opacity = done && p.status == "IN_TRANSIT" && !reduceMotion ? CGFloat(0.55 + abs(sin(phase * 6)) * 0.45) : 1
        }
        for (id, n) in packageNodes where !seen.contains(id) {
            n.removeFromParentNode()
            packageNodes[id] = nil
            anchors["pkg:\(id)"] = nil
        }
    }

    // MARK: agents

    private func agentsNow() -> [Agent] {
        guard let app else { return [] }
        return app.agents.isEmpty ? Roster.bundled : Array(app.agents.values)
    }

    private func state(of a: Agent) -> String {
        guard let app else { return a.executionState }
        if let s = app.world.states[a.id] { return s }
        return app.agents.isEmpty ? "IDLE" : a.executionState
    }

    private func updateAgents(now: Date) {
        guard let app else { return }
        let all = agentsNow()
        let byHome = Dictionary(grouping: all, by: \.homeDistrict).mapValues { $0.sorted { $0.id < $1.id }.map(\.id) }
        var seen = Set<String>()
        for a in all {
            seen.insert(a.id)
            let place = app.world.places[a.id]
            let dId = place?.district ?? (app.agents.isEmpty ? a.homeDistrict : (a.district ?? a.homeDistrict))
            let waypoint = place.map { $0.waypoint } ?? (app.agents.isEmpty ? nil : a.waypoint)
            guard let d = districts[dId] ?? districts[a.homeDistrict] else { continue }
            let slot = byHome[a.homeDistrict]?.firstIndex(of: a.id) ?? 0
            let target = waypoint != nil ? WorldMap.workstation(d, waypoint, slot: slot) : WorldMap.home(d, slot: slot)
            let key = "\(d.id)|\(waypoint ?? "")|\(slot)"
            let n = agentNodes[a.id] ?? makeAgent(a, at: target)
            if walks[a.id]?.key != key {
                let cur = n.simdPosition
                let fromDistrict = walks[a.id].flatMap { districts[String($0.key.split(separator: "|").first ?? "")] }
                let route = walks[a.id] == nil ? [target] : WorldMap.route(from: (Double(cur.x), 0, Double(cur.z)), fromDistrict: fromDistrict, to: d, target: target)
                walks[a.id] = (route, now, WorldMap.length(route), key)
            }
            let w = walks[a.id]!
            let travelled = reduceMotion ? w.length : now.timeIntervalSince(w.start) * WorldMap.walkSpeed
            let s = WorldMap.sample(w.route, travelled)
            n.simdPosition = SIMD3<Float>(Float(s.pos.x), 0, Float(s.pos.z))
            let st = state(of: a)
            styleAgent(n, a, state: st, walking: !s.done && !reduceMotion, heading: s.heading)
        }
        for (id, n) in agentNodes where !seen.contains(id) {
            n.removeFromParentNode()
            agentNodes[id] = nil
            walks[id] = nil
            lastStyle[id] = nil
            anchors["agent:\(id)"] = nil
        }
    }

    private func makeAgent(_ a: Agent, at p: WorldMap.V3) -> SCNNode {
        let n = SCNNode()
        n.name = "agent:\(a.id)"
        n.simdPosition = SIMD3<Float>(Float(p.x), 0, Float(p.z))
        let fig = CityArt.figure(a.avatar.look, fallback: a.avatar.color, visor: Self.hex(a.avatar.color))
        fig.name = "figure"
        fig.scale = SCNVector3(0.95, 0.95, 0.95)
        n.addChildNode(fig)
        let ring = SCNNode(geometry: SCNTube(innerRadius: 0.75, outerRadius: 0.9, height: 0.01))
        ring.name = "ring"
        ring.position.y = 0.05
        ring.castsShadow = false
        n.addChildNode(ring)
        let cube = SCNNode(geometry: SCNBox(width: 0.6, height: 0.6, length: 0.6, chamferRadius: 0.08))
        cube.name = "carry"
        cube.geometry?.firstMaterial = CityArt.glass(0x5BF2A5, alpha: 0.7, glow: 0.9)
        cube.position.y = 3.4
        cube.eulerAngles = SCNVector3(0.4, 0.6, 0)
        cube.isHidden = true
        n.addChildNode(cube)
        let hit = SCNNode(geometry: SCNCylinder(radius: 1.4, height: 3.6))
        hit.geometry?.firstMaterial = Self.glow(0x000000, alpha: 0.001)
        hit.position.y = 1.8
        hit.castsShadow = false
        n.addChildNode(hit)
        let head = SCNNode()
        head.position.y = 3.1
        n.addChildNode(head)
        anchors["agent:\(a.id)"] = head
        scene.rootNode.addChildNode(n)
        agentNodes[a.id] = n
        return n
    }

    private var lastStyle: [String: String] = [:]
    private var facing: [String: Float] = [:]

    /// Walk, work and idle motion for a 3D agent: legs and arms swing as it walks and it turns to face where it's
    /// going; at a desk it works with its hands; standing, it breathes.
    private func styleAgent(_ n: SCNNode, _ a: Agent, state: String, walking: Bool, heading: Double) {
        let working = ["EXECUTING", "PLANNING", "REVIEWING", "WAITING_FOR_TOOL"].contains(state)
        let carrying = app?.world.carrying[a.id] != nil
        guard let fig = n.childNode(withName: "figure", recursively: false),
              let rig = fig.childNode(withName: "rig", recursively: false) else { return }
        let seed = Double(a.id.unicodeScalars.first?.value ?? 0)
        let t = phase + seed
        if walking {
            let target = Float(heading)
            var cur = facing[a.id] ?? target
            var diff = target - cur
            while diff > .pi { diff -= 2 * .pi }
            while diff < -.pi { diff += 2 * .pi }
            cur += diff * 0.25
            facing[a.id] = cur
            rig.eulerAngles.y = cur
        }
        let legL = rig.childNode(withName: "legL", recursively: false)
        let legR = rig.childNode(withName: "legR", recursively: false)
        let torso = rig.childNode(withName: "torso", recursively: false)
        let armL = torso?.childNode(withName: "armL", recursively: false)
        let armR = torso?.childNode(withName: "armR", recursively: false)
        var legSwing: Float = 0, armLx: Float = 0, armRx: Float = 0, lift: Float = 0, bob: Float = 0
        if reduceMotion {
            // still: no swing or bob
        } else if walking {
            let swing = Float(sin(t * 9)) * 0.6
            legSwing = swing
            armLx = -swing * 0.8
            armRx = swing * 0.8
            lift = Float(abs(sin(t * 9))) * 0.07
        } else if working {
            armLx = -1.0 + Float(sin(t * 7)) * 0.12
            armRx = -1.0 + Float(sin(t * 7 + 1.7)) * 0.12
            bob = Float(sin(t * 2)) * 0.02
        } else {
            armLx = Float(sin(t * 1.3)) * 0.05
            armRx = -armLx
            bob = Float(sin(t * 1.6)) * 0.03
        }
        if carrying {
            armLx = -1.3
            armRx = -1.3
        }
        legL?.eulerAngles.x = legSwing
        legR?.eulerAngles.x = -legSwing
        armL?.eulerAngles.x = armLx
        armR?.eulerAngles.x = armRx
        rig.position.y = lift
        torso?.position.y = bob
        let styleKey = "\(state)\(carrying)\(followId == a.id)"
        if lastStyle[a.id] != styleKey {
            lastStyle[a.id] = styleKey
            let ring = n.childNode(withName: "ring", recursively: false)
            let selected = followId == a.id
            (ring?.geometry as? SCNTube)?.outerRadius = selected ? 1.05 : 0.9
            ring?.geometry?.firstMaterial = Self.glow(Self.hex(WorldMap.stateColor[state] ?? "#8FA8FF"), alpha: 0.9)
            n.childNode(withName: "carry", recursively: false)?.isHidden = !carrying
        }
    }

    func agentPosition(_ id: String) -> SIMD3<Float>? { agentNodes[id]?.simdPosition }

    // MARK: the frame loop

    private func tick() {
        if paused { return }
        let now = Date()
        let dt = Float(min(0.1, now.timeIntervalSince(last)))
        last = now
        phase += Double(dt)
        updateCamera(dt: dt)
        syncBelts()
        updateAgents(now: now)
        updatePackages(now: now)
        guard let app else { return }
        let world = app.world
        // busy districts glow, and the glow fades between events
        for (id, pad) in pads {
            let v = world.activity[id] ?? 0
            if v != seenActivity[id] { seenActivity[id] = v; padLevel[id] = max(padLevel[id] ?? 0, v) }
            padLevel[id] = max(0, (padLevel[id] ?? 0) - Double(dt) * 0.08)
            let focused = goal == nil && mode != .overview && districts[id].map { simd_distance(target, SIMD3<Float>(Float($0.x), 4, Float($0.z))) < 6 } == true
            pad.opacity = CGFloat(min(0.5, 0.12 + (padLevel[id] ?? 0) * 0.3 + (focused ? 0.08 : 0)))
        }
        // desks light up while a tool runs there, with a pulsing beam
        for (id, desk) in deskTops {
            let on = world.active[id] != nil
            desk.top.geometry?.firstMaterial?.emission.contents = on ? desk.color : UIColor(hex: 0x1F2C4A)
            desk.top.geometry?.firstMaterial?.diffuse.contents = on ? desk.color : UIColor(hex: 0x1F2C4A)
            desk.beam.opacity = on ? CGFloat(reduceMotion ? 0.5 : 0.35 + sin(phase * 6) * 0.15) : 0
        }
        for (i, f) in bankFloors.enumerated() {
            let on = world.active[f.id] != nil
            f.node.geometry?.firstMaterial?.emission.contents = on ? f.color : UIColor(hex: 0x7A6A3A)
            f.node.opacity = on ? CGFloat(reduceMotion ? 0.95 : 0.65 + sin(phase * 5 + Double(i)) * 0.3) : 0.18
        }
        // a light column over the Owner's Tower while a release waits for you
        let waiting = app.ownerWaiting > 0
        beacon?.isHidden = !waiting
        if waiting { beacon?.opacity = CGFloat(reduceMotion ? 0.35 : 0.25 + abs(sin(phase * 2)) * 0.3) }
        // the plaza ring turns green for a few seconds when a mission completes
        if let ring = plazaRing {
            let since = world.celebrateAt.map { now.timeIntervalSince($0) } ?? 99
            ring.geometry?.firstMaterial?.emission.contents = UIColor(hex: since < 6 ? 0x5BF2A5 : 0x32D8FF)
            ring.geometry?.firstMaterial?.diffuse.contents = UIColor(hex: since < 6 ? 0x5BF2A5 : 0x32D8FF)
            ring.opacity = since < 6 && !reduceMotion ? CGFloat(0.7 + sin(phase * 8) * 0.3) : 1
        }
        if !reduceMotion {
            kb.position.y = 34 + Float(sin(phase * 0.6)) * 0.8
            kbRing.eulerAngles.y = Float(phase * 0.15)
            for (i, s) in islets.enumerated() { s.node.position.y = s.y + Float(sin(phase * 0.5 + Double(i))) * 0.8 }
            for m in falls { m.diffuse.contentsTransform = SCNMatrix4Translate(m.diffuse.contentsTransform, 0, Float(-dt) * 1.6 / 9, 0); m.emission.contentsTransform = m.diffuse.contentsTransform }
            for b in belts.values {
                guard let m = b.slats.geometry?.firstMaterial else { continue }
                let t = SCNMatrix4Translate(SCNMatrix4MakeScale(1, b.length / 1.4, 1), 0, Float(-phase * 1.2 / 1.4), 0)
                m.diffuse.contentsTransform = t
                m.emission.contentsTransform = t
            }
        }
        for c in cars {  // nose along the direction of travel, banked into the curve
            let a = c.phase + (reduceMotion ? 0 : Float(phase) * c.speed * c.dir)
            c.node.position = SCNVector3(cos(a) * c.r, c.h + sin(a * 3) * 0.5, sin(a) * c.r)
            let tx = -sin(a) * c.dir, tz = cos(a) * c.dir
            c.node.eulerAngles = SCNVector3(0, atan2(tx, tz), -0.22 * c.dir)
        }
        for g in groundCars {
            let a = g.phase + (reduceMotion ? 0 : Float(phase) * g.speed)
            let dir: Float = g.speed >= 0 ? 1 : -1
            g.node.position = SCNVector3(sin(a) * g.r, 0.85, cos(a) * g.r)
            g.node.eulerAngles.y = atan2(cos(a) * dir, -sin(a) * dir)
        }
        if !lowQuality {
            for d in drones {
                let a = d.phase + (reduceMotion ? 0 : Float(phase) * d.speed)
                let y = d.center.y + Float(sin(phase * 1.3 + Double(d.phase))) * 0.6
                d.node.position = SCNVector3(d.center.x + cos(a) * d.r, y, d.center.z + sin(a) * d.r)
                d.node.eulerAngles.y = -a
            }
        }
        let on = reduceMotion || Int(phase * 1.2) % 2 == 0  // aircraft lights blink about once a second
        for b in blinks { b.isHidden = !on }
        for d in drones { d.node.childNode(withName: "blink", recursively: false)?.isHidden = !on }
        if !reduceMotion {
            globe?.eulerAngles.y = Float(phase * 0.25)
            for (i, c) in clouds.enumerated() { c.eulerAngles.y = Float(phase) * (i == 0 ? 0.004 : -0.006) }
        }
    }

    // MARK: materials and geometry

    static func hex(_ s: String) -> UInt32 { UInt32(s.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0xEAF2FF }
    static func color(_ d: District) -> UInt32 { hex(d.color) }

    /// Lit, flat-shaded surfaces (rock, grass, decks, building bodies).
    static func lit(_ c: UInt32, roughMetal: Bool = false) -> SCNMaterial {
        let m = SCNMaterial()
        m.diffuse.contents = UIColor(hex: c)
        m.lightingModel = .physicallyBased
        m.roughness.contents = NSNumber(value: roughMetal ? 0.35 : 0.8)
        m.metalness.contents = NSNumber(value: roughMetal ? 0.6 : 0)
        return m
    }

    /// Neon: unlit and bright, so the camera's bloom makes it glow.
    static func glow(_ c: UInt32, alpha: CGFloat = 1) -> SCNMaterial {
        let m = SCNMaterial()
        let col = UIColor(hex: c)
        m.diffuse.contents = col
        m.emission.contents = col
        m.lightingModel = .constant
        m.transparency = alpha
        if alpha < 1 { m.blendMode = .alpha; m.writesToDepthBuffer = false }
        m.isDoubleSided = true
        return m
    }

    private static var tileCache: [UInt32: UIImage] = [:]

    /// The deck's checkered floor (PixelWorld.tsx useTileTexture), sampled without smoothing.
    static func tiles(_ c: UInt32) -> SCNMaterial {
        let img = tileCache[c] ?? {
            let base = mix(c, 0x2B2D3E, 0.78), alt = mix(c, 0x30324A, 0.72)  // quiet stone tiles, a hint of the district
            let i = UIGraphicsImageRenderer(size: CGSize(width: 16, height: 16), format: .pixel).image { ctx in
                for y in 0..<2 { for x in 0..<2 {
                    UIColor(hex: (x + y) % 2 == 1 ? alt : base).setFill()
                    ctx.fill(CGRect(x: x * 8, y: y * 8, width: 8, height: 8))
                } }
                UIColor(white: 1, alpha: 0.08).setFill()
                ctx.fill(CGRect(x: 0, y: 0, width: 16, height: 1))
                ctx.fill(CGRect(x: 0, y: 0, width: 1, height: 16))
            }
            tileCache[c] = i
            return i
        }()
        let m = SCNMaterial()
        m.diffuse.contents = img
        m.diffuse.magnificationFilter = .linear
        m.diffuse.mipFilter = .linear
        m.diffuse.wrapS = .repeat
        m.diffuse.wrapT = .repeat
        m.diffuse.contentsTransform = SCNMatrix4MakeScale(6, 6, 1)
        m.lightingModel = .physicallyBased
        m.roughness.contents = NSNumber(value: 0.85)  // matte stone: no sun glare on the floor
        m.metalness.contents = NSNumber(value: 0)
        return m
    }

    static func mix(_ a: UInt32, _ b: UInt32, _ t: Double) -> UInt32 {
        func ch(_ v: UInt32, _ s: UInt32) -> Double { Double((v >> s) & 0xFF) }
        func m(_ s: UInt32) -> UInt32 { UInt32((ch(a, s) + (ch(b, s) - ch(a, s)) * t).rounded()) << s }
        return m(16) | m(8) | m(0)
    }

    static func slatMaterial(length: Float) -> SCNMaterial {
        let img = UIGraphicsImageRenderer(size: CGSize(width: 8, height: 14), format: .pixel).image { ctx in
            UIColor(hex: 0x0C1426).setFill(); ctx.fill(CGRect(x: 0, y: 0, width: 8, height: 14))
            UIColor(hex: 0x24407A).setFill(); ctx.fill(CGRect(x: 0, y: 6, width: 8, height: 2))
        }
        let m = SCNMaterial()
        m.diffuse.contents = img
        m.emission.contents = img
        m.diffuse.wrapT = .repeat
        m.emission.wrapT = .repeat
        m.diffuse.magnificationFilter = .nearest
        m.lightingModel = .constant
        m.diffuse.contentsTransform = SCNMatrix4MakeScale(1, length / 1.4, 1)
        return m
    }

    static func waterMaterial(repeatY: Float) -> SCNMaterial {
        let img = UIGraphicsImageRenderer(size: CGSize(width: 16, height: 16), format: .pixel).image { ctx in
            UIColor(red: 0.28, green: 0.64, blue: 0.75, alpha: 0.6).setFill(); ctx.fill(CGRect(x: 0, y: 0, width: 16, height: 16))
            UIColor(red: 0.9, green: 1, blue: 1, alpha: 0.85).setFill()
            for x in 0..<4 { ctx.fill(CGRect(x: x * 4, y: (x * 5) % 16, width: 4, height: 8)) }
        }
        let m = SCNMaterial()
        m.diffuse.contents = img
        m.emission.contents = img
        m.diffuse.wrapT = .repeat
        m.emission.wrapT = .repeat
        m.diffuse.magnificationFilter = .nearest
        m.lightingModel = .constant
        m.isDoubleSided = true
        m.writesToDepthBuffer = false
        m.blendMode = .alpha
        m.diffuse.contentsTransform = SCNMatrix4MakeScale(1, repeatY, 1)
        return m
    }

    static func skylineWindows() -> SCNMaterial {
        let img = UIGraphicsImageRenderer(size: CGSize(width: 16, height: 64), format: .pixel).image { ctx in
            UIColor(hex: 0x0D1030).setFill(); ctx.fill(CGRect(x: 0, y: 0, width: 16, height: 64))
            for y in stride(from: 2, to: 64, by: 4) {
                for x in stride(from: 2, to: 16, by: 4) {
                    let r = sin(Double(x) * 12.9898 + Double(y) * 78.233) * 43758.5453
                    let v = r - floor(r)
                    UIColor(hex: v > 0.72 ? 0xFFD27A : v > 0.55 ? 0x7FD8FF : v > 0.45 ? 0xFF7AD9 : 0x141A40).setFill()
                    ctx.fill(CGRect(x: x, y: y, width: 2, height: 2))
                }
            }
        }
        let m = SCNMaterial()
        m.diffuse.contents = img
        m.emission.contents = img
        m.multiply.contents = UIColor(hex: 0xC9CCFF)
        m.diffuse.magnificationFilter = .nearest
        m.lightingModel = .constant
        return m
    }

    /// The website's dusk sky dome as a latitude/longitude image: navy overhead, violet, a warm band at the horizon,
    /// dark below, and a scatter of stars.
    static let sky: UIImage = CityArt.sky()

    static func skyImage() -> UIImage {
        let w = 1024, h = 512
        return UIGraphicsImageRenderer(size: CGSize(width: w, height: h), format: .pixel).image { ctx in
            func c(_ r: Double, _ g: Double, _ b: Double) -> (Double, Double, Double) { (r, g, b) }
            let top = c(0.04, 0.05, 0.17), mid = c(0.23, 0.11, 0.38), low = c(0.98, 0.45, 0.42), deep = c(0.05, 0.05, 0.16)
            func lerp(_ a: (Double, Double, Double), _ b: (Double, Double, Double), _ t: Double) -> (Double, Double, Double) {
                (a.0 + (b.0 - a.0) * t, a.1 + (b.1 - a.1) * t, a.2 + (b.2 - a.2) * t)
            }
            func smooth(_ e0: Double, _ e1: Double, _ x: Double) -> Double {
                let t = max(0, min(1, (x - e0) / (e1 - e0)))
                return t * t * (3 - 2 * t)
            }
            for y in 0..<h {
                let lat = Double.pi / 2 - (Double(y) + 0.5) / Double(h) * .pi
                let hgt = sin(lat)
                let col: (Double, Double, Double)
                if hgt > 0.18 { col = lerp(mid, top, smooth(0.18, 0.7, hgt)) }
                else if hgt > 0 { col = lerp(low, mid, smooth(0, 0.18, hgt)) }
                else { col = lerp((low.0 * 0.55, low.1 * 0.55, low.2 * 0.55), deep, smooth(0, -0.22, hgt)) }
                UIColor(red: col.0, green: col.1, blue: col.2, alpha: 1).setFill()
                ctx.fill(CGRect(x: 0, y: y, width: w, height: 1))
            }
            var r = WorldMap.Rng("stars")
            UIColor.white.setFill()
            for _ in 0..<600 {
                let a = r.next(), e = 0.25 + r.next() * 1.2
                let el = min(e, .pi / 2)
                let y = (Double.pi / 2 - el) / .pi * Double(h)
                ctx.fill(CGRect(x: Int(a * Double(w)), y: Int(y), width: 1, height: 1))
            }
        }
    }

    static func tree(x: Float, z: Float, s: Float, color: UInt32) -> SCNNode {
        let n = SCNNode()
        n.position = SCNVector3(x, 0, z)
        n.scale = SCNVector3(s, s, s)
        let trunk = SCNNode(geometry: prism(top: 0.18, bottom: 0.25, height: 1.8, segments: 5))
        trunk.geometry?.firstMaterial = lit(0x5A3B2A)
        trunk.position.y = 0.9
        n.addChildNode(trunk)
        let crown = SCNNode(geometry: octahedron(1.25))
        crown.geometry?.firstMaterial = lit(color)
        crown.position.y = 2.4
        n.addChildNode(crown)
        return n
    }

    // flat-shaded custom geometry (every face has its own vertices and normal, like three.js flatShading)

    private static func mesh(_ tris: [(SIMD3<Float>, SIMD3<Float>, SIMD3<Float>)]) -> SCNGeometry {
        var v: [SCNVector3] = [], nrm: [SCNVector3] = []
        v.reserveCapacity(tris.count * 3)
        for t in tris {
            var n = simd_cross(t.1 - t.0, t.2 - t.0)
            n = simd_length(n) > 0 ? simd_normalize(n) : SIMD3<Float>(0, 1, 0)
            for p in [t.0, t.1, t.2] { v.append(SCNVector3(p)); nrm.append(SCNVector3(n)) }
        }
        let idx = (0..<Int32(v.count)).map { $0 }
        return SCNGeometry(sources: [SCNGeometrySource(vertices: v), SCNGeometrySource(normals: nrm)],
                           elements: [SCNGeometryElement(indices: idx, primitiveType: .triangles)])
    }

    /// A frustum (cylinder or cone) with flat faces, centred on its middle, axis up.
    static func prism(top: Float, bottom: Float, height: Float, segments: Int) -> SCNGeometry {
        var tris: [(SIMD3<Float>, SIMD3<Float>, SIMD3<Float>)] = []
        let h = height / 2
        for i in 0..<segments {
            let a0 = Float(i) / Float(segments) * 2 * .pi, a1 = Float(i + 1) / Float(segments) * 2 * .pi
            let t0 = SIMD3<Float>(sin(a0) * top, h, cos(a0) * top), t1 = SIMD3<Float>(sin(a1) * top, h, cos(a1) * top)
            let b0 = SIMD3<Float>(sin(a0) * bottom, -h, cos(a0) * bottom), b1 = SIMD3<Float>(sin(a1) * bottom, -h, cos(a1) * bottom)
            tris.append((t0, b0, b1)); tris.append((t0, b1, t1))
            tris.append((SIMD3<Float>(0, h, 0), t0, t1))
            tris.append((SIMD3<Float>(0, -h, 0), b1, b0))
        }
        return mesh(tris)
    }

    /// An upright cone whose rows are pushed in and out by a fixed pseudo-random amount (PixelWorld.tsx Island).
    static func jaggedCone(radius: Float, height: Float, seed: Float) -> SCNGeometry {
        let radial = 9, rows = 3
        var grid: [[SIMD3<Float>]] = []
        for iy in 0...rows {
            var row: [SIMD3<Float>] = []
            let y = height / 2 - height * Float(iy) / Float(rows)
            let r = radius * Float(iy) / Float(rows)
            for ix in 0...radial {
                let a = Float(ix) / Float(radial) * 2 * .pi
                var p = SIMD3<Float>(sin(a) * r, y, cos(a) * r)
                if iy > 0 {
                    let i = Float(iy * (radial + 1) + ix)
                    let raw = (sin(i * 12.9898 + seed) * 43758.5453).truncatingRemainder(dividingBy: 1)
                    let k = 0.75 + ((raw + 1).truncatingRemainder(dividingBy: 1)) * 0.5
                    p.x *= k; p.z *= k
                }
                row.append(p)
            }
            grid.append(row)
        }
        var tris: [(SIMD3<Float>, SIMD3<Float>, SIMD3<Float>)] = []
        for iy in 0..<rows {
            for ix in 0..<radial {
                let a = grid[iy][ix], b = grid[iy + 1][ix], c = grid[iy + 1][ix + 1], d = grid[iy][ix + 1]
                tris.append((a, b, d)); tris.append((b, c, d))
            }
        }
        let bottom = grid[rows]
        let centre = SIMD3<Float>(0, -height / 2, 0)
        for ix in 0..<radial { tris.append((centre, bottom[ix + 1], bottom[ix])) }
        return mesh(tris)
    }

    static func octahedron(_ r: Float) -> SCNGeometry {
        let px = SIMD3<Float>(r, 0, 0), nx = SIMD3<Float>(-r, 0, 0), py = SIMD3<Float>(0, r, 0), ny = SIMD3<Float>(0, -r, 0)
        let pz = SIMD3<Float>(0, 0, r), nz = SIMD3<Float>(0, 0, -r)
        return mesh([(py, pz, px), (py, px, nz), (py, nz, nx), (py, nx, pz), (ny, px, pz), (ny, nz, px), (ny, nx, nz), (ny, pz, nx)])
    }

    /// A tower's body and its neon edge lines (the website draws EdgesGeometry at 25°: box edges, cylinder rims,
    /// cone rims and ridges, the dome's rim).
    static func towerGeometry(_ t: WorldMap.Tower) -> (SCNGeometry, SCNGeometry) {
        let sx = Float(t.size.x), sy = Float(t.size.y), sz = Float(t.size.z)
        var lines: [(SIMD3<Float>, SIMD3<Float>)] = []
        let body: SCNGeometry
        func ring(_ r: Float, _ y: Float, _ n: Int) {
            for i in 0..<n {
                let a0 = Float(i) / Float(n) * 2 * .pi, a1 = Float(i + 1) / Float(n) * 2 * .pi
                lines.append((SIMD3<Float>(sin(a0) * r, y, cos(a0) * r), SIMD3<Float>(sin(a1) * r, y, cos(a1) * r)))
            }
        }
        switch t.kind {
        case .box:
            body = SCNBox(width: CGFloat(sx), height: CGFloat(sy), length: CGFloat(sz), chamferRadius: 0)
            let x = sx / 2, y = sy / 2, z = sz / 2
            let c = [SIMD3<Float>(-x, -y, -z), SIMD3<Float>(x, -y, -z), SIMD3<Float>(x, -y, z), SIMD3<Float>(-x, -y, z),
                     SIMD3<Float>(-x, y, -z), SIMD3<Float>(x, y, -z), SIMD3<Float>(x, y, z), SIMD3<Float>(-x, y, z)]
            for (a, b) in [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)] { lines.append((c[a], c[b])) }
        case .cyl:
            body = prism(top: sx / 2, bottom: sx / 2, height: sy, segments: 20)
            ring(sx / 2, sy / 2, 20); ring(sx / 2, -sy / 2, 20)
        case .cone:
            body = prism(top: 0.25, bottom: sx / 2, height: sy, segments: 6)
            ring(0.25, sy / 2, 6); ring(sx / 2, -sy / 2, 6)
            for i in 0..<6 {
                let a = Float(i) / 6 * 2 * .pi
                lines.append((SIMD3<Float>(sin(a) * 0.25, sy / 2, cos(a) * 0.25), SIMD3<Float>(sin(a) * sx / 2, -sy / 2, cos(a) * sx / 2)))
            }
        case .dome:
            var tris: [(SIMD3<Float>, SIMD3<Float>, SIMD3<Float>)] = []
            let r = sx, lat = 8, lon = 32
            func p(_ i: Int, _ j: Int) -> SIMD3<Float> {
                let th = Float(i) / Float(lat) * .pi / 2, ph = Float(j) / Float(lon) * 2 * .pi
                return SIMD3<Float>(r * cos(th) * sin(ph), r * sin(th), r * cos(th) * cos(ph))
            }
            for i in 0..<lat { for j in 0..<lon {
                tris.append((p(i, j), p(i, j + 1), p(i + 1, j + 1))); tris.append((p(i, j), p(i + 1, j + 1), p(i + 1, j)))
            } }
            body = mesh(tris)
            ring(r, 0, 32)
        }
        var v: [SCNVector3] = []
        for l in lines { v.append(SCNVector3(l.0)); v.append(SCNVector3(l.1)) }
        let edges = SCNGeometry(sources: [SCNGeometrySource(vertices: v)],
                                elements: [SCNGeometryElement(indices: (0..<Int32(v.count)).map { $0 }, primitiveType: .line)])
        return (body, edges)
    }
}

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}

extension UIGraphicsImageRendererFormat {
    /// One image pixel per point, so textures stay crisp pixel art.
    static var pixel: UIGraphicsImageRendererFormat {
        let f = UIGraphicsImageRendererFormat()
        f.scale = 1
        return f
    }
}
