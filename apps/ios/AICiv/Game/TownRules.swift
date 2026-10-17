import Foundation

/// Game rules with no drawing: movement and collision, pathfinding for tap-to-move, proximity, where an NPC stands and how
/// it animates, and where a package sits on the conveyor. Animation always follows backend state; it never decides it.
/// Same rules as apps/web/lib/play/engine.ts.
struct Vec: Equatable { var x: Double; var y: Double }

enum Anim: String { case idle, walking, talking, working, researching, coding, testing, waiting, delivering, celebrating }

/// What the game needs to know about an agent: identity and look from the roster, state from backend events.
struct TownAgent: Identifiable, Equatable {
    let id: String
    let key: String
    let name: String
    let role: String
    let homeDistrict: String
    var district: String
    var execState: String
    var moving: Bool
    var carrying: String?
    let look: Agent.Look?
    let color: String
}

/// A conveyor package (a logistics_packages record from the snapshot).
struct TownPackage: Identifiable, Equatable {
    let id: String
    let type: String
    var status: String
    let origin: String
    let destination: String
    var routeStartedAt: Date?
    var eta: Date?
}

enum TownRules {
    static let playerRadius = 0.3
    static let npcRadius = 0.42
    static let walkSpeed = 4.2   // tiles per second

    /// Moves a round body by (dx, dy), sliding along walls and around other bodies.
    static func move(_ m: GameMap, _ p: Vec, dx: Double, dy: Double, blockers: [Vec] = [], r: Double = playerRadius) -> Vec {
        func free(_ x: Double, _ y: Double) -> Bool {
            for (ox, oy) in [(-r, -r * 0.4), (r, -r * 0.4), (-r, r), (r, r)] where m.isSolid(Int(floor(x + ox)), Int(floor(y + oy))) {
                return false
            }
            return blockers.allSatisfy { b in
                let dNew = (b.x - x) * (b.x - x) + (b.y - y) * (b.y - y)
                let dOld = (b.x - p.x) * (b.x - p.x) + (b.y - p.y) * (b.y - p.y)
                return dNew >= (npcRadius + r) * (npcRadius + r) || dNew > dOld   // overlapping already: allow moving apart
            }
        }
        var x = p.x, y = p.y
        if dx != 0 && free(x + dx, y) { x += dx }
        if dy != 0 && free(x, y + dy) { y += dy }
        return Vec(x: x, y: y)
    }

    static func facing(_ dx: Double, _ dy: Double, _ prev: Dir) -> Dir {
        if abs(dx) < 1e-4 && abs(dy) < 1e-4 { return prev }
        return abs(dx) > abs(dy) ? (dx > 0 ? .right : .left) : (dy > 0 ? .down : .up)
    }

    /// A* over walkable tiles (4-way). Returns tile centres from the step after `from` to `to`, or [] if unreachable.
    /// Tapping a wall or an NPC walks to the nearest open tile instead.
    static func path(_ m: GameMap, from: Vec, to: Vec, blocked: Set<Int> = [], limit: Int = 4000) -> [Vec] {
        let sx = Int(floor(from.x)), sy = Int(floor(from.y))
        var tx = Int(floor(to.x)), ty = Int(floor(to.y))
        let open = { (x: Int, y: Int) -> Bool in !m.isSolid(x, y) && !blocked.contains(y * m.w + x) }
        if !open(tx, ty) {
            var best: TilePoint?
            for r in 1...4 where best == nil {
                var ring: [TilePoint] = []
                for dy in -r...r { for dx in -r...r where max(abs(dx), abs(dy)) == r { ring.append(TilePoint(x: tx + dx, y: ty + dy)) } }
                best = ring.filter { open($0.x, $0.y) }.min { a, b in
                    let da = hypot(Double(a.x - tx), Double(a.y - ty)), db = hypot(Double(b.x - tx), Double(b.y - ty))
                    if da != db { return da < db }
                    return hypot(Double(a.x - sx), Double(a.y - sy)) < hypot(Double(b.x - sx), Double(b.y - sy))
                }
            }
            guard let n = best else { return [] }
            tx = n.x; ty = n.y
        }
        if sx == tx && sy == ty { return [Vec(x: Double(tx) + 0.5, y: Double(ty) + 0.5)] }
        let key = { (x: Int, y: Int) in y * m.w + x }
        let start = key(sx, sy)
        var g: [Int: Int] = [start: 0]
        var came: [Int: Int] = [:]
        var frontier: [(k: Int, f: Int)] = [(start, 0)]
        var closed = Set<Int>()
        var steps = 0
        while !frontier.isEmpty && steps < limit {
            steps += 1
            frontier.sort { $0.f < $1.f }
            let k = frontier.removeFirst().k
            if closed.contains(k) { continue }
            closed.insert(k)
            let cx = k % m.w, cy = k / m.w
            if cx == tx && cy == ty {
                var out: [Vec] = []
                var c: Int? = k
                while let cur = c, cur != start {
                    out.append(Vec(x: Double(cur % m.w) + 0.5, y: Double(cur / m.w) + 0.5))
                    c = came[cur]
                }
                return out.reversed()
            }
            for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                let nx = cx + dx, ny = cy + dy, nk = key(nx, ny)
                if m.isSolid(nx, ny) || closed.contains(nk) || (blocked.contains(nk) && !(nx == tx && ny == ty)) { continue }
                let ng = (g[k] ?? 0) + 1
                if ng < (g[nk] ?? Int.max) {
                    g[nk] = ng
                    came[nk] = k
                    frontier.append((nk, ng + abs(nx - tx) + abs(ny - ty)))
                }
            }
        }
        return []
    }

    // MARK: agents follow backend state

    static let researchKeys: Set<String> = ["researcher", "research_apps", "research_marketplaces"]
    static let codeKeys: Set<String> = ["developer", "architect"]

    static func anim(_ a: TownAgent, talking: Bool = false) -> Anim {
        if talking { return .talking }
        if a.moving { return a.carrying != nil ? .delivering : .walking }
        switch a.execState {
        case "EXECUTING", "WAITING_FOR_TOOL":
            return researchKeys.contains(a.key) ? .researching : codeKeys.contains(a.key) ? .coding : a.key == "qa" ? .testing : .working
        case "ASSIGNED", "PLANNING": return .working
        case "REVIEWING": return a.key == "qa" ? .testing : .working
        case "WAITING_FOR_AGENT", "WAITING_FOR_APPROVAL": return .waiting
        case "COMPLETED": return .celebrating
        default: return .idle
        }
    }

    static func statusLabel(_ a: TownAgent) -> String {
        if a.moving { return a.carrying.map { "Delivering \($0)" } ?? "Walking" }
        return [
            "IDLE": "Idle", "ASSIGNED": "Assigned", "PLANNING": "Planning", "EXECUTING": "Working", "WAITING_FOR_TOOL": "Waiting on a tool",
            "WAITING_FOR_AGENT": "Waiting on a teammate", "WAITING_FOR_APPROVAL": "Needs your approval", "REVIEWING": "Reviewing",
            "COMPLETED": "Finished", "FAILED": "Task failed", "CANCELLED": "Cancelled",
        ][a.execState] ?? a.execState
    }

    struct Placed { let agent: TownAgent; let x: Double; let y: Double; let facing: Dir; let anim: Anim }

    /// Indoors, NPCs at work sit at their desk (back to you); otherwise they stand beside it facing the room.
    /// Agents on the move appear on the road, walking between buildings (visual only).
    static func place(_ m: GameMap, _ agents: [TownAgent], now: TimeInterval, talkingTo: String?, town: GameMap) -> [Placed] {
        var out: [Placed] = []
        if m.id == "town" {
            for a in agents where a.moving {
                guard let from = town.docks[a.homeDistrict] ?? town.docks[Town.depotId],
                      let to = town.docks[a.district] ?? town.docks[Town.depotId], from != to else { continue }
                let route = roadPath(town, from, to)
                guard !route.isEmpty else { continue }
                let t = (now * 2.5).truncatingRemainder(dividingBy: Double(route.count))
                let i = Int(t), f = t - Double(i)
                let p0 = route[i], p1 = route[min(route.count - 1, i + 1)]
                out.append(Placed(agent: a, x: p0.x + (p1.x - p0.x) * f, y: p0.y + (p1.y - p0.y) * f,
                                  facing: facing(p1.x - p0.x, p1.y - p0.y, .down), anim: anim(a, talking: talkingTo == a.id)))
            }
            return out
        }
        let here = agents.filter { $0.district == m.id && !$0.moving }.sorted {
            let ah = $0.homeDistrict == m.id, bh = $1.homeDistrict == m.id
            return ah != bh ? ah : $0.id < $1.id
        }
        let spare = standingSpots(m)
        for (i, a) in here.enumerated() {
            // more agents than desks: free floor tiles, never inside a wall or furniture
            let k = i - m.workstations.count
            let w = i < m.workstations.count ? m.workstations[i] : (k < spare.count ? spare[k] : Workstation(x: 8, y: 10, facing: .down))
            let an = anim(a, talking: talkingTo == a.id)
            let seated = an == .working || an == .coding || an == .researching || an == .testing
            out.append(Placed(agent: a, x: seated ? w.x : w.x + 1, y: seated ? w.y + 0.4 : w.y + 0.6, facing: seated ? w.facing : .down, anim: an))
        }
        return out
    }

    /// Floor tiles for agents without a desk (as Workstations whose "standing" spot is the tile's centre), clear of
    /// walls, furniture, chairs and the walkway to the door.
    static func standingSpots(_ m: GameMap) -> [Workstation] {
        let taken = Set(m.props.filter { !$0.solid }.flatMap { p in (0..<max(1, p.w)).map { (p.y * m.w) + p.x + $0 } })
        var out: [Workstation] = []
        for y in stride(from: m.h - 2, through: 2, by: -1) {
            for x in stride(from: 2, to: m.w - 1, by: 2) where x != m.spawn.x && !m.isSolid(x, y) && !taken.contains(y * m.w + x) {
                out.append(Workstation(x: Double(x) - 0.5, y: Double(y), facing: .down))
            }
        }
        return out
    }

    private static var roadCache: [String: [Vec]] = [:]
    private static func roadPath(_ town: GameMap, _ from: TilePoint, _ to: TilePoint) -> [Vec] {
        let k = "\(from.x),\(from.y)>\(to.x),\(to.y)"
        if let hit = roadCache[k] { return hit }
        let p = path(town, from: Vec(x: Double(from.x) + 0.5, y: Double(from.y) + 0.5), to: Vec(x: Double(to.x) + 0.5, y: Double(to.y) + 0.5))
        roadCache[k] = p
        return p
    }

    // MARK: packages on the conveyor

    /// Breadth-first route along conveyor tiles between two docks.
    static func beltRoute(_ m: GameMap, _ from: TilePoint, _ to: TilePoint) -> [Vec] {
        let start = m.idx(from.x, from.y), goal = m.idx(to.x, to.y)
        guard m.belt.contains(start), m.belt.contains(goal) else { return [] }
        var prev: [Int: Int] = [start: -1]
        var queue = [start], head = 0
        while head < queue.count {
            let c = queue[head]; head += 1
            if c == goal { break }
            let cx = c % m.w, cy = c / m.w
            for (dx, dy) in [(1, 0), (-1, 0), (0, 1), (0, -1)] {
                let nx = cx + dx, ny = cy + dy
                guard nx >= 0, nx < m.w, ny >= 0, ny < m.h else { continue }
                let n = m.idx(nx, ny)
                if !m.belt.contains(n) || prev[n] != nil { continue }
                prev[n] = c
                queue.append(n)
            }
        }
        guard prev[goal] != nil else { return [] }
        var out: [Vec] = []
        var c = goal
        while c != -1 {
            out.append(Vec(x: Double(c % m.w) + 0.5, y: Double(c / m.w) + 0.5))
            c = prev[c] ?? -1
        }
        return out.reversed()
    }

    static func dock(_ m: GameMap, _ district: String) -> TilePoint {
        m.docks[district] ?? m.docks[Town.depotId] ?? TilePoint(x: 0, y: 0)
    }

    struct PackagePoint { let id: String; let x: Double; let y: Double; let progress: Double; let package: TownPackage }

    private static var beltCache: [String: [Vec]] = [:]

    /// Queued at its origin dock, moving along the belt by its server-side route clock while in transit, waiting at the
    /// destination once arrived. Received and cancelled packages aren't drawn. Moving isn't proof the work is done.
    static func packagePoint(_ m: GameMap, _ p: TownPackage, serverNow: Date) -> PackagePoint? {
        if p.status == "RECEIVED" || p.status == "CANCELLED" { return nil }
        let from = dock(m, p.origin), to = dock(m, p.destination)
        let k = "\(p.origin)>\(p.destination)"
        let route: [Vec]
        if let hit = beltCache[k] { route = hit } else { route = beltRoute(m, from, to); beltCache[k] = route }
        var progress = 0.0
        if p.status == "ARRIVED" { progress = 1 }
        else if p.status == "IN_TRANSIT", let s = p.routeStartedAt, let e = p.eta {
            let span = e.timeIntervalSince(s)
            progress = span > 0 ? min(1, max(0, serverNow.timeIntervalSince(s) / span)) : 1
        }
        if route.count < 2 {
            let d = progress >= 1 ? to : from
            return PackagePoint(id: p.id, x: Double(d.x) + 0.5, y: Double(d.y) + 0.5, progress: progress, package: p)
        }
        let t = progress * Double(route.count - 1)
        let i = min(route.count - 2, Int(t)), f = t - Double(i)
        return PackagePoint(id: p.id, x: route[i].x + (route[i + 1].x - route[i].x) * f, y: route[i].y + (route[i + 1].y - route[i].y) * f,
                            progress: progress, package: p)
    }

    static let packageLabel: [String: String] = [
        "research_brief": "Research brief", "product_proposal": "Product proposal", "code_artifact": "Code", "test_report": "Test report",
        "release_package": "Release for your review", "revision_request": "Revision request", "bill_reminder": "Bill reminder",
        "payment_proposal": "Payment proposal", "purchase_request": "Purchase request", "tax_review_package": "Tax review",
    ]
}
