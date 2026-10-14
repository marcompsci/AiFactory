"use client";

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { gatePosition, PLAZA_RADIUS, type District as D } from "@aiciv/world-engine";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useStore } from "@/lib/store";

/** Deterministic pseudo-random from a string so every client builds the same skyline. */
function rng(seed: string) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

interface Tower {
  pos: [number, number, number];
  size: [number, number, number];
  rot: number;
  kind: "box" | "cyl" | "cone" | "dome";
}

function towersFor(d: D): Tower[] {
  const r = rng(d.id);
  const out: Tower[] = [];
  const H = d.height;
  switch (d.architecture) {
    case "spire":
      out.push({ pos: [0, H / 2, -2], size: [3.2, H, 3.2], rot: 0, kind: "cone" });
      out.push({ pos: [0, 4, -2], size: [7, 8, 7], rot: 0, kind: "cyl" });
      break;
    case "blocks":
      for (let i = 0; i < d.towers; i++) {
        const h = H * (0.45 + r() * 0.55);
        out.push({ pos: [(i - (d.towers - 1) / 2) * 4.2, h / 2, -3 - r() * 4], size: [3 + r(), h, 3 + r() * 1.5], rot: 0, kind: "box" });
      }
      break;
    case "fortress": {
      out.push({ pos: [0, 3.5, -3], size: [12, 7, 7], rot: 0, kind: "box" });
      const c: [number, number][] = [[-6, -6.5], [6, -6.5], [-6, 0.5], [6, 0.5]];
      c.forEach(([x, z]) => out.push({ pos: [x, H / 2, z], size: [2.6, H, 2.6], rot: 0, kind: "cyl" }));
      break;
    }
    case "twisted":
      for (let i = 0; i < d.towers; i++) {
        const h = H * (0.6 + r() * 0.4);
        const x = (i - 1) * 5;
        for (let k = 0; k < 5; k++)
          out.push({ pos: [x, (h / 5) * (k + 0.5), 2], size: [3, h / 5 - 0.25, 3], rot: (k * Math.PI) / 14 + i, kind: "box" });
      }
      break;
    case "dome":
      out.push({ pos: [0, 0, 2], size: [7, 7, 7], rot: 0, kind: "dome" });
      for (let i = 0; i < d.towers; i++) out.push({ pos: [i ? 7 : -7, H / 2, 3], size: [1.6, H, 1.6], rot: 0, kind: "cyl" });
      break;
    case "tower":
      out.push({ pos: [0, H / 2, -2], size: [5, H, 5], rot: Math.PI / 4, kind: "box" });
      out.push({ pos: [0, H + 1.5, -2], size: [3.2, 3, 3.2], rot: 0, kind: "cyl" });
      out.push({ pos: [0, 2.5, 3], size: [12, 5, 6], rot: 0, kind: "box" });
      break;
    case "vault":
      out.push({ pos: [0, 3, 3], size: [16, 6, 8], rot: 0, kind: "box" });
      for (let i = 0; i < d.towers; i++) out.push({ pos: [(i - 1) * 5.5, 6 + H / 4, 3], size: [3, H / 2, 3], rot: Math.PI / 4, kind: "box" });
      break;
  }
  return out;
}

function TowerMesh({ t, color, ghost }: { t: Tower; color: string; ghost: boolean }) {
  const geom = useMemo(() => {
    switch (t.kind) {
      case "cyl":
        return new THREE.CylinderGeometry(t.size[0] / 2, t.size[0] / 2, t.size[1], 20);
      case "cone":
        return new THREE.CylinderGeometry(0.25, t.size[0] / 2, t.size[1], 6);
      case "dome":
        return new THREE.SphereGeometry(t.size[0], 32, 16, 0, Math.PI * 2, 0, Math.PI / 2);
      default:
        return new THREE.BoxGeometry(...t.size);
    }
  }, [t]);
  const edges = useMemo(() => new THREE.EdgesGeometry(geom, 25), [geom]);
  return (
    <group position={t.pos} rotation={[0, t.rot, 0]}>
      <mesh geometry={geom}>
        <meshStandardMaterial color={color === "#F4D58D" ? "#2a2414" : "#0d1528"} roughness={0.55} metalness={0.6} transparent opacity={ghost ? 0.12 : 1} />
      </mesh>
      <lineSegments geometry={edges}>
        <lineBasicMaterial color={color} transparent opacity={ghost ? 0.35 : 0.85} toneMapped={false} />
      </lineSegments>
    </group>
  );
}

function Workstation({ id, label, pos, color, active }: { id: string; label: string; pos: [number, number, number]; color: string; active: string | undefined }) {
  const beam = useRef<THREE.Mesh>(null);
  const reduced = useStore((s) => s.settings.reducedMotion);
  useFrame(({ clock }) => {
    if (!beam.current) return;
    const m = beam.current.material as THREE.MeshBasicMaterial;
    m.opacity = active ? (reduced ? 0.5 : 0.35 + Math.sin(clock.elapsedTime * 6) * 0.15) : 0;
  });
  return (
    <group position={pos}>
      <mesh position={[0, 0.5, 0]}>
        <boxGeometry args={[2.2, 1, 1.1]} />
        <meshStandardMaterial color="#121c33" metalness={0.7} roughness={0.4} />
      </mesh>
      <mesh position={[0, 1.02, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[2, 0.9]} />
        <meshBasicMaterial color={active ? color : "#1f2c4a"} toneMapped={false} />
      </mesh>
      <mesh ref={beam} position={[0, 6, 0]}>
        <cylinderGeometry args={[0.25, 0.6, 10, 16, 1, true]} />
        <meshBasicMaterial color={color} transparent opacity={0} toneMapped={false} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      {active ? (
        <Html position={[0, 2.3, 0]} center zIndexRange={[10, 0]}>
          <div className="world-label rounded-md px-2 py-0.5 text-[11px]" style={{ background: "rgb(7 11 24 / .8)", color, border: `1px solid ${color}55` }}>
            {label}: {active.replaceAll("_", " ")}
          </div>
        </Html>
      ) : null}
      <mesh position={[0, 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]} userData={{ workstation: id }}>
        <ringGeometry args={[1.6, 1.75, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.4} toneMapped={false} />
      </mesh>
    </group>
  );
}

/** A light column over the Owner's Tower while a release waits for the owner's decision. */
function OwnerBeacon({ height, color }: { height: number; color: string }) {
  const ref = useRef<THREE.Mesh>(null);
  const reduced = useStore((s) => s.settings.reducedMotion);
  useFrame(({ clock }) => {
    if (ref.current) (ref.current.material as THREE.MeshBasicMaterial).opacity = reduced ? 0.35 : 0.25 + Math.abs(Math.sin(clock.elapsedTime * 2)) * 0.3;
  });
  return (
    <mesh ref={ref} position={[0, height + 18, -2]}>
      <cylinderGeometry args={[0.6, 1.6, 30, 24, 1, true]} />
      <meshBasicMaterial color={color} transparent opacity={0.4} toneMapped={false} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
  );
}

export function District({ d }: { d: D }) {
  const activity = useStore((s) => s.world.districtActivity[d.id] ?? 0);
  const ownerWaiting = useStore((s) => d.id === "owners-tower" && s.world.ownerQueue.length > 0);
  const active = useStore((s) => s.world.activeWorkstations);
  const focused = useStore((s) => s.focusedDistrict === d.id);
  const interior = useStore((s) => s.interior && s.focusedDistrict === d.id);
  const labels = useStore((s) => s.settings.labels);
  const focus = useStore((s) => s.focusDistrict);
  const towers = useMemo(() => towersFor(d), [d]);
  const pad = useRef<THREE.MeshBasicMaterial>(null);
  const level = useRef(activity);
  level.current = Math.max(level.current, activity);

  useFrame((_, dt) => {
    level.current = Math.max(0, level.current - dt * 0.08); // activity decays between events
    if (pad.current) pad.current.opacity = 0.18 + level.current * 0.5 + (focused ? 0.15 : 0);
  });

  const gate = gatePosition(d.id);
  const toPlaza = new THREE.Vector3(gate[0], 0, gate[2]);
  const walkLen = Math.max(0, toPlaza.length() - PLAZA_RADIUS);
  const walkAngle = Math.atan2(gate[0], gate[2]);
  const walkMid = toPlaza.clone().setLength(PLAZA_RADIUS + walkLen / 2);

  return (
    <group>
      {/* elevated walkway from this district's gate to the plaza ring */}
      {walkLen > 0.5 ? (
        <group position={[walkMid.x, 0.35, walkMid.z]} rotation={[0, walkAngle, 0]}>
          <mesh>
            <boxGeometry args={[2.4, 0.3, walkLen]} />
            <meshStandardMaterial color="#0f1a30" metalness={0.6} roughness={0.5} />
          </mesh>
          {[-1.25, 1.25].map((x) => (
            <mesh key={x} position={[x, 0.2, 0]}>
              <boxGeometry args={[0.08, 0.08, walkLen]} />
              <meshBasicMaterial color={d.color} toneMapped={false} />
            </mesh>
          ))}
        </group>
      ) : null}

      <group position={d.position}>
        <mesh
          rotation={[-Math.PI / 2, 0, 0]}
          position={[0, 0.06, 0]}
          onClick={(e) => {
            e.stopPropagation();
            focus(d.id);
          }}
        >
          <circleGeometry args={[11, 48]} />
          <meshBasicMaterial ref={pad} color={d.color} transparent opacity={0.2} toneMapped={false} depthWrite={false} />
        </mesh>
        <group
          onClick={(e) => {
            e.stopPropagation();
            focus(d.id);
          }}
        >
          {towers.map((t, i) => (
            <TowerMesh key={i} t={t} color={d.color} ghost={interior} />
          ))}
        </group>
        {d.workstations.map((w) => (
          <Workstation key={w.id} id={w.id} label={w.label} pos={w.offset} color={d.color} active={active[w.id]} />
        ))}
        <pointLight position={[0, 8, 4]} color={d.color} intensity={30 + activity * 120} distance={28} decay={2} />
        {ownerWaiting ? <OwnerBeacon height={d.height} color={d.color} /> : null}
        {labels ? (
          <Html position={[0, Math.min(d.height + 3, 24), -2]} center zIndexRange={[5, 0]}>
            <button
              type="button"
              onClick={() => focus(d.id)}
              className="world-label pointer-events-auto rounded-full px-3 py-1 text-xs font-medium"
              style={{ transform: "none", background: "rgb(7 11 24 / .72)", color: d.color, border: `1px solid ${d.color}66`, fontFamily: "var(--font-display)" }}
            >
              {d.name}
            </button>
          </Html>
        ) : null}
      </group>
    </group>
  );
}
