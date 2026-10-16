"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Json } from "@/lib/api";
import { ago, human, STATUS_COLOR, usd } from "@/lib/format";
import { useStore } from "@/lib/store";
import { ArtifactViewer } from "./Artifacts";
import { Button, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

const EXAMPLE = "Inspect the sample project, find a failing test, implement a fix, rerun the tests, and prepare a reviewable code change.";

export function MissionConsole() {
  const status = useStore((s) => s.status);
  const selected = useStore((s) => s.selectedMissionId);
  const select = useStore((s) => s.selectMission);
  const qc = useQueryClient();
  const [prompt, setPrompt] = useState(EXAMPLE);
  const [budget, setBudget] = useState("1.00");
  const snap = useQuery({ queryKey: ["snapshot"], queryFn: api.snapshot, enabled: status !== "demo" });
  const create = useMutation({
    mutationFn: () => api.createMission(prompt, Number(budget) || undefined),
    onSuccess: (m) => {
      select(m.id);
      qc.invalidateQueries({ queryKey: ["snapshot"] });
    },
  });

  if (selected) return <MissionDetail id={selected} onBack={() => select(null)} />;
  if (status === "demo") return <DemoMissions />;

  const missions: Json[] = snap.data?.missions ?? [];
  return (
    <div className="space-y-5">
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <label htmlFor="mission-prompt" className="text-sm font-semibold">
          New mission
        </label>
        <textarea
          id="mission-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          className="w-full resize-none rounded-lg border border-line bg-ground/60 p-3 text-sm text-ink placeholder:text-ink-3"
          placeholder="Tell the city what to do"
        />
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-ink-2">
            Budget $
            <input
              aria-label="Mission budget in US dollars"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              inputMode="decimal"
              className="w-16 rounded-md border border-line bg-ground/60 px-2 py-1 text-sm text-ink"
            />
          </label>
          <Button variant="primary" className="ml-auto" disabled={create.isPending || prompt.trim().length < 8} onClick={() => create.mutate()}>
            {create.isPending ? "Sending" : "Send to the city"}
          </Button>
        </div>
        <p className="text-xs text-ink-3">
          {snap.data?.execution_mode === "simulation"
            ? "No model key on the server: tools and tests run for real, but the fix comes from a labeled fixture."
            : "Agents will run real tools in a sandbox. Publishing always waits for your approval."}
        </p>
        <ErrorNote error={create.error} />
      </form>

      <Section title="Missions" aside={missions.length ? `${missions.length} recent` : undefined}>
        {snap.isLoading ? <Skeleton /> : null}
        <ErrorNote error={snap.error} />
        {!snap.isLoading && missions.length === 0 ? <Empty>No missions yet. Send one above and watch the agents walk to work.</Empty> : null}
        <ul className="space-y-1.5">
          {missions.map((m) => (
            <li key={m.id}>
              <button type="button" onClick={() => select(m.id)} className="w-full rounded-lg px-3 py-2 text-left hover:bg-white/5">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm">{m.title}</span>
                  <Pill color={STATUS_COLOR[m.status] ?? "#8FA8FF"}>{m.paused ? "Paused" : human(m.status)}</Pill>
                </div>
                <div className="mt-0.5 text-xs text-ink-3">
                  {ago(m.created_at)} · {m.execution_mode === "simulation" ? "simulation" : "live"} · est. {usd(m.spent_usd_estimated)} of {usd(m.budget_usd)}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

function DemoMissions() {
  const feed = useStore((s) => s.feed);
  const created = feed.find((e) => e.event_type === "mission.created");
  const done = feed.find((e) => e.event_type === "mission.completed");
  return (
    <div className="space-y-3">
      <Empty>
        This is a demo with no backend: the city is replaying a scripted mission so you can see how it looks. Connect a server in System to send real missions.
      </Empty>
      {created ? (
        <div className="rounded-lg bg-white/5 px-3 py-2">
          <div className="flex items-center justify-between">
            <span className="text-sm">Fix the failing test (demo)</span>
            <Pill color={done ? "#5BF2A5" : "#FFBD69"}>{done ? "Completed" : "Running"}</Pill>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* --------------------------------------------------------------------------- detail */

function MissionDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const q = useQuery({ queryKey: ["mission", id], queryFn: () => api.mission(id), refetchInterval: 15000 });
  const qc = useQueryClient();
  const [artifact, setArtifact] = useState<string | null>(null);
  const act = useMutation({
    mutationFn: (kind: "cancel" | "pause" | "resume") => api[kind](id),
    onSettled: () => qc.invalidateQueries({ queryKey: ["mission", id] }),
  });
  const agents = useStore((s) => s.world.agents);
  const recover = useMutation({
    mutationFn: ({ plan, approve }: { plan: string; approve: boolean }) => api.recoveryDecide(plan, approve),
    onSettled: () => qc.invalidateQueries({ queryKey: ["mission", id] }),
  });

  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error) return <ErrorNote error={q.error} />;
  const d = q.data!;
  const m = d.mission;
  const terminal = ["COMPLETED", "FAILED", "CANCELLED"].includes(m.status);

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <button type="button" onClick={onBack} className="text-xs text-cyan">
          ← All missions
        </button>
        <h2 className="font-display text-base leading-snug">{m.title}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Pill color={STATUS_COLOR[m.status] ?? "#8FA8FF"}>{human(m.status)}</Pill>
          {m.paused ? <Pill color="#FFBD69">Paused{m.pause_reason ? `: ${m.pause_reason}` : ""}</Pill> : null}
          <span className="text-xs text-ink-3">
            {m.execution_mode === "simulation" ? "Simulation (fixture patch)" : "Live"} · est. {usd(m.spent_usd_estimated)} of {usd(m.budget_usd)}
          </span>
        </div>
        {m.failure_reason ? <p className="text-sm text-bad">{m.failure_reason}</p> : null}
        {m.outcome ? <p className="text-sm text-ink-2">Outcome: {human(m.outcome)}</p> : null}
        {d.objective ? (
          <p className={`text-sm ${d.objective.met ? "text-ok" : "text-warn"}`}>
            {d.objective.met ? "Objective met" : d.objective.status === "objective_partly_met" ? "Objective partly met" : "Objective not met"}
            {!d.objective.met ? `: ${(d.objective.findings as string[]).join("; ")}` : ""}
          </p>
        ) : null}
        {(d.recovery ?? []).map((r: Json) => (
          <div key={r.id} className="space-y-1 rounded border border-line p-2 text-sm">
            <p className="text-xs text-ink-3">Recovery plan · {r.failure_mode} · {String(r.status).toLowerCase()}</p>
            <p className="font-semibold">{r.summary}</p>
            <p className="text-xs text-ink-2">{r.rationale}</p>
            {r.status === "PENDING" && r.actionable ? (
              <div className="flex gap-2">
                <Button disabled={recover.isPending} onClick={() => recover.mutate({ plan: r.id, approve: true })}>Approve</Button>
                <Button disabled={recover.isPending} onClick={() => recover.mutate({ plan: r.id, approve: false })}>Decline</Button>
              </div>
            ) : null}
            {recover.error ? <p className="text-xs text-bad">{(recover.error as Error).message}</p> : null}
          </div>
        ))}
        <a href={`/trace?m=${m.id}`} className="text-xs text-cyan">
          Full trace: every step, tool and AI call →
        </a>
        {!terminal ? (
          <div className="flex gap-2">
            {m.paused ? (
              <Button onClick={() => act.mutate("resume")}>Resume</Button>
            ) : (
              <Button onClick={() => act.mutate("pause")}>Pause</Button>
            )}
            <Button variant="danger" onClick={() => confirm("Cancel this mission? Running tools stop at their next step.") && act.mutate("cancel")}>
              Cancel mission
            </Button>
          </div>
        ) : null}
        <ErrorNote error={act.error} />
      </div>

      <Section title="Task graph" aside="arrows show hand-offs">
        <DependencyGraph tasks={d.tasks} deps={d.dependencies} agents={agents} />
      </Section>

      <Section title="Tool calls" aside={`${d.tool_executions.length}`}>
        <ToolCalls rows={d.tool_executions} agents={agents} />
      </Section>

      <Section title="Conversation">
        {d.messages.length === 0 ? <Empty>No messages yet.</Empty> : null}
        <ol className="space-y-2">
          {d.messages.map((msg: Json) => (
            <li key={msg.id} className="text-sm">
              <span style={{ color: agents[msg.from_agent_id]?.color ?? "#8FA8FF" }}>{agents[msg.from_agent_id]?.name ?? "System"}</span>
              {msg.to_agent_id ? <span className="text-ink-3"> to {agents[msg.to_agent_id]?.name}</span> : null}
              <p className="text-ink-2">{msg.body}</p>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Artifacts">
        {d.artifacts.length === 0 ? <Empty>Diffs, test reports and patches appear here as agents produce them.</Empty> : null}
        <ul className="space-y-1">
          {d.artifacts.map((a: Json) => (
            <li key={a.id}>
              <button type="button" className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-white/5" onClick={() => setArtifact(a.id)}>
                <span className="text-violet">{human(a.kind)}</span> <span className="text-ink">{a.title}</span>
              </button>
            </li>
          ))}
        </ul>
      </Section>
      {artifact ? <ArtifactViewer id={artifact} onClose={() => setArtifact(null)} /> : null}
    </div>
  );
}

function DependencyGraph({ tasks, deps, agents }: { tasks: Json[]; deps: Json[]; agents: Record<string, { name: string; color: string }> }) {
  if (!tasks.length) return <Empty>The Commander is planning.</Empty>;
  const depth: Record<string, number> = {};
  const parents = (id: string) => deps.filter((x) => x.task_id === id).map((x) => x.depends_on_task_id as string);
  const level = (id: string): number => (depth[id] ??= Math.max(-1, ...parents(id).map(level)) + 1);
  tasks.forEach((t) => level(t.id));
  // Laid out top-to-bottom: one row per dependency depth, so it fits a phone-width panel.
  const rowsN = Math.max(...Object.values(depth)) + 1;
  const byRow: Json[][] = Array.from({ length: rowsN }, () => []);
  tasks.forEach((t) => byRow[depth[t.id]].push(t));
  const W = 150;
  const H = 40;
  const gapX = 12;
  const gapY = 22;
  const perRow = Math.max(...byRow.map((r) => r.length));
  const width = perRow * (W + gapX) - gapX;
  const height = rowsN * (H + gapY) - gapY;
  const pos: Record<string, { x: number; y: number }> = {};
  byRow.forEach((r, ri) => r.forEach((t, ci) => (pos[t.id] = { x: ci * (W + gapX) + (width - (r.length * (W + gapX) - gapX)) / 2, y: ri * (H + gapY) })));
  return (
    <div className="scroll-thin overflow-x-auto pb-1">
      <svg width={width} height={height} role="img" aria-label="Mission task dependency graph" className="block">
        {deps.map((dp) => {
          const a = pos[dp.depends_on_task_id];
          const b = pos[dp.task_id];
          if (!a || !b) return null;
          return (
            <path key={dp.task_id + dp.depends_on_task_id} d={`M${a.x + W / 2},${a.y + H} C${a.x + W / 2},${a.y + H + gapY / 2} ${b.x + W / 2},${b.y - gapY / 2} ${b.x + W / 2},${b.y}`}
              fill="none" stroke="rgb(50 216 255 / .35)" strokeWidth={1.5} />
          );
        })}
        {tasks.map((t) => {
          const p = pos[t.id];
          const c = STATUS_COLOR[t.status] ?? "#8FA8FF";
          return (
            <g key={t.id} transform={`translate(${p.x},${p.y})`}>
              <title>{`${t.title} — ${human(t.status)}`}</title>
              <rect width={W} height={H} rx={8} fill="rgb(7 11 24 / .7)" stroke={c} strokeOpacity={0.7} />
              <text x={10} y={16} fill="#EAF2FF" fontSize={11} fontWeight={600}>{human(t.key)}</text>
              <text x={10} y={31} fill={agents[t.agent_id]?.color ?? "#8FA8FF"} fontSize={10}>
                {agents[t.agent_id]?.name ?? ""} · {human(t.status)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function ToolCalls({ rows, agents }: { rows: Json[]; agents: Record<string, { name: string; color: string }> }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!rows.length) return <Empty>No tool calls yet.</Empty>;
  return (
    <ul className="space-y-1">
      {rows.map((t) => (
        <li key={t.id} className="rounded-lg bg-white/[.03]">
          <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm" onClick={() => setOpen(open === t.id ? null : t.id)} aria-expanded={open === t.id}>
            <span className="size-2 shrink-0 rounded-full" style={{ background: STATUS_COLOR[t.status] ?? "#8FA8FF" }} />
            <span className="font-mono text-[13px]">{t.tool_name}</span>
            <span className="text-xs text-ink-3">{agents[t.agent_id]?.name}</span>
            <span className="ml-auto text-xs text-ink-3">{t.duration_ms != null ? `${t.duration_ms} ms` : human(t.status)}</span>
          </button>
          {open === t.id ? (
            <div className="space-y-2 px-3 pb-3">
              <pre className="scroll-thin max-h-28 overflow-auto rounded-md bg-ground/70 p-2 font-mono text-[11px] text-ink-2">{JSON.stringify(t.arguments, null, 2)}</pre>
              <pre className="scroll-thin max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-ground/70 p-2 font-mono text-[11px] text-ink-2">{pretty(t.output_excerpt)}</pre>
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function pretty(s: string | null): string {
  if (!s) return "(no output)";
  try {
    const o = JSON.parse(s);
    if (typeof o.output === "string") return o.output;
    if (typeof o.diff === "string" && o.diff) return o.diff;
    return JSON.stringify(o, null, 2);
  } catch {
    return s;
  }
}
