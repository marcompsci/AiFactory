import SpriteKit
import UIKit

/// The town as a SpriteKit game: pixel-art maps, your character, agents at their desks, packages on the conveyor.
/// World coordinates are map pixels (x right, y down); nodes sit at (x, -y). Agent state comes from the GameModel,
/// which follows the backend; this scene only decides how it looks.
final class TownScene: SKScene {
    weak var model: GameModel?

    private let world = SKNode()
    /// Text sits on an unscaled layer so it stays sharp; positions follow the world each frame.
    private let overlay = SKNode()
    private var buildingLabels: [(node: Pill, at: CGPoint)] = []
    private var npcLabels: [String: Pill] = [:]
    private var statusPill: (id: String, text: String, node: Pill)?
    private let fade = SKSpriteNode(color: .black, size: CGSize(width: 4000, height: 4000))
    private var maps: [String: GameMap] = [:]
    private lazy var town: GameMap = Town.buildTown()
    private var map: GameMap!
    private var beltFrames: [SKTexture] = []
    private var beltNode: SKSpriteNode?
    private var beltTimer: TimeInterval = 0
    private var beltIndex = 0

    private let player = SKSpriteNode()
    private let playerShadow = SKSpriteNode(color: UIColor(white: 0, alpha: 0.22), size: CGSize(width: 10, height: 3))
    private var npcNodes: [String: NPCNode] = [:]
    private var packageNodes: [String: SKSpriteNode] = [:]
    private let marker = SKShapeNode(rectOf: CGSize(width: 8, height: 6))
    private let arrow = SKShapeNode()

    private var last: TimeInterval = 0
    private var clock: TimeInterval = 0
    private var walkT: TimeInterval = 0
    private var moving = false
    private var path: [Vec] = []
    private var pathGoal: (kind: GameModel.Nearby.Kind, id: String)?
    private var placed: [TownRules.Placed] = []
    private var points: [TownRules.PackagePoint] = []
    private var seenInteract = 0
    private var transitioning = false
    private var scale: CGFloat = 3
    private var textureCache: [ObjectIdentifier: SKTexture] = [:]

    // MARK: setup

    override func didMove(to view: SKView) {
        scaleMode = .resizeFill
        anchorPoint = CGPoint(x: 0.5, y: 0.5)
        backgroundColor = UIColor(red: 0.18, green: 0.42, blue: 0.21, alpha: 1)
        view.ignoresSiblingOrder = true
        if world.parent == nil {
            addChild(world)
            overlay.zPosition = 500_000
            addChild(overlay)
            fade.zPosition = 1_000_000
            fade.alpha = 0
            addChild(fade)
            marker.strokeColor = UIColor(white: 1, alpha: 0.85)
            marker.lineWidth = 1
            marker.zPosition = 90_000
            let a = CGMutablePath()
            a.move(to: CGPoint(x: -3, y: 4)); a.addLine(to: CGPoint(x: 3, y: 4)); a.addLine(to: CGPoint(x: 0, y: 0)); a.closeSubpath()
            arrow.path = a
            arrow.fillColor = .white
            arrow.strokeColor = UIColor(red: 0.11, green: 0.09, blue: 0.15, alpha: 1)
            arrow.lineWidth = 0.6
            arrow.zPosition = 95_000
            let p = model?.player ?? (map: "town", x: 24.5, y: 20.5, facing: .up)
            load(p.map, at: Vec(x: p.x, y: p.y), facing: p.facing)
        }
    }

    private func texture(_ c: PixelCanvas) -> SKTexture {
        let t = c.image().map { SKTexture(cgImage: $0) } ?? SKTexture()
        t.filteringMode = .nearest
        return t
    }

    private func texture(_ img: CGImage?) -> SKTexture {
        guard let img else { return SKTexture() }
        let k = ObjectIdentifier(img)
        if let hit = textureCache[k] { return hit }
        let t = SKTexture(cgImage: img)
        t.filteringMode = .nearest
        textureCache[k] = t
        return t
    }

    private func mapFor(_ id: String) -> GameMap? {
        if id == "town" { return town }
        if let m = maps[id] { return m }
        let m = Town.buildInterior(id)
        maps[id] = m
        return m
    }

    /// Builds the nodes for a map and puts the player at `at` (or the map's spawn when that spot is blocked).
    func load(_ id: String, at: Vec?, facing: Dir) {
        guard let m = mapFor(id) else { return }
        map = m
        world.removeAllChildren()
        overlay.removeAllChildren()
        buildingLabels = []
        npcLabels = [:]
        statusPill = nil
        npcNodes = [:]
        packageNodes = [:]
        path = []
        pathGoal = nil

        let ground = SKSpriteNode(texture: texture(PixelArt.groundLayer(m)))
        ground.anchorPoint = CGPoint(x: 0, y: 1)
        ground.position = .zero
        ground.zPosition = -10_000
        world.addChild(ground)

        beltFrames = m.belt.isEmpty ? [] : (0..<4).map { texture(PixelArt.beltLayer(m, frame: $0)) }
        if let first = beltFrames.first {
            let b = SKSpriteNode(texture: first)
            b.anchorPoint = CGPoint(x: 0, y: 1)
            b.zPosition = -9_000
            world.addChild(b)
            beltNode = b
        } else { beltNode = nil }

        let sprites = PixelArt.propSprites(m) + m.buildings.map(PixelArt.building)
        for s in sprites {
            let n = SKSpriteNode(texture: texture(s.canvas))
            n.anchorPoint = CGPoint(x: 0, y: 1)
            n.position = CGPoint(x: s.ox, y: -s.oy)
            n.zPosition = CGFloat(s.baseY)
            world.addChild(n)
        }
        if m.id == "town" {
            for b in m.buildings {
                let lift: CGFloat = b.style == .spire ? 30 : b.style == .tower ? 24 : b.style == .dome ? -6 : 12
                let label = Pill(text: b.name, size: 12, fill: UIColor(red: 0.08, green: 0.06, blue: 0.14, alpha: b.enterable ? 0.85 : 0.6))
                overlay.addChild(label)
                buildingLabels.append((label, CGPoint(x: CGFloat((b.x * 2 + b.w) * Town.tile) / 2, y: -(CGFloat(b.y * Town.tile) - lift))))
            }
        }

        playerShadow.zPosition = 0
        player.anchorPoint = CGPoint(x: 0.5, y: 0)
        player.size = CGSize(width: PixelSprites.w, height: PixelSprites.h)
        world.addChild(playerShadow)
        world.addChild(player)
        world.addChild(marker)
        world.addChild(arrow)
        marker.isHidden = true
        arrow.isHidden = true

        var start = at ?? Vec(x: Double(m.spawn.x) + 0.5, y: Double(m.spawn.y) + 0.5)
        if m.isSolid(Int(floor(start.x)), Int(floor(start.y))) { start = Vec(x: Double(m.spawn.x) + 0.5, y: Double(m.spawn.y) + 0.5) }
        model?.player = (map: m.id, x: start.x, y: start.y, facing: at == nil ? m.spawn.facing : facing)
        model?.mapId = m.id
        model?.nearby = nil
        update(dtOnly: 0)
    }

    private func go(to id: String, at: Vec?, facing: Dir) {
        guard !transitioning else { return }
        transitioning = true
        moving = false
        fade.run(.sequence([
            .fadeIn(withDuration: 0.22),
            .run { [weak self] in
                self?.load(id, at: at, facing: facing)
                self?.model?.moved = true
                self?.model?.talk(nil)
            },
            .fadeOut(withDuration: 0.22),
            .run { [weak self] in self?.transitioning = false },
        ]))
    }

    private func enter(_ id: String) {
        guard let inner = mapFor(id) else { return }
        go(to: id, at: Vec(x: Double(inner.spawn.x) + 0.5, y: Double(inner.spawn.y) + 0.5), facing: inner.spawn.facing)
    }

    /// Restore a saved position (from the server).
    func restore(map id: String, x: Double, y: Double, facing: Dir) {
        guard mapFor(id) != nil else { return }
        load(id, at: Vec(x: x, y: y), facing: facing)
    }

    // MARK: input

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let t = touches.first, touches.count == 1, let model, model.talkingTo == nil, model.panel == nil, !transitioning else { return }
        let loc = t.location(in: self)
        let wx = Double((loc.x - world.position.x) / scale) / Double(Town.tile)
        let wy = Double(-(loc.y - world.position.y) / scale) / Double(Town.tile)
        tap(Vec(x: wx, y: wy))
    }

    private func tap(_ w: Vec) {
        guard let model else { return }
        let p = model.player
        if let pk = points.min(by: { hypot($0.x - w.x, $0.y - w.y) < hypot($1.x - w.x, $1.y - w.y) }), hypot(pk.x - w.x, pk.y - w.y) < 0.7 {
            model.packageId = pk.id
            return
        }
        if let npc = placed.min(by: { hypot($0.x - w.x, $0.y - 0.5 - w.y) < hypot($1.x - w.x, $1.y - 0.5 - w.y) }), hypot(npc.x - w.x, npc.y - 0.5 - w.y) < 0.8 {
            if hypot(npc.x - p.x, npc.y - p.y) < 2.1 { model.talk(npc.agent.id); return }
            walk(to: Vec(x: npc.x, y: npc.y + 1), goal: (.npc, npc.agent.id))
            return
        }
        if let obj = map.interactables.first(where: { $0.x == Int(floor(w.x)) && $0.y == Int(floor(w.y)) }), obj.action != .enter, obj.action != .exit {
            if hypot(Double(obj.x) + 0.5 - p.x, Double(obj.y) + 0.5 - p.y) < 1.6 { use(obj.id); return }
            walk(to: Vec(x: Double(obj.x) + 0.5, y: Double(obj.y) + 1.5), goal: (.object, obj.id))
            return
        }
        walk(to: w, goal: nil)
    }

    private func walk(to: Vec, goal: (kind: GameModel.Nearby.Kind, id: String)?) {
        guard let model else { return }
        let blocked = Set(placed.map { Int(floor($0.y)) * map.w + Int(floor($0.x)) })
        path = TownRules.path(map, from: Vec(x: model.player.x, y: model.player.y), to: to, blocked: blocked)
        pathGoal = path.isEmpty ? nil : goal
    }

    private func interact() {
        guard let n = model?.nearby else { return }
        if n.kind == .npc { path = []; pathGoal = nil; model?.talk(n.id) } else { use(n.id) }
    }

    private func use(_ id: String) {
        guard let model, let obj = map.interactables.first(where: { $0.id == id }) else { return }
        switch obj.action {
        case .approvals: model.panel = .approvals
        case .journal: model.panel = .journal
        case .findings: model.panel = .findings
        case .closed:
            let b = map.buildings.first { $0.id == obj.target }
            model.say(b?.note ?? "Packages for the Claude Code, GitHub and Codex factories leave town here.")
        case .enter: if let t = obj.target { enter(t) }
        case .exit: break
        }
    }

    // MARK: frame

    override func update(_ currentTime: TimeInterval) {
        let dt = last == 0 ? 0 : min(0.05, currentTime - last)
        last = currentTime
        update(dtOnly: dt)
    }

    private func update(dtOnly dt: TimeInterval) {
        guard let model, let map else { return }
        clock += dt
        if model.interactSeq != seenInteract { seenInteract = model.interactSeq; interact() }

        placed = TownRules.place(map, model.agents, now: clock, talkingTo: model.talkingTo, town: town)
        let serverNow = Date().addingTimeInterval(model.serverOffset)
        points = map.id == "town" ? model.packages.compactMap { TownRules.packagePoint(map, $0, serverNow: serverNow) } : []

        var p = model.player
        if !transitioning {
            var vx = 0.0, vy = 0.0
            if model.talkingTo == nil && model.panel == nil {
                let s = model.stick
                if abs(s.dx) > 0.15 || abs(s.dy) > 0.15 { vx = Double(s.dx); vy = Double(s.dy) }
            }
            if vx != 0 || vy != 0 { path = []; pathGoal = nil }
            else if let n = path.first {
                let dx = n.x - p.x, dy = n.y - p.y, d = hypot(dx, dy)
                if d < 0.12 { path.removeFirst() } else { vx = dx / d; vy = dy / d }
            }
            let len = hypot(vx, vy)
            moving = len > 0.01
            if moving && dt > 0 {
                let k = (min(1, len) * TownRules.walkSpeed * dt) / len
                let before = Vec(x: p.x, y: p.y)
                let after = TownRules.move(map, before, dx: vx * k, dy: vy * k, blockers: placed.map { Vec(x: $0.x, y: $0.y) })
                p.facing = TownRules.facing(vx, vy, p.facing)
                if hypot(after.x - before.x, after.y - before.y) < 1e-4 && !path.isEmpty { path = [] }
                p.x = after.x; p.y = after.y
                walkT += dt
                model.moved = true
            }
            model.player = p
            let tx = Int(floor(p.x)), ty = Int(floor(p.y))
            if map.id == "town", let b = map.buildings.first(where: { $0.enterable && $0.door.x == tx && $0.door.y == ty }) { enter(b.id) }
            else if let ex = map.exits.first(where: { $0.x == tx && $0.y == ty }) {
                go(to: ex.to, at: Vec(x: Double(ex.at.x) + 0.5, y: Double(ex.at.y) + 0.5), facing: ex.at.facing)
            }
            if let g = pathGoal, path.isEmpty {
                pathGoal = nil
                if g.kind == .npc, placed.contains(where: { $0.agent.id == g.id }) { model.talk(g.id) }
                if g.kind == .object { use(g.id) }
            }
            // what's close enough to talk to or use
            let npc = placed.min { hypot($0.x - p.x, $0.y - p.y) < hypot($1.x - p.x, $1.y - p.y) }
            var near: GameModel.Nearby?
            if let npc, hypot(npc.x - p.x, npc.y - p.y) <= 2.1 {
                near = .init(kind: .npc, id: npc.agent.id, label: "Talk to \(npc.agent.name)")
            } else if let obj = map.interactables.filter({ $0.action != .enter && $0.action != .exit })
                .min(by: { hypot(Double($0.x) + 0.5 - p.x, Double($0.y) + 0.5 - p.y) < hypot(Double($1.x) + 0.5 - p.x, Double($1.y) + 0.5 - p.y) }),
                hypot(Double(obj.x) + 0.5 - p.x, Double(obj.y) + 0.5 - p.y) <= 1.35 {
                near = .init(kind: .object, id: obj.id, label: obj.label)
            }
            if near != model.nearby { model.nearby = near }
            if let tid = model.talkingTo, let who = placed.first(where: { $0.agent.id == tid }) {
                p.facing = TownRules.facing(who.x - p.x, who.y - p.y, p.facing)
                model.player = p
            }
        }
        draw(p)
    }

    // MARK: drawing

    private func toScene(_ wp: CGPoint) -> CGPoint {
        CGPoint(x: world.position.x + wp.x * scale, y: world.position.y + wp.y * scale)
    }

    private func draw(_ p: (map: String, x: Double, y: Double, facing: Dir)) {
        guard let model, let view else { return }
        let T = CGFloat(Town.tile)
        // integer device pixels per map pixel, about 15 tiles tall in portrait
        let native = view.contentScaleFactor
        let tilesTall: CGFloat = size.height > size.width ? 21 : 13
        let dev = max(2, (size.height * native / (T * tilesTall)).rounded())
        scale = dev / native
        world.setScale(scale)
        let viewW = size.width / scale, viewH = size.height / scale
        let mapW = CGFloat(map.w) * T, mapH = CGFloat(map.h) * T
        var camX = CGFloat(p.x) * T, camY = CGFloat(p.y) * T
        camX = mapW <= viewW ? mapW / 2 : min(max(viewW / 2, camX), mapW - viewW / 2)
        camY = mapH <= viewH ? mapH / 2 : min(max(viewH / 2, camY), mapH - viewH / 2)
        world.position = CGPoint(x: (-camX * scale * native).rounded() / native, y: (camY * scale * native).rounded() / native)
        backgroundColor = map.id == "town" ? UIColor(red: 0.18, green: 0.42, blue: 0.21, alpha: 1) : UIColor(red: 0.07, green: 0.055, blue: 0.11, alpha: 1)

        if let belt = beltNode, !beltFrames.isEmpty, !UIAccessibility.isReduceMotionEnabled {  // Reduce Motion: belt stays still
            beltTimer += 1
            if beltTimer >= 5 { beltTimer = 0; beltIndex = (beltIndex + 1) % beltFrames.count; belt.texture = beltFrames[beltIndex] }
        }

        // you
        let pose: Pose = moving ? .walk : .stand
        let frame = moving ? Int(walkT / 0.13) % 4 : 0
        player.texture = texture(PixelSprites.image(PixelSprites.outfit(model.look), p.facing, pose, frame))
        player.position = CGPoint(x: (CGFloat(p.x) * T).rounded(), y: -((CGFloat(p.y) * T).rounded() + 2))
        player.zPosition = CGFloat(p.y) * T
        playerShadow.position = CGPoint(x: (CGFloat(p.x) * T).rounded(), y: -(CGFloat(p.y) * T).rounded())
        playerShadow.zPosition = player.zPosition - 0.5

        // agents
        var seen = Set<String>()
        for pl in placed {
            seen.insert(pl.agent.id)
            let node = npcNodes[pl.agent.id] ?? {
                let n = NPCNode()
                world.addChild(n)
                npcNodes[pl.agent.id] = n
                let label = Pill(text: pl.agent.name, size: 11, fill: UIColor(red: 0.08, green: 0.06, blue: 0.14, alpha: 0.8))
                overlay.addChild(label)
                npcLabels[pl.agent.id] = label
                return n
            }()
            let pose: Pose = {
                switch pl.anim {
                case .walking: return .walk
                case .delivering: return .carry
                case .talking: return .talk
                case .working, .coding, .testing: return .work
                case .researching: return .read
                case .celebrating: return .celebrate
                case .idle, .waiting: return .stand
                }
            }()
            let frameMs: Double = [Pose.stand: 0.7, .walk: 0.14, .carry: 0.14, .work: 0.26, .read: 0.9, .talk: 0.2, .celebrate: 0.26][pose] ?? 0.5
            let count = pose == .walk || pose == .carry ? 4 : 2
            var facing = pl.facing
            if pl.anim == .talking { facing = TownRules.facing(p.x - pl.x, p.y - pl.y, .down) }
            let outfit = pl.agent.look.map(PixelSprites.outfit) ?? PixelSprites.outfit(PlayerLook(skin: "#E0AC69", hairStyle: "short", hair: "#3A2A20", shirt: pl.agent.color, pants: "#2D3346", shoes: "#2A2230", glasses: false))
            node.body.texture = texture(PixelSprites.image(outfit, facing, pose, Int(clock / frameMs) % count))
            node.position = CGPoint(x: (CGFloat(pl.x) * T).rounded(), y: -(CGFloat(pl.y) * T).rounded())
            node.zPosition = CGFloat(pl.y) * T
            let icon: String? = pl.agent.execState == "FAILED" ? "fail" : pl.agent.execState == "WAITING_FOR_APPROVAL" ? "alert" :
                [Anim.working: "gear", .coding: "code", .researching: "lens", .testing: "flask", .waiting: "wait", .delivering: "box", .celebrating: "star"][pl.anim]
            node.setIcon(icon, bob: CGFloat(sin(clock * 3.3)) * 0.5)
            let head = toScene(CGPoint(x: node.position.x, y: node.position.y + 27))
            npcLabels[pl.agent.id]?.position = head
            if model.nearby?.id == pl.agent.id && model.talkingTo == nil {
                let text = TownRules.statusLabel(pl.agent)
                if statusPill?.id != pl.agent.id || statusPill?.text != text {
                    statusPill?.node.removeFromParent()
                    let sp = Pill(text: text, size: 10, fill: UIColor(red: 0.36, green: 0.95, blue: 0.65, alpha: 0.95), ink: UIColor(red: 0.04, green: 0.1, blue: 0.07, alpha: 1))
                    overlay.addChild(sp)
                    statusPill = (pl.agent.id, text, sp)
                }
                statusPill?.node.position = CGPoint(x: head.x, y: head.y + 20)
            } else if statusPill?.id == pl.agent.id {
                statusPill?.node.removeFromParent()
                statusPill = nil
            }
        }
        for (id, n) in npcNodes where !seen.contains(id) {
            n.removeFromParent(); npcNodes[id] = nil
            npcLabels[id]?.removeFromParent(); npcLabels[id] = nil
            if statusPill?.id == id { statusPill?.node.removeFromParent(); statusPill = nil }
        }
        for b in buildingLabels { b.node.position = toScene(b.at) }

        // packages
        var seenPk = Set<String>()
        for pt in points {
            seenPk.insert(pt.id)
            let flag = pt.package.status == "ARRIVED" ? "#5BF2A5" : pt.package.status == "DELIVERY_FAILED" ? "#FF6178" : nil
            let node = packageNodes[pt.id] ?? {
                let n = SKSpriteNode()
                n.anchorPoint = CGPoint(x: 0.5, y: 0)
                world.addChild(n)
                packageNodes[pt.id] = n
                return n
            }()
            node.texture = texture(PixelArt.crate(pt.package.type, flag: flag))
            node.size = CGSize(width: 14, height: 16)
            let bob: CGFloat = pt.package.status == "IN_TRANSIT" ? CGFloat(sin(clock * 6 + pt.x)).rounded() * 0.6 : 0
            node.position = CGPoint(x: (CGFloat(pt.x) * T).rounded(), y: -((CGFloat(pt.y) * T).rounded() + 2) + bob)
            node.zPosition = CGFloat(pt.y) * T + 4
            node.alpha = model.packageId == pt.id ? 0.75 + 0.25 * CGFloat(sin(clock * 8)) : 1
        }
        for (id, n) in packageNodes where !seenPk.contains(id) { n.removeFromParent(); packageNodes[id] = nil }

        // tap target and "use" arrow
        if let g = path.last {
            marker.isHidden = false
            marker.position = CGPoint(x: CGFloat(g.x) * T, y: -CGFloat(g.y) * T + 1)
            marker.setScale(1 + 0.15 * CGFloat(sin(clock * 8)))
        } else { marker.isHidden = true }
        if let n = model.nearby, n.kind == .object, let obj = map.interactables.first(where: { $0.id == n.id }) {
            arrow.isHidden = false
            arrow.position = CGPoint(x: (CGFloat(obj.x) + 0.5) * T, y: -(CGFloat(obj.y) * T - 2) + CGFloat(sin(clock * 5)) * 2)
        } else { arrow.isHidden = true }
    }
}

/// An agent in the world: body sprite, shadow and status bubble (its name is drawn on the overlay).
final class NPCNode: SKNode {
    let body = SKSpriteNode()
    private let bubble = SKSpriteNode()
    private var icon: String?
    private static var bubbles: [String: SKTexture] = [:]

    override init() {
        super.init()
        body.anchorPoint = CGPoint(x: 0.5, y: 0)
        body.size = CGSize(width: PixelSprites.w, height: PixelSprites.h)
        body.position = CGPoint(x: 0, y: -2)
        let shadow = SKSpriteNode(color: UIColor(white: 0, alpha: 0.22), size: CGSize(width: 10, height: 3))
        shadow.zPosition = -0.5
        addChild(shadow)
        addChild(body)
        bubble.anchorPoint = CGPoint(x: 0.5, y: 0.5)
        bubble.size = CGSize(width: 13, height: 13)
        bubble.zPosition = 70_001
        bubble.isHidden = true
        addChild(bubble)
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    func setIcon(_ name: String?, bob: CGFloat) {
        if name != icon {
            icon = name
            if let name {
                let t = NPCNode.bubbles[name] ?? {
                    let t = SKTexture(cgImage: PixelArt.bubble(name).image()!)
                    t.filteringMode = .nearest
                    NPCNode.bubbles[name] = t
                    return t
                }()
                bubble.texture = t
            }
            bubble.isHidden = name == nil
        }
        bubble.position = CGPoint(x: 13, y: 33 + bob)
    }
}

/// A rounded label with a dark (or colored) background, sized in map pixels.
final class Pill: SKNode {
    private(set) var width: CGFloat = 0

    init(text: String, size: CGFloat, fill: UIColor, ink: UIColor = .white) {
        super.init()
        let l = SKLabelNode(text: text)
        l.fontName = "Menlo-Bold"
        l.fontSize = size
        l.fontColor = ink
        l.verticalAlignmentMode = .center
        l.horizontalAlignmentMode = .center
        let w = l.frame.width + size * 1.1, h = size * 1.6
        width = w
        let bg = SKShapeNode(rectOf: CGSize(width: w, height: h), cornerRadius: h / 2.6)
        bg.fillColor = fill
        bg.strokeColor = .clear
        addChild(bg)
        l.zPosition = 0.1
        addChild(l)
    }

    required init?(coder: NSCoder) { fatalError("not used") }
}
