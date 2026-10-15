"use client";

/**
 * Pixel-art scenery for the city (reference: an isometric cyberpunk city on floating islands): rock islands under
 * every district, waterfalls spilling off their edges, glowing neon signs, and flying cars. All of it is decoration;
 * none of it represents agent work or data. Agents, packages and buildings are drawn by their own components from
 * backend state.
 */
import { useFrame } from "@react-three/fiber";
import { DISTRICTS, PLAZA_RADIUS, type District as D } from "@aiciv/world-engine";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useStore } from "@/lib/store";

const ROCK = "#3a2f4a";
const ROCK_DARK = "#241c33";
const GRASS = "#2f7d5b";
const WATER = "#5fd8ff";

function islandRadius(d: D): number {
  return d.architecture === "bank" ? 17 : 14;
}

/** A faceted rock island: a grassy disc on top of an inverted, jagged cone. */
function Island({ x, z, r, depth, seed }: { x: number; z: number; r: number; depth: number; seed: number }) {
  const geo = useMemo(() => {
    const g = new THREE.ConeGeometry(r, depth, 9, 3, false);
    const pos = g.attributes.position as THREE.BufferAttribute;
    for (let i = 0; i < pos.count; i++) {
      const y = pos.getY(i);
      if (y > depth / 2 - 0.01) continue; // keep the rim flat
      const k = 0.75 + (((Math.sin(i * 12.9898 + seed) * 43758.5453) % 1) + 1) % 1 * 0.5;
      pos.setX(i, pos.getX(i) * k);
      pos.setZ(i, pos.getZ(i) * k);
    }
    g.computeVertexNormals();
    return g;
  }, [r, depth, seed]);
  return (
    <group position={[x, 0, z]}>
      <mesh position={[0, -depth / 2 - 0.35, 0]} rotation={[Math.PI, seed, 0]} geometry={geo}>
        <meshStandardMaterial color={ROCK} flatShading roughness={1} />
      </mesh>
      <mesh position={[0, -0.2, 0]}>
        <cylinderGeometry args={[r * 1.02, r * 0.98, 0.5, 9]} />
        <meshStandardMaterial color={GRASS} flatShading roughness={0.9} />
      </mesh>
      <mesh position={[0, -0.75, 0]}>
        <cylinderGeometry args={[r * 0.98, r * 0.9, 0.7, 9]} />
        <meshStandardMaterial color={ROCK_DARK} flatShading />
      </mesh>
    </group>
  );
}

/** A falling sheet of water with bands that scroll downward, plus a glowing pool of mist below. */
function Waterfall({ x, z, angle, height, width }: { x: number; z: number; angle: number; height: number; width: number }) {
  const mat = useRef<THREE.ShaderMaterial>(null);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uColor: { value: new THREE.Color(WATER) } }), []);
  useFrame((_, dt) => {
    if (mat.current && !reduced) mat.current.uniforms.uTime.value += dt;
  });
  return (
    <group position={[x, 0, z]} rotation={[0, angle, 0]}>
      <mesh position={[0, -height / 2 - 0.2, 0]}>
        <planeGeometry args={[width, height, 1, 1]} />
        <shaderMaterial
          ref={mat}
          transparent
          depthWrite={false}
          side={THREE.DoubleSide}
          uniforms={uniforms}
          vertexShader="varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }"
          fragmentShader={`uniform float uTime; uniform vec3 uColor; varying vec2 vUv;
            void main(){
              float bands = step(0.5, fract(vUv.y * 9.0 + uTime * 1.6 + floor(vUv.x * 4.0) * 0.37));
              float edge = smoothstep(0.0, 0.12, vUv.x) * smoothstep(1.0, 0.88, vUv.x);
              float fade = smoothstep(0.0, 0.35, vUv.y);
              vec3 c = mix(uColor * 0.75, vec3(0.92, 1.0, 1.0), bands * 0.6);
              gl_FragColor = vec4(c, (0.55 + bands * 0.35) * edge * fade);
            }`}
        />
      </mesh>
      <mesh position={[0, -height - 0.2, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[width * 0.9, 8]} />
        <meshBasicMaterial color={WATER} transparent opacity={0.25} toneMapped={false} />
      </mesh>
    </group>
  );
}

/** A neon sign on a post at the edge of a district, facing the plaza. */
function NeonSign({ d }: { d: D }) {
  const [x, , z] = d.position;
  const toward = new THREE.Vector3(-x, 0, -z);
  if (toward.lengthSq() === 0) toward.set(0, 0, 1);
  toward.normalize();
  const p = new THREE.Vector3(x, 0, z).add(toward.clone().multiplyScalar(islandRadius(d) - 3)).add(new THREE.Vector3(toward.z, 0, -toward.x).multiplyScalar(6));
  const yaw = Math.atan2(toward.x, toward.z);
  const glow = useRef<THREE.MeshBasicMaterial>(null);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const seed = d.id.length;
  useFrame(({ clock }) => {
    if (!glow.current || reduced) return;
    // a cheap neon flicker every few seconds
    const t = clock.elapsedTime + seed;
    glow.current.opacity = Math.sin(t * 0.7) > 0.97 && Math.sin(t * 40) > 0 ? 0.35 : 1;
  });
  return (
    <group position={[p.x, 0, p.z]} rotation={[0, yaw, 0]}>
      <mesh position={[0, 3, 0]}>
        <boxGeometry args={[0.25, 6, 0.25]} />
        <meshStandardMaterial color="#1b2340" />
      </mesh>
      <mesh position={[0, 6.6, 0]}>
        <boxGeometry args={[5.6, 1.6, 0.2]} />
        <meshStandardMaterial color="#0b1226" />
      </mesh>
      <mesh position={[0, 6.6, 0.12]}>
        <planeGeometry args={[5.2, 1.2]} />
        <meshBasicMaterial ref={glow} color={d.color} transparent toneMapped={false} />
      </mesh>
      {Array.from({ length: 5 }, (_, i) => (
        <mesh key={i} position={[-2 + i, 6.6, 0.14]}>
          <planeGeometry args={[0.55, 0.55]} />
          <meshBasicMaterial color="#070B18" />
        </mesh>
      ))}
    </group>
  );
}

/** Flying cars on looping sky lanes: body plus head- and tail-lights. Decoration only. */
function FlyingCars() {
  const count = 28;
  const body = useRef<THREE.InstancedMesh>(null);
  const lights = useRef<THREE.InstancedMesh>(null);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const on = useStore((s) => s.settings.drones);
  const lanes = useMemo(
    () => Array.from({ length: count }, (_, i) => ({ r: 26 + (i % 5) * 11, h: 16 + (i % 4) * 5, speed: 0.06 + (i % 6) * 0.02, phase: (i * 2.399) % (Math.PI * 2), dir: i % 2 ? 1 : -1 })),
    [],
  );
  const colors = useMemo(() => ["#FF6178", "#32D8FF", "#F4D58D", "#A66BFF", "#5BF2A5"], []);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  useFrame(({ clock }) => {
    if (!body.current || !lights.current) return;
    lanes.forEach((l, i) => {
      const a = l.phase + (reduced ? 0 : clock.elapsedTime * l.speed * l.dir);
      dummy.position.set(Math.cos(a) * l.r, l.h + Math.sin(a * 3) * 0.6, Math.sin(a) * l.r);
      dummy.rotation.set(0, -a + (l.dir > 0 ? 0 : Math.PI), 0);
      dummy.updateMatrix();
      body.current!.setMatrixAt(i, dummy.matrix);
      dummy.translateZ(l.dir > 0 ? 0.9 : -0.9);
      dummy.updateMatrix();
      lights.current!.setMatrixAt(i, dummy.matrix);
    });
    body.current.instanceMatrix.needsUpdate = true;
    lights.current.instanceMatrix.needsUpdate = true;
  });
  const tint = useMemo(() => {
    const arr = new Float32Array(count * 3);
    const c = new THREE.Color();
    for (let i = 0; i < count; i++) {
      c.set(colors[i % colors.length]);
      arr.set([c.r, c.g, c.b], i * 3);
    }
    return arr;
  }, [colors]);
  if (!on) return null;
  return (
    <group>
      <instancedMesh ref={body} args={[undefined, undefined, count]}>
        <boxGeometry args={[0.9, 0.45, 1.8]}>
          <instancedBufferAttribute attach="attributes-color" args={[tint, 3]} />
        </boxGeometry>
        <meshStandardMaterial vertexColors metalness={0.4} roughness={0.4} emissive="#111" />
      </instancedMesh>
      <instancedMesh ref={lights} args={[undefined, undefined, count]}>
        <boxGeometry args={[0.8, 0.12, 0.12]} />
        <meshBasicMaterial color="#FFF6C8" toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

/** Small islets drifting around the city. */
function Islets() {
  const group = useRef<THREE.Group>(null);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const spots = useMemo(() => [[-78, 8, -40, 5], [70, 12, -52, 4], [86, 6, 30, 6], [-80, 14, 46, 4], [20, 18, 72, 3.5], [-24, 10, -74, 4.5]], []);
  useFrame(({ clock }) => {
    if (!group.current || reduced) return;
    group.current.children.forEach((c, i) => (c.position.y = spots[i][1] + Math.sin(clock.elapsedTime * 0.5 + i) * 0.8));
  });
  return (
    <group ref={group}>
      {spots.map(([x, y, z, r], i) => (
        <group key={i} position={[x, y, z]}>
          <Island x={0} z={0} r={r} depth={r * 2.2} seed={i * 3.1} />
          <mesh position={[0, 1.2, 0]}>
            <coneGeometry args={[r * 0.35, 2.6, 5]} />
            <meshStandardMaterial color="#1f6b4a" flatShading />
          </mesh>
        </group>
      ))}
    </group>
  );
}

export function PixelWorld() {
  const falls = useMemo(
    () =>
      DISTRICTS.filter((_, i) => i % 2 === 0).map((d, i) => {
        const [x, , z] = d.position;
        const out = new THREE.Vector3(x, 0, z);
        if (out.lengthSq() === 0) out.set(0.5, 0, 1);
        out.normalize();
        const r = islandRadius(d) * 0.98;
        const side = i % 2 ? 1 : -1;
        const dir = out.clone().applyAxisAngle(new THREE.Vector3(0, 1, 0), side * 0.6);
        return { x: x + dir.x * r, z: z + dir.z * r, angle: Math.atan2(dir.x, dir.z), height: 18 + (i % 3) * 5, width: 2.4 + (i % 2) };
      }),
    [],
  );
  return (
    <group>
      {/* the plaza's own island */}
      <Island x={0} z={0} r={PLAZA_RADIUS + 3} depth={20} seed={0.7} />
      {DISTRICTS.map((d, i) => (
        <Island key={d.id} x={d.position[0]} z={d.position[2]} r={islandRadius(d)} depth={16 + (i % 3) * 6} seed={i * 1.7} />
      ))}
      {falls.map((f, i) => <Waterfall key={i} {...f} />)}
      {DISTRICTS.filter((d) => d.id !== "nexus-spire").map((d) => <NeonSign key={d.id} d={d} />)}
      <Islets />
      <FlyingCars />
    </group>
  );
}
