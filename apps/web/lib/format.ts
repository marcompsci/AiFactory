import type { EventEnvelope } from "@aiciv/event-contracts";
import type { WorldAgent } from "@aiciv/world-engine";
import { DISTRICT_BY_ID } from "@aiciv/world-engine";

export const STATUS_COLOR: Record<string, string> = {
  CREATED: "#8FA8FF",
  VALIDATING: "#32D8FF",
  PLANNING: "#32D8FF",
  QUEUED: "#8FA8FF",
  RUNNING: "#5BF2A5",
  WAITING_FOR_APPROVAL: "#FFBD69",
  COMPLETED: "#5BF2A5",
  FAILED: "#FF6178",
  CANCELLED: "#FF6178",
  PENDING: "#8FA8FF",
  SKIPPED: "#8FA8FF",
  DENIED: "#FF6178",
};

export function human(s: string | null | undefined): string {
  if (!s) return "";
  const t = s.toLowerCase().replaceAll("_", " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function usd(n: number | null | undefined): string {
  const v = Number(n ?? 0);
  return v < 0.01 && v > 0 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;
}

/** One plain-language line per event for the activity feed. */
export function describe(e: EventEnvelope, agents: Record<string, WorldAgent>): { who: string; text: string; tone: string } {
  const p = e.payload as Record<string, unknown>;
  const who = e.agent_id ? agents[e.agent_id]?.name ?? "Agent" : "System";
  const s = (k: string) => String(p[k] ?? "");
  switch (e.event_type) {
    case "mission.created":
      return { who, text: `Mission created: ${s("title")}`, tone: "#A66BFF" };
    case "mission.started":
      return { who, text: "Mission started", tone: "#5BF2A5" };
    case "mission.status_changed":
      return p.paused !== undefined
        ? { who, text: p.paused ? `Paused: ${s("pause_reason")}` : "Resumed", tone: "#FFBD69" }
        : { who, text: `Mission ${human(s("to"))}`, tone: "#32D8FF" };
    case "mission.completed":
      return { who, text: `Mission completed${p.outcome ? ` (${human(s("outcome"))})` : ""}`, tone: "#5BF2A5" };
    case "mission.failed":
      return { who, text: `Mission failed: ${s("failure_reason")}`, tone: "#FF6178" };
    case "mission.cancelled":
      return { who, text: `Mission cancelled${p.failure_reason ? `: ${s("failure_reason")}` : ""}`, tone: "#FF6178" };
    case "task.assigned":
      return { who, text: `Assigned: ${s("title")}`, tone: "#32D8FF" };
    case "task.started":
      return { who, text: `Started: ${s("title")}`, tone: "#32D8FF" };
    case "task.progress":
      return { who, text: `${s("title")}: ${human(s("status"))}${p.error ? ` (${s("error")})` : ""}`, tone: "#8FA8FF" };
    case "task.completed":
      return { who, text: `Finished: ${s("title")}`, tone: "#5BF2A5" };
    case "task.failed":
      return { who, text: `Failed: ${s("title")} ${s("error")}`, tone: "#FF6178" };
    case "agent.message":
      return { who, text: s("body"), tone: "#EAF2FF" };
    case "agent.status_changed":
      return { who, text: `${human(s("from"))} → ${human(s("to"))}`, tone: "#8FA8FF" };
    case "agent.movement_requested":
      return { who, text: `Heading to ${DISTRICT_BY_ID[s("to_district")]?.name ?? s("to_district")}`, tone: "#8FA8FF" };
    case "agent.arrived":
      return { who, text: `Arrived at ${DISTRICT_BY_ID[s("district")]?.name ?? s("district")}`, tone: "#8FA8FF" };
    case "tool.started":
      return { who, text: `Running ${s("tool")}`, tone: "#5BF2A5" };
    case "tool.completed":
      return { who, text: `${s("tool")} done${p.summary && p.summary !== "ok" ? `: ${s("summary")}` : ""}`, tone: "#5BF2A5" };
    case "tool.failed":
      return { who, text: `${s("tool")} ${p.denied ? "denied" : "failed"}: ${s("error")}`, tone: "#FF6178" };
    case "approval.requested":
      return { who, text: `Asks for approval: ${s("summary")}`, tone: "#FFBD69" };
    case "approval.granted":
      return { who, text: "Approval granted", tone: "#5BF2A5" };
    case "approval.rejected":
      return { who, text: "Approval rejected", tone: "#FF6178" };
    case "artifact.created":
      return { who, text: `Saved ${s("kind").replace("_", " ")}: ${s("title")}`, tone: "#A66BFF" };
    case "usage.recorded":
      return { who, text: `${s("model")}: ${s("input_tokens")} in / ${s("output_tokens")} out, est. ${usd(Number(p.estimated_cost_usd))}`, tone: "#8FA8FF" };
    case "system.emergency_stop":
      return { who, text: p.engaged ? "Emergency stop engaged" : "Emergency stop released", tone: "#FF6178" };
    default:
      return { who, text: e.event_type, tone: "#8FA8FF" };
  }
}
