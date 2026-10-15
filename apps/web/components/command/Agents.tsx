"use client";

import { DISTRICT_BY_ID } from "@aiciv/world-engine";
import { Portrait } from "./Portrait";
import { useQuery } from "@tanstack/react-query";
import { api, type Json } from "@/lib/api";
import { ago, human, STATUS_COLOR, usd } from "@/lib/format";
import { useStore } from "@/lib/store";
import { ToolCalls } from "./Missions";
import { Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

export function AgentRoster() {
  const agents = useStore((s) => s.world.agents);
  const selected = useStore((s) => s.selectedAgentId);
  const select = useStore((s) => s.selectAgent);
  if (selected && agents[selected]) return <AgentInspector id={selected} />;
  return (
    <ul className="space-y-1">
      {Object.values(agents).map((a) => (
        <li key={a.id}>
          <button type="button" onClick={() => select(a.id)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-white/5">
            <Portrait look={a.look} size={40} fallback={a.color} name={a.name} />
            <span className="min-w-0 flex-1">
              <span className="block text-sm">
                {a.name} <span className="text-ink-3">{a.role}</span>
              </span>
              <span className="block truncate text-xs text-ink-3">
                {a.movement === "MOVING" ? `Walking to ${DISTRICT_BY_ID[a.district]?.name}` : `At ${DISTRICT_BY_ID[a.district]?.name}`}
                {a.currentTask ? ` — ${a.currentTask}` : ""}
              </span>
            </span>
            <Pill color={STATUS_COLOR[a.execState] ?? "#8FA8FF"}>{human(a.execState)}</Pill>
          </button>
        </li>
      ))}
    </ul>
  );
}

function AgentInspector({ id }: { id: string }) {
  const a = useStore((s) => s.world.agents[id]);
  const agents = useStore((s) => s.world.agents);
  const select = useStore((s) => s.selectAgent);
  const status = useStore((s) => s.status);
  const q = useQuery({ queryKey: ["agent", id], queryFn: () => api.agent(id), enabled: status !== "demo" });
  const d = q.data;
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <button type="button" onClick={() => select(null)} className="text-xs text-cyan">
          ← All agents
        </button>
        <div className="flex items-center gap-3">
          <Portrait look={a.look} size={64} fallback={a.color} name={a.name} />
          <div>
            <h2 className="font-display text-base">{a.name}</h2>
            <p className="text-sm text-ink-2">
              {a.role}, home in {DISTRICT_BY_ID[a.homeDistrict]?.name}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Pill color={STATUS_COLOR[a.execState] ?? "#8FA8FF"}>Execution: {human(a.execState)}</Pill>
          <Pill color="#8FA8FF">Movement: {human(a.movement)}</Pill>
        </div>
        {a.currentTask ? <p className="text-sm text-ink-2">Working on: {a.currentTask}</p> : null}
      </div>

      {status === "demo" ? <Empty>Connect a server to see this agent&apos;s real history, tools and spend.</Empty> : null}
      {q.isLoading ? <Skeleton lines={5} /> : null}
      <ErrorNote error={q.error} />
      {d ? (
        <>
          <Section title="Permissions">
            <div className="flex flex-wrap gap-1.5">
              {d.agent.tools.map((t: string) => (
                <span key={t} className="rounded-md bg-white/5 px-2 py-0.5 font-mono text-[11px] text-ink-2">
                  {t}
                </span>
              ))}
            </div>
            <p className="text-xs text-ink-3">
              Model {d.agent.model_provider}/{d.agent.model_name}. Limit {usd(d.agent.max_usd_per_mission)} per mission, {d.agent.max_concurrent_tasks} task at a time.
            </p>
          </Section>
          <Section title="Spend" aside="estimated">
            <p className="text-sm text-ink-2">
              {usd(d.usage.estimated_cost_usd)} across {d.usage.input_tokens.toLocaleString()} input and {d.usage.output_tokens.toLocaleString()} output tokens.
            </p>
          </Section>
          <Section title="Recent tasks">
            {d.tasks.length === 0 ? <Empty>No tasks yet.</Empty> : null}
            <ul className="space-y-1">
              {d.tasks.map((t: Json) => (
                <li key={t.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate">{t.title}</span>
                  <span className="shrink-0 text-xs text-ink-3">
                    {human(t.status)}, {ago(t.updated_at)}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
          <Section title="Tool calls">
            <ToolCalls rows={d.tool_executions} agents={agents} />
          </Section>
          <Section title="Audit trail" aside={`last ${d.audit.length} events`}>
            <ol className="space-y-0.5 font-mono text-[11px] text-ink-3">
              {d.audit.map((e: Json) => (
                <li key={e.sequence}>
                  #{e.sequence} {e.event_type} {e.execution_mode === "simulation" ? "(sim)" : ""}
                </li>
              ))}
            </ol>
          </Section>
        </>
      ) : null}
    </div>
  );
}
