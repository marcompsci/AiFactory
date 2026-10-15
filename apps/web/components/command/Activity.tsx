"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { decideDemoApproval } from "@/hooks/useRealtime";
import { api, type Json } from "@/lib/api";
import { describe } from "@/lib/format";
import { useStore } from "@/lib/store";
import { Button, Empty, ErrorNote } from "./ui";

const NOISY = new Set(["agent.status_changed", "agent.arrived", "task.progress"]);

export function LiveActivityFeed() {
  const feed = useStore((s) => s.feed);
  const agents = useStore((s) => s.world.agents);
  const select = useStore((s) => s.selectAgent);
  const [all, setAll] = useState(false);
  const rows = all ? feed : feed.filter((e) => !NOISY.has(e.event_type));
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-ink-3">Newest first. Every line is a stored backend event.</p>
        <label className="flex items-center gap-1.5 text-xs text-ink-2">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />
          Show state changes
        </label>
      </div>
      {rows.length === 0 ? <Empty>Quiet for now. Activity appears the moment an agent does something.</Empty> : null}
      <ol className="space-y-1" aria-live="polite" aria-relevant="additions">
        {rows.slice(0, 200).map((e) => {
          const d = describe(e, agents);
          const color = e.agent_id ? agents[e.agent_id]?.color : "#8FA8FF";
          return (
            <li key={e.event_id} className="flex gap-2 text-sm">
              <span className="w-10 shrink-0 pt-0.5 text-right font-mono text-[10px] text-ink-3">#{e.sequence}</span>
              <span className="min-w-0">
                {e.agent_id ? (
                  <button type="button" className="mr-1 font-medium" style={{ color }} onClick={() => select(e.agent_id)}>
                    {d.who}
                  </button>
                ) : (
                  <span className="mr-1 font-medium text-ink-3">{d.who}</span>
                )}
                <span style={{ color: d.tone === "#EAF2FF" ? undefined : d.tone }} className="text-ink-2">
                  {d.text}
                </span>
                {e.execution_mode === "simulation" ? <span className="ml-1 text-[10px] text-warn">sim</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function ApprovalQueue() {
  const status = useStore((s) => s.status);
  const demo = useStore((s) => s.demoApproval);
  const snap = useQuery({ queryKey: ["snapshot"], queryFn: api.snapshot, enabled: status !== "demo" });
  const approvals: Json[] = snap.data?.approvals ?? [];
  if (status === "demo") {
    return demo ? <ApprovalCard summary={demo.summary} onDecide={(g) => decideDemoApproval(g ? "granted" : "rejected")} demo /> : <Empty>Nothing waiting on you.</Empty>;
  }
  if (!approvals.length) return <Empty>Nothing waiting on you. Agents ask here before publishing anything.</Empty>;
  return (
    <div className="space-y-3">
      {approvals.map((a) => (
        <ServerApproval key={a.id} a={a} />
      ))}
    </div>
  );
}

function ServerApproval({ a }: { a: Json }) {
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: (grant: boolean) => (grant ? api.grant(a.id) : api.reject(a.id)),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["snapshot"] });
      qc.invalidateQueries({ queryKey: ["mission", a.mission_id] });
    },
  });
  return (
    <>
      <ApprovalCard summary={a.summary} action={a.action} onDecide={(g) => m.mutate(g)} busy={m.isPending} />
      <ErrorNote error={m.error} />
    </>
  );
}

export function ApprovalCard({ summary, action, onDecide, busy, demo }: { summary: string; action?: string; onDecide: (grant: boolean) => void; busy?: boolean; demo?: boolean }) {
  return (
    <div className="approval-pulse rounded-xl border border-warn/50 bg-warn/10 p-3">
      <p className="text-sm font-semibold text-warn">Vega needs your approval{demo ? " (demo)" : ""}</p>
      <p className="mt-1 text-sm text-ink">{summary}</p>
      {action ? <p className="mt-1 font-mono text-[11px] text-ink-3">{action}</p> : null}
      <div className="mt-3 flex gap-2">
        <Button variant="approve" disabled={busy} onClick={() => onDecide(true)}>
          Approve and publish
        </Button>
        <Button variant="danger" disabled={busy} onClick={() => onDecide(false)}>
          Don&apos;t publish
        </Button>
      </div>
    </div>
  );
}

/** Floats over the city whenever something is waiting, so approvals are never buried in a tab. */
export function ApprovalCall() {
  const pending = useStore((s) => s.world.pendingApprovals.length);
  const releases = useStore((s) => s.world.ownerQueue.length);
  const demo = useStore((s) => s.demoApproval);
  const tab = useStore((s) => s.tab);
  const sheet = useStore((s) => s.sheet);
  const setTab = useStore((s) => s.setTab);
  const count = demo ? 1 : pending + releases;
  if (!count || (tab === "approvals" && sheet !== "peek")) return null;
  return (
    <button
      type="button"
      onClick={() => setTab("approvals")}
      className="approval-pulse fixed left-1/2 top-[calc(max(12px,env(safe-area-inset-top))+108px)] z-30 -translate-x-1/2 whitespace-nowrap rounded-full lg:left-[calc(200px+(100vw-640px)/2)] lg:top-[calc(max(8px,env(safe-area-inset-top))+72px)] border border-warn/60 bg-ground/85 px-4 py-2 text-sm text-warn backdrop-blur"
    >
      {releases && !pending ? (releases === 1 ? "A decision is waiting at your tower" : `${releases} decisions are waiting at your tower`)
        : count === 1 ? "1 action needs your approval" : `${count} actions need your approval`}
    </button>
  );
}
