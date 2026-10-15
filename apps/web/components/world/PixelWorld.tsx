"use client";

/**
 * Pixel-art scenery for the city (reference: an isometric cyberpunk city on floating islands): rock islands under
 * every district, waterfalls spilling off their edges, glowing neon signs, and flying cars. All of it is decoration;
 * none of it represents agent work or data. Agents, packages and buildings are drawn by their own components from
 * backend state.
 */
import { useFrame } from "@react-three/fiber";
import { DISTRICTS, PLAZA_RADIUS, type District as D } from "@aiciv/world-engine";
import { Html } from "@react-three/drei";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useStore } from "@/lib/store";

const ROCK = "#54456e";
const ROCK_DARK = "#3a2f52";
const GRASS = "#3f9e64";
const WATER = "#5fd8ff";

function islandRadius(d: D): number {
  return d.architecture === "bank" ? 19 : d.architecture === "spire" ? 15 : 17;
}

function deckSize(d: D): number {
  return d.architecture === "bank" ? 26 : d.architecture === "spire" ? 0 : 23;
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
      {DISTRICTS.map((d) => <Deck key={d.id} d={d} />)}
      <LogisticsHub />
      <Skyline />
      <SkyDome />
      <Islets />
      <FlyingCars />
    </group>
  );
}

/** Checkered floor tiles, drawn once and sampled without smoothing so they stay crisp pixels. */
function useTileTexture(color: string) {
  return useMemo(() => {
    const c = document.createElement("canvas");
    c.width = c.height = 16;
    const g = c.getContext("2d")!;
    const base = new THREE.Color(color).lerp(new THREE.Color("#2a2140"), 0.62);
    const alt = new THREE.Color(color).lerp(new THREE.Color("#3a2f58"), 0.5);
    for (let y = 0; y < 2; y++)
      for (let x = 0; x < 2; x++) {
        g.fillStyle = `#${((x + y) % 2 ? alt : base).getHexString()}`;
        g.fillRect(x * 8, y * 8, 8, 8);
      }
    g.fillStyle = "rgba(255,255,255,0.08)";
    g.fillRect(0, 0, 16, 1);
    g.fillRect(0, 0, 1, 16);
    const t = new THREE.CanvasTexture(c);
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(6, 6);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, [color]);
}

/** Lo-fi tree: a trunk and a faceted crown. */
function Tree({ x, z, s = 1, color }: { x: number; z: number; s?: number; color: string }) {
  return (
    <group position={[x, 0, z]} scale={s}>
      <mesh position={[0, 0.9, 0]}>
        <cylinderGeometry args={[0.18, 0.25, 1.8, 5]} />
        <meshStandardMaterial color="#5a3b2a" flatShading />
      </mesh>
      <mesh position={[0, 2.4, 0]}>
        <icosahedronGeometry args={[1.25, 0]} />
        <meshStandardMaterial color={color} flatShading roughness={0.9} emissive={color} emissiveIntensity={0.08} />
      </mesh>
    </group>
  );
}

const CROWNS = ["#2f8f5b", "#3aa66a", "#c25bd6", "#ff7ab8", "#2a7d6b"];

/**
 * Each district stands on a raised stone deck (reference art): tiled floor, a glowing rim in the district colour,
 * a back wall of screens, open-plan desks with monitors, and trees on the corners. Decoration: the agents, desks
 * that light up from real tool events, and packages are drawn by their own components.
 */
function Deck({ d }: { d: D }) {
  const W = deckSize(d);
  const tex = useTileTexture(d.color);
  const desks = useMemo(() => {
    const out: [number, number][] = [];
    if (!W) return out;
    for (const z of [2.5, 5.5])
      for (const x of [-8.5, -5.5, 5.5, 8.5]) out.push([x, z]);
    return out;
  }, [W]);
  if (!W) return null;
  const [x, , z] = d.position;
  const h = W / 2;
  return (
    <group position={[x, 0, z]}>
      {/* stone slab with a lit rim */}
      <mesh position={[0, -1.7, 0]}>
        <boxGeometry args={[W, 3.4, W]} />
        <meshStandardMaterial color="#4a3c6e" flatShading roughness={1} />
      </mesh>
      <mesh position={[0, 0.03, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[W - 0.6, W - 0.6]} />
        <meshStandardMaterial map={tex} roughness={0.9} />
      </mesh>
      {[[0, h], [0, -h], [h, 0], [-h, 0]].map(([dx, dz], i) => (
        <mesh key={i} position={[dx, 0.1, dz]} rotation={[0, i < 2 ? 0 : Math.PI / 2, 0]}>
          <boxGeometry args={[W, 0.2, 0.25]} />
          <meshBasicMaterial color={d.color} toneMapped={false} />
        </mesh>
      ))}
      {/* back wall of screens */}
      <mesh position={[0, 1.6, -h + 0.4]}>
        <boxGeometry args={[W - 1, 3.2, 0.5]} />
        <meshStandardMaterial color="#141b33" />
      </mesh>
      {[-7.5, -2.5, 2.5, 7.5].map((sx) => (
        <mesh key={sx} position={[sx, 1.9, -h + 0.7]}>
          <planeGeometry args={[3.6, 1.8]} />
          <meshBasicMaterial color={d.color} transparent opacity={0.55} toneMapped={false} />
        </mesh>
      ))}
      {/* open-plan desks with monitors */}
      {desks.map(([dx, dz], i) => (
        <group key={i} position={[dx, 0, dz]}>
          <mesh position={[0, 0.45, 0]}>
            <boxGeometry args={[2.2, 0.9, 1.1]} />
            <meshStandardMaterial color="#3a2f52" flatShading />
          </mesh>
          <mesh position={[0, 1.35, -0.35]}>
            <boxGeometry args={[1.3, 0.85, 0.08]} />
            <meshStandardMaterial color="#0b1020" />
          </mesh>
          <mesh position={[0, 1.35, -0.3]}>
            <planeGeometry args={[1.15, 0.7]} />
            <meshBasicMaterial color={i % 3 ? d.color : "#9fe8ff"} toneMapped={false} />
          </mesh>
        </group>
      ))}
      {/* trees on the corners */}
      {[[-h + 1.6, -h + 1.6], [h - 1.6, -h + 1.6], [-h + 1.6, h - 1.6], [h - 1.6, h - 1.6]].map(([tx, tz], i) => (
        <Tree key={i} x={tx} z={tz} s={1 + (i % 2) * 0.3} color={CROWNS[(i + d.id.length) % CROWNS.length]} />
      ))}
    </group>
  );
}

/** The conveyor hub in front of the Nexus Spire, labeled like the reference: the belts themselves are real. */
function LogisticsHub() {
  return (
    <group position={[0, 0, 21]}>
      <mesh position={[0, 0.2, 0]}>
        <cylinderGeometry args={[4, 4.4, 0.4, 8]} />
        <meshStandardMaterial color="#2b2342" flatShading />
      </mesh>
      <mesh position={[0, 0.42, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[3.2, 3.6, 8]} />
        <meshBasicMaterial color="#F4D58D" toneMapped={false} />
      </mesh>
      <Html position={[0, 4, 0]} center zIndexRange={[6, 0]}>
        <div className="neon-sign" style={{ "--c": "#F4D58D", cursor: "default" } as React.CSSProperties}>
          <span className="neon-icon" aria-hidden>▣</span>
          <span>Logistics Network</span>
        </div>
      </Html>
    </group>
  );
}

/** Distant skyline with lit windows. Not part of the city's state; ignores fog so it reads as a backdrop. */
function Skyline() {
  const windows = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = 16;
    c.height = 64;
    const g = c.getContext("2d")!;
    g.fillStyle = "#0d1030";
    g.fillRect(0, 0, 16, 64);
    for (let y = 2; y < 64; y += 4)
      for (let x = 2; x < 16; x += 4) {
        const r = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453;
        const v = r - Math.floor(r);
        g.fillStyle = v > 0.72 ? "#ffd27a" : v > 0.55 ? "#7fd8ff" : v > 0.45 ? "#ff7ad9" : "#141a40";
        g.fillRect(x, y, 2, 2);
      }
    const t = new THREE.CanvasTexture(c);
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }, []);
  const towers = useMemo(() => {
    const out: { x: number; z: number; w: number; h: number; spire: boolean }[] = [];
    for (let i = 0; i < 110; i++) {
      const a = (i / 110) * Math.PI * 2 + Math.sin(i * 7.1) * 0.02;
      // keep the view toward the camera (south) open
      if (Math.sin(a) > 0.55) continue;
      const r = 300 + ((i * 37) % 60);
      out.push({ x: Math.cos(a) * r, z: Math.sin(a) * r, w: 6 + (i % 5) * 2, h: 25 + ((i * 53) % 45), spire: i % 9 === 0 });
    }
    return out;
  }, []);
  return (
    <group position={[0, -60, 0]}>
      {towers.map((t, i) => (
        <group key={i} position={[t.x, 0, t.z]}>
          <mesh position={[0, t.h / 2, 0]}>
            <boxGeometry args={[t.w, t.h, t.w]} />
            <meshBasicMaterial map={windows} fog={false} color="#c9ccff" />
          </mesh>
          {t.spire ? (
            <mesh position={[0, t.h + 10, 0]}>
              <coneGeometry args={[t.w * 0.35, 20, 4]} />
              <meshBasicMaterial color="#c86bff" fog={false} toneMapped={false} />
            </mesh>
          ) : null}
        </group>
      ))}
    </group>
  );
}

/** Dusk sky: navy overhead, violet in the middle, a warm band at the horizon, and a few stars. */
function SkyDome() {
  const stars = useMemo(() => {
    const p = new Float32Array(600 * 3);
    for (let i = 0; i < 600; i++) {
      const a = Math.random() * Math.PI * 2;
      const e = 0.25 + Math.random() * 1.2;
      p.set([Math.cos(a) * Math.cos(e) * 380, Math.sin(e) * 380, Math.sin(a) * Math.cos(e) * 380], i * 3);
    }
    return p;
  }, []);
  return (
    <group>
      <mesh>
        <sphereGeometry args={[420, 32, 16]} />
        <shaderMaterial
          side={THREE.BackSide}
          depthWrite={false}
          fog={false}
          vertexShader="varying vec3 vP; void main(){ vP = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }"
          fragmentShader={`varying vec3 vP;
            void main(){
              float h = vP.y;
              vec3 top = vec3(0.04, 0.05, 0.17);
              vec3 mid = vec3(0.23, 0.11, 0.38);
              vec3 low = vec3(0.98, 0.45, 0.42);
              vec3 deep = vec3(0.05, 0.05, 0.16);
              vec3 c = h > 0.18 ? mix(mid, top, smoothstep(0.18, 0.7, h))
                     : h > 0.0 ? mix(low, mid, smoothstep(0.0, 0.18, h))
                     : mix(low * 0.55, deep, smoothstep(0.0, -0.22, h));
              gl_FragColor = vec4(c, 1.0);
            }`}
        />
      </mesh>
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[stars, 3]} />
        </bufferGeometry>
        <pointsMaterial color="#ffffff" size={1.6} sizeAttenuation={false} fog={false} />
      </points>
    </group>
  );
}
