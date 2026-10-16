import Foundation

/// V6 playable town: your character, conversations with agents, and proposals that run only on Confirm.
extension APIClient {
    func playState() async throws -> JSONValue { try await json("/api/play/state") }

    func savePlay(name: String, look: PlayerLook, map: String, x: Double, y: Double, facing: Dir) async throws {
        let lookJSON: [String: JSONValue] = [
            "skin": .string(look.skin), "hair_style": .string(look.hairStyle), "hair": .string(look.hair), "shirt": .string(look.shirt),
            "pants": .string(look.pants), "shoes": .string(look.shoes), "glasses": .bool(look.glasses),
        ]
        _ = try await json("/api/play/state", method: "PUT", body: [
            "name": .string(name), "look": .object(lookJSON), "map": .string(map),
            "x": .number((x * 100).rounded() / 100), "y": .number((y * 100).rounded() / 100), "facing": .string(facing.rawValue),
        ])
    }

    func conversation(_ agentId: String) async throws -> JSONValue { try await json("/api/play/conversations/\(agentId)") }

    func talk(_ agentId: String, _ text: String) async throws -> JSONValue {
        try await json("/api/play/talk", method: "POST", body: ["agent_id": .string(agentId), "text": .string(text)])
    }

    func confirmProposal(_ id: String) async throws -> JSONValue { try await json("/api/play/proposals/\(id)/confirm", method: "POST") }
    func declineProposal(_ id: String) async throws { _ = try await json("/api/play/proposals/\(id)/decline", method: "POST") }

    /// Mission-step approvals (e.g. publishing a reviewed change).
    func decideApproval(_ id: String, grant: Bool) async throws {
        _ = try await json("/api/approvals/\(id)/\(grant ? "grant" : "reject")", method: "POST")
    }

    func missionDetail(_ id: String) async throws -> JSONValue { try await json("/api/missions/\(id)") }
}
