"use client";

import { Html } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { routeLength, sampleRoute, type WorldAgent } from "@aiciv/world-engine";
import { useEffect, useMemo, useReducer, useRef } from "react";
import * as THREE from "three";
import { useStore } from "@/lib/store";
import { ChibiFigure } from "./Chibi";

const WALK_SPEED = 9; // world units per second — configurable movement speed
const STATE_COLOR: Record<string, string> = {
  IDLE: "#8FA8FF",
  ASSIGNED: "#32D8FF",
  PLANNING: "#32D8FF",
  EXECUTING: "#5BF2A5",
  WAITING_FOR_TOOL: "#5BF2A5",
  WAITING_FOR_AGENT: "#FFBD69",
  WAITING_FOR_APPROVAL: "#FFBD69",
  REVIEWING: "#A66BFF",
  COMPLETED: "#5BF2A5",
  FAILED: "#FF6178",
  CANCELLED: "#FF6178",
};

/** Distinct silhouettes so agents are recognizable from far away without reading a label. */
function Body({ shape, color, height }: { shape: string; color: string; height: number }) {
  const mat = <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.55} metalness={0.3} roughness={0.35} />;
  switch (shape) {
    case "crown":
      return (
        <group>
          <mesh position={[0, height * 0.42, 0]}>
            <coneGeometry args={[0.55, height * 0.84, 6]} />
            {mat}
          </mesh>
          <mesh position={[0, height * 0.95, 0]} rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.38, 0.07, 8, 24]} />
            <meshBasicMaterial color={color} toneMapped={false} />
          </mesh>
        </group>
      );
    case "pillar":
      return (
        <mesh position={[0, height / 2, 0]}>
          <capsuleGeometry args={[0.32, height - 0.64, 6, 12]} />
          {mat}
        </mesh>
      );
    case "cube":
      return (
        <group>
          <mesh position={[0, height * 0.32, 0]}>
            <boxGeometry args={[0.8, height * 0.64, 0.6]} />
            {mat}
          </mesh>
          <mesh position={[0, height * 0.82, 0]} rotation={[0.6, 0.6, 0]}>
            <boxGeometry args={[0.45, 0.45, 0.45]} />
            {mat}
          </mesh>
        </group>
      );
    case "shield":
      return (
        <mesh position={[0, height / 2, 0]} scale={[1, 1, 0.35]}>
          <cylinderGeometry args={[0.55, 0.25, height, 5]} />
          {mat}
        </mesh>
      );
    case "orb":
      return (
        <group>
          <mesh position={[0, height * 0.75, 0]}>
            <sphereGeometry args={[0.42, 24, 16]} />
            {mat}
          </mesh>
          <mesh position={[0, height * 0.3, 0]}>
            <cylinderGeometry args={[0.08, 0.3, height * 0.6, 8]} />
            {mat}
          </mesh>
        </group>
      );
    case "monolith":
      return (
        <group>
          <mesh position={[0, height / 2, 0]}>
            <boxGeometry args={[0.7, height, 0.35]} />
            {mat}
          </mesh>
          <mesh position={[0, height + 0.25, 0]} rotation={[Math.PI / 2, 0, 0]}>
            <torusGeometry args={[0.55, 0.05, 8, 32]} />
            <meshBasicMaterial color="#F4D58D" toneMapped={false} />
          </mesh>
        </group>
      );
    case "drone":
      return (
        <group position={[0, height * 0.8, 0]}>
          <mesh>
            <sphereGeometry args={[0.3, 16, 12]} />
            {mat}
          </mesh>
          {[0, Math.PI / 2].map((r) => (
            <mesh key={r} rotation={[0, r, 0]}>
              <boxGeometry args={[1.3, 0.06, 0.12]} />
              {mat}
            </mesh>
          ))}
        </group>
      );
    default:
      return (
        <mesh position={[0, height * 0.55, 0]}>
          <octahedronGeometry args={[0.6, 0]} />
          {mat}
        </mesh>
      );
  }
}

function bubbleStyle(kind: string): { color: string; label: string } {
  switch (kind) {
    case "approval":
      return { color: "#FFBD69", label: "Needs approval" };
    case "error":
      return { color: "#FF6178", label: "Problem" };
    case "tool":
      return { color: "#5BF2A5", label: "Using" };
    case "complete":
      return { color: "#5BF2A5", label: "Done" };
    case "assignment":
      return { color: "#32D8FF", label: "Assigned" };
    default:
      return { color: "#A66BFF", label: "Says" };
  }
}

/** A big chibi head with pixel eyes on top of the silhouette, so agents read as characters. */
function ChibiFace({ height, color }: { height: number; color: string }) {
  const y = height + 0.35;
  return (
    <group position={[0, y, 0]}>
      <mesh>
        <boxGeometry args={[0.9, 0.8, 0.8]} />
        <meshStandardMaterial color="#F6D7B8" roughness={0.8} />
      </mesh>
      <mesh position={[0, 0.38, 0]}>
        <boxGeometry args={[0.98, 0.2, 0.88]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.4} />
      </mesh>
      {[-0.2, 0.2].map((x) => (
        <mesh key={x} position={[x, 0, 0.41]}>
          <boxGeometry args={[0.12, 0.18, 0.02]} />
          <meshBasicMaterial color="#0b1226" />
        </mesh>
      ))}
    </group>
  );
}

export function AgentAvatar({ agent, positions }: { agent: WorldAgent; positions: Map<string, THREE.Vector3> }) {
  const group = useRef<THREE.Group>(null);
  const body = useRef<THREE.Group>(null);
  const selected = useStore((s) => s.selectedAgentId === agent.id);
  const select = useStore((s) => s.selectAgent);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const labels = useStore((s) => s.settings.labels);
  const clock = useStore((s) => s.clock);
  const total = useMemo(() => routeLength(agent.route), [agent.route]);
  const color = STATE_COLOR[agent.execState] ?? "#8FA8FF";
  const motion = useRef({ walking: false });
  const scale = 1.05 + (agent.height - 1.4) * 0.35; // taller roles stand a little taller
  const figH = agent.look ? 2.1 * scale : agent.height;

  useFrame(({ clock: c }) => {
    if (!group.current) return;
    const elapsed = (clock() - agent.routeStartedAt) / 1000;
    const travelled = reduced ? total : elapsed * WALK_SPEED;
    const s = sampleRoute(agent.route, travelled);
    group.current.position.set(s.position[0], 0, s.position[2]);
    if (!s.done) group.current.rotation.y = s.heading;
    if (body.current) {
      const walking = !s.done && !reduced;
      motion.current.walking = walking;
      body.current.position.y = walking ? Math.abs(Math.sin(c.elapsedTime * 10)) * 0.18 : reduced ? 0 : Math.sin(c.elapsedTime * 2 + agent.id.charCodeAt(0)) * 0.05;
    }
    const v = positions.get(agent.id) ?? new THREE.Vector3();
    v.copy(group.current.position);
    positions.set(agent.id, v);
  });

  const ind = agent.indicator;
  const [, rerender] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (!ind || ind.kind === "approval") return;
    const t = window.setTimeout(rerender, 4600);
    return () => clearTimeout(t);
  }, [ind]);
  const showBubble = ind && (ind.kind === "approval" || clock() - ind.at < 4500);
  const b = ind ? bubbleStyle(ind.kind) : null;

  return (
    <group
      ref={group}
      onClick={(e) => {
        e.stopPropagation();
        select(agent.id);
      }}
    >
      <group ref={body}>
        {agent.look ? (
          <group scale={scale}>
            <ChibiFigure look={agent.look} motion={motion} />
          </group>
        ) : (
          <>
            <Body shape={agent.shape} color={agent.color} height={agent.height} />
            <ChibiFace height={agent.height} color={agent.color} />
          </>
        )}
        {agent.carrying ? (
          // the holographic package an agent carries to its dispatch terminal
          <mesh position={[0, figH + 0.6, 0]} rotation={[0.4, 0.6, 0]}>
            <boxGeometry args={[0.6, 0.6, 0.6]} />
            <meshStandardMaterial color="#5BF2A5" emissive="#5BF2A5" emissiveIntensity={1.1} transparent opacity={0.7} />
          </mesh>
        ) : null}
      </group>
      {/* status ring = execution state; independent of whether the avatar is walking */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
        <ringGeometry args={[0.75, selected ? 1.05 : 0.9, 32]} />
        <meshBasicMaterial color={color} toneMapped={false} transparent opacity={0.9} />
      </mesh>
      {/* generous invisible hit target for fingers */}
      <mesh position={[0, figH / 2, 0]} visible={false}>
        <cylinderGeometry args={[1.1, 1.1, figH + 0.6, 8]} />
        <meshBasicMaterial />
      </mesh>
      {labels || selected ? (
        <Html position={[0, figH + (agent.look ? 0.6 : 1.4), 0]} center zIndexRange={[20, 0]}>
          <div className="world-label flex flex-col items-center gap-1" style={{ transform: "none" }}>
            {showBubble && b && ind!.kind === "message" ? (
              // pixel speech bubble: what the agent just said to another agent
              <div className="speech relative" data-testid="speech-bubble">
                {ind!.text.length > 90 ? `${ind!.text.slice(0, 88)}…` : ind!.text}
                <span className="absolute -bottom-[7px] left-1/2 size-0 -translate-x-1/2 border-x-[6px] border-t-[7px] border-x-transparent border-t-[#0b1226]" />
              </div>
            ) : showBubble && b ? (
              <div className="max-w-[200px] truncate rounded px-2 py-1 text-[11px]" style={{ background: "rgb(7 11 24 / .85)", border: `2px solid ${b.color}`, color: "#EAF2FF" }}>
                <span style={{ color: b.color }}>{b.label}</span> {ind!.text.replaceAll("_", " ")}
              </div>
            ) : null}
            <div className="rounded-full px-2 py-0.5 text-[11px] font-medium" style={{ background: selected ? agent.color : "rgb(7 11 24 / .7)", color: selected ? "#070B18" : agent.color }}>
              {agent.name}
            </div>
          </div>
        </Html>
      ) : null}
    </group>
  );
}
