import type { AgentExecutionState, EventEnvelope, ExecutionMode } from "@aiciv/event-contracts";
import { DISTRICT_BY_ID, homePosition, workstationPosition, type Vec3 } from "./districts";
import { route } from "./navigation";

/**
 * Deterministic event → world interpreter. A pure reducer: (state, envelope) → state.
 * Animations are driven only by backend events; nothing here decides whether work succeeded.
 */

export type Indicator =
  | { kind: "assignment"; text: string; at: number }
  | { kind: "message"; text: string; at: number }
  | { kind: "tool"; text: string; at: number }
  | { kind: "approval"; text: string; at: number }
  | { kind: "error"; text: string; at: number }
  | { kind: "complete"; text: string; at: number };

export interface WorldAgent {
  id: string;
  key: string;
  name: string;
  role: string;
  color: string;
  shape: string;
  height: number;
  homeDistrict: string;
  district: string;
  waypoint: string | null;
  /** Visual-only. Never confuse with execState. */
  movement: "STATIONARY" | "MOVING";
  execState: AgentExecutionState;
  /** Polyline the avatar follows; startedAt drives the animation clock. */
  route: Vec3[];
  routeStartedAt: number;
  position: Vec3;
  indicator: Indicator | null;
  currentTask: string | null;
  /** Title of a holographic package the agent is carrying to a dispatch terminal (V4). */
  carrying: string | null;
}

export type PackageStatus = "QUEUED" | "IN_TRANSIT" | "ARRIVED" | "RECEIVED" | "DELIVERY_FAILED" | "CANCELLED";

export interface WorldPackage {
  id: string;
  type: string;
  status: PackageStatus;
  origin: string;
  destination: string;
  route: string[];
  routeStartedAt: string | null; // server time (ISO)
  eta: string | null;
  opportunityId: string | null;
  priority: number;
  updatedAt: number;
}

export interface WorldState {
  lastSequence: number;
  agents: Record<string, WorldAgent>;
  activeWorkstations: Record<string, string>; // workstation id → tool name
  districtActivity: Record<string, number>; // 0..1, decays in the renderer
  celebrate: { district: string; at: number } | null;
  pendingApprovals: string[];
  mode: ExecutionMode;
  packages: Record<string, WorldPackage>;
  /** Opportunities whose release package is waiting at the Owner's Tower. */
  ownerQueue: string[];
  routeStatus: Record<string, "UP" | "DOWN">;
}

export interface AgentSeed {
  id: string;
  key: string;
  name: string;
  role: string;
  home_district: string;
  avatar: { shape: string; color: string; height: number };
  district?: string;
  waypoint?: string | null;
  execution_state?: AgentExecutionState;
}

export function initialWorld(agents: AgentSeed[], lastSequence = 0, mode: ExecutionMode = "live"): WorldState {
  const slots: Record<string, number> = {};
  const map: Record<string, WorldAgent> = {};
  for (const a of agents) {
    const district = a.district ?? a.home_district;
    const slot = (slots[district] = (slots[district] ?? -1) + 1);
    const pos = a.waypoint ? workstationPosition(district, a.waypoint) : homePosition(district, slot);
    map[a.id] = {
      id: a.id,
      key: a.key,
      name: a.name,
      role: a.role,
      color: a.avatar.color,
      shape: a.avatar.shape,
      height: a.avatar.height,
      homeDistrict: a.home_district,
      district,
      waypoint: a.waypoint ?? null,
      movement: "STATIONARY",
      execState: a.execution_state ?? "IDLE",
      route: [pos],
      routeStartedAt: 0,
      position: pos,
      indicator: null,
      currentTask: null,
      carrying: null,
    };
  }
  return { lastSequence, agents: map, activeWorkstations: {}, districtActivity: {}, celebrate: null, pendingApprovals: [], mode,
    packages: {}, ownerQueue: [], routeStatus: {} };
}

function homeSlot(state: WorldState, agent: WorldAgent): number {
  return Object.values(state.agents)
    .filter((a) => a.homeDistrict === agent.homeDistrict)
    .sort((a, b) => a.id.localeCompare(b.id))
    .findIndex((a) => a.id === agent.id);
}

function bump(state: WorldState, district: string, amount: number): Record<string, number> {
  if (!DISTRICT_BY_ID[district]) return state.districtActivity;
  return { ...state.districtActivity, [district]: Math.min(1, (state.districtActivity[district] ?? 0) + amount) };
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

export type ApplyResult = { state: WorldState; status: "applied" | "duplicate" | "gap" };

/**
 * Apply one envelope. Events must arrive in sequence order: a duplicate (≤ lastSequence) is ignored,
 * and a gap (> lastSequence + 1) is refused so the caller can replay the missing range first.
 * `now` is the animation clock (ms) supplied by the caller, keeping this function pure.
 */
export function applyEvent(state: WorldState, e: EventEnvelope, now: number): ApplyResult {
  if (e.sequence <= state.lastSequence) return { state, status: "duplicate" };
  if (state.lastSequence !== 0 && e.sequence > state.lastSequence + 1) return { state, status: "gap" };
  const next: WorldState = { ...state, lastSequence: e.sequence, mode: e.execution_mode ?? state.mode };
  const p = e.payload as Record<string, unknown>;
  const agent = e.agent_id ? state.agents[e.agent_id] : undefined;
  const setAgent = (patch: Partial<WorldAgent>) => {
    if (!agent) return;
    next.agents = { ...next.agents, [agent.id]: { ...next.agents[agent.id], ...patch } };
  };

  switch (e.event_type) {
    case "task.assigned":
      setAgent({ indicator: { kind: "assignment", text: str(p.title), at: now } });
      break;
    case "task.started":
      setAgent({ currentTask: str(p.title) || null });
      next.districtActivity = bump(next, str(p.district), 0.35);
      break;
    case "agent.movement_requested": {
      if (!agent) break;
      const to = str(p.to_district);
      const waypoint = (p.waypoint as string | null) ?? null;
      const target = waypoint ? workstationPosition(to, waypoint) : homePosition(to, homeSlot(state, agent));
      setAgent({ movement: "MOVING", route: route(agent.position, agent.district, to, target), routeStartedAt: now, district: to, waypoint });
      break;
    }
    case "agent.arrived": {
      if (!agent) break;
      const d = str(p.district);
      const waypoint = (p.waypoint as string | null) ?? null;
      const pos = waypoint ? workstationPosition(d, waypoint) : homePosition(d, homeSlot(state, agent));
      // The route stays so the avatar can finish walking smoothly; the renderer snaps if it is far behind.
      setAgent({ movement: "STATIONARY", district: d, waypoint, position: pos });
      break;
    }
    case "agent.status_changed":
      setAgent({ execState: str(p.to) as AgentExecutionState });
      break;
    case "agent.message":
      setAgent({ indicator: { kind: "message", text: str(p.body), at: now } });
      break;
    case "tool.started":
      if (agent?.waypoint) next.activeWorkstations = { ...state.activeWorkstations, [agent.waypoint]: str(p.tool) };
      setAgent({ indicator: { kind: "tool", text: str(p.tool), at: now } });
      if (agent) next.districtActivity = bump(next, agent.district, 0.2);
      break;
    case "tool.completed":
    case "tool.failed": {
      if (agent?.waypoint) {
        const { [agent.waypoint]: _removed, ...rest } = state.activeWorkstations;
        next.activeWorkstations = rest;
      }
      if (e.event_type === "tool.failed") setAgent({ indicator: { kind: "error", text: `${str(p.tool)} failed`, at: now } });
      break;
    }
    case "approval.requested":
      next.pendingApprovals = [...state.pendingApprovals, str(p.approval_id)];
      setAgent({ indicator: { kind: "approval", text: str(p.summary), at: now } });
      break;
    case "approval.granted":
    case "approval.rejected":
      next.pendingApprovals = state.pendingApprovals.filter((id) => id !== str(p.approval_id));
      break;
    case "task.completed":
      setAgent({ indicator: { kind: "complete", text: str(p.title), at: now }, currentTask: null });
      break;
    case "task.failed":
      setAgent({ indicator: { kind: "error", text: str(p.error) || str(p.title), at: now }, currentTask: null });
      break;
    case "mission.completed":
      next.celebrate = { district: "nexus-spire", at: now };
      next.districtActivity = Object.fromEntries(Object.keys(DISTRICT_BY_ID).map((k) => [k, 1]));
      break;
    case "mission.failed":
    case "mission.cancelled":
      next.activeWorkstations = {};
      break;
    // ---------------------------------------------------------------- V4: research, logistics, release
    case "research.opportunity_identified":
      setAgent({ carrying: str(p.title) || "Research brief", indicator: { kind: "complete", text: `Found: ${str(p.title)}`, at: now } });
      break;
    case "package.dispatched":
    case "package.in_transit":
    case "package.rerouted": {
      const id = str(p.package_id);
      const prev = state.packages[id];
      next.packages = {
        ...state.packages,
        [id]: {
          id,
          type: str(p.package_type) || prev?.type || "package",
          status: "IN_TRANSIT",
          origin: str(p.origin) || prev?.origin || "",
          destination: str(p.destination) || prev?.destination || "",
          route: (p.route as string[]) ?? prev?.route ?? [],
          routeStartedAt: (p.route_started_at as string) ?? prev?.routeStartedAt ?? null,
          eta: (p.eta as string) ?? prev?.eta ?? null,
          opportunityId: (p.opportunity_id as string) ?? prev?.opportunityId ?? null,
          priority: Number(p.priority ?? prev?.priority ?? 5),
          updatedAt: now,
        },
      };
      if (e.event_type === "package.dispatched" && p.agent_id) {
        const carrier = state.agents[str(p.agent_id)];
        if (carrier) next.agents = { ...next.agents, [carrier.id]: { ...next.agents[carrier.id], carrying: null } };
      }
      if (prev?.origin || p.origin) next.districtActivity = bump(next, str(p.origin) || prev!.origin, 0.25);
      break;
    }
    case "package.arrived":
    case "package.received":
    case "package.delivery_failed": {
      const id = str(p.package_id);
      const prev = state.packages[id];
      const status: PackageStatus = e.event_type === "package.arrived" ? "ARRIVED" : e.event_type === "package.received" ? "RECEIVED" : "DELIVERY_FAILED";
      next.packages = {
        ...state.packages,
        [id]: { ...(prev ?? { id, type: str(p.package_type), origin: str(p.origin), destination: str(p.destination), route: [], routeStartedAt: null,
          eta: null, opportunityId: (p.opportunity_id as string) ?? null, priority: 5 }), status, updatedAt: now } as WorldPackage,
      };
      if (status === "ARRIVED") next.districtActivity = bump(next, str(p.destination) || prev?.destination || "", 0.4);
      break;
    }
    case "logistics.route_status_changed":
      next.routeStatus = { ...state.routeStatus, [str(p.route_id)]: str(p.status) === "DOWN" ? "DOWN" : "UP" };
      break;
    case "release.owner_approval_requested":
      if (!state.ownerQueue.includes(str(p.opportunity_id))) next.ownerQueue = [...state.ownerQueue, str(p.opportunity_id)];
      next.districtActivity = bump(next, "owners-tower", 1);
      break;
    case "release.owner_approved":
    case "release.owner_rejected":
      next.ownerQueue = state.ownerQueue.filter((x) => x !== str(p.opportunity_id));
      break;
    case "opportunity.status_changed":
      if (str(p.from) === "OWNER_APPROVAL") next.ownerQueue = state.ownerQueue.filter((x) => x !== str(p.opportunity_id));
      break;
    case "release.executed":
      next.celebrate = { district: "owners-tower", at: now };
      break;
    default:
      break;
  }
  return { state: next, status: "applied" };
}

/** Rebuild agent positions from an authoritative snapshot (used on connect / reconnect). */
export interface PackageSeed {
  id: string;
  package_type: string;
  status: PackageStatus;
  origin_district: string;
  destination_district: string;
  route: string[];
  route_started_at: string | null;
  eta: string | null;
  opportunity_id: string | null;
  priority: number;
}

export function hydrate(agents: AgentSeed[], sequence: number, mode: ExecutionMode, pendingApprovals: string[] = [],
  packages: PackageSeed[] = [], ownerQueue: string[] = [], routeStatus: Record<string, "UP" | "DOWN"> = {}): WorldState {
  const w = initialWorld(agents, sequence, mode);
  w.pendingApprovals = pendingApprovals;
  w.packages = Object.fromEntries(packages.map((p) => [p.id, {
    id: p.id, type: p.package_type, status: p.status, origin: p.origin_district, destination: p.destination_district, route: p.route ?? [],
    routeStartedAt: p.route_started_at, eta: p.eta, opportunityId: p.opportunity_id, priority: p.priority, updatedAt: 0,
  }]));
  w.ownerQueue = ownerQueue;
  w.routeStatus = routeStatus;
  return w;
}
