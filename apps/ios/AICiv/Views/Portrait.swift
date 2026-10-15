import SwiftUI

/// A flat chibi portrait (head and shoulders) drawn from the agent's look, matching the 3D city and the web roster.
struct AgentPortrait: View {
    let agent: Agent
    var size: CGFloat = 36

    var body: some View {
        Group {
            if let look = agent.avatar.look {
                Canvas { ctx, sz in
                    ctx.scaleBy(x: sz.width / 100, y: sz.height / 100)
                    PortraitPainter(look: look).draw(&ctx)
                }
                .background(Color(hex: 0x141B33), in: RoundedRectangle(cornerRadius: size * 0.22))
                .clipShape(RoundedRectangle(cornerRadius: size * 0.22))
            } else {
                Text(String(agent.name.prefix(1))).font(.system(size: size * 0.45, weight: .bold)).foregroundStyle(Theme.ground)
                    .frame(width: size, height: size)
                    .background(Color(hexString: agent.avatar.color), in: RoundedRectangle(cornerRadius: size * 0.22))
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel("\(agent.name)'s portrait")
    }
}

struct PortraitPainter {
    let look: Agent.Look
    private let ink = Color(hex: 0x1A1424)

    func c(_ hex: String) -> Color { Color(hexString: hex) }

    func draw(_ ctx: inout GraphicsContext) {
        let hair = c(look.hair.color)
        let hat = c(look.hatColor ?? "#32D8FF")
        // back hair
        switch look.hair.style {
        case "long": ctx.fill(Path(roundedRect: CGRect(x: 16, y: 22, width: 68, height: 66), cornerRadius: 14), with: .color(hair))
        case "bob": ctx.fill(Path(roundedRect: CGRect(x: 17, y: 20, width: 66, height: 50), cornerRadius: 16), with: .color(hair))
        case "afro": ctx.fill(Path(ellipseIn: CGRect(x: 10, y: 2, width: 80, height: 60)), with: .color(hair))
        case "ponytail": ctx.fill(Path(ellipseIn: CGRect(x: 69, y: 16, width: 18, height: 28)), with: .color(hair))
        case "buns":
            ctx.fill(Path(ellipseIn: CGRect(x: 14, y: 8, width: 20, height: 20)), with: .color(hair))
            ctx.fill(Path(ellipseIn: CGRect(x: 66, y: 8, width: 20, height: 20)), with: .color(hair))
        default: break
        }
        // shoulders and collar
        ctx.fill(Path(roundedRect: CGRect(x: 24, y: 80, width: 52, height: 24), cornerRadius: 10), with: .color(c(look.top.color)))
        if ["vest", "sweatervest", "blazer", "cardigan"].contains(look.top.style) {
            var v = Path(); v.move(to: CGPoint(x: 43, y: 80)); v.addLine(to: CGPoint(x: 50, y: 94)); v.addLine(to: CGPoint(x: 57, y: 80)); v.closeSubpath()
            ctx.fill(v, with: .color(look.top.style.contains("vest") ? c(look.top.accent) : Color(hex: 0xF4F6FA)))
        }
        // head
        ctx.fill(Path(roundedRect: CGRect(x: 20, y: 22, width: 60, height: 58), cornerRadius: 18), with: .color(c(look.skin)))
        // front hair
        if let front = hairFront(look.hair.style) { ctx.fill(front, with: .color(hair)) }
        if look.hair.style == "curly" {
            for (i, x) in [22.0, 32, 42, 52, 62, 72, 80].enumerated() {
                ctx.fill(Path(ellipseIn: CGRect(x: x - 9, y: (i % 2 == 0 ? 26 : 22) - 9, width: 18, height: 18)), with: .color(hair))
            }
        }
        // eyes and brows
        for s in [-1.0, 1.0] {
            eye(&ctx, cx: 50 + s * 13, cy: 52, side: s)
            let browY: Double = look.eyes == "anime" ? 39 : 42
            ctx.fill(Path(roundedRect: CGRect(x: 50 + s * 13 - 5, y: browY, width: 10, height: 2.4), cornerRadius: 1),
                     with: .color(look.hair.style == "bald" ? ink : hair.opacity(0.9)))
            if look.blush == true {
                ctx.fill(Path(ellipseIn: CGRect(x: 50 + s * 21 - 5, y: 58.4, width: 10, height: 5.2)), with: .color(Color(hex: 0xFF8FA3).opacity(0.75)))
            }
        }
        mouth(&ctx)
        if look.mustache == true {
            ctx.fill(Path(ellipseIn: CGRect(x: 40, y: 60, width: 10, height: 5)), with: .color(Color(hex: 0x2A1A12)))
            ctx.fill(Path(ellipseIn: CGRect(x: 50, y: 60, width: 10, height: 5)), with: .color(Color(hex: 0x2A1A12)))
        }
        accessory(&ctx, hat: hat)
    }

    private func hairFront(_ style: String) -> Path? {
        var p = Path()
        switch style {
        case "bald", "curly": return nil
        case "buzz":
            p.move(to: CGPoint(x: 20, y: 40)); p.addQuadCurve(to: CGPoint(x: 80, y: 40), control: CGPoint(x: 50, y: 6))
            p.addLine(to: CGPoint(x: 80, y: 34)); p.addQuadCurve(to: CGPoint(x: 20, y: 34), control: CGPoint(x: 50, y: 20)); p.closeSubpath()
        case "spiky":
            let pts: [(Double, Double)] = [(18, 42), (22, 18), (30, 26), (36, 8), (44, 22), (52, 4), (58, 20), (68, 8), (70, 24), (80, 16), (82, 42)]
            p.move(to: CGPoint(x: pts[0].0, y: pts[0].1))
            for q in pts.dropFirst() { p.addLine(to: CGPoint(x: q.0, y: q.1)) }
            p.addQuadCurve(to: CGPoint(x: 18, y: 42), control: CGPoint(x: 50, y: 26)); p.closeSubpath()
        case "afro":
            p.move(to: CGPoint(x: 20, y: 40)); p.addQuadCurve(to: CGPoint(x: 80, y: 40), control: CGPoint(x: 50, y: 4))
            p.addLine(to: CGPoint(x: 80, y: 30)); p.addQuadCurve(to: CGPoint(x: 20, y: 30), control: CGPoint(x: 50, y: 8)); p.closeSubpath()
        case "swoop":
            p.move(to: CGPoint(x: 18, y: 44)); p.addQuadCurve(to: CGPoint(x: 82, y: 40), control: CGPoint(x: 50, y: -10))
            p.addQuadCurve(to: CGPoint(x: 44, y: 36), control: CGPoint(x: 66, y: 24)); p.addQuadCurve(to: CGPoint(x: 18, y: 44), control: CGPoint(x: 30, y: 30))
        default:
            p.move(to: CGPoint(x: 17, y: 46)); p.addQuadCurve(to: CGPoint(x: 83, y: 46), control: CGPoint(x: 50, y: -12))
            p.addLine(to: CGPoint(x: 80, y: 46)); p.addQuadCurve(to: CGPoint(x: 50, y: 31), control: CGPoint(x: 76, y: 28))
            p.addQuadCurve(to: CGPoint(x: 20, y: 46), control: CGPoint(x: 24, y: 30)); p.closeSubpath()
        }
        return p
    }

    private func eye(_ ctx: inout GraphicsContext, cx: Double, cy: Double, side: Double) {
        switch look.eyes {
        case "happy", "sleepy":
            var p = Path()
            let up = look.eyes == "happy"
            p.move(to: CGPoint(x: cx - 6, y: cy + (up ? 2 : -1)))
            p.addQuadCurve(to: CGPoint(x: cx + 6, y: cy + (up ? 2 : -1)), control: CGPoint(x: cx, y: cy + (up ? -6 : 5)))
            ctx.stroke(p, with: .color(ink), style: StrokeStyle(lineWidth: 2.6, lineCap: .round))
        case "anime":
            ctx.fill(Path(ellipseIn: CGRect(x: cx - 7, y: cy - 8.5, width: 14, height: 17)), with: .color(.white))
            ctx.fill(Path(ellipseIn: CGRect(x: cx - 5.4, y: cy - 6, width: 10.8, height: 14)), with: .color(c(look.eyeColor)))
            ctx.fill(Path(ellipseIn: CGRect(x: cx - 2.8, y: cy - 2.6, width: 5.6, height: 7.2)), with: .color(ink))
            ctx.fill(Path(ellipseIn: CGRect(x: cx + 0.2, y: cy - 4.3, width: 3.6, height: 3.6)), with: .color(.white))
            ctx.fill(Path(roundedRect: CGRect(x: cx - 8, y: cy - 9.5, width: 16, height: 2.4), cornerRadius: 1), with: .color(ink))
        default:
            ctx.fill(Path(ellipseIn: CGRect(x: cx - 3.6, y: cy - 5.5, width: 7.2, height: 11)), with: .color(ink))
            ctx.fill(Path(ellipseIn: CGRect(x: cx - 0.3, y: cy - 3.3, width: 2.6, height: 2.6)), with: .color(.white))
        }
    }

    private func mouth(_ ctx: inout GraphicsContext) {
        switch look.mouth {
        case "grin":
            var p = Path(); p.move(to: CGPoint(x: 42, y: 64)); p.addQuadCurve(to: CGPoint(x: 58, y: 64), control: CGPoint(x: 50, y: 74)); p.closeSubpath()
            ctx.fill(p, with: .color(Color(hex: 0x7A1F35)))
            ctx.fill(Path(roundedRect: CGRect(x: 43, y: 64, width: 14, height: 3), cornerRadius: 1.5), with: .color(.white))
        case "o":
            ctx.fill(Path(ellipseIn: CGRect(x: 47, y: 62.4, width: 6, height: 7.2)), with: .color(Color(hex: 0x7A1F35)))
        case "flat":
            ctx.fill(Path(roundedRect: CGRect(x: 45, y: 65, width: 10, height: 2.4), cornerRadius: 1), with: .color(ink))
        default:
            var p = Path(); p.move(to: CGPoint(x: 44, y: 63)); p.addQuadCurve(to: CGPoint(x: 56, y: 63), control: CGPoint(x: 50, y: 69))
            ctx.stroke(p, with: .color(ink), style: StrokeStyle(lineWidth: 2.4, lineCap: .round))
        }
    }

    private func accessory(_ ctx: inout GraphicsContext, hat: Color) {
        switch look.accessory {
        case "glasses":
            let frame = Color(hex: 0x20202A)
            ctx.stroke(Path(ellipseIn: CGRect(x: 30, y: 45, width: 14, height: 14)), with: .color(frame), lineWidth: 2)
            ctx.stroke(Path(ellipseIn: CGRect(x: 56, y: 45, width: 14, height: 14)), with: .color(frame), lineWidth: 2)
            var b = Path(); b.move(to: CGPoint(x: 44, y: 52)); b.addLine(to: CGPoint(x: 56, y: 52))
            ctx.stroke(b, with: .color(frame), lineWidth: 2)
        case "headphones", "headset":
            var band = Path(); band.move(to: CGPoint(x: 18, y: 50)); band.addQuadCurve(to: CGPoint(x: 82, y: 50), control: CGPoint(x: 50, y: -22))
            ctx.stroke(band, with: .color(Color(hex: 0x2A2A36)), lineWidth: 4)
            if look.accessory == "headphones" {
                ctx.fill(Path(roundedRect: CGRect(x: 12, y: 44, width: 10, height: 16), cornerRadius: 4), with: .color(c(look.top.accent)))
            }
            ctx.fill(Path(roundedRect: CGRect(x: 78, y: 44, width: 10, height: 16), cornerRadius: 4), with: .color(c(look.top.accent)))
        case "cap":
            var p = Path(); p.move(to: CGPoint(x: 20, y: 30)); p.addQuadCurve(to: CGPoint(x: 80, y: 30), control: CGPoint(x: 50, y: -10)); p.closeSubpath()
            ctx.fill(p, with: .color(hat))
            ctx.fill(Path(roundedRect: CGRect(x: 40, y: 26, width: 34, height: 6), cornerRadius: 3), with: .color(hat))
        case "visor":
            ctx.fill(Path(roundedRect: CGRect(x: 20, y: 24, width: 60, height: 6), cornerRadius: 3), with: .color(hat))
        case "beret":
            ctx.fill(Path(ellipseIn: CGRect(x: 11, y: 10, width: 68, height: 20)), with: .color(hat))
        case "beanie":
            var p = Path(); p.move(to: CGPoint(x: 19, y: 32)); p.addQuadCurve(to: CGPoint(x: 81, y: 32), control: CGPoint(x: 50, y: -20)); p.closeSubpath()
            ctx.fill(p, with: .color(hat))
            ctx.fill(Path(roundedRect: CGRect(x: 18, y: 26, width: 64, height: 8), cornerRadius: 3), with: .color(hat.opacity(0.8)))
        case "bowtie":
            var p = Path()
            p.move(to: CGPoint(x: 42, y: 84)); p.addLine(to: CGPoint(x: 50, y: 88)); p.addLine(to: CGPoint(x: 42, y: 92)); p.closeSubpath()
            p.move(to: CGPoint(x: 58, y: 84)); p.addLine(to: CGPoint(x: 50, y: 88)); p.addLine(to: CGPoint(x: 58, y: 92)); p.closeSubpath()
            ctx.fill(p, with: .color(c(look.top.accent)))
        case "scarf":
            ctx.fill(Path(roundedRect: CGRect(x: 30, y: 78, width: 40, height: 8), cornerRadius: 4), with: .color(hat))
        default: break
        }
    }
}
