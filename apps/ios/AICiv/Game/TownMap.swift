import Foundation

/// The playable town and its building interiors, built from code so layout, collision and the conveyor all come from
/// one source. Same layout as the web version (apps/web/lib/play/maps.ts). Tiles are 16 px; x right, y down.
enum Dir: String, Codable, CaseIterable { case down, up, left, right }

enum Ground: UInt8 { case grass, grass2, path, plaza, water, wood, tile, carpet, metal, wall }

enum Deco: String {
    case tree, pine, bush, flowers, fence, lamp, rock, fountain, sign, stall, bench
    case desk, monitor, chair, shelf, plant, whiteboard, sofa, table, screen, telescope
    case server, anvil, cooler, printer, clock, window, rug, counter, board, terminal, crates
}

struct TilePoint: Hashable { var x: Int; var y: Int }

struct BuildingDef {
    enum Style { case spire, dome, forge, tower, citadel, studio, bank, vault }
    let id: String
    let name: String
    let x: Int, y: Int, w: Int, h: Int
    let door: TilePoint
    let style: Style
    let roof: String
    let wall: String
    let enterable: Bool
    var note: String? = nil
}

struct Prop {
    let kind: Deco
    let x: Int, y: Int
    var w: Int = 1, h: Int = 1
    var solid: Bool = true
    var color: String? = nil
}

struct Interactable {
    enum Action { case journal, approvals, findings, exit, closed, enter }
    let id: String
    let x: Int, y: Int
    let label: String
    let action: Action
    var target: String? = nil
}

struct Workstation { let x: Double; let y: Double; let facing: Dir }

struct MapExit { let x: Int; let y: Int; let to: String; let at: (x: Int, y: Int, facing: Dir) }

final class GameMap {
    let id: String
    let name: String
    let w: Int
    let h: Int
    var ground: [Ground]
    var solid: [Bool]
    var props: [Prop] = []
    var buildings: [BuildingDef] = []
    var interactables: [Interactable] = []
    var belt = Set<Int>()
    var docks: [String: TilePoint] = [:]
    var workstations: [Workstation] = []
    var spawn = (x: 1, y: 1, facing: Dir.down)
    var exits: [MapExit] = []

    init(id: String, name: String, w: Int, h: Int, fill g: Ground) {
        self.id = id; self.name = name; self.w = w; self.h = h
        ground = Array(repeating: g, count: w * h)
        solid = Array(repeating: false, count: w * h)
    }

    func idx(_ x: Int, _ y: Int) -> Int { y * w + x }
    func inside(_ x: Int, _ y: Int) -> Bool { x >= 0 && y >= 0 && x < w && y < h }
    func isSolid(_ x: Int, _ y: Int) -> Bool { !inside(x, y) || solid[idx(x, y)] }
    func groundAt(_ x: Int, _ y: Int) -> Ground? { inside(x, y) ? ground[idx(x, y)] : nil }

    func fill(_ x: Int, _ y: Int, _ w: Int, _ h: Int, _ g: Ground) {
        guard w > 0, h > 0 else { return }
        for j in y..<(y + h) { for i in x..<(x + w) where inside(i, j) { ground[idx(i, j)] = g } }
    }

    func block(_ x: Int, _ y: Int, _ w: Int = 1, _ h: Int = 1) {
        for j in y..<(y + h) { for i in x..<(x + w) where inside(i, j) { solid[idx(i, j)] = true } }
    }

    func add(_ p: Prop) {
        props.append(p)
        if p.solid { block(p.x, p.y, p.w, p.h) }
    }
}

/// A tiny deterministic random (same sequence as the web version), so decoration lands in the same place every load.
struct TownRandom {
    private var s: UInt32
    init(_ seed: UInt32) { s = seed }
    mutating func next() -> Double {
        s = s &* 1664525 &+ 1013904223
        return Double(s) / 4294967296.0
    }
}

enum Town {
    static let tile = 16

    static let buildings: [BuildingDef] = [
        BuildingDef(id: "data-observatory", name: "Research Observatory", x: 5, y: 5, w: 7, h: 7, door: TilePoint(x: 8, y: 11), style: .dome, roof: "#5C7FD6", wall: "#EADBC0", enterable: true),
        BuildingDef(id: "nexus-spire", name: "Nexus Spire", x: 21, y: 2, w: 7, h: 10, door: TilePoint(x: 24, y: 11), style: .spire, roof: "#7A5CD6", wall: "#E8DDF2", enterable: true),
        BuildingDef(id: "code-forge", name: "Code Forge", x: 36, y: 5, w: 7, h: 7, door: TilePoint(x: 39, y: 11), style: .forge, roof: "#C2553A", wall: "#E9D6BC", enterable: true),
        BuildingDef(id: "vision-quarter", name: "Creative Studio", x: 4, y: 16, w: 7, h: 6, door: TilePoint(x: 7, y: 21), style: .studio, roof: "#D65C9E", wall: "#F2E4D6", enterable: false, note: "The Creative Studio opens in a later update."),
        BuildingDef(id: "sentinel-citadel", name: "Sentinel Citadel", x: 37, y: 16, w: 7, h: 6, door: TilePoint(x: 40, y: 21), style: .citadel, roof: "#4F8A62", wall: "#D9D6CC", enterable: false, note: "The Sentinel Citadel opens in a later update."),
        BuildingDef(id: "central-bank", name: "AI Central Bank", x: 5, y: 27, w: 7, h: 6, door: TilePoint(x: 8, y: 32), style: .bank, roof: "#C9A23A", wall: "#F1E9D2", enterable: false, note: "The Bank's interior opens in a later update. Use More → Bank meanwhile."),
        BuildingDef(id: "owners-tower", name: "Owner's Tower", x: 21, y: 25, w: 7, h: 8, door: TilePoint(x: 24, y: 32), style: .tower, roof: "#3D4F8F", wall: "#E2E6EF", enterable: false),
        BuildingDef(id: "memory-vault", name: "Memory Vault", x: 36, y: 27, w: 7, h: 6, door: TilePoint(x: 39, y: 32), style: .vault, roof: "#5A5F73", wall: "#CFCBD8", enterable: false, note: "The Memory Vault opens in a later update."),
    ]

    static let depotId = "logistics-depot"
    static let enterable = buildings.filter(\.enterable).map(\.id)

    static func name(of district: String) -> String {
        if let b = buildings.first(where: { $0.id == district }) { return b.name }
        return ["claude-code-factory": "Claude Code Factory", "github-factory": "GitHub Factory", "codex-factory": "Codex Factory"][district] ?? district
    }

    static func buildTown() -> GameMap {
        let W = 50, H = 38
        let m = GameMap(id: "town", name: "AI Civilization", w: W, h: H, fill: .grass)
        var r = TownRandom(7)
        for i in 0..<(W * H) where r.next() < 0.18 { m.ground[i] = .grass2 }

        m.fill(2, 13, 46, 2, .path)
        m.fill(2, 23, 46, 2, .path)
        m.fill(2, 34, 46, 2, .path)
        m.fill(2, 13, 2, 23, .path)
        m.fill(46, 13, 2, 23, .path)
        m.fill(23, 12, 2, 12, .path)
        m.fill(18, 15, 12, 8, .plaza)
        m.fill(13, 16, 4, 3, .water); m.block(13, 16, 4, 3)
        m.fill(31, 29, 3, 2, .water); m.block(31, 29, 3, 2)

        for b in buildings {
            m.buildings.append(b)
            m.block(b.x, b.y, b.w, b.h)
            m.solid[m.idx(b.door.x, b.door.y)] = false
            m.fill(b.door.x, b.door.y + 1, 1, 1, .path)
            m.fill(b.door.x, b.door.y, 1, 1, .path)
            let avenue = b.door.y < 13 ? 13 : b.door.y < 23 ? 23 : 34
            m.fill(b.door.x, b.door.y + 1, 1, max(0, avenue - b.door.y - 1), .path)
            if b.enterable {
                m.interactables.append(Interactable(id: "door:\(b.id)", x: b.door.x, y: b.door.y, label: "Enter \(b.name)", action: .enter, target: b.id))
            } else if b.id == "owners-tower" {
                m.interactables.append(Interactable(id: "door:\(b.id)", x: b.door.x, y: b.door.y, label: "Owner's Tower: approvals", action: .approvals))
            } else {
                m.interactables.append(Interactable(id: "door:\(b.id)", x: b.door.x, y: b.door.y, label: b.name, action: .closed, target: b.id))
            }
            let dock = TilePoint(x: b.door.x + 2, y: b.door.y + 1)
            m.docks[b.id] = dock
            for y in dock.y...(avenue + 1) { m.belt.insert(m.idx(dock.x, y)) }
        }
        m.add(Prop(kind: .fountain, x: 23, y: 17, w: 2, h: 2))
        for x in 3...46 { for y in [14, 24, 35] { m.belt.insert(m.idx(x, y)) } }
        for y in 14...35 { m.belt.insert(m.idx(3, y)); m.belt.insert(m.idx(46, y)) }
        m.docks[depotId] = TilePoint(x: 46, y: 24)
        m.add(Prop(kind: .crates, x: 48, y: 23, w: 1, h: 2))
        m.interactables.append(Interactable(id: "depot", x: 47, y: 24, label: "Logistics depot (to the factories)", action: .closed, target: depotId))

        for (x, y) in [(6, 12), (19, 12), (33, 12), (19, 22), (29, 22), (12, 33), (29, 33)] { m.add(Prop(kind: .lamp, x: x, y: y)) }
        m.add(Prop(kind: .sign, x: 22, y: 12))
        m.interactables.append(Interactable(id: "sign:plaza", x: 22, y: 12, label: "Read the town sign", action: .journal))
        for (x, y) in [(19, 16), (28, 16), (19, 21), (28, 21)] { m.add(Prop(kind: .bench, x: x, y: y)) }
        m.add(Prop(kind: .stall, x: 31, y: 17, w: 3, h: 2))

        func free(_ x: Int, _ y: Int) -> Bool {
            guard m.inside(x, y), !m.solid[m.idx(x, y)], !m.belt.contains(m.idx(x, y)) else { return false }
            let g = m.ground[m.idx(x, y)]
            return g == .grass || g == .grass2
        }
        for x in 0..<W { for y in [0, 1, H - 2, H - 1] where free(x, y) { m.add(Prop(kind: (x + y) % 3 != 0 ? .tree : .pine, x: x, y: y)) } }
        for y in 2..<(H - 2) {
            for x in [0, 1, W - 2, W - 1] where free(x, y) && !(x >= 48 && y >= 22 && y <= 25) {
                m.add(Prop(kind: (x + y) % 3 != 0 ? .pine : .tree, x: x, y: y))
            }
        }
        let flowerColors = ["#FF8FB8", "#FFD36B", "#B98CFF", "#FFFFFF"]
        for y in 2..<(H - 2) {
            for x in 2..<(W - 2) {
                if !free(x, y) { continue }
                let nearRoad = [(1, 0), (-1, 0), (0, 1), (0, -1)].contains { m.groundAt(x + $0.0, y + $0.1) == .path }
                let nearDoor = m.buildings.contains { abs($0.door.x - x) <= 1 && y >= $0.door.y && y <= $0.door.y + 2 }
                if nearDoor { continue }
                let roll = r.next()
                if !nearRoad && roll < 0.07 { m.add(Prop(kind: r.next() < 0.5 ? .tree : .pine, x: x, y: y)) }
                else if !nearRoad && roll < 0.1 { m.add(Prop(kind: .bush, x: x, y: y)) }
                else if roll < 0.16 { m.add(Prop(kind: .flowers, x: x, y: y, solid: false, color: flowerColors[Int(r.next() * 4)])) }
                else if !nearRoad && roll < 0.175 { m.add(Prop(kind: .rock, x: x, y: y)) }
            }
        }
        for b in m.buildings where b.enterable {
            for dx in [-2, -1, 1] {
                let x = b.door.x + dx, y = b.door.y + 1
                if free(x, y) { m.add(Prop(kind: .flowers, x: x, y: y, solid: false, color: "#FF8FB8")) }
            }
        }
        m.spawn = (24, 20, .up)
        return m
    }

    // MARK: interiors

    private static func room(_ id: String, _ name: String, _ floor: Ground, _ wallColor: String, furnish: (GameMap) -> Void) -> GameMap {
        let W = 18, H = 13
        let m = GameMap(id: id, name: name, w: W, h: H, fill: floor)
        m.fill(0, 0, W, 2, .wall)
        m.block(0, 0, W, 2)
        m.block(0, 0, 1, H)
        m.block(W - 1, 0, 1, H)
        m.block(0, H - 1, W, 1)
        let door = TilePoint(x: 9, y: H - 1)
        m.solid[m.idx(door.x, door.y)] = false
        m.ground[m.idx(door.x, door.y)] = .carpet
        m.interactables.append(Interactable(id: "exit", x: door.x, y: door.y, label: "Leave", action: .exit))
        let outside = buildings.first { $0.id == id }!
        m.exits.append(MapExit(x: door.x, y: door.y, to: "town", at: (outside.door.x, outside.door.y + 1, .down)))
        m.spawn = (door.x, door.y - 1, .up)
        m.props.append(Prop(kind: .window, x: 2, y: 0, w: 2, h: 2, solid: false, color: wallColor))
        m.props.append(Prop(kind: .clock, x: 8, y: 0, solid: false))
        furnish(m)
        return m
    }

    private static func desk(_ m: GameMap, _ x: Int, _ y: Int, facing: Dir = .up) {
        m.add(Prop(kind: .desk, x: x, y: y, w: 2, h: 1))
        m.props.append(Prop(kind: .monitor, x: x, y: y, solid: false))
        m.props.append(Prop(kind: .chair, x: x, y: y + 1, solid: false))
        m.workstations.append(Workstation(x: Double(x) + 0.5, y: Double(y + 1), facing: facing))
    }

    static func buildInterior(_ id: String) -> GameMap? {
        switch id {
        case "nexus-spire":
            return room(id, "Nexus Spire", .carpet, "#7A5CD6") { m in
                m.add(Prop(kind: .screen, x: 6, y: 0, w: 6, h: 2))
                m.add(Prop(kind: .table, x: 5, y: 4, w: 4, h: 2))
                for (x, y) in [(5, 3), (8, 3), (5, 6), (8, 6)] { m.props.append(Prop(kind: .chair, x: x, y: y, solid: false)) }
                m.add(Prop(kind: .whiteboard, x: 13, y: 0, w: 3, h: 2))
                m.interactables.append(Interactable(id: "board", x: 14, y: 2, label: "Mission board", action: .journal))
                m.add(Prop(kind: .terminal, x: 15, y: 5))
                m.interactables.append(Interactable(id: "approvals", x: 14, y: 5, label: "Approval terminal", action: .approvals))
                desk(m, 11, 7)
                desk(m, 3, 8)
                m.add(Prop(kind: .plant, x: 1, y: 2))
                m.add(Prop(kind: .plant, x: 16, y: 10))
                m.add(Prop(kind: .sofa, x: 13, y: 10, w: 2, h: 1))
                m.props.append(Prop(kind: .rug, x: 7, y: 9, w: 5, h: 2, solid: false))
            }
        case "data-observatory":
            return room(id, "Research Observatory", .tile, "#5C7FD6") { m in
                m.add(Prop(kind: .telescope, x: 8, y: 2, w: 2, h: 2))
                m.interactables.append(Interactable(id: "telescope", x: 8, y: 4, label: "Telescope: findings", action: .findings))
                for x in [12, 13, 14, 15] { m.add(Prop(kind: .shelf, x: x, y: 0, h: 2)) }
                desk(m, 2, 4)
                desk(m, 12, 4)
                desk(m, 2, 8)
                m.add(Prop(kind: .table, x: 12, y: 8, w: 3, h: 2))
                m.add(Prop(kind: .plant, x: 1, y: 2))
                m.add(Prop(kind: .plant, x: 16, y: 2))
                m.add(Prop(kind: .cooler, x: 16, y: 7))
            }
        case "code-forge":
            return room(id, "Code Forge", .wood, "#C2553A") { m in
                for x in [13, 14, 15, 16] { m.add(Prop(kind: .server, x: x, y: 2)) }
                m.add(Prop(kind: .anvil, x: 8, y: 3, w: 2, h: 1))
                m.add(Prop(kind: .board, x: 5, y: 0, w: 3, h: 2))
                m.interactables.append(Interactable(id: "build-monitor", x: 6, y: 2, label: "Build monitor", action: .journal))
                desk(m, 2, 5)
                desk(m, 6, 6)
                desk(m, 11, 6)
                m.add(Prop(kind: .printer, x: 16, y: 6))
                m.add(Prop(kind: .plant, x: 1, y: 2))
                m.add(Prop(kind: .sofa, x: 2, y: 10, w: 2, h: 1))
                m.add(Prop(kind: .cooler, x: 16, y: 10))
            }
        default:
            return nil
        }
    }
}
