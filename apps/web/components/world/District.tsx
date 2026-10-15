"use client";

import { Html, Line } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { gatePosition, PLAZA_RADIUS, type District as D } from "@aiciv/world-engine";
import { useEffect, useMemo, useReducer, useRef } from "react";
import { SEED } from "@aiciv/shared-types";
import { useQuery } from "@tanstack/react-query";
import { factories, type Json } from "@/lib/api";
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
          out.push({ pos: [x, (h / 5) * (k + 0.5), -3], size: [3, h / 5 - 0.25, 3], rot: (k * Math.PI) / 14 + i, kind: "box" });
      }
      break;
    case "dome":
      out.push({ pos: [0, 0, -3], size: [7, 7, 7], rot: 0, kind: "dome" });
      for (let i = 0; i < d.towers; i++) out.push({ pos: [i ? 7 : -7, H / 2, -4], size: [1.6, H, 1.6], rot: 0, kind: "cyl" });
      break;
    case "tower":
      out.push({ pos: [0, H / 2, -2], size: [5, H, 5], rot: Math.PI / 4, kind: "box" });
      out.push({ pos: [0, H + 1.5, -2], size: [3.2, 3, 3.2], rot: 0, kind: "cyl" });
      out.push({ pos: [0, 2.5, 3], size: [12, 5, 6], rot: 0, kind: "box" });
      break;
    case "bank":
      // AI Central Bank: a vault podium, the floor shaft (floors drawn by BankFloors) and a crown
      out.push({ pos: [2, 2, 0], size: [12, 4, 14], rot: 0, kind: "box" });
      out.push({ pos: [2, H / 2, 0], size: [8, H, 8], rot: 0, kind: "box" });
      out.push({ pos: [2, H + 2.5, 0], size: [5, 5, 5], rot: Math.PI / 4, kind: "cone" });
      break;
    case "factory":
      // a long sawtooth-roofed shed with smokestacks
      out.push({ pos: [0, 3, -3], size: [18, 6, 9], rot: 0, kind: "box" });
      for (let i = 0; i < 4; i++) out.push({ pos: [-6.75 + i * 4.5, 7, -3], size: [4.5, 2, 9], rot: 0, kind: "cone" });
      for (let i = 0; i < d.towers; i++) out.push({ pos: [-6 + i * 6, H / 2 + 3, -6.5], size: [1.6, H, 1.6], rot: 0, kind: "cyl" });
      break;
    case "vault":
      out.push({ pos: [0, 3, -3], size: [16, 6, 8], rot: 0, kind: "box" });
      for (let i = 0; i < d.towers; i++) out.push({ pos: [(i - 1) * 5.5, 6 + H / 4, -3], size: [3, H / 2, 3], rot: Math.PI / 4, kind: "box" });
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

function Workstation({ id, pos, color, active }: { id: string; label: string; pos: [number, number, number]; color: string; active: string | undefined }) {
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
      <mesh position={[0, 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]} userData={{ workstation: id }}>
        <ringGeometry args={[1.6, 1.75, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.4} toneMapped={false} />
      </mesh>
    </group>
  );
}

const FLOOR_H = 4.6;

/**
 * The bank's floors, stacked in the shaft. A floor lights up while its desk is working (from real tool events), a
 * beam joins the desk to its floor, and "Go inside" turns the shaft see-through and labels every floor with who is there.
 */
function BankFloors({ d, color, interior }: { d: D; color: string; interior: boolean }) {
  const active = useStore((s) => s.world.activeWorkstations);
  const agents = useStore((s) => s.world.agents);
  const reduced = useStore((s) => s.settings.reducedMotion);
  const bands = useRef<(THREE.MeshBasicMaterial | null)[]>([]);
  const floors = d.workstations.filter((w) => w.floor !== undefined).sort((a, b) => (a.floor ?? 0) - (b.floor ?? 0));
  useFrame(({ clock }) => {
    floors.forEach((w, i) => {
      const m = bands.current[i];
      if (!m) return;
      const on = Boolean(active[w.id]);
      m.opacity = on ? (reduced ? 0.95 : 0.65 + Math.sin(clock.elapsedTime * 5 + i) * 0.3) : interior ? 0.35 : 0.18;
    });
  });
  return (
    <group>
      {floors.map((w, i) => {
        const y = (w.floor ?? 0) * FLOOR_H + 2.2;
        const on = Boolean(active[w.id]);
        const here = Object.values(agents).filter((a) => a.district === d.id && a.waypoint === w.id);
        return (
          <group key={w.id}>
            <mesh position={[2, y, 0]}>
              <boxGeometry args={[8.6, 0.35, 8.6]} />
              <meshBasicMaterial ref={(m) => { bands.current[i] = m; }} color={on ? color : "#7a6a3a"} transparent opacity={0.2} toneMapped={false} />
            </mesh>
            {on ? (
              <Line points={[[w.offset[0], 1.1, w.offset[2]], [-2.3, y, Math.max(-4, Math.min(4, w.offset[2]))]]} color={color} lineWidth={1.5}
                transparent opacity={0.8} toneMapped={false} />
            ) : null}
            {interior || on ? (
              <Html position={[7, y, 0]} center zIndexRange={[8, 0]}>
                <div className="world-label whitespace-nowrap rounded px-1.5 py-0.5 text-[10px]"
                  style={{ transform: "none", background: "rgb(7 11 24 / .85)", color: on ? color : "#d9c48a", border: `1px solid ${color}44` }}>
                  {w.floor === 0 ? "Vault" : `Floor ${w.floor}`} · {w.label}{here.length ? ` · ${here.map((a) => a.name).join(", ")}` : ""}
                </div>
              </Html>
            ) : null}
          </group>
        );
      })}
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
        {d.architecture === "bank" ? <BankFloors d={d} color={d.color} interior={interior} /> : null}
        {labels ? <NeonSign d={d} onClick={() => focus(d.id)} /> : null}
        {d.architecture === "factory" ? <FactoryBoard d={d} /> : null}
        <ActivityBubble d={d} />
      </group>
    </group>
  );
}

const SIGN_ICON: Record<string, string> = {
  "nexus-spire": "◉", "code-forge": "</>", "sentinel-citadel": "⛉", "vision-quarter": "✎", "data-observatory": "◍",
  "memory-vault": "≣", "owners-tower": "♛", "central-bank": "$", "claude-code-factory": "›_", "github-factory": "⑂",
};

const GM_MODEL = (() => {
  const gm = SEED.agents.find((a) => a.key === "general_manager") as { model?: { model?: string } } | undefined;
  const m = gm?.model?.model ?? "";
  const hit = /claude-([a-z]+)-(\d+)-(\d+)/.exec(m);
  return hit ? `${hit[1].toUpperCase()} ${hit[2]}.${hit[3]}` : "";
})();

/** The district's neon sign, as in the reference art: icon, name, and for the Nexus Spire the manager's model. */
function NeonSign({ d, onClick }: { d: D; onClick: () => void }) {
  const y = d.architecture === "bank" ? 14 : d.architecture === "tower" ? 18 : Math.min(d.height * 0.6 + 4, 14);
  return (
    <Html position={[0, y, -1]} center zIndexRange={[6, 0]}>
      <button type="button" onClick={onClick} className="neon-sign pointer-events-auto" style={{ "--c": d.color } as React.CSSProperties}>
        <span className="neon-icon" aria-hidden>{SIGN_ICON[d.id] ?? "◆"}</span>
        <span>
          <span className="block">{d.name}</span>
          {d.id === "nexus-spire" && GM_MODEL ? <span className="neon-sub">AI Manager ({GM_MODEL})</span> : null}
        </span>
      </button>
    </Html>
  );
}

const TOOL_TALK: Record<string, string> = {
  run_tests: "Running tests", run_build: "Building", read_file: "Reading code", search_code: "Searching the code", list_files: "Looking around the repo",
  edit_file: "Editing code", inspect_diff: "Reviewing the change", inspect_repository: "Inspecting the repository", create_worktree: "Setting up a workspace",
  query_market_source: "Scanning market charts", create_artifact: "Writing it up", prepare_pull_request: "Preparing a pull request",
  scaffold_prototype: "Building a prototype", build_release_bundle: "Packaging the release", research_cost_alternatives: "Researching cheaper options",
  investigate_alternatives: "Researching free alternatives", score_alternatives: "Scoring alternatives", sandbox_evaluate_candidate: "Testing in a sandbox",
  review_sandbox_evidence: "Reviewing test evidence", classify_cost: "Analyzing a cost", read_ledger_summary: "Reading the ledger",
  research_design_insights: "Researching app designs", scan_repository: "Reading your repository", propose_improvements: "Drafting improvements",
  publish_lab_change: "Publishing to GitHub", sync_claude_code: "Checking Claude Code's finished tasks", read_claude_code_memory: "Reading Claude Code's memory",
  sync_github_activity: "Checking pull requests and Actions runs",
};

/** A speech bubble over the district with what is really happening there: a tool in use, or what an agent just said. */
function ActivityBubble({ d }: { d: D }) {
  const active = useStore((s) => s.world.activeWorkstations);
  const agents = useStore((s) => s.world.agents);
  const clock = useStore((s) => s.clock);
  const [, tick] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    const t = window.setInterval(tick, 2000);
    return () => clearInterval(t);
  }, []);
  const tool = d.workstations.map((w) => active[w.id]).find(Boolean);
  let text: string | null = tool ? `${TOOL_TALK[tool] ?? tool.replaceAll("_", " ")}…` : null;
  if (!text) {
    const said = Object.values(agents)
      .filter((a) => a.district === d.id && a.indicator?.kind === "message" && clock() - a.indicator.at < 8000)
      .sort((a, b) => (b.indicator!.at ?? 0) - (a.indicator!.at ?? 0))[0];
    if (said) text = said.indicator!.text;
  }
  if (!text) return null;
  return (
    <Html position={[3, Math.min(d.height * 0.45 + 3, 11), 6]} center zIndexRange={[7, 0]}>
      <div className="speech relative" data-testid={`bubble-${d.id}`}>
        {text.length > 70 ? `${text.slice(0, 68)}…` : text}
        <span className="absolute -bottom-[7px] left-4 size-0 border-x-[6px] border-t-[7px] border-x-transparent border-t-[#0b1226]" />
      </div>
    </Html>
  );
}

/**
 * The factory's wall board: what Claude Code finished recently, or what is moving on GitHub. Owners and admins only
 * (the API refuses everyone else, and then nothing is drawn).
 */
function FactoryBoard({ d }: { d: D }) {
  const q = useQuery({ queryKey: ["factories"], queryFn: factories.get, refetchInterval: 10_000, retry: 0 });
  const data = q.data;
  if (!data) return null;
  let lines: string[] = [];
  let title = "";
  if (d.id === "claude-code-factory") {
    const cc = data.claude_code;
    if (!cc?.linked) return null;
    title = cc.data ? `${cc.data.active ? `${cc.data.active} active · ` : ""}finished recently` : "waiting for first check-in";
    lines = (cc.data?.sessions ?? []).flatMap((s: Json) => (s.completed_tasks as string[]).slice(-2).map((t) => `✓ ${t}`)).slice(0, 4);
    if (!lines.length && cc.data) lines = (cc.data.sessions ?? []).slice(0, 3).map((s: Json) => `• ${s.title}`);
  } else {
    const gh = data.github;
    if (!gh?.linked) return null;
    title = gh.data ? "latest on GitHub" : "waiting for first check-in";
    for (const r of gh.data?.repos ?? []) {
      lines.push(...(r.pulls ?? []).slice(0, 2).map((p: Json) => `${p.state === "merged" ? "⇣ merged" : p.draft ? "◌ draft" : "◉ open"} #${p.number} ${p.title}`));
      lines.push(...(r.runs ?? []).slice(0, 1).map((x: Json) => `${x.conclusion === "success" ? "✓" : x.conclusion ? "✗" : "…"} ${x.name}`));
    }
    lines = lines.slice(0, 4);
  }
  return (
    <Html position={[d.position[0] < 0 ? 7 : -7, 21, -3]} center zIndexRange={[5, 0]}>
      <div className="factory-board" style={{ "--c": d.color } as React.CSSProperties} data-testid={`board-${d.id}`}>
        <p className="factory-board-title">{title}</p>
        {lines.length ? lines.map((l, i) => <p key={i} className="truncate">{l}</p>) : <p className="opacity-60">nothing yet</p>}
      </div>
    </Html>
  );
}
