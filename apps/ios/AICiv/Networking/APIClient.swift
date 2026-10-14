import Foundation

struct APIError: LocalizedError {
    let status: Int
    let detail: String
    var errorDescription: String? { status == 0 ? detail : "\(detail) (\(status))" }
}

/// Talks to the AI Civilization API. The bearer token lives in the Keychain, never in UserDefaults.
final class APIClient {
    let baseURL: URL
    let token: String?
    private let session: URLSession

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    init(baseURL: URL, token: String?, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.token = (token?.isEmpty ?? true) ? nil : token
        self.session = session
    }

    func request(_ path: String, method: String = "GET", body: Data? = nil) -> URLRequest {
        var r = URLRequest(url: URL(string: path, relativeTo: baseURL)!)
        r.httpMethod = method
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token { r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        r.httpBody = body
        r.timeoutInterval = 20
        return r
    }

    private func send<T: Decodable>(_ req: URLRequest, as: T.Type) async throws -> T {
        let (data, resp) = try await session.data(for: req)
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"] as? String
            throw APIError(status: status, detail: detail ?? HTTPURLResponse.localizedString(forStatusCode: status))
        }
        return try Self.decoder.decode(T.self, from: data)
    }

    func health() async throws -> Health { try await send(request("/api/health"), as: Health.self) }
    func snapshot() async throws -> Snapshot { try await send(request("/api/snapshot"), as: Snapshot.self) }
    func events(after: Int) async throws -> [EventEnvelope] {
        try await send(request("/api/events?after=\(after)&limit=500"), as: EventsPage.self).events
    }
    func opportunities() async throws -> [OpportunitySummary] {
        try await send(request("/api/opportunities"), as: OpportunityList.self).opportunities
    }
    func dossier(_ id: String) async throws -> Dossier { try await send(request("/api/opportunities/\(id)"), as: Dossier.self) }

    func decide(_ id: String, decision: OwnerDecision, digest: String, note: String?) async throws {
        let body = try Self.encoder.encode(OwnerDecisionRequest(decision: decision.rawValue, artifactDigest: digest, note: note))
        _ = try await send(request("/api/opportunities/\(id)/owner-decision", method: "POST", body: body), as: [String: JSONValue].self)
    }

    func startResearch(source: String, query: String, region: String = "US") async throws {
        let body = try Self.encoder.encode(ResearchRequest(source: source, query: query, region: region))
        _ = try await send(request("/api/research", method: "POST", body: body), as: [String: JSONValue].self)
    }

    /// The prototype's preview page from the release bundle.
    func bundleFile(artifactId: String, path: String) async throws -> String {
        let (data, resp) = try await session.data(for: request("/api/artifacts/\(artifactId)/files/\(path)"))
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw APIError(status: 0, detail: "Preview unavailable") }
        return String(decoding: data, as: UTF8.self)
    }

    func streamRequest(after: Int) -> URLRequest {
        var r = request("/api/stream?after=\(after)")
        r.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        r.timeoutInterval = 60 * 60
        return r
    }
}
