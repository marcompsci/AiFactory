import Foundation

/// Pixel art for the town and interiors, painted from code at 16 px per tile: ground, props and building fronts.
/// Original art in a cozy top-down RPG style (same as apps/web/lib/play/art.ts).
enum PixelArt {
    static let T = Town.tile

    enum C {
        static let grass = "#5FAE4C", grassDark = "#4C9A3F", grassLight = "#79C25C"
        static let path = "#D9B27A", pathDark = "#BF955E", pathLight = "#E8C793"
        static let stone = "#B7BAC2", stoneDark = "#8C909B", stoneLight = "#D3D6DC"
        static let water = "#4AA3DC", waterLight = "#8FD3F5", waterDark = "#3787C1"
        static let wood = "#C4884C", woodDark = "#9B6534", woodLight = "#DDA56A"
        static let trunk = "#7A4E2C", leaf = "#3F9A47", leafDark = "#2E7A3A", leafLight = "#6CC45A"
        static let glass = "#7EC8F2", glassDark = "#4E8FC7"
    }

    static let shadow18 = RGBA.alpha(0, 0, 0, 0.18), shadow15 = RGBA.alpha(0, 0, 0, 0.15), shadow20 = RGBA.alpha(0, 0, 0, 0.2)

    // MARK: ground

    static func groundLayer(_ m: GameMap) -> PixelCanvas {
        let c = PixelCanvas(m.w * T, m.h * T)
        for y in 0..<m.h { for x in 0..<m.w { paintGround(c, m, x, y) } }
        for p in m.props where p.kind == .flowers || p.kind == .rug { paintFlat(c, p) }
        return c
    }

    private static func paintGround(_ c: PixelCanvas, _ m: GameMap, _ x: Int, _ y: Int) {
        let g = m.ground[m.idx(x, y)]
        let px = x * T, py = y * T
        func h(_ i: Int) -> Double { tileHash(x, y, i) }
        switch g {
        case .grass, .grass2:
            c.rect(px, py, T, T, C.grass)
            for i in 0..<6 {
                let tx = Int(h(i) * 15), ty = Int(h(i + 9) * 14)
                c.rect(px + tx, py + ty, 1, 2, h(i + 3) < 0.5 ? C.grassDark : C.grassLight)
            }
            if g == .grass2 {
                let tx = 3 + Int(h(20) * 9), ty = 4 + Int(h(21) * 8)
                c.rect(px + tx, py + ty, 1, 2, C.grassDark); c.rect(px + tx + 2, py + ty, 1, 2, C.grassDark); c.rect(px + tx + 1, py + ty + 1, 1, 2, C.grassDark)
            }
        case .path:
            c.rect(px, py, T, T, C.path)
            for i in 0..<5 { c.rect(px + Int(h(i) * 15), py + Int(h(i + 5) * 15), 2, 1, h(i + 7) < 0.5 ? C.pathDark : C.pathLight) }
            func edge(_ dx: Int, _ dy: Int) -> Bool { let n = m.groundAt(x + dx, y + dy); return n == .grass || n == .grass2 }
            if edge(0, -1) { c.rect(px, py, T, 1, C.pathDark); for i in stride(from: 0, to: 16, by: 3) { c.rect(px + i, py, 1, 2, C.grassDark) } }
            if edge(0, 1) { c.rect(px, py + 15, T, 1, C.pathDark) }
            if edge(-1, 0) { c.rect(px, py, 1, T, C.pathDark) }
            if edge(1, 0) { c.rect(px + 15, py, 1, T, C.pathDark) }
        case .plaza:
            c.rect(px, py, T, T, C.stoneDark)
            let off = (y % 2) * 4
            for row in 0..<2 {
                for col in -1..<2 {
                    let sx = px + col * 8 + off + (row == 1 ? 4 : 0), sy = py + row * 8
                    let cx0 = max(px, sx + 1), cx1 = min(px + 16, sx + 8)
                    if cx1 > cx0 {
                        c.rect(cx0, sy + 1, cx1 - cx0, 6, tileHash(x * 3 + col, y * 2 + row) < 0.3 ? C.stoneLight : C.stone)
                        c.rect(cx0, sy + 6, cx1 - cx0, 1, shade(C.stone, -0.1))
                    }
                }
            }
        case .water:
            c.rect(px, py, T, T, C.water)
            c.rect(px + Int(h(1) * 10), py + 4 + Int(h(2) * 8), 4, 1, C.waterLight)
            func land(_ dx: Int, _ dy: Int) -> Bool { m.groundAt(x + dx, y + dy) != .water }
            if land(0, -1) { c.rect(px, py, T, 3, C.waterDark); c.rect(px, py, T, 1, C.stoneDark) }
            if land(-1, 0) { c.rect(px, py, 2, T, C.waterLight) }
            if land(1, 0) { c.rect(px + 14, py, 2, T, C.waterLight) }
            if land(0, 1) { c.rect(px, py + 14, T, 2, C.waterLight) }
        case .wood:
            c.rect(px, py, T, T, C.wood)
            for i in 0..<4 {
                c.rect(px, py + i * 4 + 3, T, 1, C.woodDark)
                let j = Int(tileHash(x, y * 4 + i) * 14)
                c.rect(px + j, py + i * 4, 1, 3, C.woodDark)
                c.rect(px + ((j + 5) % 15), py + i * 4 + 1, 2, 1, C.woodLight)
            }
        case .tile:
            c.rect(px, py, T, T, (x + y) % 2 == 0 ? "#E6ECF2" : "#D4DCE6")
            c.rect(px, py + 15, T, 1, "#BFC9D6"); c.rect(px + 15, py, 1, T, "#BFC9D6")
        case .carpet:
            c.rect(px, py, T, T, "#4E4A86")
            if (x + y) % 2 == 0 { c.rect(px + 6, py + 6, 4, 4, "#5D58A0"); c.rect(px + 7, py + 7, 2, 2, "#6F69B5") }
        case .metal:
            c.rect(px, py, T, T, "#9AA3B2")
            c.rect(px + 2, py + 2, 1, 1, "#C9D0DB"); c.rect(px + 13, py + 13, 1, 1, "#C9D0DB")
        case .wall:
            c.rect(px, py, T, T, "#EFE7DA")
            if y == 0 { c.rect(px, py, T, 4, "#5A4A6E"); c.rect(px, py + 4, T, 1, "#3E3150") }
            else { c.rect(px, py + 11, T, 5, "#C9B79E"); c.rect(px, py + 11, T, 1, "#A99577"); c.rect(px, py + 15, T, 1, "#7E6B52") }
            for i in 0..<3 { c.rect(px + Int(tileHash(x, y, i) * 15), py + 5 + Int(tileHash(y, x, i) * 5), 1, 1, "#E2D8C8") }
        }
    }

    private static func paintFlat(_ c: PixelCanvas, _ p: Prop) {
        let px = p.x * T, py = p.y * T
        if p.kind == .flowers {
            let col = p.color ?? "#FF8FB8"
            for (fx, fy) in [(3, 4), (10, 3), (6, 10), (12, 11)] {
                c.rect(px + fx, py + fy + 2, 1, 3, C.leafDark)
                c.rect(px + fx - 1, py + fy, 3, 3, col); c.rect(px + fx, py + fy + 1, 1, 1, "#FFE66B")
            }
        } else if p.kind == .rug {
            let w = p.w * T, h = p.h * T
            c.rect(px, py, w, h, "#B5476B"); c.rect(px + 2, py + 2, w - 4, h - 4, "#D9668A"); c.rect(px + 5, py + 5, w - 10, h - 10, "#B5476B")
            for i in stride(from: 4, to: w - 4, by: 4) { c.rect(px + i, py - 1, 1, 2, "#F4D58D"); c.rect(px + i, py + h - 1, 1, 2, "#F4D58D") }
        }
    }

    /// The conveyor layer, one of four animation frames (stripes shift a pixel each frame).
    static func beltLayer(_ m: GameMap, frame shift: Int) -> PixelCanvas {
        let c = PixelCanvas(m.w * T, m.h * T)
        for i in m.belt {
            let x = i % m.w, y = i / m.w
            let hz = m.belt.contains(i - 1) || m.belt.contains(i + 1)
            let vt = m.belt.contains(i - m.w) || m.belt.contains(i + m.w)
            let px = x * T, py = y * T
            if hz { c.rect(px, py + 4, T, 8, "#3A3448") }
            if vt { c.rect(px + 4, py, 8, T, "#3A3448") }
            if hz { for k in -1..<5 { c.rect(px + k * 4 + shift, py + 5, 2, 6, "#5A5470") } }
            if vt { for k in -1..<5 { c.rect(px + 5, py + k * 4 + shift, 6, 2, "#5A5470") } }
            if hz { c.rect(px, py + 3, T, 1, "#24202E"); c.rect(px, py + 12, T, 1, "#24202E") }
            if vt { c.rect(px + 3, py, 1, T, "#24202E"); c.rect(px + 12, py, 1, T, "#24202E") }
        }
        // stripes from one tile can spill into the next; redraw the rails' edges cleanly around each tile is enough at this scale
        for (id, d) in m.docks {
            let px = d.x * T, py = d.y * T
            c.rect(px + 1, py + 1, 14, 14, "#24202E")
            c.rect(px + 3, py + 3, 10, 10, id == Town.depotId ? "#F4D58D" : "#32D8FF")
            c.rect(px + 5, py + 5, 6, 6, "#24202E")
        }
        return c
    }

    // MARK: standing props (depth-sorted with characters)

    struct Sprite { let canvas: PixelCanvas; let ox: Int; let oy: Int; let baseY: Int }

    static func propSprites(_ m: GameMap) -> [Sprite] {
        m.props.filter { $0.kind != .flowers && $0.kind != .rug }.map { p in
            let (c, ox, oy) = makeProp(p)
            let onWall: Set<Deco> = [.window, .clock, .whiteboard, .board, .screen]
            let baseY = onWall.contains(p.kind) ? -1 : (p.y + p.h) * T - (p.kind == .chair ? 10 : p.kind == .monitor ? -2 : 0)
            return Sprite(canvas: c, ox: p.x * T + ox, oy: p.y * T + oy, baseY: baseY)
        }
    }

    private static var propCache: [String: (PixelCanvas, Int, Int)] = [:]

    // swiftlint:disable:next cyclomatic_complexity function_body_length
    static func makeProp(_ p: Prop) -> (PixelCanvas, Int, Int) {
        let w = p.w * T, h = p.h * T
        let v = (p.x * 7 + p.y * 3) % 3
        let key = "\(p.kind.rawValue):\(p.w)x\(p.h):\(p.color ?? ""):\(v)"
        if let hit = propCache[key] { return hit }
        var out: (PixelCanvas, Int, Int)
        switch p.kind {
        case .tree:
            let x = PixelCanvas(22, 30)
            x.rect(9, 20, 4, 8, C.trunk); x.rect(9, 20, 1, 8, shade(C.trunk, -0.3))
            x.rect(7, 28, 8, 2, shadow18)
            let leaf = v == 2 ? "#4FA83F" : C.leaf
            x.rect(3, 4, 16, 14, leaf); x.rect(1, 7, 20, 9, leaf); x.rect(5, 2, 12, 2, leaf); x.rect(7, 1, 8, 1, leaf)
            x.rect(3, 15, 16, 3, C.leafDark); x.rect(1, 13, 2, 3, C.leafDark); x.rect(19, 13, 2, 3, C.leafDark)
            x.rect(6, 4, 4, 2, C.leafLight); x.rect(4, 7, 3, 2, C.leafLight); x.rect(12, 3, 3, 2, C.leafLight)
            if v == 1 { for (a, b) in [(6, 9), (14, 7), (10, 12)] { x.rect(a, b, 2, 2, "#F28C38"); x.rect(a, b, 1, 1, "#FFC36B") } }
            if v == 2 { for (a, b) in [(5, 10), (13, 6), (9, 13), (16, 11)] { x.rect(a, b, 1, 1, "#FFD1E8") } }
            out = (x, -3, -14)
        case .pine:
            let x = PixelCanvas(18, 30)
            x.rect(7, 24, 4, 5, C.trunk); x.rect(6, 28, 8, 2, shadow18)
            let g = "#2F8A4A", gd = "#22683A", gl = "#4DAE5E"
            for i in 0..<3 {
                let top = 2 + i * 7, wid = 8 + i * 4
                for j in 0..<9 { let ww = min(wid, 2 + j * 2); x.rect(9 - ww / 2, top + j, ww, 1, j == 8 ? gd : g) }
                x.rect(7, top + 2, 2, 2, gl)
            }
            out = (x, -1, -14)
        case .bush:
            let x = PixelCanvas(16, 16)
            x.rect(2, 14, 12, 2, shadow15)
            x.rect(1, 5, 14, 9, C.leaf); x.rect(3, 3, 10, 2, C.leaf); x.rect(2, 12, 12, 2, C.leafDark); x.rect(4, 5, 3, 2, C.leafLight)
            x.rect(9, 7, 2, 2, "#E2465E"); x.rect(5, 10, 2, 2, "#E2465E")
            out = (x, 0, 0)
        case .rock:
            let x = PixelCanvas(16, 16)
            x.rect(3, 7, 10, 7, C.stoneDark); x.rect(4, 6, 8, 6, C.stone); x.rect(5, 7, 3, 2, C.stoneLight); x.rect(3, 13, 10, 1, "#6E727C")
            out = (x, 0, 0)
        case .lamp:
            let x = PixelCanvas(16, 32)
            x.rect(7, 8, 2, 22, "#3A3448"); x.rect(5, 29, 6, 2, "#3A3448")
            x.rect(4, 2, 8, 7, "#3A3448"); x.rect(5, 3, 6, 5, "#FFE08A"); x.rect(6, 4, 2, 2, "#FFF6CF"); x.rect(6, 0, 4, 2, "#3A3448")
            out = (x, 0, -16)
        case .sign:
            let x = PixelCanvas(16, 24)
            x.rect(7, 12, 2, 12, C.woodDark); x.rect(1, 3, 14, 10, C.woodDark); x.rect(2, 4, 12, 8, C.wood)
            x.rect(4, 6, 8, 1, C.woodDark); x.rect(4, 9, 6, 1, C.woodDark)
            out = (x, 0, -8)
        case .bench:
            let x = PixelCanvas(16, 16)
            x.rect(1, 5, 14, 3, C.woodDark); x.rect(1, 9, 14, 3, C.wood); x.rect(2, 12, 2, 3, "#3A3448"); x.rect(12, 12, 2, 3, "#3A3448")
            out = (x, 0, 0)
        case .fountain:
            let x = PixelCanvas(32, 36)
            x.rect(1, 14, 30, 20, C.stoneDark); x.rect(2, 15, 28, 17, C.stone); x.rect(4, 17, 24, 13, C.water); x.rect(6, 19, 6, 1, C.waterLight)
            x.rect(13, 6, 6, 14, C.stoneDark); x.rect(14, 6, 4, 13, C.stone); x.rect(10, 4, 12, 3, C.stoneDark)
            x.rect(15, 0, 2, 5, C.waterLight); x.rect(11, 3, 2, 2, C.waterLight); x.rect(19, 3, 2, 2, C.waterLight)
            x.rect(1, 33, 30, 2, shadow20)
            out = (x, 0, -4)
        case .stall:
            let x = PixelCanvas(48, 36)
            x.rect(3, 14, 2, 20, C.woodDark); x.rect(43, 14, 2, 20, C.woodDark)
            for i in 0..<8 { x.rect(1 + i * 6, 6, 6, 9, i % 2 == 1 ? "#FFFFFF" : "#F07A3A") }
            x.rect(1, 14, 46, 2, "#C25A28"); x.rect(1, 4, 46, 2, "#C25A28")
            x.rect(4, 22, 40, 10, C.wood); x.rect(4, 22, 40, 2, C.woodLight)
            x.rect(8, 19, 5, 4, "#E2465E"); x.rect(16, 19, 5, 4, "#FFD36B"); x.rect(26, 19, 5, 4, "#7FD3FF"); x.rect(34, 19, 5, 4, "#9B6BE0")
            out = (x, 0, -4)
        case .crates:
            let x = PixelCanvas(16, 32)
            for y in [4, 18] { x.rect(1, y, 14, 12, C.woodDark); x.rect(2, y + 1, 12, 10, C.wood); x.rect(2, y + 5, 12, 1, C.woodDark); x.rect(7, y + 1, 1, 10, C.woodDark) }
            out = (x, 0, 0)
        case .desk:
            let x = PixelCanvas(w, 20)
            x.rect(0, 2, w, 10, "#B07A45"); x.rect(0, 2, w, 2, "#CF9A5E"); x.rect(0, 11, w, 3, "#8A5A30")
            x.rect(2, 12, 2, 8, "#6B4424"); x.rect(w - 4, 12, 2, 8, "#6B4424")
            x.rect(4, 5, 8, 3, "#3A3448"); x.rect(5, 6, 6, 1, "#5A5470"); x.rect(w - 10, 4, 4, 5, "#F2F2F2"); x.rect(w - 9, 5, 2, 3, "#C9D3E0")
            out = (x, 0, -4)
        case .monitor:
            let x = PixelCanvas(16, 16)
            x.rect(2, 0, 12, 9, "#2A2838"); x.rect(3, 1, 10, 7, "#4FB6F0"); x.rect(4, 2, 5, 1, "#BFE9FF"); x.rect(4, 4, 7, 1, "#8FD3F5"); x.rect(4, 6, 4, 1, "#8FD3F5")
            x.rect(7, 9, 2, 2, "#2A2838"); x.rect(5, 11, 6, 1, "#2A2838")
            out = (x, 4, -8)
        case .chair:
            let x = PixelCanvas(16, 16)
            x.rect(4, 2, 8, 7, "#2F3A5E"); x.rect(5, 3, 6, 5, "#3E4C78"); x.rect(3, 9, 10, 3, "#2F3A5E"); x.rect(7, 12, 2, 2, "#1D2136"); x.rect(4, 14, 8, 1, "#1D2136")
            out = (x, 4, 0)
        case .shelf:
            let x = PixelCanvas(16, 32)
            x.rect(0, 0, 16, 32, "#7A4E2C"); x.rect(1, 1, 14, 30, "#5A3A20")
            let books = ["#E2465E", "#3F8CFF", "#FFD36B", "#5BF2A5", "#9B6BE0", "#F28C38", "#F2F2F2"]
            for sy in [2, 11, 20] {
                var bx = 2
                while bx < 14 {
                    let bw = 1 + Int(tileHash(bx, sy, p.x) * 2)
                    x.rect(bx, sy + 1 + Int(tileHash(sy, bx) * 2), bw, 7, books[Int(tileHash(bx, sy + p.x) * Double(books.count)) % books.count])
                    bx += bw
                }
                x.rect(1, sy + 8, 14, 1, "#8A5A30")
            }
            out = (x, 0, 0)
        case .plant:
            let x = PixelCanvas(16, 24)
            x.rect(4, 16, 8, 7, "#C2553A"); x.rect(4, 16, 8, 2, "#DA6E4F")
            for (a, b, ww, hh) in [(7, 2, 2, 14), (3, 5, 4, 6), (9, 4, 5, 7), (5, 9, 6, 6), (2, 10, 3, 4), (11, 10, 3, 4)] { x.rect(a, b, ww, hh, C.leaf) }
            x.rect(4, 6, 2, 2, C.leafLight); x.rect(10, 5, 2, 2, C.leafLight)
            out = (x, 0, -8)
        case .whiteboard, .board:
            let x = PixelCanvas(w, 28)
            x.rect(0, 4, w, 20, "#8C909B"); x.rect(1, 5, w - 2, 18, "#FBFCFE")
            if p.kind == .board { x.rect(1, 5, w - 2, 18, "#2D4A3E"); for i in 0..<4 { x.rect(4, 8 + i * 4, 6 + ((i * 7) % 14), 1, "#E8F5EC") } }
            else { x.rect(4, 8, 12, 1, "#3F8CFF"); x.rect(4, 11, 18, 1, "#E2465E"); x.rect(4, 14, 9, 1, "#2B2F3A"); x.rect(26, 9, 10, 8, "#FFD36B"); x.rect(4, 17, 14, 1, "#2B2F3A") }
            x.rect(2, 23, w - 4, 2, "#8C909B")
            out = (x, 0, 0)
        case .screen:
            let x = PixelCanvas(w, 30)
            x.rect(0, 2, w, 26, "#1E1B2E"); x.rect(2, 4, w - 4, 22, "#162447")
            var lx = 4, ly = 20
            for i in 0..<16 {
                let ny = 8 + Int(tileHash(i, 3) * 14)
                x.rect(lx, min(ly, ny), 5, 1, "#5BF2A5"); lx += 5; ly = ny
                if lx > w - 8 { break }
            }
            x.rect(6, 7, 18, 2, "#C9A7FF"); x.rect(w - 22, 7, 16, 8, "#2E3B6B"); x.rect(w - 20, 9, 12, 1, "#F4D58D"); x.rect(w - 20, 12, 8, 1, "#5BF2A5")
            out = (x, 0, 0)
        case .table:
            let x = PixelCanvas(w, h)
            x.rect(1, 2, w - 2, h - 6, "#B9D9EC"); x.rect(2, 3, w - 4, h - 8, "#D6ECF7"); x.rect(4, 4, 8, 1, "#FFFFFF")
            x.rect(3, h - 4, 2, 4, "#7A8696"); x.rect(w - 5, h - 4, 2, 4, "#7A8696")
            out = (x, 0, 0)
        case .sofa:
            let x = PixelCanvas(w, 20)
            x.rect(0, 2, w, 14, "#6B3FA0"); x.rect(2, 4, w - 4, 6, "#8250BD"); x.rect(0, 10, w, 6, "#5A3388"); x.rect(w / 2 - 1, 4, 1, 6, "#5A3388")
            x.rect(1, 16, 2, 3, "#3A2A20"); x.rect(w - 3, 16, 2, 3, "#3A2A20")
            out = (x, 0, -4)
        case .telescope:
            let x = PixelCanvas(32, 40)
            x.rect(4, 30, 24, 8, "#5A5F73"); x.rect(6, 30, 20, 2, "#7A8096")
            x.rect(14, 18, 4, 12, "#3A3448")
            for i in 0..<14 { x.rect(6 + i, 18 - i, 7, 5, i < 2 ? "#8C6A2E" : "#C9A23A") }
            x.rect(19, 3, 7, 5, "#8C6A2E"); x.rect(21, 4, 3, 2, "#BFE9FF")
            out = (x, 0, -8)
        case .server:
            let x = PixelCanvas(16, 30)
            x.rect(1, 0, 14, 30, "#2A2838"); x.rect(2, 1, 12, 28, "#3A3850")
            for i in 0..<6 { x.rect(3, 3 + i * 4, 10, 3, "#22202E"); x.rect(4, 4 + i * 4, 1, 1, i % 2 == 1 ? "#5BF2A5" : "#32D8FF"); x.rect(6, 4 + i * 4, 1, 1, "#FFBD69") }
            out = (x, 0, -14)
        case .anvil:
            let x = PixelCanvas(32, 24)
            x.rect(2, 6, 28, 6, "#4A4E5C"); x.rect(0, 6, 6, 3, "#4A4E5C"); x.rect(4, 6, 24, 2, "#6E7385")
            x.rect(10, 12, 12, 6, "#3A3D49"); x.rect(6, 18, 20, 4, "#3A3D49")
            x.rect(12, 2, 8, 3, "#FF9A3D"); x.rect(14, 0, 4, 2, "#FFD36B")
            out = (x, 0, -6)
        case .cooler:
            let x = PixelCanvas(16, 30)
            x.rect(4, 0, 8, 10, "#7EC8F2"); x.rect(5, 1, 6, 8, "#A9DCF7"); x.rect(3, 10, 10, 19, "#E8ECF2"); x.rect(3, 10, 10, 2, "#FFFFFF"); x.rect(6, 16, 4, 2, "#3F8CFF")
            out = (x, 0, -14)
        case .printer:
            let x = PixelCanvas(16, 20)
            x.rect(1, 6, 14, 12, "#8C909B"); x.rect(2, 7, 12, 4, "#B7BAC2"); x.rect(4, 2, 8, 5, "#F6F4EF"); x.rect(3, 13, 10, 2, "#3A3448")
            out = (x, 0, -4)
        case .terminal:
            let x = PixelCanvas(16, 28)
            x.rect(3, 12, 10, 16, "#3A3448"); x.rect(1, 0, 14, 13, "#2A2838"); x.rect(2, 1, 12, 10, "#FFBD69"); x.rect(4, 3, 8, 1, "#3A2A20"); x.rect(4, 6, 5, 1, "#3A2A20")
            out = (x, 0, -12)
        case .clock:
            let x = PixelCanvas(16, 16)
            x.rect(3, 3, 10, 10, "#3A3448"); x.rect(4, 4, 8, 8, "#FBFCFE"); x.rect(8, 5, 1, 4, "#3A3448"); x.rect(8, 8, 3, 1, "#3A3448")
            out = (x, 0, 6)
        case .window:
            let x = PixelCanvas(w, 28)
            x.rect(0, 4, w, 22, "#5A4A6E"); x.rect(2, 6, w - 4, 18, "#8FD3F5")
            for i in 0..<5 { let bh = 5 + Int(tileHash(i, 9) * 10); x.rect(3 + i * 6, 24 - bh, 5, bh, "#5C7FD6"); x.rect(4 + i * 6, 25 - bh, 1, 1, "#FFE08A") }
            x.rect(w / 2 - 1, 6, 2, 18, "#5A4A6E")
            out = (x, 0, 0)
        default:
            let x = PixelCanvas(w, h)
            x.rect(0, 0, w, h, "#888888")
            out = (x, 0, 0)
        }
        propCache[key] = out
        return out
    }

    // MARK: building fronts

    // swiftlint:disable:next function_body_length
    static func building(_ b: BuildingDef) -> Sprite {
        let W = b.w * T, H = b.h * T
        let extra = b.style == .spire ? 26 : b.style == .tower ? 20 : b.style == .forge ? 14 : 8
        let x = PixelCanvas(W, H + extra)
        let top = extra
        let wallH = b.style == .spire ? 64 : b.style == .tower ? 80 : 50
        let wallY = top + H - wallH
        let wall = b.wall, wallD = shade(wall, -0.18), beam = "#6B4A33", roof = b.roof, roofD = shade(roof, -0.28), roofL = shade(roof, 0.2)
        let doorX = (b.door.x - b.x) * T

        x.rect(2, top + H - 3, W - 2, 3, shadow20)
        x.rect(0, wallY, W, wallH - 2, wall)
        x.rect(0, wallY + wallH - 8, W, 6, b.style == .vault || b.style == .citadel ? "#8C909B" : "#A99B8A")
        for i in stride(from: 0, to: W, by: 8) { x.rect(i, wallY + wallH - 8, 1, 6, "#7E7366") }
        x.rect(0, wallY + wallH - 2, W, 2, "#5E5448")
        if b.style != .vault && b.style != .citadel && b.style != .bank {
            x.rect(0, wallY, 3, wallH - 8, beam); x.rect(W - 3, wallY, 3, wallH - 8, beam); x.rect(0, wallY, W, 3, beam)
            for i in stride(from: 32, to: W - 8, by: 32) { x.rect(i, wallY, 2, wallH - 8, beam) }
        } else {
            for j in stride(from: wallY + 4, to: wallY + wallH - 8, by: 6) {
                let q = (Double(j) / 6).truncatingRemainder(dividingBy: 2)
                for i in stride(from: q != 0 ? 0 : 6, to: W, by: 12) { x.rect(i, j, 11, 1, wallD) }
            }
        }
        let winY = wallY + max(10, wallH - 40)
        for wx in [10, W - 26] {
            if abs(wx + 8 - (doorX + 8)) < 14 { continue }
            x.rect(wx - 1, winY - 1, 18, 14, beam); x.rect(wx, winY, 16, 12, C.glass); x.rect(wx, winY + 7, 16, 5, C.glassDark)
            x.rect(wx + 7, winY, 2, 12, beam); x.rect(wx, winY + 5, 16, 2, beam); x.rect(wx + 2, winY + 1, 3, 2, "#D5F0FF")
            x.rect(wx - 2, winY + 12, 20, 3, shade(wall, -0.3))
            if b.style == .studio || b.style == .dome { x.rect(wx, winY + 13, 16, 3, C.leaf); x.rect(wx + 3, winY + 13, 2, 2, "#FF8FB8"); x.rect(wx + 10, winY + 13, 2, 2, "#FFD36B") }
        }
        if b.style == .spire || b.style == .tower {
            for wx in [10, W - 26] {
                let y2 = winY - 22
                x.rect(wx - 1, y2 - 1, 18, 14, beam); x.rect(wx, y2, 16, 12, C.glass); x.rect(wx + 7, y2, 2, 12, beam); x.rect(wx + 2, y2 + 1, 3, 2, "#D5F0FF")
            }
        }
        let dY = wallY + wallH - 26
        x.rect(doorX - 1, dY - 3, 18, 27, beam)
        x.rect(doorX + 1, dY, 14, 24, b.style == .vault ? "#5A5F73" : "#8B5A33")
        x.rect(doorX + 1, dY, 14, 2, shade("#8B5A33", 0.2))
        if b.style == .vault { x.rect(doorX + 4, dY + 6, 8, 8, "#3A3D49"); x.rect(doorX + 7, dY + 9, 2, 2, "#C9A23A") }
        else { x.rect(doorX + 7, dY + 2, 2, 22, shade("#8B5A33", -0.3)); x.rect(doorX + 11, dY + 12, 2, 2, "#F4D58D"); x.rect(doorX + 3, dY + 4, 3, 5, C.glass); x.rect(doorX + 10, dY + 4, 3, 5, C.glass) }
        x.rect(doorX - 2, dY + 24, 20, 2, "#8C909B")
        x.rect(doorX - 4, dY - 12, 24, 8, beam); x.rect(doorX - 3, dY - 11, 22, 6, "#F1E2C0")
        emblem(x, b.style, doorX + 8, dY - 8)

        let roofTop = top, roofBottom = wallY + 2
        switch b.style {
        case .dome:
            let cx = W / 2, rad = min(W / 2 - 2, roofBottom - roofTop)
            for j in 0..<rad {
                let half = Int((Double(rad * rad - (rad - j) * (rad - j))).squareRoot().rounded())
                x.rect(cx - half, roofBottom - rad + j, half * 2, 1, j % 6 == 5 ? roofD : roof)
                if j > 3 { x.rect(cx - half + 2, roofBottom - rad + j, 3, 1, roofL) }
            }
            x.rect(cx - 3, roofBottom - rad + 2, 6, Int((Double(rad) * 0.5).rounded()), "#1E2A4A"); x.rect(cx - 1, roofBottom - rad + 4, 2, 4, "#FFE08A")
            x.rect(0, roofBottom - 4, W, 4, roofD)
        case .citadel, .vault, .bank:
            x.rect(0, roofBottom - 14, W, 14, roofD)
            x.rect(0, roofBottom - 16, W, 4, roof)
            if b.style == .citadel { for i in stride(from: 0, to: W, by: 10) { x.rect(i, roofBottom - 22, 6, 7, roof) } }
            if b.style == .bank {
                x.rect(6, roofBottom - 28, W - 12, 13, roof)
                for j in 0..<12 { x.rect(W / 2 - j * 3, roofBottom - 28 - (12 - j), j * 6, 1, roof) }
                x.rect(W / 2 - 5, roofBottom - 30, 10, 8, "#FFE08A"); x.rect(W / 2 - 1, roofBottom - 29, 2, 6, "#C9A23A")
                for cx in [8, 22, W - 30, W - 16] { x.rect(cx, wallY + 4, 6, wallH - 12, "#F7F3E8") }
            }
            if b.style == .vault { x.rect(W / 2 - 8, roofBottom - 30, 16, 16, roof); x.rect(W / 2 - 4, roofBottom - 26, 8, 8, "#5BF2A5") }
        default:
            let rows = roofBottom - roofTop
            for j in 0..<rows {
                let inset = max(0, Int(((1 - Double(j) / max(1, Double(rows) * 0.55)) * Double(W / 2 - 6)).rounded()))
                let col = (j / 4) % 2 == 1 ? roof : shade(roof, -0.08)
                x.rect(inset - 3, roofTop + j, W - inset * 2 + 6, 1, col)
                if j % 4 == 3 { for i in stride(from: inset, to: W - inset, by: 6) { x.rect(i + ((j / 4) % 2) * 3, roofTop + j, 1, 1, roofD) } }
            }
            x.rect(0, roofBottom - 3, W, 3, roofD)
            x.rect(W / 2 - 1, roofTop, 2, rows - 3, roofL)
            if b.style == .forge {
                x.rect(W - 24, roofTop - 12, 10, 26, "#7E6B5A"); x.rect(W - 25, roofTop - 14, 12, 3, "#5E5448")
                x.rect(W - 22, roofTop - 22, 6, 6, RGBA.alpha(220, 220, 230, 0.7)); x.rect(W - 18, roofTop - 30, 8, 7, RGBA.alpha(220, 220, 230, 0.5))
                x.rect(10, winY, 16, 12, "#FF9A3D"); x.rect(12, winY + 6, 12, 6, "#FFD36B")
            }
            if b.style == .spire {
                x.rect(W / 2 - 8, roofTop - 6, 16, 20, shade(roof, 0.1))
                x.rect(W / 2 - 4, roofTop - 22, 8, 18, "#C9A7FF"); x.rect(W / 2 - 2, roofTop - 26, 4, 6, "#E9DBFF"); x.rect(W / 2 - 1, roofTop - 20, 2, 10, "#FFFFFF")
            }
            if b.style == .tower {
                x.rect(W / 2 - 1, roofTop - 20, 2, 22, "#3A3448"); x.rect(W / 2 + 1, roofTop - 20, 12, 8, "#F4D58D"); x.rect(W / 2 + 3, roofTop - 18, 5, 4, "#C9A23A")
            }
            if b.style == .studio {
                for i in stride(from: 0, to: W - 8, by: 8) { x.rect(4 + i, wallY - 2, 8, 7, (i / 8) % 2 == 1 ? "#FFFFFF" : "#FF6FAE") }
            }
        }
        return Sprite(canvas: x, ox: b.x * T, oy: b.y * T - extra, baseY: (b.y + b.h) * T)
    }

    private static func emblem(_ x: PixelCanvas, _ style: BuildingDef.Style, _ cx: Int, _ cy: Int) {
        let ink = "#3A2A40"
        switch style {
        case .dome: x.rect(cx - 3, cy - 2, 5, 4, ink); x.rect(cx - 2, cy - 1, 3, 2, "#7EC8F2"); x.rect(cx + 2, cy + 1, 2, 2, ink)
        case .spire: x.rect(cx - 1, cy - 3, 2, 6, "#7A5CD6"); x.rect(cx - 3, cy - 1, 6, 2, "#7A5CD6")
        case .forge: x.rect(cx - 4, cy - 1, 8, 2, ink); x.rect(cx - 2, cy + 1, 4, 2, ink); x.rect(cx - 1, cy - 3, 2, 2, "#FF9A3D")
        case .tower: x.rect(cx - 3, cy - 2, 6, 4, "#C9A23A"); x.rect(cx - 1, cy - 1, 2, 2, "#FFE08A")
        case .bank: x.rect(cx - 2, cy - 2, 4, 4, "#C9A23A"); x.rect(cx - 1, cy - 1, 2, 2, "#FFE08A")
        case .studio: x.rect(cx - 3, cy - 2, 2, 2, "#FF6FAE"); x.rect(cx, cy - 2, 2, 2, "#FFD36B"); x.rect(cx - 2, cy + 1, 2, 2, "#7FD3FF")
        case .citadel: x.rect(cx - 2, cy - 3, 4, 5, "#4F8A62"); x.rect(cx - 1, cy + 2, 2, 1, "#4F8A62")
        case .vault: x.rect(cx - 2, cy - 2, 4, 4, ink)
        }
    }

    // MARK: small icons for status bubbles (9×8 inside an 11×10 bubble)

    static func bubble(_ icon: String) -> PixelCanvas {
        let c = PixelCanvas(13, 13)
        c.rect(0, 0, 13, 12, "#1D1626")
        c.rect(1, 1, 11, 10, icon == "fail" ? "#FFD6DC" : icon == "alert" ? "#FFE9C2" : "#FFFFFF")
        c.rect(3, 12, 2, 1, "#1D1626")
        func P(_ px: Int, _ py: Int, _ pw: Int = 1, _ ph: Int = 1, _ col: String = "#1D1626") { c.rect(2 + px, 2 + py, pw, ph, col) }
        switch icon {
        case "gear": P(3, 1, 3, 1, "#5A5F73"); P(2, 2, 5, 4, "#5A5F73"); P(3, 6, 3, 1, "#5A5F73"); P(1, 3, 1, 2, "#5A5F73"); P(7, 3, 1, 2, "#5A5F73"); P(4, 3, 1, 2, "#FFFFFF")
        case "code": P(1, 3, 1, 2, "#3F8CFF"); P(2, 2); P(2, 5); P(7, 3, 1, 2, "#3F8CFF"); P(6, 2); P(6, 5); P(4, 1, 1, 6, "#C2553A")
        case "lens": P(2, 1, 3, 1); P(1, 2, 1, 3); P(5, 2, 1, 3); P(2, 5, 3, 1); P(2, 2, 3, 3, "#BFE3FF"); P(6, 6, 2, 2, "#8B5A33")
        case "flask": P(3, 0, 3, 1); P(3, 1, 3, 2, "#DDE7F0"); P(2, 3, 5, 4, "#5BF2A5"); P(3, 4, 1, 1, "#FFFFFF")
        case "wait": P(2, 0, 5, 1); P(2, 7, 5, 1); P(3, 1, 3, 2, "#FFD36B"); P(4, 3, 1, 2, "#FFD36B"); P(3, 5, 3, 2, "#FFD36B")
        case "box": P(1, 2, 7, 5, "#C98B4A"); P(1, 2, 7, 1, "#E2A866"); P(4, 2, 1, 5, "#8E5A2C")
        case "star": P(4, 0, 1, 2, "#F4C430"); P(1, 2, 7, 2, "#F4C430"); P(2, 4, 5, 1, "#F4C430"); P(2, 5, 2, 2, "#F4C430"); P(5, 5, 2, 2, "#F4C430")
        case "alert": P(4, 0, 1, 5, "#E07A00"); P(4, 6, 1, 1, "#E07A00")
        case "fail": for (a, b) in [(2, 1), (3, 2), (4, 3), (5, 4), (6, 5), (6, 1), (5, 2), (3, 4), (2, 5)] { P(a, b, 1, 1, "#E2465E") }
        default: break
        }
        return c
    }

    static let packageColor: [String: String] = [
        "research_brief": "#5C7FD6", "product_proposal": "#7A5CD6", "code_artifact": "#C2553A", "test_report": "#4F8A62", "release_package": "#C9A23A",
        "revision_request": "#E2465E", "bill_reminder": "#F28C38", "payment_proposal": "#F28C38", "purchase_request": "#F28C38", "tax_review_package": "#C9A23A",
    ]

    static func crate(_ type: String, flag: String? = nil) -> PixelCanvas {
        let c = PixelCanvas(14, 16)
        c.rect(1, 5, 12, 11, "#1D1626")
        c.rect(2, 6, 10, 9, packageColor[type] ?? "#C98B4A")
        c.rect(2, 6, 10, 2, RGBA.alpha(255, 255, 255, 0.35))
        c.rect(6, 6, 2, 9, "#F4D58D")
        if let flag { c.rect(9, 1, 4, 4, flag) }
        return c
    }
}
