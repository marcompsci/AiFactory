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
  blocked: { text: "Waiting", color: "#A66BFF" },
  snoozed: { text: "Snoozed", color: "#8a93b8" },
  waiting: { text: "Waiting for someone", color: "#A66BFF" },
};
const SNOOZE: [string, string][] = [["later", "Later today"], ["tonight", "Tonight"], ["tomorrow", "Tomorrow"], ["next_week", "Next week"]];
const mins = (m: number) => (m < 60 ? `${m}m` : m % 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m / 60}h`);
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
  const [listFilter, setListFilter] = useState<string | null>(null);
  const [tool, setTool] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [undo, setUndo] = useState<{ label: string; run: () => Promise<Json> } | null>(null);
  useEffect(() => { const h = window.setTimeout(() => setQ(search.trim()), 250); return () => clearTimeout(h); }, [search]);
  useEffect(() => { if (!undo) return; const h = window.setTimeout(() => setUndo(null), 6_000); return () => clearTimeout(h); }, [undo]);
  const found = useQuery({ queryKey: ["my-tasks", "search", q], queryFn: () => myTasks.search(q), enabled: status === "live" && q.length > 0 });
  const list = useQuery({ queryKey: ["my-tasks"], queryFn: myTasks.list, enabled: status === "live", refetchInterval: 5_000 });
  useListStyles();
  const refresh = () => {
    for (const k of ["my-tasks", "my-task", "goals", "shutdown", "month", "fit"]) qc.invalidateQueries({ queryKey: [k] });
  };
  const add = useMutation({ mutationFn: () => myTasks.add(text), onSuccess: () => { setText(""); setPreview(null); refresh(); } });
  const act = useMutation({ mutationFn: (f: () => Promise<Json>) => f(), onSuccess: refresh });
  const finish = (t: Json) => {
    act.mutate(() => myTasks.done(t.id), { onSuccess: () => setUndo({ label: `Done: ${t.title}`, run: () => myTasks.undoDone(t.id) }) });
  };

  useEffect(() => {
    const t = text.trim();
    if (t.length < 2 || status !== "live") { setPreview(null); return; }
    const timer = window.setTimeout(() => { myTasks.preview(t).then(setPreview).catch(() => setPreview(null)); }, 300);
    return () => clearTimeout(timer);
  }, [text, status]);

  if (status !== "live") {
    return <Empty>Your task list lives on your server. Connect to it to add tasks and hand them to the agents.</Empty>;
  }
  const all: Json[] = list.data?.tasks ?? [];
  const lists = [...new Set(all.filter((t) => t.status === "OPEN" && t.list_name).map((t) => t.list_name as string))].sort();
  const tasks = listFilter ? all.filter((t) => t.list_name === listFilter) : all;
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
    ["Waiting on something", live.filter((t) => t.stage === "blocked")],
    ["Waiting for people", live.filter((t) => t.stage === "waiting")],
    ["Snoozed", live.filter((t) => t.stage === "snoozed")],
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
          <Button type="submit" variant="primary" disabled={add.isPending || text.trim().length < 2}>{add.isPending ? "Adding" : "Add"}</Button>
        </div>
        {preview && text ? (
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-ink-2" aria-live="polite">
            <span className="font-semibold text-ink">{preview.title}</span>
            {preview.due_label ? <Pill color="#32D8FF">{preview.due_label}</Pill> : null}
            <Pill color={KIND_COLOR[preview.kind] ?? "#A66BFF"}>{preview.kind}</Pill>
            {preview.priority !== "normal" ? <Pill color={preview.priority === "urgent" ? "#FF6178" : "#8a93b8"}>{preview.priority}</Pill> : null}
            {preview.budget_usd ? <Pill color="#5BF2A5">${Number(preview.budget_usd).toFixed(2)}</Pill> : null}
            {preview.repeat !== "none" ? <Pill color="#A66BFF">{preview.repeat_label || preview.repeat}</Pill> : null}
            {preview.links?.length ? <Pill color="#32D8FF">{preview.links.length === 1 ? "1 link" : `${preview.links.length} links`}</Pill> : null}
            {preview.bill_hint ? (
              <button type="button" className="rounded-full bg-[#5BF2A5]/20 px-2 py-0.5 text-xs text-[#5BF2A5]"
                onClick={() => act.mutate(() => myTasks.addBill({ name: preview.bill_hint.name, amount: preview.bill_hint.amount, due_day: preview.bill_hint.due_day ?? 1,
                  cadence: preview.bill_hint.cadence === "yearly" ? "yearly" : "monthly", due_month: preview.bill_hint.cadence === "yearly" ? new Date().getMonth() + 1 : null }),
                  { onSuccess: () => { setText(""); setPreview(null); qc.invalidateQueries({ queryKey: ["bills"] }); } })}>
                Add as a bill{preview.bill_hint.amount != null ? ` (${money(preview.bill_hint.amount)}` + (preview.bill_hint.due_day ? `, day ${preview.bill_hint.due_day})` : ")") : ""}
              </button>
            ) : null}
            {preview.list_name ? <Pill color="#FFBD69">#{preview.list_name}</Pill> : null}
            {preview.estimate_minutes ? <Pill color="#8a93b8">{mins(preview.estimate_minutes)}</Pill> : null}
          </p>
        ) : null}
        <ErrorNote error={add.error ?? act.error} />
      </form>
      <div className="flex flex-wrap gap-1.5" role="toolbar" aria-label="Task tools">
        {[["plan", "Plan my day"], ["money", "Money"], ["fit", "I have…"], ["eod", "End of day"], ["goals", "Goals"], ["bills", "Bills"], ["month", "Month"], ["dump", "Brain dump"], ["review", "Weekly review"], ["habits", "Habits"], ["results", "Results"], ["insights", "Insights"], ["templates", "Templates"], ["archive", "Archive & export"]].map(([k, label]) => (
          <Button key={k} aria-pressed={tool === k} variant={tool === k ? "primary" : "quiet"} onClick={() => setTool(tool === k ? null : k)}>{label}</Button>
        ))}
      </div>
      {tool ? <TaskTools tool={tool} refresh={refresh} /> : null}
      <input aria-label="Search tasks" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search titles, notes, lists, steps and links"
        className="w-full rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink" />
      {undo ? (
        <div role="status" className="flex items-center gap-2 rounded-lg bg-white/10 px-3 py-1.5 text-xs">
          <span className="min-w-0 flex-1 truncate">{undo.label}</span>
          <button type="button" className="font-semibold text-[#FFBD69]" onClick={() => { const u = undo; setUndo(null); act.mutate(u.run); }}>Undo</button>
        </div>
      ) : null}
      {q ? (
        <div className="space-y-1">
          <h4 className="pixel-title text-[11px] text-ink-2">Search ({found.data?.tasks.length ?? "…"})</h4>
          <ErrorNote error={found.error} />
          {found.data && !found.data.tasks.length ? <Empty>Nothing matches "{q}".</Empty> : null}
          <ul className="space-y-1">{(found.data?.tasks ?? []).map((t) => <TaskRow key={t.id} t={t} open={open === t.id} onOpen={() => setOpen(open === t.id ? null : t.id)} act={act.mutate} busy={act.isPending} onDone={finish} />)}</ul>
        </div>
      ) : null}
      {lists.length ? (
        <div className="flex flex-wrap gap-1.5 text-xs" aria-label="Lists">
          <button type="button" aria-pressed={!listFilter} onClick={() => setListFilter(null)} className={`rounded-full px-2 py-0.5 ${!listFilter ? "bg-white/15 text-ink" : "text-ink-3"}`}>All</button>
          {lists.map((n) => (
            <button key={n} type="button" aria-pressed={listFilter === n} onClick={() => setListFilter(listFilter === n ? null : n)}
              className={`rounded-full px-2 py-0.5 ${listFilter === n ? "bg-[#FFBD69]/25 text-ink" : "text-[#FFBD69]"}`}>#{n}</button>
          ))}
        </div>
      ) : null}
      {list.isLoading ? <Skeleton /> : null}
      {!list.isLoading && live.length === 0 ? <Empty>Nothing on your list. Add something above, or tell any agent in the town "add a task: …".</Empty> : null}
      {groups.filter(([, g]) => g.length).map(([name, g]) => (
        <div key={name} className="space-y-1">
          <h4 className="pixel-title text-[11px] text-ink-2">{name}</h4>
          <ul className="space-y-1">{g.map((t) => <TaskRow key={t.id} t={t} open={open === t.id} onOpen={() => setOpen(open === t.id ? null : t.id)} act={act.mutate} busy={act.isPending} onDone={finish} />)}</ul>
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

function TaskRow({ t, open, onOpen, act, busy, onDone }: { t: Json; open: boolean; onOpen: () => void; act: (f: () => Promise<Json>) => void; busy: boolean; onDone?: (t: Json) => void }) {
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
          onChange={() => (onDone ? onDone(t) : act(() => myTasks.done(t.id)))}
          className="mt-1 size-4 accent-[#5BF2A5]"
        />
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left" aria-expanded={open}>
          <span className={`block truncate text-sm ${t.stage === "done" ? "text-ink-3 line-through" : ""}`}>{t.title}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
            <Pill color={st.color}>{t.stage === "review" && sim ? "Template ready" : st.text}</Pill>
            {t.due_at ? <span className={t.overdue ? "text-bad" : ""}>{dueLabel(t.due_at)}</span> : null}
            {t.repeat !== "none" ? <span>↻ {t.repeat_label || t.repeat}</span> : null}
            {t.priority === "urgent" ? <span className="text-bad">urgent</span> : null}
            {t.list_name ? <span style={{ color: styleOf(t.list_name)?.color ?? "#FFBD69" }}>#{t.list_name}</span> : null}
            {t.waiting_for ? <span className={t.follow_up_due ? "text-[#FFBD69]" : "text-[#A66BFF]"}>{t.follow_up_due ? "follow up with" : "waiting for"} {t.waiting_for.person}</span> : null}
            {t.estimate_minutes ? <span>{mins(t.estimate_minutes)}</span> : null}
            {t.items_total ? <span aria-label={`${t.items_done} of ${t.items_total} steps done`}>☑ {t.items_done}/{t.items_total}</span> : null}
            {t.stage === "snoozed" && t.snoozed_until ? <span>until {dueLabel(t.snoozed_until)}</span> : null}
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
  const [step, setStep] = useState("");
  const [why, setWhy] = useState("");
  const [link, setLink] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const hist = useQuery({ queryKey: ["my-task-history", id], queryFn: () => myTasks.history(id), enabled: showHistory });
  const t = q.data;
  const runnable = t?.status === "OPEN" && (t?.stage === "open" || t?.stage === "problem");
  const est = useQuery({ queryKey: ["my-task-estimate", id], queryFn: () => myTasks.estimate(id), enabled: !!runnable });
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
      {t.items?.length || t.status === "OPEN" ? (
        <div>
          <p className="text-xs font-semibold text-ink-2">Checklist{t.items?.length ? ` ${t.items_done}/${t.items_total}` : ""}</p>
          <ul className="mt-1 space-y-0.5">
            {(t.items ?? []).map((i: Json) => (
              <li key={i.id} className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={i.done} disabled={busy} aria-label={i.done ? `Untick ${i.text}` : `Tick ${i.text}`}
                  onChange={() => act(() => myTasks.setItem(id, i.id, { done: !i.done }))} className="size-3.5 accent-[#5BF2A5]" />
                <span className={i.done ? "text-ink-3 line-through" : ""}>{i.text}</span>
                {i.from_agents ? <span className="text-ink-3" title="From the agents' plan">✦</span> : null}
                {t.status === "OPEN" ? <button type="button" className="text-ink-3 hover:text-ink" title="Make this step its own task" aria-label={`Make "${i.text}" its own task`} onClick={() => act(() => myTasks.promote(id, i.id))}>↗</button> : null}
                <button type="button" className="ml-auto text-ink-3 hover:text-bad" aria-label={`Remove ${i.text}`} onClick={() => act(() => myTasks.removeItem(id, i.id))}>×</button>
              </li>
            ))}
          </ul>
          {t.status === "OPEN" ? (
            <form className="mt-1 flex gap-1.5" onSubmit={(e) => { e.preventDefault(); if (step.trim()) { act(() => myTasks.addItems(id, [step.trim()])); setStep(""); } }}>
              <input aria-label="Add a step" value={step} onChange={(e) => setStep(e.target.value)} placeholder="Add a step"
                className="min-w-0 flex-1 rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink" />
              <Button type="submit" disabled={!step.trim() || busy}>Add</Button>
            </form>
          ) : null}
        </div>
      ) : null}
      {t.status === "OPEN" ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">
          <label className="flex items-center gap-1">List
            <input defaultValue={t.list_name ? `#${t.list_name}` : ""} placeholder="#home" aria-label="List"
              onBlur={(e) => { const v = e.target.value.trim(); if (v.replace(/^#/, "") !== (t.list_name ?? "")) act(() => myTasks.edit(id, { list_name: v || null })); }}
              className="w-24 rounded-md border border-line bg-ground/60 px-1.5 py-0.5 text-ink" />
          </label>
          <label className="flex items-center gap-1">Time
            <select value={t.estimate_minutes ?? ""} aria-label="Time it takes" onChange={(e) => act(() => myTasks.edit(id, { estimate_minutes: e.target.value ? Number(e.target.value) : null }))}
              className="rounded-md border border-line bg-ground/60 px-1 py-0.5 text-ink">
              <option value="">not set</option>
              {[...new Set([15, 30, 45, 60, 90, 120, 180, 240, ...(t.estimate_minutes ? [t.estimate_minutes] : [])])].sort((a, b) => a - b).map((m) => <option key={m} value={m}>{mins(m)}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1">Snooze
            <select value="" aria-label="Snooze" onChange={(e) => { if (e.target.value) act(() => myTasks.snooze(id, e.target.value)); }}
              className="rounded-md border border-line bg-ground/60 px-1 py-0.5 text-ink">
              <option value="">{t.snoozed_until ? `until ${dueLabel(t.snoozed_until)}` : "choose"}</option>
              {SNOOZE.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              {t.snoozed_until ? <option value="wake">Wake it now</option> : null}
            </select>
          </label>
          {t.blocked_by ? <span>Waiting on “{t.blocked_by_title}” <button type="button" className="underline" onClick={() => act(() => myTasks.edit(id, { blocked_by: null }))}>clear</button></span> : null}
          {t.focus_minutes ? <span>{mins(t.focus_minutes)} focused</span> : null}
          <Button onClick={() => { const n = window.prompt("Template name", t.title); if (n) act(() => myTasks.saveTemplate(id, n)); }}>Save as template</Button>
        </div>
      ) : null}
      {runnable && est.data ? (
        <p className="text-xs text-ink-3">
          {est.data.cost_usd ? <b className="text-ink-2">Estimate: about ${Number(est.data.cost_usd.typical).toFixed(2)} (up to ${Number(est.data.cost_usd.high).toFixed(2)}). </b> : null}
          {est.data.note}
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
      {t.result && t.mission?.status === "COMPLETED" ? (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-ink-2">{t.feedback ? (t.feedback.rating > 0 ? "You rated this useful." : `You rated this not useful${t.feedback.reason ? `: ${t.feedback.reason}` : ""}.`) : "Was it useful?"}</span>
          <input aria-label="Why? (optional)" value={why} onChange={(e) => setWhy(e.target.value)} placeholder="Why? (optional)"
            className="min-w-0 flex-1 rounded-md border border-line bg-ground/60 px-2 py-1 text-ink" />
          <Button aria-label="Useful" disabled={busy} onClick={() => { act(() => myTasks.feedback(id, 1, why)); setWhy(""); }}>👍</Button>
          <Button aria-label="Not useful" disabled={busy} onClick={() => { act(() => myTasks.feedback(id, -1, why)); setWhy(""); }}>👎</Button>
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
        {t.status === "OPEN" ? <Button disabled={busy} onClick={() => act(() => myTasks.drop(id))}>Drop</Button> : t.status === "DONE" ? <Button disabled={busy} onClick={() => act(() => myTasks.undoDone(id))}>Undo done</Button> : <Button disabled={busy} onClick={() => act(() => myTasks.reopen(id))}>Reopen</Button>}
        <Button disabled={busy} onClick={() => { if (window.confirm("Delete this task from your list?")) act(() => myTasks.remove(id)); }}>Delete</Button>
      </div>
      {t.status === "OPEN" ? (
        <label className="flex items-center gap-1 text-xs text-ink-2">Repeats
          <select value={t.repeat} aria-label="Repeats" onChange={(e) => act(() => myTasks.edit(id, { repeat: e.target.value }))}
            className="rounded-md border border-line bg-ground/60 px-1 py-0.5 text-ink">
            {REPEATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            {!REPEATS.some(([v]) => v === t.repeat) ? <option value={t.repeat}>{t.repeat_label || t.repeat}</option> : null}
          </select>
          {t.streak?.times ? <span className="ml-2">🔥 {t.streak.current} in a row (best {t.streak.best})</span> : null}
        </label>
      ) : null}
      {t.links?.length || t.status === "OPEN" ? (
        <div className="text-xs">
          <p className="font-semibold text-ink-2">Links <span className="font-normal text-ink-3">(open in a new tab; the agents don't visit them)</span></p>
          <ul>{(t.links ?? []).map((l: Json) => (
            <li key={l.id} className="flex items-center gap-2">
              <a href={l.url} target="_blank" rel="noopener noreferrer nofollow" className="min-w-0 flex-1 truncate text-[#32D8FF] underline">{l.title || l.url}</a>
              <button type="button" className="text-ink-3 hover:text-bad" aria-label={`Remove ${l.url}`} onClick={() => act(() => myTasks.removeLink(id, l.id))}>×</button>
            </li>
          ))}</ul>
          {t.status === "OPEN" ? (
            <form className="mt-1 flex gap-1.5" onSubmit={(e) => { e.preventDefault(); if (/^https?:\/\//i.test(link.trim())) { act(() => myTasks.addLink(id, link.trim())); setLink(""); } }}>
              <input aria-label="Add a link" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://…" type="url"
                className="min-w-0 flex-1 rounded-md border border-line bg-ground/60 px-2 py-1 text-ink" />
              <Button type="submit" disabled={!/^https?:\/\//i.test(link.trim()) || busy}>Add</Button>
            </form>
          ) : null}
        </div>
      ) : null}
      {t.status === "OPEN" ? <PeopleAndGoals t={t} act={act} /> : null}
      <details onToggle={(e) => setShowHistory((e.target as HTMLDetailsElement).open)}>
        <summary className="cursor-pointer text-xs text-ink-2">History</summary>
        <ol className="mt-1 space-y-0.5 text-xs text-ink-3">
          {(hist.data?.history ?? []).map((h: Json, i: number) => (
            <li key={i}><span className="text-ink-2">{new Date(h.at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span> · {h.text}</li>
          ))}
        </ol>
      </details>
      <ErrorNote error={q.error} />
    </div>
  );
}

const REPEATS: [string, string][] = [["none", "Never"], ["daily", "Every day"], ["weekdays", "Weekdays"], ["weekly", "Every week"],
  ["biweekly", "Every 2 weeks"], ["monthly", "Every month"], ["monthly_last", "Last day of the month"], ["yearly", "Every year"]];

/** Plan my day, the weekly review, results, insights and templates (V6.74–V6.84). */
function TaskTools({ tool, refresh }: { tool: string; refresh: () => void }) {
  if (tool === "plan") return <PlanDay />;
  if (tool === "review") return <Review refresh={refresh} />;
  if (tool === "habits") return <Habits />;
  if (tool === "fit") return <Fit />;
  if (tool === "money") return <Money />;
  if (tool === "eod") return <EndOfDay refresh={refresh} />;
  if (tool === "goals") return <Goals />;
  if (tool === "bills") return <Bills />;
  if (tool === "month") return <Month />;
  if (tool === "dump") return <Dump refresh={refresh} />;
  if (tool === "archive") return <Archive refresh={refresh} />;
  if (tool === "results") return <Results />;
  if (tool === "insights") return <Insights />;
  return <Templates refresh={refresh} />;
}

/** RFC 5545: lines over 75 bytes continue on the next line after a space, never splitting a character. */
function fold(line: string): string {
  const enc = new TextEncoder();
  const out: string[] = [];
  let cur = "";
  let bytes = 0;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (bytes + n > (out.length ? 74 : 75)) { out.push(cur); cur = ""; bytes = 0; }
    cur += ch; bytes += n;
  }
  out.push(cur);
  return out.join("\r\n ");
}

function icsFor(plan: Json): string {
  const f = (iso: string) => new Date(iso).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const esc = (s: string) => s.replace(/\\/g, "\\\\").replace(/[;,]/g, (c) => `\\${c}`).replace(/\r\n|\r|\n/g, "\\n");
  const now = f(new Date().toISOString());
  const ev = (plan.blocks as Json[]).flatMap((b) => ["BEGIN:VEVENT", `UID:${b.task_id}-${f(b.start)}@aiciv`, `DTSTAMP:${now}`, `DTSTART:${f(b.start)}`,
    `DTEND:${f(b.end)}`, `SUMMARY:${esc(`${b.verb}: ${b.title}`)}`,
    `DESCRIPTION:${esc(b.estimated ? `${b.minutes} minutes (a default length, not your estimate)` : `${b.minutes} minutes`)}`, "END:VEVENT"]);
  return ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//AI Civilization//Plan my day//EN", "CALSCALE:GREGORIAN", ...ev, "END:VCALENDAR"]
    .map(fold).join("\r\n") + "\r\n";
}

function PlanDay() {
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("18:00");
  const q = useQuery({ queryKey: ["plan", start, end], queryFn: () => myTasks.plan(start, end) });
  const p = q.data;
  const download = () => {
    const url = URL.createObjectURL(new Blob([icsFor(p!)], { type: "text/calendar" }));
    const a = document.createElement("a");
    a.href = url; a.download = "plan-my-day.ics"; a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      <div className="flex items-center gap-2 text-xs text-ink-2">
        <label>From <input type="time" value={start} onChange={(e) => setStart(e.target.value)} className="rounded border border-line bg-ground/60 px-1 text-ink" /></label>
        <label>to <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded border border-line bg-ground/60 px-1 text-ink" /></label>
        {p ? <span>{mins(p.planned_minutes)} planned · {mins(p.free_minutes)} free</span> : null}
        {p?.blocks?.length ? <Button className="ml-auto" onClick={download}>Download .ics</Button> : null}
      </div>
      {q.isLoading ? <Skeleton lines={3} /> : null}
      <ErrorNote error={q.error} />
      {p && !p.blocks.length ? <Empty>Nothing to plan for the rest of the day.</Empty> : null}
      <ol className="space-y-1">
        {(p?.blocks ?? []).map((b: Json) => (
          <li key={b.task_id + b.start} className="flex items-baseline gap-2">
            <span className="w-16 shrink-0 text-right font-mono text-xs text-ink-2">{new Date(b.start).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
            <span className="h-3 w-1 shrink-0 rounded" style={{ background: KIND_COLOR[b.kind] ?? "#A66BFF" }} />
            <span className="min-w-0 flex-1 truncate">{b.title}</span>
            <Pill color={b.verb === "Decide" ? "#FFBD69" : b.verb === "Review" ? "#5BF2A5" : "#32D8FF"}>{b.verb}</Pill>
            <span className="text-xs text-ink-3">{mins(b.minutes)}{b.estimated ? " (default)" : ""}</span>
          </li>
        ))}
      </ol>
      {p?.later?.length ? <p className="text-xs text-ink-3">Doesn't fit today: {p.later.map((l: Json) => l.title).join(", ")}</p> : null}
    </div>
  );
}

function Review({ refresh }: { refresh: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["review"], queryFn: myTasks.review });
  const [picked, setPicked] = useState<string[]>([]);
  const bulk = useMutation({ mutationFn: (action: string) => myTasks.bulk(picked, action), onSuccess: () => { setPicked([]); refresh(); qc.invalidateQueries({ queryKey: ["review"] }); } });
  const r = q.data;
  const group = (name: string, list: Json[]) => (list?.length ? (
    <div key={name}>
      <h5 className="text-xs font-semibold text-ink-2">{name} ({list.length})</h5>
      <ul>{list.map((t) => (
        <li key={t.id} className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={picked.includes(t.id)} aria-label={`Pick ${t.title}`}
            onChange={() => setPicked(picked.includes(t.id) ? picked.filter((x) => x !== t.id) : [...picked, t.id])} />
          <span className="truncate">{t.title}</span>
          {t.due_at ? <span className={t.overdue ? "text-bad" : "text-ink-3"}>{dueLabel(t.due_at)}</span> : null}
        </li>
      ))}</ul>
    </div>
  ) : null);
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      {q.isLoading ? <Skeleton lines={3} /> : null}
      <ErrorNote error={q.error ?? bulk.error} />
      {r ? <p className="text-xs text-ink-2">{r.summary}</p> : null}
      {r ? [group("Slipped", r.slipped), group("Sitting for two weeks or more", r.stale), group("Due in the next seven days", r.upcoming)] : null}
      {picked.length ? (
        <div className="flex gap-1.5">
          <Button disabled={bulk.isPending} onClick={() => bulk.mutate("done")}>Mark {picked.length} done</Button>
          <Button disabled={bulk.isPending} onClick={() => bulk.mutate("next_week")}>Next week</Button>
          <Button disabled={bulk.isPending} onClick={() => bulk.mutate("drop")}>Drop</Button>
        </div>
      ) : null}
    </div>
  );
}

function Results() {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { const t = window.setTimeout(() => setQ(text), 250); return () => clearTimeout(t); }, [text]);
  const r = useQuery({ queryKey: ["task-results", q], queryFn: () => myTasks.results(q) });
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      <input aria-label="Search results" value={text} onChange={(e) => setText(e.target.value)} placeholder="Search what the agents wrote"
        className="w-full rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink" />
      <ErrorNote error={r.error} />
      {r.data && !r.data.results.length ? <Empty>{q ? `Nothing matches "${q}".` : "No results yet."}</Empty> : null}
      {(r.data?.results ?? []).map((x) => (
        <details key={x.artifact_id} className="rounded-md bg-ground/40 p-1.5">
          <summary className="cursor-pointer text-xs">
            <b>{x.task_title ?? x.title}</b> {x.simulated ? <Pill color="#FFBD69">simulation</Pill> : null} {x.rating ? (x.rating > 0 ? "👍" : "👎") : null}
            <span className="block truncate text-ink-3">{x.excerpt}</span>
          </summary>
          <pre className="mt-1 max-h-72 overflow-auto whitespace-pre-wrap font-sans text-xs">{x.content}</pre>
        </details>
      ))}
    </div>
  );
}

function Insights() {
  const [days, setDays] = useState(14);
  const q = useQuery({ queryKey: ["insights", days], queryFn: () => myTasks.insights(days) });
  const a = useQuery({ queryKey: ["agent-quality"], queryFn: myTasks.agentQuality });
  const i = q.data;
  const top = Math.max(1, ...((i?.series ?? []) as Json[]).map((d) => Math.max(d.done, d.added)));
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      <div className="flex gap-1.5">{[14, 30, 60].map((d) => <Button key={d} aria-pressed={days === d} variant={days === d ? "primary" : "quiet"} onClick={() => setDays(d)}>{d} days</Button>)}</div>
      {q.isLoading ? <Skeleton lines={3} /> : null}
      <ErrorNote error={q.error} />
      {i ? (
        <>
          <p className="font-semibold">{i.headline}</p>
          <div className="flex h-24 items-end gap-0.5" role="img" aria-label={`${i.done} done and ${i.added} added over ${i.days} days`}>
            {(i.series as Json[]).map((d) => (
              <div key={d.day} className="flex flex-1 items-end gap-px" title={`${d.day}: ${d.done} done, ${d.added} added, ${d.focus_minutes}m focused`}>
                <div className="flex-1 rounded-t bg-[#5BF2A5]" style={{ height: `${(d.done / top) * 100}%` }} />
                <div className="flex-1 rounded-t bg-[#32D8FF]/60" style={{ height: `${(d.added / top) * 100}%` }} />
              </div>
            ))}
          </div>
          <p className="text-xs text-ink-3"><span className="text-[#5BF2A5]">■</span> done <span className="text-[#32D8FF]">■</span> added · {i.open} open · on time {i.on_time_rate == null ? "n/a" : `${Math.round(i.on_time_rate * 100)}%`} · {mins(i.focus_minutes)} focused · runs {i.runs.completed} finished, {i.runs.failed} failed{i.runs.simulated ? ` (${i.runs.simulated} simulated)` : ""}</p>
        </>
      ) : null}
      {a.data?.agents?.length ? (
        <div>
          <h5 className="text-xs font-semibold text-ink-2">Your ratings by agent</h5>
          <ul className="text-xs">{a.data.agents.map((x) => <li key={x.agent}>{x.name}: 👍 {x.up} · 👎 {x.down}{x.recent_reasons.length ? ` — ${x.recent_reasons.join("; ")}` : ""}</li>)}</ul>
        </div>
      ) : null}
    </div>
  );
}

function Templates({ refresh }: { refresh: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["templates"], queryFn: myTasks.templates });
  const act = useMutation({ mutationFn: (f: () => Promise<Json>) => f(), onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["templates"] }); } });
  return (
    <div className="space-y-1 rounded-lg border border-line p-2 text-sm">
      <ErrorNote error={q.error ?? act.error} />
      {q.data && !q.data.templates.length ? <Empty>No templates yet. Open a task and choose Save as template.</Empty> : null}
      {(q.data?.templates ?? []).map((t) => (
        <div key={t.id} className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate"><b>{t.name}</b> <span className="text-xs text-ink-3">{t.title}{t.items.length ? ` · ${t.items.length} steps` : ""}</span></span>
          <Button disabled={act.isPending} onClick={() => act.mutate(() => myTasks.useTemplate(t.id))}>Start a copy</Button>
          <Button disabled={act.isPending} onClick={() => { if (window.confirm(`Delete the template "${t.name}"?`)) act.mutate(() => myTasks.deleteTemplate(t.id)); }}>Delete</Button>
        </div>
      ))}
    </div>
  );
}

/** V6.95: streaks on repeating tasks. */
function Habits() {
  const q = useQuery({ queryKey: ["habits"], queryFn: myTasks.habits });
  const color: Record<string, string> = { done: "#5BF2A5", late: "#FFBD69", missed: "#FF6B6B", open: "transparent" };
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      {q.isLoading ? <Skeleton lines={2} /> : null}
      <ErrorNote error={q.error} />
      {q.data && !q.data.habits.length ? <Empty>No repeating tasks yet. Try "stretch every day" or "pay rent on the 1st of every month".</Empty> : null}
      {(q.data?.habits ?? []).map((h) => (
        <div key={h.task_id}>
          <div className="flex items-center gap-2"><b className="min-w-0 flex-1 truncate">{h.title}</b><span>🔥 {h.current}</span></div>
          <div className="mt-0.5 flex gap-0.5" aria-hidden>
            {h.recent.map((o: Json, i: number) => <span key={i} className="size-3 rounded-sm border border-white/10" style={{ background: color[o.outcome] }} />)}
          </div>
          <p className="text-xs text-ink-3">{h.repeat_label} · best {h.best} in a row{h.on_time_rate != null ? ` · ${Math.round(h.on_time_rate * 100)}% on time` : ""}</p>
        </div>
      ))}
    </div>
  );
}

/** V6.110: list colors, shared by every row (loaded once). */
let STYLES: Record<string, { color: string; icon: string }> = {};
function styleOf(name: string) { return STYLES[name]; }
export function useListStyles() {
  const q = useQuery({ queryKey: ["list-styles"], queryFn: myTasks.styles, staleTime: 60_000 });
  if (q.data) STYLES = q.data.styles;
  return q;
}

function PeopleAndGoals({ t, act }: { t: Json; act: (f: () => Promise<Json>) => void }) {
  const goals = useQuery({ queryKey: ["goals"], queryFn: myTasks.goals });
  const [person, setPerson] = useState("");
  const [when, setWhen] = useState("");
  return (
    <div className="space-y-1 text-xs text-ink-2">
      {t.waiting_for ? (
        <p>Waiting for <b>{t.waiting_for.person}</b>, follow up {new Date(t.waiting_for.follow_up_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}{" "}
          <button type="button" className="underline" onClick={() => act(() => myTasks.waiting(t.id, null, null))}>no longer waiting</button></p>
      ) : (
        <form className="flex flex-wrap items-center gap-1.5" onSubmit={(e) => { e.preventDefault(); if (person.trim() && when) { act(() => myTasks.waiting(t.id, person.trim(), new Date(when).toISOString())); setPerson(""); } }}>
          <input aria-label="Waiting for someone" value={person} onChange={(e) => setPerson(e.target.value)} placeholder="Waiting for someone?" className="w-40 rounded-md border border-line bg-ground/60 px-2 py-1 text-ink" />
          <input aria-label="Follow-up date" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className="rounded-md border border-line bg-ground/60 px-1 py-0.5 text-ink" />
          <Button type="submit" disabled={!person.trim() || !when}>Save</Button>
        </form>
      )}
      {goals.data?.goals?.length ? (
        <label className="flex items-center gap-1">Counts toward
          <select value={t.goal_id ?? ""} aria-label="Weekly goal" onChange={(e) => act(() => myTasks.linkGoal(t.id, e.target.value || null))} className="rounded-md border border-line bg-ground/60 px-1 py-0.5 text-ink">
            <option value="">no goal</option>
            {goals.data.goals.map((g: Json) => <option key={g.id} value={g.id}>{g.text}</option>)}
          </select>
        </label>
      ) : null}
    </div>
  );
}

const money = (n: number | null | undefined) => (n == null ? "varies" : n.toLocaleString(undefined, { style: "currency", currency: "USD" }));

function Fit() {
  const [m, setM] = useState(30);
  const q = useQuery({ queryKey: ["fit", m], queryFn: () => myTasks.fit(m) });
  return (
    <div className="space-y-1 rounded-lg border border-line p-2 text-sm">
      <div className="flex gap-1.5">{[15, 30, 60, 90].map((x) => <Button key={x} aria-pressed={m === x} variant={m === x ? "primary" : "quiet"} onClick={() => setM(x)}>{mins(x)}</Button>)}</div>
      <ErrorNote error={q.error} />
      {q.data && !q.data.picks.length ? <Empty>Nothing on your list fits in {mins(m)}.</Empty> : null}
      <ul>{(q.data?.picks ?? []).map((p: Json) => <li key={p.task_id}>{p.title} <span className="text-xs text-ink-3">{mins(p.minutes)}{p.estimated ? " (default)" : ""}{p.overdue ? " · overdue" : ""}</span></li>)}</ul>
    </div>
  );
}

function EndOfDay({ refresh }: { refresh: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["shutdown"], queryFn: myTasks.shutdown });
  const [note, setNote] = useState("");
  const [move, setMove] = useState(true);
  const close = useMutation({ mutationFn: () => myTasks.closeDay(move && !!q.data?.still_due?.length, note), onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["shutdown"] }); } });
  const s = q.data;
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      <ErrorNote error={q.error ?? close.error} />
      {s?.yesterdays_note ? <p className="text-xs text-ink-2">Yesterday's note: {s.yesterdays_note}</p> : null}
      {s ? <p className="text-xs">Done today: {s.done.length ? s.done.map((x: Json) => x.title).join(", ") : "nothing yet"}</p> : null}
      {s?.still_due?.length ? (
        <label className="flex items-center gap-1.5 text-xs"><input type="checkbox" checked={move} onChange={(e) => setMove(e.target.checked)} />
          Move {s.still_due.length} still due ({s.still_due.map((x: Json) => x.title).join(", ")}) to tomorrow</label>
      ) : null}
      <input aria-label="A note for tomorrow" value={note} onChange={(e) => setNote(e.target.value)} placeholder={s?.note || "A note for tomorrow"} className="w-full rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink" />
      <Button variant="primary" disabled={close.isPending || !s} onClick={() => close.mutate()}>Close the day</Button>
      {close.isSuccess ? <p className="text-xs text-[#5BF2A5]">Closed. Moved {close.data.moved.length}.</p> : null}
    </div>
  );
}

function Goals() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["goals"], queryFn: myTasks.goals });
  const [text, setText] = useState("");
  const act = useMutation({ mutationFn: (f: () => Promise<Json>) => f(), onSuccess: () => qc.invalidateQueries({ queryKey: ["goals"] }) });
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      <ErrorNote error={q.error ?? act.error} />
      {q.data ? <p className="text-xs text-ink-3">Week of {q.data.week_start}</p> : null}
      {(q.data?.goals ?? []).map((g: Json) => (
        <div key={g.id}>
          <div className="flex items-center gap-2">
            <input type="checkbox" checked={g.done} aria-label={`Reached: ${g.text}`} onChange={() => act.mutate(() => myTasks.setGoal(g.id, !g.done))} />
            <b className={`min-w-0 flex-1 ${g.done ? "line-through" : ""}`}>{g.text}</b>
            <button type="button" className="text-ink-3 hover:text-bad" aria-label={`Remove ${g.text}`} onClick={() => act.mutate(() => myTasks.removeGoal(g.id))}>×</button>
          </div>
          <div className="mt-1 h-1.5 rounded bg-white/10" role="progressbar" aria-valuenow={Math.round(g.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full rounded bg-[#FFBD69]" style={{ width: `${g.progress * 100}%` }} />
          </div>
          <p className="text-xs text-ink-3">{g.tasks.length ? `${g.tasks_done} of ${g.tasks.length} linked tasks done` : "Link tasks from their details."}</p>
        </div>
      ))}
      {(q.data?.goals?.length ?? 0) < 3 ? (
        <form className="flex gap-1.5" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { act.mutate(() => myTasks.addGoal(text.trim())); setText(""); } }}>
          <input aria-label="A goal for this week" value={text} onChange={(e) => setText(e.target.value)} placeholder="A goal for this week (up to 3)" className="min-w-0 flex-1 rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink" />
          <Button type="submit" disabled={!text.trim()}>Add</Button>
        </form>
      ) : null}
    </div>
  );
}

function Bills() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["bills"], queryFn: myTasks.bills });
  const s = useQuery({ queryKey: ["bills", "summary"], queryFn: myTasks.billSummary });
  const act = useMutation({ mutationFn: (f: () => Promise<Json>) => f(), onSuccess: () => qc.invalidateQueries({ queryKey: ["bills"] }) });
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [day, setDay] = useState("1");
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      <ErrorNote error={q.error ?? act.error} />
      {s.data ? <p className="text-xs text-ink-2">This month {money(s.data.total)}{s.data.varies_count ? ` + ${s.data.varies_count} that vary` : ""} · paid {money(s.data.paid)} · next 30 days {money(s.data.next_30_total)}{s.data.overdue.length ? ` · ${s.data.overdue.length} past due` : ""}</p> : null}
      <p className="text-xs text-ink-3">AI Civ doesn't pay bills or move money. Pay wherever you normally do, then mark it paid.</p>
      <ul className="space-y-1">{(q.data?.bills ?? []).map((b: Json) => (
        <li key={b.id} className="flex flex-wrap items-center gap-2">
          <b className="min-w-0 flex-1 truncate">{b.name}{b.autopay ? " (autopay)" : ""}</b>
          <span>{money(b.amount)}</span>
          <label className="flex items-center gap-1 text-xs text-ink-3"><input type="checkbox" checked={!!b.subscription}
            onChange={(e) => act.mutate(() => myTasks.setSubscription(b.id, { subscription: e.target.checked }))} /> subscription</label>
          <button type="button" className="text-xs underline" title="Adds a research task; it only starts if you press Do it"
            onClick={() => act.mutate(() => myTasks.findSavings(b.id))}>find cheaper</button>
          <span className={`text-xs ${b.overdue ? "text-bad" : "text-ink-3"}`}>{b.overdue ? `was due ${b.next_due}` : `due ${b.next_due}`}</span>
          {b.link_url ? <a href={b.link_url} target="_blank" rel="noopener noreferrer nofollow" className="text-xs text-[#32D8FF] underline">pay page</a> : null}
          {b.paid_this_period && !b.overdue ? <span className="text-xs text-[#5BF2A5]">paid ✓ <button type="button" className="underline" onClick={() => act.mutate(() => myTasks.billUnpaid(b.id, b.this_period))}>undo</button></span>
            : <Button disabled={act.isPending} onClick={() => act.mutate(() => myTasks.billPaid(b.id))}>Mark paid</Button>}
          <button type="button" className="text-ink-3 hover:text-bad" aria-label={`Delete ${b.name}`} onClick={() => { if (window.confirm(`Delete the bill "${b.name}"?`)) act.mutate(() => myTasks.removeBill(b.id)); }}>×</button>
        </li>
      ))}</ul>
      <form className="flex flex-wrap gap-1.5" onSubmit={(e) => { e.preventDefault(); if (name.trim()) { act.mutate(() => myTasks.addBill({ name: name.trim(), amount: amount ? Number(amount) : null, due_day: Number(day) })); setName(""); setAmount(""); } }}>
        <input aria-label="Bill name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Bill (Rent, Phone…)" className="min-w-0 flex-1 rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink" />
        <input aria-label="Amount" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Amount" inputMode="decimal" className="w-20 rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink" />
        <label className="flex items-center gap-1 text-xs text-ink-2">due on
          <select aria-label="Due day" value={day} onChange={(e) => setDay(e.target.value)} className="rounded-md border border-line bg-ground/60 px-1 py-0.5 text-ink">
            {Array.from({ length: 31 }, (_, i) => String(i + 1)).map((d) => <option key={d} value={d}>{d === "31" ? "31 (or last day)" : d}</option>)}
          </select></label>
        <Button type="submit" disabled={!name.trim() || (amount !== "" && Number.isNaN(Number(amount)))}>Add bill</Button>
      </form>
    </div>
  );
}

function Month() {
  const now = new Date();
  const [ym, setYm] = useState({ y: now.getFullYear(), m: now.getMonth() + 1 });
  const [picked, setPicked] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["month", ym.y, ym.m], queryFn: () => myTasks.month(ym.y, ym.m) });
  const days = new Date(ym.y, ym.m, 0).getDate();
  const lead = (new Date(ym.y, ym.m - 1, 1).getDay() + 6) % 7; // weeks start on Monday
  const step = (n: number) => { const d = new Date(ym.y, ym.m - 1 + n, 1); setYm({ y: d.getFullYear(), m: d.getMonth() + 1 }); setPicked(null); };
  const key = (d: number) => `${ym.y}-${String(ym.m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  const day = picked ? q.data?.days?.[picked] : null;
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      <div className="flex items-center justify-between">
        <button type="button" aria-label="Previous month" onClick={() => step(-1)}>‹</button>
        <b>{new Date(ym.y, ym.m - 1, 1).toLocaleString([], { month: "long", year: "numeric" })}</b>
        <button type="button" aria-label="Next month" onClick={() => step(1)}>›</button>
      </div>
      <ErrorNote error={q.error} />
      <div className="grid grid-cols-7 gap-0.5 text-center text-xs">
        {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => <span key={i} className="text-ink-3">{d}</span>)}
        {Array.from({ length: lead }, (_, i) => <span key={`x${i}`} />)}
        {Array.from({ length: days }, (_, i) => i + 1).map((d) => {
          const info = q.data?.days?.[key(d)];
          return (
            <button key={d} type="button" onClick={() => setPicked(key(d))} aria-label={`${d}: ${info?.tasks.length ?? 0} tasks, ${info?.bills.length ?? 0} bills`}
              className={`rounded py-1 ${picked === key(d) ? "bg-white/15" : "hover:bg-white/5"}`}>
              {d}
              <span className="flex justify-center gap-0.5">
                {info?.tasks.length ? <span className="size-1 rounded-full bg-[#32D8FF]" /> : null}
                {info?.bills.length ? <span className="size-1 rounded-full bg-[#FFBD69]" /> : null}
              </span>
            </button>
          );
        })}
      </div>
      {day ? (
        <ul className="text-xs">
          {day.bills.map((b: Json) => <li key={b.id} className="text-[#FFBD69]">$ {b.name} {money(b.amount)}{b.paid ? " · paid" : ""}</li>)}
          {day.tasks.map((t: Json) => <li key={t.id}>{t.stage === "done" ? "✓" : "○"} {t.title}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

function Dump({ refresh }: { refresh: () => void }) {
  const [text, setText] = useState("");
  const [format, setFormat] = useState("lines");
  const [preview, setPreview] = useState<Json[]>([]);
  useEffect(() => {
    if (text.trim().length < 2) { setPreview([]); return; }
    const h = window.setTimeout(() => { myTasks.dump(text, format).then((r) => setPreview(r.preview)).catch(() => setPreview([])); }, 400);
    return () => clearTimeout(h);
  }, [text, format]);
  const add = useMutation({ mutationFn: () => myTasks.dump(text, format, false), onSuccess: () => { setText(""); setPreview([]); refresh(); } });
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      <div className="flex gap-1.5">{[["lines", "One per line"], ["csv", "CSV"]].map(([k, l]) => <Button key={k} aria-pressed={format === k} variant={format === k ? "primary" : "quiet"} onClick={() => setFormat(k)}>{l}</Button>)}
        <label className="ml-auto cursor-pointer text-xs text-ink-2 underline">Import a file
          <input type="file" accept=".csv,.txt,text/plain,text/csv" className="hidden" onChange={async (e) => {
            const f = e.target.files?.[0]; if (!f) return;
            setText((await f.text()).slice(0, 40_000)); setFormat(f.name.toLowerCase().endsWith(".csv") ? "csv" : "lines");
          }} /></label>
      </div>
      <textarea aria-label="Tasks, one per line" value={text} onChange={(e) => setText(e.target.value)} rows={5}
        placeholder={format === "csv" ? "title,list,due,notes,priority,estimate" : "call the bank tomorrow #money 15m\nbook flights by friday"}
        className="w-full rounded-md border border-line bg-ground/60 px-2 py-1 font-mono text-xs text-ink" />
      <ErrorNote error={add.error} />
      {preview.length ? (
        <>
          <ul className="text-xs">{preview.map((p, i) => <li key={i}>• {p.title}{p.due_label ? ` · ${p.due_label}` : ""}{p.list_name ? ` · #${p.list_name}` : ""}</li>)}</ul>
          <Button variant="primary" disabled={add.isPending} onClick={() => add.mutate()}>Add all {preview.length}</Button>
        </>
      ) : null}
      {add.isSuccess ? <p className="text-xs text-[#5BF2A5]">Added {add.data.added.length}.{add.data.problems.length ? ` ${add.data.problems.length} couldn't be added.` : ""}</p> : null}
    </div>
  );
}

function Archive({ refresh }: { refresh: () => void }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const a = useQuery({ queryKey: ["archive", q], queryFn: () => myTasks.archive(q) });
  const restore = useMutation({ mutationFn: (id: string) => myTasks.reopen(id), onSuccess: () => { refresh(); qc.invalidateQueries({ queryKey: ["archive"] }); } });
  const [err, setErr] = useState<unknown>(null);
  const download = async (format: "json" | "csv") => {
    try {
      const url = URL.createObjectURL(await myTasks.exportFile(format));
      const el = document.createElement("a");
      el.href = url; el.download = `my-tasks.${format}`; el.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);  // let the download start first
    } catch (e) { setErr(e); }
  };
  return (
    <div className="space-y-2 rounded-lg border border-line p-2 text-sm">
      <div className="flex gap-1.5"><Button onClick={() => download("json")}>Export JSON</Button><Button onClick={() => download("csv")}>Export CSV</Button></div>
      <ErrorNote error={err ?? a.error ?? restore.error} />
      <input aria-label="Search the archive" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the archive" className="w-full rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink" />
      {a.data && !a.data.tasks.length ? <Empty>Nothing archived. Tasks closed more than 30 days ago land here.</Empty> : null}
      <ul className="space-y-0.5 text-xs">{(a.data?.tasks ?? []).map((t) => (
        <li key={t.id} className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate">{t.title}</span>
          <span className="text-ink-3">{t.status === "DONE" ? "done" : "dropped"}</span>
          <button type="button" className="underline" onClick={() => restore.mutate(t.id)}>restore</button></li>
      ))}</ul>
    </div>
  );
}

/** V6.113–V6.127: budget, payday planner, income, savings, subscriptions and credit — from what you type in. */
function Money() {
  const qc = useQueryClient();
  const b = useQuery({ queryKey: ["money", "budget"], queryFn: myTasks.budget });
  const pl = useQuery({ queryKey: ["money", "planner"], queryFn: myTasks.planner });
  const inc = useQuery({ queryKey: ["money", "income"], queryFn: myTasks.income });
  const sav = useQuery({ queryKey: ["money", "savings"], queryFn: myTasks.savings });
  const subs = useQuery({ queryKey: ["money", "subs"], queryFn: myTasks.subscriptions });
  const cr = useQuery({ queryKey: ["money", "credit"], queryFn: myTasks.credit });
  const pay = useQuery({ queryKey: ["money", "pay"], queryFn: myTasks.pay });
  const act = useMutation({ mutationFn: (f: () => Promise<Json>) => f(), onSuccess: () => qc.invalidateQueries({ queryKey: ["money"] }) });
  const [amt, setAmt] = useState(""); const [src, setSrc] = useState(""); const [hrs, setHrs] = useState("");
  const [gName, setGName] = useState(""); const [gTarget, setGTarget] = useState(""); const [gMonthly, setGMonthly] = useState("");
  const [cName, setCName] = useState(""); const [cLimit, setCLimit] = useState(""); const [cBal, setCBal] = useState("");
  const [pCad, setPCad] = useState("biweekly"); const [pDay, setPDay] = useState(""); const [pAmt, setPAmt] = useState("");
  const input = "rounded-md border border-line bg-ground/60 px-2 py-1 text-xs text-ink";
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  return (
    <div className="space-y-3 rounded-lg border border-line p-2 text-sm">
      <ErrorNote error={act.error ?? b.error} />
      {b.data ? (
        <div>
          <h5 className="text-xs font-semibold text-ink-2">This month</h5>
          <p className="text-xs">Income {money(b.data.income)} − bills {money(b.data.bills)}{b.data.bills_vary ? ` (+${b.data.bills_vary} that vary)` : ""} − savings plan {money(b.data.savings_plan)} = <b className={b.data.left < 0 ? "text-bad" : "text-[#5BF2A5]"}>{money(b.data.left)} left</b></p>
        </div>
      ) : null}
      <div>
        <h5 className="text-xs font-semibold text-ink-2">Payday planner</h5>
        {(pl.data?.periods ?? []).map((p: Json) => (
          <p key={p.from} className="text-xs">{p.from} → {p.to}: {p.bills.length ? p.bills.map((x: Json) => `${x.name} ${money(x.amount)}`).join(", ") : "no bills"} · needs {money(p.needed)}{p.left != null ? ` · left ${money(p.left)}` : ""}</p>
        ))}
        <p className="text-xs text-ink-3">Paydays: {(pay.data?.schedules ?? []).map((s: Json) => `${s.name} (${s.cadence}) next ${s.next[0]}`).join("; ") || "none yet"}</p>
        <form className="mt-1 flex flex-wrap gap-1" onSubmit={(e) => { e.preventDefault(); if (pDay) act.mutate(() => myTasks.addPay({ name: "Paycheck", cadence: pCad, anchor_day: pDay, amount: pAmt ? Number(pAmt) : null })); }}>
          <select aria-label="How often you get paid" value={pCad} onChange={(e) => setPCad(e.target.value)} className={input}>
            <option value="weekly">weekly</option><option value="biweekly">every 2 weeks</option><option value="semimonthly">15th + last day</option><option value="monthly">monthly</option>
          </select>
          <input aria-label="A recent payday" type="date" value={pDay} onChange={(e) => setPDay(e.target.value)} className={input} />
          <input aria-label="Usual pay" value={pAmt} onChange={(e) => setPAmt(e.target.value)} placeholder="usual pay" inputMode="decimal" className={`w-24 ${input}`} />
          <Button type="submit" disabled={!pDay}>Add payday</Button>
        </form>
      </div>
      <div>
        <h5 className="text-xs font-semibold text-ink-2">Income · this week {money(inc.data?.week_total)}{inc.data?.week_hourly ? ` (${money(inc.data.week_hourly)}/hr)` : ""} · this month {money(inc.data?.month_total)}</h5>
        <form className="flex flex-wrap gap-1" onSubmit={(e) => { e.preventDefault(); if (Number(amt) > 0 && src.trim()) { act.mutate(() => myTasks.logIncome(Number(amt), src.trim(), hrs ? Number(hrs) : undefined)); setAmt(""); setHrs(""); } }}>
          <input aria-label="Amount earned" value={amt} onChange={(e) => setAmt(e.target.value)} placeholder="amount" inputMode="decimal" className={`w-20 ${input}`} />
          <input aria-label="Where it came from" value={src} onChange={(e) => setSrc(e.target.value)} placeholder="from" className={`w-32 ${input}`} />
          <input aria-label="Hours" value={hrs} onChange={(e) => setHrs(e.target.value)} placeholder="hours" inputMode="decimal" className={`w-16 ${input}`} />
          <Button type="submit" disabled={!(Number(amt) > 0) || !src.trim()}>Log</Button>
        </form>
      </div>
      <div>
        <h5 className="text-xs font-semibold text-ink-2">Savings</h5>
        {(sav.data?.goals ?? []).map((g: Json) => (
          <div key={g.id} className="text-xs">
            <div className="flex items-center gap-2"><b className="min-w-0 flex-1 truncate">{g.name}</b>{money(g.saved)} of {money(g.target)}
              <button type="button" className="underline" onClick={() => { const v = window.prompt(`Deposit to ${g.name} (negative to take out)`); if (v && Number(v)) act.mutate(() => myTasks.deposit(g.id, Number(v))); }}>deposit</button></div>
            <div className="h-1.5 rounded bg-white/10"><div className="h-full rounded bg-[#FFBD69]" style={{ width: pct(g.progress) }} /></div>
            {g.per_week_needed ? <p className="text-ink-3">{money(g.per_week_needed)} a week reaches it by {g.deadline}</p> : null}
          </div>
        ))}
        <form className="mt-1 flex flex-wrap gap-1" onSubmit={(e) => { e.preventDefault(); if (gName.trim() && Number(gTarget) > 0) { act.mutate(() => myTasks.addSavings({ name: gName.trim(), target: Number(gTarget), monthly_plan: gMonthly ? Number(gMonthly) : null })); setGName(""); setGTarget(""); setGMonthly(""); } }}>
          <input aria-label="Goal name" value={gName} onChange={(e) => setGName(e.target.value)} placeholder="goal" className={`w-28 ${input}`} />
          <input aria-label="Target" value={gTarget} onChange={(e) => setGTarget(e.target.value)} placeholder="target" inputMode="decimal" className={`w-20 ${input}`} />
          <input aria-label="Monthly plan" value={gMonthly} onChange={(e) => setGMonthly(e.target.value)} placeholder="per month" inputMode="decimal" className={`w-20 ${input}`} />
          <Button type="submit" disabled={!gName.trim() || !(Number(gTarget) > 0)}>Add goal</Button>
        </form>
      </div>
      {subs.data?.subscriptions?.length ? (
        <div>
          <h5 className="text-xs font-semibold text-ink-2">Subscriptions · {money(subs.data.yearly_total)} a year</h5>
          {subs.data.subscriptions.map((x: Json) => (
            <p key={x.bill_id} className="text-xs">{x.name} {money(x.yearly)}/yr {x.review_due ? <span className="text-[#FFBD69]">· review due</span> : null}{" "}
              <button type="button" className="underline" onClick={() => act.mutate(() => myTasks.setSubscription(x.bill_id, { reviewed: true }))}>still worth it</button></p>
          ))}
        </div>
      ) : null}
      <div>
        <h5 className="text-xs font-semibold text-ink-2">Credit{cr.data?.utilization != null ? ` · ${pct(cr.data.utilization)} used overall` : ""}{cr.data?.record?.on_time_rate != null ? ` · ${pct(cr.data.record.on_time_rate)} of bills paid on time` : ""}</h5>
        {(cr.data?.cards ?? []).map((c: Json) => (
          <p key={c.id} className="text-xs">{c.name}: {money(c.balance)} of {money(c.limit)} ({pct(c.utilization)}){" "}
            <button type="button" className="underline" onClick={() => { const v = window.prompt(`New balance for ${c.name}`); if (v != null && v !== "" && Number(v) >= 0) act.mutate(() => myTasks.editCard(c.id, { balance: Number(v) })); }}>update</button>{" "}
            <button type="button" className="text-ink-3" aria-label={`Delete ${c.name}`} onClick={() => act.mutate(() => myTasks.removeCard(c.id))}>×</button></p>
        ))}
        <form className="flex flex-wrap gap-1" onSubmit={(e) => { e.preventDefault(); if (cName.trim() && Number(cLimit) > 0) { act.mutate(() => myTasks.addCard({ name: cName.trim(), limit: Number(cLimit), balance: Number(cBal || 0) })); setCName(""); setCLimit(""); setCBal(""); } }}>
          <input aria-label="Card nickname" value={cName} onChange={(e) => setCName(e.target.value)} placeholder="nickname (no number)" className={`w-36 ${input}`} />
          <input aria-label="Limit" value={cLimit} onChange={(e) => setCLimit(e.target.value)} placeholder="limit" inputMode="decimal" className={`w-20 ${input}`} />
          <input aria-label="Balance" value={cBal} onChange={(e) => setCBal(e.target.value)} placeholder="balance" inputMode="decimal" className={`w-20 ${input}`} />
          <Button type="submit" disabled={!cName.trim() || !(Number(cLimit) > 0)}>Add card</Button>
        </form>
        {cr.data ? <p className="text-xs text-ink-3">{cr.data.note}</p> : null}
      </div>
      <p className="text-xs text-ink-3">Everything here comes from what you enter. AI Civ isn't connected to a bank and never moves money.</p>
    </div>
  );
}
