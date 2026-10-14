"use client";

import { DISTRICT_BY_ID } from "@aiciv/world-engine";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Json } from "@/lib/api";
import { ago, human, PACKAGE_COLORS, STATUS_COLOR } from "@/lib/format";
import { useStore } from "@/lib/store";
import { Button, Dot, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

/** The opportunity workflow, in order, so a packet's progress reads left to right. */
export const STAGES = ["RESEARCHED", "MANAGER_REVIEW", "ROUTED", "DEPARTMENT_ACCEPTED", "IN_PRODUCTION", "QUALITY_REVIEW",
  "MANAGER_APPROVAL", "OWNER_APPROVAL", "RELEASE_AUTHORIZED"];

const OPP_COLOR: Record<string, string> = { ...STATUS_COLOR, REVISION_REQUESTED: "#FFBD69", REJECTED: "#FF6178", DEFERRED: "#8FA8FF",
  RELEASE_AUTHORIZED: "#F4D58D", OWNER_APPROVAL: "#F4D58D" };

export function CompanyPanel() {
  const status = useStore((s) => s.status);
  if (status === "demo") return <Empty>Research, the org chart and the conveyor network need a server. Connect one in System.</Empty>;
  return (
    <div className="space-y-6">
      <ResearchForm />
      <Opportunities />
      <OrgChart />
      <Decisions />
      <Belts />
    </div>
  );
}

function ResearchForm() {
  const qc = useQueryClient();
  const [source, setSource] = useState("apple_charts");
  const [query, setQuery] = useState("productivity");
  const m = useMutation({ mutationFn: () => api.research(source, query), onSuccess: () => qc.invalidateQueries({ queryKey: ["snapshot"] }) });
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
      <h3 className="text-sm font-semibold">Send a researcher out</h3>
      <div className="flex gap-2">
        <select aria-label="Market source" value={source} onChange={(e) => setSource(e.target.value)} className="rounded-lg border border-line bg-ground px-2 py-2 text-sm">
          <option value="apple_charts">App Store charts</option>
          <option value="etsy">Etsy</option>
          <option value="depop">Depop</option>
          <option value="app_store_connect">Your App Store Connect</option>
        </select>
        <input aria-label="What to research" value={query} onChange={(e) => setQuery(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-line bg-ground/60 px-3 py-2 text-sm" />
      </div>
      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" disabled={m.isPending || query.trim().length < 2}>{m.isPending ? "Sending" : "Start research"}</Button>
        <span className="text-xs text-ink-3">Only permitted sources. Without credentials, labeled fixture data is used and marked everywhere.</span>
      </div>
      <ErrorNote error={m.error} />
    </form>
  );
}

function StageBar({ status }: { status: string }) {
  const i = STAGES.indexOf(status);
  return (
    <div className="flex gap-0.5" aria-label={`Stage ${human(status)}`}>
      {STAGES.map((s, k) => (
        <span key={s} title={human(s)} className="h-1 flex-1 rounded-full" style={{ background: k <= i ? OPP_COLOR[status] ?? "#32D8FF" : "rgb(234 242 255 / .1)" }} />
      ))}
    </div>
  );
}

function Opportunities() {
  const q = useQuery({ queryKey: ["opportunities"], queryFn: api.opportunities, refetchInterval: 10000 });
  const setTab = useStore((s) => s.setTab);
  const rows = q.data?.opportunities ?? [];
  return (
    <Section title="Opportunities" aside={rows.length ? `${rows.length}` : undefined}>
      {q.isLoading ? <Skeleton lines={2} /> : null}
      <ErrorNote error={q.error} />
      {!q.isLoading && !rows.length ? <Empty>No packets yet. When research finds something worth building, it rides the conveyor to Atlas.</Empty> : null}
      <ul className="space-y-2">
        {rows.map((o: Json) => (
          <li key={o.id} className="space-y-1.5 rounded-lg bg-white/[.03] px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm">{o.title}</span>
              <Pill color={OPP_COLOR[o.status] ?? "#8FA8FF"}>{human(o.status)}</Pill>
            </div>
            <StageBar status={o.status} />
            <div className="flex items-center justify-between text-xs text-ink-3">
              <span>
                score {Number(o.opportunity_score).toFixed(2)}, {o.confidence} confidence
                {o.data_mode === "fixture" ? <span className="ml-1 text-warn">fixture data</span> : null}
              </span>
              {o.status === "OWNER_APPROVAL" ? (
                <button type="button" className="text-warn" onClick={() => setTab("approvals")}>Review in Owner&apos;s Tower</button>
              ) : <span>{ago(o.updated_at)}</span>}
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function OrgChart() {
  const agents = useStore((s) => s.world.agents);
  const snap = useQuery({ queryKey: ["snapshot"], queryFn: api.snapshot });
  const select = useStore((s) => s.selectAgent);
  const rows: Json[] = snap.data?.agents ?? [];
  const byId = Object.fromEntries(rows.map((a) => [a.id, a]));
  const gm = rows.find((a) => a.tier === "general_manager");
  const children = (id: string) => rows.filter((a) => a.supervisor_agent_id === id);
  const Node = ({ a, depth }: { a: Json; depth: number }) => {
    const live = agents[a.id];
    return (
      <li>
        <button type="button" onClick={() => select(a.id)} className="flex w-full items-center gap-2 rounded-md py-1 text-left text-sm hover:bg-white/5" style={{ paddingLeft: depth * 16 }}>
          <Dot color={STATUS_COLOR[live?.execState === "EXECUTING" ? "RUNNING" : live?.execState ?? "IDLE"] ?? "#8FA8FF"} />
          <span style={{ color: a.avatar?.color }}>{a.name}</span>
          <span className="truncate text-ink-3">{a.role}</span>
          <span className="ml-auto shrink-0 font-mono text-[10px] text-ink-3">{String(a.model_name).replace("claude-", "")}</span>
        </button>
        {children(a.id).length ? <ul>{children(a.id).map((c) => <Node key={c.id} a={c} depth={depth + 1} />)}</ul> : null}
      </li>
    );
  };
  void byId;
  return (
    <Section title="Chain of command" aside="every agent reports to one supervisor">
      <p className="text-sm text-ink-2">You, the owner</p>
      {gm ? <ul><Node a={gm} depth={1} /></ul> : <Skeleton lines={3} />}
    </Section>
  );
}

function Decisions() {
  const q = useQuery({ queryKey: ["hierarchy"], queryFn: api.hierarchy, refetchInterval: 15000 });
  const agents = useStore((s) => s.world.agents);
  const decisions: Json[] = q.data?.decisions ?? [];
  const reports: Json[] = q.data?.reports ?? [];
  return (
    <>
      <Section title="Manager decisions" aside="rules, or Opus when judgment is needed">
        {!decisions.length ? <Empty>No decisions yet.</Empty> : null}
        <ol className="space-y-2">
          {decisions.slice(0, 12).map((d) => (
            <li key={d.id} className="text-sm">
              <span className="text-ink">{human(d.decision_type)}</span>{" "}
              <span className="text-violet">{d.outcome.replaceAll("_", " ").toLowerCase()}</span>
              <span className="ml-1 text-xs text-ink-3">{d.method === "model" ? `by ${d.model}` : "by rule"}, {agents[d.manager_agent_id]?.name ?? ""}</span>
              <p className="text-xs text-ink-2">{d.rationale}</p>
            </li>
          ))}
        </ol>
      </Section>
      <Section title="Reports to supervisors" aside="reporting a problem is never penalized">
        <ol className="space-y-1">
          {reports.slice(0, 10).map((r) => (
            <li key={r.id} className="text-xs">
              <span style={{ color: agents[r.agent_id]?.color }}>{agents[r.agent_id]?.name}</span>
              <span className="text-ink-3"> → {agents[r.supervisor_agent_id]?.name ?? "owner"}: </span>
              <span className="text-ink-2">{human(r.kind)}: {r.body}</span>
            </li>
          ))}
        </ol>
      </Section>
    </>
  );
}

function Belts() {
  const logistics = useStore((s) => s.logistics);
  const routeStatus = useStore((s) => s.world.routeStatus);
  const packages = useStore((s) => s.world.packages);
  const qc = useQueryClient();
  const toggle = useMutation({ mutationFn: ({ id, up }: { id: string; up: boolean }) => api.routeStatus(id, up ? "UP" : "DOWN"),
    onSettled: () => qc.invalidateQueries({ queryKey: ["logistics"] }) });
  const ring = (logistics?.routes ?? []).filter((r) => r.from_node.startsWith("junction:") && r.to_node.startsWith("junction:"));
  const moving = Object.values(packages).filter((p) => p.status === "IN_TRANSIT");
  const label = (id: string) => DISTRICT_BY_ID[id.replace("junction:", "")]?.name ?? id;
  return (
    <Section title="Conveyor network" aside={`${moving.length} package${moving.length === 1 ? "" : "s"} moving`}>
      <ul className="space-y-1 text-sm">
        {moving.map((p) => (
          <li key={p.id} className="flex items-center gap-2">
            <Dot color={PACKAGE_COLORS[p.type] ?? "#EAF2FF"} pulse />
            <span>{human(p.type)}</span>
            <span className="text-xs text-ink-3">{DISTRICT_BY_ID[p.origin]?.name} → {DISTRICT_BY_ID[p.destination]?.name}</span>
          </li>
        ))}
      </ul>
      <details className="text-sm">
        <summary className="cursor-pointer text-ink-2">Ring belts ({ring.filter((r) => (routeStatus[r.id] ?? r.status) === "DOWN").length} down)</summary>
        <p className="my-1 text-xs text-ink-3">Taking a belt down makes packages reroute the other way around the ring. Admins only.</p>
        <ul className="space-y-1">
          {ring.map((r) => {
            const up = (routeStatus[r.id] ?? r.status) === "UP";
            return (
              <li key={r.id} className="flex items-center gap-2 text-xs">
                <Dot color={up ? "#5BF2A5" : "#FF6178"} />
                <span className="truncate">{label(r.from_node)} → {label(r.to_node)}</span>
                <button type="button" className="ml-auto text-cyan" onClick={() => toggle.mutate({ id: r.id, up: !up })}>{up ? "Take down" : "Restore"}</button>
              </li>
            );
          })}
        </ul>
        <ErrorNote error={toggle.error} />
      </details>
    </Section>
  );
}

/** Inspection panel for a package clicked on the belt. */
export function PackageCard() {
  const id = useStore((s) => s.selectedPackageId);
  const pkg = useStore((s) => (id ? s.world.packages[id] : undefined));
  const select = useStore((s) => s.selectPackage);
  if (!pkg) return null;
  const color = PACKAGE_COLORS[pkg.type] ?? "#EAF2FF";
  return (
    <div className="glass fixed left-3 top-[calc(max(12px,env(safe-area-inset-top))+104px)] z-20 w-[min(300px,calc(100vw-24px))] rounded-2xl p-3 text-sm lg:top-auto lg:bottom-16">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-sm" style={{ color }}>{human(pkg.type)}</h2>
          <p className="text-xs text-ink-2">{DISTRICT_BY_ID[pkg.origin]?.name} → {DISTRICT_BY_ID[pkg.destination]?.name}</p>
        </div>
        <button type="button" onClick={() => select(null)} className="text-xs text-ink-3">Close</button>
      </div>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-ink-3">Status</dt><dd>{human(pkg.status)}</dd>
        <dt className="text-ink-3">Priority</dt><dd>{pkg.priority}</dd>
        <dt className="text-ink-3">Belts</dt><dd>{pkg.route.length} segments</dd>
        <dt className="text-ink-3">Dispatched</dt><dd>{pkg.routeStartedAt ? new Date(pkg.routeStartedAt).toLocaleTimeString() : "-"}</dd>
        <dt className="text-ink-3">ETA</dt><dd>{pkg.eta ? new Date(pkg.eta).toLocaleTimeString() : "-"}</dd>
        <dt className="text-ink-3">Package</dt><dd className="truncate font-mono">{pkg.id.slice(0, 8)}</dd>
      </dl>
      <p className="mt-2 text-[11px] text-ink-3">Position is drawn from the server&apos;s route and clock; only the backend marks it delivered.</p>
    </div>
  );
}
