import Foundation

/// Mirrors packages/event-contracts (schema v1). Decoded with `.convertFromSnakeCase`.
struct EventEnvelope: Codable, Identifiable, Equatable {
    let eventId: String
    let schemaVersion: Int
    let organizationId: String
    let missionId: String?
    let agentId: String?
    let eventType: String
    let sequence: Int
    let occurredAt: String
    let correlationId: String
    let payload: [String: JSONValue]
    let executionMode: String?

    var id: String { eventId }
    var isSimulation: Bool { executionMode == "simulation" }
}

struct EventsPage: Codable { let events: [EventEnvelope] }

struct Agent: Codable, Identifiable, Hashable {
    struct Avatar: Codable, Hashable { let shape: String; let color: String; let height: Double; var look: Look? = nil }
    /// The agent's chibi character (same data the 3D city and the web roster draw from).
    struct Look: Codable, Hashable {
        struct Hair: Codable, Hashable { let style: String; let color: String }
        struct Top: Codable, Hashable { let style: String; let color: String; let accent: String }
        struct Bottom: Codable, Hashable { let style: String; let color: String }
        let skin: String
        let hair: Hair
        let eyes: String
        let eyeColor: String
        let mouth: String
        let top: Top
        let bottom: Bottom
        let shoes: String
        let accessory: String
        var hatColor: String? = nil
        var prop: String? = nil
        var blush: Bool? = nil
        var mustache: Bool? = nil
    }
    let id: String
    let key: String
    let name: String
    let role: String
    let homeDistrict: String
    let avatar: Avatar
    let modelName: String
    let executionState: String
    let tier: String?
    let district: String?
    let supervisorAgentId: String?
    /// STATIONARY | MOVING (from agent_positions); visual only, never a sign of work.
    var movementState: String? = nil
}

struct MissionRow: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let status: String
    let executionMode: String
    let kind: String?
    let budgetUsd: Double
    let spentUsdEstimated: Double
    let failureReason: String?
    let outcome: String?
    let createdAt: String
}

struct OpportunitySummary: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let status: String
    let opportunityScore: Double
    let confidence: String
    let dataMode: String
    let updatedAt: String
}

struct District: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let purpose: String?
    let position: [Double]
    let color: String
    let architecture: String?
    var x: Double { position.first ?? 0 }
    var z: Double { position.count > 2 ? position[2] : 0 }
}

struct Snapshot: Codable {
    let sequence: Int
    let agents: [Agent]
    let districts: [District]?
    let missions: [MissionRow]
    let opportunities: [OpportunitySummary]?
    let emergencyStopped: Bool
    let executionMode: String
    var approvals: [ApprovalRow]? = nil
    var logistics: SnapshotLogistics? = nil
}

/// A mission step waiting for the owner (approvals table).
struct ApprovalRow: Codable, Identifiable, Hashable {
    let id: String
    let missionId: String
    let action: String
    let summary: String
    let status: String
}

/// Conveyor packages and the server clock they move by.
struct SnapshotLogistics: Codable {
    struct Package: Codable, Hashable {
        let id: String
        let packageType: String
        let status: String
        let originDistrict: String
        let destinationDistrict: String
        let routeStartedAt: String?
        let eta: String?
    }
    let packages: [Package]?
    let serverTime: String?
}

enum ISODate {
    private static let fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let plain = ISO8601DateFormatter()
    static func parse(_ s: String?) -> Date? {
        guard let s else { return nil }
        return fractional.date(from: s) ?? plain.date(from: s)
    }
}

struct OpportunityList: Codable { let opportunities: [OpportunitySummary] }

struct Health: Codable {
    let status: String
    let authMode: String
    let executionMode: String
    let providers: [String]
    let networkIsolation: Bool
    let emergencyStopped: Bool
}

/// Everything the Owner's Tower shows for one release (GET /api/opportunities/{id}).
struct Dossier: Codable {
    struct Opportunity: Codable {
        let id: String
        let title: String
        let description: String
        let status: String
        let confidence: String
        let opportunityScore: Double
        let estimatedCostUsd: Double
        let dataMode: String
        let riskFlags: [String]
        let revisionCount: Int
        let spec: [String: JSONValue]
    }
    struct Review: Codable {
        let id: String
        let artifactId: String
        let artifactDigest: String
        let verdict: String
        let summary: String
        let method: String
        let model: String?
    }
    struct ChecklistItem: Codable, Identifiable {
        let category: String
        let status: String
        let evidence: String
        var id: String { category }
    }
    struct Bundle: Codable { let artifactId: String; let digest: String; let title: String }
    struct TestReport: Codable {
        let bundleDigest: String?
        let passed: Int?
        let failed: Int?
        let errors: Int?
        let summaryLine: String?
    }
    struct Finding: Codable, Identifiable {
        let id: String
        let title: String
        let summary: String
        let sourceUrl: String
        let collectedAt: String
        let geographicScope: String
        let dataCoverage: String
        let measurementType: String
        let confidence: String
        let dataMode: String
    }
    struct Authorization: Codable, Identifiable {
        let id: String
        let artifactDigest: String
        let invalidated: Bool?
    }

    let opportunity: Opportunity
    let managerReview: Review?
    let checklist: [ChecklistItem]
    let bundle: Bundle?
    let testReport: TestReport?
    let findings: [Finding]
    let estimatedSpendUsd: Double
    let awaitingOwner: Bool
    let risks: [String]
    let authorizations: [Authorization]

    var appName: String { opportunity.spec.get("app_name")?.string ?? opportunity.title }
    var tagline: String { opportunity.spec.get("tagline")?.string ?? opportunity.description }
    var testedExactBundle: Bool { testReport?.bundleDigest != nil && testReport?.bundleDigest == bundle?.digest }
}

enum OwnerDecision: String, CaseIterable, Identifiable {
    case approve = "APPROVE"
    case requestChanges = "REQUEST_CHANGES"
    case defer_ = "DEFER"
    case reject = "REJECT"

    var id: String { rawValue }
    var label: String {
        switch self {
        case .approve: return "Approve this release"
        case .requestChanges: return "Request changes"
        case .defer_: return "Decide later"
        case .reject: return "Reject"
        }
    }
}

struct OwnerDecisionRequest: Codable {
    let decision: String
    let artifactDigest: String
    let note: String?
}

struct ResearchRequest: Codable { let source: String; let query: String; let region: String }

enum Format {
    static func human(_ s: String) -> String {
        let t = s.lowercased().replacingOccurrences(of: "_", with: " ")
        return t.prefix(1).uppercased() + t.dropFirst()
    }

    static func usd(_ v: Double) -> String {
        v > 0 && v < 0.01 ? String(format: "$%.4f", v) : String(format: "$%.2f", v)
    }
}
