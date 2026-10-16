"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Portrait } from "@/components/command/Portrait";
import { ApiError, play, type Json } from "@/lib/api";
import { statusLabel } from "@/lib/play/engine";
import { usePlay } from "@/lib/play/state";
import { useStore } from "@/lib/store";

/**
 * RPG dialogue with an agent NPC. Everything the NPC says comes from the backend (POST /api/play/talk), which answers from
 * real records. Requests that would change something come back as an offer with Confirm / Not now; closing the dialogue
 * or walking away leaves it unconfirmed, and it expires.
 */
export function Dialogue() {
  const agentId = usePlay((s) => s.talkingTo);
  const agent = useStore((s) => (agentId ? s.world.agents[agentId] : undefined));
  const status = useStore((s) => s.status);
  const close = () => usePlay.getState().talk(null);
  if (!agentId || !agent) return null;
  return (
    <div className="fixed inset-x-0 bottom-0 z-40 flex justify-center p-2 pb-[max(8px,env(safe-area-inset-bottom))] sm:p-4" role="dialog" aria-label={`Talking to ${agent.name}`}>
      <div className="px-panel flex max-h-[62dvh] w-full max-w-2xl flex-col overflow-hidden">
        <div className="flex items-center gap-3 border-b-2 border-[#f3e9d2]/25 px-3 py-2">
          <Portrait look={agent.look} size={44} fallback={agent.color} name={agent.name} />
          <div className="min-w-0 flex-1">
            <div className="font-pixel text-lg leading-tight text-[#f3e9d2]">{agent.name}</div>
            <div className="truncate text-xs text-ink-2">{agent.role} · <span className="text-ok">{statusLabel(agent)}</span></div>
          </div>
          <button type="button" onClick={close} className="px-btn rounded-md bg-[#2a2246] px-3 py-1 text-sm text-[#f3e9d2]" aria-label="Walk away">
            Walk away
          </button>
        </div>
        {status === "demo" ? (
          <p className="p-4 text-sm text-ink-2">
            This is the demo city: {agent.name} is part of a scripted demo, not your real team. Connect to your Mac in Settings to talk to your agents.
          </p>
        ) : status === "signin" ? (
          <p className="p-4 text-sm text-ink-2">Sign in with Google or GitHub to talk to your agents.</p>
        ) : (
          <Conversation agentId={agentId} />
        )}
      </div>
    </div>
  );
}

function Typewriter({ text, animate }: { text: string; animate: boolean }) {
  const [n, setN] = useState(animate ? 0 : text.length);
  useEffect(() => {
    if (!animate) return;
    setN(0);
    const id = window.setInterval(() => setN((v) => (v >= text.length ? (window.clearInterval(id), v) : v + 2)), 16);
    return () => window.clearInterval(id);
  }, [text, animate]);
  return <span onClick={() => setN(text.length)}>{text.slice(0, n)}</span>;
}

function Conversation({ agentId }: { agentId: string }) {
  const qc = useQueryClient();
  const key = ["play-convo", agentId];
  const q = useQuery({ queryKey: key, queryFn: () => play.conversation(agentId) });
  const [text, setText] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [fresh, setFresh] = useState<string | null>(null);
  const greeted = useRef(false);
  const scroller = useRef<HTMLDivElement>(null);

  const send = useMutation({
    mutationFn: (t: string) => play.talk(agentId, t),
    onSuccess: (r) => {
      setSuggestions(r.suggestions ?? []);
      setFresh(r.message?.id ?? null);
      qc.invalidateQueries({ queryKey: key });
    },
  });

  useEffect(() => {
    if (q.data && !greeted.current) {
      greeted.current = true;
      if (!q.data.messages.length) send.mutate("");
    }
  }, [q.data, send]);

  useEffect(() => {
    // stay pinned to the newest line while the reply types out
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(() => el.scrollTo({ top: el.scrollHeight }));
    Array.from(el.children).forEach((c) => ro.observe(c));
    el.scrollTo({ top: el.scrollHeight });
    return () => ro.disconnect();
  }, [q.data, send.isPending]);

  const messages: Json[] = q.data?.messages ?? [];
  const proposals = q.data?.proposals ?? {};
  const submit = (t: string) => {
    const v = t.trim();
    if (!v || send.isPending) return;
    setText("");
    send.mutate(v);
  };
  const quick = suggestions.length ? suggestions : ["What are you working on?", "What needs my approval?", "Show everything in progress"];

  return (
    <>
      <div ref={scroller} className="scroll-thin min-h-24 flex-1 space-y-2 overflow-y-auto px-3 py-3 text-[15px] leading-snug">
        {q.isLoading ? <p className="text-ink-3">…</p> : null}
        {q.error ? <p className="text-bad">{errorText(q.error)}</p> : null}
        {messages.map((m) => (
          <div key={m.id} className={m.speaker === "owner" ? "flex justify-end" : ""}>
            <div className={m.speaker === "owner" ? "max-w-[85%] rounded-lg bg-[#2a2246] px-3 py-1.5 text-ink" : "max-w-[95%] text-[#f3e9d2]"}>
              {m.speaker === "npc" ? <Typewriter text={m.text} animate={m.id === fresh} /> : m.text}
              {m.proposal_id && proposals[m.proposal_id] ? <Offer p={proposals[m.proposal_id]} agentId={agentId} /> : null}
            </div>
          </div>
        ))}
        {send.isPending ? <p className="font-pixel text-[#f3e9d2]/60">▍</p> : null}
        {send.error ? <p className="text-sm text-bad">{errorText(send.error)}</p> : null}
      </div>
      <div className="flex gap-1.5 overflow-x-auto px-3 pb-2 scroll-thin">
        {quick.map((s) => (
          <button key={s} type="button" onClick={() => submit(s)} className="shrink-0 rounded-full border border-[#f3e9d2]/30 px-3 py-1 text-xs text-[#f3e9d2] hover:bg-white/5">
            {s}
          </button>
        ))}
      </div>
      <form className="flex gap-2 border-t-2 border-[#f3e9d2]/25 p-2" onSubmit={(e) => { e.preventDefault(); submit(text); }}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={2000}
          placeholder="Ask, or give a request…"
          aria-label="Message"
          className="min-w-0 flex-1 rounded-md border border-[#f3e9d2]/30 bg-[#0f0c1f] px-3 py-2 text-[16px] text-ink placeholder:text-ink-3"
        />
        <button type="submit" disabled={!text.trim() || send.isPending} className="px-btn rounded-md bg-[#5BF2A5] px-4 text-sm font-bold text-[#0B1A12] disabled:opacity-40">
          Say
        </button>
      </form>
    </>
  );
}

function Offer({ p, agentId }: { p: Json; agentId: string }) {
  const qc = useQueryClient();
  const done = () => {
    qc.invalidateQueries({ queryKey: ["play-convo", agentId] });
    qc.invalidateQueries({ queryKey: ["snapshot"] });
  };
  const yes = useMutation({ mutationFn: () => play.confirm(p.id), onSettled: done });
  const no = useMutation({ mutationFn: () => play.decline(p.id), onSettled: done });
  const busy = yes.isPending || no.isPending;
  return (
    <div className="mt-2 rounded-md border-2 border-[#F4D58D]/70 bg-[#F4D58D]/10 p-2 text-sm text-ink">
      <div className="font-pixel text-xs uppercase tracking-wide text-[#F4D58D]">Request</div>
      <p className="mt-0.5">{p.summary}</p>
      {p.status === "PENDING" ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button type="button" disabled={busy} onClick={() => yes.mutate()} className="px-btn rounded-md bg-[#5BF2A5] px-3 py-1 font-bold text-[#0B1A12] disabled:opacity-40">
            Confirm
          </button>
          <button type="button" disabled={busy} onClick={() => no.mutate()} className="px-btn rounded-md bg-[#2a2246] px-3 py-1 text-[#f3e9d2] disabled:opacity-40">
            Not now
          </button>
          <span className="text-[11px] text-ink-3">Nothing starts until you confirm.</span>
        </div>
      ) : (
        <p className="mt-1 text-xs text-ink-2">
          {{ CONFIRMED: "Confirmed", DECLINED: "Declined", EXPIRED: "Expired (ask again to redo)", FAILED: "Couldn't start" }[p.status as string] ?? p.status}
        </p>
      )}
      {yes.error ? <p className="mt-1 text-xs text-bad">{errorText(yes.error)}</p> : null}
    </div>
  );
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Your account can't do that. The owner, an admin or an operator can.";
    if (e.status === 401) return "Sign in to talk to your agents.";
    return e.message;
  }
  return "Couldn't reach your server.";
}
