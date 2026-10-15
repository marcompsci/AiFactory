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

function sim(p: Record<string, unknown>): string {
  return p.data_mode === "simulated" ? " [simulated data]" : "";
}

/** Money in minor units → "$1,234.56". Null means "no data", never zero. */
export function money(minor: number | null | undefined, currency = "USD"): string {
  if (minor === null || minor === undefined) return "No data";
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(minor / 100);
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
    case "research.started":
      return { who, text: `Querying ${s("source").replace("_", " ")} for "${s("query")}"${p.cached ? " (cached)" : ""}`, tone: "#5BF2A5" };
    case "research.finding_created":
      return { who, text: `Finding: ${s("title")}${p.data_mode === "fixture" ? " [fixture data]" : ""}`, tone: "#5BF2A5" };
    case "research.opportunity_identified":
      return { who, text: `Opportunity: ${s("title")} (score ${Number(p.score).toFixed(2)})`, tone: "#5BF2A5" };
    case "research.completed":
      return { who, text: p.status === "unavailable" ? `Source unavailable: ${s("reason")}` : "Research complete", tone: "#5BF2A5" };
    case "package.dispatched":
    case "package.in_transit":
      return { who, text: `${human(s("package_type"))} on the belt: ${s("origin")} → ${s("destination")}`, tone: "#32D8FF" };
    case "package.rerouted":
      return { who, text: `${human(s("package_type"))} rerouted around a belt problem`, tone: "#FFBD69" };
    case "package.arrived":
      return { who, text: `${human(s("package_type"))} arrived at ${s("destination")}`, tone: "#32D8FF" };
    case "package.received":
      return { who, text: `${human(s("package_type"))} taken in at ${s("district")}`, tone: "#8FA8FF" };
    case "package.delivery_failed":
      return { who, text: `${human(s("package_type"))} could not be delivered: ${s("reason")}`, tone: "#FF6178" };
    case "manager.decision_recorded":
      return { who, text: `${human(s("decision_type"))}: ${s("outcome").replaceAll("_", " ").toLowerCase()}`, tone: "#EAF2FF" };
    case "manager.review_started":
      return { who, text: "Started a review", tone: "#A66BFF" };
    case "manager.review_completed":
      return { who, text: `Review: ${s("outcome").replaceAll("_", " ").toLowerCase()}`, tone: "#A66BFF" };
    case "manager.goal_assigned":
      return { who, text: "Assigned a measurable goal", tone: "#A66BFF" };
    case "manager.revision_requested":
      return { who, text: "Sent work back for revision", tone: "#FFBD69" };
    case "manager.escalation_created":
      return { who, text: `Escalated: ${s("rationale") || s("reason")}`, tone: "#FFBD69" };
    case "release.manager_approved":
      return { who, text: "Release approved by the manager; heading to your tower", tone: "#F4D58D" };
    case "release.owner_approval_requested":
      return { who, text: `Waiting for your decision: ${s("title")}`, tone: "#F4D58D" };
    case "release.owner_approved":
      return { who, text: "You approved the release", tone: "#5BF2A5" };
    case "release.owner_rejected":
      return { who, text: "You rejected the release", tone: "#FF6178" };
    case "release.authorized":
      return { who, text: `Release authorized for bundle ${s("artifact_digest").slice(0, 10)}`, tone: "#5BF2A5" };
    case "release.invalidated":
      return { who, text: `Release approval cancelled: ${s("reason")}`, tone: "#FF6178" };
    case "release.executed":
      return { who, text: `Released to ${s("channel").replace("_", " ")}`, tone: "#5BF2A5" };
    case "opportunity.status_changed":
      return { who, text: `${s("title")}: ${human(s("to"))}`, tone: "#8FA8FF" };
    case "report.submitted":
      return { who, text: `Report (${human(s("kind"))}): ${s("body")}`, tone: "#8FA8FF" };
    case "logistics.route_status_changed":
      return { who, text: `Belt ${s("status") === "DOWN" ? "down" : "restored"}`, tone: s("status") === "DOWN" ? "#FF6178" : "#5BF2A5" };
    case "system.emergency_stop":
      return { who, text: p.engaged ? "Emergency stop engaged" : "Emergency stop released", tone: "#FF6178" };
    // V5 AI Central Bank: the stream never carries amounts; details live in the Bank tab (owners and admins only)
    case "finance.packet_created":
      return { who, text: `New cost review (${human(s("origin"))}, ${human(s("classification")).toLowerCase()})${sim(p)}`, tone: "#F4D58D" };
    case "finance.packet_status_changed":
      return { who, text: `Cost review: ${human(s("to")).toLowerCase()} (${s("label")})${sim(p)}`, tone: "#F4D58D" };
    case "finance.fee_detected":
      return { who, text: `Fee detected; opened a review${sim(p)}`, tone: "#FFBD69" };
    case "finance.research_requested":
    case "finance.findings_returned":
      return { who, text: `Cost research ${e.event_type.endsWith("returned") ? "returned to the bank" : "requested"}${sim(p)}`, tone: "#5BF2A5" };
    case "finance.recommendation_ready":
      return { who, text: `Recommendation ready${p.significant ? ", escalating to the General Manager" : ""}${sim(p)}`, tone: "#F4D58D" };
    case "finance.gm_reviewed":
      return { who, text: `General Manager: ${human(s("decision")).toLowerCase()}`, tone: "#EAF2FF" };
    case "finance.approval_requested":
      return { who, text: `A cost review is waiting for your decision${sim(p)}`, tone: "#F4D58D" };
    case "finance.approval_decided":
      return { who, text: `You decided: ${human(s("decision")).toLowerCase()}`, tone: s("decision") === "APPROVE" ? "#5BF2A5" : "#FFBD69" };
    case "finance.approval_expired":
      return { who, text: "A financial approval expired unused", tone: "#FFBD69" };
    case "finance.action_executed":
      return { who, text: `Owner-approved ${human(s("action_type")).toLowerCase()} carried out (${s("label")})`, tone: "#5BF2A5" };
    case "finance.action_refused":
      return { who, text: `Refused: ${human(s("reason_code") || s("action_type")).toLowerCase()}`, tone: "#FF6178" };
    case "finance.connection_status_changed":
      return { who, text: `${human(s("provider") || "Connection")} ${human(s("status")).toLowerCase()}`, tone: "#8FA8FF" };
    case "finance.sync_completed":
      return { who, text: `Synced ${s("provider")}: ${s("inserted")} new, ${s("duplicates")} already known${sim(p)}`, tone: "#8FA8FF" };
    case "finance.sync_failed":
      return { who, text: `Sync failed (${s("reason_code")})`, tone: "#FF6178" };
    case "finance.bill_reminder":
      return { who, text: `${s("label") || "Bill due"}: reminder sent to your tower${sim(p)}`, tone: "#FFBD69" };
    case "finance.investigation_status_changed":
      return { who, text: `Free-alternative investigation: ${human(s("to")).toLowerCase()}${p.label ? ` (${s("label")})` : ""}${sim(p)}`, tone: "#3DFFB8" };
    case "finance.investigation_ready":
      return { who, text: `Investigation complete; the recommendation is at your tower${sim(p)}`, tone: "#3DFFB8" };
    case "lab.repository_changed":
      return { who, text: `App Lab: ${s("repo")} ${s("label")}`, tone: "#32D8FF" };
    case "lab.cycle_status_changed":
      return { who, text: `App Lab cycle: ${human(s("to")).toLowerCase()}${p.label ? ` (${s("label")})` : ""}${sim(p)}`, tone: "#32D8FF" };
    case "lab.proposals_ready":
      return { who, text: `${s("label")}: the General Manager's briefing is at your tower${sim(p)}`, tone: "#FFD36B" };
    case "lab.proposal_decided":
      return { who, text: `Owner ${s("decision") === "APPROVE" ? "approved" : s("decision") === "REJECT" ? "rejected" : "deferred"} "${s("title")}"`, tone: "#FFD36B" };
    case "lab.change_published":
      return { who, text: `Published "${s("title")}" as ${s("kind") === "pr" ? "draft pull request" : "Claude Code issue"} #${s("number")}`, tone: "#3DFFB8" };
    case "lab.change_status":
      return { who, text: `GitHub #${s("number")} is ${p.merged ? "merged" : s("state")}`, tone: "#3DFFB8" };
    case "game.score_recorded":
      return { who, text: `scored in the money game (${human(s("kind")).toLowerCase()}${p.verified ? ", verified" : ", simulated"})`, tone: "#FFD36B" };
    case "factory.synced":
      return { who, text: s("kind") === "claude_code" ? `checked Claude Code: ${p.sessions ?? 0} session(s), ${p.completed_tasks ?? 0} finished task(s)` : `checked GitHub: ${p.pulls ?? 0} pull request(s), ${p.runs ?? 0} Actions run(s)`, tone: "#FF8A5C" };
    case "game.season_changed":
      return { who, text: `New money-game season ${s("season")}`, tone: "#FFD36B" };
    case "finance.tax_estimate_updated":
      return { who, text: `Tax estimate updated for ${s("tax_year")} (an estimate)${sim(p)}`, tone: "#A66BFF" };
    default:
      return { who, text: e.event_type, tone: "#8FA8FF" };
  }
}

export const PACKAGE_COLORS: Record<string, string> = {
  research_brief: "#5BF2A5",
  product_proposal: "#A66BFF",
  design_spec: "#FF6178",
  code_artifact: "#32D8FF",
  test_report: "#FFBD69",
  revision_request: "#FF6178",
  approval_request: "#F4D58D",
  release_package: "#F4D58D",
  // V5 AI Central Bank
  revenue_report: "#5BF2A5",
  expense_alert: "#FFBD69",
  bill_reminder: "#FF9F43",
  fee_research_request: "#F4D58D",
  savings_recommendation: "#7CFFCB",
  purchase_request: "#E7C66A",
  payment_proposal: "#FF8FA3",
  tax_review_package: "#B794FF",
  financial_forecast: "#9AD1FF",
  owner_approval_request: "#FFD86B",
  savings_investigation: "#3DFFB8",
  // App Lab
  design_insights: "#7CF7FF",
  lab_proposal: "#FFD36B",
};
