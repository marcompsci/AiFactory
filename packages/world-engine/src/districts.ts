import data from "./districts.json";

export type Vec3 = [number, number, number];

export interface Workstation {
  id: string;
  label: string;
  offset: Vec3;
  /** AI Central Bank: which floor of the tower this desk serves (0 = vault level). */
  floor?: number;
}

export type Architecture = "spire" | "blocks" | "fortress" | "twisted" | "dome" | "vault" | "tower" | "bank";

export interface District {
  id: string;
  name: string;
  purpose: string;
  position: Vec3;
  color: string;
  architecture: Architecture;
  towers: number;
  height: number;
  workstations: Workstation[];
}

/** Configuration-driven: add a district to districts.json and the renderer, navigation and labels pick it up. */
export const DISTRICTS: District[] = data.districts as District[];
export const DISTRICT_BY_ID: Record<string, District> = Object.fromEntries(DISTRICTS.map((d) => [d.id, d]));

export function add(a: Vec3, b: Vec3): Vec3 {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
}

export const BELT_HEIGHT = 1.2;
const TERMINAL_SPREAD = 3;

/** Dispatch / receiving terminals at a district's gate. Mirrors services/logistics/graph.py. */
export function terminalPosition(districtId: string, kind: "dispatch" | "receiving"): Vec3 {
  const [gx, , gz] = gatePosition(districtId);
  const n = Math.hypot(gx, gz) || 1;
  const px = -gz / n;
  const pz = gx / n;
  const s = kind === "dispatch" ? TERMINAL_SPREAD : -TERMINAL_SPREAD;
  return [gx + px * s, 0, gz + pz * s];
}

export function workstationPosition(districtId: string, workstationId?: string | null): Vec3 {
  const d = DISTRICT_BY_ID[districtId];
  if (!d) return [0, 0, 0];
  if (workstationId?.endsWith(":dispatch") || workstationId?.endsWith(":receiving")) {
    const kind = workstationId.endsWith(":dispatch") ? "dispatch" : "receiving";
    const t = terminalPosition(districtId, kind);
    // stand just in front of the terminal, on the plaza side
    const [gx, , gz] = gatePosition(districtId);
    const n = Math.hypot(gx, gz) || 1;
    return [t[0] - (gx / n) * 1.6, 0, t[2] - (gz / n) * 1.6];
  }
  const ws = d.workstations.find((w) => w.id === workstationId) ?? null;
  return ws ? add(d.position, ws.offset) : homePosition(districtId);
}

/** Where an idle agent stands in its home district: in front of the district, toward the plaza. */
export function homePosition(districtId: string, slot = 0): Vec3 {
  const d = DISTRICT_BY_ID[districtId];
  if (!d) return [0, 0, 0];
  if (d.architecture === "bank" && d.workstations.length) {
    // the bank's staff wait at the floor desks in front of the tower rather than crowding its gate
    const w = d.workstations[slot % d.workstations.length];
    return add(d.position, [w.offset[0] - 1.6, 0, w.offset[2]]);
  }
  const g = gatePosition(districtId);
  const side = slot % 2 === 0 ? 1 : -1;
  const spread = Math.ceil(slot / 2) * 4.5 * side;
  // perpendicular to the gate direction
  const dx = -d.position[0];
  const dz = -d.position[2];
  const len = Math.hypot(dx, dz) || 1;
  return [g[0] + (-dz / len) * spread, 0, g[2] + (dx / len) * spread];
}

/** The point where a district's elevated walkway meets the ground, at the near edge of the district pad. */
export function gatePosition(districtId: string): Vec3 {
  const d = DISTRICT_BY_ID[districtId];
  if (!d) return [0, 0, 0];
  if (d.position[0] === 0 && d.position[2] === 0) return [0, 0, 9]; // south, toward the Logistics Network hub; north belongs to the Owner's Tower
  return [d.position[0] * 0.72, 0, d.position[2] * 0.72];
}
