"use client";

import { SEED } from "@aiciv/shared-types";
import type { AgentLook } from "@aiciv/world-engine";
import { useEffect, useRef } from "react";
import { frameCanvas, outfitFromLook, outfitFromPlayer, DEFAULT_PLAYER, type Outfit, type Pose } from "@/lib/play/sprites";
import type { Dir } from "@/lib/play/maps";

/** Every pixel-art character in every direction and pose, for checking the art. */
function Row({ name, o }: { name: string; o: Outfit }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current!;
    const k = 4;
    const cells: [Dir, Pose, number][] = [["down", "stand", 0], ["down", "walk", 1], ["down", "walk", 3], ["left", "stand", 0], ["left", "walk", 1], ["right", "walk", 3], ["up", "stand", 0], ["up", "work", 1], ["down", "talk", 1], ["down", "celebrate", 1], ["down", "read", 0], ["down", "carry", 1]];
    c.width = cells.length * 18 * k; c.height = 26 * k;
    const ctx = c.getContext("2d")!;
    ctx.imageSmoothingEnabled = false;
    cells.forEach(([d, p, f], i) => ctx.drawImage(frameCanvas(o, d, p, f), i * 18 * k, k, 16 * k, 24 * k));
  }, [o]);
  return (
    <div className="flex items-center gap-3">
      <span className="w-20 shrink-0 text-right text-xs text-ink-2">{name}</span>
      <canvas ref={ref} style={{ imageRendering: "pixelated", height: 104 }} />
    </div>
  );
}

export default function PixelCast() {
  return (
    <main className="h-full overflow-auto bg-[#5FAE4C] p-4" style={{ overflow: "auto" }}>
      <div className="space-y-1">
        <Row name="You" o={outfitFromPlayer(DEFAULT_PLAYER)} />
        {SEED.agents.map((a) => {
          const look = (a.avatar as { look?: AgentLook }).look;
          return look ? <Row key={a.id} name={a.name} o={outfitFromLook(look)} /> : null;
        })}
      </div>
    </main>
  );
}
