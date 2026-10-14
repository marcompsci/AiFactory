"use client";

import { validateEnvelope, type EventEnvelope } from "@aiciv/event-contracts";
import { demoScript } from "@aiciv/world-engine";
import { SEED } from "@aiciv/shared-types";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api, streamUrl } from "@/lib/api";
import { useStore } from "@/lib/store";

/**
 * Connection lifecycle:
 *   1. GET /api/snapshot  → hydrate world at sequence N (authoritative state)
 *   2. SSE /api/stream?after=N → live envelopes (schema-validated, deduped, ordered)
 *   3. gaps → GET /api/events?after=<last> replay;  disconnect → snapshot again on reconnect
 * If the API cannot be reached at all, the app runs a clearly labeled client-side demo.
 */
export function useRealtime(reconnectKey: number) {
  const qc = useQueryClient();
  const timers = useRef<number[]>([]);

  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;
    let retry = 0;
    const store = useStore.getState;

    const invalidateFor = (events: EventEnvelope[]) => {
      const missions = new Set(events.map((e) => e.mission_id).filter(Boolean) as string[]);
      if (events.some((e) => e.event_type.startsWith("mission.") || e.event_type.startsWith("approval.")))
        qc.invalidateQueries({ queryKey: ["snapshot"] });
      for (const m of missions) qc.invalidateQueries({ queryKey: ["mission", m] });
      if (events.some((e) => e.event_type === "usage.recorded")) qc.invalidateQueries({ queryKey: ["costs"] });
      if (events.some((e) => e.agent_id)) qc.invalidateQueries({ queryKey: ["agent"] });
    };

    const replay = async () => {
      try {
        const { events } = await api.events(store().world.lastSequence);
        store().ingest(events);
        store().replayDone();
      } catch {
        /* next reconnect re-hydrates from the snapshot */
      }
    };

    const connect = async () => {
      store().setStatus(retry ? "reconnecting" : "connecting");
      let snap;
      try {
        snap = await api.snapshot();
      } catch (err) {
        if (retry === 0) return startDemo(String(err));
        scheduleReconnect();
        return;
      }
      if (closed) return;
      store().hydrate(snap.agents, snap.sequence, snap.execution_mode, snap.approvals.map((a: { id: string }) => a.id));
      qc.setQueryData(["snapshot"], snap);
      // History for the activity feed only; the world itself is already at snap.sequence.
      api.events(Math.max(0, snap.sequence - 200)).then((h) => store().seedFeed(h.events)).catch(() => {});
      es = new EventSource(streamUrl(snap.sequence));
      es.addEventListener("ready", () => {
        retry = 0;
        store().setStatus("live");
      });
      es.addEventListener("envelope", (msg) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse((msg as MessageEvent).data);
        } catch {
          return;
        }
        const v = validateEnvelope(parsed);
        if (!v.ok) {
          console.warn("dropped invalid envelope:", v.error);
          return;
        }
        store().ingest([v.event]);
        if (store().needsReplay) void replay();
        invalidateFor([v.event]);
      });
      es.onerror = () => {
        es?.close();
        if (!closed) scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      retry += 1;
      store().setStatus("reconnecting", `retry ${retry}`);
      const delay = Math.min(15000, 500 * 2 ** Math.min(retry, 5));
      timers.current.push(window.setTimeout(() => !closed && void connect(), delay));
    };

    const startDemo = (why: string) => {
      store().setStatus("demo", why);
      const ids = Object.fromEntries(SEED.agents.map((a) => [a.key, a.id])) as Record<string, string>;
      const approvalId = crypto.randomUUID();
      const script = demoScript(
        { commander: ids.commander, architect: ids.architect, developer: ids.developer, qa: ids.qa, researcher: ids.researcher },
        SEED.organization_id,
        store().world.lastSequence,
        approvalId,
      );
      const play = (steps: { delay: number; event: EventEnvelope }[], then?: () => void) => {
        let t = 800;
        for (const s of steps) {
          t += s.delay;
          timers.current.push(window.setTimeout(() => !closed && store().ingest([{ ...s.event, occurred_at: new Date().toISOString() }]), t));
        }
        if (then) timers.current.push(window.setTimeout(() => !closed && then(), t + 50));
      };
      play(script.beforeApproval, () =>
        store().setDemoApproval({ id: approvalId, summary: "Commit the verified fix and publish the patch." }),
      );
      (window as unknown as { __aicivDemoDecide?: (d: "granted" | "rejected") => void }).__aicivDemoDecide = (d) => {
        store().setDemoApproval(null);
        play(script.afterApproval(d));
      };
    };

    void connect();
    return () => {
      closed = true;
      es?.close();
      timers.current.forEach((t) => clearTimeout(t));
      timers.current = [];
    };
  }, [qc, reconnectKey]);
}

export function decideDemoApproval(decision: "granted" | "rejected") {
  (window as unknown as { __aicivDemoDecide?: (d: "granted" | "rejected") => void }).__aicivDemoDecide?.(decision);
}
