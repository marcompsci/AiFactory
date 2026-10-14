import type { EventEnvelope, EventType } from "@aiciv/event-contracts";

/**
 * Client-side demo script, used ONLY when the app cannot reach an API (e.g. opened on a phone with no
 * backend). Every envelope is marked execution_mode "simulation" and the UI shows a persistent
 * "Demo — no backend" banner. Nothing here is real agent work.
 */

export interface DemoAgentIds {
  commander: string;
  architect: string;
  developer: string;
  qa: string;
  researcher: string;
}

type Step = [number, EventType, keyof DemoAgentIds | null, Record<string, unknown>];

const uuid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx".replace(/x/g, () => Math.floor(Math.random() * 16).toString(16));

export function demoScript(ids: DemoAgentIds, orgId: string, startSequence: number, approvalId: string): {
  missionId: string;
  beforeApproval: Array<{ delay: number; event: EventEnvelope }>;
  afterApproval: (decision: "granted" | "rejected") => Array<{ delay: number; event: EventEnvelope }>;
} {
  const missionId = uuid();
  let seq = startSequence;
  const mk = (delay: number, type: EventType, who: keyof DemoAgentIds | null, payload: Record<string, unknown>) => ({
    delay,
    event: {
      event_id: uuid(),
      schema_version: 1 as const,
      organization_id: orgId,
      mission_id: missionId,
      agent_id: who ? ids[who] : null,
      event_type: type,
      sequence: ++seq,
      occurred_at: new Date().toISOString(),
      correlation_id: missionId,
      payload,
      execution_mode: "simulation" as const,
    },
  });
  const move = (who: keyof DemoAgentIds, district: string, waypoint: string | null): Step[] => [
    [400, "agent.status_changed", who, { from: "IDLE", to: "ASSIGNED" }],
    [200, "agent.movement_requested", who, { to_district: district, waypoint }],
    [2600, "agent.arrived", who, { district, waypoint }],
    [100, "agent.status_changed", who, { from: "ASSIGNED", to: "EXECUTING" }],
  ];
  const before: Step[] = [
    [0, "mission.created", null, { title: "Fix the failing test (demo)", execution_mode: "simulation" }],
    [600, "agent.message", "commander", { body: "Demo: permissions validated against project policy." }],
    [500, "task.assigned", "architect", { title: "Inspect repository structure", district: "code-forge" }],
    [100, "task.assigned", "qa", { title: "Reproduce the failing test", district: "sentinel-citadel" }],
    [100, "task.assigned", "developer", { title: "Implement a fix", district: "code-forge" }],
    [400, "mission.started", null, {}],
    [100, "task.started", "architect", { title: "Inspect repository structure", district: "code-forge" }],
    ...move("architect", "code-forge", "forge-blueprint"),
    [100, "task.started", "qa", { title: "Reproduce the failing test", district: "sentinel-citadel" }],
    [300, "tool.started", "architect", { tool: "inspect_repository" }],
    [1200, "tool.completed", "architect", { tool: "inspect_repository" }],
    [300, "agent.message", "architect", { body: "One source file; tests in tests/." }],
    [200, "task.completed", "architect", { title: "Inspect repository structure" }],
    [300, "tool.started", "qa", { tool: "run_tests" }],
    [1600, "tool.completed", "qa", { tool: "run_tests" }],
    [200, "agent.message", "qa", { body: "1 failed, 4 passed — test_median_even." }],
    [200, "task.completed", "qa", { title: "Reproduce the failing test" }],
    [200, "task.started", "developer", { title: "Implement a fix", district: "code-forge" }],
    ...move("developer", "code-forge", "forge-anvil"),
    [200, "tool.started", "developer", { tool: "create_worktree" }],
    [800, "tool.completed", "developer", { tool: "create_worktree" }],
    [200, "tool.started", "developer", { tool: "edit_file" }],
    [1400, "tool.completed", "developer", { tool: "edit_file" }],
    [200, "task.completed", "developer", { title: "Implement a fix" }],
    [200, "task.started", "qa", { title: "Rerun the tests", district: "sentinel-citadel" }],
    [200, "tool.started", "qa", { tool: "run_tests" }],
    [1600, "tool.completed", "qa", { tool: "run_tests" }],
    [200, "agent.message", "qa", { body: "5 passed." }],
    [200, "task.completed", "qa", { title: "Rerun the tests" }],
    [200, "task.started", "commander", { title: "Publish the reviewable change", district: "nexus-spire" }],
    ...move("commander", "nexus-spire", "nexus-command"),
    [300, "approval.requested", "commander", { approval_id: approvalId, summary: "Commit the verified fix and publish the patch.", action: "prepare_pull_request" }],
  ];
  const after = (decision: "granted" | "rejected"): Step[] =>
    decision === "granted"
      ? [
          [0, "approval.granted", null, { approval_id: approvalId }],
          [300, "tool.started", "commander", { tool: "prepare_pull_request" }],
          [1200, "tool.completed", "commander", { tool: "prepare_pull_request" }],
          [200, "task.completed", "commander", { title: "Publish the reviewable change" }],
          ...move("researcher", "memory-vault", "vault-archive"),
          [300, "agent.message", "researcher", { body: "Archived in the Memory Vault." }],
          [400, "mission.completed", null, { outcome: "published" }],
        ]
      : [
          [0, "approval.rejected", null, { approval_id: approvalId }],
          [400, "mission.completed", null, { outcome: "not_published" }],
        ];
  const build = (steps: Step[]) => steps.map(([d, t, w, p]) => mk(d, t, w, p));
  return { missionId, beforeApproval: build(before), afterApproval: (d) => build(after(d)) };
}
