import Foundation

/// Ordered, deduplicated, gap-aware application of backend events — the same rules as the web client's
/// interpreter: duplicates are ignored, and a gap holds later events back until the missing range is replayed.
struct EventLedger {
    private(set) var lastSequence: Int
    private(set) var feed: [EventEnvelope] = []
    private(set) var held: [EventEnvelope] = []
    /// Opportunity ids whose release package is waiting at the Owner's Tower.
    private(set) var ownerQueue: [String] = []

    init(lastSequence: Int = 0, ownerQueue: [String] = []) {
        self.lastSequence = lastSequence
        self.ownerQueue = ownerQueue
    }

    /// Returns events that became newly applied (in order) and whether a replay is needed.
    mutating func ingest(_ incoming: [EventEnvelope]) -> (applied: [EventEnvelope], needsReplay: Bool) {
        var pending = (held + incoming).sorted { $0.sequence < $1.sequence }
        held = []
        var applied: [EventEnvelope] = []
        var gap = false
        while !pending.isEmpty {
            let e = pending.removeFirst()
            if e.sequence <= lastSequence { continue }
            if lastSequence != 0 && e.sequence > lastSequence + 1 {
                gap = true
                held = [e] + pending.filter { $0.sequence > lastSequence }
                break
            }
            lastSequence = e.sequence
            apply(e)
            applied.append(e)
        }
        feed = (applied.reversed() + feed).prefix(400).map { $0 }
        return (applied, gap)
    }

    private mutating func apply(_ e: EventEnvelope) {
        let oid = e.payload.get("opportunity_id")?.string
        switch e.eventType {
        case "release.owner_approval_requested":
            if let oid, !ownerQueue.contains(oid) { ownerQueue.append(oid) }
        case "release.owner_approved", "release.owner_rejected":
            ownerQueue.removeAll { $0 == oid }
        case "opportunity.status_changed":
            if e.payload.get("from")?.string == "OWNER_APPROVAL" { ownerQueue.removeAll { $0 == oid } }
        default:
            break
        }
    }

    mutating func reset(lastSequence: Int, ownerQueue: [String]) {
        self.lastSequence = lastSequence
        self.ownerQueue = ownerQueue
        held = []
    }
}

enum FeedText {
    /// One plain-language line per event, matching the web feed's wording.
    static func line(_ e: EventEnvelope, agents: [String: Agent]) -> (who: String, text: String) {
        let p = e.payload
        let who = e.agentId.flatMap { agents[$0]?.name } ?? "System"
        func s(_ k: String) -> String { p.get(k)?.string ?? "" }
        switch e.eventType {
        case "mission.created": return (who, "Mission created: \(s("title"))")
        case "mission.completed": return (who, "Mission completed")
        case "mission.failed": return (who, "Mission failed: \(s("failure_reason"))")
        case "task.started": return (who, "Started: \(s("title"))")
        case "task.completed": return (who, "Finished: \(s("title"))")
        case "tool.started": return (who, "Running \(s("tool"))")
        case "tool.failed": return (who, "\(s("tool")) failed: \(s("error"))")
        case "agent.message": return (who, s("body"))
        case "research.opportunity_identified": return (who, "Opportunity: \(s("title"))")
        case "research.finding_created": return (who, "Finding: \(s("title"))" + (s("data_mode") == "fixture" ? " [fixture data]" : ""))
        case "package.dispatched": return (who, "\(Format.human(s("package_type"))) on the belt to \(s("destination"))")
        case "package.arrived": return (who, "\(Format.human(s("package_type"))) arrived at \(s("destination"))")
        case "manager.review_completed": return (who, "Review: \(Format.human(s("outcome")))")
        case "release.owner_approval_requested": return (who, "Waiting for your decision: \(s("title"))")
        case "release.owner_approved": return (who, "You approved the release")
        case "release.authorized": return (who, "Release authorized")
        case "release.invalidated": return (who, "Approval cancelled: \(s("reason"))")
        case "release.executed": return (who, "Released to the local release channel")
        case "approval.requested": return (who, "Asks for approval: \(s("summary"))")
        default: return (who, Format.human(e.eventType.replacingOccurrences(of: ".", with: " ")))
        }
    }
}
