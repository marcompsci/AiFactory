import CoreGraphics
import Foundation

/// Pixel-art characters drawn from code: 16×24 px, a big head on a small body, four directions, walk cycles and poses.
/// Agents use their seeded look; the owner's avatar uses the look picked in the editor. Same art as the web version.
enum Pose: String, CaseIterable { case stand, walk, work, talk, celebrate, carry, read }

struct Outfit: Hashable {
    enum HairStyle: String, CaseIterable { case spiky, short, buzz, curly, long, bun, afro, bald, ponytail }
    struct Hat: Hashable { let kind: String; let color: String }   // cap | beanie | beret | visor
    var skin: String
    var hairStyle: HairStyle
    var hair: String
    var shirt: String
    var accent: String
    var pants: String
    var bottom: String         // pants | shorts | skirt
    var shoes: String
    var glasses: Bool
    var hat: Hat? = nil
    var headphones = false
    var coat = false
    var blush = false
}

/// The owner's character, as saved by PUT /api/play/state.
struct PlayerLook: Codable, Hashable {
    var skin = "#E8B48A"
    var hairStyle = "spiky"
    var hair = "#1E1B22"
    var shirt = "#B8BCC6"
    var pants = "#25252E"
    var shoes = "#F2F2F2"
    var glasses = true

    enum CodingKeys: String, CodingKey { case skin, hairStyle = "hair_style", hair, shirt, pants, shoes, glasses }
}

enum PixelSprites {
    static let w = 16
    static let h = 24
    static let ink = "#1D1626"

    private static let hairMap: [String: Outfit.HairStyle] = [
        "spiky": .spiky, "swoop": .short, "buzz": .buzz, "curly": .curly, "long": .long, "bob": .short, "buns": .bun,
        "afro": .afro, "bald": .bald, "ponytail": .ponytail, "short": .short, "bun": .bun,
    ]

    static func outfit(_ l: Agent.Look) -> Outfit {
        let hatKinds: Set<String> = ["cap", "beanie", "beret", "visor"]
        return Outfit(skin: l.skin, hairStyle: hairMap[l.hair.style] ?? .short, hair: l.hair.color, shirt: l.top.color, accent: l.top.accent,
                      pants: l.bottom.color, bottom: l.bottom.style, shoes: l.shoes.hasPrefix("#") ? l.shoes : "#2A2230",
                      glasses: l.accessory == "glasses",
                      hat: hatKinds.contains(l.accessory) ? Outfit.Hat(kind: l.accessory, color: l.hatColor ?? l.top.accent) : nil,
                      headphones: l.accessory == "headphones" || l.accessory == "headset",
                      coat: ["labcoat", "blazer", "jacket", "cardigan", "cape"].contains(l.top.style), blush: l.blush ?? false)
    }

    static func outfit(_ l: PlayerLook) -> Outfit {
        Outfit(skin: l.skin, hairStyle: hairMap[l.hairStyle] ?? .spiky, hair: l.hair, shirt: l.shirt, accent: shade(l.shirt, -0.2),
               pants: l.pants, bottom: "pants", shoes: l.shoes, glasses: l.glasses)
    }

    // MARK: pixel buffer (hex strings, nil = transparent)

    final class Px {
        var c = [String?](repeating: nil, count: PixelSprites.w * PixelSprites.h)
        func set(_ x: Int, _ y: Int, _ col: String) { if x >= 0 && y >= 0 && x < PixelSprites.w && y < PixelSprites.h { c[y * PixelSprites.w + x] = col } }
        func rect(_ x: Int, _ y: Int, _ w: Int, _ h: Int, _ col: String) {
            guard w > 0, h > 0 else { return }
            for j in y..<(y + h) { for i in x..<(x + w) { set(i, j, col) } }
        }
        func get(_ x: Int, _ y: Int) -> String? { x >= 0 && y >= 0 && x < PixelSprites.w && y < PixelSprites.h ? c[y * PixelSprites.w + x] : nil }
        func outline() {
            var o = c
            for y in 0..<PixelSprites.h { for x in 0..<PixelSprites.w where get(x, y) == nil {
                if get(x - 1, y) != nil || get(x + 1, y) != nil || get(x, y - 1) != nil || get(x, y + 1) != nil { o[y * PixelSprites.w + x] = PixelSprites.ink }
            } }
            c = o
        }
        func mirror() {
            var o = c
            for y in 0..<PixelSprites.h { for x in 0..<PixelSprites.w { o[y * PixelSprites.w + x] = c[y * PixelSprites.w + (PixelSprites.w - 1 - x)] } }
            c = o
        }
    }

    // MARK: body parts

    private static func hairDown(_ p: Px, _ o: Outfit, back: Bool) {
        let h = o.hair, hi = shade(h, 0.25), dk = shade(h, -0.3)
        let s = o.hairStyle
        if s == .bald {
            if back { p.rect(3, 4, 10, 8, o.skin) }
            p.set(5, 5, shade(o.skin, 0.35))
            return
        }
        if s == .afro {
            p.rect(2, 1, 12, 8, h); p.rect(1, 3, 14, 5, h); p.rect(3, 0, 10, 1, h)
            if back { p.rect(2, 8, 12, 4, h) }
            p.rect(4, 1, 4, 1, hi)
            return
        }
        p.rect(3, 3, 10, 4, h); p.rect(2, 4, 12, 3, h); p.rect(4, 2, 8, 1, h); p.rect(5, 3, 4, 1, hi)
        if back {
            p.rect(2, 4, 12, 8, h); p.rect(4, 5, 6, 1, hi)
            if s == .long { p.rect(2, 12, 12, 5, h) }
            if s == .ponytail { p.rect(7, 12, 2, 4, dk) }
            return
        }
        switch s {
        case .spiky:
            for x in [3, 5, 7, 9, 11] { p.set(x, 1, h); p.set(x + 1, 0, h); p.set(x, 2, h); p.set(x + 1, 1, h); p.set(x + 1, 2, h) }
            p.rect(2, 3, 12, 4, h)
            p.set(1, 4, h); p.set(14, 4, h); p.set(1, 5, h); p.set(14, 5, h)
            for x in [3, 4, 6, 9, 11, 12] { p.set(x, 7, h) }
            p.rect(2, 7, 1, 3, h); p.rect(13, 7, 1, 3, h)
            p.set(4, 2, hi); p.set(8, 1, hi); p.set(10, 2, hi)
        case .buzz:
            p.rect(3, 6, 10, 1, h)
        case .curly:
            for x in [2, 4, 6, 8, 10, 12] { p.set(x, 2, h); p.set(x + 1, 2, h) }
            p.rect(2, 6, 12, 1, h)
            for x in [3, 6, 9, 12] { p.set(x, 7, h) }
            p.set(5, 2, hi); p.set(9, 2, hi)
        default:
            p.rect(3, 6, 10, 1, h); p.rect(3, 7, 3, 1, h); p.rect(10, 7, 3, 1, h)
            p.rect(2, 7, 1, 3, h); p.rect(13, 7, 1, 3, h)
            if s == .long { p.rect(1, 7, 2, 10, h); p.rect(13, 7, 2, 10, h); p.rect(1, 15, 2, 2, dk); p.rect(13, 15, 2, 2, dk) }
            if s == .ponytail { p.rect(13, 8, 2, 5, dk) }
            if s == .bun { p.rect(6, 0, 4, 2, h); p.set(7, 0, hi) }
        }
    }

    private static func hat(_ p: Px, _ o: Outfit, _ dir: Dir) {
        guard let hat = o.hat else { return }
        let c = hat.color, dk = shade(c, -0.3)
        switch hat.kind {
        case "cap":
            p.rect(3, 2, 10, 4, c); p.rect(4, 1, 8, 1, c); p.set(7, 1, shade(c, 0.3))
            if dir == .down { p.rect(2, 6, 12, 1, dk) } else if dir == .left { p.rect(0, 6, 7, 1, dk) } else if dir == .right { p.rect(9, 6, 7, 1, dk) }
        case "beanie":
            p.rect(3, 1, 10, 5, c); p.rect(5, 0, 6, 1, c); p.rect(2, 5, 12, 2, dk); p.set(8, 0, shade(c, 0.4))
        case "beret":
            p.rect(2, 2, 11, 3, c); p.rect(4, 1, 7, 1, c); p.set(9, 0, dk)
        default:
            p.rect(3, 5, 10, 1, c)
            if dir == .down { p.rect(4, 6, 8, 1, dk) }
        }
    }

    private static func face(_ p: Px, _ o: Outfit, _ pose: Pose, _ frame: Int, side: Bool) {
        let eye = ink
        if side {
            p.rect(5, 9, 1, 2, eye)
            if o.glasses {
                let F = "#2B2433"
                p.rect(3, 8, 4, 1, F); p.rect(3, 11, 4, 1, F); p.rect(3, 9, 1, 2, F); p.rect(4, 9, 2, 2, "#CFE8FF"); p.rect(5, 9, 1, 2, eye); p.rect(7, 9, 3, 1, F)
            }
            if o.blush { p.set(6, 11, "#FF8FA3") }
            let open = pose == .talk && frame % 2 == 1
            p.rect(4, 12, 2, open ? 2 : 1, open ? "#7A1F35" : shade(o.skin, -0.45))
            p.set(3, 10, o.skin)
            return
        }
        p.rect(5, 9, 1, 2, eye)
        p.rect(10, 9, 1, 2, eye)
        if o.glasses {
            let F = "#2B2433", L = "#CFE8FF"
            for lx in [3, 8] {
                p.rect(lx, 8, 5, 1, F); p.rect(lx, 11, 5, 1, F); p.rect(lx, 9, 1, 2, F); p.rect(lx + 4, 9, 1, 2, F)
                p.rect(lx + 1, 9, 3, 2, L)
            }
            p.rect(5, 9, 1, 2, eye); p.rect(10, 9, 1, 2, eye)
        }
        if o.blush { p.set(3, 11, "#FF8FA3"); p.set(12, 11, "#FF8FA3") }
        let open = (pose == .talk && frame % 2 == 1) || pose == .celebrate
        if open { p.rect(7, 12, 2, 1, "#7A1F35"); p.set(7, 13, "#7A1F35"); p.set(8, 13, "#7A1F35") }
        else { p.rect(7, 12, 2, 1, shade(o.skin, -0.45)) }
    }

    private static func headphones(_ p: Px, _ o: Outfit, _ dir: Dir) {
        guard o.headphones else { return }
        p.rect(3, 2, 10, 1, "#2A2A36")
        if dir == .down || dir == .up { p.rect(1, 8, 2, 4, o.accent); p.rect(13, 8, 2, 4, o.accent) }
        else { p.rect(dir == .left ? 9 : 6, 8, 2, 4, o.accent) }
    }

    private static func body(_ p: Px, _ o: Outfit, _ dir: Dir, _ pose: Pose, _ frame: Int) {
        let shirt = o.shirt, sDark = shade(shirt, -0.22), skin = o.skin
        let step = pose == .walk || pose == .carry ? frame % 4 : 0
        let side = dir == .left || dir == .right
        p.rect(5, 14, 6, 5, shirt)
        p.rect(5, 18, 6, 1, sDark)
        p.rect(6, 14, 4, 1, shade(shirt, 0.15))
        if o.coat && !side { p.rect(7, 14, 2, 4, o.accent) }
        if o.coat && side { p.rect(5, 14, 1, 5, o.accent) }
        let swing = step == 1 ? 1 : step == 3 ? -1 : 0
        if pose == .celebrate {
            let up = frame % 2 == 1 ? 1 : 0
            p.rect(3, 9 + up, 2, 5, shirt); p.rect(11, 9 + up, 2, 5, shirt)
            p.rect(3, 8 + up, 2, 1, skin); p.rect(11, 8 + up, 2, 1, skin)
        } else if pose == .carry {
            p.rect(4, 14, 1, 3, shirt); p.rect(11, 14, 1, 3, shirt)
            if !side { p.rect(4, 15, 8, 4, "#C98B4A"); p.rect(4, 15, 8, 1, "#E2A866"); p.rect(7, 15, 2, 4, "#8E5A2C") }
            else { p.rect(dir == .left ? 2 : 10, 15, 4, 4, "#C98B4A"); p.rect(dir == .left ? 2 : 10, 15, 4, 1, "#E2A866") }
        } else if side {
            let ax = 7 + swing
            p.rect(ax, 14, 2, 4, sDark)
            p.rect(ax, 18, 2, 1, skin)
            if pose == .read { p.rect(dir == .left ? 3 : 10, 15, 3, 3, o.accent) }
        } else {
            let typing = pose == .work ? (frame % 2 == 1 ? -1 : 0) : 0
            p.rect(4, 14, 1, 4, shirt)
            p.rect(11, 14, 1, 4, shirt)
            p.set(4, 18 + typing + (swing < 0 ? -1 : 0), skin)
            p.set(11, 18 - typing + (swing > 0 ? -1 : 0), skin)
            p.set(3, 15, shirt); p.set(12, 15, shirt)
            if pose == .read { p.rect(5, 16, 6, 3, o.accent); p.rect(7, 16, 2, 3, shade(o.accent, 0.4)) }
        }
        let pc = o.pants, pDark = shade(pc, -0.25)
        let legTop = 19
        if o.bottom == "skirt" { p.rect(4, 18, 8, 3, pc); p.rect(4, 20, 8, 1, pDark) }
        let legColor = o.bottom == "pants" ? pc : skin
        if side {
            let f = step == 1 ? 1 : step == 3 ? -1 : 0
            p.rect(6 - f, legTop, 2, 3, o.bottom == "shorts" ? pc : legColor)
            p.rect(8 + f, legTop, 2, 3, o.bottom == "pants" ? pDark : legColor)
            if o.bottom == "shorts" { p.rect(5, legTop, 6, 1, pc) }
            p.rect(5 - f, legTop + 3, 3, 1, o.shoes); p.rect(8 + f, legTop + 3, 3, 1, shade(o.shoes, -0.2))
        } else {
            let lUp = step == 3 ? 1 : 0, rUp = step == 1 ? 1 : 0
            p.rect(5, legTop, 3, 3 - lUp, legColor)
            p.rect(8, legTop, 3, 3 - rUp, legColor)
            if o.bottom != "skirt" { p.rect(5, legTop, 6, 1, pc) }
            if o.bottom == "pants" { p.rect(7, legTop + 1, 2, 2, pDark) }
            p.rect(4, legTop + 3 - lUp, 4, 1, o.shoes)
            p.rect(8, legTop + 3 - rUp, 4, 1, o.shoes)
            p.set(4, legTop + 3 - lUp, shade(o.shoes, -0.25))
            p.set(11, legTop + 3 - rUp, shade(o.shoes, -0.25))
        }
    }

    private static func head(_ p: Px, _ o: Outfit, _ dir: Dir, _ pose: Pose, _ frame: Int) {
        let skin = o.skin, sd = shade(skin, -0.18)
        p.rect(3, 4, 10, 10, skin)
        p.rect(2, 6, 1, 6, skin); p.rect(13, 6, 1, 6, skin)
        p.rect(3, 13, 10, 1, sd)
        if dir == .up {
            hairDown(p, o, back: true)
        } else if dir == .down {
            face(p, o, pose, frame, side: false)
            hairDown(p, o, back: false)
        } else {
            face(p, o, pose, frame, side: true)
            let h = o.hair
            if o.hairStyle != .bald {
                let hi = shade(h, 0.25)
                if o.hairStyle == .afro { p.rect(2, 1, 13, 7, h); p.rect(3, 0, 10, 1, h) }
                else {
                    p.rect(3, 3, 11, 4, h); p.rect(4, 2, 9, 1, h); p.rect(2, 5, 2, 2, h); p.rect(5, 3, 4, 1, hi)
                    if o.hairStyle == .spiky { for x in [4, 7, 10, 13] { p.set(x, 1, h); p.set(x + 1, 0, h); p.set(x + 1, 1, h) }; p.set(14, 3, h); p.set(15, 4, h) }
                    if o.hairStyle == .curly { for x in [3, 6, 9, 12] { p.rect(x, 1, 2, 2, h) } }
                    if o.hairStyle == .bun { p.rect(9, 0, 4, 3, h) }
                    if o.hairStyle != .buzz { p.rect(3, 7, 2, 1, h) }
                }
                p.rect(8, 4, 6, 8, h)
                p.rect(9, 12, 4, 1, h)
                if o.hairStyle == .long { p.rect(9, 12, 5, 5, h) }
                if o.hairStyle == .ponytail { p.rect(13, 7, 2, 6, shade(h, -0.3)) }
                if o.hairStyle == .afro { p.rect(7, 2, 8, 10, h) }
            }
        }
        headphones(p, o, dir)
        hat(p, o, dir)
    }

    /// One frame as hex colors (nil = transparent), row by row.
    static func paint(_ o: Outfit, _ dir: Dir, _ pose: Pose, _ frame: Int) -> [String?] {
        let p = Px()
        let d: Dir = dir == .right ? .left : dir
        let bob = (pose == .walk || pose == .carry) && frame % 2 == 1 ? -1 : pose == .celebrate && frame % 2 == 1 ? -2 : 0
        body(p, o, d, pose, frame)
        head(p, o, d, pose, frame)
        if bob != 0 {
            let c = p.c
            p.c = [String?](repeating: nil, count: w * h)
            for y in 0..<h { for x in 0..<w { if let v = c[y * w + x] { p.set(x, y + bob, v) } } }
        }
        p.outline()
        if dir == .right { p.mirror() }
        return p.c
    }

    private static var cache: [String: CGImage] = [:]

    static func image(_ o: Outfit, _ dir: Dir, _ pose: Pose, _ frame: Int) -> CGImage? {
        let k = "\(o.hashValue)#\(dir.rawValue)#\(pose.rawValue)#\(frame)"
        if let hit = cache[k] { return hit }
        let canvas = PixelCanvas(w, h)
        for (i, v) in paint(o, dir, pose, frame).enumerated() { if let v { canvas.rect(i % w, i / w, 1, 1, v) } }
        let img = canvas.image()
        if let img { cache[k] = img }
        return img
    }
}
