import { describe, expect, it } from "vitest";
import { validateEnvelope, type EventEnvelope, type EventType } from "@aiciv/event-contracts";
import { SEED } from "../../shared-types/src/index";
import { applyEvent, demoScript, DISTRICTS, initialWorld, route, routeLength, sampleRoute, workstationPosition } from "./index";

const ORG = SEED.organization_id;
const ids = Object.fromEntries(SEED.agents.map((a) => [a.key, a.id])) as Record<string, string>;
let n = 0;
const uuid = () => `00000000-0000-4000-8000-${String(++n).padStart(12, "0")}`;

function ev(sequence: number, event_type: EventType, agent: string | null, payload: Record<string, unknown> = {}): EventEnvelope {
  return { event_id: uuid(), schema_version: 1, organization_id: ORG, mission_id: null, agent_id: agent, event_type, sequence,
    occurred_at: new Date().toISOString(), correlation_id: uuid(), payload, execution_mode: "live" };
}

describe("event contract", () => {
  it("accepts a valid envelope and rejects malformed ones", () => {
    expect(validateEnvelope(ev(1, "task.started", ids.qa)).ok).toBe(true);
    expect(validateEnvelope({ ...ev(1, "task.started", null), sequence: 0 }).ok).toBe(false);
    expect(validateEnvelope({ ...ev(1, "task.started", null), event_type: "task.hacked" }).ok).toBe(false);
    expect(validateEnvelope({ ...ev(1, "task.started", null), schema_version: 2 }).ok).toBe(false);
    expect(validateEnvelope({ ...ev(1, "task.started", null), agent_id: "nope" }).ok).toBe(false);
    expect(validateEnvelope(null).ok).toBe(false);
  });
});

describe("interpreter", () => {
  const world = () => initialWorld(SEED.agents);

  it("applies in order, ignores duplicates and refuses gaps", () => {
    let w = world();
    const a = applyEvent(w, ev(1, "agent.status_changed", ids.qa, { from: "IDLE", to: "ASSIGNED" }), 0);
    expect(a.status).toBe("applied");
    w = a.state;
    expect(w.agents[ids.qa].execState).toBe("ASSIGNED");
    expect(applyEvent(w, ev(1, "agent.status_changed", ids.qa, { to: "FAILED" }), 0).status).toBe("duplicate");
    expect(applyEvent(w, ev(3, "agent.status_changed", ids.qa, { to: "FAILED" }), 0).status).toBe("gap");
    expect(w.agents[ids.qa].execState).toBe("ASSIGNED");
  });

  it("keeps movement and execution state separate", () => {
    let w = world().agents[ids.developer] ? world() : world();
    w = applyEvent(w, ev(1, "agent.movement_requested", ids.developer, { to_district: "sentinel-citadel", waypoint: "citadel-testbay" }), 100).state;
    const dev = w.agents[ids.developer];
    expect(dev.movement).toBe("MOVING");
    expect(dev.execState).toBe("IDLE");
    expect(dev.route.length).toBeGreaterThan(2);
    expect(dev.route[dev.route.length - 1]).toEqual(workstationPosition("sentinel-citadel", "citadel-testbay"));
    w = applyEvent(w, ev(2, "agent.arrived", ids.developer, { district: "sentinel-citadel", waypoint: "citadel-testbay" }), 200).state;
    expect(w.agents[ids.developer].movement).toBe("STATIONARY");
  });

  it("lights workstations only while a tool runs", () => {
    let w = world();
    w = applyEvent(w, ev(1, "agent.arrived", ids.qa, { district: "sentinel-citadel", waypoint: "citadel-testbay" }), 0).state;
    w = applyEvent(w, ev(2, "tool.started", ids.qa, { tool: "run_tests" }), 0).state;
    expect(w.activeWorkstations["citadel-testbay"]).toBe("run_tests");
    w = applyEvent(w, ev(3, "tool.completed", ids.qa, { tool: "run_tests" }), 0).state;
    expect(w.activeWorkstations["citadel-testbay"]).toBeUndefined();
  });

  it("tracks approvals and never marks success without a backend event", () => {
    let w = world();
    w = applyEvent(w, ev(1, "approval.requested", ids.commander, { approval_id: "a1", summary: "publish" }), 0).state;
    expect(w.pendingApprovals).toEqual(["a1"]);
    expect(w.agents[ids.commander].indicator?.kind).toBe("approval");
    expect(w.celebrate).toBeNull();
    w = applyEvent(w, ev(2, "approval.granted", null, { approval_id: "a1" }), 0).state;
    expect(w.pendingApprovals).toEqual([]);
    w = applyEvent(w, ev(3, "mission.completed", null, {}), 5).state;
    expect(w.celebrate).toEqual({ district: "nexus-spire", at: 5 });
  });

  it("is deterministic", () => {
    const events = [ev(1, "agent.movement_requested", ids.architect, { to_district: "memory-vault", waypoint: "vault-archive" })];
    const a = events.reduce((w, e) => applyEvent(w, e, 10).state, world());
    const b = events.reduce((w, e) => applyEvent(w, e, 10).state, world());
    expect(a).toEqual(b);
  });
});

describe("navigation", () => {
  it("routes between every pair of districts and ends at the target", () => {
    for (const from of DISTRICTS)
      for (const to of DISTRICTS) {
        const target = workstationPosition(to.id, to.workstations[0].id);
        const r = route([from.position[0], 0, from.position[2]], from.id, to.id, target);
        expect(r[r.length - 1]).toEqual(target);
        expect(routeLength(r)).toBeLessThan(250);
      }
  });

  it("samples along the polyline and reports completion", () => {
    const pts: [number, number, number][] = [[0, 0, 0], [10, 0, 0], [10, 0, 10]];
    expect(sampleRoute(pts, 5).position).toEqual([5, 0, 0]);
    expect(sampleRoute(pts, 15).position).toEqual([10, 0, 5]);
    expect(sampleRoute(pts, 999).done).toBe(true);
  });
});

describe("demo script", () => {
  it("emits valid, gapless, simulation-labeled envelopes", () => {
    const s = demoScript({ commander: ids.commander, architect: ids.architect, developer: ids.developer, qa: ids.qa, researcher: ids.researcher }, ORG, 0, uuid());
    const all = [...s.beforeApproval, ...s.afterApproval("granted")].map((x) => x.event);
    all.forEach((e, i) => {
      expect(validateEnvelope(e).ok).toBe(true);
      expect(e.sequence).toBe(i + 1);
      expect(e.execution_mode).toBe("simulation");
    });
    let w = initialWorld(SEED.agents);
    for (const e of all) {
      const r = applyEvent(w, e, 0);
      expect(r.status).toBe("applied");
      w = r.state;
    }
    expect(w.pendingApprovals).toEqual([]);
  });
});
