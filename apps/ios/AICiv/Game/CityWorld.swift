import Foundation
import Observation

/// What the city shows on top of the records, worked out from the event stream the same way as the website's world
/// interpreter (packages/world-engine/src/interpreter.ts): who was just assigned what, which desk is using which tool,
/// what an agent just said, what needs approval, how busy each district is, and a celebration when a mission finishes.
/// With no server it plays the website's scripted demo mission (simulation.ts demoScript), clearly labelled as a demo.
@MainActor
@Observable
final class CityWorld {
    struct Indicator: Equatable {
        let kind: String   // assignment | message | tool | approval | complete | error
        let text: String
        let at: Date
    }
    struct Place: Equatable { var district: String; var waypoint: String? }

    var indicators: [String: Indicator] = [:]
    /// workstation id → tool in use there
    var active: [String: String] = [:]
    /// district id → 0…1, decays in the renderer between events
    var activity: [String: Double] = [:]
    var celebrateAt: Date?
    /// Where agents went and what state they are in, from events that arrived before the next snapshot (the demo has no
    /// snapshots at all). A snapshot replaces these.
    var places: [String: Place] = [:]
    var states: [String: String] = [:]
    var carrying: [String: String] = [:]
    var pendingApprovals: Set<String> = []

    // the offline demo
    private(set) var demo = false
    var demoApproval: String?
    private var demoTask: Task<Void, Never>?
    private var demoSequence = 0

    func clearOverrides() {
        places = [:]
        states = [:]
    }

    /// Apply one event (in sequence order). `waypoints` is where each agent stands now, for tool events.
    func apply(_ e: EventEnvelope, now: Date = Date()) {
        func s(_ k: String) -> String { e.payload.get(k)?.string ?? "" }
        let who = e.agentId
        func indicate(_ kind: String, _ text: String) { if let who { indicators[who] = Indicator(kind: kind, text: text, at: now) } }
        func bump(_ district: String, _ by: Double) { if !district.isEmpty { activity[district] = min(1, (activity[district] ?? 0) + by) } }
        switch e.eventType {
        case "task.assigned":
            indicate("assignment", s("title"))
        case "task.started":
            bump(s("district"), 0.35)
        case "agent.movement_requested":
            if let who { places[who] = Place(district: s("to_district"), waypoint: e.payload.get("waypoint")?.string) }
        case "agent.arrived":
            if let who { places[who] = Place(district: s("district"), waypoint: e.payload.get("waypoint")?.string) }
        case "agent.status_changed":
            if let who { states[who] = s("to") }
        case "agent.message":
            indicate("message", s("body"))
        case "tool.started":
            if let who, let w = places[who]?.waypoint ?? waypointOf?(who) { active[w] = s("tool") }
            indicate("tool", s("tool"))
            if let who, let d = places[who]?.district ?? districtOf?(who) { bump(d, 0.2) }
        case "tool.completed", "tool.failed":
            if let who, let w = places[who]?.waypoint ?? waypointOf?(who) { active[w] = nil }
            if e.eventType == "tool.failed" { indicate("error", "\(s("tool")) failed") }
        case "approval.requested":
            pendingApprovals.insert(s("approval_id"))
            indicate("approval", s("summary"))
        case "approval.granted", "approval.rejected":
            pendingApprovals.remove(s("approval_id"))
            if let who, indicators[who]?.kind == "approval" { indicators[who] = nil }
        case "task.completed":
            indicate("complete", s("title"))
        case "task.failed":
            indicate("error", s("error").isEmpty ? s("title") : s("error"))
        case "mission.completed":
            celebrateAt = now
            for k in Self.districtIds { activity[k] = 1 }
        case "mission.failed", "mission.cancelled":
            active = [:]
        case "research.opportunity_identified":
            if let who { carrying[who] = s("title").isEmpty ? "Research brief" : s("title") }
            indicate("complete", "Found: \(s("title"))")
        case "finance.fee_detected":
            indicate("tool", "Fee detected")
        default:
            break
        }
    }

    /// Set by the app so tool events can light the desk an agent is standing at.
    @ObservationIgnored var waypointOf: ((String) -> String?)?
    @ObservationIgnored var districtOf: ((String) -> String?)?

    static var districtIds: [String] { Roster.districts.map(\.id) }

    // MARK: the offline demo (the website's demoScript, step for step)

    private typealias Step = (delay: Int, type: String, who: String?, payload: [String: JSONValue])

    private static func move(_ who: String, _ district: String, _ waypoint: String) -> [Step] {
        [(400, "agent.status_changed", who, ["from": .string("IDLE"), "to": .string("ASSIGNED")]),
         (200, "agent.movement_requested", who, ["to_district": .string(district), "waypoint": .string(waypoint)]),
         (2600, "agent.arrived", who, ["district": .string(district), "waypoint": .string(waypoint)]),
         (100, "agent.status_changed", who, ["from": .string("ASSIGNED"), "to": .string("EXECUTING")])]
    }

    private static func say(_ d: Int, _ type: String, _ who: String?, _ k: String, _ v: String) -> Step { (d, type, who, [k: .string(v)]) }
    private static func task(_ d: Int, _ type: String, _ who: String, _ title: String, _ district: String) -> Step {
        (d, type, who, ["title": .string(title), "district": .string(district)])
    }

    private static let beforeApproval: [Step] = {
        var s: [Step] = []
        s.append(say(0, "mission.created", nil, "title", "Fix the failing test (demo)"))
        s.append(say(600, "agent.message", "commander", "body", "Demo: permissions validated against project policy."))
        s.append(task(500, "task.assigned", "architect", "Inspect repository structure", "code-forge"))
        s.append(task(100, "task.assigned", "qa", "Reproduce the failing test", "sentinel-citadel"))
        s.append(task(100, "task.assigned", "developer", "Implement a fix", "code-forge"))
        s.append((400, "mission.started", nil, [:]))
        s.append(task(100, "task.started", "architect", "Inspect repository structure", "code-forge"))
        s += move("architect", "code-forge", "forge-blueprint")
        s.append(task(100, "task.started", "qa", "Reproduce the failing test", "sentinel-citadel"))
        s.append(say(300, "tool.started", "architect", "tool", "inspect_repository"))
        s.append(say(1200, "tool.completed", "architect", "tool", "inspect_repository"))
        s.append(say(300, "agent.message", "architect", "body", "One source file; tests in tests/."))
        s.append(say(200, "task.completed", "architect", "title", "Inspect repository structure"))
        s.append(say(300, "tool.started", "qa", "tool", "run_tests"))
        s.append(say(1600, "tool.completed", "qa", "tool", "run_tests"))
        s.append(say(200, "agent.message", "qa", "body", "1 failed, 4 passed — test_median_even."))
        s.append(say(200, "task.completed", "qa", "title", "Reproduce the failing test"))
        s.append(task(200, "task.started", "developer", "Implement a fix", "code-forge"))
        s += move("developer", "code-forge", "forge-anvil")
        s.append(say(200, "tool.started", "developer", "tool", "create_worktree"))
        s.append(say(800, "tool.completed", "developer", "tool", "create_worktree"))
        s.append(say(200, "tool.started", "developer", "tool", "edit_file"))
        s.append(say(1400, "tool.completed", "developer", "tool", "edit_file"))
        s.append(say(200, "task.completed", "developer", "title", "Implement a fix"))
        s.append(task(200, "task.started", "qa", "Rerun the tests", "sentinel-citadel"))
        s.append(say(200, "tool.started", "qa", "tool", "run_tests"))
        s.append(say(1600, "tool.completed", "qa", "tool", "run_tests"))
        s.append(say(200, "agent.message", "qa", "body", "5 passed."))
        s.append(say(200, "task.completed", "qa", "title", "Rerun the tests"))
        s.append(task(200, "task.started", "commander", "Publish the reviewable change", "nexus-spire"))
        s += move("commander", "nexus-spire", "nexus-command")
        s.append((300, "approval.requested", "commander", ["approval_id": .string("demo-approval"),
                                                           "summary": .string("Commit the verified fix and publish the patch."),
                                                           "action": .string("prepare_pull_request")]))
        return s
    }()

    private static func afterApproval(_ granted: Bool) -> [Step] {
        if !granted {
            return [say(0, "approval.rejected", nil, "approval_id", "demo-approval"), say(400, "mission.completed", nil, "outcome", "not_published")]
        }
        var s: [Step] = [say(0, "approval.granted", nil, "approval_id", "demo-approval"),
                         say(300, "tool.started", "commander", "tool", "prepare_pull_request"),
                         say(1200, "tool.completed", "commander", "tool", "prepare_pull_request"),
                         say(200, "task.completed", "commander", "title", "Publish the reviewable change")]
        s += move("researcher", "memory-vault", "vault-archive")
        s.append(say(300, "agent.message", "researcher", "body", "Archived in the Memory Vault."))
        s.append(say(400, "mission.completed", nil, "outcome", "published"))
        return s
    }

    /// Start the demo with the bundled cast (key → agent id). Plays once, then waits at the approval.
    func startDemo(ids: [String: String], onEvent: @escaping (EventEnvelope) -> Void) {
        guard !demo else { return }
        demo = true
        play(Self.beforeApproval, ids: ids, onEvent: onEvent) { [weak self] in
            self?.demoApproval = "Commit the verified fix and publish the patch."
        }
    }

    func decideDemo(granted: Bool, ids: [String: String], onEvent: @escaping (EventEnvelope) -> Void) {
        guard demoApproval != nil else { return }
        demoApproval = nil
        play(Self.afterApproval(granted), ids: ids, onEvent: onEvent, then: nil)
    }

    func stopDemo() {
        demoTask?.cancel()
        demoTask = nil
        guard demo else { return }
        demo = false
        demoApproval = nil
        indicators = [:]
        active = [:]
        activity = [:]
        carrying = [:]
        pendingApprovals = []
        clearOverrides()
    }

    private func play(_ steps: [Step], ids: [String: String], onEvent: @escaping (EventEnvelope) -> Void, then: (() -> Void)?) {
        demoTask?.cancel()
        demoTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 800_000_000)
            for st in steps {
                if st.delay > 0 { try? await Task.sleep(nanoseconds: UInt64(st.delay) * 1_000_000) }
                guard let self, !Task.isCancelled, self.demo else { return }
                self.demoSequence += 1
                let e = EventEnvelope(eventId: UUID().uuidString, schemaVersion: 1, organizationId: "demo", missionId: "demo",
                                      agentId: st.who.flatMap { ids[$0] }, eventType: st.type, sequence: self.demoSequence,
                                      occurredAt: ISO8601DateFormatter().string(from: Date()), correlationId: "demo",
                                      payload: st.payload, executionMode: "simulation")
                self.apply(e)
                onEvent(e)
            }
            if !Task.isCancelled { then?() }
        }
    }

    /// The website's names for tools (District.tsx TOOL_TALK), for the speech bubble over a busy district.
    static let toolTalk: [String: String] = [
        "run_tests": "Running tests", "run_build": "Building", "read_file": "Reading code", "search_code": "Searching the code",
        "list_files": "Looking around the repo", "edit_file": "Editing code", "inspect_diff": "Reviewing the change",
        "inspect_repository": "Inspecting the repository", "create_worktree": "Setting up a workspace",
        "query_market_source": "Scanning market charts", "create_artifact": "Writing it up", "prepare_pull_request": "Preparing a pull request",
        "scaffold_prototype": "Building a prototype", "build_release_bundle": "Packaging the release",
        "research_cost_alternatives": "Researching cheaper options", "investigate_alternatives": "Researching free alternatives",
        "score_alternatives": "Scoring alternatives", "sandbox_evaluate_candidate": "Testing in a sandbox",
        "review_sandbox_evidence": "Reviewing test evidence", "classify_cost": "Analyzing a cost", "read_ledger_summary": "Reading the ledger",
        "research_design_insights": "Researching app designs", "scan_repository": "Reading your repository",
        "propose_improvements": "Drafting improvements", "publish_lab_change": "Publishing to GitHub",
        "sync_claude_code": "Checking Claude Code's finished tasks", "read_claude_code_memory": "Reading Claude Code's memory",
        "sync_github_activity": "Checking pull requests and Actions runs", "sync_codex": "Checking Codex's finished steps",
        "read_codex_memory": "Reading Codex's AGENTS.md", "read_plan_usage": "Reading the plan meters",
        "search_knowledge_base": "Looking it up in the knowledge base", "read_knowledge_document": "Reading a skill from the knowledge base",
    ]

    /// The website's bubble label and colour for an indicator (AgentAvatar.tsx bubbleStyle).
    static func bubble(_ kind: String) -> (label: String, color: UInt32) {
        switch kind {
        case "approval": return ("Needs approval", 0xFFBD69)
        case "error": return ("Problem", 0xFF6178)
        case "tool": return ("Using", 0x5BF2A5)
        case "complete": return ("Done", 0x5BF2A5)
        case "assignment": return ("Assigned", 0x32D8FF)
        default: return ("Says", 0xA66BFF)
        }
    }
}
