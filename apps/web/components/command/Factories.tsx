"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { factories, type Json } from "@/lib/api";
import { ago, human } from "@/lib/format";
import { Button, Dot, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

/** The Claude Code Factory and the GitHub Factory: read-only, opt-in, owner/admin only. */
export function FactoriesPanel() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["factories"], queryFn: factories.get, refetchInterval: 8000 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["factories"] });
  const link = useMutation({ mutationFn: ({ kind, on }: { kind: "claude_code" | "github"; on: boolean }) => factories.link(kind, on), onSuccess: refresh });
  const sync = useMutation({ mutationFn: factories.sync, onSuccess: refresh });
  if (q.isLoading) return <Skeleton lines={5} />;
  if (q.error) return <ErrorNote error={q.error} />;
  const d = q.data!;
  const cc = d.claude_code;
  const gh = d.github;
  return (
    <div className="space-y-6">
      <p className="text-xs text-ink-2">
        Coda and Rook visit these factories every few minutes and read, never write. Claude Code's memory (CLAUDE.md and auto memory) is
        shared with the other agents as background, so App Lab proposals follow how your projects are already built.
      </p>
      <div className="flex items-center gap-2 text-xs text-ink-3">
        {d.last_sync_mission ? <><Dot color={d.last_sync_mission.status === "COMPLETED" ? "#5BF2A5" : "#FFBD69"} /> Last check-in: {human(d.last_sync_mission.status).toLowerCase()}</> : "No check-in yet"}
        <Button className="ml-auto" onClick={() => sync.mutate()} disabled={sync.isPending || !(cc.linked || gh.linked)}>Check in now</Button>
      </div>
      <ErrorNote error={sync.error || link.error} />

      <Section title="Claude Code Factory" aside={<Toggle on={cc.linked} onChange={(on) => link.mutate({ kind: "claude_code", on })} />}>
        {!cc.found_on_server ? (
          <p className="text-xs text-warn">No Claude Code data was found on the computer running the API (~/.claude). Run the app on the Mac where you use Claude Code, or set AICIV_CLAUDE_HOME.</p>
        ) : null}
        {!cc.linked ? <Empty>Off. Turn it on to show your recent Claude Code sessions and finished tasks here and in the city. Only session titles, task names and memory notes are read; secrets are scrubbed.</Empty> : null}
        {cc.linked && cc.data ? (
          <>
            <p className="text-xs text-ink-3">Read {ago(cc.synced_at)} · {cc.data.sessions.length} session(s) · {cc.data.completed_recent} finished task(s)</p>
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
            <Section title="Shared memory" aside={`${cc.data.memory.length} file(s)`}>
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
