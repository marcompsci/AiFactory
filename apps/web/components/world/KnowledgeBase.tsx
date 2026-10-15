"use client";

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { knowledge } from "@/lib/api";
import { useStore } from "@/lib/store";

const Y = 34;          // floats over the plaza, in front of the Nexus Spire (34 high)
const Z = 16;
const CYAN = "#9BE7FF";
const VIOLET = "#C9A3FF";

/**
 * The company knowledge base, floating in the middle of the city: a pixel-art library island for Phoronomics and
 * Phoronomic Studios. Each orbiting tile is a skill or doc; it glows when an agent pulls from it. Click to manage it.
 */
export function KnowledgeBase() {
  const setTab = useStore((s) => s.setTab);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const status = useStore((s) => s.status);
  const lastPull = useStore((s) => s.feed.find((e) => e.event_type === "knowledge.consulted"));
  const q = useQuery({ queryKey: ["knowledge", "", "", ""], queryFn: () => knowledge.list(), refetchInterval: 30_000, retry: 0,
    enabled: status === "live" || status === "connecting" || status === "reconnecting" });
  const counts = q.data?.counts ?? { doc: 0, skill: 0 };
  const tiles = Math.min(28, counts.doc + counts.skill);
  const group = useRef<THREE.Group>(null);
  const ring = useRef<THREE.Group>(null);
  const core = useRef<THREE.MeshStandardMaterial>(null);
  const pullAt = lastPull ? Date.parse(lastPull.occurred_at) : 0;

  useFrame(({ clock: c }) => {
    const t = c.elapsedTime;
    if (group.current && !reduced) group.current.position.y = Y + Math.sin(t * 0.6) * 0.8;
    if (ring.current && !reduced) ring.current.rotation.y = t * 0.15;
    if (core.current) {
      const since = Date.now() - pullAt;
      core.current.emissiveIntensity = since >= 0 && since < 6000 ? 2.4 - since / 3000 : 0.9 + Math.sin(t * 2) * 0.15;
    }
  });

  const rocks = useMemo(() => {
    const g = new THREE.ConeGeometry(9, 9, 7, 1);
    g.rotateX(Math.PI);
    return g;
  }, []);

  const open = () => setTab("knowledge");
  return (
    <group ref={group} position={[0, Y, Z]} scale={1.5}>
      {/* the floating rock and its deck */}
      <mesh geometry={rocks} position={[0, -5, 0]}>
        <meshStandardMaterial color="#3b2f5c" flatShading roughness={1} />
      </mesh>
      <mesh position={[0, -0.4, 0]}>
        <cylinderGeometry args={[9.2, 9.2, 0.8, 7]} />
        <meshStandardMaterial color="#1a1f3d" flatShading />
      </mesh>
      <mesh position={[0, 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[8.6, 9.2, 7]} />
        <meshBasicMaterial color={CYAN} toneMapped={false} />
      </mesh>
      {/* two library wings: Phoronomics (cyan) and Phoronomic Studios (violet) */}
      {[[-3.2, CYAN], [3.2, VIOLET]].map(([x, c]) => (
        <group key={String(c)} position={[x as number, 0, 0]}>
          <mesh position={[0, 2.6, 0]}>
            <boxGeometry args={[4, 5.2, 4]} />
            <meshStandardMaterial color="#141b33" emissive={c as string} emissiveIntensity={0.08} flatShading />
          </mesh>
          {[0.9, 2.1, 3.3, 4.5].map((y) => (
            <mesh key={y} position={[0, y, 2.02]}>
              <boxGeometry args={[3.2, 0.5, 0.05]} />
              <meshBasicMaterial color={c as string} toneMapped={false} />
            </mesh>
          ))}
        </group>
      ))}
      {/* the core crystal */}
      <mesh position={[0, 8.2, 0]} onClick={(e) => { e.stopPropagation(); open(); }}
        onPointerOver={() => (document.body.style.cursor = "pointer")} onPointerOut={() => (document.body.style.cursor = "")}>
        <octahedronGeometry args={[1.9, 0]} />
        <meshStandardMaterial ref={core} color="#E6F7FF" emissive={CYAN} emissiveIntensity={1} flatShading toneMapped={false} />
      </mesh>
      {/* one orbiting tile per doc or skill */}
      <group ref={ring} position={[0, 7, 0]}>
        {Array.from({ length: tiles }, (_, i) => {
          const a = (i / Math.max(1, tiles)) * Math.PI * 2;
          const r = 6 + (i % 2) * 1.2;
          return (
            <mesh key={i} position={[Math.cos(a) * r, Math.sin(i * 1.7) * 0.8, Math.sin(a) * r]} rotation={[0, -a, 0]}>
              <boxGeometry args={[0.9, 1.2, 0.12]} />
              <meshBasicMaterial color={i < counts.skill ? "#F4D58D" : i % 2 ? VIOLET : CYAN} toneMapped={false} />
            </mesh>
          );
        })}
      </group>
      <Html position={[0, 13, 0]} center zIndexRange={[8, 0]}>
        <button type="button" onClick={open} className="neon-sign pointer-events-auto" style={{ "--c": CYAN } as React.CSSProperties}
          data-testid="knowledge-sign">
          <span className="neon-icon" aria-hidden>✦</span>
          <span>
            <span className="block">Knowledge Base</span>
            <span className="neon-sub">Phoronomics · Phoronomic Studios{q.data ? ` · ${counts.skill} skills, ${counts.doc} docs` : ""}</span>
          </span>
        </button>
      </Html>
    </group>
  );
}
