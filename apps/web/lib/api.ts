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
    if (res.status === 401 && (detail === "token expired" || detail === "invalid token")) {
      // a stale or broken saved session: stop sending it (the sign-in library refreshes a live session on its own)
      const c = loadConnection();
      if (c.token && !c.native) saveConnection({ ...c, token: "" });
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
  failures: (days = 30) => call<Json>(`/api/insights/failures?days=${days}`),
  lessons: () => call<Json>("/api/insights/lessons"),
  trace: (id: string) => call<Json>(`/api/insights/missions/${id}/trace`),
  recoveryDecide: (id: string, approve: boolean) => call<Json>(`/api/recovery/${id}/${approve ? "approve" : "decline"}`, { method: "POST" }),
  charter: () => call<Json>("/api/charter"),
  brief: () => call<Json>("/api/insights/brief"),
  scorecards: (weeks = 4) => call<Json>(`/api/insights/scorecards?weeks=${weeks}`),
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

/** V6 playable town: avatar state, NPC conversations, and proposals that run only on Confirm. */
export const play = {
  state: () => call<Json>("/api/play/state"),
  save: (body: Json) => call<Json>("/api/play/state", { method: "PUT", body: JSON.stringify(body) }),
  conversation: (agentId: string) => call<{ messages: Json[]; proposals: Record<string, Json> }>(`/api/play/conversations/${agentId}`),
  talk: (agent_id: string, text: string) =>
    call<Json>("/api/play/talk", post({ agent_id, text, tz: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" })),
  confirm: (id: string) => call<Json>(`/api/play/proposals/${id}/confirm`, post()),
  decline: (id: string) => call<Json>(`/api/play/proposals/${id}/decline`, post()),
};

/** V6.43–V6.49 your task list: quick capture, "do it for me", review, today. */
const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
export const myTasks = {
  list: () => call<{ tasks: Json[] }>("/api/my-tasks"),
  get: (id: string) => call<Json>(`/api/my-tasks/${id}`),
  today: () => call<Json>(`/api/my-tasks/today?tz=${encodeURIComponent(tz())}`),
  preview: (text: string) => call<Json>(`/api/my-tasks/parse?${new URLSearchParams({ text, tz: tz() })}`),
  add: (text: string) => call<Json>("/api/my-tasks", post({ text, tz: tz() })),
  edit: (id: string, fields: Json) => call<Json>(`/api/my-tasks/${id}`, { method: "PATCH", body: JSON.stringify(fields) }),
  doIt: (id: string) => call<Json>(`/api/my-tasks/${id}/do`, post()),
  redo: (id: string, note: string) => call<Json>(`/api/my-tasks/${id}/redo`, post({ note })),
  done: (id: string) => call<Json>(`/api/my-tasks/${id}/done`, post({ tz: tz() })),
  reopen: (id: string) => call<Json>(`/api/my-tasks/${id}/reopen`, post()),
  drop: (id: string) => call<Json>(`/api/my-tasks/${id}/drop`, post()),
  remove: (id: string) => call<Json>(`/api/my-tasks/${id}`, { method: "DELETE" }),
  // V6.68–V6.87
  addItems: (id: string, texts: string[]) => call<Json>(`/api/my-tasks/${id}/items`, post({ texts })),
  setItem: (id: string, item: string, fields: Json) => call<Json>(`/api/my-tasks/${id}/items/${item}`, { method: "PATCH", body: JSON.stringify(fields) }),
  removeItem: (id: string, item: string) => call<Json>(`/api/my-tasks/${id}/items/${item}`, { method: "DELETE" }),
  snooze: (id: string, preset: string) => call<Json>(`/api/my-tasks/${id}/snooze`, post({ preset, tz: tz() })),
  saveTemplate: (id: string, name: string) => call<Json>(`/api/my-tasks/${id}/template`, post({ name })),
  templates: () => call<{ templates: Json[] }>("/api/my-tasks/templates"),
  useTemplate: (tmpl: string) => call<Json>(`/api/my-tasks/templates/${tmpl}/use`, post({})),
  deleteTemplate: (tmpl: string) => call<Json>(`/api/my-tasks/templates/${tmpl}`, { method: "DELETE" }),
  plan: (start = "09:00", end = "18:00") => call<Json>(`/api/my-tasks/plan?${new URLSearchParams({ tz: tz(), start, end })}`),
  review: () => call<Json>(`/api/my-tasks/review?tz=${encodeURIComponent(tz())}`),
  bulk: (ids: string[], action: string) => call<Json>("/api/my-tasks/bulk", post({ ids, action, tz: tz() })),
  results: (q: string) => call<{ results: Json[] }>(`/api/my-tasks/results?${new URLSearchParams(q.trim() ? { q: q.trim() } : {})}`),
  insights: (days = 14) => call<Json>(`/api/insights/tasks?${new URLSearchParams({ tz: tz(), days: String(days) })}`),
  agentQuality: () => call<{ agents: Json[] }>("/api/insights/agent-quality"),
  estimate: (id: string) => call<Json>(`/api/my-tasks/${id}/estimate`),
  feedback: (id: string, rating: number, reason?: string) => call<Json>(`/api/my-tasks/${id}/feedback`, post({ rating, reason: reason || null })),
  // V6.113–V6.127 money (records what you type in; moves nothing)
  moneyOverview: () => call<Json>(`/api/money/overview?tz=${encodeURIComponent(tz())}`),
  income: () => call<Json>(`/api/money/income?tz=${encodeURIComponent(tz())}`),
  logIncome: (amount: number, source: string, hours?: number) => call<Json>("/api/money/income", post({ amount, source, hours: hours ?? null, tz: tz() })),
  removeIncome: (id: string) => call<Json>(`/api/money/income/${id}`, { method: "DELETE" }),
  pay: () => call<{ schedules: Json[] }>(`/api/money/pay?tz=${encodeURIComponent(tz())}`),
  addPay: (fields: Json) => call<Json>("/api/money/pay", post(fields)),
  removePay: (id: string) => call<Json>(`/api/money/pay/${id}`, { method: "DELETE" }),
  planner: () => call<Json>(`/api/money/planner?tz=${encodeURIComponent(tz())}`),
  budget: () => call<Json>(`/api/money/budget?tz=${encodeURIComponent(tz())}`),
  savings: () => call<{ goals: Json[] }>(`/api/money/savings?tz=${encodeURIComponent(tz())}`),
  addSavings: (fields: Json) => call<Json>("/api/money/savings", post({ ...fields, tz: tz() })),
  deposit: (id: string, amount: number) => call<Json>(`/api/money/savings/${id}/deposits`, post({ amount, tz: tz() })),
  removeSavings: (id: string) => call<Json>(`/api/money/savings/${id}`, { method: "DELETE" }),
  subscriptions: () => call<Json>(`/api/money/subscriptions?tz=${encodeURIComponent(tz())}`),
  setSubscription: (bill: string, fields: Json) => call<Json>(`/api/money/bills/${bill}/subscription?tz=${encodeURIComponent(tz())}`, post(fields)),
  findSavings: (bill: string) => call<Json>(`/api/money/bills/${bill}/find-savings?tz=${encodeURIComponent(tz())}`, post()),
  credit: () => call<Json>(`/api/money/credit?tz=${encodeURIComponent(tz())}`),
  addCard: (fields: Json) => call<Json>("/api/money/credit/cards", post(fields)),
  editCard: (id: string, fields: Json) => call<Json>(`/api/money/credit/cards/${id}`, { method: "PATCH", body: JSON.stringify(fields) }),
  removeCard: (id: string) => call<Json>(`/api/money/credit/cards/${id}`, { method: "DELETE" }),
  // V6.128–V6.157 money, round 2 (records what you type in; moves nothing)
  spending: () => call<Json>(`/api/money/spending?tz=${encodeURIComponent(tz())}`),
  logExpense: (amount: number, category: string) => call<Json>("/api/money/spending", post({ amount, category, tz: tz() })),
  removeExpense: (id: string) => call<Json>(`/api/money/spending/${id}`, { method: "DELETE" }),
  setLimit: (category: string, limit: number | null) => call<Json>("/api/money/spending/limits", { method: "PUT", body: JSON.stringify({ category, limit }) }),
  accounts: () => call<{ accounts: Json[] }>("/api/money/accounts"),
  addAccount: (name: string, kind: string, balance: number | null) => call<Json>("/api/money/accounts", post({ name, kind, balance, tz: tz() })),
  checkIn: (id: string, balance: number) => call<Json>(`/api/money/accounts/${id}/balance`, post({ balance, tz: tz() })),
  removeAccount: (id: string) => call<Json>(`/api/money/accounts/${id}`, { method: "DELETE" }),
  safeToSpend: () => call<Json>(`/api/money/safe-to-spend?tz=${encodeURIComponent(tz())}`),
  paycheckSplit: () => call<Json>(`/api/money/paycheck-split?tz=${encodeURIComponent(tz())}`),
  debts: (extra: number) => call<Json>(`/api/money/debts?${new URLSearchParams({ tz: tz(), extra: String(extra) })}`),
  addDebt: (fields: Json) => call<Json>("/api/money/debts", post(fields)),
  removeDebt: (id: string) => call<Json>(`/api/money/debts/${id}`, { method: "DELETE" }),
  paydown: () => call<Json>(`/api/money/paydown?tz=${encodeURIComponent(tz())}`),
  billChecks: () => call<Json>(`/api/money/bill-checks?tz=${encodeURIComponent(tz())}`),
  gigs: () => call<Json>(`/api/money/gigs?tz=${encodeURIComponent(tz())}`),
  cashback: () => call<Json>(`/api/money/cashback?tz=${encodeURIComponent(tz())}`),
  logCashback: (card: string, amount: number) => call<Json>("/api/money/cashback", post({ card, amount, tz: tz() })),
  checklist: () => call<Json>("/api/money/checklist"),
  checkItem: (key: string, done: boolean) => call<Json>(`/api/money/checklist/${key}`, { method: "PUT", body: JSON.stringify({ done }) }),
  emergency: () => call<Json>(`/api/money/emergency?tz=${encodeURIComponent(tz())}`),
  netWorth: () => call<Json>(`/api/money/net-worth?tz=${encodeURIComponent(tz())}`),
  snapshotNetWorth: () => call<Json>(`/api/money/net-worth/snapshot?tz=${encodeURIComponent(tz())}`, post()),
  moneyReview: () => call<Json>(`/api/money/review?tz=${encodeURIComponent(tz())}`),
  // V6.158–V6.187 money, round 3
  parseBill: (text: string) => call<Json>("/api/money/bills/parse", post({ text, tz: tz() })),
  forecast: () => call<Json>(`/api/money/forecast?tz=${encodeURIComponent(tz())}`),
  moneyTodos: () => call<Json>(`/api/money/todos?tz=${encodeURIComponent(tz())}`),
  afford: (amount: number) => call<Json>(`/api/money/afford?${new URLSearchParams({ amount: String(amount), tz: tz() })}`),
  creditWatch: () => call<Json>(`/api/money/credit-watch?tz=${encodeURIComponent(tz())}`),
  markBureau: (kind: string, bureau: string, on: boolean) => call<Json>(`/api/money/credit-watch/${kind}/${bureau}`, { method: "PUT", body: JSON.stringify({ on }) }),
  addDispute: (bureau: string, item: string) => call<Json>("/api/money/disputes", post({ bureau, item, tz: tz() })),
  updateDispute: (id: string, status: string) => call<Json>(`/api/money/disputes/${id}`, { method: "PATCH", body: JSON.stringify({ status, tz: tz() }) }),
  incomeGoal: () => call<Json>(`/api/money/income-goal?tz=${encodeURIComponent(tz())}`),
  setIncomeGoal: (monthly: number | null) => call<Json>("/api/money/income-goal", { method: "PUT", body: JSON.stringify({ monthly }) }),
  bestDays: () => call<Json>(`/api/money/best-days?tz=${encodeURIComponent(tz())}`),
  wins: () => call<Json>(`/api/money/wins?tz=${encodeURIComponent(tz())}`),
  addWin: (title: string, amount: number, monthly: boolean) => call<Json>("/api/money/wins", post({ title, amount, monthly, tz: tz() })),
  owed: () => call<Json>(`/api/money/owed?tz=${encodeURIComponent(tz())}`),
  addOwed: (who: string, amount: number) => call<Json>("/api/money/owed", post({ who, amount })),
  markOwed: (id: string, received: boolean) => call<Json>(`/api/money/owed/${id}/received`, { method: "PUT", body: JSON.stringify({ received, tz: tz() }) }),
  selling: () => call<Json>(`/api/money/selling?tz=${encodeURIComponent(tz())}`),
  setAsides: () => call<Json>(`/api/money/set-asides?tz=${encodeURIComponent(tz())}`),
  setAsideGoal: (bill: string) => call<Json>(`/api/money/set-asides/${bill}/goal`, post({ tz: tz() })),
  noSpend: () => call<Json>(`/api/money/no-spend?tz=${encodeURIComponent(tz())}`),
  setNoSpend: (on: boolean) => call<Json>("/api/money/no-spend", { method: "PUT", body: JSON.stringify({ on, tz: tz() }) }),
  roundUps: () => call<Json>(`/api/money/round-ups?tz=${encodeURIComponent(tz())}`),
  moneySetup: () => call<Json>(`/api/money/setup?tz=${encodeURIComponent(tz())}`),
  dueDateMoves: () => call<Json>(`/api/money/due-date-moves?tz=${encodeURIComponent(tz())}`),
  moneyExport: () => call<Json>("/api/money/export"),
  calendarFile: async () => {
    const { apiUrl, token } = loadConnection();
    const res = await fetch(apiUrl.replace(/\/$/, "") + `/api/money/calendar.ics?tz=${encodeURIComponent(tz())}`,
      { headers: token ? { authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new Error(`Calendar failed (${res.status})`);
    return res.blob();
  },
  // V6.98–V6.112
  dump: (text: string, format = "lines", dryRun = true) => call<Json>("/api/my-tasks/dump", post({ text, format, tz: tz(), dry_run: dryRun })),
  promote: (id: string, item: string) => call<Json>(`/api/my-tasks/${id}/items/${item}/promote`, post()),
  month: (year: number, month: number) => call<Json>(`/api/my-tasks/month?${new URLSearchParams({ year: String(year), month: String(month), tz: tz() })}`),
  fit: (minutes: number) => call<Json>(`/api/my-tasks/fit?${new URLSearchParams({ minutes: String(minutes), tz: tz() })}`),
  shutdown: () => call<Json>(`/api/my-tasks/shutdown?tz=${encodeURIComponent(tz())}`),
  closeDay: (move: boolean, note: string) => call<Json>("/api/my-tasks/shutdown", post({ tz: tz(), move, note })),
  archive: (q: string) => call<{ tasks: Json[] }>(`/api/my-tasks/archive?${new URLSearchParams({ q })}`),
  exportFile: async (format: "json" | "csv") => {
    const { apiUrl, token } = loadConnection();
    const res = await fetch(apiUrl.replace(/\/$/, "") + `/api/my-tasks/export?format=${format}`,
      { headers: token ? { authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new Error(`Export failed (${res.status})`);
    return res.blob();
  },
  waiting: (id: string, person: string | null, followUpAt: string | null) =>
    call<Json>(`/api/my-tasks/${id}/waiting`, post({ person, follow_up_at: followUpAt })),
  linkGoal: (id: string, goalId: string | null) => call<Json>(`/api/my-tasks/${id}/goal`, post({ goal_id: goalId, tz: tz() })),
  goals: () => call<Json>(`/api/goals?tz=${encodeURIComponent(tz())}`),
  addGoal: (text: string) => call<Json>("/api/goals", post({ text, tz: tz() })),
  setGoal: (id: string, done: boolean) => call<Json>(`/api/goals/${id}`, { method: "PATCH", body: JSON.stringify({ done, tz: tz() }) }),
  removeGoal: (id: string) => call<Json>(`/api/goals/${id}?tz=${encodeURIComponent(tz())}`, { method: "DELETE" }),
  bills: () => call<{ bills: Json[] }>(`/api/bills?tz=${encodeURIComponent(tz())}`),
  billSummary: () => call<Json>(`/api/bills/summary?tz=${encodeURIComponent(tz())}`),
  addBill: (fields: Json) => call<Json>("/api/bills", post({ ...fields, tz: tz() })),
  removeBill: (id: string) => call<Json>(`/api/bills/${id}`, { method: "DELETE" }),
  billPaid: (id: string) => call<Json>(`/api/bills/${id}/paid`, post({ tz: tz() })),
  billUnpaid: (id: string, period: string) => call<Json>(`/api/bills/${id}/paid/${period}?tz=${encodeURIComponent(tz())}`, { method: "DELETE" }),
  styles: () => call<{ styles: Record<string, { color: string; icon: string }>; icons: string[] }>("/api/lists/styles"),
  setStyle: (name: string, color: string | null, icon: string | null) =>
    call<{ styles: Record<string, { color: string; icon: string }> }>(`/api/lists/${encodeURIComponent(name)}/style`, { method: "PUT", body: JSON.stringify({ color, icon }) }),
  // V6.88–V6.97
  search: (q: string) => call<{ tasks: Json[] }>(`/api/my-tasks?${new URLSearchParams({ q })}`),
  undoDone: (id: string) => call<Json>(`/api/my-tasks/${id}/undo-done`, post()),
  history: (id: string) => call<{ history: Json[] }>(`/api/my-tasks/${id}/history`),
  addLink: (id: string, url: string) => call<{ links: Json[] }>(`/api/my-tasks/${id}/links`, post({ url })),
  removeLink: (id: string, lid: string) => call<{ links: Json[] }>(`/api/my-tasks/${id}/links/${lid}`, { method: "DELETE" }),
  habits: () => call<{ habits: Json[] }>(`/api/my-tasks/habits?tz=${encodeURIComponent(tz())}`),
  digest: (day = "today") => call<Json>(`/api/my-tasks/digest?${new URLSearchParams({ tz: tz(), day })}`),
  focus: (id: string, minutes: number, startedAt: string) => call<Json>(`/api/my-tasks/${id}/focus`, post({ minutes, started_at: startedAt })),
};
