"use client";

import { AdaptiveDpr, Grid, OrbitControls, PerformanceMonitor } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { DISTRICT_BY_ID, DISTRICTS, PLAZA_RADIUS, workstationPosition } from "@aiciv/world-engine";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
type OrbitImpl = React.ComponentRef<typeof OrbitControls>;
import { useStore } from "@/lib/store";
import { AgentAvatar } from "./AgentAvatar";
import { Conveyors } from "./Conveyors";
import { District } from "./District";

const OVERVIEW = { pos: new THREE.Vector3(66, 80, 84), target: new THREE.Vector3(0, 0, -2) };

function Plaza() {
  const ring = useRef<THREE.Mesh>(null);
  const celebrate = useStore((s) => s.world.celebrate);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const clock = useStore((s) => s.clock);
  useFrame(({ clock: c }) => {
    if (!ring.current) return;
    const m = ring.current.material as THREE.MeshBasicMaterial;
    const since = celebrate ? (clock() - celebrate.at) / 1000 : 99;
    m.color.set(since < 6 ? "#5BF2A5" : "#32D8FF");
    m.opacity = since < 6 && !reduced ? 0.6 + Math.sin(c.elapsedTime * 8) * 0.3 : 0.55;
  });
  return (
    <group>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.04, 0]}>
        <ringGeometry args={[PLAZA_RADIUS - 0.25, PLAZA_RADIUS + 0.25, 96]} />
        <meshBasicMaterial color="#32D8FF" transparent opacity={0.55} toneMapped={false} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.015, 0]}>
        <circleGeometry args={[PLAZA_RADIUS + 1.5, 96]} />
        <meshStandardMaterial color="#0b1224" metalness={0.5} roughness={0.6} />
      </mesh>
    </group>
  );
}

/** Ambient traffic. Pure decoration, labeled as such in World settings — never mistaken for agent work. */
function Drones() {
  const count = 36;
  const mesh = useRef<THREE.InstancedMesh>(null);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const on = useStore((s) => s.settings.drones);
  const lanes = useMemo(
    () => Array.from({ length: count }, (_, i) => ({ r: 22 + (i % 6) * 9, h: 14 + (i % 5) * 4, speed: 0.08 + (i % 7) * 0.025, phase: (i * 2.399) % (Math.PI * 2), dir: i % 2 ? 1 : -1 })),
    [],
  );
  const dummy = useMemo(() => new THREE.Object3D(), []);
  useFrame(({ clock }) => {
    if (!mesh.current) return;
    lanes.forEach((l, i) => {
      const a = l.phase + (reduced ? 0 : clock.elapsedTime * l.speed * l.dir);
      dummy.position.set(Math.cos(a) * l.r, l.h, Math.sin(a) * l.r);
      dummy.rotation.y = -a;
      dummy.updateMatrix();
      mesh.current!.setMatrixAt(i, dummy.matrix);
    });
    mesh.current.instanceMatrix.needsUpdate = true;
  });
  if (!on) return null;
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, count]}>
      <boxGeometry args={[0.9, 0.18, 0.4]} />
      <meshBasicMaterial color="#A66BFF" toneMapped={false} />
    </instancedMesh>
  );
}

/** Keeps the city centred in the part of the screen the command panel does not cover. */
function ViewFit() {
  const { camera, size, scene } = useThree();
  const sheet = useStore((s) => s.sheet);
  useEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    const desktop = size.width >= 1024;
    const panelX = desktop ? 444 : 0;
    const peek = { peek: 168, half: size.height * 0.52, full: size.height * 0.52 }[sheet];
    const panelY = desktop ? 0 : peek * 0.5;
    const k = size.width < size.height ? Math.min(2.1, 1.05 / (size.width / size.height)) : 1;
    if (scene.fog instanceof THREE.Fog) {
      scene.fog.near = 70 * k;
      scene.fog.far = 210 * k;
    }
    if (panelX || panelY) cam.setViewOffset(size.width + panelX, size.height + panelY, panelX, panelY, size.width, size.height);
    else cam.clearViewOffset();
    cam.updateProjectionMatrix();
  }, [camera, size, sheet, scene]);
  return null;
}

function overviewFor(aspect: number) {
  const k = aspect < 1 ? Math.min(2.1, 1.05 / aspect) : 1;
  return { pos: OVERVIEW.pos.clone().multiplyScalar(k), target: OVERVIEW.target.clone() };
}

function CameraRig({ positions }: { positions: Map<string, THREE.Vector3> }) {
  const controls = useRef<OrbitImpl>(null);
  const { camera, size } = useThree();
  const mode = useStore((s) => s.camera);
  const selected = useStore((s) => s.selectedAgentId);
  const focused = useStore((s) => s.focusedDistrict);
  const interior = useStore((s) => s.interior);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const goal = useRef<{ pos: THREE.Vector3; target: THREE.Vector3 } | null>(overviewFor(size.width / size.height));
  const keys = useRef<Record<string, boolean>>({});

  useEffect(() => {
    if (mode === "overview") goal.current = overviewFor(size.width / size.height);
  }, [mode, size.width, size.height]);

  useEffect(() => {
    if (!focused) return;
    const d = DISTRICT_BY_ID[focused];
    if (!d) return;
    const c = new THREE.Vector3(...d.position);
    if (interior) {
      const ws = new THREE.Vector3(...workstationPosition(d.id, d.workstations[0]?.id));
      const out = ws.clone().sub(c).setY(0).normalize();
      goal.current = { pos: ws.clone().add(out.multiplyScalar(7)).setY(4), target: ws.clone().setY(1) };
    } else {
      const out = c.clone().setY(0).normalize();
      if (out.lengthSq() === 0) out.set(0, 0, 1);
      goal.current = { pos: c.clone().add(out.multiplyScalar(30)).setY(24), target: c.clone().setY(4) };
    }
  }, [focused, interior]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest?.("input,textarea")) return;
      keys.current[e.key.toLowerCase()] = true;
    };
    const up = (e: KeyboardEvent) => (keys.current[e.key.toLowerCase()] = false);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  useFrame((_, dt) => {
    const ctl = controls.current;
    if (!ctl) return;
    const k = reduced ? 1 : 1 - Math.pow(0.02, dt);
    if (mode === "follow" && selected) {
      const p = positions.get(selected);
      if (p) {
        const target = p.clone().setY(1.5);
        const offset = camera.position.clone().sub(ctl.target);
        if (offset.length() > 26 || offset.length() < 8) offset.setLength(16);
        if (offset.y < 6) offset.y = 8;
        ctl.target.lerp(target, k);
        camera.position.lerp(target.clone().add(offset), k);
      }
    } else if (mode === "fly") {
      const speed = 30 * dt * (keys.current["shift"] ? 2.5 : 1);
      const fwd = ctl.target.clone().sub(camera.position).setY(0).normalize();
      const right = new THREE.Vector3().crossVectors(fwd, new THREE.Vector3(0, 1, 0));
      const move = new THREE.Vector3();
      if (keys.current["w"]) move.add(fwd);
      if (keys.current["s"]) move.sub(fwd);
      if (keys.current["d"]) move.add(right);
      if (keys.current["a"]) move.sub(right);
      if (keys.current["e"]) move.y += 1;
      if (keys.current["q"]) move.y -= 1;
      if (move.lengthSq()) {
        move.normalize().multiplyScalar(speed);
        camera.position.add(move);
        ctl.target.add(move);
      }
    } else if (goal.current) {
      camera.position.lerp(goal.current.pos, k);
      ctl.target.lerp(goal.current.target, k);
      if (camera.position.distanceTo(goal.current.pos) < 0.3) goal.current = null;
    }
    ctl.update();
  });

  return (
    <OrbitControls
      ref={controls}
      makeDefault
      enableDamping
      maxPolarAngle={Math.PI / 2.08}
      minDistance={4}
      maxDistance={180}
      screenSpacePanning={mode === "fly"}
      onStart={() => {
        goal.current = null;
      }}
    />
  );
}

export function CityScene() {
  const agents = useStore((s) => s.world.agents);
  const quality = useStore((s) => s.settings.quality);
  const focus = useStore((s) => s.focusDistrict);
  const select = useStore((s) => s.selectAgent);
  const [degraded, setDegraded] = useState(false);
  const positions = useMemo(() => new Map<string, THREE.Vector3>(), []);
  const low = quality === "low" || (quality === "auto" && degraded);

  return (
    <Canvas
      className="!fixed inset-0"
      camera={{ position: OVERVIEW.pos.toArray(), fov: 45, near: 0.5, far: 600 }}
      dpr={low ? [1, 1.25] : [1, 2]}
      gl={{ antialias: !low, powerPreference: "high-performance" }}
      onPointerMissed={() => {
        focus(null);
        select(null);
        useStore.getState().selectPackage(null);
      }}
      aria-label="3D city of AI agents"
    >
      <color attach="background" args={["#070B18"]} />
      <fog attach="fog" args={["#070B18", 70, 210]} />
      <ambientLight intensity={0.35} color="#8FA8FF" />
      <hemisphereLight args={["#32D8FF", "#070B18", 0.4]} />
      <directionalLight position={[40, 80, 20]} intensity={0.6} color="#A66BFF" />
      <PerformanceMonitor onDecline={() => setDegraded(true)} onIncline={() => setDegraded(false)} />
      <AdaptiveDpr pixelated />
      <Suspense fallback={null}>
        <Grid
          position={[0, 0, 0]}
          args={[400, 400]}
          cellSize={4}
          cellThickness={0.5}
          cellColor="#1a2a4d"
          sectionSize={20}
          sectionThickness={1}
          sectionColor="#24407a"
          fadeDistance={190}
          fadeStrength={1.5}
          infiniteGrid
        />
        <Plaza />
        {DISTRICTS.map((d) => (
          <District key={d.id} d={d} />
        ))}
        {Object.values(agents).map((a) => (
          <AgentAvatar key={a.id} agent={a} positions={positions} />
        ))}
        <Conveyors />
        <Drones />
      </Suspense>
      <ViewFit />
      <CameraRig positions={positions} />
      {!low ? (
        <EffectComposer multisampling={0}>
          <Bloom mipmapBlur intensity={0.9} luminanceThreshold={0.55} luminanceSmoothing={0.2} />
        </EffectComposer>
      ) : (
        <></>
      )}
    </Canvas>
  );
}
