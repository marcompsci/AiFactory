"use client";

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { buildLogistics, packagePosition, type Vec3, type WorldPackage } from "@aiciv/world-engine";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { PACKAGE_COLORS } from "@/lib/format";
import { useStore, type Logistics } from "@/lib/store";

/**
 * The conveyor network. Belt geometry and status come from the backend (snapshot + logistics.* events);
 * package positions are computed from each package's server-side route, start time and belt speed.
 * A package that reaches the end of its belt before the backend says ARRIVED waits there, pulsing,
 * because the animation never decides delivery.
 */



const SLAT_SPACING = 1.4;
const SIDE_OFFSET = 0.55; // the two directions of a ring belt run side by side

type Seg = { id: string; from: Vec3; to: Vec3; length: number; status: "UP" | "DOWN"; load: number; side: number };

function useSegments(logistics: Logistics | null, routeStatus: Record<string, "UP" | "DOWN">): { segs: Seg[]; nodes: Logistics["nodes"] } {
  return useMemo(() => {
    const g = logistics ?? { ...buildLogistics(), beltSpeed: 8 };
    const pos = Object.fromEntries(g.nodes.map((n) => [n.id, n.position as Vec3]));
    const segs = g.routes.map((r) => {
      const a = pos[r.from_node];
      const b = pos[r.to_node];
      const ring = r.from_node.startsWith("junction:") && r.to_node.startsWith("junction:");
      // offset each direction of a ring belt to its right-hand side
      const dx = b[0] - a[0];
      const dz = b[2] - a[2];
      const n = Math.hypot(dx, dz) || 1;
      const off: Vec3 = ring ? [(dz / n) * SIDE_OFFSET, 0, (-dx / n) * SIDE_OFFSET] : [0, 0, 0];
      return {
        id: r.id,
        from: [a[0] + off[0], a[1], a[2] + off[2]] as Vec3,
        to: [b[0] + off[0], b[1], b[2] + off[2]] as Vec3,
        length: r.length,
        status: routeStatus[r.id] ?? r.status,
        load: ("load" in r ? (r as { load?: number }).load : 0) ?? 0,
        side: ring ? 1 : 0,
      };
    });
    return { segs, nodes: g.nodes };
  }, [logistics, routeStatus]);
}

function Belt({ s, load }: { s: Seg; load: number }) {
  const mid: Vec3 = [(s.from[0] + s.to[0]) / 2, s.from[1] - 0.2, (s.from[2] + s.to[2]) / 2];
  const angle = Math.atan2(s.to[0] - s.from[0], s.to[2] - s.from[2]);
  const color = s.status === "DOWN" ? "#FF6178" : load >= 2 ? "#FFBD69" : "#32D8FF";
  return (
    <group position={mid} rotation={[0, angle, 0]}>
      <mesh>
        <boxGeometry args={[0.9, 0.18, s.length]} />
        <meshStandardMaterial color="#0c1426" metalness={0.6} roughness={0.5} transparent opacity={s.status === "DOWN" ? 0.45 : 1} />
      </mesh>
      {[-0.47, 0.47].map((x) => (
        <mesh key={x} position={[x, 0.1, 0]}>
          <boxGeometry args={[0.05, 0.05, s.length]} />
          <meshBasicMaterial color={color} toneMapped={false} transparent opacity={s.status === "DOWN" ? 0.9 : 0.55} />
        </mesh>
      ))}
    </group>
  );
}

/** Moving slats on every running belt, one instanced mesh for the whole city. */
function Slats({ segs }: { segs: Seg[] }) {
  const reduced = useStore((s) => s.settings.reducedMotion);
  const live = segs.filter((s) => s.status === "UP");
  const plan = useMemo(() => live.flatMap((s) => Array.from({ length: Math.max(1, Math.floor(s.length / SLAT_SPACING)) }, (_, i) => ({ s, i }))), [live]);
  const mesh = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  useFrame(({ clock }) => {
    if (!mesh.current) return;
    const t = reduced ? 0 : clock.elapsedTime * 1.2;
    plan.forEach(({ s, i }, k) => {
      const d = (t + i * SLAT_SPACING) % s.length;
      const f = d / s.length;
      dummy.position.set(s.from[0] + (s.to[0] - s.from[0]) * f, s.from[1] - 0.09, s.from[2] + (s.to[2] - s.from[2]) * f);
      dummy.rotation.set(0, Math.atan2(s.to[0] - s.from[0], s.to[2] - s.from[2]), 0);
      dummy.updateMatrix();
      mesh.current!.setMatrixAt(k, dummy.matrix);
    });
    mesh.current.count = plan.length;
    mesh.current.instanceMatrix.needsUpdate = true;
  });
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, Math.max(1, plan.length)]} key={plan.length}>
      <boxGeometry args={[0.8, 0.03, 0.18]} />
      <meshBasicMaterial color="#24407a" toneMapped={false} />
    </instancedMesh>
  );
}

function Terminal({ node, queue, color }: { node: Logistics["nodes"][number]; queue: number; color: string }) {
  const light = useRef<THREE.MeshBasicMaterial>(null);
  const reduced = useStore((s) => s.settings.reducedMotion);
  useFrame(({ clock }) => {
    if (!light.current) return;
    light.current.color.set(queue > 0 ? "#FFBD69" : node.kind === "dispatch" ? color : "#5BF2A5");
    light.current.opacity = queue > 0 && !reduced ? 0.6 + Math.sin(clock.elapsedTime * 5) * 0.35 : 0.85;
  });
  const p = node.position;
  return (
    <group position={[p[0], 0, p[2]]}>
      {/* gantry */}
      {[-0.7, 0.7].map((x) => (
        <mesh key={x} position={[x, 1.1, 0]}>
          <boxGeometry args={[0.12, 2.2, 0.12]} />
          <meshStandardMaterial color="#1a2742" metalness={0.7} roughness={0.4} />
        </mesh>
      ))}
      <mesh position={[0, 2.25, 0]}>
        <boxGeometry args={[1.6, 0.16, 0.5]} />
        <meshBasicMaterial ref={light} color={color} transparent toneMapped={false} />
      </mesh>
      {/* package queue waiting for the building to take it */}
      {Array.from({ length: Math.min(queue, 6) }, (_, i) => (
        <mesh key={i} position={[0, p[1] + 0.3 + i * 0.5, 0]}>
          <boxGeometry args={[0.45, 0.45, 0.45]} />
          <meshStandardMaterial color="#F4D58D" emissive="#F4D58D" emissiveIntensity={0.6} />
        </mesh>
      ))}
    </group>
  );
}

function Package({ pkg, segIndex, beltSpeed, clockOffset }: { pkg: WorldPackage; segIndex: Record<string, { from: Vec3; to: Vec3; length: number }>; beltSpeed: number; clockOffset: number }) {
  const ref = useRef<THREE.Group>(null);
  const mat = useRef<THREE.MeshStandardMaterial>(null);
  const select = useStore((s) => s.selectPackage);
  const selected = useStore((s) => s.selectedPackageId === pkg.id);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const color = PACKAGE_COLORS[pkg.type] ?? "#EAF2FF";
  useFrame(({ clock }) => {
    if (!ref.current || !pkg.routeStartedAt) return;
    const elapsed = (Date.now() + clockOffset - Date.parse(pkg.routeStartedAt)) / 1000;
    const at = packagePosition(pkg.route, segIndex, reduced && pkg.status !== "IN_TRANSIT" ? 1e9 : elapsed, beltSpeed);
    ref.current.position.set(at.position[0], at.position[1] + 0.55, at.position[2]);
    ref.current.rotation.y = reduced ? 0 : clock.elapsedTime * 0.8;
    if (mat.current) {
      // reached the end but the backend has not confirmed arrival: wait and pulse
      const waiting = at.done && pkg.status === "IN_TRANSIT";
      mat.current.emissiveIntensity = waiting && !reduced ? 0.5 + Math.abs(Math.sin(clock.elapsedTime * 6)) : 0.9;
    }
  });
  return (
    <group ref={ref} onClick={(e) => { e.stopPropagation(); select(pkg.id); }}>
      <mesh>
        <boxGeometry args={[0.95, 0.95, 0.95]} />
        <meshStandardMaterial ref={mat} color={color} emissive={color} emissiveIntensity={0.9} transparent opacity={0.85} />
      </mesh>
      <mesh visible={false}>
        <boxGeometry args={[1.4, 1.4, 1.4]} />
        <meshBasicMaterial />
      </mesh>
      {selected ? (
        <Html position={[0, 0.9, 0]} center zIndexRange={[15, 0]}>
          <div className="world-label rounded-md px-2 py-0.5 text-[11px]" style={{ transform: "none", background: "rgb(7 11 24 / .85)", color, border: `1px solid ${color}` }}>
            {pkg.type.replace("_", " ")}
          </div>
        </Html>
      ) : null}
    </group>
  );
}

export function Conveyors() {
  const logistics = useStore((s) => s.logistics);
  const routeStatus = useStore((s) => s.world.routeStatus);
  const packages = useStore((s) => s.world.packages);
  const clockOffset = useStore((s) => s.clockOffset);
  const { segs, nodes } = useSegments(logistics, routeStatus);
  const beltSpeed = logistics?.beltSpeed ?? 8;
  const segIndex = useMemo(() => Object.fromEntries(segs.map((s) => [s.id, { from: s.from, to: s.to, length: s.length }])), [segs]);
  const live = Object.values(packages).filter((p) => p.status === "IN_TRANSIT" && p.route.length);
  const load = useMemo(() => {
    const l: Record<string, number> = {};
    live.forEach((p) => p.route.forEach((r) => (l[r] = (l[r] ?? 0) + 1)));
    return l;
  }, [live]);
  const queues = useMemo(() => {
    const q: Record<string, number> = {};
    Object.values(packages).filter((p) => p.status === "ARRIVED").forEach((p) => (q[p.destination] = (q[p.destination] ?? 0) + 1));
    return q;
  }, [packages]);
  return (
    <group>
      {segs.map((s) => (
        <Belt key={s.id} s={s} load={load[s.id] ?? 0} />
      ))}
      <Slats segs={segs} />
      {nodes.filter((n) => n.kind !== "junction").map((n) => (
        <Terminal key={n.id} node={n} queue={n.kind === "receiving" ? queues[n.district ?? ""] ?? 0 : 0} color={n.kind === "dispatch" ? "#32D8FF" : "#5BF2A5"} />
      ))}
      {live.map((p) => (
        <Package key={p.id} pkg={p} segIndex={segIndex} beltSpeed={beltSpeed} clockOffset={clockOffset} />
      ))}
    </group>
  );
}
