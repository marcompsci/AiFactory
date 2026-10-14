"use client";

import type { EventEnvelope } from "@aiciv/event-contracts";
import { applyEvent, hydrate as hydrateWorld, initialWorld, type AgentSeed, type PackageSeed, type WorldState } from "@aiciv/world-engine";
import { SEED } from "@aiciv/shared-types";
import { create } from "zustand";

export type ConnectionStatus = "connecting" | "live" | "reconnecting" | "demo";
export type Tab = "missions" | "company" | "agents" | "activity" | "approvals" | "system";
export type CameraMode = "overview" | "orbit" | "follow" | "fly";
export type Quality = "auto" | "high" | "low";

export interface DemoApproval {
  id: string;
  summary: string;
}

interface Settings {
  reducedMotion: boolean;
  quality: Quality;
  labels: boolean;
  drones: boolean;
}

export interface LogisticsNode {
  id: string;
  kind: "dispatch" | "receiving" | "junction";
  district: string | null;
  position: [number, number, number];
}

export interface LogisticsRoute {
  id: string;
  from_node: string;
  to_node: string;
  length: number;
  status: "UP" | "DOWN";
  load?: number;
}

export interface Logistics {
  nodes: LogisticsNode[];
  routes: LogisticsRoute[];
  beltSpeed: number;
}

interface Store {
  logistics: Logistics | null;
  /** serverTime - clientTime in ms, so package positions computed in the browser match the backend clock. */
  clockOffset: number;
  selectedPackageId: string | null;
  selectPackage: (id: string | null) => void;
  status: ConnectionStatus;
  statusDetail: string;
  world: WorldState;
  feed: EventEnvelope[];
  buffer: EventEnvelope[];
  needsReplay: boolean;
  selectedAgentId: string | null;
  selectedMissionId: string | null;
  focusedDistrict: string | null;
  interior: boolean;
  tab: Tab;
  sheet: "peek" | "half" | "full";
  camera: CameraMode;
  settings: Settings;
  demoApproval: DemoApproval | null;
  clock: () => number;

  hydrate: (agents: AgentSeed[], sequence: number, mode: "live" | "simulation", approvals: string[],
    extra?: { packages?: PackageSeed[]; ownerQueue?: string[]; logistics?: Logistics; serverTime?: string }) => void;
  ingest: (events: EventEnvelope[]) => void;
  seedFeed: (history: EventEnvelope[]) => void;
  setStatus: (s: ConnectionStatus, detail?: string) => void;
  selectAgent: (id: string | null) => void;
  selectMission: (id: string | null) => void;
  focusDistrict: (id: string | null, interior?: boolean) => void;
  setTab: (t: Tab) => void;
  setSheet: (s: Store["sheet"]) => void;
  setCamera: (c: CameraMode) => void;
  setSettings: (s: Partial<Settings>) => void;
  setDemoApproval: (a: DemoApproval | null) => void;
  replayDone: () => void;
}

const prefersReduced = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

const seedAgents: AgentSeed[] = SEED.agents.map((a) => ({ ...a }));

export const useStore = create<Store>((set, get) => ({
  status: "connecting",
  statusDetail: "",
  logistics: null,
  clockOffset: 0,
  selectedPackageId: null,
  selectPackage: (id) => set({ selectedPackageId: id }),
  world: initialWorld(seedAgents),
  feed: [],
  buffer: [],
  needsReplay: false,
  selectedAgentId: null,
  selectedMissionId: null,
  focusedDistrict: null,
  interior: false,
  tab: "missions",
  sheet: "peek",
  camera: "overview",
  settings: { reducedMotion: prefersReduced(), quality: "auto", labels: true, drones: true },
  demoApproval: null,
  clock: () => (typeof performance !== "undefined" ? performance.now() : 0),

  hydrate: (agents, sequence, mode, approvals, extra = {}) => {
    const routeStatus = Object.fromEntries((extra.logistics?.routes ?? []).map((r) => [r.id, r.status]));
    const world = hydrateWorld(agents, sequence, mode, approvals, extra.packages ?? [], extra.ownerQueue ?? [], routeStatus);
    set({
      world, buffer: [], needsReplay: false,
      ...(extra.logistics ? { logistics: extra.logistics } : {}),
      ...(extra.serverTime ? { clockOffset: Date.parse(extra.serverTime) - Date.now() } : {}),
    });
  },

  ingest: (incoming) => {
    const { clock } = get();
    let world = get().world;
    let feed = get().feed;
    // Merge with anything held back by an earlier gap, then apply strictly in sequence order.
    const pending = [...get().buffer, ...incoming].sort((a, b) => a.sequence - b.sequence);
    const held: EventEnvelope[] = [];
    let gap = false;
    for (const e of pending) {
      if (gap) {
        held.push(e);
        continue;
      }
      const r = applyEvent(world, e, clock());
      if (r.status === "gap") {
        gap = true;
        held.push(e);
      } else if (r.status === "applied") {
        world = r.state;
        feed = [e, ...feed].slice(0, 400);
      }
    }
    set({ world, feed, buffer: held.filter((e) => e.sequence > world.lastSequence), needsReplay: gap });
  },

  seedFeed: (history) =>
    set((s) => {
      const seen = new Set(s.feed.map((e) => e.event_id));
      const older = history.filter((e) => !seen.has(e.event_id)).sort((a, b) => b.sequence - a.sequence);
      return { feed: [...s.feed, ...older].sort((a, b) => b.sequence - a.sequence).slice(0, 400) };
    }),

  setStatus: (status, statusDetail = "") => set({ status, statusDetail }),
  selectAgent: (id) => set((s) => ({ selectedAgentId: id, tab: id ? "agents" : s.tab, camera: id ? "follow" : s.camera === "follow" ? "orbit" : s.camera, sheet: id && s.sheet === "peek" ? "half" : s.sheet })),
  selectMission: (id) => set({ selectedMissionId: id }),
  focusDistrict: (id, interior = false) => set({ focusedDistrict: id, interior: id ? interior : false, camera: id ? "orbit" : get().camera }),
  setTab: (tab) => set((s) => ({ tab, sheet: s.sheet === "peek" ? "half" : s.sheet })),
  setSheet: (sheet) => set({ sheet }),
  setCamera: (camera) => set({ camera, ...(camera !== "follow" ? {} : {}) }),
  setSettings: (s) => set((st) => ({ settings: { ...st.settings, ...s } })),
  setDemoApproval: (demoApproval) => set({ demoApproval }),
  replayDone: () => set({ needsReplay: false }),
}));
