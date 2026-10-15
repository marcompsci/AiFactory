"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { bank, type Json } from "@/lib/api";
import { human, money } from "@/lib/format";
import { Button, Dot, ErrorNote, Pill, Skeleton } from "./ui";

export const INVESTIGATION_STAGES = ["REQUESTED", "RESEARCHING", "EVALUATING", "TESTING", "MANAGER_REVIEW", "AWAITING_OWNER"];
const WHERE: Record<string, string> = {
  REQUESTED: "on the belt to the Data Observatory",
  RESEARCHING: "Haiku researchers are gathering candidates",
  EVALUATING: "the Savings Strategist is scoring the shortlist",
  TESTING: "Code Forge is testing in a sandbox, then QA reviews",
  MANAGER_REVIEW: "the General Manager is preparing a recommendation",
  AWAITING_OWNER: "waiting for your decision",
};
const OUTCOME_COLOR: Record<string, string> = { passed: "#5BF2A5", failed: "#FF6178", error: "#FFBD69" };

/** A free-alternative investigation: everything the backend recorded, labeled as fixture data where it is. */
export function InvestigationCard({ id, compact = false }: { id: string; compact?: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["bank", "investigation", id], queryFn: () => bank.investigation(id), refetchInterval: 4000 });
  const cancel = useMutation({ mutationFn: () => bank.cancelInvestigation(id), onSettled: () => qc.invalidateQueries({ queryKey: ["bank"] }) });
  if (!q.data) return <Skeleton lines={2} />;
  const { investigation: inv, candidates, sandbox_evaluations: evals, cost_comparisons: costs, reviews } = q.data;
  const i = INVESTIGATION_STAGES.indexOf(inv.status);
  const ended = ["BLOCKED", "FAILED", "CANCELLED"].includes(inv.status);
  const rec = inv.recommendation ?? {};
  const qa = reviews.find((r: Json) => r.stage === "qa");
  return (
    <div className="space-y-2 rounded-lg border border-[#3DFFB8]/30 bg-[#3DFFB8]/[.04] p-2 text-xs" data-testid="investigation">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-[#3DFFB8]">Free-alternative investigation</span>
        <Pill color={ended ? "#FF6178" : inv.status === "AWAITING_OWNER" ? "#FFD86B" : "#3DFFB8"}>{human(inv.status)}</Pill>
      </div>
      <div className="flex gap-0.5" aria-label={`Stage ${human(inv.status)}`}>
        {INVESTIGATION_STAGES.map((s, k) => (
          <span key={s} title={human(s)} className="h-1 flex-1 rounded-full" style={{ background: !ended && k <= i ? "#3DFFB8" : "rgb(234 242 255 / .1)" }} />
        ))}
      </div>
      <p className="text-ink-2">{ended ? inv.reason : WHERE[inv.status]}. Research and sandbox testing only: nothing is bought, cancelled or deployed.</p>
      {!ended && inv.status !== "AWAITING_OWNER" && !compact ? <Button variant="danger" onClick={() => cancel.mutate()}>Cancel investigation</Button> : null}
      <ErrorNote error={cancel.error} />
      {rec.headline ? (
        <div className="rounded-md bg-white/[.04] p-2">
          <p className="font-semibold">General Manager: {human(rec.verdict)}</p>
          <p>{rec.headline}</p>
          {rec.manager_note ? <p className="text-ink-2">{rec.manager_note}</p> : null}
          <ul className="mt-1 space-y-0.5">
            {(rec.options ?? []).map((o: Json) => (
              <li key={o.label}><span className="tabular-nums">{o.three_year_minor === null ? "" : `${money(o.three_year_minor)} over 3 years · `}</span>{o.label}: <span className="text-ink-3">{o.how}</span></li>
            ))}
          </ul>
          <p className="mt-1 text-ink-3">This recommendation authorizes nothing. Any purchase or switch needs your own, separate decision.</p>
        </div>
      ) : null}
      {compact ? null : (
        <>
          {evals.map((e: Json) => (
            <div key={e.id} className="rounded-md bg-white/[.04] p-2">
              <p className="font-semibold">Sandbox: {candidates.find((c: Json) => c.id === e.candidate_id)?.name} · {e.status}
                <span className="font-normal text-ink-3"> ({e.passed} passed, {e.failed} failed, {e.errors} errors · {e.sandbox}, network isolated: {e.network_isolated ? "yes" : "no"})</span></p>
              <p className="text-ink-3">{e.subject}</p>
              <ul className="mt-1 space-y-0.5">
                {(e.results ?? []).map((r: Json) => (
                  <li key={r.requirement} className="flex items-start gap-1.5"><Dot color={OUTCOME_COLOR[r.outcome] ?? "#8FA8FF"} />
                    <span>{r.description}{r.detail ? <span className="text-ink-3">: {r.detail}</span> : null}</span></li>
                ))}
              </ul>
              {e.status === "ERROR" ? <p className="text-warn">{e.output_excerpt?.split("\n")[0]}</p> : null}
            </div>
          ))}
          {qa ? <p><span className="text-ink-3">QA ({human(qa.verdict)}):</span> {qa.summary}</p> : null}
          {candidates.length ? (
            <table className="w-full text-left">
              <thead className="text-ink-3"><tr><th>#</th><th>Candidate</th><th>Score</th><th>3 years</th><th>Sources</th></tr></thead>
              <tbody>
                {candidates.map((c: Json) => (
                  <tr key={c.id} className="align-top">
                    <td className="pr-1">{c.rank}</td>
                    <td className="pr-2">{c.name}{c.shortlisted ? " ★" : ""}<br /><span className="text-ink-3">{c.license} · {c.confidence} confidence</span>
                      {(c.limitations ?? []).length ? <><br /><span className="text-warn">{c.limitations[0]}</span></> : null}</td>
                    <td className="pr-2 tabular-nums" title={c.assessment ? `compatibility ${c.assessment.compatibility} · security ${c.assessment.security} · functionality ${c.assessment.functionality} · migration ${c.assessment.migration} · cost ${c.assessment.total_cost}` : ""}>
                      {c.assessment ? c.assessment.total_score.toFixed(2) : "-"}</td>
                    <td className="pr-2 tabular-nums">{c.estimated_costs?.three_year_minor !== undefined ? money(c.estimated_costs.three_year_minor) : "-"}</td>
                    <td className="break-all text-ink-3">
                      {c.data_mode === "fixture" ? "fixture · " : ""}
                      {c.product_url ? <a className="underline" href={c.product_url} target="_blank" rel="noreferrer">site</a> : null}
                      {c.license_url ? <> · <a className="underline" href={c.license_url} target="_blank" rel="noreferrer">license</a></> : null}
                      <br />{(c.evidence ?? []).filter((e: Json) => e.kind === "pricing").map((e: Json) => <span key={e.id}>{e.claim} (as of {e.as_of})</span>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          {costs.length ? (
            <p className="text-ink-3">Cost comparison: {costs.slice().sort((a: Json, b: Json) => a.three_year_minor - b.three_year_minor).map((x: Json) => `${x.label} ${money(x.three_year_minor)}`).join(" · ")}</p>
          ) : null}
        </>
      )}
    </div>
  );
}
