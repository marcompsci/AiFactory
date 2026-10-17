"use client";

import { useEffect, useRef } from "react";
import { play } from "@/lib/api";
import { DEFAULT_PLAYER, type PlayerLook } from "@/lib/play/sprites";
import { usePlay } from "@/lib/play/state";
import { useStore } from "@/lib/store";
import { Dialogue } from "./Dialogue";
import { Announcer, Controls, Minimap, Toasts, TopBar } from "./Hud";
import { PackageCard, Panels } from "./Panels";
import { live, Runner } from "./runner";

/** The playable town: canvas plus HUD. Restores where you were and how you look, and saves it as you play. */
export function Game() {
  const ref = useRef<HTMLCanvasElement>(null);
  const runner = useRef<Runner | null>(null);
  const status = useStore((s) => s.status);

  useEffect(() => {
    runner.current = new Runner(ref.current!);
    return () => runner.current?.stop();
  }, []);

  // restore the avatar and position once the server is reachable
  useEffect(() => {
    if (status !== "live" || live.ready) return;
    play.state().then((r) => {
      const p = r.player;
      if (p) {
        usePlay.getState().setLook({ ...DEFAULT_PLAYER, ...(p.look as PlayerLook) }, p.name);
        runner.current?.place(p.map, p.x, p.y, p.facing);
      }
      live.ready = true;
    }).catch(() => { live.ready = true; });
  }, [status]);

  // save position: every few seconds while moving, on changing rooms, and when the app goes to the background
  useEffect(() => {
    const save = () => {
      if (!live.ready || !live.moved || useStore.getState().status !== "live") return;
      live.moved = false;
      const { look, name } = usePlay.getState();
      play.save({ name, look, map: live.mapId, x: Math.round(live.x * 100) / 100, y: Math.round(live.y * 100) / 100, facing: live.facing }).catch(() => {});
    };
    const id = window.setInterval(save, 8000);
    const unsub = usePlay.subscribe((s, prev) => { if (s.mapId !== prev.mapId) save(); });
    const hide = () => document.visibilityState === "hidden" && save();
    document.addEventListener("visibilitychange", hide);
    return () => { window.clearInterval(id); unsub(); document.removeEventListener("visibilitychange", hide); };
  }, []);

  return (
    <main className="fixed inset-0 select-none overflow-hidden bg-[#120E1C]">
      <canvas ref={ref} className="absolute inset-0 h-full w-full touch-none" style={{ imageRendering: "pixelated" }} aria-label="AI Civilization town. Walk around and talk to your agents. Shift and an arrow key steps one tile and says what's ahead; L looks around." />
      <Announcer />
      <TopBar />
      <Minimap />
      <Toasts />
      <PackageCard />
      <Controls />
      <Dialogue />
      <Panels />
    </main>
  );
}
