"use client";

import { create } from "zustand";
import type { Interactable } from "./maps";
import { DEFAULT_PLAYER, type PlayerLook } from "./sprites";

export type Panel = null | "journal" | "approvals" | "avatar" | "findings";

export interface Nearby {
  kind: "npc" | "object";
  id: string;          // agent id or interactable id
  label: string;
  object?: Interactable;
}

interface PlayState {
  mapId: string;
  setMap: (id: string) => void;
  talkingTo: string | null;
  talk: (agentId: string | null) => void;
  panel: Panel;
  openPanel: (p: Panel) => void;
  packageId: string | null;
  selectPackage: (id: string | null) => void;
  nearby: Nearby | null;
  setNearby: (n: Nearby | null) => void;
  toast: { text: string; at: number } | null;
  say: (text: string) => void;
  name: string;
  look: PlayerLook;
  setLook: (look: PlayerLook, name?: string) => void;
  showMap: boolean;
  toggleMap: () => void;
  /** Joystick vector in [-1, 1]; the keyboard writes into the same place. */
  stick: { x: number; y: number };
  setStick: (x: number, y: number) => void;
  /** Bumped when the HUD asks the game to interact with whatever is near (Talk button, E key). */
  interactSeq: number;
  interact: () => void;
  /** Read out by the screen-reader live region (step-by-step movement, looking around). */
  announcement: { text: string; seq: number };
  announce: (text: string) => void;
}

export const usePlay = create<PlayState>((set) => ({
  mapId: "town",
  setMap: (mapId) => set({ mapId, nearby: null }),
  talkingTo: null,
  talk: (talkingTo) => set({ talkingTo, panel: null }),
  panel: null,
  openPanel: (panel) => set({ panel, talkingTo: null }),
  packageId: null,
  selectPackage: (packageId) => set({ packageId }),
  nearby: null,
  setNearby: (nearby) => set((s) => (s.nearby?.id === nearby?.id ? {} : { nearby })),
  toast: null,
  say: (text) => set({ toast: { text, at: Date.now() } }),
  name: "Owner",
  look: DEFAULT_PLAYER,
  setLook: (look, name) => set((s) => ({ look, name: name ?? s.name })),
  showMap: true,
  toggleMap: () => set((s) => ({ showMap: !s.showMap })),
  stick: { x: 0, y: 0 },
  setStick: (x, y) => set({ stick: { x, y } }),
  interactSeq: 0,
  interact: () => set((s) => ({ interactSeq: s.interactSeq + 1 })),
  announcement: { text: "", seq: 0 },
  announce: (text) => set((s) => ({ announcement: { text, seq: s.announcement.seq + 1 } })),
}));
