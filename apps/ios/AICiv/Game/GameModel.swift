import Foundation
import Observation
import SpriteKit

/// Shared between the SpriteKit town and the SwiftUI controls on top of it.
@MainActor
@Observable
final class GameModel {
    enum Panel: String, Identifiable { case journal, approvals, avatar, findings; var id: String { rawValue } }

    struct Nearby: Equatable {
        enum Kind { case npc, object }
        let kind: Kind
        let id: String
        let label: String
    }

    var mapId = "town"
    var talkingTo: String?
    var panel: Panel?
    var packageId: String?
    var nearby: Nearby?
    var toast: (text: String, at: Date)?
    var name = "Owner"
    var look = PlayerLook()
    var showMap = true
    /// Joystick vector in [-1, 1].
    var stick = CGVector.zero
    /// Bumped by the Talk / Use button; the scene acts on whatever is near.
    var interactSeq = 0

    /// Who lives in town: the live roster when connected, otherwise the cast bundled with the app.
    var agents: [TownAgent] = []
    var packages: [TownPackage] = []
    var serverOffset: TimeInterval = 0
    /// LIVE, SIMULATION or OFFLINE, for the top bar.
    var mode = "OFFLINE"

    /// Where the player stands (the scene writes it; saving and the minimap read it).
    var player = (map: "town", x: 24.5, y: 20.5, facing: Dir.up)
    var restored = false
    var moved = false

    @ObservationIgnored lazy var scene: TownScene = {
        let s = TownScene(size: CGSize(width: 390, height: 844))
        s.model = self
        return s
    }()

    func say(_ text: String) { toast = (text, Date()) }
    func interact() { interactSeq += 1 }

    func talk(_ id: String?) { talkingTo = id; if id != nil { panel = nil } }

    /// Keeps the town's cast in step with the server (or the bundled cast when offline).
    func sync(from app: AppState) {
        let source: [Agent] = app.agents.isEmpty ? Roster.bundled : Array(app.agents.values)
        let live = !app.agents.isEmpty
        agents = source.map { a in
            TownAgent(id: a.id, key: a.key, name: a.name, role: a.role, homeDistrict: a.homeDistrict,
                      district: live ? (a.district ?? a.homeDistrict) : a.homeDistrict,
                      execState: live ? a.executionState : "IDLE", moving: live && a.movementState == "MOVING",
                      carrying: nil, look: a.avatar.look, color: a.avatar.color)
        }.sorted { $0.id < $1.id }
        packages = live ? app.packages : []
        serverOffset = app.serverOffset
        mode = app.connection == .live ? (app.executionMode == "simulation" ? "SIMULATION" : "LIVE") : live ? "RECONNECTING" : "OFFLINE"
    }

    func agent(_ id: String?) -> TownAgent? { agents.first { $0.id == id } }
}

/// The agents shipped with the app (packages/shared-types/seed/agents.json), so the town is never empty.
enum Roster {
    private struct Seed: Decodable {
        struct A: Decodable {
            let id: String
            let key: String
            let name: String
            let role: String
            let homeDistrict: String
            let avatar: Agent.Avatar
            let modelName: String?
            let tier: String?
        }
        let agents: [A]
    }

    static let bundled: [Agent] = {
        guard let url = Bundle.main.url(forResource: "agents", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let seed = try? APIClient.decoder.decode(Seed.self, from: data) else { return [] }
        return seed.agents.map {
            Agent(id: $0.id, key: $0.key, name: $0.name, role: $0.role, homeDistrict: $0.homeDistrict, avatar: $0.avatar,
                  modelName: $0.modelName ?? "", executionState: "IDLE", tier: $0.tier, district: $0.homeDistrict, supervisorAgentId: nil)
        }
    }()
}
