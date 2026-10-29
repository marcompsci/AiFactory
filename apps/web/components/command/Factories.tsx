"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { factories, type Json } from "@/lib/api";
import { ago, human, until, plural } from "@/lib/format";
import { Button, Dot, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

/** The Claude Code Factory and the GitHub Factory: read-only, opt-in, owner/admin only. */
export function FactoriesPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["factories"], queryFn: factories.get, refetchInterval: 8000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["factories"] });
  const link = useMutation({ mutationFn: ({ kind, on }: { kind: "claude_code" | "github" | "codex"; on: boolean }) => factories.link(kind, on), onSuccess: refresh });
  const sync = useMutation({ mutationFn: factories.sync, onSuccess: refresh });
  if (q.isLoading) return <Skeleton lines={5} />;
  if (q.error) return <ErrorNote error={q.error} />;
  const d = q.data!;
  const cc = d.claude_code;
  const gh = d.github;
  const cx = d.codex;
  return (
    <div className="space-y-6">
      <p className="text-xs text-ink-2">
        Coda and Rook visit these factories every few minutes and read, never write. Claude Code's memory (CLAUDE.md and auto memory) is
        shared with the other agents as background, so App Lab proposals follow how your projects are already built.
      </p>
      <div className="flex items-center gap-2 text-xs text-ink-3">
        {d.last_sync_mission ? <><Dot color={d.last_sync_mission.status === "COMPLETED" ? "#5BF2A5" : "#FFBD69"} /> Last check-in: {human(d.last_sync_mission.status).toLowerCase()}</> : "No check-in yet"}
        <Button className="ml-auto" onClick={() => sync.mutate()} disabled={sync.isPending}>Check in now</Button>
      </div>
      <ErrorNote error={sync.error || link.error} />

      <PlanMeters usage={d.plan_usage} onSaved={refresh} />

      <Section title="Codex Factory" aside={<Toggle on={cx.linked} onChange={(on) => link.mutate({ kind: "codex", on })} />}>
        {!cx.found_on_server ? (
          <p className="text-xs text-warn">No Codex data was found on the computer running the API (~/.codex). Run the app on the Mac where you use Codex, or set AICIV_CODEX_HOME.</p>
        ) : null}
        {!cx.linked ? <Empty>Off. Turn it on to show your recent Codex sessions and finished plan steps here and in the city, and to share AGENTS.md with the team. The plan meter works either way.</Empty> : null}
        {cx.linked && cx.data ? (
          <>
            <p className="text-xs text-ink-3">Read {ago(cx.synced_at)} · {plural(cx.data.sessions.length, "session")} · {plural(cx.data.completed_recent, "finished step")}{cx.data.by_agents ? ` · ${cx.data.by_agents} run by the agents` : ""}</p>
            <ul className="space-y-2">
              {cx.data.sessions.slice(0, 8).map((s: Json) => (
                <li key={s.id} className="rounded-lg border border-line p-2 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate">{s.title}</span>
                    {s.by_agents ? <Pill color="#5EEAD4">agents</Pill> : null}
                    {s.active ? <Pill color="#5BF2A5">active</Pill> : null}
                  </div>
                  <p className="text-xs text-ink-3">{s.project} · {s.last_activity_at ? ago(s.last_activity_at) : ""}</p>
                  {s.completed_tasks.length ? (
                    <ul className="mt-1 space-y-0.5 text-xs">
                      {s.completed_tasks.map((t: string) => <li key={t} className="text-ok">✓ <span className="text-ink-2">{t}</span></li>)}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
            {cx.data.memory.length ? (
              <Section title="Shared memory (AGENTS.md)" aside={plural(cx.data.memory.length, "file")}>
                <ul className="space-y-1 text-xs">
                  {cx.data.memory.map((m: Json) => (
                    <li key={m.label} className="rounded border border-line p-2">
                      <p className="font-mono text-[11px] text-ink">{m.label}</p>
                      <p className="text-ink-3">{m.excerpt}</p>
                    </li>
                  ))}
                </ul>
              </Section>
            ) : null}
          </>
        ) : null}
      </Section>

      <Section title="Claude Code Factory" aside={<Toggle on={cc.linked} onChange={(on) => link.mutate({ kind: "claude_code", on })} />}>
        {!cc.found_on_server ? (
          <p className="text-xs text-warn">No Claude Code data was found on the computer running the API (~/.claude). Run the app on the Mac where you use Claude Code, or set AICIV_CLAUDE_HOME.</p>
        ) : null}
        {!cc.linked ? <Empty>Off. Turn it on to show your recent Claude Code sessions and finished tasks here and in the city. Only session titles, task names and memory notes are read; secrets are scrubbed.</Empty> : null}
        {cc.linked && cc.data ? (
          <>
            <p className="text-xs text-ink-3">Read {ago(cc.synced_at)} · {plural(cc.data.sessions.length, "session")} · {plural(cc.data.completed_recent, "finished task")}</p>
            <ul className="space-y-2">
              {cc.data.sessions.slice(0, 8).map((s: Json) => (
                <li key={s.id} className="rounded-lg border border-line p-2 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate">{s.title}</span>
                    {s.active ? <Pill color="#5BF2A5">active</Pill> : null}
                  </div>
                  <p className="text-xs text-ink-3">{s.project}{s.branch ? ` · ${s.branch}` : ""} · {s.last_activity_at ? ago(s.last_activity_at) : ""}</p>
                  {s.completed_tasks.length ? (
                    <ul className="mt-1 space-y-0.5 text-xs">
                      {s.completed_tasks.map((t: string) => <li key={t} className="text-ok">✓ <span className="text-ink-2">{t}</span></li>)}
                      {s.open_tasks.slice(0, 2).map((t: string) => <li key={t} className="text-ink-3">○ {t}</li>)}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
            <Section title="Shared memory" aside={plural(cc.data.memory.length, "file")}>
              <ul className="space-y-1 text-xs">
                {cc.data.memory.map((m: Json) => (
                  <li key={m.label} className="rounded border border-line p-2">
                    <p className="font-mono text-[11px] text-ink">{m.label}</p>
                    <p className="text-ink-3">{m.excerpt}</p>
                  </li>
                ))}
              </ul>
            </Section>
          </>
        ) : null}
      </Section>

      <Section title="GitHub Factory" aside={<Toggle on={gh.linked} onChange={(on) => link.mutate({ kind: "github", on })} />}>
        {!gh.repositories.length ? <p className="text-xs text-ink-3">Connect a repository in App Lab first; the factory reads the same authorized repositories.</p> : null}
        {gh.linked && gh.data ? gh.data.repos.map((r: Json) => (
          <div key={r.repo} className="space-y-1 rounded-lg border border-line p-2 text-sm">
            <p className="font-mono text-[12px]">{r.repo}</p>
            {r.errors?.length ? <p className="text-xs text-warn">Not available: {r.errors.join(", ")}</p> : null}
            {(r.pulls ?? []).slice(0, 5).map((p: Json) => (
              <a key={p.number} href={p.url} target="_blank" rel="noreferrer" className="flex gap-2 text-xs hover:underline">
                <span className="w-14 shrink-0 text-ink-3">#{p.number}</span><span className="min-w-0 flex-1 truncate">{p.title}</span>
                <Pill color={p.state === "merged" ? "#A66BFF" : p.state === "open" ? "#5BF2A5" : "#7d8aa8"}>{p.draft ? "draft" : p.state}</Pill>
              </a>
            ))}
            {(r.runs ?? []).slice(0, 4).map((x: Json, i: number) => (
              <a key={i} href={x.url} target="_blank" rel="noreferrer" className="flex gap-2 text-xs hover:underline">
                <span className="w-14 shrink-0 text-ink-3">{x.claude ? "Claude" : "Action"}</span><span className="min-w-0 flex-1 truncate">{x.name} · {x.branch}</span>
                <Pill color={x.conclusion === "success" ? "#5BF2A5" : x.conclusion ? "#FF6178" : "#FFBD69"}>{x.conclusion ?? x.status}</Pill>
              </a>
            ))}
            {(r.commits ?? []).slice(0, 3).map((c: Json) => <p key={c.sha} className="truncate text-xs text-ink-3"><span className="font-mono">{c.sha}</span> {c.message}</p>)}
          </div>
        )) : null}
      </Section>
    </div>
  );
}

function Toggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)}
      className={`rounded-full px-2 py-0.5 text-[11px] ${on ? "bg-ok/20 text-ok" : "bg-white/5 text-ink-2"}`}>
      {on ? "Linked" : "Off"}
    </button>
  );
}

function Meter({ label, pct, sub, color }: { label: string; pct: number | null | undefined; sub: string; color: string }) {
  const v = pct == null ? null : Math.max(0, Math.min(100, pct));
  return (
    <div className="space-y-1">
      <div className="flex text-xs"><span>{label}</span><span className="ml-auto font-mono">{v == null ? "?" : `${v.toFixed(0)}%`}</span></div>
      <div className="flex h-2 gap-[2px]" aria-label={`${label} ${v == null ? "unknown" : `${v.toFixed(0)} percent`}`}>
        {Array.from({ length: 20 }, (_, i) => (
          <span key={i} className="flex-1" style={{ background: v != null && i < Math.round(v / 5) ? (v >= 90 ? "#FF6178" : v >= 70 ? "#FFBD69" : color) : "rgba(255,255,255,0.08)" }} />
        ))}
      </div>
      <p className="text-[11px] text-ink-3">{sub}</p>
    </div>
  );
}

/** The plan meters: which plan and model the agents use now, and the owner's routing settings. */
function PlanMeters({ usage, onSaved }: { usage: Json; onSaved: () => void }) {
  const live = useQuery({ queryKey: ["plan-usage"], queryFn: factories.usage, refetchInterval: 15_000 });
  const u: Json | undefined = live.data ?? usage?.data;
  const [budget, setBudget] = useState("");
  const [reserve, setReserve] = useState("");
  const save = useMutation({ mutationFn: factories.usageSettings, onSuccess: () => { setBudget(""); setReserve(""); onSaved(); live.refetch(); } });
  const s = u?.settings ?? {};
  return (
    <Section title="Plan meters" aside={usage?.plans_enabled ? <Pill color="#5EEAD4">agents on your plans</Pill> : <Pill color="#FFBD69">plans off</Pill>}>
      {!usage?.plans_enabled ? (
        <p className="text-xs text-warn">
          The agents aren't using your plans yet. Set AICIV_USE_PLANS=1 in .env and restart. The codex command is {usage?.codex_cli ? "installed" : "not installed"};
          the claude command is {usage?.claude_cli ? "installed" : "not installed"}.
        </p>
      ) : null}
      {u ? (
        <div className="space-y-3">
          <p className="text-sm">
            {u.plan ? <>Agents run on the <b>{u.plan === "codex" ? "Codex" : "Claude"}</b> plan{u.model ? <> with <b>{u.model}</b></> : null}.</> : <b className="text-warn">No plan has usage left; tasks wait.</b>}{" "}
            <span className="text-ink-3">{u.reason}</span>
          </p>
          {u.owner_active ? <p className="rounded border border-[#5EEAD4]/40 p-2 text-xs">You're using Claude ({u.owner?.reason}), so agents on the Claude plan use the smallest model.</p> : null}
          <Meter label="Codex · 5 hours" pct={u.codex?.primary?.used_percent} color="#5EEAD4"
            sub={u.codex?.available ? (u.codex?.source === "reported" ? `reported by Codex ${u.codex?.reported_at ? ago(u.codex.reported_at) : ""}${u.codex?.primary?.resets_at ? ` · resets ${until(u.codex.primary.resets_at)}` : ""}` : "no report from Codex yet") : "codex command not installed"} />
          <Meter label="Codex · week" pct={u.codex?.secondary?.used_percent} color="#5EEAD4"
            sub={`${u.codex?.secondary?.resets_at ? `resets ${until(u.codex.secondary.resets_at)} · ` : ""}agents stop using Codex at ${s.codex_stop_percent ?? 95}%`} />
          <Meter label="Claude · 5 hours (estimate)" pct={u.claude?.used_percent} color="#FF8A5C"
            sub={`${(u.claude?.tokens_5h ?? 0).toLocaleString()} tokens (you ${(u.claude?.owner_tokens_5h ?? 0).toLocaleString()}, agents ${(u.claude?.agent_tokens_5h ?? 0).toLocaleString()})${u.claude?.budget_5h ? ` of ${Number(u.claude.budget_5h).toLocaleString()}` : " · set a budget below for a percentage"} · ${s.claude_reserve_percent ?? 40}% kept for you`} />
          <form className="grid grid-cols-2 gap-2 text-xs" onSubmit={(e) => { e.preventDefault(); save.mutate({
            ...(budget ? { claude_5h_token_budget: Number(budget) } : {}), ...(reserve ? { claude_reserve_percent: Number(reserve) } : {}) }); }}>
            <label className="space-y-1"><span className="text-ink-3">Claude 5-hour budget (tokens)</span>
              <input inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value.replace(/[^0-9]/g, ""))} placeholder={s.claude_5h_token_budget ? String(s.claude_5h_token_budget) : "not set"} className="w-full rounded border border-line bg-transparent px-2 py-1" /></label>
            <label className="space-y-1"><span className="text-ink-3">Keep for you (%)</span>
              <input inputMode="numeric" value={reserve} onChange={(e) => setReserve(e.target.value.replace(/[^0-9]/g, ""))} placeholder={String(s.claude_reserve_percent ?? 40)} className="w-full rounded border border-line bg-transparent px-2 py-1" /></label>
            <Button type="submit" className="col-span-2" disabled={save.isPending || (!budget && !reserve)}>Save</Button>
          </form>
          <ErrorNote error={save.error} />
          <p className="text-[11px] text-ink-3">
            Codex figures are Codex's own reports. Claude has no public usage figure for plans, so its meter is an estimate from your Claude Code
            sessions plus the agents' calls; a "limit reached" from Claude always counts. Nyx and Coda brief every agent each check-in.
          </p>
        </div>
      ) : <Skeleton lines={3} />}
    </Section>
  );
}
