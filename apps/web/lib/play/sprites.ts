/**
 * Pixel-art characters drawn from code: 16×24 px, a big head on a small body, four directions, walk cycles and poses
 * (work, talk, celebrate). Agents use their seeded look; the owner's avatar uses the look picked in the editor.
 */
import type { AgentLook } from "@aiciv/world-engine";
import type { Dir } from "./maps";

export type HairStyle = "spiky" | "short" | "buzz" | "curly" | "long" | "bun" | "afro" | "bald" | "ponytail";
export type Pose = "stand" | "walk" | "work" | "talk" | "celebrate" | "carry" | "read";

export interface Outfit {
  skin: string;
  hairStyle: HairStyle;
  hair: string;
  shirt: string;
  accent: string;
  pants: string;
  bottom: "pants" | "shorts" | "skirt";
  shoes: string;
  glasses: boolean;
  hat?: { kind: "cap" | "beanie" | "beret" | "visor"; color: string };
  headphones?: boolean;
  coat?: boolean;
  blush?: boolean;
}

export interface PlayerLook {
  skin: string; hair_style: string; hair: string; shirt: string; pants: string; shoes: string; glasses: boolean;
}

export const SPRITE_W = 16;
export const SPRITE_H = 24;
const INK = "#1D1626";

export function shade(hex: string, amt: number): string {
  const n = parseInt(hex.replace("#", ""), 16);
  const f = (v: number) => Math.max(0, Math.min(255, Math.round(amt < 0 ? v * (1 + amt) : v + (255 - v) * amt)));
  return `#${[(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => f(v).toString(16).padStart(2, "0")).join("")}`;
}

const HAIR_MAP: Record<string, HairStyle> = {
  spiky: "spiky", swoop: "short", buzz: "buzz", curly: "curly", long: "long", bob: "short", buns: "bun", afro: "afro",
  bald: "bald", ponytail: "ponytail", short: "short", bun: "bun",
};

export function outfitFromLook(l: AgentLook): Outfit {
  const hat = ["cap", "beanie", "beret", "visor"].includes(l.accessory) ? { kind: l.accessory as "cap", color: l.hatColor ?? l.top.accent } : undefined;
  return {
    skin: l.skin, hairStyle: HAIR_MAP[l.hair.style] ?? "short", hair: l.hair.color, shirt: l.top.color, accent: l.top.accent,
    pants: l.bottom.color, bottom: (l.bottom.style as Outfit["bottom"]) ?? "pants", shoes: l.shoes.startsWith("#") ? l.shoes : "#2A2230",
    glasses: l.accessory === "glasses", hat, headphones: l.accessory === "headphones" || l.accessory === "headset",
    coat: ["labcoat", "blazer", "jacket", "cardigan", "cape"].includes(l.top.style), blush: l.blush,
  };
}

export function outfitFromPlayer(l: PlayerLook): Outfit {
  return {
    skin: l.skin, hairStyle: HAIR_MAP[l.hair_style] ?? "spiky", hair: l.hair, shirt: l.shirt, accent: shade(l.shirt, -0.2),
    pants: l.pants, bottom: "pants", shoes: l.shoes, glasses: l.glasses,
  };
}

export const DEFAULT_PLAYER: PlayerLook = { skin: "#E8B48A", hair_style: "spiky", hair: "#1E1B22", shirt: "#B8BCC6", pants: "#25252E", shoes: "#F2F2F2", glasses: true };

// ---------------------------------------------------------------- pixel buffer
class Px {
  c: (string | null)[] = new Array(SPRITE_W * SPRITE_H).fill(null);
  set(x: number, y: number, col: string) {
    if (x >= 0 && y >= 0 && x < SPRITE_W && y < SPRITE_H) this.c[y * SPRITE_W + x] = col;
  }
  rect(x: number, y: number, w: number, h: number, col: string) {
    for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) this.set(i, j, col);
  }
  get(x: number, y: number) {
    return x >= 0 && y >= 0 && x < SPRITE_W && y < SPRITE_H ? this.c[y * SPRITE_W + x] : null;
  }
  outline() {
    const o = this.c.slice();
    for (let y = 0; y < SPRITE_H; y++) for (let x = 0; x < SPRITE_W; x++) {
      if (this.get(x, y)) continue;
      if (this.get(x - 1, y) || this.get(x + 1, y) || this.get(x, y - 1) || this.get(x, y + 1)) o[y * SPRITE_W + x] = INK;
    }
    this.c = o;
  }
  mirror() {
    const o = this.c.slice();
    for (let y = 0; y < SPRITE_H; y++) for (let x = 0; x < SPRITE_W; x++) o[y * SPRITE_W + x] = this.c[y * SPRITE_W + (SPRITE_W - 1 - x)];
    this.c = o;
  }
}

// ---------------------------------------------------------------- body parts
function hairDown(p: Px, o: Outfit, back: boolean) {
  const h = o.hair, hi = shade(h, 0.25), dk = shade(h, -0.3);
  const s = o.hairStyle;
  if (s === "bald") {
    if (back) p.rect(3, 4, 10, 8, o.skin);
    p.set(5, 5, shade(o.skin, 0.35));
    return;
  }
  if (s === "afro") {
    p.rect(2, 1, 12, 8, h);
    p.rect(1, 3, 14, 5, h);
    p.rect(3, 0, 10, 1, h);
    if (back) p.rect(2, 8, 12, 4, h);
    p.rect(4, 1, 4, 1, hi);
    return;
  }
  // a cap of hair over the top of the head
  p.rect(3, 3, 10, 4, h);
  p.rect(2, 4, 12, 3, h);
  p.rect(4, 2, 8, 1, h);
  p.rect(5, 3, 4, 1, hi);
  if (back) {
    p.rect(2, 4, 12, 8, h);
    p.rect(4, 5, 6, 1, hi);
    if (s === "long") p.rect(2, 12, 12, 5, h);
    if (s === "ponytail") p.rect(7, 12, 2, 4, dk);
  } else {
    // fringe
    if (s === "spiky") {
      for (const x of [3, 5, 7, 9, 11]) { p.set(x, 1, h); p.set(x + 1, 0, h); p.set(x, 2, h); p.set(x + 1, 1, h); p.set(x + 1, 2, h); }
      p.rect(2, 3, 12, 4, h);
      p.set(1, 4, h); p.set(14, 4, h); p.set(1, 5, h); p.set(14, 5, h);
      for (const x of [3, 4, 6, 9, 11, 12]) p.set(x, 7, h);
      p.rect(2, 7, 1, 3, h); p.rect(13, 7, 1, 3, h);
      p.set(4, 2, hi); p.set(8, 1, hi); p.set(10, 2, hi);
    } else if (s === "buzz") {
      p.rect(3, 6, 10, 1, h);
    } else if (s === "curly") {
      for (const x of [2, 4, 6, 8, 10, 12]) { p.set(x, 2, h); p.set(x + 1, 2, h); }
      p.rect(2, 6, 12, 1, h);
      for (const x of [3, 6, 9, 12]) p.set(x, 7, h);
      p.set(5, 2, hi); p.set(9, 2, hi);
    } else {
      p.rect(3, 6, 10, 1, h);
      p.rect(3, 7, 3, 1, h);
      p.rect(10, 7, 3, 1, h);
      p.rect(2, 7, 1, 3, h); p.rect(13, 7, 1, 3, h);
      if (s === "long") { p.rect(1, 7, 2, 10, h); p.rect(13, 7, 2, 10, h); p.rect(1, 15, 2, 2, dk); p.rect(13, 15, 2, 2, dk); }
      if (s === "ponytail") { p.rect(13, 8, 2, 5, dk); }
      if (s === "bun") { p.rect(6, 0, 4, 2, h); p.set(7, 0, hi); }
    }
  }
}

function hat(p: Px, o: Outfit, dir: Dir) {
  if (!o.hat) return;
  const c = o.hat.color, dk = shade(c, -0.3);
  if (o.hat.kind === "cap") {
    p.rect(3, 2, 10, 4, c); p.rect(4, 1, 8, 1, c); p.set(7, 1, shade(c, 0.3));
    if (dir === "down") p.rect(2, 6, 12, 1, dk);
    else if (dir === "left") p.rect(0, 6, 7, 1, dk);
    else if (dir === "right") p.rect(9, 6, 7, 1, dk);
  } else if (o.hat.kind === "beanie") {
    p.rect(3, 1, 10, 5, c); p.rect(5, 0, 6, 1, c); p.rect(2, 5, 12, 2, dk); p.set(8, 0, shade(c, 0.4));
  } else if (o.hat.kind === "beret") {
    p.rect(2, 2, 11, 3, c); p.rect(4, 1, 7, 1, c); p.set(9, 0, dk);
  } else {
    p.rect(3, 5, 10, 1, c);
    if (dir === "down") p.rect(4, 6, 8, 1, dk);
  }
}

function face(p: Px, o: Outfit, pose: Pose, frame: number, side: boolean) {
  const eye = INK;
  if (side) {
    p.rect(5, 9, 1, 2, eye);
    if (o.glasses) { const F = "#2B2433"; p.rect(3, 8, 4, 1, F); p.rect(3, 11, 4, 1, F); p.rect(3, 9, 1, 2, F); p.rect(4, 9, 2, 2, "#CFE8FF"); p.rect(5, 9, 1, 2, eye); p.rect(7, 9, 3, 1, F); }
    if (o.blush) p.set(6, 11, "#FF8FA3");
    const open = pose === "talk" && frame % 2 === 1;
    p.rect(4, 12, 2, open ? 2 : 1, open ? "#7A1F35" : shade(o.skin, -0.45));
    p.set(3, 10, o.skin); // nose
    return;
  }
  p.rect(5, 9, 1, 2, eye);
  p.rect(10, 9, 1, 2, eye);
  p.set(5, 9, pose === "celebrate" ? eye : eye);
  if (o.glasses) {
    const F = "#2B2433", L = "#CFE8FF";
    for (const lx of [3, 8]) {
      p.rect(lx, 8, 5, 1, F); p.rect(lx, 11, 5, 1, F); p.rect(lx, 9, 1, 2, F); p.rect(lx + 4, 9, 1, 2, F);
      p.rect(lx + 1, 9, 3, 2, L);
    }
    p.rect(5, 9, 1, 2, eye); p.rect(10, 9, 1, 2, eye);
  }
  if (o.blush) { p.set(3, 11, "#FF8FA3"); p.set(12, 11, "#FF8FA3"); }
  const open = (pose === "talk" && frame % 2 === 1) || pose === "celebrate";
  if (open) { p.rect(7, 12, 2, 1, "#7A1F35"); p.set(7, 13, "#7A1F35"); p.set(8, 13, "#7A1F35"); }
  else { p.rect(7, 12, 2, 1, shade(o.skin, -0.45)); }
}

function headphones(p: Px, o: Outfit, dir: Dir) {
  if (!o.headphones) return;
  p.rect(3, 2, 10, 1, "#2A2A36");
  if (dir === "down" || dir === "up") { p.rect(1, 8, 2, 4, o.accent); p.rect(13, 8, 2, 4, o.accent); }
  else p.rect(dir === "left" ? 9 : 6, 8, 2, 4, o.accent);
}

function body(p: Px, o: Outfit, dir: Dir, pose: Pose, frame: number) {
  const shirt = o.shirt, sDark = shade(shirt, -0.22), skin = o.skin;
  const step = pose === "walk" || pose === "carry" ? frame % 4 : 0; // 0,2 stand · 1 left foot · 3 right foot
  const side = dir === "left" || dir === "right";
  // torso
  p.rect(5, 14, 6, 5, shirt);
  p.rect(5, 18, 6, 1, sDark);
  p.rect(6, 14, 4, 1, shade(shirt, 0.15));
  if (o.coat && !side) { p.rect(7, 14, 2, 4, o.accent); }
  if (o.coat && side) { p.rect(5, 14, 1, 5, o.accent); }
  // arms
  const swing = step === 1 ? 1 : step === 3 ? -1 : 0;
  if (pose === "celebrate") {
    const up = frame % 2 ? 1 : 0;
    p.rect(3, 9 + up, 2, 5, shirt); p.rect(11, 9 + up, 2, 5, shirt);
    p.rect(3, 8 + up, 2, 1, skin); p.rect(11, 8 + up, 2, 1, skin);
  } else if (pose === "carry") {
    p.rect(4, 14, 1, 3, shirt); p.rect(11, 14, 1, 3, shirt);
    if (!side) { p.rect(4, 15, 8, 4, "#C98B4A"); p.rect(4, 15, 8, 1, "#E2A866"); p.rect(7, 15, 2, 4, "#8E5A2C"); }
    else { p.rect(dir === "left" ? 2 : 10, 15, 4, 4, "#C98B4A"); p.rect(dir === "left" ? 2 : 10, 15, 4, 1, "#E2A866"); }
  } else if (side) {
    const ax = 7 + swing;
    p.rect(ax, 14, 2, 4, sDark);
    p.rect(ax, 18, 2, 1, skin);
    if (pose === "read") p.rect(dir === "left" ? 3 : 10, 15, 3, 3, o.accent);
  } else {
    const typing = pose === "work" ? (frame % 2 ? -1 : 0) : 0;
    p.rect(4, 14, 1, 4 + (swing > 0 ? 0 : 0), shirt);
    p.rect(11, 14, 1, 4, shirt);
    p.set(4, 18 + typing + (swing < 0 ? -1 : 0), skin);
    p.set(11, 18 - typing + (swing > 0 ? -1 : 0), skin);
    p.set(3, 15, shirt); p.set(12, 15, shirt);
    if (pose === "read") { p.rect(5, 16, 6, 3, o.accent); p.rect(7, 16, 2, 3, shade(o.accent, 0.4)); }
  }
  // legs
  const pc = o.pants, pDark = shade(pc, -0.25);
  const legTop = 19;
  if (o.bottom === "skirt") {
    p.rect(4, 18, 8, 3, pc); p.rect(4, 20, 8, 1, pDark);
  }
  const legColor = o.bottom === "pants" ? pc : skin;
  if (side) {
    const f = step === 1 ? 1 : step === 3 ? -1 : 0;
    p.rect(6 - f, legTop, 2, 3, o.bottom === "shorts" && true ? (legTop < 20 ? pc : legColor) : legColor);
    p.rect(8 + f, legTop, 2, 3, o.bottom === "pants" ? pDark : legColor);
    if (o.bottom === "shorts") { p.rect(5, legTop, 6, 1, pc); }
    p.rect(5 - f, legTop + 3, 3, 1, o.shoes); p.rect(8 + f, legTop + 3, 3, 1, shade(o.shoes, -0.2));
  } else {
    const lUp = step === 3 ? 1 : 0, rUp = step === 1 ? 1 : 0;
    p.rect(5, legTop, 3, 3 - lUp, legColor);
    p.rect(8, legTop, 3, 3 - rUp, legColor);
    if (o.bottom !== "skirt") p.rect(5, legTop, 6, 1, pc);
    if (o.bottom === "pants") p.rect(7, legTop + 1, 2, 2, pDark);
    p.rect(4, legTop + 3 - lUp, 4, 1, o.shoes);
    p.rect(8, legTop + 3 - rUp, 4, 1, o.shoes);
    p.set(4, legTop + 3 - lUp, shade(o.shoes, -0.25));
    p.set(11, legTop + 3 - rUp, shade(o.shoes, -0.25));
  }
}

function head(p: Px, o: Outfit, dir: Dir, pose: Pose, frame: number) {
  const skin = o.skin, sd = shade(skin, -0.18);
  p.rect(3, 4, 10, 10, skin);
  p.rect(2, 6, 1, 6, skin); p.rect(13, 6, 1, 6, skin);
  p.rect(3, 13, 10, 1, sd);
  if (dir === "up") {
    hairDown(p, o, true);
  } else if (dir === "down") {
    face(p, o, pose, frame, false);
    hairDown(p, o, false);
  } else {
    // drawn facing left; "right" mirrors the finished sprite
    face(p, o, pose, frame, true);
    const h = o.hair;
    if (o.hairStyle !== "bald") {
      const hi = shade(h, 0.25);
      if (o.hairStyle === "afro") { p.rect(2, 1, 13, 7, h); p.rect(3, 0, 10, 1, h); }
      else {
        p.rect(3, 3, 11, 4, h); p.rect(4, 2, 9, 1, h); p.rect(2, 5, 2, 2, h); p.rect(5, 3, 4, 1, hi);
        if (o.hairStyle === "spiky") { for (const x of [4, 7, 10, 13]) { p.set(x, 1, h); p.set(x + 1, 0, h); p.set(x + 1, 1, h); } p.set(14, 3, h); p.set(15, 4, h); }
        if (o.hairStyle === "curly") for (const x of [3, 6, 9, 12]) p.rect(x, 1, 2, 2, h);
        if (o.hairStyle === "bun") p.rect(9, 0, 4, 3, h);
        if (o.hairStyle !== "buzz") p.rect(3, 7, 2, 1, h);
      }
      p.rect(8, 4, 6, 8, h);
      p.rect(9, 12, 4, 1, h);
      if (o.hairStyle === "long") p.rect(9, 12, 5, 5, h);
      if (o.hairStyle === "ponytail") p.rect(13, 7, 2, 6, shade(h, -0.3));
      if (o.hairStyle === "afro") p.rect(7, 2, 8, 10, h);
    }
  }
  headphones(p, o, dir);
  hat(p, o, dir);
}

/** Paints one frame. Callers cache the result; frames are tiny. */
export function paintFrame(o: Outfit, dir: Dir, pose: Pose, frame: number): (string | null)[] {
  const p = new Px();
  const d: Dir = dir === "right" ? "left" : dir;
  const bob = (pose === "walk" || pose === "carry") && frame % 2 === 1 ? -1 : pose === "celebrate" && frame % 2 === 1 ? -2 : 0;
  body(p, o, d, pose, frame);
  head(p, o, d, pose, frame);
  if (bob) {
    const c = p.c.slice();
    p.c.fill(null);
    for (let y = 0; y < SPRITE_H; y++) for (let x = 0; x < SPRITE_W; x++) {
      const v = c[y * SPRITE_W + x];
      if (v) p.set(x, y + bob, v);
    }
  }
  p.outline();
  if (dir === "right") p.mirror();
  return p.c;
}

const cache = new Map<string, HTMLCanvasElement>();

export function outfitKey(o: Outfit): string {
  return [o.skin, o.hairStyle, o.hair, o.shirt, o.accent, o.pants, o.bottom, o.shoes, o.glasses, o.hat?.kind, o.hat?.color, o.headphones, o.coat, o.blush].join("|");
}

export function frameCanvas(o: Outfit, dir: Dir, pose: Pose, frame: number): HTMLCanvasElement {
  const k = `${outfitKey(o)}#${dir}#${pose}#${frame}`;
  let c = cache.get(k);
  if (c) return c;
  c = document.createElement("canvas");
  c.width = SPRITE_W;
  c.height = SPRITE_H;
  const ctx = c.getContext("2d")!;
  const px = paintFrame(o, dir, pose, frame);
  for (let i = 0; i < px.length; i++) {
    const v = px[i];
    if (!v) continue;
    ctx.fillStyle = v;
    ctx.fillRect(i % SPRITE_W, Math.floor(i / SPRITE_W), 1, 1);
  }
  cache.set(k, c);
  return c;
}
