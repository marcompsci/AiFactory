import data from "./districts.json";

export type Vec3 = [number, number, number];

export interface Workstation {
  id: string;
  label: string;
  offset: Vec3;
}

export type Architecture = "spire" | "blocks" | "fortress" | "twisted" | "dome" | "vault";

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

export function workstationPosition(districtId: string, workstationId?: string | null): Vec3 {
  const d = DISTRICT_BY_ID[districtId];
  if (!d) return [0, 0, 0];
  const ws = d.workstations.find((w) => w.id === workstationId) ?? null;
  return ws ? add(d.position, ws.offset) : homePosition(districtId);
}

/** Where an idle agent stands in its home district: in front of the district, toward the plaza. */
export function homePosition(districtId: string, slot = 0): Vec3 {
  const d = DISTRICT_BY_ID[districtId];
  if (!d) return [0, 0, 0];
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
  if (d.position[0] === 0 && d.position[2] === 0) return [0, 0, 9];
  return [d.position[0] * 0.72, 0, d.position[2] * 0.72];
}
