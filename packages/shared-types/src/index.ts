import seed from "../seed/agents.json";

export interface SeedAgent {
  id: string;
  key: string;
  name: string;
  role: string;
  home_district: string;
  avatar: { shape: string; color: string; height: number };
  model: { provider: string; model: string };
  tools: string[];
  limits: { max_usd_per_mission: number; max_concurrent_tasks: number };
}

export const SEED = seed as { organization_id: string; project_id: string; agents: SeedAgent[] };

export interface MissionRow {
  id: string;
  title: string;
  prompt: string;
  status: string;
  execution_mode: "live" | "simulation";
  budget_usd: number;
  spent_usd_estimated: number;
  failure_reason: string | null;
  outcome: string | null;
  paused: number;
  pause_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApprovalRow {
  id: string;
  mission_id: string;
  task_id: string;
  action: string;
  summary: string;
  status: string;
  created_at: string;
}
