import { describe, expect, it } from "vitest";
import { validateEnvelope, type EventEnvelope, type EventType } from "@aiciv/event-contracts";
import { SEED } from "../../shared-types/src/index";
import { applyEvent, demoScript, DISTRICT_BY_ID, DISTRICTS, initialWorld, route, routeLength, sampleRoute, workstationPosition } from "./index";

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

import graph from "./__fixtures__/graph.json";
import { buildLogistics, packagePosition, terminalPosition } from "./index";

describe("V4 logistics mirror", () => {
  it("matches the backend conveyor graph exactly (services/logistics/graph.py)", () => {
    const g = buildLogistics();
    expect(g.nodes.map((n) => n.id)).toEqual(graph.nodes.map((n) => n.id));
    g.nodes.forEach((n, i) => n.position.forEach((v, k) => expect(v).toBeCloseTo(graph.nodes[i].position[k], 2)));
    expect(g.routes.map((r) => [r.id, r.length])).toEqual(graph.routes.map((r) => [r.id, r.length]));
  });

  it("puts the agent-side terminal next to the belt node", () => {
    const node = buildLogistics().nodes.find((n) => n.id === "data-observatory:dispatch")!;
    const t = terminalPosition("data-observatory", "dispatch");
    expect(Math.hypot(t[0] - node.position[0], t[2] - node.position[2])).toBeLessThan(0.01);
  });

  it("samples packages along their route and reports the end", () => {
    const segs = { a: { from: [0, 1, 0] as [number, number, number], to: [10, 1, 0] as [number, number, number], length: 10 } };
    expect(packagePosition(["a"], segs, 1, 5).position[0]).toBeCloseTo(5);
    expect(packagePosition(["a"], segs, 10, 5).done).toBe(true);
  });
});

describe("V4 package events", () => {
  it("tracks a package from dispatch to arrival and drops the carried hologram", () => {
    let w = initialWorld(SEED.agents);
    const pip = SEED.agents.find((a) => a.key === "research_apps")!.id;
    w = applyEvent(w, ev(1, "research.opportunity_identified", pip, { title: "Steady Focus", opportunity_id: "o1" }), 0).state;
    expect(w.agents[pip].carrying).toBe("Steady Focus");
    w = applyEvent(w, ev(2, "package.dispatched", null, { package_id: "p1", package_type: "research_brief", origin: "data-observatory",
      destination: "nexus-spire", route: ["x"], route_started_at: "2026-10-14T00:00:00Z", agent_id: pip }), 0).state;
    expect(w.agents[pip].carrying).toBeNull();
    expect(w.packages.p1.status).toBe("IN_TRANSIT");
    w = applyEvent(w, ev(3, "package.arrived", null, { package_id: "p1" }), 0).state;
    expect(w.packages.p1.status).toBe("ARRIVED");
    w = applyEvent(w, ev(4, "release.owner_approval_requested", null, { opportunity_id: "o1" }), 0).state;
    expect(w.ownerQueue).toEqual(["o1"]);
    w = applyEvent(w, ev(5, "release.owner_approved", null, { opportunity_id: "o1" }), 0).state;
    expect(w.ownerQueue).toEqual([]);
  });
});

describe("V5 AI Central Bank events", () => {
  it("queues a cost review at the Owner's Tower and clears it when the owner decides", () => {
    let w = initialWorld(SEED.agents);
    w = applyEvent(w, ev(1, "finance.approval_requested", null, { packet_id: "k1", data_mode: "simulated" }), 0).state;
    expect(w.ownerQueue).toEqual(["fin:k1"]);
    w = applyEvent(w, ev(2, "finance.approval_decided", null, { packet_id: "k1", decision: "APPROVE" }), 0).state;
    expect(w.ownerQueue).toEqual([]);
    w = applyEvent(w, ev(3, "finance.approval_requested", null, { packet_id: "k2" }), 0).state;
    w = applyEvent(w, ev(4, "finance.packet_status_changed", null, { packet_id: "k2", from: "OWNER_DECISION", to: "RESEARCH_REQUESTED" }), 0).state;
    expect(w.ownerQueue).toEqual([]);
    expect(w.districtActivity["central-bank"]).toBeGreaterThan(0);
  });

  it("puts every bank floor on a real desk and the bank on the belt network", () => {
    const bank = DISTRICT_BY_ID["central-bank"];
    expect(bank.architecture).toBe("bank");
    expect(bank.workstations.map((w) => w.floor).sort((a, b) => (a ?? 0) - (b ?? 0))).toEqual([0, 2, 3, 4, 5, 6, 7, 8]);
    const ids = buildLogistics().nodes.map((n) => n.id);
    expect(ids).toEqual(expect.arrayContaining(["central-bank:dispatch", "central-bank:receiving", "junction:central-bank"]));
  });
});
