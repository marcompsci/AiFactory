"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { myTasks, type Json } from "@/lib/api";
import { useStore } from "@/lib/store";
import { Button, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

const STAGE: Record<string, { text: string; color: string }> = {
  open: { text: "To do", color: "#8FA8FF" },
  working: { text: "Working", color: "#32D8FF" },
  needs_you: { text: "Needs you", color: "#FFBD69" },
  review: { text: "Ready to review", color: "#5BF2A5" },
  problem: { text: "Run stopped", color: "#FF6178" },
  done: { text: "Done", color: "#8a93b8" },
  dropped: { text: "Dropped", color: "#8a93b8" },
};
const KIND_COLOR: Record<string, string> = { code: "#FF9A3D", research: "#5B8CFF", write: "#FF4FB0", personal: "#A66BFF" };

/** "today 5:00 PM", "tomorrow 9:00 AM", "Fri 5:00 PM", "Nov 14", in this browser's time zone. */
export function dueLabel(iso: string, now = new Date()): string {
  const d = new Date(iso);
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(d) - day(now)) / 86_400_000);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (days === 0) return `today ${time}`;
  if (days === 1) return `tomorrow ${time}`;
  if (days === -1) return `yesterday ${time}`;
  if (days > 1 && days < 7) return `${d.toLocaleDateString([], { weekday: "short" })} ${time}`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

/** Your task list (V6.52): type it the way you'd say it, hand it to the agents, review what comes back. */
export function MyTasksPanel() {
  const status = useStore((s) => s.status);
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Json | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);
  const list = useQuery({ queryKey: ["my-tasks"], queryFn: myTasks.list, enabled: status === "live", refetchInterval: 5_000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["my-tasks"] });
  const add = useMutation({ mutationFn: () => myTasks.add(text), onSuccess: () => { setText(""); setPreview(null); refresh(); } });
  const act = useMutation({ mutationFn: (f: () => Promise<Json>) => f(), onSuccess: refresh });

  useEffect(() => {
    const t = text.trim();
    if (t.length < 2 || status !== "live") { setPreview(null); return; }
    const timer = window.setTimeout(() => { myTasks.preview(t).then(setPreview).catch(() => setPreview(null)); }, 300);
    return () => clearTimeout(timer);
  }, [text, status]);

  if (status !== "live") {
    return <Empty>Your task list lives on your server. Connect to it to add tasks and hand them to the agents.</Empty>;
  }
  const tasks: Json[] = list.data?.tasks ?? [];
  const live = tasks.filter((t) => t.stage !== "done" && t.stage !== "dropped");
  const pending = live.filter((t) => t.stage === "open" || t.stage === "working");
  const endOfDay = new Date(); endOfDay.setHours(23, 59, 59, 999);
  const groups: [string, Json[]][] = [
    ["Needs you", live.filter((t) => t.stage === "needs_you")],
    ["Ready to review", live.filter((t) => t.stage === "review" || t.stage === "problem")],
    ["Overdue", pending.filter((t) => t.overdue)],
    ["Today", pending.filter((t) => !t.overdue && t.due_at && new Date(t.due_at) <= endOfDay)],
    ["Coming up", pending.filter((t) => t.due_at && new Date(t.due_at) > endOfDay)],
    ["Anytime", pending.filter((t) => !t.due_at)],
  ];
  const done = tasks.filter((t) => t.stage === "done");

  return (
    <Section title="My tasks" aside={live.length ? `${live.length} open` : undefined}>
      <form className="space-y-1.5" onSubmit={(e) => { e.preventDefault(); if (text.trim().length >= 2) add.mutate(); }}>
        <div className="flex gap-2">
          <input
            aria-label="Add a task"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Add a task: draft the Echo blurb by Friday $1"
            className="min-w-0 flex-1 rounded-lg border border-line bg-ground/60 px-3 py-2 text-sm text-ink placeholder:text-ink-3"
          />
          <Button variant="primary" disabled={add.isPending || text.trim().length < 2}>{add.isPending ? "Adding" : "Add"}</Button>
        </div>
        {preview && text ? (
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-2" aria-live="polite">
            <span className="font-semibold text-ink">{preview.title}</span>
            {preview.due_label ? <Pill color="#32D8FF">{preview.due_label}</Pill> : null}
            <Pill color={KIND_COLOR[preview.kind] ?? "#A66BFF"}>{preview.kind}</Pill>
            {preview.priority !== "normal" ? <Pill color={preview.priority === "urgent" ? "#FF6178" : "#8a93b8"}>{preview.priority}</Pill> : null}
            {preview.budget_usd ? <Pill color="#5BF2A5">${Number(preview.budget_usd).toFixed(2)}</Pill> : null}
            {preview.repeat !== "none" ? <Pill color="#A66BFF">{preview.repeat}</Pill> : null}
          </p>
        ) : null}
        <ErrorNote error={add.error ?? act.error} />
      </form>
      {list.isLoading ? <Skeleton /> : null}
      {!list.isLoading && live.length === 0 ? <Empty>Nothing on your list. Add something above, or tell any agent in the town "add a task: …".</Empty> : null}
      {groups.filter(([, g]) => g.length).map(([name, g]) => (
        <div key={name} className="space-y-1">
          <h4 className="pixel-title text-[11px] text-ink-2">{name}</h4>
          <ul className="space-y-1">{g.map((t) => <TaskRow key={t.id} t={t} open={open === t.id} onOpen={() => setOpen(open === t.id ? null : t.id)} act={act.mutate} busy={act.isPending} />)}</ul>
        </div>
      ))}
      {done.length ? (
        <div>
          <button type="button" className="text-xs text-ink-3" onClick={() => setShowDone(!showDone)} aria-expanded={showDone}>
            Done ({done.length}) {showDone ? "▾" : "▸"}
          </button>
          {showDone ? <ul className="mt-1 space-y-1">{done.slice(0, 20).map((t) => <TaskRow key={t.id} t={t} open={open === t.id} onOpen={() => setOpen(open === t.id ? null : t.id)} act={act.mutate} busy={act.isPending} />)}</ul> : null}
        </div>
      ) : null}
    </Section>
  );
}

function TaskRow({ t, open, onOpen, act, busy }: { t: Json; open: boolean; onOpen: () => void; act: (f: () => Promise<Json>) => void; busy: boolean }) {
  const st = STAGE[t.stage] ?? STAGE.open;
  const sim = t.mission?.execution_mode === "simulation";
  return (
    <li className="rounded-lg px-2 py-1.5 hover:bg-white/5">
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          aria-label={t.stage === "done" ? "Done" : `Mark ${t.title} done`}
          checked={t.stage === "done"}
          disabled={t.stage === "done" || busy}
          onChange={() => act(() => myTasks.done(t.id))}
          className="mt-1 size-4 accent-[#5BF2A5]"
        />
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left" aria-expanded={open}>
          <span className={`block truncate text-sm ${t.stage === "done" ? "text-ink-3 line-through" : ""}`}>{t.title}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
            <Pill color={st.color}>{t.stage === "review" && sim ? "Template ready" : st.text}</Pill>
            {t.due_at ? <span className={t.overdue ? "text-bad" : ""}>{dueLabel(t.due_at)}</span> : null}
            {t.repeat !== "none" ? <span>↻ {t.repeat}</span> : null}
            {t.priority === "urgent" ? <span className="text-bad">urgent</span> : null}
          </span>
        </button>
        {t.status === "OPEN" && (t.stage === "open" || t.stage === "problem") ? (
          <Button disabled={busy} onClick={() => act(() => myTasks.doIt(t.id))} title="Hand it to the agents; the result comes back for your review">
            {t.stage === "problem" ? "Try again" : "Do it"}
          </Button>
        ) : null}
      </div>
      {open ? <TaskDetail id={t.id} act={act} busy={busy} /> : null}
    </li>
  );
}

function TaskDetail({ id, act, busy }: { id: string; act: (f: () => Promise<Json>) => void; busy: boolean }) {
  const q = useQuery({ queryKey: ["my-task", id], queryFn: () => myTasks.get(id), refetchInterval: 4_000 });
  const [note, setNote] = useState("");
  const t = q.data;
  if (!t) return <div className="mt-2"><Skeleton lines={2} /></div>;
  const sim = t.mission?.execution_mode === "simulation";
  return (
    <div className="mt-2 space-y-2 border-l border-line pl-3 text-sm">
      {t.notes ? <p className="text-xs text-ink-2">Notes: {t.notes}</p> : null}
      {t.mission ? (
        <p className="text-xs text-ink-3">
          Latest run: {String(t.mission.status).toLowerCase().replaceAll("_", " ")} · est. ${Number(t.mission.spent_usd_estimated ?? 0).toFixed(2)} of $
          {Number(t.mission.budget_usd ?? 0).toFixed(2)} · {t.runs} run{t.runs === 1 ? "" : "s"}
        </p>
      ) : null}
      {t.result ? (
        <div>
          <p className="text-xs font-semibold text-ink-2">Result</p>
          <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-ground/60 p-2 font-sans text-xs text-ink">{t.result.content}</pre>
          <p className="mt-1 text-[11px] text-ink-3">
            {sim ? "Simulation: no AI model is connected, so this is a template, not finished work." : "Written by the agents. Check facts before you use it; nothing has been sent or published."}
          </p>
        </div>
      ) : null}
      {t.plan ? (
        <details>
          <summary className="cursor-pointer text-xs text-ink-2">Plan</summary>
          <pre className="mt-1 whitespace-pre-wrap font-sans text-xs text-ink-2">{t.plan.content}</pre>
        </details>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {t.stage === "review" ? (
          <>
            <Button variant="primary" disabled={busy} onClick={() => act(() => myTasks.done(id))}>Accept and mark done</Button>
            <input aria-label="What should change?" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What should change?"
              className="min-w-0 flex-1 rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink" />
            <Button disabled={busy || !note.trim()} onClick={() => { act(() => myTasks.redo(id, note)); setNote(""); }}>Redo with note</Button>
          </>
        ) : null}
        {t.status === "OPEN" ? <Button disabled={busy} onClick={() => act(() => myTasks.drop(id))}>Drop</Button> : <Button disabled={busy} onClick={() => act(() => myTasks.reopen(id))}>Reopen</Button>}
        <Button disabled={busy} onClick={() => { if (window.confirm("Delete this task from your list?")) act(() => myTasks.remove(id)); }}>Delete</Button>
      </div>
      <ErrorNote error={q.error} />
    </div>
  );
}
