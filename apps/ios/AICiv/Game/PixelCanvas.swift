import CoreGraphics
import Foundation

/// A tiny software canvas for pixel art: integer rectangles with source-over blending, turned into a CGImage.
/// Painting in our own buffer keeps the art identical to the web version and testable without a screen.
struct RGBA: Equatable {
    var r: UInt8, g: UInt8, b: UInt8, a: UInt8

    init(_ r: UInt8, _ g: UInt8, _ b: UInt8, _ a: UInt8 = 255) { self.r = r; self.g = g; self.b = b; self.a = a }

    /// "#RRGGBB" (or "RRGGBB").
    init(hex: String) {
        let s = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
        let n = UInt32(s, radix: 16) ?? 0x888888
        self.init(UInt8((n >> 16) & 255), UInt8((n >> 8) & 255), UInt8(n & 255))
    }

    /// Black or another color at an opacity, like "rgba(0,0,0,0.18)".
    static func alpha(_ r: UInt8, _ g: UInt8, _ b: UInt8, _ a: Double) -> RGBA { RGBA(r, g, b, UInt8(max(0, min(255, (a * 255).rounded())))) }

    var hex: String { String(format: "#%02X%02X%02X", r, g, b) }
}

/// Lighten (amt > 0) or darken (amt < 0) a hex color, the same formula as the web version.
func shade(_ hex: String, _ amt: Double) -> String {
    let c = RGBA(hex: hex)
    func f(_ v: UInt8) -> UInt8 {
        let d = Double(v)
        let out = amt < 0 ? d * (1 + amt) : d + (255 - d) * amt
        return UInt8(max(0, min(255, out.rounded())))
    }
    return RGBA(f(c.r), f(c.g), f(c.b)).hex
}

final class PixelCanvas {
    let width: Int
    let height: Int
    private(set) var px: [RGBA]

    init(_ width: Int, _ height: Int) {
        self.width = width
        self.height = height
        px = Array(repeating: RGBA(0, 0, 0, 0), count: width * height)
    }

    @inline(__always) func blend(_ i: Int, _ c: RGBA) {
        if c.a == 255 { px[i] = c; return }
        if c.a == 0 { return }
        let d = px[i]
        let sa = Double(c.a) / 255, da = Double(d.a) / 255
        let oa = sa + da * (1 - sa)
        guard oa > 0 else { return }
        func ch(_ s: UInt8, _ dd: UInt8) -> UInt8 { UInt8(max(0, min(255, ((Double(s) * sa + Double(dd) * da * (1 - sa)) / oa).rounded()))) }
        px[i] = RGBA(ch(c.r, d.r), ch(c.g, d.g), ch(c.b, d.b), UInt8((oa * 255).rounded()))
    }

    func rect(_ x: Int, _ y: Int, _ w: Int, _ h: Int, _ c: RGBA) {
        let x0 = max(0, x), y0 = max(0, y), x1 = min(width, x + w), y1 = min(height, y + h)
        guard x1 > x0, y1 > y0 else { return }
        for j in y0..<y1 { let row = j * width; for i in x0..<x1 { blend(row + i, c) } }
    }

    func rect(_ x: Int, _ y: Int, _ w: Int, _ h: Int, _ hex: String) { rect(x, y, w, h, PixelCanvas.color(hex)) }

    private static var colors: [String: RGBA] = [:]
    static func color(_ hex: String) -> RGBA {
        if let c = colors[hex] { return c }
        let c = RGBA(hex: hex)
        colors[hex] = c
        return c
    }

    func pixel(_ x: Int, _ y: Int) -> RGBA? { x >= 0 && y >= 0 && x < width && y < height ? px[y * width + x] : nil }

    /// Copy another canvas in at (x, y), blending its transparency.
    func draw(_ other: PixelCanvas, at x: Int, _ y: Int) {
        for j in 0..<other.height {
            let ty = y + j
            guard ty >= 0, ty < height else { continue }
            for i in 0..<other.width {
                let tx = x + i
                guard tx >= 0, tx < width else { continue }
                blend(ty * width + tx, other.px[j * other.width + i])
            }
        }
    }

    func image() -> CGImage? {
        var bytes = [UInt8](repeating: 0, count: width * height * 4)
        for (i, c) in px.enumerated() {
            let a = UInt16(c.a)
            bytes[i * 4] = UInt8(UInt16(c.r) * a / 255)
            bytes[i * 4 + 1] = UInt8(UInt16(c.g) * a / 255)
            bytes[i * 4 + 2] = UInt8(UInt16(c.b) * a / 255)
            bytes[i * 4 + 3] = c.a
        }
        guard let provider = CGDataProvider(data: Data(bytes) as CFData) else { return nil }
        return CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: width * 4,
                       space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                       provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)
    }
}

/// Deterministic per-tile noise (same as the web version's hash), for grass tufts and pebbles.
func tileHash(_ x: Int, _ y: Int, _ s: Int = 0) -> Double {
    var h = Int32(truncatingIfNeeded: x &* 374761393 &+ y &* 668265263 &+ s &* 2147483647)
    h = (h ^ Int32(bitPattern: UInt32(bitPattern: h) >> 13)) &* 1274126177
    let u = UInt32(bitPattern: h ^ Int32(bitPattern: UInt32(bitPattern: h) >> 16))
    return Double(u) / 4294967296.0
}
