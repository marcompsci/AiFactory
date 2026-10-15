"use client";

import type { EventEnvelope } from "@aiciv/event-contracts";

const KEY = "aiciv.connection";

export interface Connection {
  apiUrl: string;
  token: string;
  /** Set by the iPhone app, which signs in natively and hands its session to the city view. */
  native?: boolean;
}

const LOCAL = /^(localhost|127\.0\.0\.1|\[::1\])$/;

/** Opened from another device (a phone on your Wi-Fi), "localhost" would mean that device: use this page's host instead. */
function reachable(apiUrl: string): string {
  try {
    const u = new URL(apiUrl);
    const page = typeof window !== "undefined" ? window.location : null;
    if (page && LOCAL.test(u.hostname) && !LOCAL.test(page.hostname)) {
      u.hostname = page.hostname;
      return u.toString().replace(/\/$/, "");
    }
  } catch {
    /* not a URL; leave it */
  }
  return apiUrl;
}

export function loadConnection(): Connection {
  const fallback = { apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000", token: "" };
  try {
    const raw = localStorage.getItem(KEY);
    const c = raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
    return { ...c, apiUrl: reachable(c.apiUrl) };
  } catch {
    return { ...fallback, apiUrl: reachable(fallback.apiUrl) };
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
  research: (source: string, query: string, region = "US") =>
    call<Json>("/api/research", { method: "POST", body: JSON.stringify({ source, query, region }) }),
  opportunities: () => call<{ opportunities: Json[] }>("/api/opportunities"),
  opportunity: (id: string) => call<Json>(`/api/opportunities/${id}`),
  ownerDecision: (id: string, decision: string, artifact_digest: string, note?: string) =>
    call<Json>(`/api/opportunities/${id}/owner-decision`, { method: "POST", body: JSON.stringify({ decision, artifact_digest, note }) }),
  ownerCommit: (id: string, approve: boolean) => call<Json>(`/api/opportunities/${id}/owner-commit`, { method: "POST", body: JSON.stringify({ approve }) }),
  reopen: (id: string) => call<Json>(`/api/opportunities/${id}/reopen`, { method: "POST" }),
  hierarchy: () => call<Json>("/api/hierarchy"),
  logistics: () => call<Json>("/api/logistics"),
  routeStatus: (id: string, status: "UP" | "DOWN") =>
    call<Json>(`/api/logistics/routes/${encodeURIComponent(id)}/status`, { method: "POST", body: JSON.stringify({ status }) }),
  /** Fetches a bundle file with the caller's credentials (iframes can't send headers). */
  bundleFile: async (artifactId: string, path: string): Promise<string> => {
    const { apiUrl, token } = loadConnection();
    const r = await fetch(`${apiUrl.replace(/\/$/, "")}/api/artifacts/${artifactId}/files/${path}`, { headers: token ? { authorization: `Bearer ${token}` } : {} });
    if (!r.ok) throw new ApiError(r.status, "preview unavailable");
    return r.text();
  },
  bundleDownload: async (artifactId: string): Promise<Blob> => {
    const { apiUrl, token } = loadConnection();
    const r = await fetch(`${apiUrl.replace(/\/$/, "")}/api/artifacts/${artifactId}/download`, { headers: token ? { authorization: `Bearer ${token}` } : {} });
    if (!r.ok) throw new ApiError(r.status, "download failed");
    return r.blob();
  },
  overview: () => call<Json>("/api/overview"),
  emergencyStop: (engaged: boolean) => call<Json>("/api/emergency-stop", { method: "POST", body: JSON.stringify({ engaged }) }),
};

/** V5 AI Central Bank. Approving needs a step-up token (X-Step-Up) from `stepUpVerify`. */
const post = (body?: unknown, stepUp?: string): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
  headers: stepUp ? { "x-step-up": stepUp } : {},
});

export const bank = {
  dashboard: () => call<Json>("/api/finance/dashboard"),
  packets: () => call<{ packets: Json[] }>("/api/finance/packets"),
  packet: (id: string) => call<Json>(`/api/finance/packets/${id}`),
  approvals: (status?: string) => call<{ approvals: Json[] }>(`/api/finance/approvals${status ? `?status=${status}` : ""}`),
  decide: (id: string, body: { decision: string; approval_id?: string; payload_hash?: string; note?: string; defer_days?: number }, stepUp?: string) =>
    call<Json>(`/api/finance/packets/${id}/decide`, post(body, stepUp)),
  decideApproval: (id: string, body: { decision: string; payload_hash: string; note?: string }, stepUp?: string) =>
    call<Json>(`/api/finance/approvals/${id}/decide`, post(body, stepUp)),
  complete: (id: string, stepUp: string) => call<Json>(`/api/finance/approvals/${id}/complete`, post(undefined, stepUp)),
  reopen: (id: string) => call<Json>(`/api/finance/packets/${id}/reopen`, post()),
  toolRequest: (body: { vendor: string; item: string; amount: number; interval: string; justification: string }) =>
    call<Json>("/api/finance/tool-requests", post(body)),
  stepUpStatus: () => call<Json>("/api/finance/stepup"),
  stepUpEnroll: () => call<Json>("/api/finance/stepup/enroll", post()),
  stepUpVerify: (code: string, purpose: string) => call<{ step_up_token: string }>("/api/finance/stepup/verify", post({ code, purpose })),
  loadSimulated: () => call<Json>("/api/finance/simulated", post()),
  providers: () => call<{ providers: Json[] }>("/api/finance/providers"),
  connections: () => call<Json>("/api/finance/connections"),
  createConnection: (provider: string) => call<Json>("/api/finance/connections", post({ provider })),
  authorize: (id: string, credential: string | null, stepUp?: string) =>
    call<Json>(`/api/finance/connections/${id}/authorize`, post({ credential, confirm_read_only: true }, stepUp)),
  sync: (id: string) => call<Json>(`/api/finance/connections/${id}/sync`, post()),
  upload: (id: string, file: Blob) => call<Json>(`/api/finance/connections/${id}/upload`, { method: "PUT", body: file, headers: { "content-type": "text/csv" } }),
  revoke: (id: string) => call<Json>(`/api/finance/connections/${id}/revoke`, post()),
  tax: () => call<Json>("/api/finance/tax"),
  taxEstimate: () => call<Json>("/api/finance/tax/estimate", post({})),
  taxFile: () => call<Json>("/api/finance/tax/file", post()),
  taxExport: async (year: number, stepUp: string): Promise<Blob> => {
    const { apiUrl, token } = loadConnection();
    const r = await fetch(`${apiUrl.replace(/\/$/, "")}/api/finance/tax/export?tax_year=${year}`, {
      headers: { "x-step-up": stepUp, ...(token ? { authorization: `Bearer ${token}` } : {}) },
    });
    if (!r.ok) throw new ApiError(r.status, "export refused");
    return r.blob();
  },
  audit: () => call<Json>("/api/finance/audit?limit=50"),
  investigations: () => call<{ investigations: Json[] }>("/api/finance/investigations"),
  investigation: (id: string) => call<Json>(`/api/finance/investigations/${id}`),
  cancelInvestigation: (id: string) => call<Json>(`/api/finance/investigations/${id}/cancel`, post()),
};

/** App Lab: research-driven, owner-gated improvements to the owner's GitHub repositories. */
export const lab = {
  overview: () => call<Json>("/api/applab"),
  connect: (body: { full_name: string; default_branch?: string; auth_mode: string; token?: string }, stepUp?: string) =>
    call<Json>("/api/applab/repositories", post(body, stepUp)),
  revoke: (id: string) => call<Json>(`/api/applab/repositories/${id}/revoke`, post()),
  autopilot: (id: string, enabled: boolean) => call<Json>(`/api/applab/repositories/${id}/autopilot`, post({ enabled })),
  startCycle: (id: string) => call<Json>(`/api/applab/repositories/${id}/cycles`, post()),
  cycle: (id: string) => call<Json>(`/api/applab/cycles/${id}`),
  cancelCycle: (id: string) => call<Json>(`/api/applab/cycles/${id}/cancel`, post()),
  proposal: (id: string) => call<Json>(`/api/applab/proposals/${id}`),
  decide: (id: string, body: { decision: "APPROVE" | "REJECT" | "DEFER"; payload_hash: string; note?: string }, stepUp?: string) =>
    call<Json>(`/api/applab/proposals/${id}/decide`, post(body, stepUp)),
};

/** The money game: agents compete on verified money only. */
export const game = {
  board: (season?: string) => call<Json>(`/api/game${season ? `?season=${season}` : ""}`),
  link: (merchant: string, opportunity_id: string) => call<Json>("/api/game/revenue-links", post({ merchant, opportunity_id })),
  unlink: (id: string) => call<Json>(`/api/game/revenue-links/${id}/deactivate`, post()),
};

/** Claude Code and GitHub factories (owner/admin; read-only). */
export const factories = {
  get: () => call<Json>("/api/factories"),
  link: (kind: "claude_code" | "github" | "codex", enabled: boolean) => call<Json>(`/api/factories/${kind}/link`, post({ enabled })),
  sync: () => call<Json>("/api/factories/sync", post()),
  usage: () => call<Json>("/api/factories/usage"),
  usageSettings: (body: Json) => call<Json>("/api/factories/usage/settings", { method: "PUT", body: JSON.stringify(body) }),
};

/** Company knowledge base: Phoronomics and Phoronomic Studios docs and skills. Members read; owner/admin edit. */
export const knowledge = {
  list: (q = "", company = "", kind = "") =>
    call<Json>(`/api/knowledge?${new URLSearchParams({ ...(q ? { q } : {}), ...(company ? { company } : {}), ...(kind ? { kind } : {}) })}`),
  get: (slug: string) => call<Json>(`/api/knowledge/${encodeURIComponent(slug)}`),
  create: (doc: Json) => call<Json>("/api/knowledge", post(doc)),
  update: (slug: string, doc: Json) => call<Json>(`/api/knowledge/${encodeURIComponent(slug)}`, { method: "PUT", body: JSON.stringify(doc) }),
  remove: (slug: string) => call<Json>(`/api/knowledge/${encodeURIComponent(slug)}`, { method: "DELETE" }),
  upload: (file: File, company: string) =>
    file.text().then((text) =>
      call<Json>(`/api/knowledge/upload?${new URLSearchParams({ filename: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name, company })}`,
        { method: "PUT", body: text, headers: { "content-type": "text/markdown" } })),
};
