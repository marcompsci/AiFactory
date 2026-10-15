"use client";

import { Html, OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { SEED } from "@aiciv/shared-types";
import type { AgentLook } from "@aiciv/world-engine";
import { ChibiFigure } from "./Chibi";

type SeedAgent = { key: string; name: string; role: string; avatar: { look?: AgentLook } };

/** Meet the team: every agent standing in a row (also used to review character designs). */
export function Cast() {
  const agents = (SEED.agents as unknown as SeedAgent[]).filter((a) => a.avatar.look);
  const perRow = 7;
  return (
    <div className="h-dvh w-full" style={{ background: "linear-gradient(#2A1650, #4A1F55)" }} data-testid="cast">
      <Canvas camera={{ position: [0, 3.2, 15], fov: 40 }} dpr={[1, 2]}>
        <ambientLight intensity={1.1} />
        <directionalLight position={[4, 8, 6]} intensity={1.6} />
        <hemisphereLight args={["#bfe9ff", "#3a2a5e", 0.8]} />
        {agents.map((a, i) => {
          const row = Math.floor(i / perRow);
          const col = i % perRow;
          const x = (col - (perRow - 1) / 2) * 2.1;
          const y = -row * 3.6 + 2.2;
          return (
            <group key={a.key} position={[x, y, 0]}>
              <ChibiFigure look={a.avatar.look} />
              <Html position={[0, -0.25, 0]} center>
                <div className="whitespace-nowrap text-center text-[11px] font-semibold text-white" style={{ textShadow: "0 1px 2px #000" }}>
                  {a.name}
                  <div className="text-[9px] font-normal opacity-80">{a.role}</div>
                </div>
              </Html>
            </group>
          );
        })}
        <OrbitControls target={[0, 0.2, 0]} />
      </Canvas>
    </div>
  );
}
