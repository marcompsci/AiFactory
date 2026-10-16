/**
 * The playable town and its building interiors, built from code so layout, collision and the conveyor network all come
 * from one source. Tiles are 16 px. Coordinates are tile units: x right, y down.
 */

export type Ground = "grass" | "grass2" | "path" | "plaza" | "water" | "wood" | "tile" | "carpet" | "metal" | "wall";
export type Deco =
  | "tree" | "pine" | "bush" | "flowers" | "fence" | "lamp" | "rock" | "fountain" | "sign" | "stall" | "bench"
  | "desk" | "monitor" | "chair" | "shelf" | "plant" | "whiteboard" | "sofa" | "table" | "screen" | "telescope"
  | "server" | "anvil" | "cooler" | "printer" | "clock" | "window" | "rug" | "counter" | "board" | "terminal" | "crates";

export interface BuildingDef {
  id: string;            // district id
  name: string;
  x: number; y: number; w: number; h: number;  // footprint, including the roof rows
  door: { x: number; y: number };
  style: "spire" | "dome" | "forge" | "tower" | "citadel" | "studio" | "bank" | "vault" | "depot";
  roof: string;
  wall: string;
  enterable: boolean;
  note?: string;         // shown when the building isn't open yet
}

export interface Prop { kind: Deco; x: number; y: number; w?: number; h?: number; solid?: boolean; flip?: boolean; color?: string }

export interface Interactable {
  id: string;
  x: number; y: number;
  label: string;
  action: "journal" | "approvals" | "findings" | "exit" | "closed" | "enter";
  target?: string;
}

export interface Workstation { x: number; y: number; facing: Dir }
export type Dir = "down" | "up" | "left" | "right";

export interface GameMap {
  id: string;
  name: string;
  w: number;
  h: number;
  ground: Ground[];          // w*h
  solid: Uint8Array;         // w*h, 1 = blocked
  props: Prop[];
  buildings: BuildingDef[];
  interactables: Interactable[];
  belt: Set<number>;         // tile indexes carrying a conveyor
  docks: Record<string, { x: number; y: number }>;  // district → conveyor dock tile
  workstations: Workstation[];
  spawn: { x: number; y: number; facing: Dir };
  exits: { x: number; y: number; to: string; at: { x: number; y: number; facing: Dir } }[];
}

export const TILE = 16;

function blank(id: string, name: string, w: number, h: number, g: Ground): GameMap {
  return {
    id, name, w, h, ground: new Array(w * h).fill(g), solid: new Uint8Array(w * h), props: [], buildings: [], interactables: [],
    belt: new Set(), docks: {}, workstations: [], spawn: { x: 1, y: 1, facing: "down" }, exits: [],
  };
}

const idx = (m: GameMap, x: number, y: number) => y * m.w + x;
const inside = (m: GameMap, x: number, y: number) => x >= 0 && y >= 0 && x < m.w && y < m.h;

function fill(m: GameMap, x: number, y: number, w: number, h: number, g: Ground) {
  for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) if (inside(m, i, j)) m.ground[idx(m, i, j)] = g;
}

function block(m: GameMap, x: number, y: number, w = 1, h = 1) {
  for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) if (inside(m, i, j)) m.solid[idx(m, i, j)] = 1;
}

function prop(m: GameMap, p: Prop) {
  m.props.push(p);
  if (p.solid !== false) block(m, p.x, p.y, p.w ?? 1, p.h ?? 1);
}

/** A tiny deterministic random, so decoration lands in the same place every load. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

// ---------------------------------------------------------------- the town
export const TOWN_BUILDINGS: BuildingDef[] = [
  { id: "data-observatory", name: "Research Observatory", x: 5, y: 5, w: 7, h: 7, door: { x: 8, y: 11 }, style: "dome", roof: "#5C7FD6", wall: "#EADBC0", enterable: true },
  { id: "nexus-spire", name: "Nexus Spire", x: 21, y: 2, w: 7, h: 10, door: { x: 24, y: 11 }, style: "spire", roof: "#7A5CD6", wall: "#E8DDF2", enterable: true },
  { id: "code-forge", name: "Code Forge", x: 36, y: 5, w: 7, h: 7, door: { x: 39, y: 11 }, style: "forge", roof: "#C2553A", wall: "#E9D6BC", enterable: true },
  { id: "vision-quarter", name: "Creative Studio", x: 4, y: 16, w: 7, h: 6, door: { x: 7, y: 21 }, style: "studio", roof: "#D65C9E", wall: "#F2E4D6", enterable: false, note: "The Creative Studio opens in a later update." },
  { id: "sentinel-citadel", name: "Sentinel Citadel", x: 37, y: 16, w: 7, h: 6, door: { x: 40, y: 21 }, style: "citadel", roof: "#4F8A62", wall: "#D9D6CC", enterable: false, note: "The Sentinel Citadel opens in a later update." },
  { id: "central-bank", name: "AI Central Bank", x: 5, y: 27, w: 7, h: 6, door: { x: 8, y: 32 }, style: "bank", roof: "#C9A23A", wall: "#F1E9D2", enterable: false, note: "The Bank's interior opens in a later update. Use the Bank panel on the main screen meanwhile." },
  { id: "owners-tower", name: "Owner's Tower", x: 21, y: 25, w: 7, h: 8, door: { x: 24, y: 32 }, style: "tower", roof: "#3D4F8F", wall: "#E2E6EF", enterable: false },
  { id: "memory-vault", name: "Memory Vault", x: 36, y: 27, w: 7, h: 6, door: { x: 39, y: 32 }, style: "vault", roof: "#5A5F73", wall: "#CFCBD8", enterable: false, note: "The Memory Vault opens in a later update." },
];

/** Districts that aren't buildings in town (the factories) hand packages over at the logistics depot on the east road. */
export const DEPOT = { id: "logistics-depot", x: 46, y: 23 };

export function buildTown(): GameMap {
  const W = 50, H = 38;
  const m = blank("town", "AI Civilization", W, H, "grass");
  const r = rng(7);
  for (let i = 0; i < W * H; i++) if (r() < 0.18) m.ground[i] = "grass2";

  // roads: three avenues, two side roads, the plaza
  fill(m, 2, 13, 46, 2, "path");
  fill(m, 2, 23, 46, 2, "path");
  fill(m, 2, 34, 46, 2, "path");
  fill(m, 2, 13, 2, 23, "path");
  fill(m, 46, 13, 2, 23, "path");
  fill(m, 23, 12, 2, 12, "path");
  fill(m, 18, 15, 12, 8, "plaza");
  // a pond in the north-west corner of the plaza block and one by the vault
  fill(m, 13, 16, 4, 3, "water");
  block(m, 13, 16, 4, 3);
  fill(m, 31, 29, 3, 2, "water");
  block(m, 31, 29, 3, 2);

  for (const b of TOWN_BUILDINGS) {
    m.buildings.push(b);
    block(m, b.x, b.y, b.w, b.h);
    m.solid[idx(m, b.door.x, b.door.y)] = 0;
    fill(m, b.door.x, b.door.y + 1, 1, 1, "path");
    fill(m, b.door.x, b.door.y, 1, 1, "path");
    // connect the door down to its avenue
    const avenue = b.door.y < 13 ? 13 : b.door.y < 23 ? 23 : 34;
    fill(m, b.door.x, b.door.y + 1, 1, Math.max(0, avenue - b.door.y - 1), "path");
    m.interactables.push(b.enterable
      ? { id: `door:${b.id}`, x: b.door.x, y: b.door.y, label: `Enter ${b.name}`, action: "enter", target: b.id }
      : b.id === "owners-tower"
        ? { id: `door:${b.id}`, x: b.door.x, y: b.door.y, label: "Owner's Tower: approvals", action: "approvals" }
        : { id: `door:${b.id}`, x: b.door.x, y: b.door.y, label: b.name, action: "closed", target: b.id });
    // conveyor dock two tiles right of the door, with a spur down to the belt lane on the avenue's lower row
    const dock = { x: b.door.x + 2, y: b.door.y + 1 };
    m.docks[b.id] = dock;
    for (let y = dock.y; y <= avenue + 1; y++) m.belt.add(idx(m, dock.x, y));
  }
  // fountain in the middle of the plaza
  prop(m, { kind: "fountain", x: 23, y: 17, w: 2, h: 2 });
  // belt lanes: lower row of each avenue and the outer edge of each side road, joined into one loop
  for (let x = 3; x <= 46; x++) for (const y of [14, 24, 35]) m.belt.add(idx(m, x, y));
  for (let y = 14; y <= 35; y++) { m.belt.add(idx(m, 3, y)); m.belt.add(idx(m, 46, y)); }
  m.docks[DEPOT.id] = { x: 46, y: 24 };
  prop(m, { kind: "crates", x: 48, y: 23, w: 1, h: 2 });
  m.interactables.push({ id: "depot", x: 47, y: 24, label: "Logistics depot (to the factories)", action: "closed", target: DEPOT.id });

  // signposts, lamps and benches along the roads
  for (const [x, y] of [[6, 12], [19, 12], [33, 12], [19, 22], [29, 22], [12, 33], [29, 33]] as const) prop(m, { kind: "lamp", x, y });
  prop(m, { kind: "sign", x: 22, y: 12 });
  m.interactables.push({ id: "sign:plaza", x: 22, y: 12, label: "Read the town sign", action: "journal" });
  for (const [x, y] of [[19, 16], [28, 16], [19, 21], [28, 21]] as const) prop(m, { kind: "bench", x, y });
  prop(m, { kind: "stall", x: 31, y: 17, w: 3, h: 2 });

  // trees around the edge and in the gaps, flowers and bushes on open grass
  const free = (x: number, y: number) => inside(m, x, y) && !m.solid[idx(m, x, y)] && !m.belt.has(idx(m, x, y)) && (m.ground[idx(m, x, y)] === "grass" || m.ground[idx(m, x, y)] === "grass2");
  for (let x = 0; x < W; x++) for (const y of [0, 1, H - 2, H - 1]) if (free(x, y)) prop(m, { kind: (x + y) % 3 ? "tree" : "pine", x, y });
  for (let y = 2; y < H - 2; y++) for (const x of [0, 1, W - 2, W - 1]) if (free(x, y) && !(x >= 48 && y >= 22 && y <= 25)) prop(m, { kind: (x + y) % 3 ? "pine" : "tree", x, y });
  for (let y = 2; y < H - 2; y++) for (let x = 2; x < W - 2; x++) {
    if (!free(x, y)) continue;
    const nearRoad = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => inside(m, x + dx, y + dy) && m.ground[idx(m, x + dx, y + dy)] === "path");
    const nearDoor = m.buildings.some((b) => Math.abs(b.door.x - x) <= 1 && y >= b.door.y && y <= b.door.y + 2);
    if (nearDoor) continue;
    const roll = r();
    if (!nearRoad && roll < 0.07) prop(m, { kind: r() < 0.5 ? "tree" : "pine", x, y });
    else if (!nearRoad && roll < 0.1) prop(m, { kind: "bush", x, y });
    else if (roll < 0.16) prop(m, { kind: "flowers", x, y, solid: false, color: ["#FF8FB8", "#FFD36B", "#B98CFF", "#FFFFFF"][Math.floor(r() * 4)] });
    else if (!nearRoad && roll < 0.175) prop(m, { kind: "rock", x, y });
  }
  // flower beds in front of the enterable buildings
  for (const b of m.buildings.filter((b) => b.enterable)) {
    for (const dx of [-2, -1, 1]) {
      const x = b.door.x + dx, y = b.door.y + 1;
      if (free(x, y)) prop(m, { kind: "flowers", x, y, solid: false, color: "#FF8FB8" });
    }
  }
  m.spawn = { x: 24, y: 20, facing: "up" };
  return m;
}

// ---------------------------------------------------------------- interiors
type Furnish = (m: GameMap) => void;

function room(id: string, name: string, floor: Ground, wallColor: string, furnish: Furnish): GameMap {
  const W = 18, H = 13;
  const m = blank(id, name, W, H, floor);
  fill(m, 0, 0, W, 2, "wall");
  block(m, 0, 0, W, 2);
  block(m, 0, 0, 1, H);
  block(m, W - 1, 0, 1, H);
  block(m, 0, H - 1, W, 1);
  const door = { x: 9, y: H - 1 };
  m.solid[idx(m, door.x, door.y)] = 0;
  m.ground[idx(m, door.x, door.y)] = "carpet";
  m.interactables.push({ id: "exit", x: door.x, y: door.y, label: "Leave", action: "exit" });
  const outside = TOWN_BUILDINGS.find((b) => b.id === id)!;
  m.exits.push({ x: door.x, y: door.y, to: "town", at: { x: outside.door.x, y: outside.door.y + 1, facing: "down" } });
  m.spawn = { x: door.x, y: door.y - 1, facing: "up" };
  m.props.push({ kind: "window", x: 2, y: 0, w: 2, h: 2, solid: false, color: wallColor }, { kind: "clock", x: 8, y: 0, solid: false });
  furnish(m);
  return m;
}

function desk(m: GameMap, x: number, y: number, facing: Dir = "up") {
  prop(m, { kind: "desk", x, y, w: 2, h: 1 });
  m.props.push({ kind: "monitor", x, y, solid: false });
  m.props.push({ kind: "chair", x, y: y + 1, solid: false });
  m.workstations.push({ x: x + 0.5, y: y + 1, facing });
}

export function buildInterior(id: string): GameMap | null {
  if (id === "nexus-spire") {
    return room(id, "Nexus Spire", "carpet", "#7A5CD6", (m) => {
      prop(m, { kind: "screen", x: 6, y: 0, w: 6, h: 2, solid: true });
      prop(m, { kind: "table", x: 5, y: 4, w: 4, h: 2 });
      for (const [x, y] of [[5, 3], [8, 3], [5, 6], [8, 6]] as const) m.props.push({ kind: "chair", x, y, solid: false });
      prop(m, { kind: "whiteboard", x: 13, y: 0, w: 3, h: 2 });
      m.interactables.push({ id: "board", x: 14, y: 2, label: "Mission board", action: "journal" });
      prop(m, { kind: "terminal", x: 15, y: 5 });
      m.interactables.push({ id: "approvals", x: 14, y: 5, label: "Approval terminal", action: "approvals" });
      desk(m, 11, 7);
      desk(m, 3, 8);
      prop(m, { kind: "plant", x: 1, y: 2 });
      prop(m, { kind: "plant", x: 16, y: 10 });
      prop(m, { kind: "sofa", x: 13, y: 10, w: 2, h: 1 });
      m.props.push({ kind: "rug", x: 7, y: 9, w: 5, h: 2, solid: false });
    });
  }
  if (id === "data-observatory") {
    return room(id, "Research Observatory", "tile", "#5C7FD6", (m) => {
      prop(m, { kind: "telescope", x: 8, y: 2, w: 2, h: 2 });
      m.interactables.push({ id: "telescope", x: 8, y: 4, label: "Telescope: findings", action: "findings" });
      for (const x of [12, 13, 14, 15]) prop(m, { kind: "shelf", x, y: 0, h: 2 });
      desk(m, 2, 4);
      desk(m, 12, 4);
      desk(m, 2, 8);
      prop(m, { kind: "table", x: 12, y: 8, w: 3, h: 2 });
      prop(m, { kind: "plant", x: 1, y: 2 });
      prop(m, { kind: "plant", x: 16, y: 2 });
      prop(m, { kind: "cooler", x: 16, y: 7 });
    });
  }
  if (id === "code-forge") {
    return room(id, "Code Forge", "wood", "#C2553A", (m) => {
      for (const x of [13, 14, 15, 16]) prop(m, { kind: "server", x, y: 2, h: 1 });
      prop(m, { kind: "anvil", x: 8, y: 3, w: 2, h: 1 });
      prop(m, { kind: "board", x: 5, y: 0, w: 3, h: 2 });
      m.interactables.push({ id: "build-monitor", x: 6, y: 2, label: "Build monitor", action: "journal" });
      desk(m, 2, 5);
      desk(m, 6, 6);
      desk(m, 11, 6);
      prop(m, { kind: "printer", x: 16, y: 6 });
      prop(m, { kind: "plant", x: 1, y: 2 });
      prop(m, { kind: "sofa", x: 2, y: 10, w: 2, h: 1 });
      prop(m, { kind: "cooler", x: 16, y: 10 });
    });
  }
  return null;
}

export const ENTERABLE = TOWN_BUILDINGS.filter((b) => b.enterable).map((b) => b.id);

export function isSolid(m: GameMap, x: number, y: number): boolean {
  if (!inside(m, x, y)) return true;
  return m.solid[idx(m, x, y)] === 1;
}

export function tileIndex(m: GameMap, x: number, y: number): number {
  return idx(m, x, y);
}
