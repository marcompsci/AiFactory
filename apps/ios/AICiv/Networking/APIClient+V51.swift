import Foundation

/// V5.1 endpoints: dashboard overview, the money game, App Lab, the factories, and public sign-in config.
/// These screens read flexible JSON (`JSONValue`) so a new field on the server never breaks decoding.
extension APIClient {
    func json(_ path: String, method: String = "GET", body: [String: JSONValue]? = nil, stepUp: String? = nil) async throws -> JSONValue {
        var r = request(path, method: method, body: try body.map { try JSONEncoder().encode($0) })
        if let stepUp { r.setValue(stepUp, forHTTPHeaderField: "X-Step-Up") }
        let (data, resp) = try await URLSession.shared.data(for: r)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let raw = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
            let detail = (raw as? String) ?? ((raw as? [String: Any])?["message"] as? String)
            throw APIError(status: status, detail: detail ?? HTTPURLResponse.localizedString(forStatusCode: status))
        }
        // plain JSONDecoder: keys stay snake_case, read them with `.get("snake_key")`
        return try JSONDecoder().decode(JSONValue.self, from: data)
    }

    func overview() async throws -> JSONValue { try await json("/api/overview") }
    func game() async throws -> JSONValue { try await json("/api/game") }
    func lab() async throws -> JSONValue { try await json("/api/applab") }
    func labProposal(_ id: String) async throws -> JSONValue { try await json("/api/applab/proposals/\(id)") }
    func labStartCycle(_ repoId: String) async throws { _ = try await json("/api/applab/repositories/\(repoId)/cycles", method: "POST") }
    func labDecide(_ id: String, decision: String, payloadHash: String, stepUp: String?) async throws {
        _ = try await json("/api/applab/proposals/\(id)/decide", method: "POST",
                           body: ["decision": .string(decision), "payload_hash": .string(payloadHash)], stepUp: stepUp)
    }
    func factories() async throws -> JSONValue { try await json("/api/factories") }
    func factoryLink(_ kind: String, enabled: Bool) async throws {
        _ = try await json("/api/factories/\(kind)/link", method: "POST", body: ["enabled": .bool(enabled)])
    }
    func factorySync() async throws { _ = try await json("/api/factories/sync", method: "POST") }
    func publicConfig() async throws -> JSONValue { try await json("/api/public-config") }
}

extension JSONValue {
    func get(_ key: String) -> JSONValue? {
        guard case .object(let o) = self, let v = o[key] ?? o[key.snakeToCamel] else { return nil }
        if case .null = v { return nil }  // JSON null reads as "absent"
        return v
    }
    var list: [JSONValue] { array ?? [] }
    var int: Int? { double.map { Int($0) } }
    var str: String { string ?? "" }
    var isTrue: Bool { bool ?? ((int ?? 0) != 0) }
    /// "s" for "key" — shorthand used throughout the V5.1 views.
    func s(_ key: String) -> String { get(key)?.string ?? "" }
}

extension JSONValue: Identifiable {
    public var id: String { s("id").isEmpty ? (s("agent_id") + s("key") + s("label") + s("number") + s("sha")) : s("id") }
}
