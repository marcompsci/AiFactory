"use client";

import { DISTRICT_BY_ID } from "@aiciv/world-engine";
import { useStore, type CameraMode, type Tab } from "@/lib/store";
import { human, STATUS_COLOR } from "@/lib/format";
import { LiveActivityFeed } from "./Activity";
import { CompanyPanel } from "./Company";
import { BankPanel } from "./Bank";
import { OwnerDesk } from "./OwnerTower";
import { AgentRoster } from "./Agents";
import { MissionConsole } from "./Missions";
import { SystemPanel } from "./System";
import { Button, Dot } from "./ui";
import { AppLabPanel } from "./AppLab";
import { GamePanel } from "./Game";
import { OverviewTab } from "./Frame";

const STATUS_TEXT = {
  connecting: { text: "Connecting", color: "#8FA8FF" },
  live: { text: "Live", color: "#5BF2A5" },
  reconnecting: { text: "Reconnecting", color: "#FFBD69" },
  demo: { text: "Demo, no server", color: "#FFBD69" },
} as const;

export function TopBar() {
  const status = useStore((s) => s.status);
  const mode = useStore((s) => s.world.mode);
  const camera = useStore((s) => s.camera);
  const setCamera = useStore((s) => s.setCamera);
  const selected = useStore((s) => s.selectedAgentId);
  const st = STATUS_TEXT[status];
  const cams: { id: CameraMode; label: string; title: string }[] = [
    { id: "overview", label: "City", title: "Overview of the whole city" },
    { id: "orbit", label: "Orbit", title: "Drag to orbit, pinch or scroll to zoom" },
    { id: "follow", label: "Follow", title: "Follow the selected agent" },
    { id: "fly", label: "Fly", title: "Fly with W A S D, Q and E" },
  ];
  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-30 flex items-start justify-between gap-2 p-3 pt-[max(12px,env(safe-area-inset-top))]">
      <div className="glass pointer-events-auto flex items-center gap-3 rounded-2xl px-3 py-2">
        <h1 className="font-display text-[13px] font-bold tracking-tight">AI Civilization</h1>
        <span className="flex items-center gap-1.5 text-xs text-ink-2" role="status">
          <Dot color={st.color} pulse={status === "live"} />
          {st.text}
        </span>
        {status !== "demo" && mode === "simulation" ? (
          <span className="rounded-full bg-warn/15 px-2 py-0.5 text-[11px] text-warn" title="No model key on the server. Tools run for real; text and patches come from labeled fixtures.">
            Simulation
          </span>
        ) : null}
      </div>
      <nav aria-label="Camera" className="glass pointer-events-auto fixed right-3 top-[calc(max(12px,env(safe-area-inset-top))+52px)] flex gap-1 rounded-2xl p-1 lg:bottom-4 lg:left-3 lg:right-auto lg:top-auto">
        {cams.map((c) => (
          <button
            key={c.id}
            type="button"
            title={c.title}
            disabled={c.id === "follow" && !selected}
            onClick={() => setCamera(c.id)}
            aria-pressed={camera === c.id}
            className={`rounded-xl px-3 py-1.5 text-xs disabled:opacity-30 ${camera === c.id ? "bg-cyan text-ground" : "text-ink-2 hover:bg-white/5"}`}
          >
            {c.label}
          </button>
        ))}
      </nav>
    </header>
  );
}

export function DistrictCard() {
  const id = useStore((s) => s.focusedDistrict);
  const interior = useStore((s) => s.interior);
  const focus = useStore((s) => s.focusDistrict);
  const agents = useStore((s) => s.world.agents);
  const active = useStore((s) => s.world.activeWorkstations);
  const select = useStore((s) => s.selectAgent);
  if (!id) return null;
  const d = DISTRICT_BY_ID[id];
  const here = Object.values(agents).filter((a) => a.district === id);
  return (
    <div className="pixel-panel fixed left-3 top-[calc(max(12px,env(safe-area-inset-top))+104px)] z-20 w-[min(320px,calc(100vw-24px))] p-3 lg:left-[200px] lg:top-[84px]">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-sm" style={{ color: d.color }}>
            {d.name}
          </h2>
          <p className="text-xs text-ink-2">{d.purpose}</p>
        </div>
        <button type="button" onClick={() => focus(null)} className="text-xs text-ink-3" aria-label="Close district">
          Close
        </button>
      </div>
      <ul className="mt-2 space-y-1 text-sm">
        {d.workstations.map((w) => (
          <li key={w.id} className="flex items-center gap-2">
            <Dot color={active[w.id] ? d.color : "#2a3a5e"} pulse={!!active[w.id]} />
            <span>{w.label}</span>
            <span className="ml-auto truncate text-xs text-ink-3">{active[w.id] ? active[w.id].replaceAll("_", " ") : "idle"}</span>
          </li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {here.length === 0 ? <span className="text-xs text-ink-3">No agents here right now.</span> : null}
        {here.map((a) => (
          <button key={a.id} type="button" onClick={() => select(a.id)} className="rounded-full px-2 py-0.5 text-xs" style={{ color: a.color, background: `${a.color}1f` }}>
            {a.name}, {human(a.execState).toLowerCase()}
          </button>
        ))}
      </div>
      <Button className="mt-3 w-full" onClick={() => focus(id, !interior)}>
        {interior ? "Step back outside" : "Go inside"}
      </Button>
    </div>
  );
}

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "missions", label: "Tasks" },
  { id: "game", label: "Arena" },
  { id: "lab", label: "App Lab" },
  { id: "company", label: "Company" },
  { id: "bank", label: "Bank" },
  { id: "agents", label: "Agents" },
  { id: "activity", label: "Activity" },
  { id: "approvals", label: "Owner" },
  { id: "system", label: "System" },
];

export function Dock({ onReconnect }: { onReconnect: () => void }) {
  const tab = useStore((s) => s.tab);
  const setTab = useStore((s) => s.setTab);
  const sheet = useStore((s) => s.sheet);
  const setSheet = useStore((s) => s.setSheet);
  const approvals = useStore((s) => s.world.pendingApprovals.length + s.world.ownerQueue.length + (s.demoApproval ? 1 : 0));
  const running = useStore((s) => Object.values(s.world.agents).filter((a) => a.execState === "EXECUTING").length);
  const height = { peek: "var(--sheet-peek)", half: "52dvh", full: "calc(100dvh - 72px)" }[sheet];
  const cycle = () => setSheet(sheet === "peek" ? "half" : sheet === "half" ? "full" : "peek");

  return (
    <aside
      aria-label="Command center"
      className="glass pixel-panel fixed inset-x-0 bottom-0 z-40 flex flex-col rounded-t-2xl pb-[env(safe-area-inset-bottom)] transition-[height] duration-300 lg:inset-y-2 lg:left-auto lg:right-2 lg:!h-auto lg:w-[424px] lg:rounded"
      style={{ height }}
    >
      <button type="button" onClick={cycle} className="mx-auto mt-2 h-1.5 w-12 shrink-0 rounded-full bg-white/20 lg:hidden" aria-label={`Resize panel (now ${sheet})`} />
      <div className="flex items-center gap-1 overflow-x-auto px-3 pt-2" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`relative shrink-0 rounded-xl px-2.5 py-2 text-[13px] ${tab === t.id ? "bg-white/10 text-ink" : "text-ink-2 hover:text-ink"}`}
          >
            {t.label}
            {t.id === "approvals" && approvals ? (
              <span className="ml-1.5 rounded-full bg-warn px-1.5 text-[11px] font-semibold text-ground">{approvals}</span>
            ) : null}
            {t.id === "agents" && running ? <span className="ml-1.5 text-[11px]" style={{ color: STATUS_COLOR.RUNNING }}>{running} working</span> : null}
          </button>
        ))}
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-3" role="tabpanel">
        {tab === "overview" ? <OverviewTab /> : null}
        {tab === "game" ? <GamePanel /> : null}
        {tab === "lab" ? <AppLabPanel /> : null}
        {tab === "missions" ? <MissionConsole /> : null}
        {tab === "agents" ? <AgentRoster /> : null}
        {tab === "activity" ? <LiveActivityFeed /> : null}
        {tab === "company" ? <CompanyPanel /> : null}
        {tab === "bank" ? <BankPanel /> : null}
        {tab === "approvals" ? <OwnerDesk /> : null}
        {tab === "system" ? <SystemPanel onReconnect={onReconnect} /> : null}
      </div>
    </aside>
  );
}
