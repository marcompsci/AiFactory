/**
 * Versioned event contract shared by the web client and (via the JSON Schema in
 * ../schema) the Python backend. Bump SCHEMA_VERSION and add a new schema file
 * for breaking changes; never mutate v1 in place.
 */
export const SCHEMA_VERSION = 1 as const;

export const EVENT_TYPES = [
  "mission.created",
  "mission.started",
  "mission.status_changed",
  "mission.completed",
  "mission.failed",
  "mission.cancelled",
  "task.assigned",
  "task.started",
  "task.progress",
  "task.completed",
  "task.failed",
  "agent.message",
  "agent.status_changed",
  "agent.movement_requested",
  "agent.arrived",
  "tool.started",
  "tool.completed",
  "tool.failed",
  "approval.requested",
  "approval.granted",
  "approval.rejected",
  "artifact.created",
  "usage.recorded",
  "system.emergency_stop",
  // V4.0 — management, research, logistics, release (additive)
  "manager.goal_assigned",
  "manager.review_started",
  "manager.review_completed",
  "manager.revision_requested",
  "manager.escalation_created",
  "manager.decision_recorded",
  "research.started",
  "research.finding_created",
  "research.opportunity_identified",
  "research.completed",
  "package.dispatched",
  "package.in_transit",
  "package.arrived",
  "package.rerouted",
  "package.delivery_failed",
  "package.received",
  "release.manager_approved",
  "release.owner_approval_requested",
  "release.owner_approved",
  "release.owner_rejected",
  "release.authorized",
  "release.invalidated",
  "release.executed",
  "opportunity.status_changed",
  "report.submitted",
  "logistics.route_status_changed",
  // V5.0 — AI Central Bank (additive). Payloads carry ids, statuses and labels only: never amounts or accounts.
  "finance.packet_created",
  "finance.packet_status_changed",
  "finance.fee_detected",
  "finance.research_requested",
  "finance.findings_returned",
  "finance.recommendation_ready",
  "finance.gm_reviewed",
  "finance.approval_requested",
  "finance.approval_decided",
  "finance.approval_expired",
  "finance.action_executed",
  "finance.action_refused",
  "finance.connection_status_changed",
  "finance.sync_completed",
  "finance.sync_failed",
  "finance.bill_reminder",
  "finance.tax_estimate_updated",
  "finance.forecast_updated",
  "finance.revenue_reported",
  // V5.1 — free-alternative investigations (research and sandboxed evaluation only)
  "finance.investigation_status_changed",
  "finance.investigation_ready",
  // V5.1 — App Lab (owner-gated improvements to the owner's GitHub repositories) and the money game
  "lab.repository_changed",
  "lab.cycle_status_changed",
  "lab.proposals_ready",
  "lab.proposal_decided",
  "lab.change_published",
  "lab.change_status",
  "game.score_recorded",
  "game.season_changed",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];
export type ExecutionMode = "live" | "simulation";

export interface EventEnvelope<P extends Record<string, unknown> = Record<string, unknown>> {
  event_id: string;
  schema_version: typeof SCHEMA_VERSION;
  organization_id: string;
  mission_id: string | null;
  agent_id: string | null;
  event_type: EventType;
  sequence: number;
  occurred_at: string;
  correlation_id: string;
  payload: P;
  execution_mode?: ExecutionMode;
}

export const AGENT_EXECUTION_STATES = [
  "IDLE",
  "ASSIGNED",
  "PLANNING",
  "EXECUTING",
  "WAITING_FOR_TOOL",
  "WAITING_FOR_AGENT",
  "WAITING_FOR_APPROVAL",
  "REVIEWING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
] as const;
export type AgentExecutionState = (typeof AGENT_EXECUTION_STATES)[number];

/** Visual-only state. Kept separate from execution state on purpose: an agent can be MOVING while EXECUTING is false. */
export type AgentMovementState = "STATIONARY" | "MOVING";

export const MISSION_STATES = [
  "CREATED",
  "VALIDATING",
  "PLANNING",
  "QUEUED",
  "RUNNING",
  "WAITING_FOR_APPROVAL",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
] as const;
export type MissionState = (typeof MISSION_STATES)[number];

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ValidationResult = { ok: true; event: EventEnvelope } | { ok: false; error: string };

/** Hand-rolled validator mirroring event-envelope.v1.json, so the client has no schema-runtime dependency. */
export function validateEnvelope(input: unknown): ValidationResult {
  if (typeof input !== "object" || input === null) return { ok: false, error: "not an object" };
  const e = input as Record<string, unknown>;
  const isUuid = (v: unknown) => typeof v === "string" && UUID_RE.test(v);
  const isUuidOrNull = (v: unknown) => v === null || isUuid(v);
  if (!isUuid(e.event_id)) return { ok: false, error: "event_id" };
  if (e.schema_version !== SCHEMA_VERSION) return { ok: false, error: "schema_version" };
  if (!isUuid(e.organization_id)) return { ok: false, error: "organization_id" };
  if (!isUuidOrNull(e.mission_id)) return { ok: false, error: "mission_id" };
  if (!isUuidOrNull(e.agent_id)) return { ok: false, error: "agent_id" };
  if (!EVENT_TYPES.includes(e.event_type as EventType)) return { ok: false, error: "event_type" };
  if (typeof e.sequence !== "number" || !Number.isInteger(e.sequence) || e.sequence < 1)
    return { ok: false, error: "sequence" };
  if (typeof e.occurred_at !== "string" || Number.isNaN(Date.parse(e.occurred_at)))
    return { ok: false, error: "occurred_at" };
  if (!isUuid(e.correlation_id)) return { ok: false, error: "correlation_id" };
  if (typeof e.payload !== "object" || e.payload === null || Array.isArray(e.payload))
    return { ok: false, error: "payload" };
  if (e.execution_mode !== undefined && e.execution_mode !== "live" && e.execution_mode !== "simulation")
    return { ok: false, error: "execution_mode" };
  return { ok: true, event: e as unknown as EventEnvelope };
}
