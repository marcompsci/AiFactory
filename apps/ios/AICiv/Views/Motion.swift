import SwiftUI
import UIKit

/// Motion, press feedback, haptics and wording in one place, following Emil Kowalski's design-engineering rules:
/// UI motion is quick (under 300 ms), eases out or uses a critically damped spring (interruptible, no bounce), never
/// starts from nothing, and with Reduce Motion becomes a fade instead of a slide. Every control answers the press the
/// moment the finger lands.
enum Motion {
    /// Panels, toasts and cards coming and going.
    static let ui = Animation.spring(duration: 0.3, bounce: 0)
    /// Press feedback: fast and ease-out.
    static let press = Animation.easeOut(duration: 0.12)

    static func ui(reduce: Bool) -> Animation { reduce ? .easeOut(duration: 0.18) : ui }
}

extension AnyTransition {
    /// Slides in from its edge with a fade, and leaves the same way, faster than it came. Reduce Motion: a fade only.
    static func fromEdge(_ edge: Edge, reduce: Bool) -> AnyTransition {
        if reduce { return .opacity }
        let dy: CGFloat = edge == .top ? -12 : edge == .bottom ? 12 : 0
        let dx: CGFloat = edge == .leading ? -12 : edge == .trailing ? 12 : 0
        let shift = AnyTransition.offset(x: dx, y: dy).combined(with: .opacity).combined(with: .scale(scale: 0.97))
        return .asymmetric(insertion: shift, removal: shift.animation(.easeOut(duration: 0.15)))
    }
}

extension View {
    /// Scale down a touch on press (0.97, or less for small icons) with an ease-out.
    func pressFeedback(_ pressed: Bool, scale: CGFloat = 0.97) -> some View {
        scaleEffect(pressed ? scale : 1).animation(Motion.press, value: pressed)
    }
}

/// Plain press feedback for custom tappable things (rows, tiles, cards) that otherwise only dim.
struct PressableStyle: ButtonStyle {
    var scale: CGFloat = 0.97
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.contentShape(Rectangle()).pressFeedback(configuration.isPressed, scale: scale)
    }
}

/// The phone answers decisions the way native apps do: a success tap when something you approved went through,
/// a warning when it didn't.
enum Haptics {
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func warning() { UINotificationFeedbackGenerator().notificationOccurred(.warning) }
    static func light() { UIImpactFeedbackGenerator(style: .light).impactOccurred() }
}

/// "1 run", "3 runs": never "3 run(s)".
enum Plural {
    static func of(_ n: Int, _ one: String, _ many: String? = nil) -> String {
        "\(n) \(n == 1 ? one : (many ?? one + "s"))"
    }
}
