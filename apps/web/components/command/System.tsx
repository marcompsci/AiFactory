"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, loadConnection, saveConnection, type Json } from "@/lib/api";
import { usd } from "@/lib/format";
import { useStore, type Quality } from "@/lib/store";
import { Button, Dot, Empty, ErrorNote, Pill, Section, Skeleton } from "./ui";
import { useEffect } from "react";
import type { Session } from "@supabase/supabase-js";
import { authConfigured, githubSigninToken, onSession, signIn, signOut } from "@/lib/auth";

/** Sign in with Google or GitHub, and how Claude is connected. */
function AccountsPanel({ onReconnect }: { onReconnect: () => void }) {
  const [session, setSession] = useState<Session | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => onSession(setSession), []);
  const go = (p: "google" | "github", repo = false) => signIn(p, repo).catch(setErr);
  const provider = session?.user?.app_metadata?.provider as string | undefined;
  return (
    <Section title="Accounts">
      {!authConfigured() ? (
        <p className="text-xs text-ink-3">Sign-in isn't configured on this deployment. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY and enable the Google and GitHub providers in Supabase (docs/AUTH.md). Until then, use an API token below.</p>
      ) : session ? (
        <div className="flex items-center gap-2 text-sm">
          <Pill color="#5BF2A5">Signed in</Pill>
          <span className="min-w-0 flex-1 truncate">{session.user.email} via {provider}</span>
          <Button onClick={() => signOut().then(onReconnect)}>Sign out</Button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => go("google")}>Sign in with Google</Button>
          <Button onClick={() => go("github")}>Sign in with GitHub</Button>
        </div>
      )}
      {authConfigured() ? (
        <p className="text-xs text-ink-3">
          {githubSigninToken() ? "Your GitHub sign-in can be used to connect repositories in App Lab." : (
            <>For App Lab, a fine-grained token for one repository is safest. Or <button type="button" className="text-cyan" onClick={() => go("github", true)}>sign in with GitHub with repository access</button>.</>
          )}
        </p>
      ) : null}
      <div className="rounded-xl border border-line p-3 text-xs text-ink-2">
        <p className="font-semibold text-ink">Claude</p>
        <p className="mt-1">Agents think with Claude through the server's Anthropic API key (ANTHROPIC_API_KEY). Code changes you approve in App Lab can be carried out by Claude Code in GitHub, through Anthropic's Claude Code GitHub Action, using a CLAUDE_CODE_OAUTH_TOKEN repository secret you create with <code>claude setup-token</code>. Third-party apps can't offer claude.ai login, so this app never asks for your Claude password.</p>
      </div>
      <ErrorNote error={err} />
    </Section>
  );
}

export function SystemPanel({ onReconnect }: { onReconnect: () => void }) {
  const status = useStore((s) => s.status);
  return (
    <div className="space-y-6">
      {status !== "demo" ? (
        <>
          <EmergencyStopControl />
          <CostDashboard />
          <SystemHealthPanel />
          <MemoryPanel />
        </>
      ) : null}
      <AccountsPanel onReconnect={onReconnect} />
      <ConnectionSettings onReconnect={onReconnect} />
      <WorldSettings />
    </div>
  );
}

function EmergencyStopControl() {
  const qc = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 10000 });
  const stop = useMutation({
    mutationFn: (engaged: boolean) => api.emergencyStop(engaged),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["health"] });
      qc.invalidateQueries({ queryKey: ["snapshot"] });
    },
  });
  const engaged = health.data?.emergency_stopped;
  return (
    <div className={`rounded-xl border p-3 ${engaged ? "border-bad bg-bad/15" : "border-bad/30"}`}>
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-bad">{engaged ? "Emergency stop is on" : "Emergency stop"}</p>
          <p className="text-xs text-ink-2">
            {engaged ? "Every tool call is refused and no mission can start." : "Cancels every active mission and blocks all tool calls until released."}
          </p>
        </div>
        {engaged ? (
          <Button onClick={() => stop.mutate(false)} disabled={stop.isPending}>
            Release
          </Button>
        ) : (
          <Button variant="danger" onClick={() => confirm("Stop every agent now?") && stop.mutate(true)} disabled={stop.isPending}>
            Stop everything
          </Button>
        )}
      </div>
      <ErrorNote error={stop.error} />
    </div>
  );
}

function CostDashboard() {
  const q = useQuery({ queryKey: ["costs"], queryFn: api.costs });
  const agents = useStore((s) => s.world.agents);
  const d = q.data;
  const pct = d ? Math.min(100, (d.today_estimated_usd / d.daily_budget_usd) * 100) : 0;
  return (
    <Section title="Spend today" aside="estimates, not invoices">
      {q.isLoading ? <Skeleton lines={2} /> : null}
      <ErrorNote error={q.error} />
      {d ? (
        <>
          <div className="flex items-baseline gap-2">
            <span className="font-display text-xl">{usd(d.today_estimated_usd)}</span>
            <span className="text-sm text-ink-3">of {usd(d.daily_budget_usd)} daily cap</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: pct > 80 ? "#FFBD69" : "#32D8FF" }} />
          </div>
          {d.by_agent_model.length === 0 ? (
            <p className="text-xs text-ink-3">No model calls yet. Simulation missions cost nothing.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {d.by_agent_model.map((r: Json) => (
                <li key={r.agent_id + r.model} className="flex justify-between gap-2">
                  <span className="truncate">
                    <span style={{ color: agents[r.agent_id]?.color }}>{agents[r.agent_id]?.name ?? "?"}</span> <span className="text-ink-3">{r.model}</span>
                  </span>
                  <span className="text-ink-2">{usd(r.estimated_cost_usd)}</span>
                </li>
              ))}
            </ul>
          )}
          {d.tool_time.length ? (
            <p className="text-xs text-ink-3">
              Tool time:{" "}
              {d.tool_time
                .map((t: Json) => `${t.tool_name} ${t.calls}×`)
                .slice(0, 6)
                .join(", ")}
            </p>
          ) : null}
        </>
      ) : null}
    </Section>
  );
}

function SystemHealthPanel() {
  const q = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 10000 });
  const status = useStore((s) => s.status);
  const d = q.data;
  const row = (label: string, ok: boolean, value: string) => (
    <li className="flex items-center gap-2 text-sm">
      <Dot color={ok ? "#5BF2A5" : "#FFBD69"} />
      <span className="text-ink-2">{label}</span>
      <span className="ml-auto text-ink">{value}</span>
    </li>
  );
  return (
    <Section title="System health">
      {q.isLoading ? <Skeleton lines={4} /> : null}
      <ErrorNote error={q.error} />
      {d ? (
        <ul className="space-y-1">
          {row("Realtime", status === "live", status === "live" ? "connected" : status)}
          {row("Agents' brains", d.execution_mode === "live", d.execution_mode === "live" ? d.providers.join(", ") : "simulation (no model key)")}
          {row("Sandbox", d.network_isolation, `${d.sandbox}${d.network_isolation ? ", no network" : ", network not isolated"}`)}
          {row("Event outbox", d.outbox_backlog < 50 && d.publisher_alive, `${d.outbox_backlog} waiting`)}
          {row("Database", true, d.database)}
          {row("Sign-in", d.auth_mode !== "dev", d.auth_mode === "dev" ? "local dev (no token)" : d.auth_mode)}
        </ul>
      ) : null}
    </Section>
  );
}

function MemoryPanel() {
  const [q, setQ] = useState("");
  const m = useQuery({ queryKey: ["memory", q], queryFn: () => api.memory(q) });
  return (
    <Section title="Memory Vault" aside="verified facts cite their source">
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search memory"
        aria-label="Search memory"
        className="w-full rounded-lg border border-line bg-ground/60 px-3 py-2 text-sm"
      />
      {m.data?.entries.length === 0 ? <Empty>Nothing remembered yet. Finished missions leave verified results here.</Empty> : null}
      <ul className="space-y-1.5">
        {m.data?.entries.slice(0, 20).map((e: Json) => (
          <li key={e.id} className="text-sm">
            <span className={e.trust === "verified" ? "text-ok" : "text-warn"}>{e.trust === "verified" ? "Verified" : "Hypothesis"}</span>{" "}
            <span className="text-ink-2">{e.content}</span>
            <div className="font-mono text-[10px] text-ink-3">{e.source}</div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function ConnectionSettings({ onReconnect }: { onReconnect: () => void }) {
  const [c, setC] = useState(loadConnection);
  const status = useStore((s) => s.status);
  const detail = useStore((s) => s.statusDetail);
  return (
    <Section title="Server">
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          saveConnection(c);
          onReconnect();
        }}
      >
        <label className="block text-xs text-ink-2">
          API address
          <input value={c.apiUrl} onChange={(e) => setC({ ...c, apiUrl: e.target.value })} className="mt-1 w-full rounded-lg border border-line bg-ground/60 px-3 py-2 text-sm text-ink" inputMode="url" autoCapitalize="off" autoCorrect="off" />
        </label>
        <label className="block text-xs text-ink-2">
          Access token
          <input type="password" value={c.token} onChange={(e) => setC({ ...c, token: e.target.value })} className="mt-1 w-full rounded-lg border border-line bg-ground/60 px-3 py-2 text-sm text-ink" autoComplete="off" placeholder="AICIV_API_TOKEN from the server" />
        </label>
        <div className="flex items-center gap-2">
          <Button type="submit" variant="primary">
            Connect
          </Button>
          <span className="text-xs text-ink-3">{status === "demo" ? `Not reachable, showing demo. ${detail}` : status}</span>
        </div>
      </form>
    </Section>
  );
}

function WorldSettings() {
  const s = useStore((st) => st.settings);
  const set = useStore((st) => st.setSettings);
  const toggle = (k: "reducedMotion" | "labels" | "drones" | "pixelArt", label: string, hint: string) => (
    <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" className="mt-1" checked={s[k]} onChange={(e) => set({ [k]: e.target.checked })} />
      <span>
        {label}
        <span className="block text-xs text-ink-3">{hint}</span>
      </span>
    </label>
  );
  return (
    <Section title="World">
      <div className="space-y-2">
        {toggle("reducedMotion", "Reduce motion", "Agents jump to places instead of walking; no bobbing or pulsing.")}
        {toggle("labels", "Name tags", "Show agent and district names in the city.")}
        {toggle("drones", "Ambient traffic", "Flying cars are decoration only. They never represent agent work.")}
        {toggle("pixelArt", "Pixel-art rendering", "Renders the city at a low resolution and scales it up without smoothing.")}
        <label className="flex items-center gap-2 text-sm">
          Rendering
          <select value={s.quality} onChange={(e) => set({ quality: e.target.value as Quality })} className="rounded-md border border-line bg-ground px-2 py-1 text-sm">
            <option value="auto">Adapt to device</option>
            <option value="high">High (glow on)</option>
            <option value="low">Battery saver</option>
          </select>
        </label>
      </div>
    </Section>
  );
}
