"use client";

import type { EventEnvelope } from "@aiciv/event-contracts";

const KEY = "aiciv.connection";

export interface Connection {
  apiUrl: string;
  token: string;
}

export function loadConnection(): Connection {
  const fallback = { apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000", token: "" };
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

export function saveConnection(c: Connection): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(c));
  } catch {
    /* storage unavailable (private mode): connection lasts for this session only */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { apiUrl, token } = loadConnection();
  const res = await fetch(apiUrl.replace(/\/$/, "") + path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export function streamUrl(after: number): string {
  const { apiUrl, token } = loadConnection();
  const q = new URLSearchParams({ after: String(after) });
  if (token) q.set("access_token", token);
  return `${apiUrl.replace(/\/$/, "")}/api/stream?${q}`;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
export type Json = Record<string, any>;

export const api = {
  health: () => call<Json>("/api/health"),
  snapshot: () => call<Json>("/api/snapshot"),
  events: (after: number) => call<{ events: EventEnvelope[] }>(`/api/events?after=${after}`),
  mission: (id: string) => call<Json>(`/api/missions/${id}`),
  createMission: (prompt: string, budget_usd?: number) =>
    call<Json>("/api/missions", {
      method: "POST",
      body: JSON.stringify({ prompt, budget_usd, idempotency_key: crypto.randomUUID() }),
    }),
  cancel: (id: string) => call<Json>(`/api/missions/${id}/cancel`, { method: "POST" }),
  pause: (id: string) => call<Json>(`/api/missions/${id}/pause`, { method: "POST" }),
  resume: (id: string) => call<Json>(`/api/missions/${id}/resume`, { method: "POST" }),
  grant: (id: string) => call<Json>(`/api/approvals/${id}/grant`, { method: "POST" }),
  reject: (id: string) => call<Json>(`/api/approvals/${id}/reject`, { method: "POST" }),
  artifact: (id: string) => call<Json>(`/api/artifacts/${id}`),
  agent: (id: string) => call<Json>(`/api/agents/${id}`),
  costs: () => call<Json>("/api/costs"),
  memory: (q = "") => call<{ entries: Json[] }>(`/api/memory?q=${encodeURIComponent(q)}`),
  emergencyStop: (engaged: boolean) => call<Json>("/api/emergency-stop", { method: "POST", body: JSON.stringify({ engaged }) }),
};
