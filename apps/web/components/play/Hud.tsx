"use client";

import { useEffect, useRef, useState } from "react";
import type { EventEnvelope } from "@aiciv/event-contracts";
import { buildTown, type GameMap } from "@/lib/play/maps";
import { PACKAGE_LABEL } from "@/lib/play/engine";
import { usePlay } from "@/lib/play/state";
import { useStore } from "@/lib/store";
import { live } from "./runner";

const MAP_NAME: Record<string, string> = { town: "Town", "nexus-spire": "Nexus Spire", "data-observatory": "Research Observatory", "code-forge": "Code Forge",
  "sentinel-citadel": "Sentinel Citadel", "central-bank": "AI Central Bank", "owners-tower": "Owner's Tower" };

function Icon({ d, label }: { d: string; label: string }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <title>{label}</title>
      <path d={d} />
    </svg>
  );
}

const ICONS = {
  bell: "M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0",
  map: "M9 3 3 6v15l6-3 6 3 6-3V3l-6 3-6-3zM9 3v15M15 6v15",
  menu: "M4 6h16M4 12h10M4 18h16",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  chat: "M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 1 1 21 11.5z",
  bag: "M6 8h12l1 12H5L6 8zM9 8V6a3 3 0 0 1 6 0v2",
  city: "M3 21h18M5 21V8l5-3v16M14 21V3l5 3v15",
};

export function TopBar() {
  const status = useStore((s) => s.status);
  const mode = useStore((s) => s.world.mode);
  const pending = useStore((s) => s.world.pendingApprovals.length + s.world.ownerQueue.length);
  const mapId = usePlay((s) => s.mapId);
  const open = usePlay((s) => s.openPanel);
  const badge = status === "demo" ? { t: "DEMO: not real work", c: "bg-warn text-[#1d1626]" }
    : status === "signin" ? { t: "SIGN IN", c: "bg-warn text-[#1d1626]" }
    : status !== "live" ? { t: "RECONNECTING", c: "bg-white/15 text-ink" }
    : mode === "simulation" ? { t: "SIMULATION", c: "bg-[#C9A7FF] text-[#1d1626]" } : { t: "LIVE", c: "bg-ok text-[#0B1A12]" };
  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-30 flex items-start justify-between gap-2 px-3 pt-[max(10px,env(safe-area-inset-top))]">
      <div className="pointer-events-auto flex min-w-0 items-center gap-2 rounded-full bg-[#191430]/85 py-1.5 pl-3 pr-1.5 backdrop-blur">
        <span className="whitespace-nowrap font-pixel text-xs tracking-wider text-[#f3e9d2] sm:text-sm"><span className="sm:hidden">AI CIV</span><span className="hidden sm:inline">AI CIVILIZATION</span></span>
        <span className="hidden text-xs text-ink-3 sm:inline">· {MAP_NAME[mapId] ?? mapId}</span>
        <span className={`whitespace-nowrap rounded-full px-2 py-0.5 font-pixel text-[10px] ${badge.c}`}>{badge.t}</span>
      </div>
      <div className="pointer-events-auto flex items-center gap-1 rounded-full bg-[#191430]/85 p-1 text-[#f3e9d2] backdrop-blur">
        <button type="button" className="relative grid size-9 place-items-center rounded-full sm:size-10 hover:bg-white/10" onClick={() => open("approvals")} aria-label={`Approvals (${pending} waiting)`}>
          <Icon d={ICONS.bell} label="Approvals" />
          {pending ? <span className="absolute right-1 top-1 grid min-w-4 place-items-center rounded-full bg-warn px-1 text-[10px] font-bold text-[#1d1626]">{pending}</span> : null}
        </button>
        <button type="button" className="grid size-9 place-items-center rounded-full sm:size-10 hover:bg-white/10" onClick={() => usePlay.getState().toggleMap()} aria-label="Toggle minimap"><Icon d={ICONS.map} label="Map" /></button>
        <button type="button" className="grid size-9 place-items-center rounded-full sm:size-10 hover:bg-white/10" onClick={() => open("avatar")} aria-label="Your character"><Icon d={ICONS.user} label="Character" /></button>
        <button type="button" className="grid size-9 place-items-center rounded-full sm:size-10 hover:bg-white/10" onClick={() => open("journal")} aria-label="Mission journal"><Icon d={ICONS.menu} label="Journal" /></button>
        <a href="/" className="grid size-9 place-items-center rounded-full sm:size-10 hover:bg-white/10" aria-label="3D city and command center"><Icon d={ICONS.city} label="3D city" /></a>
      </div>
    </div>
  );
}

/** Town minimap: buildings, roads, packages, agents on the move and you. */
export function Minimap() {
  const show = usePlay((s) => s.showMap);
  const mapId = usePlay((s) => s.mapId);
  const ref = useRef<HTMLCanvasElement>(null);
  const town = useRef<GameMap | null>(null);
  useEffect(() => {
    if (!show || mapId !== "town") return;
    town.current ??= buildTown();
    const m = town.current;
    let raf = 0, last = 0;
    const draw = (t: number) => {
      raf = requestAnimationFrame(draw);
      if (t - last < 200) return;
      last = t;
      const c = ref.current;
      if (!c) return;
      const k = 3;
      c.width = m.w * k; c.height = m.h * k;
      const ctx = c.getContext("2d")!;
      for (let y = 0; y < m.h; y++) for (let x = 0; x < m.w; x++) {
        const g = m.ground[y * m.w + x];
        ctx.fillStyle = g === "path" ? "#D9B27A" : g === "plaza" ? "#B7BAC2" : g === "water" ? "#4AA3DC" : m.solid[y * m.w + x] ? "#3F8A40" : "#5FAE4C";
        ctx.fillRect(x * k, y * k, k, k);
      }
      for (const b of m.buildings) { ctx.fillStyle = b.roof; ctx.fillRect(b.x * k, b.y * k, b.w * k, b.h * k); }
      const world = useStore.getState().world;
      ctx.fillStyle = "#F4D58D";
      for (const p of Object.values(world.packages)) {
        if (p.status !== "IN_TRANSIT" && p.status !== "ARRIVED" && p.status !== "QUEUED") continue;
        const d = m.docks[p.status === "ARRIVED" ? p.destination : p.origin] ?? m.docks["logistics-depot"];
        ctx.fillRect(d.x * k, d.y * k, k, k);
      }
      ctx.fillStyle = "#FFFFFF";
      ctx.fillRect(live.x * k - 3, live.y * k - 3, 6, 6);
      ctx.fillStyle = "#E2465E";
      ctx.fillRect(live.x * k - 2, live.y * k - 2, 4, 4);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [show, mapId]);
  if (!show) return null;
  return (
    <div className="pointer-events-none fixed right-3 top-[calc(max(10px,env(safe-area-inset-top))+56px)] z-20">
      {mapId === "town" ? (
        <canvas ref={ref} className="w-[120px] rounded-md border-2 border-[#f3e9d2] sm:w-[150px]" style={{ imageRendering: "pixelated" }} aria-label="Town map" />
      ) : (
        <div className="rounded-md border-2 border-[#f3e9d2] bg-[#191430]/90 px-3 py-1.5 font-pixel text-xs text-[#f3e9d2]">{MAP_NAME[mapId]}</div>
      )}
    </div>
  );
}

export function Joystick() {
  const base = useRef<HTMLDivElement>(null);
  const [knob, setKnob] = useState({ x: 0, y: 0 });
  const active = useRef<number | null>(null);
  const R = 46;
  const move = (e: React.PointerEvent) => {
    if (active.current !== e.pointerId || !base.current) return;
    const r = base.current.getBoundingClientRect();
    let x = e.clientX - (r.left + r.width / 2), y = e.clientY - (r.top + r.height / 2);
    const d = Math.hypot(x, y);
    if (d > R) { x = (x / d) * R; y = (y / d) * R; }
    setKnob({ x, y });
    usePlay.getState().setStick(x / R, y / R);
  };
  const end = () => { active.current = null; setKnob({ x: 0, y: 0 }); usePlay.getState().setStick(0, 0); };
  return (
    <div
      ref={base}
      className="pointer-events-auto relative size-32 touch-none rounded-full border-2 border-white/25 bg-[#191430]/55 backdrop-blur-sm"
      onPointerDown={(e) => { active.current = e.pointerId; (e.target as HTMLElement).setPointerCapture(e.pointerId); move(e); }}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      role="application"
      aria-label="Movement joystick"
    >
      {["▲", "▼", "◀", "▶"].map((a, i) => (
        <span key={a} className="absolute text-xs text-white/60" style={[{ left: "50%", top: 6, transform: "translateX(-50%)" }, { left: "50%", bottom: 6, transform: "translateX(-50%)" }, { left: 8, top: "50%", transform: "translateY(-50%)" }, { right: 8, top: "50%", transform: "translateY(-50%)" }][i]}>{a}</span>
      ))}
      <div className="absolute left-1/2 top-1/2 size-14 rounded-full border-2 border-white/40 bg-white/25" style={{ transform: `translate(calc(-50% + ${knob.x}px), calc(-50% + ${knob.y}px))` }} />
    </div>
  );
}

export function Controls() {
  const nearby = usePlay((s) => s.nearby);
  const talking = usePlay((s) => s.talkingTo);
  const panel = usePlay((s) => s.panel);
  const [touch, setTouch] = useState(false);
  useEffect(() => { setTouch(window.matchMedia("(pointer: coarse)").matches || "ontouchstart" in window); }, []);
  if (talking || panel) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-30 flex items-end justify-between px-4 pb-[max(16px,env(safe-area-inset-bottom))]">
      <div>{touch ? <Joystick /> : <p className="rounded-md bg-[#191430]/80 px-3 py-2 text-xs text-ink-2">Move: WASD / arrows · Talk: E · Journal: J · or click to walk</p>}</div>
      <div className="pointer-events-auto flex items-end gap-3">
        <button type="button" onClick={() => usePlay.getState().openPanel("journal")} className="px-btn grid size-14 place-items-center rounded-full bg-[#2a3a5e] text-[#f3e9d2]" aria-label="Mission journal">
          <Icon d={ICONS.bag} label="Journal" />
        </button>
        <button
          type="button"
          disabled={!nearby}
          onClick={() => usePlay.getState().interact()}
          className="px-btn grid size-20 place-items-center rounded-full bg-[#5A5FBF] text-[#f3e9d2] disabled:opacity-45"
          aria-label={nearby?.label ?? "Nothing nearby"}
        >
          <span className="flex flex-col items-center">
            <Icon d={ICONS.chat} label="Talk" />
            <span className="font-pixel text-xs">{nearby?.kind === "object" ? "USE" : "TALK"}</span>
          </span>
        </button>
      </div>
      {nearby ? (
        <div className="pointer-events-none absolute bottom-[calc(max(16px,env(safe-area-inset-bottom))+96px)] right-4 max-w-[60vw] rounded-md bg-[#191430]/90 px-3 py-1.5 font-pixel text-sm text-[#f3e9d2]">
          {nearby.label}
        </div>
      ) : null}
    </div>
  );
}

/** Short notes: closed buildings, finished missions, approvals requested, packages arriving. */
export function Toasts() {
  const toast = usePlay((s) => s.toast);
  const feed = useStore((s) => s.feed);
  const seen = useRef(new Set<string>());
  const since = useRef(Date.now() - 5000);
  const [, force] = useState(0);
  useEffect(() => {
    // only news: events that happened after the game opened (history and replays aren't announced)
    const fresh = feed.filter((e) => !seen.current.has(e.event_id) && Date.parse(e.occurred_at) > since.current);
    feed.forEach((e) => seen.current.add(e.event_id));
    const note = fresh.map(describe).find(Boolean);
    if (note) usePlay.getState().say(note);
  }, [feed]);
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => force((n) => n + 1), 4200);
    return () => window.clearTimeout(id);
  }, [toast]);
  if (!toast || Date.now() - toast.at > 4000) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 top-[calc(max(10px,env(safe-area-inset-top))+60px)] z-30 flex justify-center px-4">
      <div className="px-panel max-w-md px-4 py-2 text-center text-sm text-[#f3e9d2]">{toast.text}</div>
    </div>
  );
}

function describe(e: EventEnvelope): string | null {
  const p = (e.payload ?? {}) as Record<string, unknown>;
  switch (e.event_type) {
    case "mission.completed": return p.title ? `Mission finished: ${String(p.title)}` : "A mission finished. The journal has the result.";
    case "mission.failed": return "A mission failed. Check the journal.";
    case "approval.requested": return "Something needs your approval. Tap the bell.";
    case "package.arrived": return `${PACKAGE_LABEL[String(p.package_type)] ?? "A package"} arrived at its destination.`;
    default: return null;
  }
}



/** The screen-reader voice for step-by-step movement: Shift+arrow steps one tile, L looks around (V6.32). */
export function Announcer() {
  const a = usePlay((s) => s.announcement);
  return (
    <div className="sr-only" role="status" aria-live="polite" aria-atomic="true" data-testid="announcer">
      {/* the key makes a repeated phrase ("Can't go north…") announce again */}
      <span key={a.seq}>{a.text}</span>
    </div>
  );
}
