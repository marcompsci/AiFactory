import Foundation

/// AI Central Bank (V5). Amounts are integer minor units (cents), exactly as the server stores them.
struct FinancePacket: Codable, Identifiable, Hashable {
    let id: String
    let origin: String
    let status: String
    let vendor: String
    let item: String
    let amountMinor: Int
    let currency: String
    let interval: String
    let classification: String?
    let classificationReason: String?
    let significant: Int
    let risk: String?
    let researchRounds: Int
    let recommendation: [String: JSONValue]
    let gmDecision: [String: JSONValue]
    let dataMode: String

    var isSimulated: Bool { dataMode == "simulated" }
    var summary: String? { recommendation.get("summary")?.string }
}

struct FinancePacketList: Codable { let packets: [FinancePacket] }

struct FinanceApproval: Codable, Identifiable, Hashable {
    let id: String
    let packetId: String?
    let actionType: String
    let amountMinor: Int
    let currency: String
    let recipient: String
    let accountRef: String
    let details: [String: JSONValue]
    let payloadHash: String
    let status: String
    let expiresAt: String
    let dataMode: String

    var option: String? { details.get("option")?.string }
    var accountLabel: String { details.get("account_label")?.string ?? accountRef }
    var billingInterval: String? { details.get("interval")?.string }
    var itemName: String? { details.get("item")?.string }
}

struct FinancePacketDetail: Codable {
    let packet: FinancePacket
    let approvals: [FinanceApproval]
}

struct StepUpToken: Codable { let stepUpToken: String }
struct StepUpVerifyRequest: Codable { let code: String; let purpose: String }

struct PacketDecisionRequest: Codable {
    let decision: String
    let approvalId: String?
    let payloadHash: String?
    let note: String?
    let deferDays: Int?
}

extension Format {
    static func money(_ minor: Int, currency: String = "USD") -> String {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = currency
        return f.string(from: NSNumber(value: Double(minor) / 100)) ?? "\(currency) \(Double(minor) / 100)"
    }
}
