import Foundation

/// The city's geometry, ported from the website's world engine (packages/world-engine/src: districts.ts, navigation.ts,
/// logistics.ts) and its renderer (apps/web/components/world/District.tsx `towersFor`), so the iPhone draws the same
/// city from the same districts.json: the same gates, walkways, desks, belts, routes and buildings.
enum WorldMap {
    typealias V3 = (x: Double, y: Double, z: Double)

    static let plazaRadius = 11.0
    static let ringRadius = 16.0
    static let beltHeight = 1.2
    static let walkSpeed = 9.0   // tiles per second, as on the web

    static func gate(_ d: District) -> V3 {
        if d.x == 0 && d.z == 0 { return (0, 0, 9) }  // the Nexus Spire's gate faces south, toward the Logistics Network
        return (d.x * 0.72, 0, d.z * 0.72)
    }

    static func terminal(_ d: District, dispatch: Bool) -> V3 {
        let g = gate(d)
        let n = max(0.0001, hypot(g.x, g.z))
        let px = -g.z / n, pz = g.x / n
        let s = dispatch ? 3.0 : -3.0
        return (g.x + px * s, 0, g.z + pz * s)
    }

    /// Where an idle agent stands: in front of its district toward the plaza, spread sideways by slot.
    static func home(_ d: District, slot: Int) -> V3 {
        if d.architecture == "bank", let ws = d.workstations, !ws.isEmpty {
            let w = ws[slot % ws.count]
            return (d.x + w.offset[0] - 1.6, 0, d.z + w.offset[2])
        }
        let g = gate(d)
        let side: Double = slot % 2 == 0 ? 1 : -1
        let spread = Double((slot + 1) / 2) * 4.5 * side
        let dx = -d.x, dz = -d.z
        let len = max(0.0001, hypot(dx, dz))
        if d.x == 0 && d.z == 0 { return (g.x + spread, 0, g.z) }
        return (g.x + (-dz / len) * spread, 0, g.z + (dx / len) * spread)
    }

    static func workstation(_ d: District, _ id: String?, slot: Int) -> V3 {
        if let id, id.hasSuffix(":dispatch") || id.hasSuffix(":receiving") {
            let t = terminal(d, dispatch: id.hasSuffix(":dispatch"))
            let g = gate(d)
            let n = max(0.0001, hypot(g.x, g.z))
            return (t.x - g.x / n * 1.6, 0, t.z - g.z / n * 1.6)
        }
        if let id, let w = d.workstations?.first(where: { $0.id == id }) { return (d.x + w.offset[0], 0, d.z + w.offset[2]) }
        return home(d, slot: slot)
    }

    private static func ringPoint(_ toward: V3) -> V3 {
        let len = hypot(toward.x, toward.z)
        if len < 0.001 { return (0, 0, plazaRadius) }
        return (toward.x / len * plazaRadius, 0, toward.z / len * plazaRadius)
    }

    /// gate → walkway → plaza ring (the short way round) → walkway → gate, as the website routes agents.
    static func route(from: V3, fromDistrict: District?, to toDistrict: District, target: V3) -> [V3] {
        guard let a = fromDistrict, a.id != toDistrict.id else { return [from, target] }
        let ga = gate(a), gb = gate(toDistrict)
        let ra = ringPoint(ga), rb = ringPoint(gb)
        var a0 = atan2(ra.z, ra.x)
        var delta = atan2(rb.z, rb.x) - a0
        while delta > .pi { delta -= 2 * .pi }
        while delta < -.pi { delta += 2 * .pi }
        let steps = max(1, Int(ceil(abs(delta) / (.pi / 8))))
        var arc: [V3] = []
        for _ in 1..<steps {
            a0 += delta / Double(steps)
            arc.append((cos(a0) * plazaRadius, 0, sin(a0) * plazaRadius))
        }
        var out: [V3] = []
        for p in [from, ga, ra] + arc + [rb, gb, target] {
            if let l = out.last, hypot(p.x - l.x, p.z - l.z) <= 0.05 { continue }
            out.append(p)
        }
        return out
    }

    static func length(_ pts: [V3]) -> Double {
        guard pts.count > 1 else { return 0 }
        return (1..<pts.count).reduce(0) { $0 + hypot(pts[$1].x - pts[$1 - 1].x, pts[$1].z - pts[$1 - 1].z) }
    }

    /// Position along a polyline at distance `d`, the heading there, and whether the walk is over.
    static func sample(_ pts: [V3], _ d: Double) -> (pos: V3, heading: Double, done: Bool) {
        guard let first = pts.first else { return ((0, 0, 0), 0, true) }
        var remaining = max(0, d)
        if pts.count == 1 { return (first, 0, true) }
        for i in 1..<pts.count {
            let a = pts[i - 1], b = pts[i]
            let seg = hypot(b.x - a.x, b.z - a.z)
            if remaining <= seg {
                let t = seg == 0 ? 1 : remaining / seg
                return ((a.x + (b.x - a.x) * t, 0, a.z + (b.z - a.z) * t), atan2(b.x - a.x, b.z - a.z), false)
            }
            remaining -= seg
        }
        let last = pts[pts.count - 1], prev = pts[pts.count - 2]
        return (last, atan2(last.x - prev.x, last.z - prev.z), true)
    }

    // MARK: conveyors (mirror of services/logistics/graph.py; the server's graph wins when the snapshot has one)

    struct BeltNode: Hashable { let id: String; let district: String?; let kind: String; let x: Double; let z: Double }
    struct BeltSegment: Hashable { let id: String; let from: String; let to: String; var status: String = "UP"; var load: Int = 0 }

    static func logistics(_ districts: [District]) -> (nodes: [BeltNode], segments: [BeltSegment]) {
        var nodes: [BeltNode] = [], segs: [BeltSegment] = [], junctions: [(Double, String)] = []
        for d in districts {
            let g = gate(d)
            let n = max(0.0001, hypot(g.x, g.z))
            let px = -g.z / n, pz = g.x / n
            let disp = BeltNode(id: "\(d.id):dispatch", district: d.id, kind: "dispatch", x: g.x + px * 3, z: g.z + pz * 3)
            let recv = BeltNode(id: "\(d.id):receiving", district: d.id, kind: "receiving", x: g.x - px * 3, z: g.z - pz * 3)
            let junc = BeltNode(id: "junction:\(d.id)", district: d.id, kind: "junction", x: g.x / n * ringRadius, z: g.z / n * ringRadius)
            nodes += [disp, recv, junc]
            segs.append(BeltSegment(id: "\(disp.id)->\(junc.id)", from: disp.id, to: junc.id))
            segs.append(BeltSegment(id: "\(junc.id)->\(recv.id)", from: junc.id, to: recv.id))
            junctions.append((atan2(junc.z, junc.x), junc.id))
        }
        junctions.sort { Int(($0.0 * 1e6).rounded()) != Int(($1.0 * 1e6).rounded()) ? $0.0 < $1.0 : $0.1 < $1.1 }
        for (i, j) in junctions.enumerated() {
            let b = junctions[(i + 1) % junctions.count].1
            segs.append(BeltSegment(id: "\(j.1)->\(b)", from: j.1, to: b))
            segs.append(BeltSegment(id: "\(b)->\(j.1)", from: b, to: j.1))
        }
        return (nodes, segs)
    }

    // MARK: buildings (port of District.tsx towersFor: same seeded random, same shapes)

    enum Kind { case box, cyl, cone, dome }
    struct Tower { let pos: V3; let size: V3; let rot: Double; let kind: Kind }

    /// The website's string-seeded random (Math.imul-based), so both apps build identical blocks and spires.
    struct Rng {
        private var h: UInt32
        init(_ seed: String) {
            var h: UInt32 = 2166136261
            for c in seed.utf16 { h = (h ^ UInt32(c)) &* 16777619 }
            self.h = h
        }
        mutating func next() -> Double {
            h = (h ^ (h >> 15)) &* 2246822507
            h = (h ^ (h >> 13)) &* 3266489909
            h ^= h >> 16
            return Double(h) / 4294967296
        }
    }

    static func towers(_ d: District) -> [Tower] {
        var r = Rng(d.id)
        var out: [Tower] = []
        let H = d.height ?? 16
        let n = d.towers ?? 1
        switch d.architecture ?? "" {
        case "spire":
            out.append(Tower(pos: (0, H / 2, -2), size: (3.2, H, 3.2), rot: 0, kind: .cone))
            out.append(Tower(pos: (0, 4, -2), size: (7, 8, 7), rot: 0, kind: .cyl))
        case "blocks":
            for i in 0..<n {
                let h = H * (0.45 + r.next() * 0.55)
                let x = (Double(i) - Double(n - 1) / 2) * 4.2
                let z = -3 - r.next() * 4
                let w = 3 + r.next()
                let l = 3 + r.next() * 1.5
                out.append(Tower(pos: (x, h / 2, z), size: (w, h, l), rot: 0, kind: .box))
            }
        case "fortress":
            out.append(Tower(pos: (0, 3.5, -3), size: (12, 7, 7), rot: 0, kind: .box))
            for c in [(-6.0, -6.5), (6, -6.5), (-6, 0.5), (6, 0.5)] { out.append(Tower(pos: (c.0, H / 2, c.1), size: (2.6, H, 2.6), rot: 0, kind: .cyl)) }
        case "twisted":
            for i in 0..<n {
                let h = H * (0.6 + r.next() * 0.4)
                let x = Double(i - 1) * 5
                for k in 0..<5 {
                    out.append(Tower(pos: (x, h / 5 * (Double(k) + 0.5), -3), size: (3, h / 5 - 0.25, 3), rot: Double(k) * .pi / 14 + Double(i), kind: .box))
                }
            }
        case "dome":
            out.append(Tower(pos: (0, 0, -3), size: (7, 7, 7), rot: 0, kind: .dome))
            for i in 0..<n { out.append(Tower(pos: (i == 0 ? -7 : 7, H / 2, -4), size: (1.6, H, 1.6), rot: 0, kind: .cyl)) }
        case "tower":
            out.append(Tower(pos: (0, H / 2, -2), size: (5, H, 5), rot: .pi / 4, kind: .box))
            out.append(Tower(pos: (0, H + 1.5, -2), size: (3.2, 3, 3.2), rot: 0, kind: .cyl))
            out.append(Tower(pos: (0, 2.5, 3), size: (12, 5, 6), rot: 0, kind: .box))
        case "bank":
            out.append(Tower(pos: (2, 2, 0), size: (12, 4, 14), rot: 0, kind: .box))
            out.append(Tower(pos: (2, H / 2, 0), size: (8, H, 8), rot: 0, kind: .box))
            out.append(Tower(pos: (2, H + 2.5, 0), size: (5, 5, 5), rot: .pi / 4, kind: .cone))
        case "factory":
            out.append(Tower(pos: (0, 3, -3), size: (18, 6, 9), rot: 0, kind: .box))
            for i in 0..<4 { out.append(Tower(pos: (-6.75 + Double(i) * 4.5, 7, -3), size: (4.5, 2, 9), rot: 0, kind: .cone)) }
            for i in 0..<n { out.append(Tower(pos: (-6 + Double(i) * 6, H / 2 + 3, -6.5), size: (1.6, H, 1.6), rot: 0, kind: .cyl)) }
        case "vault":
            out.append(Tower(pos: (0, 3, -3), size: (16, 6, 8), rot: 0, kind: .box))
            for i in 0..<n { out.append(Tower(pos: (Double(i - 1) * 5.5, 6 + H / 4, -3), size: (3, H / 2, 3), rot: .pi / 4, kind: .box)) }
        default:
            out.append(Tower(pos: (0, H / 2, 0), size: (8, H, 8), rot: 0, kind: .box))
        }
        return out
    }

    static func islandRadius(_ d: District) -> Double { d.architecture == "bank" ? 19 : d.architecture == "spire" ? 15 : 17 }
    static func deckSize(_ d: District) -> Double { d.architecture == "bank" ? 26 : d.architecture == "spire" ? 0 : 23 }

    /// Where the district's neon sign floats (District.tsx NeonSign).
    static func signHeight(_ d: District) -> Double {
        d.architecture == "bank" ? 14 : d.architecture == "tower" ? 18 : min((d.height ?? 16) * 0.6 + 4, 14)
    }

    static let signIcon: [String: String] = [
        "nexus-spire": "◉", "code-forge": "</>", "sentinel-citadel": "⛉", "vision-quarter": "✎", "data-observatory": "◍",
        "memory-vault": "≣", "owners-tower": "♛", "central-bank": "$", "claude-code-factory": "›_", "github-factory": "⑂",
        "codex-factory": "◎",
    ]

    /// "claude-opus-5-5" → "OPUS 5.5", for the Nexus Spire's "AI Manager (…)" line.
    static func managerModel(_ modelName: String) -> String? {
        guard let r = modelName.range(of: #"claude-([a-z]+)-(\d+)-(\d+)"#, options: .regularExpression) else { return nil }
        let parts = modelName[r].split(separator: "-")
        guard parts.count >= 4 else { return nil }
        return "\(parts[1].uppercased()) \(parts[2]).\(parts[3])"
    }

    /// The website's package colours (lib/format.ts PACKAGE_COLORS).
    static let packageColor: [String: String] = [
        "research_brief": "#5BF2A5", "product_proposal": "#A66BFF", "design_spec": "#FF6178", "code_artifact": "#32D8FF",
        "test_report": "#FFBD69", "revision_request": "#FF6178", "approval_request": "#F4D58D", "release_package": "#F4D58D",
        "revenue_report": "#5BF2A5", "expense_alert": "#FFBD69", "bill_reminder": "#FF9F43", "fee_research_request": "#F4D58D",
        "savings_recommendation": "#7CFFCB", "purchase_request": "#E7C66A", "payment_proposal": "#FF8FA3", "tax_review_package": "#B794FF",
        "financial_forecast": "#9AD1FF", "owner_approval_request": "#FFD86B", "savings_investigation": "#3DFFB8",
        "design_insights": "#7CF7FF", "lab_proposal": "#FFD36B",
    ]

    /// The website's status ring colours (STATE_COLOR).
    static let stateColor: [String: String] = [
        "IDLE": "#8FA8FF", "ASSIGNED": "#32D8FF", "PLANNING": "#32D8FF", "EXECUTING": "#5BF2A5", "WAITING_FOR_TOOL": "#5BF2A5",
        "WAITING_FOR_AGENT": "#FFBD69", "WAITING_FOR_APPROVAL": "#FFBD69", "REVIEWING": "#A66BFF", "COMPLETED": "#5BF2A5",
        "FAILED": "#FF6178", "CANCELLED": "#FF6178",
    ]
}
