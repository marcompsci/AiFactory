/**
 * Game rules with no drawing: movement and collision, pathfinding for tap-to-move, proximity, where an NPC stands and how
 * it animates, and where a package sits on the conveyor. Animation always follows backend state; it never decides it.
 */
import type { WorldAgent, WorldPackage } from "@aiciv/world-engine";
import { DEPOT, isSolid, tileIndex, type Dir, type GameMap } from "./maps";

export interface Vec { x: number; y: number }

export const PLAYER_RADIUS = 0.3;
export const NPC_RADIUS = 0.42;
export const WALK_SPEED = 4.2; // tiles per second

/** Moves a round body by (dx, dy), sliding along walls and around other bodies. */
export function moveBody(m: GameMap, p: Vec, dx: number, dy: number, blockers: Vec[] = [], r = PLAYER_RADIUS): Vec {
  const free = (x: number, y: number) => {
    for (const [ox, oy] of [[-r, -r * 0.4], [r, -r * 0.4], [-r, r], [r, r]] as const) {
      if (isSolid(m, Math.floor(x + ox), Math.floor(y + oy))) return false;
    }
    return blockers.every((b) => (b.x - x) ** 2 + (b.y - y) ** 2 >= (NPC_RADIUS + r) ** 2 ||
      // already overlapping (spawned on top): allow moving apart
      (b.x - x) ** 2 + (b.y - y) ** 2 > (b.x - p.x) ** 2 + (b.y - p.y) ** 2);
  };
  let { x, y } = p;
  if (dx && free(x + dx, y)) x += dx;
  if (dy && free(x, y + dy)) y += dy;
  return { x, y };
}

export function facingFor(dx: number, dy: number, prev: Dir): Dir {
  if (Math.abs(dx) < 1e-4 && Math.abs(dy) < 1e-4) return prev;
  return Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "right" : "left") : dy > 0 ? "down" : "up";
}

/** A* over walkable tiles (4-way). Returns tile centres from the step after `from` to `to`, or [] if unreachable. */
export function findPath(m: GameMap, from: Vec, to: Vec, blocked: Set<number> = new Set(), limit = 4000): Vec[] {
  const sx = Math.floor(from.x), sy = Math.floor(from.y);
  let tx = Math.floor(to.x), ty = Math.floor(to.y);
  if (isSolid(m, tx, ty) || blocked.has(tileIndex(m, tx, ty))) {
    // tapped a wall or an NPC: walk to the nearest open neighbour instead
    let n: Vec | undefined;
    for (let r = 1; r <= 4 && !n; r++) {
      const ring: Vec[] = [];
      for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (Math.max(Math.abs(dx), Math.abs(dy)) === r) ring.push({ x: tx + dx, y: ty + dy });
      n = ring.filter((c) => !isSolid(m, c.x, c.y) && !blocked.has(tileIndex(m, c.x, c.y)))
        .sort((a, b) => Math.hypot(a.x - tx, a.y - ty) - Math.hypot(b.x - tx, b.y - ty) || Math.hypot(a.x - sx, a.y - sy) - Math.hypot(b.x - sx, b.y - sy))[0];
    }
    if (!n) return [];
    tx = n.x; ty = n.y;
  }
  if (sx === tx && sy === ty) return [{ x: tx + 0.5, y: ty + 0.5 }];
  const key = (x: number, y: number) => y * m.w + x;
  const g = new Map<number, number>([[key(sx, sy), 0]]);
  const came = new Map<number, number>();
  const open: { k: number; f: number }[] = [{ k: key(sx, sy), f: 0 }];
  const closed = new Set<number>();
  let steps = 0;
  while (open.length && steps++ < limit) {
    open.sort((a, b) => a.f - b.f);
    const { k } = open.shift()!;
    if (closed.has(k)) continue;
    closed.add(k);
    const cx = k % m.w, cy = Math.floor(k / m.w);
    if (cx === tx && cy === ty) {
      const out: Vec[] = [];
      let c: number | undefined = k;
      while (c !== undefined && c !== key(sx, sy)) {
        out.push({ x: (c % m.w) + 0.5, y: Math.floor(c / m.w) + 0.5 });
        c = came.get(c);
      }
      return out.reverse();
    }
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
      const nx = cx + dx, ny = cy + dy, nk = key(nx, ny);
      if (isSolid(m, nx, ny) || closed.has(nk) || (blocked.has(nk) && !(nx === tx && ny === ty))) continue;
      const ng = (g.get(k) ?? 0) + 1;
      if (ng < (g.get(nk) ?? Infinity)) {
        g.set(nk, ng);
        came.set(nk, k);
        open.push({ k: nk, f: ng + Math.abs(nx - tx) + Math.abs(ny - ty) });
      }
    }
  }
  return [];
}

export function nearest<T extends Vec>(p: Vec, items: T[], max: number): T | null {
  let best: T | null = null, bd = max;
  for (const it of items) {
    const d = Math.hypot(it.x - p.x, it.y - p.y);
    if (d <= bd) { best = it; bd = d; }
  }
  return best;
}

// ---------------------------------------------------------------- NPC animation from backend state
export type Anim = "IDLE" | "WALKING" | "TALKING" | "WORKING" | "RESEARCHING" | "CODING" | "TESTING" | "WAITING" | "DELIVERING" | "CELEBRATING";

const RESEARCH_KEYS = new Set(["researcher", "research_apps", "research_marketplaces"]);
const CODE_KEYS = new Set(["developer", "architect"]);

export function animFor(a: Pick<WorldAgent, "execState" | "movement" | "carrying" | "key">, talking = false): Anim {
  if (talking) return "TALKING";
  if (a.movement === "MOVING") return a.carrying ? "DELIVERING" : "WALKING";
  switch (a.execState) {
    case "EXECUTING":
    case "WAITING_FOR_TOOL":
      return RESEARCH_KEYS.has(a.key) ? "RESEARCHING" : CODE_KEYS.has(a.key) ? "CODING" : a.key === "qa" ? "TESTING" : "WORKING";
    case "ASSIGNED":
    case "PLANNING":
      return "WORKING";
    case "REVIEWING":
      return a.key === "qa" ? "TESTING" : "WORKING";
    case "WAITING_FOR_AGENT":
    case "WAITING_FOR_APPROVAL":
      return "WAITING";
    case "COMPLETED":
      return "CELEBRATING";
    default:
      return "IDLE";
  }
}

/** Short label for the status bubble: the backend's execution state, in words. */
export function statusLabel(a: Pick<WorldAgent, "execState" | "movement" | "carrying">): string {
  if (a.movement === "MOVING") return a.carrying ? `Delivering ${a.carrying}` : "Walking";
  return {
    IDLE: "Idle", ASSIGNED: "Assigned", PLANNING: "Planning", EXECUTING: "Working", WAITING_FOR_TOOL: "Waiting on a tool",
    WAITING_FOR_AGENT: "Waiting on a teammate", WAITING_FOR_APPROVAL: "Needs your approval", REVIEWING: "Reviewing",
    COMPLETED: "Finished", FAILED: "Task failed", CANCELLED: "Cancelled",
  }[a.execState] ?? a.execState;
}

// ---------------------------------------------------------------- where NPCs are
export interface Placed { agent: WorldAgent; x: number; y: number; facing: Dir; anim: Anim; outdoors: boolean }

/** NPCs inside a building stand at its workstations. Agents on the move appear on the road, walking between buildings. */
export function placeAgents(m: GameMap, agents: WorldAgent[], now: number, talkingTo: string | null, town: GameMap): Placed[] {
  const out: Placed[] = [];
  if (m.id === "town") {
    for (const a of agents) {
      if (a.movement !== "MOVING") continue;
      const from = town.docks[a.homeDistrict] ?? town.docks[DEPOT.id];
      const to = town.docks[a.district] ?? town.docks[DEPOT.id];
      if (!from || !to || (from.x === to.x && from.y === to.y)) continue;
      const path = roadPath(town, from, to);
      if (!path.length) continue;
      const t = ((now / 1000) * 2.5) % path.length; // visual only; the backend owns where the agent really is
      const i = Math.floor(t), f = t - i, p0 = path[i], p1 = path[Math.min(path.length - 1, i + 1)];
      out.push({ agent: a, x: p0.x + (p1.x - p0.x) * f, y: p0.y + (p1.y - p0.y) * f, facing: facingFor(p1.x - p0.x, p1.y - p0.y, "down"),
        anim: animFor(a, talkingTo === a.id), outdoors: true });
    }
    return out;
  }
  const here = agents.filter((a) => a.district === m.id && a.movement !== "MOVING")
    .sort((a, b) => Number(b.homeDistrict === m.id) - Number(a.homeDistrict === m.id) || a.id.localeCompare(b.id));
  const spare = standingSpots(m);
  here.forEach((a, i) => {
    // more agents than desks: free floor tiles, never inside a wall or furniture
    const w = m.workstations[i] ?? spare[i - m.workstations.length] ?? { x: 8, y: 10, facing: "down" as Dir };
    const anim = animFor(a, talkingTo === a.id);
    // at work: seated at the desk, back to you; otherwise standing beside it, facing the room
    const seated = anim === "WORKING" || anim === "CODING" || anim === "RESEARCHING" || anim === "TESTING";
    const facing: Dir = seated ? w.facing : "down";
    out.push({ agent: a, x: seated ? w.x : w.x + 1, y: seated ? w.y + 0.4 : w.y + 0.6, facing, anim, outdoors: false });
  });
  return out;
}

const roadCache = new Map<string, Vec[]>();
function roadPath(town: GameMap, from: Vec, to: Vec): Vec[] {
  const k = `${from.x},${from.y}>${to.x},${to.y}`;
  if (!roadCache.has(k)) roadCache.set(k, findPath(town, { x: from.x + 0.5, y: from.y + 0.5 }, { x: to.x + 0.5, y: to.y + 0.5 }));
  return roadCache.get(k)!;
}

// ---------------------------------------------------------------- packages on the conveyor
/** Breadth-first route along conveyor tiles between two docks. */
export function beltRoute(m: GameMap, from: Vec, to: Vec): Vec[] {
  const start = tileIndex(m, from.x, from.y), goal = tileIndex(m, to.x, to.y);
  if (!m.belt.has(start) || !m.belt.has(goal)) return [];
  const prev = new Map<number, number>([[start, -1]]);
  const q = [start];
  while (q.length) {
    const c = q.shift()!;
    if (c === goal) break;
    const cx = c % m.w, cy = Math.floor(c / m.w);
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
      const n = tileIndex(m, cx + dx, cy + dy);
      if (cx + dx < 0 || cx + dx >= m.w || !m.belt.has(n) || prev.has(n)) continue;
      prev.set(n, c);
      q.push(n);
    }
  }
  if (!prev.has(goal)) return [];
  const out: Vec[] = [];
  for (let c = goal; c !== -1; c = prev.get(c)!) out.push({ x: (c % m.w) + 0.5, y: Math.floor(c / m.w) + 0.5 });
  return out.reverse();
}

export interface PackagePoint { id: string; x: number; y: number; progress: number; status: WorldPackage["status"]; pkg: WorldPackage }

const beltCache = new Map<string, Vec[]>();
export function dockFor(m: GameMap, district: string): Vec {
  return m.docks[district] ?? m.docks[DEPOT.id];
}

/**
 * Where a package is drawn: queued at its origin dock, moving along the belt by its server-side route clock while in
 * transit, waiting at the destination dock once it has arrived. Received and cancelled packages aren't drawn.
 */
export function packagePoint(m: GameMap, p: WorldPackage, serverNow: number): PackagePoint | null {
  if (p.status === "RECEIVED" || p.status === "CANCELLED") return null;
  const from = dockFor(m, p.origin), to = dockFor(m, p.destination);
  const k = `${p.origin}>${p.destination}`;
  if (!beltCache.has(k)) beltCache.set(k, beltRoute(m, from, to));
  const route = beltCache.get(k)!;
  let progress = 0;
  if (p.status === "ARRIVED") progress = 1;
  else if (p.status === "IN_TRANSIT" && p.routeStartedAt && p.eta) {
    const s = Date.parse(p.routeStartedAt), e = Date.parse(p.eta);
    progress = e > s ? Math.min(1, Math.max(0, (serverNow - s) / (e - s))) : 1;
  }
  if (route.length < 2) {
    const d = progress >= 1 ? to : from;
    return { id: p.id, x: d.x + 0.5, y: d.y + 0.5, progress, status: p.status, pkg: p };
  }
  const t = progress * (route.length - 1), i = Math.min(route.length - 2, Math.floor(t)), f = t - i;
  return { id: p.id, x: route[i].x + (route[i + 1].x - route[i].x) * f, y: route[i].y + (route[i + 1].y - route[i].y) * f, progress, status: p.status, pkg: p };
}

export const PACKAGE_LABEL: Record<string, string> = {
  research_brief: "Research brief", product_proposal: "Product proposal", code_artifact: "Code", test_report: "Test report",
  release_package: "Release for your review", revision_request: "Revision request", bill_reminder: "Bill reminder",
  payment_proposal: "Payment proposal", purchase_request: "Purchase request", tax_review_package: "Tax review",
};

/** Floor tiles for agents without a desk, clear of walls, furniture, chairs and the walkway to the door. */
export function standingSpots(m: GameMap): { x: number; y: number; facing: Dir }[] {
  const taken = new Set<number>();
  for (const p of m.props) if (p.solid === false) for (let dx = 0; dx < Math.max(1, p.w ?? 1); dx++) taken.add(p.y * m.w + p.x + dx);
  const out: { x: number; y: number; facing: Dir }[] = [];
  for (let y = m.h - 2; y >= 2; y--)
    for (let x = 2; x < m.w - 1; x += 2)
      if (x !== m.spawn.x && !isSolid(m, x, y) && !taken.has(y * m.w + x)) out.push({ x: x - 0.5, y, facing: "down" });
  return out;
}
