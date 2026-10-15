import SwiftUI

/// The pixel-art look from the web app, for SwiftUI: hard 2 px edges, a neon rim, dark panels, monospaced caps.
enum Pixel {
    static let panel = Color(hex: 0x0A1022)
    static let rim = Color(hex: 0x32D8FF).opacity(0.35)
    static let sky = LinearGradient(colors: [Color(hex: 0x0A0D2B), Color(hex: 0x2A1650), Color(hex: 0x4A1F55)], startPoint: .top, endPoint: .bottom)

    static func title(_ size: CGFloat = 13) -> Font { .system(size: size, weight: .heavy, design: .monospaced) }
    static func mono(_ size: CGFloat = 12) -> Font { .system(size: size, weight: .regular, design: .monospaced) }

    /// District colours, matching packages/world-engine/src/districts.json.
    static let districtColor: [String: Color] = [
        "nexus-spire": Color(hex: 0x4C8DFF), "code-forge": Color(hex: 0xFF9A3D), "sentinel-citadel": Color(hex: 0x3FB8FF),
        "vision-quarter": Color(hex: 0xFF4FB0), "data-observatory": Color(hex: 0x5B8CFF), "memory-vault": Color(hex: 0xA66BFF),
        "owners-tower": Color(hex: 0xF4D58D), "central-bank": Color(hex: 0x3DE08A), "claude-code-factory": Color(hex: 0xFF8A5C),
        "github-factory": Color(hex: 0xB8C4D6),
    ]
}

struct PixelPanel: ViewModifier {
    var color: Color = Pixel.rim
    func body(content: Content) -> some View {
        content
            .padding(12)
            .background(Pixel.panel, in: RoundedRectangle(cornerRadius: 4))
            .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(color, lineWidth: 2))
            .overlay(RoundedRectangle(cornerRadius: 5).strokeBorder(Color.black.opacity(0.8), lineWidth: 1).padding(-2))
            .shadow(color: color.opacity(0.35), radius: 8)
    }
}

extension View {
    func pixelPanel(_ color: Color = Pixel.rim) -> some View { modifier(PixelPanel(color: color)) }
}

/// A section heading in pixel caps, like the web dashboard's panel titles.
struct PixelHeader: View {
    let text: String
    var color: Color = Theme.cyan
    var trailing: String? = nil
    var body: some View {
        HStack {
            Text(text.uppercased()).font(Pixel.title(11)).foregroundStyle(color).kerning(0.8)
            Spacer()
            if let trailing { Text(trailing).font(Pixel.mono(10)).foregroundStyle(.secondary) }
        }
    }
}

/// The district neon sign: an icon tile and the name on a dark board with a glowing rim.
struct NeonSign: View {
    let icon: String
    let text: String
    let color: Color
    var sub: String? = nil
    var body: some View {
        HStack(spacing: 6) {
            Text(icon).font(Pixel.title(11)).foregroundStyle(Color.black).frame(minWidth: 22, minHeight: 22).background(color, in: RoundedRectangle(cornerRadius: 3))
            VStack(alignment: .leading, spacing: 0) {
                Text(text.uppercased()).font(Pixel.title(12)).foregroundStyle(.white).shadow(color: color, radius: 4)
                if let sub { Text(sub.uppercased()).font(Pixel.mono(8)).foregroundStyle(color) }
            }
        }
        .padding(.vertical, 4).padding(.leading, 4).padding(.trailing, 10)
        .background(Pixel.panel, in: RoundedRectangle(cornerRadius: 4))
        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(color, lineWidth: 2))
        .shadow(color: color.opacity(0.6), radius: 6)
    }
}

/// One figure in the stats bar.
struct StatTile: View {
    let label: String
    let value: String
    var sub: String? = nil
    var color: Color = Theme.ink
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased()).font(Pixel.mono(9)).foregroundStyle(.secondary)
            Text(value).font(Pixel.title(16)).foregroundStyle(color).lineLimit(1).minimumScaleFactor(0.6)
            if let sub { Text(sub).font(Pixel.mono(9)).foregroundStyle(.secondary).lineLimit(1) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .pixelPanel()
        .accessibilityElement(children: .combine)
    }
}

/// A segmented pixel progress bar.
struct PixelBar: View {
    let progress: Double
    var color: Color = Theme.ok
    var body: some View {
        GeometryReader { g in
            let cells = max(1, Int(g.size.width / 8))
            HStack(spacing: 2) {
                ForEach(0..<cells, id: \.self) { i in
                    Rectangle().fill(Double(i) / Double(cells) < progress ? color : Color.white.opacity(0.08))
                }
            }
        }
        .frame(height: 6)
        .accessibilityLabel("\(Int(progress * 100)) percent")
    }
}

enum Money {
    static func minor(_ v: Int?, currency: String = "USD") -> String {
        guard let v else { return "—" }
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = currency
        return f.string(from: NSNumber(value: Double(v) / 100)) ?? "\(v)"
    }
}

enum Ago {
    static func text(_ iso: String) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let d = f.date(from: iso) ?? ISO8601DateFormatter().date(from: iso)
        guard let d else { return "" }
        return RelativeDateTimeFormatter().localizedString(for: d, relativeTo: Date())
    }
}
