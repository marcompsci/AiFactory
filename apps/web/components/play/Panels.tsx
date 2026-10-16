"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ArtifactViewer } from "@/components/command/Artifacts";
import { OwnerDesk } from "@/components/command/OwnerTower";
import { api, play, type Json } from "@/lib/api";
import { PACKAGE_LABEL } from "@/lib/play/engine";
import { TOWN_BUILDINGS } from "@/lib/play/maps";
import { DEFAULT_PLAYER, type PlayerLook } from "@/lib/play/sprites";
import { usePlay } from "@/lib/play/state";
import { useStore } from "@/lib/store";
import { live } from "./runner";

function Sheet({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-2 pb-[max(8px,env(safe-area-inset-bottom))] sm:items-center sm:p-6" onClick={onClose}>
      <div className="px-panel flex max-h-[86dvh] w-full max-w-2xl flex-col" role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b-2 border-[#f3e9d2]/25 px-4 py-2">
          <h2 className="font-pixel text-lg text-[#f3e9d2]">{title}</h2>
          <button type="button" onClick={onClose} className="px-btn rounded-md bg-[#2a2246] px-3 py-1 text-sm text-[#f3e9d2]">Close</button>
        </div>
        <div className="scroll-thin overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}

const close = () => usePlay.getState().openPanel(null);

export function Panels() {
  const panel = usePlay((s) => s.panel);
  if (panel === "approvals") return <Sheet title="Owner approvals" onClose={close}><Approvals /></Sheet>;
  if (panel === "journal" || panel === "findings") return <Sheet title="Mission journal" onClose={close}><Journal start={panel === "findings" ? "findings" : "missions"} /></Sheet>;
  if (panel === "avatar") return <Sheet title="Your character" onClose={close}><AvatarEditor /></Sheet>;
  return null;
}

function Approvals() {
  return (
    <div className="space-y-5">
      <p className="rounded-md bg-white/5 p-2 text-xs text-ink-2">
        Only Approve buttons approve anything. Closing this screen, walking away from an agent or closing the game never counts as approval.
        Purchases, payments and submissions also ask you to confirm with your authenticator.
      </p>
      <OwnerDesk />
    </div>
  );
}

const MISSION_TONE: Record<string, string> = { COMPLETED: "text-ok", FAILED: "text-bad", CANCELLED: "text-ink-3", WAITING_FOR_APPROVAL: "text-warn" };

function Journal({ start }: { start: "missions" | "findings" }) {
  const status = useStore((s) => s.status);
  const [tab, setTab] = useState(start);
  const snap = useQuery({ queryKey: ["snapshot"], queryFn: api.snapshot, enabled: status !== "demo" && status !== "signin" });
  const missions: Json[] = snap.data?.missions ?? [];
  const opps: Json[] = snap.data?.opportunities ?? [];
  if (status === "demo") return <p className="text-sm text-ink-2">The demo city has no journal. Connect to your Mac to see your real missions.</p>;
  if (status === "signin") return <p className="text-sm text-ink-2">Sign in to see your missions.</p>;
  return (
    <div>
      <div className="mb-3 flex gap-2">
        {(["missions", "findings"] as const).map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)} className={`px-btn rounded-md px-3 py-1 text-sm ${tab === t ? "bg-[#F4D58D] text-[#1d1626]" : "bg-[#2a2246] text-[#f3e9d2]"}`}>
            {t === "missions" ? "Missions" : "Findings"}
          </button>
        ))}
      </div>
      {tab === "missions" ? (
        missions.length ? (
          <ul className="space-y-2">{missions.map((m) => <MissionRow key={m.id} m={m} />)}</ul>
        ) : <p className="text-sm text-ink-2">No missions yet. Talk to Lumen at the Research Observatory or Kade at the Code Forge to start one.</p>
      ) : opps.length ? (
        <ul className="space-y-2">
          {opps.map((o) => (
            <li key={o.id} className="rounded-md bg-white/5 p-2 text-sm">
              <div className="font-semibold text-ink">{o.title}</div>
              <div className="text-xs text-ink-2">
                Score {Number(o.opportunity_score).toFixed(2)} · {o.confidence} confidence · {String(o.status).toLowerCase().replace(/_/g, " ")}
                {o.data_mode !== "live" ? " · fixture data" : ""}
              </div>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-ink-2">No research findings yet.</p>}
    </div>
  );
}

function MissionRow({ m }: { m: Json }) {
  const [open, setOpen] = useState(false);
  const [artifact, setArtifact] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["mission", m.id], queryFn: () => api.mission(m.id), enabled: open });
  const tasks: Json[] = q.data?.tasks ?? [];
  const arts: Json[] = q.data?.artifacts ?? [];
  const agents = useStore((s) => s.world.agents);
  return (
    <li className="rounded-md bg-white/5 p-2 text-sm">
      <button type="button" className="w-full text-left" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <div className="flex items-start justify-between gap-2">
          <span className="font-semibold text-ink">{m.title}</span>
          <span className={`shrink-0 text-xs ${MISSION_TONE[m.status] ?? "text-cyan"}`}>{String(m.status).toLowerCase().replace(/_/g, " ")}{m.paused ? " · paused" : ""}</span>
        </div>
        <div className="text-xs text-ink-3">
          {m.execution_mode === "simulation" ? "Simulation: no AI model connected, so this is a rehearsal" : "Live"} · {new Date(m.created_at).toLocaleString()}
        </div>
      </button>
      {open ? (
        <div className="mt-2 space-y-1 border-t border-white/10 pt-2">
          {q.isLoading ? <p className="text-xs text-ink-3">Loading…</p> : null}
          {tasks.map((t) => (
            <div key={t.id} className="flex justify-between gap-2 text-xs">
              <span className="text-ink-2">{t.title} <span className="text-ink-3">· {agents[t.agent_id]?.name ?? "agent"}</span></span>
              <span className={MISSION_TONE[t.status] ?? "text-cyan"}>{String(t.status).toLowerCase().replace(/_/g, " ")}</span>
            </div>
          ))}
          {arts.length ? <div className="pt-1 text-xs text-ink-3">Artifacts</div> : null}
          {arts.map((a) => (
            <button key={a.id} type="button" onClick={() => setArtifact(a.id)} className="block text-left text-xs text-cyan underline-offset-2 hover:underline">
              {a.title} ({a.kind})
            </button>
          ))}
          {m.failure_reason ? <p className="text-xs text-bad">{m.failure_reason}</p> : null}
        </div>
      ) : null}
      {artifact ? <ArtifactViewer id={artifact} onClose={() => setArtifact(null)} /> : null}
    </li>
  );
}

const NAME: Record<string, string> = Object.fromEntries([...TOWN_BUILDINGS.map((b) => [b.id, b.name]),
  ["claude-code-factory", "Claude Code Factory"], ["github-factory", "GitHub Factory"], ["codex-factory", "Codex Factory"]]);

export function PackageCard() {
  const id = usePlay((s) => s.packageId);
  const pkg = useStore((s) => (id ? s.world.packages[id] : undefined));
  if (!id || !pkg) return null;
  const eta = pkg.eta ? new Date(pkg.eta) : null;
  return (
    <div className="fixed left-1/2 top-[calc(max(12px,env(safe-area-inset-top))+64px)] z-30 w-[min(92vw,380px)] -translate-x-1/2">
      <div className="px-panel p-3 text-sm">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="font-pixel text-[#f3e9d2]">{PACKAGE_LABEL[pkg.type] ?? pkg.type.replace(/_/g, " ")}</div>
            <div className="text-xs text-ink-2">{NAME[pkg.origin] ?? pkg.origin} → {NAME[pkg.destination] ?? pkg.destination}</div>
          </div>
          <button type="button" onClick={() => usePlay.getState().selectPackage(null)} className="text-xs text-ink-3" aria-label="Close">✕</button>
        </div>
        <div className="mt-1 text-xs">
          <span className="text-cyan">{pkg.status.toLowerCase().replace(/_/g, " ")}</span>
          {pkg.status === "IN_TRANSIT" && eta ? <span className="text-ink-3"> · arrives {eta.toLocaleTimeString()}</span> : null}
        </div>
        <p className="mt-2 text-[11px] text-ink-3">A package on the belt is a real handoff record. Moving or arriving isn&apos;t proof the work is done; the journal has the verified result.</p>
      </div>
    </div>
  );
}

const SKINS = ["#FFDBB4", "#F1C27D", "#E8B48A", "#C68642", "#8D5524", "#5C3A21"];
const HAIRS = ["#1E1B22", "#4A2E1F", "#8E5BE8", "#C9CED8", "#E8862E", "#3CCB7F", "#3F8CFF", "#FF6FAE"];
const SHIRTS = ["#B8BCC6", "#24345C", "#C2553A", "#4F8A62", "#7A5CD6", "#F2F2F2", "#F4D58D", "#1E1E26"];
const PANTS = ["#25252E", "#33415C", "#5A6275", "#6B4B2E", "#2D4A3E"];
const STYLES = ["spiky", "short", "buzz", "curly", "long", "bun", "afro", "bald"];

function Swatches({ label, value, options, onPick }: { label: string; value: string; options: string[]; onPick: (v: string) => void }) {
  return (
    <div>
      <div className="mb-1 text-xs text-ink-2">{label}</div>
      <div className="flex flex-wrap gap-2">
        {options.map((c) => (
          <button key={c} type="button" onClick={() => onPick(c)} aria-label={`${label} ${c}`} aria-pressed={value.toUpperCase() === c.toUpperCase()}
            className={`size-8 rounded-md border-2 ${value.toUpperCase() === c.toUpperCase() ? "border-white" : "border-[#1d1626]"}`} style={{ background: c }} />
        ))}
      </div>
    </div>
  );
}

function AvatarEditor() {
  const look = usePlay((s) => s.look);
  const name = usePlay((s) => s.name);
  const [draft, setDraft] = useState<PlayerLook>(look);
  const [nm, setNm] = useState(name);
  const status = useStore((s) => s.status);
  const save = useMutation({
    mutationFn: () => play.save({ name: nm || "Owner", look: draft, map: live.mapId, x: live.x, y: live.y, facing: live.facing }),
    onSuccess: () => { usePlay.getState().setLook(draft, nm || "Owner"); close(); },
  });
  const set = (k: keyof PlayerLook, v: string | boolean) => { const next = { ...draft, [k]: v }; setDraft(next); usePlay.getState().setLook(next); };
  return (
    <div className="space-y-4">
      <label className="block text-xs text-ink-2">
        Name
        <input value={nm} maxLength={24} onChange={(e) => setNm(e.target.value)} className="mt-1 block w-full rounded-md border border-[#f3e9d2]/30 bg-[#0f0c1f] px-3 py-2 text-[16px] text-ink" />
      </label>
      <div>
        <div className="mb-1 text-xs text-ink-2">Hair</div>
        <div className="flex flex-wrap gap-2">
          {STYLES.map((s) => (
            <button key={s} type="button" onClick={() => set("hair_style", s)} aria-pressed={draft.hair_style === s}
              className={`px-btn rounded-md px-3 py-1 text-sm ${draft.hair_style === s ? "bg-[#F4D58D] text-[#1d1626]" : "bg-[#2a2246] text-[#f3e9d2]"}`}>{s}</button>
          ))}
        </div>
      </div>
      <Swatches label="Hair color" value={draft.hair} options={HAIRS} onPick={(v) => set("hair", v)} />
      <Swatches label="Skin" value={draft.skin} options={SKINS} onPick={(v) => set("skin", v)} />
      <Swatches label="Shirt" value={draft.shirt} options={SHIRTS} onPick={(v) => set("shirt", v)} />
      <Swatches label="Pants" value={draft.pants} options={PANTS} onPick={(v) => set("pants", v)} />
      <label className="flex items-center gap-2 text-sm text-ink">
        <input type="checkbox" checked={draft.glasses} onChange={(e) => set("glasses", e.target.checked)} className="size-5" /> Glasses
      </label>
      <div className="flex gap-2">
        <button type="button" disabled={save.isPending || status === "demo" || status === "signin"} onClick={() => save.mutate()}
          className="px-btn rounded-md bg-[#5BF2A5] px-4 py-2 font-bold text-[#0B1A12] disabled:opacity-40">Save</button>
        <button type="button" onClick={() => { setDraft(DEFAULT_PLAYER); usePlay.getState().setLook(DEFAULT_PLAYER); }} className="px-btn rounded-md bg-[#2a2246] px-4 py-2 text-[#f3e9d2]">Reset</button>
      </div>
      {status === "demo" || status === "signin" ? <p className="text-xs text-ink-3">Connect and sign in to keep your character between visits.</p> : null}
      {save.error ? <p className="text-xs text-bad">Couldn&apos;t save. Try again.</p> : null}
    </div>
  );
}
