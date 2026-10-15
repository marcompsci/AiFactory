"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, bank, type Json } from "@/lib/api";
import { human, money, usd } from "@/lib/format";
import { useStore } from "@/lib/store";
import { ApprovalQueue } from "./Activity";
import { StepUpDialog } from "./Bank";
import { Button, Dot, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

const CHECK_COLOR: Record<string, string> = { pass: "#5BF2A5", warn: "#FFBD69", fail: "#FF6178", not_applicable: "#8FA8FF" };
const VERDICT_COPY: Record<string, string> = {
  APPROVED_FOR_OWNER_REVIEW: "Atlas recommends you approve",
  CHANGES_REQUESTED: "Atlas asked for changes",
  REJECTED: "Atlas rejected it",
  BLOCKED: "Atlas blocked it",
};

/** The owner's private desk: releases waiting at the Owner's Tower, escalations, and V3 publish approvals. */
export function OwnerDesk() {
  const status = useStore((s) => s.status);
  const q = useQuery({ queryKey: ["opportunities"], queryFn: api.opportunities, enabled: status !== "demo", refetchInterval: 8000 });
  const rows: Json[] = q.data?.opportunities ?? [];
  const waiting = rows.filter((o) => o.status === "OWNER_APPROVAL");
  const escalated = rows.filter((o) => o.status === "MANAGER_REVIEW");
  const authorized = rows.filter((o) => o.status === "RELEASE_AUTHORIZED");
  return (
    <div className="space-y-6">
      <FinancialDecisions />
      <Section title="Owner's Tower" aside="nothing ships without your yes">
        {status === "demo" ? <Empty>Releases appear here once a server is connected.</Empty> : null}
        {q.isLoading ? <Skeleton lines={3} /> : null}
        {status !== "demo" && !q.isLoading && !waiting.length ? (
          <Empty>No release is waiting for you. When Atlas approves a product, its release package travels here on the conveyor.</Empty>
        ) : null}
        {waiting.map((o) => <ReleaseReview key={o.id} id={o.id} />)}
      </Section>
      {escalated.map((o) => <Escalation key={o.id} id={o.id} />)}
      {authorized.length ? (
        <Section title="Approved by you">
          <ul className="space-y-1 text-sm">{authorized.map((o) => <li key={o.id}><Dot color="#F4D58D" /> <span className="ml-1">{o.title}</span></li>)}</ul>
        </Section>
      ) : null}
      <Section title="Publish approvals" aside="code changes from missions">
        <ApprovalQueue />
      </Section>
    </div>
  );
}

function Escalation({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["opportunity", id], queryFn: () => api.opportunity(id) });
  const qc = useQueryClient();
  const m = useMutation({ mutationFn: (approve: boolean) => api.ownerCommit(id, approve), onSettled: () => qc.invalidateQueries({ queryKey: ["opportunities"] }) });
  const esc = (q.data?.decisions ?? []).find((d: Json) => d.outcome === "escalate");
  if (!esc) return null;
  return (
    <div className="rounded-xl border border-warn/50 bg-warn/10 p-3 text-sm">
      <p className="font-semibold text-warn">Atlas needs your call on a commitment</p>
      <p className="mt-1">{q.data?.opportunity.title}</p>
      <p className="text-xs text-ink-2">{esc.rationale}</p>
      <div className="mt-2 flex gap-2">
        <Button variant="approve" onClick={() => m.mutate(true)} disabled={m.isPending}>Commit the spend</Button>
        <Button variant="danger" onClick={() => m.mutate(false)} disabled={m.isPending}>Decline</Button>
      </div>
      <ErrorNote error={m.error} />
    </div>
  );
}

function Preview({ artifactId }: { artifactId: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.bundleFile(artifactId, "index.html").then(setHtml).catch((e) => setErr(String(e.message ?? e)));
  }, [artifactId]);
  if (err) return <ErrorNote error={err} />;
  if (!html) return <Skeleton lines={2} />;
  // srcDoc + sandbox without allow-same-origin: the prototype runs, but can't touch this app or its credentials
  return <iframe title="Prototype preview" srcDoc={html} sandbox="allow-scripts" className="h-80 w-full rounded-lg border border-line bg-white" />;
}

function ReleaseReview({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["opportunity", id], queryFn: () => api.opportunity(id) });
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (decision: string) => api.ownerDecision(id, decision, q.data!.bundle.digest, note || undefined),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["opportunity", id] });
      qc.invalidateQueries({ queryKey: ["opportunities"] });
    },
  });
  const download = async () => {
    const blob = await api.bundleDownload(q.data!.bundle.artifact_id);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `bundle-${q.data!.bundle.digest.slice(0, 12)}.zip`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error) return <ErrorNote error={q.error} />;
  const d = q.data!;
  const o = d.opportunity;
  const r = d.manager_review;
  if (!d.awaiting_owner) {
    return <Empty>The release package for “{o.title}” is still on its way to the tower.</Empty>;
  }
  const fixture = o.data_mode === "fixture";
  return (
    <article className="space-y-4 rounded-2xl border border-[#F4D58D]/40 p-3" aria-label={`Release review: ${o.title}`}>
      <header className="space-y-1">
        <h3 className="font-display text-base text-[#F4D58D]">{o.spec?.app_name ?? o.title}</h3>
        <p className="text-sm text-ink-2">{o.spec?.tagline ?? o.description}</p>
        <div className="flex flex-wrap gap-1.5">
          <Pill color={r?.verdict === "APPROVED_FOR_OWNER_REVIEW" ? "#5BF2A5" : "#FFBD69"}>{VERDICT_COPY[r?.verdict] ?? "No review"}</Pill>
          {fixture ? <Pill color="#FFBD69">Built on fixture research, not live market data</Pill> : null}
        </div>
      </header>

      <Section title="Manager recommendation" aside={r?.method === "model" ? r.model : "rules"}>
        <p className="text-sm text-ink-2">{r?.summary}</p>
      </Section>

      <Section title="Preview">
        <Preview artifactId={d.bundle.artifact_id} />
      </Section>

      <Section title="Build" aside="you approve these exact bytes">
        <p className="break-all font-mono text-[11px] text-ink-2">sha256 {d.bundle.digest}</p>
        <Button onClick={download}>Download bundle</Button>
      </Section>

      <Section title="Test results">
        <p className="text-sm">
          <span className={d.test_report?.failed === 0 ? "text-ok" : "text-bad"}>{d.test_report?.summary_line}</span>
          <span className="text-ink-3"> on bundle {String(d.test_report?.bundle_digest).slice(0, 12)}</span>
          {d.test_report?.bundle_digest === d.bundle.digest ? <span className="text-ok"> (the same bundle)</span> : <span className="text-bad"> (a different bundle)</span>}
        </p>
      </Section>

      <Section title="Release checklist" aside="12 categories">
        <ul className="space-y-1.5">
          {d.checklist.map((c: Json) => (
            <li key={c.category} className="text-sm">
              <span className="inline-flex items-center gap-1.5"><Dot color={CHECK_COLOR[c.status]} /> {human(c.category)}</span>
              <span className="ml-1 text-xs" style={{ color: CHECK_COLOR[c.status] }}>{c.status === "warn" ? "note" : c.status}</span>
              <p className="text-xs text-ink-3">{c.evidence}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Market research" aside={`score ${Number(o.opportunity_score).toFixed(2)}, ${o.confidence} confidence`}>
        <ul className="space-y-1.5">
          {d.findings.map((f: Json) => (
            <li key={f.id} className="text-xs">
              <p className="text-sm text-ink">{f.title}</p>
              <p className="text-ink-2">{f.summary}</p>
              <p className="text-ink-3">
                {human(f.measurement_type)} · {f.data_coverage} · {f.geographic_scope} · collected {String(f.collected_at).slice(0, 10)} ·{" "}
                <span className={f.data_mode === "fixture" ? "text-warn" : ""}>{f.data_mode}</span>
              </p>
              <p className="break-all font-mono text-[10px] text-ink-3">{f.source_url}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Costs and risks">
        <p className="text-sm text-ink-2">Planned {usd(o.estimated_cost_usd)}; spent so far {usd(d.estimated_spend_usd)} (estimates).</p>
        <ul className="list-disc space-y-0.5 pl-5 text-xs text-ink-2">
          {d.risks.map((x: string, i: number) => <li key={i}>{x}</li>)}
        </ul>
      </Section>

      <div className="space-y-2">
        <label htmlFor={`note-${id}`} className="text-sm">Note (optional)</label>
        <textarea id={`note-${id}`} value={note} onChange={(e) => setNote(e.target.value)} rows={2} className="w-full rounded-lg border border-line bg-ground/60 p-2 text-sm" />
        <div className="flex flex-wrap gap-2">
          <Button variant="approve" onClick={() => decide.mutate("APPROVE")} disabled={decide.isPending}>Approve this release</Button>
          <Button onClick={() => decide.mutate("REQUEST_CHANGES")} disabled={decide.isPending}>Request changes</Button>
          <Button onClick={() => decide.mutate("DEFER")} disabled={decide.isPending}>Decide later</Button>
          <Button variant="danger" onClick={() => decide.mutate("REJECT")} disabled={decide.isPending}>Reject</Button>
        </div>
        <p className="text-xs text-ink-3">Your decision is recorded permanently against this exact bundle. If the bundle changes, approval is cancelled and it comes back to you.</p>
        <ErrorNote error={decide.error} />
      </div>
    </article>
  );
}

/** V5: financial decisions at the Owner's Tower. Exact terms, an expiry, and step-up before any approval. */
export function FinancialDecisions() {
  const status = useStore((s) => s.status);
  const packets = useQuery({ queryKey: ["bank", "packets"], queryFn: bank.packets, enabled: status !== "demo", refetchInterval: 5000, retry: false });
  const bills = useQuery({ queryKey: ["bank", "approvals", "REQUESTED"], queryFn: () => bank.approvals("REQUESTED"), enabled: status !== "demo",
    refetchInterval: 8000, retry: false });
  if (status === "demo" || packets.error) return null;
  const waiting = (packets.data?.packets ?? []).filter((p: Json) => p.status === "OWNER_DECISION");
  const deferred = (packets.data?.packets ?? []).filter((p: Json) => p.status === "DEFERRED");
  const payments = (bills.data?.approvals ?? []).filter((a: Json) => !a.packet_id);
  return (
    <Section title="Financial decisions" aside="no money moves without your yes">
      {!waiting.length && !payments.length ? <Empty>Nothing financial is waiting. Cost reviews and bill payments arrive here from the AI Central Bank.</Empty> : null}
      {waiting.map((p: Json) => <CostDecision key={p.id} id={p.id} />)}
      {payments.map((a: Json) => <PaymentDecision key={a.id} a={a} />)}
      {deferred.length ? (
        <p className="text-xs text-ink-3">{deferred.length} deferred cost review(s); reopen them from the Bank tab or wait for their deferral to end.</p>
      ) : null}
    </Section>
  );
}

function Terms({ a }: { a: Json }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
      <dt className="text-ink-3">Action</dt><dd>{human(a.action_type)}</dd>
      <dt className="text-ink-3">Amount</dt><dd className="font-semibold tabular-nums">{money(a.amount_minor, a.currency)}{a.details?.interval && a.details.interval !== "one_time" ? ` per ${a.details.interval}` : ""}</dd>
      <dt className="text-ink-3">To</dt><dd>{a.recipient}{a.details?.item ? ` (${a.details.item})` : ""}</dd>
      <dt className="text-ink-3">From</dt><dd>{a.details?.account_label ?? a.account_ref}</dd>
      <dt className="text-ink-3">Expires</dt><dd>{new Date(a.expires_at).toLocaleString()}</dd>
      <dt className="text-ink-3">Fingerprint</dt><dd className="font-mono">{a.payload_hash.slice(0, 16)}</dd>
      {a.data_mode === "simulated" ? <><dt className="text-ink-3">Data</dt><dd className="text-warn">simulated: approving records a simulated purchase, no real money</dd></> : null}
    </dl>
  );
}

function CostDecision({ id }: { id: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["bank", "packet", id], queryFn: () => bank.packet(id), refetchInterval: 5000 });
  const [approving, setApproving] = useState<Json | null>(null);
  const [note, setNote] = useState("");
  const m = useMutation({
    mutationFn: (body: { decision: string; approval_id?: string; payload_hash?: string; note?: string; defer_days?: number; tok?: string }) =>
      bank.decide(id, body, body.tok),
    onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }),
  });
  if (!q.data) return <Skeleton lines={3} />;
  const { packet: p, approvals } = q.data;
  const open = approvals.filter((a: Json) => a.status === "REQUESTED");
  return (
    <div className="space-y-2 rounded-xl border border-gold/40 bg-white/[.03] p-3 text-sm" data-testid="cost-decision">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{p.origin === "purchase_request" ? "Paid tool request" : "Fee review"}: {p.vendor} {p.item}</p>
          <p className="text-xs text-ink-2">{p.recommendation?.summary}</p>
        </div>
        {p.data_mode === "simulated" ? <Pill color="#FFBD69">simulated</Pill> : null}
      </div>
      {p.gm_decision?.outcome ? <p className="text-xs text-ink-3">General Manager: {human(p.gm_decision.outcome)} ({p.gm_decision.method}).</p> : null}
      {open.map((a: Json) => (
        <div key={a.id} className="space-y-1.5 rounded-lg bg-white/[.04] p-2">
          <p className="text-xs font-semibold">{a.details?.option === "recommended" ? "Recommended option" : "As requested"}</p>
          <Terms a={a} />
          <Button variant="approve" onClick={() => setApproving(a)}>Approve exactly this</Button>
        </div>
      ))}
      {!open.length ? <p className="text-xs text-ink-2">No purchase to approve: this is a recommendation. Any change (switching providers, asking for a fee waiver) is yours to make.</p> : null}
      <input aria-label="Note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" className="w-full rounded-lg border border-line bg-ground/60 px-3 py-1.5 text-xs" />
      <div className="flex flex-wrap gap-2">
        {open.length ? <Button variant="danger" onClick={() => m.mutate({ decision: "REJECT", note })}>Reject</Button> : <Button onClick={() => m.mutate({ decision: "ACKNOWLEDGE", note })}>Acknowledge</Button>}
        <Button onClick={() => m.mutate({ decision: "DEFER", defer_days: 14, note })}>Defer 2 weeks</Button>
        {p.research_rounds < 3 ? <Button onClick={() => m.mutate({ decision: "MORE_RESEARCH", note })}>More research</Button> : null}
      </div>
      <ErrorNote error={m.error} />
      {approving ? (
        <StepUpDialog purpose={approving.id} action={`Approving ${money(approving.amount_minor, approving.currency)} to ${approving.recipient}`}
          onCancel={() => setApproving(null)}
          onVerified={async (tok) => {
            await m.mutateAsync({ decision: "APPROVE", approval_id: approving.id, payload_hash: approving.payload_hash, note, tok });
            setApproving(null);
          }} />
      ) : null}
    </div>
  );
}

function PaymentDecision({ a }: { a: Json }) {
  const qc = useQueryClient();
  const [approving, setApproving] = useState(false);
  const m = useMutation({
    mutationFn: ({ decision, tok }: { decision: string; tok?: string }) => bank.decideApproval(a.id, { decision, payload_hash: a.payload_hash }, tok),
    onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }),
  });
  return (
    <div className="space-y-2 rounded-xl border border-warn/40 bg-white/[.03] p-3 text-sm">
      <p className="font-semibold">Bill payment proposed{a.details?.due_at ? `, due ${new Date(a.details.due_at).toLocaleDateString()}` : ""}</p>
      <Terms a={a} />
      <div className="flex gap-2">
        <Button variant="approve" onClick={() => setApproving(true)}>Approve payment</Button>
        <Button onClick={() => m.mutate({ decision: "DEFER" })}>I'll pay it myself</Button>
      </div>
      <ErrorNote error={m.error} />
      {approving ? <StepUpDialog purpose={a.id} action={`Paying ${money(a.amount_minor, a.currency)} to ${a.recipient}`} onCancel={() => setApproving(false)}
        onVerified={async (tok) => { await m.mutateAsync({ decision: "APPROVE", tok }); setApproving(false); }} /> : null}
    </div>
  );
}
