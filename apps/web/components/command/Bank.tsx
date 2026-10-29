"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, bank, type Json } from "@/lib/api";
import { ago, human, money, PACKAGE_COLORS, plural } from "@/lib/format";
import { useStore } from "@/lib/store";
import { InvestigationCard } from "./Investigation";
import { Button, Dot, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

export const PACKET_STAGES = ["SUBMITTED", "AT_BANK", "RESEARCH_REQUESTED", "RESEARCHING", "FINDINGS_RETURNED", "GM_REVIEW", "OWNER_DECISION", "APPROVED", "EXECUTED"];
export const PACKET_COLOR: Record<string, string> = {
  SUBMITTED: "#8FA8FF", AT_BANK: "#F4D58D", RESEARCH_REQUESTED: "#5BF2A5", RESEARCHING: "#5BF2A5", FINDINGS_RETURNED: "#7CFFCB",
  GM_REVIEW: "#EAF2FF", OWNER_DECISION: "#FFD86B", APPROVED: "#5BF2A5", EXECUTED: "#5BF2A5", REJECTED: "#FF6178", DEFERRED: "#8FA8FF",
  CLOSED: "#8FA8FF",
};

/** AI Central Bank: owners and admins only. Every figure is labeled; simulated data is flagged everywhere. */
export function BankPanel() {
  const status = useStore((s) => s.status);
  const q = useQuery({ queryKey: ["bank", "dashboard"], queryFn: bank.dashboard, enabled: status !== "demo", refetchInterval: 8000, retry: false });
  if (status === "demo") return <Empty>The AI Central Bank needs a server. Connect one in System.</Empty>;
  if (q.error instanceof ApiError && q.error.status === 403) {
    return <Empty>Financial data is limited to owners and admins.</Empty>;
  }
  const d = q.data;
  return (
    <div className="space-y-6">
      {q.isLoading ? <Skeleton lines={4} /> : null}
      <ErrorNote error={q.error} />
      {d ? (
        <>
          {d.simulated ? (
            <p className="rounded-lg border border-warn/50 bg-warn/10 px-3 py-2 text-xs text-warn" role="status">
              SIMULATED DATA. These figures describe a labeled test ledger, not your business. Connect a real read-only source below to replace it.
            </p>
          ) : null}
          {!d.has_data ? <NoData /> : <Overview d={d} />}
          <Reviews />
          <ToolRequest />
          {d.has_data ? <BillsAndSubs d={d} /> : null}
          {d.has_data ? <Savings d={d} /> : null}
          <Tax />
          <Connections d={d} />
          <AuditStatus />
        </>
      ) : null}
    </div>
  );
}

function NoData() {
  const qc = useQueryClient();
  const m = useMutation({ mutationFn: bank.loadSimulated, onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }) });
  return (
    <Section title="No financial data yet">
      <p className="text-sm text-ink-2">
        Nothing is connected, so there is nothing to show. The bank shows missing data as missing, never as zero. Connect a read-only source
        below, or load a clearly labeled simulated ledger to try the workflow.
      </p>
      <Button variant="primary" onClick={() => m.mutate()} disabled={m.isPending}>{m.isPending ? "Loading" : "Load simulated ledger"}</Button>
      <ErrorNote error={m.error} />
    </Section>
  );
}

function Figure({ label, value, hint, tone = "#EAF2FF", estimate = false }: { label: string; value: string; hint: string; tone?: string; estimate?: boolean }) {
  return (
    <div className="rounded-lg bg-white/[.03] px-3 py-2" title={hint}>
      <div className="flex items-center justify-between gap-2 text-[11px] uppercase tracking-wide text-ink-3">
        <span>{label}</span>
        {estimate ? <span className="rounded bg-white/10 px-1 text-[10px] text-ink-2">estimate</span> : null}
      </div>
      <div className="mt-0.5 font-semibold tabular-nums" style={{ color: tone }}>{value}</div>
      <div className="mt-0.5 text-[11px] leading-snug text-ink-3">{hint}</div>
    </div>
  );
}

function Overview({ d }: { d: Json }) {
  const m = d.last_30_days;
  const tax = d.tax;
  const fc = d.forecast;
  const stale = (d.freshness ?? []).filter((f: Json) => f.stale);
  return (
    <Section title="Executive dashboard" aside={`last 30 days · updated ${ago(d.generated_at)}`}>
      <div className="grid grid-cols-2 gap-2">
        <Figure label="Available cash" value={money(d.available_cash_minor)} hint={d.labels.available_balance} tone="#5BF2A5" />
        <Figure label="Net cash flow" value={money(m.net_cash_flow_minor)} hint={d.labels.cash_flow} tone={m.net_cash_flow_minor >= 0 ? "#5BF2A5" : "#FF6178"} />
        <Figure label="Revenue (gross)" value={money(m.revenue_gross_minor)} hint={d.labels.revenue} />
        <Figure label="Net profit" value={money(m.net_profit_estimate_minor)} hint={d.labels.profit} estimate />
        <Figure label="Gross profit" value={money(m.gross_profit_estimate_minor)} hint="Revenue after refunds and payment/store fees." estimate />
        <Figure label="Operating expenses" value={money(m.operating_expenses_minor)} hint="Categorized business spending (no transfers or tax payments)." />
        <Figure label="Fees" value={money(m.fees_minor)} hint="Payment processing, store commission and bank fees." tone="#FFBD69" />
        <Figure label="Refunds" value={money(m.refunds_minor)} hint="Money returned to customers." />
        <Figure label="AI operating costs" value={money(d.ai_operating_costs.ledger_last_30_minor)}
          hint={`${d.ai_operating_costs.label} Agents' own estimate: $${d.ai_operating_costs.agents_estimated_usd_last_30.toFixed(2)}.`} />
        <Figure label="Tax reserve" value={tax ? money(tax.reserve_minor) : "No estimate yet"} hint={d.labels.tax} estimate tone="#B794FF" />
      </div>
      {fc ? (
        <div className="rounded-lg bg-white/[.03] px-3 py-2 text-xs">
          <p className="font-semibold text-ink">Cash forecast <span className="ml-1 rounded bg-white/10 px-1 text-[10px] font-normal text-ink-2">estimate</span></p>
          <ul className="mt-1 grid grid-cols-3 gap-2 tabular-nums">
            {fc.points.map((pt: Json) => (
              <li key={pt.days}><span className="text-ink-3">{pt.days} days</span><br />{money(pt.expected_minor)}<br />
                <span className="text-ink-3">{money(pt.low_minor)} to {money(pt.high_minor)}</span></li>
            ))}
          </ul>
          <p className="mt-1 text-ink-3">{fc.label}. {fc.method}.</p>
        </div>
      ) : <Empty>Not enough history for a forecast yet (needs two full months).</Empty>}
      <div className="flex flex-wrap gap-1.5 text-xs">
        <Pill color="#5BF2A5">{d.reconciliation.matched} reconciled</Pill>
        <Pill color="#FFBD69">{d.reconciliation.unreconciled} unreconciled</Pill>
        {d.reconciliation.needs_review ? <Pill color="#FF6178">{d.reconciliation.needs_review} need review</Pill> : null}
        {stale.length ? <Pill color="#FF6178">{plural(stale.length, "source")} stale</Pill> : <Pill color="#5BF2A5">sources fresh</Pill>}
        {(d.coverage.gaps ?? []).map((g: string) => <Pill key={g} color="#8FA8FF">not connected: {human(g).toLowerCase()}</Pill>)}
      </div>
      <ul className="space-y-1 text-xs">
        {d.accounts.map((a: Json) => (
          <li key={a.id} className="flex justify-between gap-2">
            <span>{a.name} ••{a.mask} <span className="text-ink-3">{human(a.type).toLowerCase()}</span></span>
            <span className="tabular-nums" title={`current ${money(a.current_balance_minor)} · as of ${a.as_of ? ago(a.as_of) : "unknown"}`}>
              {a.type === "credit_card"
                ? (a.current_balance_minor ?? 0) < 0 ? `${money(-(a.current_balance_minor ?? 0))} owed` : `${money(a.current_balance_minor)} credit`
                : `${money(a.available_balance_minor)} available`}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function StageBar({ status }: { status: string }) {
  const i = PACKET_STAGES.indexOf(status);
  return (
    <div className="flex gap-0.5" aria-label={`Stage ${human(status)}`}>
      {PACKET_STAGES.map((s, k) => (
        <span key={s} title={human(s)} className="h-1 flex-1 rounded-full" style={{ background: k <= i ? PACKET_COLOR[status] ?? "#F4D58D" : "rgb(234 242 255 / .1)" }} />
      ))}
    </div>
  );
}

function Reviews() {
  const q = useQuery({ queryKey: ["bank", "packets"], queryFn: bank.packets, refetchInterval: 5000 });
  const [open, setOpen] = useState<string | null>(null);
  const rows: Json[] = q.data?.packets ?? [];
  return (
    <Section title="Cost reviews" aside="fees found and purchases requested">
      {q.isLoading ? <Skeleton lines={2} /> : null}
      {!q.isLoading && !rows.length ? <Empty>No cost reviews yet. Requests for paid tools and detected fees appear here.</Empty> : null}
      <ul className="space-y-2">
        {rows.map((p) => (
          <li key={p.id} className="space-y-1.5 rounded-lg bg-white/[.03] px-3 py-2 text-sm">
            <button type="button" className="flex w-full items-start justify-between gap-2 text-left" onClick={() => setOpen(open === p.id ? null : p.id)}
              aria-expanded={open === p.id}>
              <span className="min-w-0">
                <span className="block truncate">{p.vendor}: {p.item}</span>
                <span className="text-xs text-ink-3">
                  {human(p.origin)} · {human(p.classification).toLowerCase()} · {money(p.amount_minor, p.currency)}{p.interval !== "one_time" ? `/${p.interval}` : ""}
                  {p.data_mode === "simulated" ? " · simulated" : ""}
                </span>
              </span>
              <Pill color={PACKET_COLOR[p.status] ?? "#8FA8FF"}>{human(p.status)}</Pill>
            </button>
            <StageBar status={p.status} />
            {open === p.id ? <PacketDetail id={p.id} /> : null}
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function PacketDetail({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["bank", "packet", id], queryFn: () => bank.packet(id), refetchInterval: 5000 });
  if (!q.data) return <Skeleton lines={2} />;
  const { packet: p, approvals, packages, audit, investigation } = q.data;
  const rec = p.recommendation ?? {};
  return (
    <div className="space-y-2 border-t border-line pt-2 text-xs">
      <p className="text-ink-2">{p.classification_reason}. Annualized {money(p.annualized_minor)}; risk {p.risk}{p.significant ? "; escalated to the General Manager" : ""}.</p>
      {p.justification ? <p><span className="text-ink-3">Why requested:</span> {p.justification}</p> : null}
      {rec.summary ? <p><span className="text-ink-3">Recommendation:</span> {rec.summary}</p> : null}
      {rec.narrative && !String(rec.narrative).startsWith("[simulation") ? <p className="text-ink-2">{rec.narrative}</p> : null}
      {investigation ? <InvestigationCard id={investigation.id} /> : null}
      {p.gm_decision?.outcome ? <p><span className="text-ink-3">General Manager:</span> {human(p.gm_decision.outcome)} ({p.gm_decision.method}){p.gm_decision.note ? `: ${p.gm_decision.note}` : ""}</p> : null}
      {(p.findings ?? []).length ? (
        <table className="w-full text-left">
          <thead className="text-ink-3"><tr><th>Option</th><th>3-year cost</th><th>Fit</th><th>Source</th></tr></thead>
          <tbody>
            {p.findings.map((f: Json) => (
              <tr key={f.vendor} className="align-top">
                <td className="pr-2">{f.vendor}{f.is_requested ? " (requested)" : ""}<br /><span className="text-ink-3">{f.item}</span></td>
                <td className="pr-2 tabular-nums">{f.three_year_minor === null ? "usage-priced" : money(f.three_year_minor)}{f.migration_minor ? <><br /><span className="text-ink-3">incl. {money(f.migration_minor)} migration</span></> : null}</td>
                <td className="pr-2">{f.compatibility}<br /><span className="text-ink-3">{f.security}</span></td>
                <td className="break-all text-ink-3">{f.data_mode === "fixture" ? "fixture" : f.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {approvals.length ? (
        <ul className="space-y-1">
          {approvals.map((a: Json) => (
            <li key={a.id} className="flex justify-between gap-2"><span>{human(a.action_type)} {money(a.amount_minor, a.currency)} to {a.recipient}</span><span className="text-ink-3">{human(a.status)}</span></li>
          ))}
        </ul>
      ) : null}
      <p className="flex flex-wrap gap-1">
        {packages.map((x: Json) => (
          <span key={x.id} className="rounded px-1" style={{ color: PACKAGE_COLORS[x.type] ?? "#EAF2FF", background: "rgb(234 242 255 / .05)" }}>
            {human(x.type)}: {x.origin} → {x.destination} ({human(x.status).toLowerCase()})
          </span>
        ))}
      </p>
      <details>
        <summary className="cursor-pointer text-ink-3">Audit trail ({audit.length})</summary>
        <ol className="mt-1 space-y-0.5">
          {audit.map((t: Json) => <li key={t.seq} className="text-ink-3">#{t.seq} {t.action} by {t.actor_type}{t.detail?.to ? ` → ${human(t.detail.to)}` : ""}</li>)}
        </ol>
      </details>
    </div>
  );
}

function ToolRequest() {
  const qc = useQueryClient();
  const [vendor, setVendor] = useState("Figma");
  const [item, setItem] = useState("Professional (per editor)");
  const [amount, setAmount] = useState("15");
  const [interval, setInterval] = useState("month");
  const [why, setWhy] = useState("Design reviews for the iOS app redesign");
  const m = useMutation({ mutationFn: () => bank.toolRequest({ vendor, item, amount: Number(amount), interval, justification: why }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }) });
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
      <h3 className="text-sm font-semibold">Have a developer request a paid tool</h3>
      <div className="grid grid-cols-2 gap-2">
        <input aria-label="Vendor" value={vendor} onChange={(e) => setVendor(e.target.value)} className="rounded-lg border border-line bg-ground/60 px-3 py-2 text-sm" />
        <input aria-label="Plan or item" value={item} onChange={(e) => setItem(e.target.value)} className="rounded-lg border border-line bg-ground/60 px-3 py-2 text-sm" />
        <input aria-label="Price in dollars" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className="rounded-lg border border-line bg-ground/60 px-3 py-2 text-sm" />
        <select aria-label="Billing" value={interval} onChange={(e) => setInterval(e.target.value)} className="rounded-lg border border-line bg-ground px-2 py-2 text-sm">
          <option value="month">per month</option><option value="year">per year</option><option value="one_time">one time</option>
        </select>
      </div>
      <input aria-label="Why it is needed" value={why} onChange={(e) => setWhy(e.target.value)} className="w-full rounded-lg border border-line bg-ground/60 px-3 py-2 text-sm" />
      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" disabled={m.isPending || !vendor.trim() || !(Number(amount) >= 0)}>{m.isPending ? "Sending" : "Send to the bank"}</Button>
        <span className="text-xs text-ink-3">Kade carries it to the bank. Nothing is bought without your step-up approval.</span>
      </div>
      <ErrorNote error={m.error} />
    </form>
  );
}

function BillsAndSubs({ d }: { d: Json }) {
  return (
    <Section title="Bills and subscriptions" aside={d.subscriptions_monthly_minor !== null ? `${money(d.subscriptions_monthly_minor)}/month in subscriptions` : undefined}>
      <ul className="space-y-1 text-sm">
        {d.bills.map((b: Json) => (
          <li key={b.id} className="flex justify-between gap-2">
            <span>{b.payee} <span className="text-xs text-ink-3">due {new Date(b.due_at).toLocaleDateString()}{b.autopay ? " · autopay" : ""}</span></span>
            <span className="flex items-center gap-2 tabular-nums">{money(b.amount_minor, b.currency)}<Pill color={b.status === "OVERDUE" ? "#FF6178" : b.status === "DUE" ? "#FFBD69" : "#8FA8FF"}>{human(b.status)}</Pill></span>
          </li>
        ))}
      </ul>
      <ul className="space-y-1 text-xs">
        {d.subscriptions.map((s: Json) => (
          <li key={s.id} className="flex justify-between gap-2">
            <span>{s.vendor} {s.plan}{s.contract_terms ? <span className="text-warn"> · {s.contract_terms}</span> : null}</span>
            <span className="tabular-nums text-ink-2">{money(s.amount_minor)}/{s.interval}{s.renews_at ? ` · renews ${new Date(s.renews_at).toLocaleDateString()}` : ""}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Savings({ d }: { d: Json }) {
  if (!d.savings.length) return null;
  return (
    <Section title="Savings opportunities" aside="recommendations only; you make any change">
      <ul className="space-y-1 text-sm">
        {d.savings.map((s: Json) => (
          <li key={s.id} className="flex justify-between gap-2">
            <span>{s.title} <span className="text-xs text-ink-3">{s.confidence} confidence{s.data_mode === "simulated" ? " · simulated" : ""}</span></span>
            <span className="tabular-nums text-ok">{money(s.first_year_saving_minor)} first year</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Tax() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["bank", "tax"], queryFn: bank.tax, refetchInterval: 15000 });
  const est = useMutation({ mutationFn: bank.taxEstimate, onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }) });
  const [exporting, setExporting] = useState(false);
  const t = q.data;
  if (!t) return null;
  const e = t.estimate;
  return (
    <Section title={`Taxes ${t.tax_year}`} aside="estimates for your tax professional">
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => est.mutate()} disabled={est.isPending}>Prepare estimate</Button>
        <Button onClick={() => setExporting(true)}>Export for your tax professional</Button>
        <Button disabled title={t.filing.reason}>File return</Button>
      </div>
      <p className="text-xs text-ink-3">{t.filing.reason}</p>
      {e ? (
        <div className="rounded-lg bg-white/[.03] px-3 py-2 text-xs">
          <p className="font-semibold">Estimate ({e.jurisdiction}, {e.period}) <span className="ml-1 rounded bg-white/10 px-1 text-[10px] font-normal">estimate</span></p>
          <p className="tabular-nums">Net profit {money(e.net_profit_minor)} · planning tax {money(e.estimated_tax_minor)} · still to reserve {money(e.reserve_minor)}</p>
          <ul className="mt-1 list-disc pl-4 text-ink-3">{e.uncertainty.map((u: string) => <li key={u}>{u}</li>)}</ul>
        </div>
      ) : null}
      <ul className="space-y-0.5 text-xs">
        {t.deadlines.filter((x: Json) => x.days_left === undefined || x.days_left > -30).slice(0, 4).map((x: Json) => (
          <li key={x.label} className="flex justify-between gap-2"><span>{x.label}</span><span className="text-ink-3">{x.due} ({x.days_left} days)</span></li>
        ))}
      </ul>
      <ul className="space-y-0.5 text-xs">
        {t.checklist.map((c: Json) => (
          <li key={c.doc_type} className="flex items-start gap-1.5"><Dot color={c.status === "received" ? "#5BF2A5" : "#FFBD69"} /><span>{c.doc_type}: {c.why} ({c.status})</span></li>
        ))}
      </ul>
      <ErrorNote error={est.error} />
      {exporting ? (
        <StepUpDialog purpose={`export:${t.tax_year}`} action="Export the tax review package" onCancel={() => setExporting(false)}
          onVerified={async (tok) => {
            const blob = await bank.taxExport(t.tax_year, tok);
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `tax-review-${t.tax_year}.zip`;
            a.click();
            URL.revokeObjectURL(url);
            setExporting(false);
          }} />
      ) : null}
    </Section>
  );
}

function Connections({ d }: { d: Json }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["bank", "connections"], queryFn: bank.connections, refetchInterval: 15000 });
  const pq = useQuery({ queryKey: ["bank", "providers"], queryFn: bank.providers });
  const [adding, setAdding] = useState<string>("");
  const create = useMutation({ mutationFn: (p: string) => bank.createConnection(p), onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }) });
  const sync = useMutation({ mutationFn: (id: string) => bank.sync(id), onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }) });
  const revoke = useMutation({ mutationFn: (id: string) => bank.revoke(id), onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }) });
  const upload = useMutation({ mutationFn: ({ id, f }: { id: string; f: File }) => bank.upload(id, f), onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }) });
  const [authorizing, setAuthorizing] = useState<Json | null>(null);
  const providers: Json[] = pq.data?.providers ?? [];
  const conns: Json[] = q.data?.connections ?? [];
  return (
    <Section title="Data connections" aside="read-only; you authorize each one here">
      <ul className="space-y-2 text-sm">
        {conns.map((c) => (
          <li key={c.id} className="space-y-1 rounded-lg bg-white/[.03] px-3 py-2">
            <div className="flex justify-between gap-2">
              <span>{c.display_name} <span className="text-xs text-ink-3">{c.data_mode}</span></span>
              <Pill color={c.status === "ACTIVE" ? "#5BF2A5" : c.status === "ERROR" ? "#FF6178" : "#8FA8FF"}>{human(c.status)}</Pill>
            </div>
            <p className="text-xs text-ink-3">Scopes: {(c.scopes ?? []).join(", ")}. {c.last_sync_at ? `Synced ${ago(c.last_sync_at)}.` : "Never synced."} {c.last_error ?? ""}</p>
            <div className="flex flex-wrap gap-2">
              {c.status === "PENDING_AUTHORIZATION" ? <Button variant="primary" onClick={() => setAuthorizing(c)}>Authorize read-only access</Button> : null}
              {c.status === "ACTIVE" && c.provider !== "csv_upload" ? <Button onClick={() => sync.mutate(c.id)}>Sync now</Button> : null}
              {c.status === "ACTIVE" && c.provider === "csv_upload" ? (
                <label className="inline-flex min-h-9 cursor-pointer items-center rounded-lg border border-line bg-white/5 px-3 text-sm">
                  Upload CSV<input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => e.target.files?.[0] && upload.mutate({ id: c.id, f: e.target.files[0] })} />
                </label>
              ) : null}
              {c.status !== "REVOKED" ? <Button variant="danger" onClick={() => revoke.mutate(c.id)}>Revoke</Button> : null}
            </div>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <select aria-label="Add a connection" value={adding} onChange={(e) => setAdding(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-line bg-ground px-2 py-2 text-sm">
          <option value="">Add a read-only source…</option>
          {providers.map((p) => <option key={p.key} value={p.key} disabled={!p.built}>{p.label}{p.built ? "" : " (not built yet)"}</option>)}
        </select>
        <Button disabled={!adding || create.isPending} onClick={() => create.mutate(adding)}>Add</Button>
      </div>
      <p className="text-xs text-ink-3">
        Coverage: {(d.coverage.connected_kinds ?? []).map(human).join(", ") || "nothing yet"}. Gaps: {(d.coverage.gaps ?? []).map(human).join(", ") || "none"}.
        Connections this assistant may have elsewhere are never used; each source must be authorized here.
      </p>
      {upload.data ? <p className="text-xs text-ink-2">Imported {upload.data.inserted}, skipped {upload.data.duplicates} already known, rejected {upload.data.rejected}. {(upload.data.errors ?? []).slice(0, 3).join("; ")}</p> : null}
      <ErrorNote error={create.error || sync.error || upload.error || revoke.error} />
      {authorizing ? <Authorize c={authorizing} provider={providers.find((p) => p.key === authorizing.provider)} onDone={() => { setAuthorizing(null); qc.invalidateQueries({ queryKey: ["bank"] }); }} /> : null}
    </Section>
  );
}

function Authorize({ c, provider, onDone }: { c: Json; provider?: Json; onDone: () => void }) {
  const [cred, setCred] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const needsCred = !["simulated", "csv_upload"].includes(c.provider);
  const [verifying, setVerifying] = useState(false);
  const go = async (tok?: string) => {
    try {
      await bank.authorize(c.id, needsCred ? cred : null, tok);
      onDone();
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <div className="space-y-2 rounded-xl border border-gold/40 bg-white/[.03] p-3 text-sm" role="dialog" aria-label={`Authorize ${c.display_name}`}>
      <p className="font-semibold">Authorize {c.display_name}</p>
      <p className="text-xs text-ink-2">Read-only scopes: {(c.scopes ?? []).join(", ")}. The credential is encrypted at rest and never shown again.</p>
      {needsCred ? <textarea aria-label="Credential" value={cred} onChange={(e) => setCred(e.target.value)} placeholder={provider?.credential_hint} rows={3}
        className="w-full rounded-lg border border-line bg-ground/60 px-3 py-2 font-mono text-xs" /> : null}
      <div className="flex gap-2">
        <Button variant="primary" disabled={needsCred && !cred.trim()} onClick={() => (needsCred ? setVerifying(true) : go())}>Grant read-only access</Button>
        <Button onClick={onDone}>Cancel</Button>
      </div>
      <ErrorNote error={err} />
      {verifying ? <StepUpDialog purpose={`connection:${c.id}`} action={`Authorize ${c.display_name}`} onCancel={() => setVerifying(false)}
        onVerified={async (tok) => { setVerifying(false); await go(tok); }} /> : null}
    </div>
  );
}

function AuditStatus() {
  const q = useQuery({ queryKey: ["bank", "audit"], queryFn: bank.audit, refetchInterval: 20000 });
  if (!q.data) return null;
  const c = q.data.chain;
  return (
    <p className="text-xs text-ink-3">
      <Dot color={c.ok ? "#5BF2A5" : "#FF6178"} /> <span className="ml-1">Financial audit log: {c.entries} entries, hash chain {c.ok ? "verified" : `BROKEN at #${c.broken_at_seq}`}.</span>
    </p>
  );
}

/**
 * Step-up verification: a fresh 6-digit code from the owner's authenticator, exchanged for a 5-minute token that only
 * works for this one action. First use enrolls the authenticator (the secret is shown once).
 */
export function StepUpDialog({ purpose, action, onVerified, onCancel }: { purpose: string; action: string; onVerified: (token: string) => Promise<void> | void; onCancel: () => void }) {
  const status = useQuery({ queryKey: ["bank", "stepup"], queryFn: bank.stepUpStatus });
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const enroll = useMutation({ mutationFn: bank.stepUpEnroll, onSuccess: () => qc.invalidateQueries({ queryKey: ["bank", "stepup"] }) });
  const verify = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await bank.stepUpVerify(code, purpose);
      await onVerified(r.step_up_token);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2 rounded-xl border border-gold/50 bg-ground/90 p-3 text-sm" role="dialog" aria-label="Step-up verification">
      <p className="font-semibold">Confirm it's you</p>
      <p className="text-xs text-ink-2">{action} needs a fresh code from your authenticator app. The confirmation works for this action only, for 5 minutes.</p>
      {status.data && !status.data.enrolled && !enroll.data ? (
        <Button variant="primary" onClick={() => enroll.mutate()} disabled={enroll.isPending}>Set up an authenticator</Button>
      ) : null}
      {enroll.data ? (
        <div className="rounded-lg border border-warn/40 bg-warn/10 p-2 text-xs">
          <p>Add this to your authenticator app now. It is shown once.</p>
          <p className="mt-1 break-all font-mono" data-testid="totp-secret">{enroll.data.secret}</p>
          <p className="mt-1 break-all text-ink-3">{enroll.data.otpauth_uri}</p>
        </div>
      ) : null}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); verify(); }}>
        <input aria-label="6-digit code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          className="w-28 rounded-lg border border-line bg-ground/60 px-3 py-2 text-center font-mono tracking-widest" />
        <Button type="submit" variant="approve" disabled={code.length !== 6 || busy}>{busy ? "Checking" : "Confirm"}</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </form>
      <ErrorNote error={err} />
    </div>
  );
}
