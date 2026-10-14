import SwiftUI

/// Same palette as the web app (#070B18 ground, cyan/violet accents, semantic green/amber/red).
enum Theme {
    static let ground = Color(hex: 0x070B18)
    static let surface = Color(hex: 0x111A2E)
    static let cyan = Color(hex: 0x32D8FF)
    static let violet = Color(hex: 0xA66BFF)
    static let ok = Color(hex: 0x5BF2A5)
    static let warn = Color(hex: 0xFFBD69)
    static let bad = Color(hex: 0xFF6178)
    static let gold = Color(hex: 0xF4D58D)
    static let ink = Color(hex: 0xEAF2FF)

    static func status(_ s: String) -> Color {
        switch s {
        case "COMPLETED", "RUNNING", "pass", "RELEASE_AUTHORIZED", "EXECUTING": return ok
        case "FAILED", "CANCELLED", "REJECTED", "fail", "BLOCKED": return bad
        case "WAITING_FOR_APPROVAL", "warn", "REVISION_REQUESTED", "CHANGES_REQUESTED": return warn
        case "OWNER_APPROVAL": return gold
        default: return cyan
        }
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255, blue: Double(hex & 0xFF) / 255)
    }

    init(hexString: String) {
        let clean = hexString.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        self.init(hex: UInt32(clean, radix: 16) ?? 0x32D8FF)
    }
}

struct StatusPill: View {
    let text: String
    let color: Color

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(text).font(.caption).lineLimit(1)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .foregroundStyle(color)
        .background(color.opacity(0.12), in: Capsule())
        .accessibilityElement(children: .combine)
    }
}
