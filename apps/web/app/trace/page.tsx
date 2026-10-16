"use client";

import { useEffect, useState } from "react";
import { api, type Json } from "@/lib/api";
import { usd } from "@/lib/format";

const KIND: Record<string, { label: string; color: string }> = {
  mission: { label: "Mission", color: "#EAF2FF" },
  step: { label: "Step", color: "#32D8FF" },
  tool: { label: "Tool", color: "#8FA8FF" },
  model: { label: "AI call", color: "#A66BFF" },
  message: { label: "Message", color: "#9CC8FF" },
  approval: { label: "Approval", color: "#F4D58D" },
  decision: { label: "Manager", color: "#FFBD69" },
  check: { label: "Check", color: "#5BF2A5" },
  lesson: { label: "Lesson", color: "#9CC8FF" },
};

function dur(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

/** Everything that happened in one mission, in order: steps, tool calls, AI calls, messages, approvals and checks. */
export default function Trace() {
  const [data, setData] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [only, setOnly] = useState<string | null>(null);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("m");
    if (!id) {
      setError("No mission given.");
      return;
    }
    api.trace(id).then(setData).catch((e) => setError(String(e.message ?? e)));
  }, []);

  const items: Json[] = (data?.items ?? []).filter((i: Json) => !only || i.kind === only);
  const t = data?.totals;
  return (
    <main className="h-full overflow-auto bg-ground p-4 text-ink" style={{ overflow: "auto" }}>
      <div className="mx-auto max-w-3xl space-y-5">
        <header>
          <a href="/" className="text-xs text-cyan">← City</a>
          <h1 className="font-pixel text-2xl">Mission trace</h1>
          {data ? <p className="text-sm text-ink-2">{data.mission.title} · {data.mission.status.toLowerCase().replace(/_/g, " ")}{data.mission.execution_mode === "simulation" ? " · simulation" : ""}</p> : null}
        </header>
        {error ? <p className="text-bad">{error}</p> : null}
        {!data && !error ? <p className="text-ink-3">Loading…</p> : null}
        {t ? (
          <section className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            {[["Time", dur(t.wall_ms)], ["AI cost (est.)", usd(t.cost_usd)], ["Tool calls", t.tool_calls], ["Failed steps", t.failed_steps]].map(([k, v]) => (
              <div key={String(k)} className="px-panel rounded p-2"><p className="text-xs text-ink-3">{k}</p><p className="font-mono">{v}</p></div>
            ))}
          </section>
        ) : null}
        {data?.by_agent?.length ? (
          <section>
            <h2 className="mb-2 font-pixel text-sm uppercase text-cyan">By agent</h2>
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-ink-3"><tr><th>Agent</th><th>Steps</th><th>Tools</th><th>AI calls</th><th>Busy</th><th>Cost</th></tr></thead>
              <tbody>
                {data.by_agent.map((a: Json) => (
                  <tr key={a.agent_id} className="border-t border-line">
                    <td className="py-1">{a.agent}</td><td>{a.steps}{a.failed_steps ? <span className="text-bad"> ({a.failed_steps} failed)</span> : null}</td>
                    <td>{a.tool_calls}</td><td>{a.model_calls}</td><td>{dur(a.busy_ms)}</td><td>{usd(a.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : null}
        {data ? (
          <section>
            <div className="mb-2 flex flex-wrap gap-1">
              <button type="button" onClick={() => setOnly(null)} className={`rounded px-2 py-0.5 text-xs ${!only ? "bg-cyan text-ground" : "bg-surface"}`}>All</button>
              {Object.entries(KIND).map(([k, v]) => (
                <button key={k} type="button" onClick={() => setOnly(k)} className={`rounded px-2 py-0.5 text-xs ${only === k ? "bg-cyan text-ground" : "bg-surface"}`}>{v.label}</button>
              ))}
            </div>
            <ol className="relative space-y-2 border-l border-line pl-4">
              {items.map((i: Json, n: number) => (
                <li key={`${i.ref}-${n}`} className="text-sm">
                  <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full" style={{ background: KIND[i.kind]?.color }} />
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-mono text-[10px] text-ink-3">{new Date(i.at).toLocaleTimeString()}</span>
                    <span style={{ color: KIND[i.kind]?.color }} className="text-xs">{KIND[i.kind]?.label}</span>
                    <span className="font-semibold">{i.title}</span>
                    {i.status ? <span className={`text-xs ${i.status === "FAILED" ? "text-bad" : "text-ink-3"}`}>{String(i.status).toLowerCase()}</span> : null}
                    {i.duration_ms != null ? <span className="text-xs text-ink-3">{dur(i.duration_ms)}</span> : null}
                    {i.cost_usd != null ? <span className="text-xs text-ink-3">{usd(i.cost_usd)} · {i.tokens} tokens</span> : null}
                  </div>
                  {i.agent ? <p className="text-xs text-ink-2">{i.agent}{i.task && i.kind !== "step" ? ` · ${i.task}` : ""}</p> : null}
                  {i.detail ? <p className="whitespace-pre-wrap font-mono text-[11px] text-ink-3">{i.detail}</p> : null}
                </li>
              ))}
            </ol>
            {data.truncated ? <p className="mt-2 text-xs text-ink-3">Showing the first {data.items.length} entries.</p> : null}
            <p className="mt-3 text-xs text-ink-3">AI costs are the gateway&apos;s estimates.</p>
          </section>
        ) : null}
      </div>
    </main>
  );
}
