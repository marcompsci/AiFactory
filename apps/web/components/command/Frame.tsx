"use client";

/**
 * The dashboard frame around the city: a stats bar on top, navigation on the left, and four live panels along the
 * bottom (Live Agent Activity, Conveyor Flow, Active Projects, Financial Overview). Every number comes from
 * /api/overview; money is shown to owners and admins only, and labeled simulated when it is.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Json } from "@/lib/api";
import { describe, human, money } from "@/lib/format";
import { useStore, type CameraMode, type Tab } from "@/lib/store";
import { Dot } from "./ui";

export const useOverview = () =>
  useQuery({ queryKey: ["overview"], queryFn: () => api.overview(), refetchInterval: 4000, enabled: useStore.getState().status !== "demo" });

const NAV: { id: Tab; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "◈" },
  { id: "agents", label: "Agents", icon: "☺" },
  { id: "missions", label: "Tasks", icon: "▤" },
  { id: "company", label: "Projects", icon: "◆" },
  { id: "bank", label: "Finances", icon: "$" },
  { id: "game", label: "Arena", icon: "♛" },
  { id: "lab", label: "App Lab", icon: "⚗" },
  { id: "factories", label: "Factories", icon: "▥" },
  { id: "knowledge", label: "Knowledge", icon: "✦" },
  { id: "approvals", label: "Owner", icon: "♜" },
  { id: "activity", label: "Activity", icon: "≋" },
  { id: "system", label: "Settings", icon: "⚙" },
];

const STATUS_TEXT = {
  connecting: { text: "Connecting", color: "#8FA8FF" },
  live: { text: "Live", color: "#5BF2A5" },
  reconnecting: { text: "Reconnecting", color: "#FFBD69" },
  demo: { text: "Demo, no server", color: "#FFBD69" },
  signin: { text: "Sign in to connect", color: "#FFD36B" },
} as const;

function Clock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 15000);
    return () => clearInterval(t);
  }, []);
  const weather = useQuery({ queryKey: ["weather"], queryFn: fetchWeather, refetchInterval: 30 * 60_000, staleTime: 15 * 60_000, retry: 0 });
  if (!now) return null;
  return (
    <span className="flex items-center gap-3">
      <span className="text-right leading-tight">
        <span className="block text-[10px] uppercase text-ink-3">{now.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}</span>
        <span className="block font-mono text-[13px]">{now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
      </span>
      {weather.data ? (
        <span className="text-right leading-tight" title={`Open-Meteo, ${WEATHER_PLACE.name}`}>
          <span className="block font-mono text-[13px]">{weather.data.icon} {Math.round(weather.data.tempF)}°F</span>
          <span className="block text-[10px] text-ink-3">{WEATHER_PLACE.name}</span>
        </span>
      ) : null}
    </span>
  );
}

/** Real current weather from Open-Meteo (free, no key). Shown only when it loads; nothing is made up. */
const WEATHER_PLACE = { name: "San Francisco", lat: 37.7749, lon: -122.4194 };
async function fetchWeather(): Promise<{ tempF: number; icon: string }> {
  const r = await fetch(`https://api.open-meteo.com/v1/forecast?latitude=${WEATHER_PLACE.lat}&longitude=${WEATHER_PLACE.lon}&current=temperature_2m,weather_code,is_day&temperature_unit=fahrenheit`);
  if (!r.ok) throw new Error("weather unavailable");
  const c = (await r.json()).current;
  const code: number = c.weather_code;
  const icon = code === 0 ? (c.is_day ? "☀" : "☾") : code <= 3 ? "⛅" : code <= 48 ? "🌫" : code <= 67 || (code >= 80 && code <= 82) ? "☂" : code <= 77 ? "❄" : "⛈";
  return { tempF: c.temperature_2m, icon };
}

function Stat({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="min-w-0 px-2" data-testid={`stat-${label.toLowerCase().replace(/\W+/g, "-")}`}>
      <p className="pixel-title text-[9px] text-ink-3">{label}</p>
      <p className="truncate font-mono text-sm" style={{ color }}>{value}</p>
      {sub ? <p className="text-[9px] text-ink-3">{sub}</p> : null}
    </div>
  );
}

export function StatsBar() {
  const status = useStore((s) => s.status);
  const mode = useStore((s) => s.world.mode);
  const agentCount = useStore((s) => Object.keys(s.world.agents).length);
  const ov = useOverview();
  const st = STATUS_TEXT[status];
  const o = ov.data;
  const f = o?.finance;
  const sim = f?.simulated ? "simulated" : undefined;
  return (
    <header className="pointer-events-none fixed inset-x-0 top-0 z-30 p-2 pt-[max(8px,env(safe-area-inset-top))] lg:pl-[200px] lg:pr-[440px]">
      <div className="pixel-panel pointer-events-auto flex items-center gap-1 overflow-x-auto px-2 py-1.5 scroll-thin">
        <h1 className="pixel-title mr-2 shrink-0 text-[13px] text-cyan lg:hidden">AI Civ</h1>
        <span className="mr-1 flex shrink-0 items-center gap-1.5 text-xs text-ink-2" role="status">
          <Dot color={st.color} />
          {st.text}
          {status !== "demo" && mode === "simulation" ? <span className="rounded bg-warn/15 px-1.5 text-[10px] text-warn" title="No model key on the server. Tools run for real; agent text comes from labeled templates.">Sim</span> : null}
        </span>
        <div className="grid min-w-0 flex-1 grid-cols-3 divide-x divide-white/10 sm:grid-cols-[repeat(5,minmax(84px,1fr))]">
          <Stat label="Cash" value={f ? (f.cash_minor === null ? "—" : money(f.cash_minor)) : "owner only"} sub={sim} color="#3DFFB8" />
          <Stat label="Agents" value={o ? `${o.agents.working}/${o.agents.total}` : `${agentCount}`} sub="working" />
          <Stat label="Tasks" value={o ? `${o.tasks.running}` : "—"} sub={o ? `${o.tasks.completed_today} done today` : undefined} />
          <div className="hidden sm:block"><Stat label="Projects" value={o ? `${o.projects.active}` : "—"} sub={o?.lab_waiting ? `${o.lab_waiting} need you` : "active"} /></div>
          <div className="hidden sm:block"><Stat label="30-day revenue" value={f ? (f.revenue_30d_minor == null ? "—" : money(f.revenue_30d_minor)) : "owner only"} sub={sim} color="#FFD36B" /></div>
        </div>
        <div className="hidden shrink-0 sm:block"><Clock /></div>
      </div>
    </header>
  );
}

export function SideNav() {
  const tab = useStore((s) => s.tab);
  const setTab = useStore((s) => s.setTab);
  const setSheet = useStore((s) => s.setSheet);
  const camera = useStore((s) => s.camera);
  const setCamera = useStore((s) => s.setCamera);
  const selected = useStore((s) => s.selectedAgentId);
  const owner = useStore((s) => s.world.pendingApprovals.length + s.world.ownerQueue.length);
  const cams: { id: CameraMode; label: string }[] = [
    { id: "overview", label: "City" }, { id: "orbit", label: "Orbit" }, { id: "follow", label: "Follow" }, { id: "fly", label: "Fly" },
  ];
  return (
    <nav aria-label="Sections" className="pixel-panel fixed bottom-3 left-2 top-2 z-40 hidden w-[184px] flex-col p-2 lg:flex">
      <div className="flex items-center gap-2 px-1 pb-3 pt-1">
        <span className="grid size-9 shrink-0 place-items-center rounded bg-gradient-to-br from-violet via-cyan to-[#FF4FB0] font-display text-sm font-bold text-ground" aria-hidden>▲</span>
        <span className="min-w-0">
          <span className="pixel-title block whitespace-nowrap text-[13px] leading-tight text-ink">AI Civilization</span>
          <span className="block whitespace-nowrap text-[7px] tracking-[0.08em] text-ink-3">BUILD · RESEARCH · CREATE · GROW</span>
        </span>
      </div>
      <ul className="space-y-0.5">
        {NAV.map((n) => (
          <li key={n.id}>
            <button type="button" onClick={() => { setTab(n.id); setSheet("half"); }} aria-current={tab === n.id ? "page" : undefined}
              className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[13px] ${tab === n.id ? "bg-cyan/15 text-cyan" : "text-ink-2 hover:bg-white/5"}`}>
              <span className="w-4 text-center" aria-hidden>{n.icon}</span>
              {n.label}
              {n.id === "approvals" && owner ? <span className="ml-auto rounded bg-warn px-1 text-[10px] font-semibold text-ground">{owner}</span> : null}
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-auto space-y-1">
        <p className="pixel-title px-2 text-[9px] text-ink-3">Camera</p>
        <div className="grid grid-cols-2 gap-1">
          {cams.map((c) => (
            <button key={c.id} type="button" disabled={c.id === "follow" && !selected} onClick={() => setCamera(c.id)} aria-pressed={camera === c.id}
              className={`rounded px-2 py-1 text-[11px] disabled:opacity-30 ${camera === c.id ? "bg-cyan text-ground" : "bg-white/5 text-ink-2"}`}>
              {c.label}
            </button>
          ))}
        </div>
      </div>
    </nav>
  );
}

/** Mobile: camera chips (the side nav is desktop-only). */
export function CameraChips() {
  const camera = useStore((s) => s.camera);
  const setCamera = useStore((s) => s.setCamera);
  const selected = useStore((s) => s.selectedAgentId);
  const cams: { id: CameraMode; label: string }[] = [
    { id: "overview", label: "City" }, { id: "orbit", label: "Orbit" }, { id: "follow", label: "Follow" }, { id: "fly", label: "Fly" },
  ];
  return (
    <nav aria-label="Camera" className="pixel-panel fixed right-2 top-[calc(max(8px,env(safe-area-inset-top))+64px)] z-30 flex gap-1 p-1 lg:hidden">
      {cams.map((c) => (
        <button key={c.id} type="button" disabled={c.id === "follow" && !selected} onClick={() => setCamera(c.id)} aria-pressed={camera === c.id}
          className={`rounded px-2.5 py-1 text-xs disabled:opacity-30 ${camera === c.id ? "bg-cyan text-ground" : "text-ink-2"}`}>
          {c.label}
        </button>
      ))}
    </nav>
  );
}

function Panel({ title, children, testid }: { title: string; children: React.ReactNode; testid?: string }) {
  return (
    <section className="pixel-panel flex min-h-0 min-w-0 flex-col p-2" data-testid={testid}>
      <h2 className="pixel-title pb-1 text-[11px] text-cyan">{title}</h2>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">{children}</div>
    </section>
  );
}

export function LiveActivityPanel({ limit = 6 }: { limit?: number }) {
  const feed = useStore((s) => s.feed);
  const agents = useStore((s) => s.world.agents);
  const items = feed.slice(-40).reverse().map((e) => ({ e, d: describe(e, agents) })).filter((x) => x.d.text).slice(0, limit);
  return (
    <ul className="space-y-1 text-[12px]">
      {items.length === 0 ? <li className="text-ink-3">Waiting for the agents…</li> : null}
      {items.map(({ e, d }) => (
        <li key={e.event_id} className="flex items-start gap-1.5">
          <span className="w-12 shrink-0 font-mono text-[10px] leading-5 text-ink-3">{new Date(e.occurred_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
          <span className="pixel-avatar mt-1 size-3 shrink-0 rounded-sm" style={{ background: e.agent_id ? agents[e.agent_id]?.color ?? d.tone : d.tone }} />
          <span className="min-w-0"><b className="font-medium">{d.who}</b> <span className="text-ink-2">{d.text}</span></span>
        </li>
      ))}
    </ul>
  );
}

const STAGE_COLOR: Record<string, string> = { research: "#F4D58D", manager: "#A66BFF", production: "#4C8DFF", qa: "#3FB8FF", bank: "#3DE08A", owner: "#FF9A3D" };

export function ConveyorFlowPanel({ data }: { data?: Json }) {
  const stages: Json[] = data?.conveyor ?? [];
  return (
    <div className="relative flex h-full items-center pt-1" aria-label="Conveyor flow">
      <div className="pixel-bar absolute left-[8%] right-[8%] top-[calc(50%-10px)] h-0.5 text-cyan/40" aria-hidden />
      {stages.map((s) => (
        <div key={s.id} className="relative flex min-w-0 flex-1 items-center">
          <div className="min-w-0 flex-1 text-center">
            <div className="mx-auto grid size-8 place-items-center rounded border-2 bg-ground font-mono text-sm"
              style={{ borderColor: STAGE_COLOR[s.id], color: s.in_transit ? "#fff" : STAGE_COLOR[s.id], background: s.in_transit ? STAGE_COLOR[s.id] + "55" : undefined,
                boxShadow: s.in_transit ? `0 0 10px ${STAGE_COLOR[s.id]}` : undefined }}>
              {s.in_transit}
            </div>
            <p className="mt-1 text-[9px] leading-tight text-ink-2">{s.label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ActiveProjectsPanel({ data }: { data?: Json }) {
  const items: Json[] = data?.projects?.items ?? [];
  if (!items.length) return <p className="text-[12px] text-ink-3">No active projects. Start an App Lab cycle or approve research in the Owner tab.</p>;
  return (
    <ul className="space-y-1.5 text-[12px]">
      {items.map((p) => (
        <li key={p.id}>
          <div className="flex gap-2"><span className="min-w-0 flex-1 truncate">{p.title}</span><span className="text-[10px] text-ink-3">{human(p.status)}</span></div>
          <div className="mt-0.5 h-1.5 overflow-hidden rounded-sm bg-white/10">
            <div className="pixel-bar h-full text-ok" style={{ width: `${Math.round(p.progress * 100)}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

export function FinancialOverviewPanel({ data }: { data?: Json }) {
  const f = data?.finance;
  if (!data) return null;
  if (!f) return <p className="text-[12px] text-ink-3">Financial figures are visible to the owner and admins.</p>;
  if (!f.has_data) return <p className="text-[12px] text-ink-3">No financial data yet. Connect a read-only account in Finances.</p>;
  const rows: [string, number | null, string][] = [
    ["Revenue (30 days)", f.revenue_30d_minor, "#3DFFB8"],
    ["Expenses (30 days)", f.expenses_30d_minor, "#FF6178"],
    ["Tax reserve (estimate)", f.tax_reserve_minor, "#FFD36B"],
    ["Operating surplus (estimate)", f.surplus_30d_minor, "#32D8FF"],
  ];
  return (
    <div className="text-[12px]">
      {f.simulated ? <p className="mb-1 text-[10px] text-warn">SIMULATED data</p> : null}
      <dl className="space-y-0.5">
        {rows.map(([k, v, c]) => (
          <div key={k} className="flex gap-2" title={k.includes("surplus") ? f.surplus_label : undefined}>
            <dt className="min-w-0 flex-1 truncate text-ink-2">{k}</dt>
            <dd className="font-mono" style={{ color: c }}>{v === null || v === undefined ? "—" : money(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** Desktop: four panels along the bottom of the city. */
export function BottomPanels() {
  const status = useStore((s) => s.status);
  const ov = useOverview();
  if (status === "demo") return null;
  return (
    <div className="pointer-events-none fixed bottom-3 left-[200px] right-[440px] z-20 hidden h-[188px] grid-cols-4 gap-2 lg:grid">
      <div className="pointer-events-auto contents">
        <Panel title="Live agent activity" testid="panel-activity"><LiveActivityPanel /></Panel>
        <Panel title="Conveyor flow" testid="panel-conveyor"><ConveyorFlowPanel data={ov.data} /></Panel>
        <Panel title="Active projects" testid="panel-projects"><ActiveProjectsPanel data={ov.data} /></Panel>
        <Panel title="Financial overview" testid="panel-finance"><FinancialOverviewPanel data={ov.data} /></Panel>
      </div>
    </div>
  );
}

/** Mobile: the same four panels, stacked, in the Overview tab. */
export function OverviewTab() {
  const ov = useOverview();
  return (
    <div className="space-y-3">
      <Panel title="Live agent activity"><LiveActivityPanel limit={8} /></Panel>
      <Panel title="Conveyor flow"><ConveyorFlowPanel data={ov.data} /></Panel>
      <Panel title="Active projects"><ActiveProjectsPanel data={ov.data} /></Panel>
      <Panel title="Financial overview"><FinancialOverviewPanel data={ov.data} /></Panel>
    </div>
  );
}
