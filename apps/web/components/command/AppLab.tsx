"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { lab, type Json } from "@/lib/api";
import { githubSigninToken } from "@/lib/auth";
import { ago, human } from "@/lib/format";
import { StepUpDialog } from "./Bank";
import { Button, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

const STAGE = ["RESEARCHING", "ANALYZING", "MANAGER_REVIEW", "AWAITING_OWNER", "DONE"];
const COLOR: Record<string, string> = {
  RESEARCHING: "#8FA8FF", ANALYZING: "#5BF2A5", MANAGER_REVIEW: "#EAF2FF", AWAITING_OWNER: "#FFD36B", DONE: "#5BF2A5",
  FAILED: "#FF6B7A", CANCELLED: "#7d8aa8", APPROVED: "#5BF2A5", PUBLISHING: "#5BF2A5", PUBLISHED: "#3DFFB8", REJECTED: "#FF6B7A",
  DEFERRED: "#FFBD69", WITHDRAWN: "#7d8aa8", PROPOSED: "#8FA8FF", ACTIVE: "#5BF2A5", REVOKED: "#FF6B7A",
};

/** App Lab: the Research Division finds designs people engage with, pay for and play; Code Forge turns them into
 * proposals for your repository; the General Manager briefs you; nothing reaches GitHub until you approve it. */
export function AppLabPanel() {
  const q = useQuery({ queryKey: ["lab"], queryFn: lab.overview, refetchInterval: 4000 });
  if (q.isLoading) return <Skeleton lines={5} />;
  if (q.error) return <ErrorNote error={q.error} />;
  const d = q.data!;
  const waiting = d.proposals.filter((p: Json) => p.status === "AWAITING_OWNER");
  return (
    <div className="space-y-5">
      <p className="text-xs text-ink-2">
        Agents research what people engage with, buy and play, then propose improvements to your code. The General Manager briefs you
        first. Approved changes go to a separate branch as a draft pull request, or to Claude Code as an issue. Never to your default branch.
      </p>
      <Repositories repos={d.repositories} ambient={d.ambient_allowed} />
      {waiting.length ? (
        <Section title="Waiting for you" aside={`${waiting.length} proposal(s)`}>
          {waiting.map((p: Json) => <ProposalCard key={p.id} id={p.id} />)}
        </Section>
      ) : null}
      <Section title="Cycles">
        {d.cycles.length === 0 ? <Empty>No cycles yet. Connect a repository and start one.</Empty> : null}
        {d.cycles.map((c: Json) => <CycleRow key={c.id} c={c} proposals={d.proposals.filter((p: Json) => p.cycle_id === c.id)} />)}
      </Section>
    </div>
  );
}

function Repositories({ repos, ambient }: { repos: Json[]; ambient: boolean }) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(repos.length === 0);
  const refresh = () => qc.invalidateQueries({ queryKey: ["lab"] });
  const start = useMutation({ mutationFn: lab.startCycle, onSuccess: refresh });
  const autopilot = useMutation({ mutationFn: ({ id, on }: { id: string; on: boolean }) => lab.autopilot(id, on), onSuccess: refresh });
  const revoke = useMutation({ mutationFn: lab.revoke, onSuccess: refresh });
  return (
    <Section title="Repositories" aside={<button type="button" className="text-cyan" onClick={() => setAdding(!adding)}>{adding ? "Close" : "Connect"}</button>}>
      {adding ? <ConnectForm ambient={ambient} onDone={() => { setAdding(false); refresh(); }} /> : null}
      {repos.map((r) => (
        <div key={r.id} className="space-y-2 rounded-xl border border-line p-3 text-sm" data-testid="lab-repo">
          <div className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{r.full_name}</span>
            <Pill color={COLOR[r.status] ?? "#8FA8FF"}>{human(r.status)}</Pill>
          </div>
          <p className="text-xs text-ink-3">
            Base branch <span className="font-mono">{r.default_branch}</span> · {r.auth_mode === "github_signin" ? "GitHub sign-in" : r.auth_mode}
            {r.claude_code_ready ? " · Claude Code installed" : " · Claude Code not installed yet"}
            {r.last_scan_at ? ` · scanned ${ago(r.last_scan_at)}` : ""}
          </p>
          {r.last_error ? <p className="text-xs text-bad">{r.last_error}</p> : null}
          {r.status === "ACTIVE" ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => start.mutate(r.id)} disabled={start.isPending}>Start a cycle</Button>
              <Button onClick={() => autopilot.mutate({ id: r.id, on: !r.autopilot })} title="Research and proposals on a schedule. Publishing still waits for you.">
                Autopilot: {r.autopilot ? "on" : "off"}
              </Button>
              <Button variant="danger" onClick={() => revoke.mutate(r.id)}>Revoke access</Button>
            </div>
          ) : null}
        </div>
      ))}
      <ErrorNote error={start.error || autopilot.error || revoke.error} />
    </Section>
  );
}

function ConnectForm({ ambient, onDone }: { ambient: boolean; onDone: () => void }) {
  const [full, setFull] = useState("");
  const [mode, setMode] = useState<"token" | "github_signin" | "ambient">(githubSigninToken() ? "github_signin" : "token");
  const [token, setToken] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const submit = async (stepUp: string) => {
    setErr(null);
    try {
      const tok = mode === "token" ? token.trim() : mode === "github_signin" ? githubSigninToken() ?? "" : undefined;
      if (mode === "github_signin" && !tok) throw new Error("Sign in with GitHub (with repository access) in Settings first.");
      await lab.connect({ full_name: full.trim(), auth_mode: mode, token: tok }, stepUp);
      setToken("");
      setVerifying(false);
      onDone();
    } catch (e) {
      setErr(e);
      setVerifying(false);
    }
  };
  return (
    <form className="space-y-2 rounded-xl border border-cyan/40 p-3 text-sm" onSubmit={(e) => { e.preventDefault(); setVerifying(true); }}>
      <label className="block text-xs text-ink-2">
        Repository (owner/name)
        <input value={full} onChange={(e) => setFull(e.target.value)} placeholder="you/your-app" required pattern="[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+"
          className="mt-1 w-full rounded-lg border border-line bg-ground/60 px-3 py-2 font-mono" />
      </label>
      <fieldset className="flex flex-wrap gap-3 text-xs">
        <label><input type="radio" checked={mode === "token"} onChange={() => setMode("token")} /> Fine-grained token</label>
        <label><input type="radio" checked={mode === "github_signin"} onChange={() => setMode("github_signin")} /> My GitHub sign-in</label>
        {ambient ? <label><input type="radio" checked={mode === "ambient"} onChange={() => setMode("ambient")} /> Server credentials</label> : null}
      </fieldset>
      {mode === "token" ? (
        <label className="block text-xs text-ink-2">
          Token: one repository only, with Contents, Pull requests and Issues set to read and write. It's checked with GitHub, encrypted and never shown again.
          <input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} required minLength={20}
            className="mt-1 w-full rounded-lg border border-line bg-ground/60 px-3 py-2 font-mono" />
        </label>
      ) : null}
      {mode === "github_signin" ? <p className="text-xs text-ink-3">Uses the token from your GitHub sign-in. That token can reach every repository you can, so a fine-grained token scoped to one repository is the safer choice.</p> : null}
      {verifying ? (
        <StepUpDialog purpose="lab-connect" action={`Giving the App Lab access to ${full}`} onCancel={() => setVerifying(false)} onVerified={submit} />
      ) : (
        <Button type="submit" variant="primary">Authorize this repository</Button>
      )}
      <ErrorNote error={err} />
    </form>
  );
}

function CycleRow({ c, proposals }: { c: Json; proposals: Json[] }) {
  const qc = useQueryClient();
  const cancel = useMutation({ mutationFn: lab.cancelCycle, onSuccess: () => qc.invalidateQueries({ queryKey: ["lab"] }) });
  const idx = STAGE.indexOf(c.status);
  return (
    <div className="space-y-2 rounded-xl border border-line p-3 text-sm" data-testid="lab-cycle">
      <div className="flex items-center gap-2">
        <span className="flex-1 text-xs text-ink-3">{c.trigger === "autopilot" ? "Autopilot" : "You"} started {ago(c.created_at)}{c.data_mode === "simulated" ? " · simulation" : ""}</span>
        <Pill color={COLOR[c.status] ?? "#8FA8FF"}>{human(c.status)}</Pill>
      </div>
      <ol className="flex gap-1" aria-label="Cycle progress">
        {STAGE.map((s, i) => (
          <li key={s} title={human(s)} className="h-1.5 flex-1 rounded-full" style={{ background: idx >= i || c.status === "DONE" ? COLOR[s] : "#22304f" }} />
        ))}
      </ol>
      <p className="text-[11px] text-ink-3">Research Observatory → Code Forge → Nexus Spire → Owner's Tower</p>
      {c.reason ? <p className="text-xs text-ink-2">{c.reason}</p> : null}
      {proposals.filter((p) => p.status !== "AWAITING_OWNER").map((p) => (
        <div key={p.id} className="flex items-center gap-2 text-xs">
          <span className="min-w-0 flex-1 truncate">{p.title}</span>
          {p.published?.url ? <a className="text-cyan underline" href={p.published.url} target="_blank" rel="noreferrer">{p.published.kind === "pr" ? `PR #${p.published.number}` : `Issue #${p.published.number}`}</a> : null}
          <Pill color={COLOR[p.status] ?? "#8FA8FF"}>{human(p.status)}</Pill>
        </div>
      ))}
      {["RESEARCHING", "ANALYZING", "MANAGER_REVIEW", "AWAITING_OWNER"].includes(c.status) ? (
        <Button onClick={() => cancel.mutate(c.id)} disabled={cancel.isPending}>Cancel cycle</Button>
      ) : null}
    </div>
  );
}

export function ProposalCard({ id }: { id: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["lab", "proposal", id], queryFn: () => lab.proposal(id) });
  const [approving, setApproving] = useState(false);
  const [showPatch, setShowPatch] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  if (q.isLoading) return <Skeleton lines={3} />;
  if (q.error) return <ErrorNote error={q.error} />;
  const p = q.data!.proposal;
  const gm = p.gm_review ?? {};
  const decide = async (decision: "APPROVE" | "REJECT" | "DEFER", stepUp?: string) => {
    setErr(null);
    try {
      await lab.decide(id, { decision, payload_hash: p.payload_hash }, stepUp);
      setApproving(false);
      qc.invalidateQueries({ queryKey: ["lab"] });
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <article className="space-y-2 rounded-xl border border-gold/50 bg-gold/5 p-3 text-sm" data-testid="lab-proposal">
      <header className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h4 className="font-semibold">{p.title}</h4>
          <p className="text-xs text-ink-3">
            {q.data!.repository.full_name} · {p.route === "patch" ? `patch, ${p.files.length} file(s)` : "task for Claude Code"} · risk {p.risk}
            {p.authored_by ? ` · ${p.authored_by}` : ""}
          </p>
        </div>
        <Pill color={COLOR[p.status] ?? "#8FA8FF"}>{human(p.status)}</Pill>
      </header>
      <p>{p.summary}</p>
      {p.plan?.length ? <ol className="list-decimal space-y-0.5 pl-5 text-xs text-ink-2">{p.plan.map((s: string, i: number) => <li key={i}>{s}</li>)}</ol> : null}
      {gm.briefing ? (
        <div className="rounded-lg border border-line bg-white/5 p-2 text-xs">
          <p className="font-semibold">General Manager</p>
          <p className="text-ink-2">{gm.briefing}</p>
          {gm.notes?.map((n: string) => <p key={n} className="mt-1 text-warn">{n}</p>)}
        </div>
      ) : null}
      {q.data!.insights.length ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-ink-2">Why: research evidence</summary>
          {q.data!.insights.map((i: Json) => (
            <div key={i.id} className="mt-1">
              <p>{i.why_it_works}</p>
              <p className="text-ink-3">Engagement {i.signals.engagement} · purchase {i.signals.purchase} · play {i.signals.play} · {i.data_mode}</p>
              {i.evidence.map((e: Json, k: number) => <p key={k} className="break-all text-ink-3">{e.source_url}</p>)}
            </div>
          ))}
        </details>
      ) : null}
      {p.route === "patch" ? (
        <div className="text-xs">
          <button type="button" className="text-cyan" onClick={() => setShowPatch(!showPatch)}>{showPatch ? "Hide" : "Show"} the exact change</button>
          {p.checks?.applies ? <span className="ml-2 text-ok">applies cleanly</span> : null}
          {showPatch ? <pre className="scroll-thin mt-1 max-h-64 overflow-auto rounded-lg bg-black/40 p-2 font-mono text-[11px]">{p.patch}</pre> : null}
        </div>
      ) : (
        <details className="text-xs">
          <summary className="cursor-pointer text-ink-2">What Claude Code will be asked to do</summary>
          <pre className="scroll-thin mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-black/40 p-2 font-mono text-[11px]">{p.instructions}</pre>
        </details>
      )}
      {["AWAITING_OWNER", "DEFERRED"].includes(p.status) ? (
        approving ? (
          <StepUpDialog purpose={`lab:${id}`} action={`Publishing "${p.title}" to ${q.data!.repository.full_name}`} onCancel={() => setApproving(false)}
            onVerified={(t) => decide("APPROVE", t)} />
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button variant="approve" onClick={() => setApproving(true)}>Approve and publish</Button>
            <Button onClick={() => decide("DEFER")}>Later</Button>
            <Button variant="danger" onClick={() => decide("REJECT")}>Reject</Button>
          </div>
        )
      ) : null}
      {p.published?.url ? <a className="text-xs text-cyan underline" href={p.published.url} target="_blank" rel="noreferrer">{p.published.url}</a> : null}
      <ErrorNote error={err} />
    </article>
  );
}
