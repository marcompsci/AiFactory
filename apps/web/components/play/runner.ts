"use client";

/**
 * The game loop: input, movement, collision, doors, proximity and drawing. World data (agents, packages) is read from
 * the realtime store every frame, so what you see follows backend events; this file only decides how it looks.
 */
import { useStore } from "@/lib/store";
import { buildingSprite, paintGroundLayer, propSprites, type Sprite } from "@/lib/play/art";
import {
  animFor, facingFor, findPath, moveBody, nearest, packagePoint, placeAgents, statusLabel, WALK_SPEED,
  type Anim, type PackagePoint, type Placed, type Vec,
} from "@/lib/play/engine";
import { buildInterior, buildTown, isSolid, TILE, type Dir, type GameMap } from "@/lib/play/maps";
import { frameCanvas, outfitFromLook, outfitFromPlayer, SPRITE_H, SPRITE_W, type Outfit, type Pose } from "@/lib/play/sprites";
import { usePlay } from "@/lib/play/state";

interface Loaded { map: GameMap; ground: HTMLCanvasElement; sprites: Sprite[] }

/** Shared with the HUD (minimap, saving). */
export const live = { mapId: "town", x: 24.5, y: 20.5, facing: "down" as Dir, moved: false, ready: false };

const POSE: Record<Anim, Pose> = {
  IDLE: "stand", WALKING: "walk", TALKING: "talk", WORKING: "work", RESEARCHING: "read", CODING: "work", TESTING: "work",
  WAITING: "stand", DELIVERING: "carry", CELEBRATING: "celebrate",
};
const FRAME_MS: Record<Pose, number> = { stand: 700, walk: 140, carry: 140, work: 260, read: 900, talk: 200, celebrate: 260 };

const ICON: Partial<Record<Anim, string>> = { WORKING: "gear", CODING: "code", RESEARCHING: "lens", TESTING: "flask", WAITING: "wait", DELIVERING: "box", CELEBRATING: "star" };
const PKG_COLOR: Record<string, string> = {
  research_brief: "#5C7FD6", product_proposal: "#7A5CD6", code_artifact: "#C2553A", test_report: "#4F8A62", release_package: "#C9A23A",
  revision_request: "#E2465E", bill_reminder: "#F28C38", payment_proposal: "#F28C38", purchase_request: "#F28C38", tax_review_package: "#C9A23A",
};

export class Runner {
  private ctx: CanvasRenderingContext2D;
  private maps = new Map<string, Loaded>();
  private raf = 0;
  private last = 0;
  private walkT = 0;
  private moving = false;
  private path: Vec[] = [];
  private pathGoal: { kind: "npc" | "object"; id: string } | null = null;
  private keys = new Set<string>();
  private placed: Placed[] = [];
  private packages: PackagePoint[] = [];
  private fade: { at: number; to?: () => void; done?: boolean } | null = null;
  private cam = { x: 0, y: 0, s: 3 };
  private unsub: (() => void)[] = [];
  private down: { x: number; y: number; t: number } | null = null;
  private outfitCache: { key: string; o: Outfit } | null = null;
  private agentOutfits = new Map<string, Outfit>();

  constructor(private canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext("2d")!;
    this.load("town");
    const t = this.maps.get("town")!.map;
    live.x = t.spawn.x + 0.5; live.y = t.spawn.y + 0.5; live.facing = t.spawn.facing;
    const onKey = (e: KeyboardEvent, on: boolean) => {
      if ((e.target as HTMLElement)?.closest?.("input,textarea,select")) return;
      const k = e.key.toLowerCase();
      if (["arrowup", "arrowdown", "arrowleft", "arrowright", "w", "a", "s", "d"].includes(k)) {
        e.preventDefault();
        if (on) this.keys.add(k); else this.keys.delete(k);
      }
      if (on && (k === "e" || k === " " || k === "enter")) { e.preventDefault(); this.interact(); }
      if (on && k === "j") usePlay.getState().openPanel(usePlay.getState().panel === "journal" ? null : "journal");
      if (on && k === "escape") { usePlay.getState().talk(null); usePlay.getState().openPanel(null); usePlay.getState().selectPackage(null); }
    };
    const kd = (e: KeyboardEvent) => onKey(e, true), ku = (e: KeyboardEvent) => onKey(e, false);
    window.addEventListener("keydown", kd);
    window.addEventListener("keyup", ku);
    const blur = () => this.keys.clear();
    window.addEventListener("blur", blur);
    const pd = (e: PointerEvent) => { this.down = { x: e.clientX, y: e.clientY, t: performance.now() }; };
    const pu = (e: PointerEvent) => {
      const d = this.down;
      this.down = null;
      if (d && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 12 && performance.now() - d.t < 400) this.tap(e.clientX, e.clientY);
    };
    canvas.addEventListener("pointerdown", pd);
    canvas.addEventListener("pointerup", pu);
    let seq = usePlay.getState().interactSeq;
    this.unsub.push(usePlay.subscribe((s) => { if (s.interactSeq !== seq) { seq = s.interactSeq; this.interact(); } }));
    this.unsub.push(() => { window.removeEventListener("keydown", kd); window.removeEventListener("keyup", ku); window.removeEventListener("blur", blur);
      canvas.removeEventListener("pointerdown", pd); canvas.removeEventListener("pointerup", pu); });
    if (process.env.NODE_ENV !== "production") {
      // development-only hooks for automated screenshots and tests
      (window as unknown as Record<string, unknown>).__play = { place: (m: string, x: number, y: number, f: Dir = "down") => this.place(m, x, y, f), enter: (id: string) => this.enter(id) };
    }
    this.raf = requestAnimationFrame(this.loop);
  }

  stop() {
    cancelAnimationFrame(this.raf);
    this.unsub.forEach((u) => u());
  }

  /** Puts the player somewhere (restored state). Falls back to the spawn point if the spot is blocked. */
  place(mapId: string, x: number, y: number, facing: Dir) {
    const l = this.load(mapId);
    if (!l) return;
    const ok = !isSolid(l.map, Math.floor(x), Math.floor(y));
    live.mapId = mapId;
    usePlay.getState().setMap(mapId);
    live.x = ok ? x : l.map.spawn.x + 0.5;
    live.y = ok ? y : l.map.spawn.y + 0.5;
    live.facing = facing;
    live.ready = true;
  }

  private load(id: string): Loaded | null {
    if (this.maps.has(id)) return this.maps.get(id)!;
    const map = id === "town" ? buildTown() : buildInterior(id);
    if (!map) return null;
    const sprites = [...propSprites(map), ...map.buildings.map(buildingSprite)];
    const l = { map, ground: paintGroundLayer(map), sprites };
    this.maps.set(id, l);
    return l;
  }

  private get here(): Loaded {
    return this.maps.get(live.mapId) ?? this.maps.get("town")!;
  }

  private go(to: string, at: { x: number; y: number; facing: Dir }) {
    if (this.fade) return;
    this.fade = {
      at: performance.now(),
      to: () => {
        this.load(to);
        live.mapId = to;
        live.x = at.x + 0.5; live.y = at.y + 0.5; live.facing = at.facing;
        live.moved = true;
        this.path = [];
        this.pathGoal = null;
        usePlay.getState().setMap(to);
        usePlay.getState().talk(null);
      },
    };
  }

  // ---------------------------------------------------------------- input
  private tap(cx: number, cy: number) {
    const st = usePlay.getState();
    if (st.talkingTo || st.panel) return;
    const rect = this.canvas.getBoundingClientRect();
    const dpr = this.canvas.width / rect.width;
    const wx = ((cx - rect.left) * dpr - this.cam.x) / this.cam.s / TILE;
    const wy = ((cy - rect.top) * dpr - this.cam.y) / this.cam.s / TILE;
    const pkg = nearest({ x: wx, y: wy }, this.packages, 0.7);
    if (pkg) { st.selectPackage(pkg.id); return; }
    const npc = nearest({ x: wx, y: wy - 0.5 }, this.placed.map((p) => ({ ...p, id: p.agent.id })), 0.8);
    const { map } = this.here;
    if (npc) {
      if (Math.hypot(npc.x - live.x, npc.y - live.y) < 2.1) { this.talkTo(npc.agent.id); return; }
      this.walkTo({ x: npc.x, y: npc.y + 1 }, { kind: "npc", id: npc.agent.id });
      return;
    }
    const obj = map.interactables.find((o) => Math.floor(wx) === o.x && Math.floor(wy) === o.y);
    if (obj && obj.action !== "enter" && obj.action !== "exit") {
      if (Math.hypot(obj.x + 0.5 - live.x, obj.y + 0.5 - live.y) < 1.6) { this.useObject(obj.id); return; }
      this.walkTo({ x: obj.x + 0.5, y: obj.y + 1.5 }, { kind: "object", id: obj.id });
      return;
    }
    this.walkTo({ x: wx, y: wy }, null);
  }

  private walkTo(to: Vec, goal: Runner["pathGoal"]) {
    const { map } = this.here;
    const blocked = new Set(this.placed.map((p) => Math.floor(p.y) * map.w + Math.floor(p.x)));
    this.path = findPath(map, { x: live.x, y: live.y }, to, blocked);
    this.pathGoal = this.path.length ? goal : null;
  }

  private interact() {
    const n = usePlay.getState().nearby;
    if (!n) return;
    if (n.kind === "npc") this.talkTo(n.id);
    else this.useObject(n.id);
  }

  private talkTo(agentId: string) {
    this.path = [];
    this.pathGoal = null;
    usePlay.getState().talk(agentId);
  }

  private useObject(id: string) {
    const obj = this.here.map.interactables.find((o) => o.id === id);
    if (!obj) return;
    const st = usePlay.getState();
    if (obj.action === "approvals") st.openPanel("approvals");
    else if (obj.action === "journal") st.openPanel("journal");
    else if (obj.action === "findings") st.openPanel("findings");
    else if (obj.action === "closed") {
      const b = this.here.map.buildings.find((b) => b.id === obj.target);
      st.say(b?.note ?? "Packages for the Claude Code, GitHub and Codex factories leave town here.");
    } else if (obj.action === "enter" && obj.target) this.enter(obj.target);
  }

  private enter(id: string) {
    const inner = this.load(id);
    if (!inner) return;
    this.go(id, inner.map.spawn);
  }

  // ---------------------------------------------------------------- update
  private loop = (t: number) => {
    const dt = Math.min(0.05, (t - (this.last || t)) / 1000);
    this.last = t;
    this.update(dt, t);
    this.draw(t);
    this.raf = requestAnimationFrame(this.loop);
  };

  private update(dt: number, now: number) {
    const st = usePlay.getState();
    const { map } = this.here;
    const world = useStore.getState().world;
    const agents = Object.values(world.agents);
    this.placed = placeAgents(map, agents, now, st.talkingTo, this.maps.get("town")!.map);
    const serverNow = Date.now() + useStore.getState().clockOffset;
    this.packages = map.id === "town"
      ? Object.values(world.packages).map((p) => packagePoint(map, p, serverNow)).filter((p): p is PackagePoint => !!p)
      : [];

    if (this.fade) {
      const k = (now - this.fade.at) / 260;
      if (k >= 1 && !this.fade.done) { this.fade.done = true; this.fade.to?.(); this.fade.at = now; }
      else if (this.fade.done && k >= 1) this.fade = null;
      return;
    }
    let vx = 0, vy = 0;
    if (!st.talkingTo && !st.panel) {
      if (this.keys.has("arrowleft") || this.keys.has("a")) vx -= 1;
      if (this.keys.has("arrowright") || this.keys.has("d")) vx += 1;
      if (this.keys.has("arrowup") || this.keys.has("w")) vy -= 1;
      if (this.keys.has("arrowdown") || this.keys.has("s")) vy += 1;
      if (!vx && !vy && (Math.abs(st.stick.x) > 0.15 || Math.abs(st.stick.y) > 0.15)) { vx = st.stick.x; vy = st.stick.y; }
    }
    if (vx || vy) { this.path = []; this.pathGoal = null; }
    else if (this.path.length) {
      const n = this.path[0];
      const dx = n.x - live.x, dy = n.y - live.y, d = Math.hypot(dx, dy);
      if (d < 0.12) this.path.shift();
      else { vx = dx / d; vy = dy / d; }
    }
    const len = Math.hypot(vx, vy);
    this.moving = len > 0.01;
    if (this.moving) {
      const k = (Math.min(1, len) * WALK_SPEED * dt) / len;
      const before = { x: live.x, y: live.y };
      const after = moveBody(map, before, vx * k, vy * k, this.placed);
      live.facing = facingFor(vx, vy, live.facing);
      if (Math.hypot(after.x - before.x, after.y - before.y) < 1e-4 && this.path.length) this.path = []; // stuck: give up
      live.x = after.x; live.y = after.y;
      live.moved = true;
      this.walkT += dt;
    }
    // doors
    const tx = Math.floor(live.x), ty = Math.floor(live.y);
    if (map.id === "town") {
      const b = map.buildings.find((b) => b.enterable && b.door.x === tx && b.door.y === ty);
      if (b) this.enter(b.id);
    } else {
      const ex = map.exits.find((e) => e.x === tx && e.y === ty);
      if (ex) this.go(ex.to, ex.at);
    }
    // arrived next to what we walked to
    if (this.pathGoal && !this.path.length) {
      const g = this.pathGoal;
      this.pathGoal = null;
      if (g.kind === "npc" && this.placed.some((p) => p.agent.id === g.id)) this.talkTo(g.id);
      if (g.kind === "object") this.useObject(g.id);
    }
    // what's close enough to talk to or use
    const npc = nearest({ x: live.x, y: live.y }, this.placed.map((p) => ({ x: p.x, y: p.y, id: p.agent.id, name: p.agent.name })), 2.1);
    if (npc) st.setNearby({ kind: "npc", id: npc.id, label: `Talk to ${npc.name}` });
    else {
      const obj = nearest({ x: live.x, y: live.y },
        map.interactables.filter((o) => o.action !== "enter" && o.action !== "exit").map((o) => ({ ...o, x: o.x + 0.5, y: o.y + 0.5 })), 1.35);
      st.setNearby(obj ? { kind: "object", id: obj.id, label: obj.label, object: obj } : null);
    }
    // face the person you're talking to
    if (st.talkingTo) {
      const p = this.placed.find((p) => p.agent.id === st.talkingTo);
      if (p) live.facing = facingFor(p.x - live.x, p.y - live.y, live.facing);
    }
  }

  // ---------------------------------------------------------------- drawing
  private playerOutfit(): Outfit {
    const { look } = usePlay.getState();
    const key = JSON.stringify(look);
    if (this.outfitCache?.key !== key) this.outfitCache = { key, o: outfitFromPlayer(look) };
    return this.outfitCache.o;
  }

  private agentOutfit(p: Placed): Outfit {
    let o = this.agentOutfits.get(p.agent.id);
    if (!o) {
      o = p.agent.look ? outfitFromLook(p.agent.look) : outfitFromPlayer({ skin: "#E0AC69", hair_style: "short", hair: "#3A2A20", shirt: p.agent.color, pants: "#2D3346", shoes: "#2A2230", glasses: false });
      this.agentOutfits.set(p.agent.id, o);
    }
    return o;
  }

  private draw(now: number) {
    const c = this.canvas, ctx = this.ctx;
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    const W = Math.round(c.clientWidth * dpr), H = Math.round(c.clientHeight * dpr);
    if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
    ctx.imageSmoothingEnabled = false;
    const { map, ground, sprites } = this.here;
    const tilesTall = H > W ? 15 : 17;
    const s = Math.max(2, Math.round(H / (TILE * tilesTall)));
    const viewW = W / s, viewH = H / s;
    const mapW = map.w * TILE, mapH = map.h * TILE;
    let camX = live.x * TILE - viewW / 2, camY = live.y * TILE - viewH / 2;
    camX = mapW <= viewW ? (mapW - viewW) / 2 : Math.max(0, Math.min(mapW - viewW, camX));
    camY = mapH <= viewH ? (mapH - viewH) / 2 : Math.max(0, Math.min(mapH - viewH, camY));
    const ox = Math.round(-camX * s), oy = Math.round(-camY * s);
    this.cam = { x: ox, y: oy, s };

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = map.id === "town" ? "#2E6B35" : "#120E1C";
    ctx.fillRect(0, 0, W, H);
    ctx.setTransform(s, 0, 0, s, ox, oy);
    ctx.drawImage(ground, 0, 0);

    // conveyor belts (town)
    if (map.belt.size) this.drawBelts(ctx, map, now, camX, camY, viewW, viewH);

    // depth-sorted things
    type D = { y: number; draw: () => void };
    const list: D[] = [];
    const visible = (x0: number, y0: number, w: number, h: number) => x0 + w >= camX - 8 && y0 + h >= camY - 40 && x0 <= camX + viewW + 8 && y0 <= camY + viewH + 40;
    for (const sp of sprites) if (visible(sp.ox, sp.oy, sp.canvas.width, sp.canvas.height)) list.push({ y: sp.baseY, draw: () => ctx.drawImage(sp.canvas, sp.ox, sp.oy) });
    for (const pk of this.packages) list.push({ y: pk.y * TILE + 4, draw: () => this.drawPackage(ctx, pk, now) });
    for (const p of this.placed) {
      const anim = p.anim;
      const pose = POSE[anim];
      const frame = Math.floor(now / FRAME_MS[pose]) % (pose === "walk" || pose === "carry" ? 4 : 2);
      let facing = p.facing;
      if (anim === "TALKING") facing = facingFor(live.x - p.x, live.y - p.y, "down");
      const img = frameCanvas(this.agentOutfit(p), facing, pose, frame);
      const px = Math.round(p.x * TILE - SPRITE_W / 2), py = Math.round(p.y * TILE - SPRITE_H + 2);
      list.push({ y: p.y * TILE, draw: () => { this.shadow(ctx, p.x, p.y); ctx.drawImage(img, px, py); } });
    }
    {
      const pose: Pose = this.moving ? "walk" : usePlay.getState().talkingTo ? "stand" : "stand";
      const frame = this.moving ? Math.floor(this.walkT / 0.13) % 4 : 0;
      const img = frameCanvas(this.playerOutfit(), live.facing, pose, frame);
      const px = Math.round(live.x * TILE - SPRITE_W / 2), py = Math.round(live.y * TILE - SPRITE_H + 2);
      list.push({ y: live.y * TILE, draw: () => { this.shadow(ctx, live.x, live.y); ctx.drawImage(img, px, py); } });
    }
    list.sort((a, b) => a.y - b.y);
    for (const d of list) d.draw();

    // tap-to-move target
    if (this.path.length) {
      const g = this.path[this.path.length - 1];
      const pulse = 1 + Math.sin(now / 120) * 0.5;
      ctx.strokeStyle = "rgba(255,255,255,0.8)";
      ctx.lineWidth = 1;
      ctx.strokeRect(g.x * TILE - 4 - pulse, g.y * TILE - 3 - pulse / 2, 8 + pulse * 2, 6 + pulse);
    }

    // screen-space labels
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const toScreen = (wx: number, wy: number) => ({ x: wx * s + ox, y: wy * s + oy });
    const font = Math.max(11, Math.round(s * 3.6));
    ctx.font = `600 ${font}px "Pixelify Sans", ui-sans-serif, system-ui`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    if (map.id === "town") {
      for (const b of map.buildings) {
        const p = toScreen((b.x + b.w / 2) * TILE, b.y * TILE - (b.style === "spire" ? 30 : b.style === "tower" ? 24 : b.style === "dome" ? -6 : 12));
        if (p.x < -200 || p.x > W + 200 || p.y < -50 || p.y > H + 50) continue;
        this.pill(ctx, p.x, p.y, b.name, font, b.enterable ? "rgba(20,16,36,0.82)" : "rgba(20,16,36,0.6)", b.enterable ? "#FFFFFF" : "rgba(255,255,255,0.75)");
      }
    }
    const near = usePlay.getState().nearby;
    for (const p of this.placed) {
      const head = toScreen(p.x * TILE, (p.y * TILE) - SPRITE_H - 3);
      this.pill(ctx, head.x, head.y, p.agent.name, Math.round(font * 0.85), "rgba(20,16,36,0.78)", "#FFFFFF");
      const icon = p.agent.execState === "FAILED" ? "fail" : p.agent.execState === "WAITING_FOR_APPROVAL" ? "alert" : ICON[p.anim];
      if (icon) this.bubble(ctx, head.x + font * 2.3, head.y - font * 0.9, icon, s, now);
      if (near?.kind === "npc" && near.id === p.agent.id && !usePlay.getState().talkingTo) {
        const status = statusLabel(p.agent);
        this.pill(ctx, head.x, head.y - font * 1.5, status, Math.round(font * 0.75), "rgba(91,242,165,0.92)", "#0B1A12");
      }
    }
    if (near?.kind === "object" && near.object) {
      const p = toScreen((near.object.x + 0.5) * TILE, near.object.y * TILE - 2 + Math.sin(now / 200) * 2);
      this.arrow(ctx, p.x, p.y, s);
    }

    // fade between maps
    if (this.fade) {
      const k = Math.min(1, (now - this.fade.at) / 260);
      ctx.fillStyle = `rgba(7,6,14,${this.fade.done ? 1 - k : k})`;
      ctx.fillRect(0, 0, W, H);
    }
  }

  private drawBelts(ctx: CanvasRenderingContext2D, map: GameMap, now: number, camX: number, camY: number, vw: number, vh: number) {
    const x0 = Math.max(0, Math.floor(camX / TILE) - 1), y0 = Math.max(0, Math.floor(camY / TILE) - 1);
    const x1 = Math.min(map.w - 1, Math.ceil((camX + vw) / TILE) + 1), y1 = Math.min(map.h - 1, Math.ceil((camY + vh) / TILE) + 1);
    const shift = Math.floor(now / 90) % 4;
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      const i = y * map.w + x;
      if (!map.belt.has(i)) continue;
      const h = map.belt.has(i - 1) || map.belt.has(i + 1);
      const v = map.belt.has(i - map.w) || map.belt.has(i + map.w);
      const px = x * TILE, py = y * TILE;
      ctx.fillStyle = "#3A3448";
      if (h) ctx.fillRect(px, py + 4, TILE, 8);
      if (v) ctx.fillRect(px + 4, py, 8, TILE);
      ctx.fillStyle = "#5A5470";
      if (h) for (let k = -1; k < 5; k++) ctx.fillRect(px + k * 4 + shift, py + 5, 2, 6);
      if (v) for (let k = -1; k < 5; k++) ctx.fillRect(px + 5, py + k * 4 + shift, 6, 2);
      ctx.fillStyle = "#24202E";
      if (h) { ctx.fillRect(px, py + 3, TILE, 1); ctx.fillRect(px, py + 12, TILE, 1); }
      if (v) { ctx.fillRect(px + 3, py, 1, TILE); ctx.fillRect(px + 12, py, 1, TILE); }
    }
    for (const [id, d] of Object.entries(map.docks)) {
      const px = d.x * TILE, py = d.y * TILE;
      ctx.fillStyle = "#24202E"; ctx.fillRect(px + 1, py + 1, 14, 14);
      ctx.fillStyle = id === "logistics-depot" ? "#F4D58D" : "#32D8FF"; ctx.fillRect(px + 3, py + 3, 10, 10);
      ctx.fillStyle = "#24202E"; ctx.fillRect(px + 5, py + 5, 6, 6);
    }
  }

  private drawPackage(ctx: CanvasRenderingContext2D, pk: PackagePoint, now: number) {
    const col = PKG_COLOR[pk.pkg.type] ?? "#C98B4A";
    const bob = pk.status === "IN_TRANSIT" ? Math.round(Math.sin(now / 160 + pk.x) * 0.6) : 0;
    const x = Math.round(pk.x * TILE - 5), y = Math.round(pk.y * TILE - 8 + bob);
    ctx.fillStyle = "#1D1626"; ctx.fillRect(x - 1, y - 1, 12, 11);
    ctx.fillStyle = col; ctx.fillRect(x, y, 10, 9);
    ctx.fillStyle = "rgba(255,255,255,0.35)"; ctx.fillRect(x, y, 10, 2);
    ctx.fillStyle = "#F4D58D"; ctx.fillRect(x + 4, y, 2, 9);
    if (usePlay.getState().packageId === pk.id) { ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 1; ctx.strokeRect(x - 2.5, y - 2.5, 15, 14); }
    if (pk.status === "ARRIVED") { ctx.fillStyle = "#5BF2A5"; ctx.fillRect(x + 8, y - 4, 4, 4); }
    if (pk.status === "DELIVERY_FAILED") { ctx.fillStyle = "#FF6178"; ctx.fillRect(x + 8, y - 4, 4, 4); }
  }

  private shadow(ctx: CanvasRenderingContext2D, x: number, y: number) {
    ctx.fillStyle = "rgba(0,0,0,0.22)";
    ctx.fillRect(Math.round(x * TILE - 5), Math.round(y * TILE), 10, 2);
    ctx.fillRect(Math.round(x * TILE - 4), Math.round(y * TILE - 1), 8, 4);
  }

  private pill(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, font: number, bg: string, fg: string) {
    ctx.font = `600 ${font}px "Pixelify Sans", ui-sans-serif, system-ui`;
    const w = ctx.measureText(text).width + font * 0.9, h = font * 1.45;
    ctx.fillStyle = bg;
    const r = h / 2.5;
    ctx.beginPath();
    ctx.roundRect(Math.round(x - w / 2), Math.round(y - h / 2), Math.round(w), Math.round(h), r);
    ctx.fill();
    ctx.fillStyle = fg;
    ctx.fillText(text, Math.round(x), Math.round(y + 1));
  }

  private arrow(ctx: CanvasRenderingContext2D, x: number, y: number, s: number) {
    ctx.fillStyle = "#FFFFFF";
    ctx.strokeStyle = "#1D1626";
    ctx.lineWidth = Math.max(1, s / 2);
    ctx.beginPath();
    ctx.moveTo(x - s * 3, y - s * 4); ctx.lineTo(x + s * 3, y - s * 4); ctx.lineTo(x, y);
    ctx.closePath(); ctx.fill(); ctx.stroke();
  }

  private bubble(ctx: CanvasRenderingContext2D, x: number, y: number, icon: string, s: number, now: number) {
    const u = Math.max(2, Math.round(s * 0.9));
    const w = 11 * u, h = 10 * u;
    const bx = Math.round(x - w / 2), by = Math.round(y - h / 2 + Math.sin(now / 300) * u * 0.5);
    ctx.fillStyle = "#1D1626"; ctx.fillRect(bx - u, by - u, w + 2 * u, h + 2 * u);
    ctx.fillStyle = icon === "fail" ? "#FFD6DC" : icon === "alert" ? "#FFE9C2" : "#FFFFFF"; ctx.fillRect(bx, by, w, h);
    ctx.fillStyle = "#1D1626"; ctx.fillRect(bx + 2 * u, by + h + u, 2 * u, u);
    const P = (px: number, py: number, pw = 1, ph = 1, c = "#1D1626") => { ctx.fillStyle = c; ctx.fillRect(bx + (px + 1) * u, by + (py + 1) * u, pw * u, ph * u); };
    switch (icon) {
      case "gear": P(3, 1, 3, 1, "#5A5F73"); P(2, 2, 5, 4, "#5A5F73"); P(3, 6, 3, 1, "#5A5F73"); P(1, 3, 1, 2, "#5A5F73"); P(7, 3, 1, 2, "#5A5F73"); P(4, 3, 1, 2, "#FFFFFF"); break;
      case "code": P(1, 3, 1, 2, "#3F8CFF"); P(2, 2); P(2, 5); P(7, 3, 1, 2, "#3F8CFF"); P(6, 2); P(6, 5); P(4, 1, 1, 6, "#C2553A"); break;
      case "lens": P(2, 1, 3, 1); P(1, 2, 1, 3); P(5, 2, 1, 3); P(2, 5, 3, 1); P(2, 2, 3, 3, "#BFE3FF"); P(6, 6, 2, 2, "#8B5A33"); break;
      case "flask": P(3, 0, 3, 1); P(3, 1, 3, 2, "#DDE7F0"); P(2, 3, 5, 4, "#5BF2A5"); P(3, 4, 1, 1, "#FFFFFF"); break;
      case "wait": P(2, 0, 5, 1); P(2, 7, 5, 1); P(3, 1, 3, 2, "#FFD36B"); P(4, 3, 1, 2, "#FFD36B"); P(3, 5, 3, 2, "#FFD36B"); break;
      case "box": P(1, 2, 7, 5, "#C98B4A"); P(1, 2, 7, 1, "#E2A866"); P(4, 2, 1, 5, "#8E5A2C"); break;
      case "star": P(4, 0, 1, 2, "#F4C430"); P(1, 2, 7, 2, "#F4C430"); P(2, 4, 5, 1, "#F4C430"); P(2, 5, 2, 2, "#F4C430"); P(5, 5, 2, 2, "#F4C430"); break;
      case "alert": P(4, 0, 1, 5, "#E07A00"); P(4, 6, 1, 1, "#E07A00"); break;
      case "fail": P(2, 1, 1, 1, "#E2465E"); P(3, 2, 1, 1, "#E2465E"); P(4, 3, 1, 1, "#E2465E"); P(5, 4, 1, 1, "#E2465E"); P(6, 5, 1, 1, "#E2465E"); P(6, 1, 1, 1, "#E2465E"); P(5, 2, 1, 1, "#E2465E"); P(3, 4, 1, 1, "#E2465E"); P(2, 5, 1, 1, "#E2465E"); break;
    }
  }
}

export { animFor };
