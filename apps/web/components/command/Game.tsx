"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { game, type Json } from "@/lib/api";
import { ago, human, money } from "@/lib/format";
import { useStore } from "@/lib/store";
import { Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";

const KIND: Record<string, string> = {
  realized_savings: "Saved on a purchase",
  avoided_cost: "Found a free alternative",
  attributed_revenue: "Revenue from a product they built",
};

/** The money game: who made you the most money this season. Only verified money scores; simulated plays are labeled
 * and kept in their own column. */
export function GamePanel() {
  const [season, setSeason] = useState<string | undefined>();
  const q = useQuery({ queryKey: ["game", season], queryFn: () => game.board(season), refetchInterval: 5000 });
  const agents = useStore((s) => s.world.agents);
  const select = useStore((s) => s.selectAgent);
  if (q.isLoading) return <Skeleton lines={6} />;
  if (q.error) return <ErrorNote error={q.error} />;
  const d = q.data!;
  const hidden = Boolean(d.amounts_hidden);
  const anyPlays = d.plays.length > 0;
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <h3 className="font-display text-base">Season {d.season?.key}</h3>
        <select aria-label="Season" value={season ?? d.season?.key} onChange={(e) => setSeason(e.target.value)}
          className="ml-auto rounded-lg border border-line bg-ground/60 px-2 py-1 text-xs">
          {d.seasons.map((s: string) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      {!hidden ? (
        <div className="grid grid-cols-2 gap-2 text-sm">
          <Stat label="Verified this season" value={money(d.totals.verified_minor)} tone="#3DFFB8" />
          <Stat label="Simulated (practice)" value={money(d.totals.simulated_minor)} tone="#FFBD69" />
        </div>
      ) : <p className="text-xs text-ink-3">Amounts are visible to the owner and admins.</p>}

      <Section title="Leaderboard" aside="ranked by verified money">
        <ol className="space-y-1" data-testid="leaderboard">
          {d.leaderboard.map((r: Json) => {
            const color = agents[r.agent_id]?.color ?? "#8FA8FF";
            return (
              <li key={r.agent_id}>
                <button type="button" onClick={() => select(r.agent_id)}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-white/5">
                  <span className="w-6 text-center font-display text-xs" style={{ color: r.rank <= 3 ? "#FFD36B" : undefined }}>{r.rank}</span>
                  <span className="pixel-avatar size-5 shrink-0 rounded-sm" style={{ background: color }} aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{r.name} <span className="text-xs text-ink-3">{r.role}</span></span>
                  <span className="text-[11px] text-ink-3">Lv {r.level}</span>
                  {!hidden ? (
                    <span className="w-24 text-right font-mono text-xs">
                      {r.verified_minor ? <span className="text-ok">{money(r.verified_minor)}</span> : <span className="text-ink-3">$0</span>}
                      {r.simulated_minor ? <span className="block text-[10px] text-warn">sim {money(r.simulated_minor)}</span> : null}
                    </span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ol>
      </Section>

      <Section title="Plays">
        {!anyPlays ? (
          <Empty>No scores yet. Agents score when you approve a cheaper option and it's carried out, when you turn down a purchase after they found a free alternative, or when revenue arrives from a product you've linked to their work.</Empty>
        ) : null}
        <ul className="space-y-1.5">
          {d.plays.map((p: Json) => (
            <li key={p.id} className="flex items-start gap-2 text-sm">
              <span className="min-w-0 flex-1">
                <b>{p.agent}</b> · {KIND[p.kind] ?? human(p.kind)}
                {p.share < 1 ? <span className="text-xs text-ink-3"> (shared {Math.round(p.share * 100)}%)</span> : null}
                <span className="block text-xs text-ink-3">{ago(p.created_at)}{p.evidence?.vendor ? ` · ${p.evidence.vendor}` : ""}{p.evidence?.merchant ? ` · ${p.evidence.merchant}` : ""}</span>
              </span>
              {!hidden && p.amount_minor !== undefined ? <span className="font-mono text-xs">{money(p.amount_minor, p.currency)}</span> : null}
              <Pill color={p.verified ? "#3DFFB8" : "#FFBD69"}>{p.verified ? "verified" : "simulated"}</Pill>
            </li>
          ))}
        </ul>
      </Section>

      <details className="text-xs text-ink-2">
        <summary className="cursor-pointer">Rules</summary>
        <pre className="mt-1 whitespace-pre-wrap font-sans">{d.rules}</pre>
      </details>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-xl border border-line p-2">
      <p className="text-[11px] text-ink-3">{label}</p>
      <p className="font-display text-lg" style={{ color: tone }}>{value}</p>
    </div>
  );
}
