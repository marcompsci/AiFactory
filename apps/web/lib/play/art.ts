/**
 * Pixel art for the town and interiors, painted from code at 16 px per tile: ground, props and building fronts.
 * Original art in a cozy top-down RPG style; nothing here is copied from another game.
 */
import { TILE, type BuildingDef, type GameMap, type Ground, type Prop } from "./maps";
import { shade } from "./sprites";

type Ctx = CanvasRenderingContext2D;

const C = {
  grass: "#5FAE4C", grassDark: "#4C9A3F", grassLight: "#79C25C", path: "#D9B27A", pathDark: "#BF955E", pathLight: "#E8C793",
  stone: "#B7BAC2", stoneDark: "#8C909B", stoneLight: "#D3D6DC", water: "#4AA3DC", waterLight: "#8FD3F5", waterDark: "#3787C1",
  wood: "#C4884C", woodDark: "#9B6534", woodLight: "#DDA56A", trunk: "#7A4E2C", leaf: "#3F9A47", leafDark: "#2E7A3A", leafLight: "#6CC45A",
  ink: "#1D1626", glass: "#7EC8F2", glassDark: "#4E8FC7", white: "#F6F4EF",
};

function r(ctx: Ctx, x: number, y: number, w: number, h: number, c: string) {
  ctx.fillStyle = c;
  ctx.fillRect(x, y, w, h);
}

function hash(x: number, y: number, s = 0): number {
  let h = (x * 374761393 + y * 668265263 + s * 2147483647) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function canvas(w: number, h: number): [HTMLCanvasElement, Ctx] {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  ctx.imageSmoothingEnabled = false;
  return [c, ctx];
}

// ---------------------------------------------------------------- ground
function groundAt(m: GameMap, x: number, y: number): Ground | null {
  return x < 0 || y < 0 || x >= m.w || y >= m.h ? null : m.ground[y * m.w + x];
}

function paintGround(ctx: Ctx, m: GameMap, x: number, y: number) {
  const g = m.ground[y * m.w + x];
  const px = x * TILE, py = y * TILE;
  const h = (i: number) => hash(x, y, i);
  switch (g) {
    case "grass":
    case "grass2": {
      r(ctx, px, py, TILE, TILE, C.grass);
      for (let i = 0; i < 6; i++) {
        const tx = Math.floor(h(i) * 15), ty = Math.floor(h(i + 9) * 14);
        r(ctx, px + tx, py + ty, 1, 2, h(i + 3) < 0.5 ? C.grassDark : C.grassLight);
      }
      if (g === "grass2") {
        const tx = 3 + Math.floor(h(20) * 9), ty = 4 + Math.floor(h(21) * 8);
        r(ctx, px + tx, py + ty, 1, 2, C.grassDark); r(ctx, px + tx + 2, py + ty, 1, 2, C.grassDark); r(ctx, px + tx + 1, py + ty + 1, 1, 2, C.grassDark);
      }
      break;
    }
    case "path": {
      r(ctx, px, py, TILE, TILE, C.path);
      for (let i = 0; i < 5; i++) r(ctx, px + Math.floor(h(i) * 15), py + Math.floor(h(i + 5) * 15), 2, 1, h(i + 7) < 0.5 ? C.pathDark : C.pathLight);
      const edge = (dx: number, dy: number) => { const n = groundAt(m, x + dx, y + dy); return n === "grass" || n === "grass2"; };
      if (edge(0, -1)) { r(ctx, px, py, TILE, 1, C.pathDark); for (let i = 0; i < 16; i += 3) r(ctx, px + i, py, 1, 2, C.grassDark); }
      if (edge(0, 1)) r(ctx, px, py + 15, TILE, 1, C.pathDark);
      if (edge(-1, 0)) r(ctx, px, py, 1, TILE, C.pathDark);
      if (edge(1, 0)) r(ctx, px + 15, py, 1, TILE, C.pathDark);
      break;
    }
    case "plaza": {
      r(ctx, px, py, TILE, TILE, C.stoneDark);
      const off = (y % 2) * 4;
      for (let row = 0; row < 2; row++) for (let col = -1; col < 2; col++) {
        const sx = px + col * 8 + off + (row ? 4 : 0), sy = py + row * 8;
        const cx0 = Math.max(px, sx + 1), cx1 = Math.min(px + 16, sx + 8);
        if (cx1 > cx0) {
          r(ctx, cx0, sy + 1, cx1 - cx0, 6, hash(x * 3 + col, y * 2 + row) < 0.3 ? C.stoneLight : C.stone);
          r(ctx, cx0, sy + 6, cx1 - cx0, 1, shade(C.stone, -0.1));
        }
      }
      break;
    }
    case "water": {
      r(ctx, px, py, TILE, TILE, C.water);
      r(ctx, px + Math.floor(h(1) * 10), py + 4 + Math.floor(h(2) * 8), 4, 1, C.waterLight);
      const land = (dx: number, dy: number) => { const n = groundAt(m, x + dx, y + dy); return n !== "water"; };
      if (land(0, -1)) { r(ctx, px, py, TILE, 3, C.waterDark); r(ctx, px, py, TILE, 1, C.stoneDark); }
      if (land(-1, 0)) r(ctx, px, py, 2, TILE, C.waterLight);
      if (land(1, 0)) r(ctx, px + 14, py, 2, TILE, C.waterLight);
      if (land(0, 1)) r(ctx, px, py + 14, TILE, 2, C.waterLight);
      break;
    }
    case "wood": {
      r(ctx, px, py, TILE, TILE, C.wood);
      for (let i = 0; i < 4; i++) {
        r(ctx, px, py + i * 4 + 3, TILE, 1, C.woodDark);
        const j = Math.floor(hash(x, y * 4 + i) * 14);
        r(ctx, px + j, py + i * 4, 1, 3, C.woodDark);
        r(ctx, px + ((j + 5) % 15), py + i * 4 + 1, 2, 1, C.woodLight);
      }
      break;
    }
    case "tile": {
      const a = (x + y) % 2 === 0;
      r(ctx, px, py, TILE, TILE, a ? "#E6ECF2" : "#D4DCE6");
      r(ctx, px, py + 15, TILE, 1, "#BFC9D6"); r(ctx, px + 15, py, 1, TILE, "#BFC9D6");
      break;
    }
    case "carpet": {
      r(ctx, px, py, TILE, TILE, "#4E4A86");
      if ((x + y) % 2 === 0) { r(ctx, px + 6, py + 6, 4, 4, "#5D58A0"); r(ctx, px + 7, py + 7, 2, 2, "#6F69B5"); }
      break;
    }
    case "metal": {
      r(ctx, px, py, TILE, TILE, "#9AA3B2");
      r(ctx, px + 2, py + 2, 1, 1, "#C9D0DB"); r(ctx, px + 13, py + 13, 1, 1, "#C9D0DB");
      break;
    }
    case "wall": {
      r(ctx, px, py, TILE, TILE, "#EFE7DA");
      if (y === 0) { r(ctx, px, py, TILE, 4, "#5A4A6E"); r(ctx, px, py + 4, TILE, 1, "#3E3150"); }
      else { r(ctx, px, py + 11, TILE, 5, "#C9B79E"); r(ctx, px, py + 11, TILE, 1, "#A99577"); r(ctx, px, py + 15, TILE, 1, "#7E6B52"); }
      for (let i = 0; i < 3; i++) r(ctx, px + Math.floor(hash(x, y, i) * 15), py + 5 + Math.floor(hash(y, x, i) * 5), 1, 1, "#E2D8C8");
      break;
    }
  }
}

/** Flat things drawn into the ground layer (players walk over them). */
function paintFlat(ctx: Ctx, p: Prop) {
  const px = p.x * TILE, py = p.y * TILE;
  if (p.kind === "flowers") {
    const c = p.color ?? "#FF8FB8";
    for (const [fx, fy] of [[3, 4], [10, 3], [6, 10], [12, 11]] as const) {
      r(ctx, px + fx, py + fy + 2, 1, 3, C.leafDark);
      r(ctx, px + fx - 1, py + fy, 3, 3, c); r(ctx, px + fx, py + fy + 1, 1, 1, "#FFE66B");
    }
  } else if (p.kind === "rug") {
    const w = (p.w ?? 1) * TILE, h = (p.h ?? 1) * TILE;
    r(ctx, px, py, w, h, "#B5476B"); r(ctx, px + 2, py + 2, w - 4, h - 4, "#D9668A"); r(ctx, px + 5, py + 5, w - 10, h - 10, "#B5476B");
    for (let i = 4; i < w - 4; i += 4) { r(ctx, px + i, py - 1, 1, 2, "#F4D58D"); r(ctx, px + i, py + h - 1, 1, 2, "#F4D58D"); }
  }
}

export function paintGroundLayer(m: GameMap): HTMLCanvasElement {
  const [c, ctx] = canvas(m.w * TILE, m.h * TILE);
  for (let y = 0; y < m.h; y++) for (let x = 0; x < m.w; x++) paintGround(ctx, m, x, y);
  for (const p of m.props) if (p.kind === "flowers" || p.kind === "rug") paintFlat(ctx, p);
  return c;
}

// ---------------------------------------------------------------- standing props (depth-sorted with characters)
export interface Sprite { canvas: HTMLCanvasElement; ox: number; oy: number; baseY: number }

const propCache = new Map<string, { canvas: HTMLCanvasElement; ox: number; oy: number }>();

function makeProp(p: Prop): { canvas: HTMLCanvasElement; ox: number; oy: number } {
  const w = (p.w ?? 1) * TILE, h = (p.h ?? 1) * TILE;
  const key = `${p.kind}:${p.w ?? 1}x${p.h ?? 1}:${p.color ?? ""}:${(p.x * 7 + p.y * 3) % 3}`;
  const hit = propCache.get(key);
  if (hit) return hit;
  let out: { canvas: HTMLCanvasElement; ox: number; oy: number };
  const v = (p.x * 7 + p.y * 3) % 3;
  switch (p.kind) {
    case "tree": {
      const [c, x] = canvas(22, 30);
      r(x, 9, 20, 4, 8, C.trunk); r(x, 9, 20, 1, 8, shade(C.trunk, -0.3));
      r(x, 7, 28, 8, 2, "rgba(0,0,0,0.18)");
      const leaf = v === 2 ? "#4FA83F" : C.leaf;
      r(x, 3, 4, 16, 14, leaf); r(x, 1, 7, 20, 9, leaf); r(x, 5, 2, 12, 2, leaf); r(x, 7, 1, 8, 1, leaf);
      r(x, 3, 15, 16, 3, C.leafDark); r(x, 1, 13, 2, 3, C.leafDark); r(x, 19, 13, 2, 3, C.leafDark);
      r(x, 6, 4, 4, 2, C.leafLight); r(x, 4, 7, 3, 2, C.leafLight); r(x, 12, 3, 3, 2, C.leafLight);
      if (v === 1) for (const [a, b] of [[6, 9], [14, 7], [10, 12]] as const) { r(x, a, b, 2, 2, "#F28C38"); r(x, a, b, 1, 1, "#FFC36B"); }
      if (v === 2) for (const [a, b] of [[5, 10], [13, 6], [9, 13], [16, 11]] as const) r(x, a, b, 1, 1, "#FFD1E8");
      out = { canvas: c, ox: -3, oy: -14 };
      break;
    }
    case "pine": {
      const [c, x] = canvas(18, 30);
      r(x, 7, 24, 4, 5, C.trunk); r(x, 6, 28, 8, 2, "rgba(0,0,0,0.18)");
      const g = "#2F8A4A", gd = "#22683A", gl = "#4DAE5E";
      for (let i = 0; i < 3; i++) {
        const top = 2 + i * 7, wid = 8 + i * 4;
        for (let j = 0; j < 9; j++) { const ww = Math.min(wid, 2 + j * 2); r(x, 9 - ww / 2, top + j, ww, 1, j === 8 ? gd : g); }
        r(x, 7, top + 2, 2, 2, gl);
      }
      out = { canvas: c, ox: -1, oy: -14 };
      break;
    }
    case "bush": {
      const [c, x] = canvas(16, 16);
      r(x, 2, 14, 12, 2, "rgba(0,0,0,0.15)");
      r(x, 1, 5, 14, 9, C.leaf); r(x, 3, 3, 10, 2, C.leaf); r(x, 2, 12, 12, 2, C.leafDark); r(x, 4, 5, 3, 2, C.leafLight);
      r(x, 9, 7, 2, 2, "#E2465E"); r(x, 5, 10, 2, 2, "#E2465E");
      out = { canvas: c, ox: 0, oy: 0 };
      break;
    }
    case "rock": {
      const [c, x] = canvas(16, 16);
      r(x, 3, 7, 10, 7, C.stoneDark); r(x, 4, 6, 8, 6, C.stone); r(x, 5, 7, 3, 2, C.stoneLight); r(x, 3, 13, 10, 1, "#6E727C");
      out = { canvas: c, ox: 0, oy: 0 };
      break;
    }
    case "lamp": {
      const [c, x] = canvas(16, 32);
      r(x, 7, 8, 2, 22, "#3A3448"); r(x, 5, 29, 6, 2, "#3A3448");
      r(x, 4, 2, 8, 7, "#3A3448"); r(x, 5, 3, 6, 5, "#FFE08A"); r(x, 6, 4, 2, 2, "#FFF6CF"); r(x, 6, 0, 4, 2, "#3A3448");
      out = { canvas: c, ox: 0, oy: -16 };
      break;
    }
    case "sign": {
      const [c, x] = canvas(16, 24);
      r(x, 7, 12, 2, 12, C.woodDark); r(x, 1, 3, 14, 10, C.woodDark); r(x, 2, 4, 12, 8, C.wood);
      r(x, 4, 6, 8, 1, C.woodDark); r(x, 4, 9, 6, 1, C.woodDark);
      out = { canvas: c, ox: 0, oy: -8 };
      break;
    }
    case "bench": {
      const [c, x] = canvas(16, 16);
      r(x, 1, 5, 14, 3, C.woodDark); r(x, 1, 9, 14, 3, C.wood); r(x, 2, 12, 2, 3, "#3A3448"); r(x, 12, 12, 2, 3, "#3A3448");
      out = { canvas: c, ox: 0, oy: 0 };
      break;
    }
    case "fountain": {
      const [c, x] = canvas(32, 36);
      r(x, 1, 14, 30, 20, C.stoneDark); r(x, 2, 15, 28, 17, C.stone); r(x, 4, 17, 24, 13, C.water); r(x, 6, 19, 6, 1, C.waterLight);
      r(x, 13, 6, 6, 14, C.stoneDark); r(x, 14, 6, 4, 13, C.stone); r(x, 10, 4, 12, 3, C.stoneDark);
      r(x, 15, 0, 2, 5, C.waterLight); r(x, 11, 3, 2, 2, C.waterLight); r(x, 19, 3, 2, 2, C.waterLight);
      r(x, 1, 33, 30, 2, "rgba(0,0,0,0.2)");
      out = { canvas: c, ox: 0, oy: -4 };
      break;
    }
    case "stall": {
      const [c, x] = canvas(48, 36);
      r(x, 3, 14, 2, 20, C.woodDark); r(x, 43, 14, 2, 20, C.woodDark);
      for (let i = 0; i < 8; i++) r(x, 1 + i * 6, 6, 6, 9, i % 2 ? "#FFFFFF" : "#F07A3A");
      r(x, 1, 14, 46, 2, "#C25A28"); r(x, 1, 4, 46, 2, "#C25A28");
      r(x, 4, 22, 40, 10, C.wood); r(x, 4, 22, 40, 2, C.woodLight);
      r(x, 8, 19, 5, 4, "#E2465E"); r(x, 16, 19, 5, 4, "#FFD36B"); r(x, 26, 19, 5, 4, "#7FD3FF"); r(x, 34, 19, 5, 4, "#9B6BE0");
      out = { canvas: c, ox: 0, oy: -4 };
      break;
    }
    case "crates": {
      const [c, x] = canvas(16, 32);
      for (const y of [4, 18]) { r(x, 1, y, 14, 12, C.woodDark); r(x, 2, y + 1, 12, 10, C.wood); r(x, 2, y + 5, 12, 1, C.woodDark); r(x, 7, y + 1, 1, 10, C.woodDark); }
      out = { canvas: c, ox: 0, oy: 0 };
      break;
    }
    // ---------------------------------------------------------------- interiors
    case "desk": {
      const [c, x] = canvas(w, 20);
      r(x, 0, 2, w, 10, "#B07A45"); r(x, 0, 2, w, 2, "#CF9A5E"); r(x, 0, 11, w, 3, "#8A5A30");
      r(x, 2, 12, 2, 8, "#6B4424"); r(x, w - 4, 12, 2, 8, "#6B4424");
      r(x, 4, 5, 8, 3, "#3A3448"); r(x, 5, 6, 6, 1, "#5A5470"); r(x, w - 10, 4, 4, 5, "#F2F2F2"); r(x, w - 9, 5, 2, 3, "#C9D3E0");
      out = { canvas: c, ox: 0, oy: -4 };
      break;
    }
    case "monitor": {
      const [c, x] = canvas(16, 16);
      r(x, 2, 0, 12, 9, "#2A2838"); r(x, 3, 1, 10, 7, "#4FB6F0"); r(x, 4, 2, 5, 1, "#BFE9FF"); r(x, 4, 4, 7, 1, "#8FD3F5"); r(x, 4, 6, 4, 1, "#8FD3F5");
      r(x, 7, 9, 2, 2, "#2A2838"); r(x, 5, 11, 6, 1, "#2A2838");
      out = { canvas: c, ox: 4, oy: -8 };
      break;
    }
    case "chair": {
      const [c, x] = canvas(16, 16);
      r(x, 4, 2, 8, 7, "#2F3A5E"); r(x, 5, 3, 6, 5, "#3E4C78"); r(x, 3, 9, 10, 3, "#2F3A5E"); r(x, 7, 12, 2, 2, "#1D2136"); r(x, 4, 14, 8, 1, "#1D2136");
      out = { canvas: c, ox: 4, oy: 0 };
      break;
    }
    case "shelf": {
      const [c, x] = canvas(16, 32);
      r(x, 0, 0, 16, 32, "#7A4E2C"); r(x, 1, 1, 14, 30, "#5A3A20");
      const books = ["#E2465E", "#3F8CFF", "#FFD36B", "#5BF2A5", "#9B6BE0", "#F28C38", "#F2F2F2"];
      for (const sy of [2, 11, 20]) {
        let bx = 2;
        while (bx < 14) { const bw = 1 + Math.floor(hash(bx, sy, p.x) * 2); r(x, bx, sy + 1 + Math.floor(hash(sy, bx) * 2), bw, 7, books[Math.floor(hash(bx, sy + p.x) * books.length)]); bx += bw + 0; }
        r(x, 1, sy + 8, 14, 1, "#8A5A30");
      }
      out = { canvas: c, ox: 0, oy: 0 };
      break;
    }
    case "plant": {
      const [c, x] = canvas(16, 24);
      r(x, 4, 16, 8, 7, "#C2553A"); r(x, 4, 16, 8, 2, "#DA6E4F");
      for (const [a, b, ww, hh] of [[7, 2, 2, 14], [3, 5, 4, 6], [9, 4, 5, 7], [5, 9, 6, 6], [2, 10, 3, 4], [11, 10, 3, 4]] as const) r(x, a, b, ww, hh, C.leaf);
      r(x, 4, 6, 2, 2, C.leafLight); r(x, 10, 5, 2, 2, C.leafLight);
      out = { canvas: c, ox: 0, oy: -8 };
      break;
    }
    case "whiteboard": case "board": {
      const [c, x] = canvas(w, 28);
      r(x, 0, 4, w, 20, "#8C909B"); r(x, 1, 5, w - 2, 18, "#FBFCFE");
      if (p.kind === "board") { r(x, 1, 5, w - 2, 18, "#2D4A3E"); for (let i = 0; i < 4; i++) r(x, 4, 8 + i * 4, 6 + ((i * 7) % 14), 1, "#E8F5EC"); }
      else { r(x, 4, 8, 12, 1, "#3F8CFF"); r(x, 4, 11, 18, 1, "#E2465E"); r(x, 4, 14, 9, 1, "#2B2F3A"); r(x, 26, 9, 10, 8, "#FFD36B"); r(x, 4, 17, 14, 1, "#2B2F3A"); }
      r(x, 2, 23, w - 4, 2, "#8C909B");
      out = { canvas: c, ox: 0, oy: 0 };
      break;
    }
    case "screen": {
      const [c, x] = canvas(w, 30);
      r(x, 0, 2, w, 26, "#1E1B2E"); r(x, 2, 4, w - 4, 22, "#162447");
      let lx = 4, ly = 20;
      for (let i = 0; i < 16; i++) { const ny = 8 + Math.floor(hash(i, 3) * 14); r(x, lx, Math.min(ly, ny), 5, 1, "#5BF2A5"); lx += 5; ly = ny; if (lx > w - 8) break; }
      r(x, 6, 7, 18, 2, "#C9A7FF"); r(x, w - 22, 7, 16, 8, "#2E3B6B"); r(x, w - 20, 9, 12, 1, "#F4D58D"); r(x, w - 20, 12, 8, 1, "#5BF2A5");
      out = { canvas: c, ox: 0, oy: 0 };
      break;
    }
    case "table": {
      const [c, x] = canvas(w, h);
      r(x, 1, 2, w - 2, h - 6, "#B9D9EC"); r(x, 2, 3, w - 4, h - 8, "#D6ECF7"); r(x, 4, 4, 8, 1, "#FFFFFF");
      r(x, 3, h - 4, 2, 4, "#7A8696"); r(x, w - 5, h - 4, 2, 4, "#7A8696");
      out = { canvas: c, ox: 0, oy: 0 };
      break;
    }
    case "sofa": {
      const [c, x] = canvas(w, 20);
      r(x, 0, 2, w, 14, "#6B3FA0"); r(x, 2, 4, w - 4, 6, "#8250BD"); r(x, 0, 10, w, 6, "#5A3388"); r(x, w / 2 - 1, 4, 1, 6, "#5A3388");
      r(x, 1, 16, 2, 3, "#3A2A20"); r(x, w - 3, 16, 2, 3, "#3A2A20");
      out = { canvas: c, ox: 0, oy: -4 };
      break;
    }
    case "telescope": {
      const [c, x] = canvas(32, 40);
      r(x, 4, 30, 24, 8, "#5A5F73"); r(x, 6, 30, 20, 2, "#7A8096");
      r(x, 14, 18, 4, 12, "#3A3448");
      for (let i = 0; i < 14; i++) r(x, 6 + i, 18 - i, 7, 5, i < 2 ? "#8C6A2E" : "#C9A23A");
      r(x, 19, 3, 7, 5, "#8C6A2E"); r(x, 21, 4, 3, 2, "#BFE9FF");
      out = { canvas: c, ox: 0, oy: -8 };
      break;
    }
    case "server": {
      const [c, x] = canvas(16, 30);
      r(x, 1, 0, 14, 30, "#2A2838"); r(x, 2, 1, 12, 28, "#3A3850");
      for (let i = 0; i < 6; i++) { r(x, 3, 3 + i * 4, 10, 3, "#22202E"); r(x, 4, 4 + i * 4, 1, 1, i % 2 ? "#5BF2A5" : "#32D8FF"); r(x, 6, 4 + i * 4, 1, 1, "#FFBD69"); }
      out = { canvas: c, ox: 0, oy: -14 };
      break;
    }
    case "anvil": {
      const [c, x] = canvas(32, 24);
      r(x, 2, 6, 28, 6, "#4A4E5C"); r(x, 0, 6, 6, 3, "#4A4E5C"); r(x, 4, 6, 24, 2, "#6E7385");
      r(x, 10, 12, 12, 6, "#3A3D49"); r(x, 6, 18, 20, 4, "#3A3D49");
      r(x, 12, 2, 8, 3, "#FF9A3D"); r(x, 14, 0, 4, 2, "#FFD36B");
      out = { canvas: c, ox: 0, oy: -6 };
      break;
    }
    case "cooler": {
      const [c, x] = canvas(16, 30);
      r(x, 4, 0, 8, 10, "#7EC8F2"); r(x, 5, 1, 6, 8, "#A9DCF7"); r(x, 3, 10, 10, 19, "#E8ECF2"); r(x, 3, 10, 10, 2, "#FFFFFF"); r(x, 6, 16, 4, 2, "#3F8CFF");
      out = { canvas: c, ox: 0, oy: -14 };
      break;
    }
    case "printer": {
      const [c, x] = canvas(16, 20);
      r(x, 1, 6, 14, 12, "#8C909B"); r(x, 2, 7, 12, 4, "#B7BAC2"); r(x, 4, 2, 8, 5, "#F6F4EF"); r(x, 3, 13, 10, 2, "#3A3448");
      out = { canvas: c, ox: 0, oy: -4 };
      break;
    }
    case "terminal": {
      const [c, x] = canvas(16, 28);
      r(x, 3, 12, 10, 16, "#3A3448"); r(x, 1, 0, 14, 13, "#2A2838"); r(x, 2, 1, 12, 10, "#FFBD69"); r(x, 4, 3, 8, 1, "#3A2A20"); r(x, 4, 6, 5, 1, "#3A2A20");
      out = { canvas: c, ox: 0, oy: -12 };
      break;
    }
    case "clock": {
      const [c, x] = canvas(16, 16);
      r(x, 3, 3, 10, 10, "#3A3448"); r(x, 4, 4, 8, 8, "#FBFCFE"); r(x, 8, 5, 1, 4, "#3A3448"); r(x, 8, 8, 3, 1, "#3A3448");
      out = { canvas: c, ox: 0, oy: 6 };
      break;
    }
    case "window": {
      const [c, x] = canvas(w, 28);
      r(x, 0, 4, w, 22, "#5A4A6E"); r(x, 2, 6, w - 4, 18, "#8FD3F5");
      for (let i = 0; i < 5; i++) { const bh = 5 + Math.floor(hash(i, 9) * 10); r(x, 3 + i * 6, 24 - bh, 5, bh, "#5C7FD6"); r(x, 4 + i * 6, 25 - bh, 1, 1, "#FFE08A"); }
      r(x, w / 2 - 1, 6, 2, 18, "#5A4A6E");
      out = { canvas: c, ox: 0, oy: 0 };
      break;
    }
    default: {
      const [c, x] = canvas(w, h);
      r(x, 0, 0, w, h, "#888");
      out = { canvas: c, ox: 0, oy: 0 };
    }
  }
  propCache.set(key, out);
  return out;
}

export function propSprites(m: GameMap): Sprite[] {
  return m.props.filter((p) => p.kind !== "flowers" && p.kind !== "rug").map((p) => {
    const s = makeProp(p);
    // wall-mounted things sit behind everything standing on the floor
    const onWall = ["window", "clock", "whiteboard", "board", "screen"].includes(p.kind);
    const baseY = onWall ? -1 : (p.y + (p.h ?? 1)) * TILE - (p.kind === "chair" ? 10 : p.kind === "monitor" ? -2 : 0);
    return { canvas: s.canvas, ox: p.x * TILE + s.ox, oy: p.y * TILE + s.oy, baseY };
  });
}

// ---------------------------------------------------------------- building fronts
export function buildingSprite(b: BuildingDef): Sprite {
  const W = b.w * TILE, H = b.h * TILE;
  const extra = b.style === "spire" ? 26 : b.style === "tower" ? 20 : b.style === "forge" ? 14 : 8;
  const [c, x] = canvas(W, H + extra);
  const top = extra;
  const wallH = b.style === "spire" ? 64 : b.style === "tower" ? 80 : 50;
  const wallY = top + H - wallH;
  const wall = b.wall, wallD = shade(wall, -0.18), beam = "#6B4A33", roof = b.roof, roofD = shade(roof, -0.28), roofL = shade(roof, 0.2);
  const doorX = (b.door.x - b.x) * TILE;

  // shadow
  r(x, 2, top + H - 3, W - 2, 3, "rgba(0,0,0,0.2)");
  // walls
  r(x, 0, wallY, W, wallH - 2, wall);
  r(x, 0, wallY + wallH - 8, W, 6, b.style === "vault" || b.style === "citadel" ? "#8C909B" : "#A99B8A");
  for (let i = 0; i < W; i += 8) r(x, i, wallY + wallH - 8, 1, 6, "#7E7366");
  r(x, 0, wallY + wallH - 2, W, 2, "#5E5448");
  if (b.style !== "vault" && b.style !== "citadel" && b.style !== "bank") {
    r(x, 0, wallY, 3, wallH - 8, beam); r(x, W - 3, wallY, 3, wallH - 8, beam); r(x, 0, wallY, W, 3, beam);
    for (let i = 32; i < W - 8; i += 32) r(x, i, wallY, 2, wallH - 8, beam);
  } else {
    for (let j = wallY + 4; j < wallY + wallH - 8; j += 6) for (let i = (j / 6) % 2 ? 0 : 6; i < W; i += 12) r(x, i, j, 11, 1, wallD);
  }
  // windows
  const winY = wallY + Math.max(10, wallH - 40);
  for (const wx of [10, W - 26]) {
    if (Math.abs(wx + 8 - (doorX + 8)) < 14) continue;
    r(x, wx - 1, winY - 1, 18, 14, beam); r(x, wx, winY, 16, 12, C.glass); r(x, wx, winY + 7, 16, 5, C.glassDark);
    r(x, wx + 7, winY, 2, 12, beam); r(x, wx, winY + 5, 16, 2, beam); r(x, wx + 2, winY + 1, 3, 2, "#D5F0FF");
    r(x, wx - 2, winY + 12, 20, 3, shade(wall, -0.3));
    if (b.style === "studio" || b.style === "dome") { r(x, wx, winY + 13, 16, 3, C.leaf); r(x, wx + 3, winY + 13, 2, 2, "#FF8FB8"); r(x, wx + 10, winY + 13, 2, 2, "#FFD36B"); }
  }
  if (b.style === "spire" || b.style === "tower") {
    for (const wx of [10, W - 26]) {
      const y2 = winY - 22;
      r(x, wx - 1, y2 - 1, 18, 14, beam); r(x, wx, y2, 16, 12, C.glass); r(x, wx + 7, y2, 2, 12, beam); r(x, wx + 2, y2 + 1, 3, 2, "#D5F0FF");
    }
  }
  // door
  const dY = wallY + wallH - 26;
  r(x, doorX - 1, dY - 3, 18, 27, beam);
  r(x, doorX + 1, dY, 14, 24, b.style === "vault" ? "#5A5F73" : "#8B5A33");
  r(x, doorX + 1, dY, 14, 2, shade("#8B5A33", 0.2));
  if (b.style === "vault") { r(x, doorX + 4, dY + 6, 8, 8, "#3A3D49"); r(x, doorX + 7, dY + 9, 2, 2, "#C9A23A"); }
  else { r(x, doorX + 7, dY + 2, 2, 22, shade("#8B5A33", -0.3)); r(x, doorX + 11, dY + 12, 2, 2, "#F4D58D"); r(x, doorX + 3, dY + 4, 3, 5, C.glass); r(x, doorX + 10, dY + 4, 3, 5, C.glass); }
  r(x, doorX - 2, dY + 24, 20, 2, "#8C909B");
  // sign above the door
  r(x, doorX - 4, dY - 12, 24, 8, beam); r(x, doorX - 3, dY - 11, 22, 6, "#F1E2C0");
  emblem(x, b.style, doorX + 8, dY - 8);

  // roofs
  const roofTop = top;
  const roofBottom = wallY + 2;
  if (b.style === "dome") {
    const cx = W / 2, rad = Math.min(W / 2 - 2, roofBottom - roofTop);
    for (let j = 0; j < rad; j++) {
      const half = Math.round(Math.sqrt(rad * rad - (rad - j) * (rad - j)));
      r(x, cx - half, roofBottom - rad + j, half * 2, 1, j % 6 === 5 ? roofD : roof);
      if (j > 3) r(x, cx - half + 2, roofBottom - rad + j, 3, 1, roofL);
    }
    r(x, cx - 3, roofBottom - rad + 2, 6, Math.round(rad * 0.5), "#1E2A4A"); r(x, cx - 1, roofBottom - rad + 4, 2, 4, "#FFE08A");
    r(x, 0, roofBottom - 4, W, 4, roofD);
  } else if (b.style === "citadel" || b.style === "vault" || b.style === "bank") {
    r(x, 0, roofBottom - 14, W, 14, roofD);
    r(x, 0, roofBottom - 16, W, 4, roof);
    if (b.style === "citadel") for (let i = 0; i < W; i += 10) r(x, i, roofBottom - 22, 6, 7, roof);
    if (b.style === "bank") {
      r(x, 6, roofBottom - 28, W - 12, 13, roof);
      for (let j = 0; j < 12; j++) r(x, W / 2 - j * 3, roofBottom - 28 - (12 - j), j * 6, 1, roof);
      r(x, W / 2 - 5, roofBottom - 30, 10, 8, "#FFE08A"); r(x, W / 2 - 1, roofBottom - 29, 2, 6, "#C9A23A");
      for (const cx of [8, 22, W - 30, W - 16]) r(x, cx, wallY + 4, 6, wallH - 12, "#F7F3E8");
    }
    if (b.style === "vault") { r(x, W / 2 - 8, roofBottom - 30, 16, 16, roof); r(x, W / 2 - 4, roofBottom - 26, 8, 8, "#5BF2A5"); }
  } else {
    // gable roof with shingles
    const rows = roofBottom - roofTop;
    for (let j = 0; j < rows; j++) {
      const inset = Math.max(0, Math.round((1 - j / Math.max(1, rows * 0.55)) * (W / 2 - 6)));
      const col = (Math.floor(j / 4) % 2 ? roof : shade(roof, -0.08));
      r(x, inset - 3, roofTop + j, W - inset * 2 + 6, 1, col);
      if (j % 4 === 3) for (let i = inset; i < W - inset; i += 6) r(x, i + (Math.floor(j / 4) % 2) * 3, roofTop + j, 1, 1, roofD);
    }
    r(x, -3 + 3, roofBottom - 3, W, 3, roofD);
    r(x, W / 2 - 1, roofTop, 2, rows - 3, roofL);
    if (b.style === "forge") {
      r(x, W - 24, roofTop - 12, 10, 26, "#7E6B5A"); r(x, W - 25, roofTop - 14, 12, 3, "#5E5448");
      r(x, W - 22, roofTop - 22, 6, 6, "rgba(220,220,230,0.7)"); r(x, W - 18, roofTop - 30, 8, 7, "rgba(220,220,230,0.5)");
      r(x, 10, winY, 16, 12, "#FF9A3D"); r(x, 12, winY + 6, 12, 6, "#FFD36B");
    }
    if (b.style === "spire") {
      r(x, W / 2 - 8, roofTop - 6, 16, 20, shade(roof, 0.1));
      r(x, W / 2 - 4, roofTop - 22, 8, 18, "#C9A7FF"); r(x, W / 2 - 2, roofTop - 26, 4, 6, "#E9DBFF"); r(x, W / 2 - 1, roofTop - 20, 2, 10, "#FFFFFF");
    }
    if (b.style === "tower") {
      r(x, W / 2 - 1, roofTop - 20, 2, 22, "#3A3448"); r(x, W / 2 + 1, roofTop - 20, 12, 8, "#F4D58D"); r(x, W / 2 + 3, roofTop - 18, 5, 4, "#C9A23A");
    }
    if (b.style === "studio") {
      for (let i = 0; i < W - 8; i += 8) r(x, 4 + i, wallY - 2, 8, 7, (i / 8) % 2 ? "#FFFFFF" : "#FF6FAE");
    }
  }
  return { canvas: c, ox: b.x * TILE, oy: b.y * TILE - extra, baseY: (b.y + b.h) * TILE };
}

function emblem(x: Ctx, style: BuildingDef["style"], cx: number, cy: number) {
  const ink = "#3A2A40";
  switch (style) {
    case "dome": r(x, cx - 3, cy - 2, 5, 4, ink); r(x, cx - 2, cy - 1, 3, 2, "#7EC8F2"); r(x, cx + 2, cy + 1, 2, 2, ink); break;
    case "spire": r(x, cx - 1, cy - 3, 2, 6, "#7A5CD6"); r(x, cx - 3, cy - 1, 6, 2, "#7A5CD6"); break;
    case "forge": r(x, cx - 4, cy - 1, 8, 2, ink); r(x, cx - 2, cy + 1, 4, 2, ink); r(x, cx - 1, cy - 3, 2, 2, "#FF9A3D"); break;
    case "tower": r(x, cx - 3, cy - 2, 6, 4, "#C9A23A"); r(x, cx - 1, cy - 1, 2, 2, "#FFE08A"); break;
    case "bank": r(x, cx - 2, cy - 2, 4, 4, "#C9A23A"); r(x, cx - 1, cy - 1, 2, 2, "#FFE08A"); break;
    case "studio": r(x, cx - 3, cy - 2, 2, 2, "#FF6FAE"); r(x, cx, cy - 2, 2, 2, "#FFD36B"); r(x, cx - 2, cy + 1, 2, 2, "#7FD3FF"); break;
    case "citadel": r(x, cx - 2, cy - 3, 4, 5, "#4F8A62"); r(x, cx - 1, cy + 2, 2, 1, "#4F8A62"); break;
    default: r(x, cx - 2, cy - 2, 4, 4, ink);
  }
}
