"use client";

import { useEffect, useState } from "react";
import { api, type Json } from "@/lib/api";
import { ago } from "@/lib/format";

const CAT_COLOR: Record<string, string> = {
  specification: "#FFBD69",
  misalignment: "#B38CFF",
  verification: "#FF6178",
  resources: "#F4D58D",
  infrastructure: "#32D8FF",
  unclassified: "#8A93A6",
};

/** Why agents failed (MAST categories, sorted by rules) and what they learned from it. */
export default function Clinic() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Json | null>(null);
  const [lessons, setLessons] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [brief, setBrief] = useState<Json | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    api.failures(days).then((d) => live && setData(d)).catch((e) => live && setError(String(e.message ?? e)));
    api.lessons().then((d) => live && setLessons(d)).catch(() => undefined);
    api.brief().then((d) => live && setBrief(d)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [days]);

  const total = data?.total ?? 0;
  return (
    <main className="h-full overflow-auto bg-ground p-4 text-ink" style={{ overflow: "auto" }}>
      <div className="mx-auto max-w-3xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <a href="/" className="text-xs text-cyan">← City</a>
            <h1 className="font-pixel text-2xl">Failure clinic</h1>
            <p className="text-sm text-ink-2">Why agents failed, sorted into the categories from {data?.reference ?? "the MAST study"}. Sorted by rules, not by a model.</p>
          </div>
          <div className="flex gap-1">
            {[7, 30, 90].map((d) => (
              <button key={d} type="button" onClick={() => setDays(d)}
                className={`px-btn rounded px-3 py-1 text-sm ${d === days ? "bg-cyan text-ground" : "bg-surface"}`}>
                {d} days
              </button>
            ))}
          </div>
        </header>

        {brief ? (
          <section className="px-panel rounded p-4">
            <h2 className="font-pixel text-sm uppercase text-cyan">Daily brief · Atlas</h2>
            <p className="mt-1 font-semibold">{brief.headline}</p>
            {brief.failed.length ? <p className="text-sm text-bad">Failed: {brief.failed.slice(0, 3).map((f: Json) => f.title).join("; ")}</p> : null}
            <p className="text-sm text-ink-2">
              {brief.waiting.approvals} approvals · {brief.waiting.recovery_plans.length} recovery plans · about ${brief.spend.today_usd.toFixed(2)} spent today (estimated)
            </p>
            {brief.lessons[0] ? <p className="text-xs text-ink-3">{brief.lessons[0].agent} learned: {brief.lessons[0].lesson}</p> : null}
          </section>
        ) : null}
        {error ? <p className="text-bad">Couldn&apos;t load the clinic: {error}</p> : null}
        {!data && !error ? <p className="text-ink-3">Loading…</p> : null}

        {data ? (
          <>
            <section className="px-panel rounded p-4">
              {total === 0 ? (
                <p className="text-ok">No failures in this period.</p>
              ) : (
                <>
                  <p className="font-display text-xl">{data.incidents} problem{data.incidents === 1 ? "" : "s"}</p>
                  <p className="text-xs text-ink-3">Counting every failed attempt: {total}</p>
                  <p className="mt-2 text-sm">{data.advice}</p>
                </>
              )}
            </section>

            {data.by_category.length ? (
              <section className="space-y-3">
                <h2 className="font-pixel text-sm uppercase text-cyan">By kind</h2>
                {data.by_category.map((c: Json) => (
                  <div key={c.category}>
                    <div className="flex justify-between text-sm"><span className="font-semibold">{c.name}</span><span className="font-mono">{c.count}</span></div>
                    <div className="mt-1 h-1.5 rounded-full bg-surface">
                      <div className="h-1.5 rounded-full" style={{ width: `${Math.max(4, (100 * c.count) / Math.max(1, total))}%`, background: CAT_COLOR[c.category] }} />
                    </div>
                    <p className="mt-1 text-xs text-ink-3">{c.fix}</p>
                  </div>
                ))}
              </section>
            ) : null}

            {data.by_agent.length ? (
              <section>
                <h2 className="mb-2 font-pixel text-sm uppercase text-cyan">By agent</h2>
                <ul className="divide-y divide-line text-sm">
                  {data.by_agent.map((a: Json) => (
                    <li key={a.agent_id} className="flex justify-between py-1.5"><span>{a.agent}</span><span className="font-mono">{a.count}</span></li>
                  ))}
                </ul>
              </section>
            ) : null}

            {data.labels.length ? (
              <section>
                <h2 className="mb-2 font-pixel text-sm uppercase text-cyan">Recent</h2>
                <ul className="space-y-3">
                  {data.labels.slice(0, 60).map((l: Json, i: number) => (
                    <li key={`${l.source}-${i}`} className="text-sm">
                      <div className="flex items-center gap-2">
                        <span className="rounded-full px-2 py-0.5 font-mono text-[10px]" style={{ background: `${CAT_COLOR[l.category]}33`, color: CAT_COLOR[l.category] }}>{l.mode}</span>
                        <span className="font-semibold">{l.name}</span>
                        <span className="text-xs text-ink-3">{l.at ? ago(l.at) : ""}</span>
                      </div>
                      <p className="text-xs text-ink-2">
                        {[l.agent, l.task, l.mission].filter(Boolean).join(" · ")}
                        {l.mission_id ? <> · <a className="text-cyan" href={`/trace?m=${l.mission_id}`}>trace</a></> : null}
                      </p>
                      {l.evidence ? <p className="font-mono text-[11px] text-ink-3">{l.evidence}</p> : null}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        ) : null}

        <section>
          <h2 className="mb-2 font-pixel text-sm uppercase text-cyan">What agents have learned</h2>
          {!lessons?.agents?.length ? <p className="text-sm text-ink-3">No lessons yet. An agent writes one when a task struggles.</p> : null}
          <ul className="space-y-3">
            {(lessons?.agents ?? []).map((a: Json) => (
              <li key={a.agent_id}>
                <p className="font-semibold">{a.agent} <span className="text-xs font-normal text-ink-3">{a.role}</span></p>
                <ul className="ml-4 list-disc text-sm text-ink-2">
                  {a.lessons.map((l: Json) => <li key={l.id}>{l.lesson} <span className="font-mono text-[10px] text-ink-3">[{l.source}]</span></li>)}
                </ul>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-3">Written by rules from real task runs, each citing its run. Agents get them as hints, not facts.</p>
        </section>
      </div>
    </main>
  );
}
