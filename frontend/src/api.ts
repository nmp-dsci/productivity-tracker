// Typed client for /api/*. Shapes mirror src/pt/api/queries.py.

export type Cell = { d: string; v: number };
export type TrendRow = {
  key: string; label: string; note: string; total: number; active: number;
  spark: number[]; growth: { wow: number | null; w4: number | null }; cells: Cell[];
};
export type Trends = { grain: 'day' | 'week'; window: number; start: string; end: string; rows: TrendRow[] };

export type Ship = { ts: string; day: string; source: string; kind: string; project: string | null; repo?: string | null; branch?: string | null; title: string | null; status: string | null; url?: string | null; number?: number | null };
export type Overview = {
  week_start: string; week_end: string; kpis: Record<string, number>; prior: Record<string, number>;
  projects: { project: string; tok_out: number; cost_usd: number; commits: number; prs: number; pages: number; deploys: number }[];
  split: { cls: string; tok_out: number; cost_usd: number }[]; shiplog: Ship[];
};
export type Session = { session_id?: string; source: string; project: string | null; branch?: string | null; first_ts: string; last_ts: string; seconds: number; messages: number; prompts: number; tok_out: number; cost_usd: number; cls: string; models?: string[]; subagent_msgs: number };
export type Agents = {
  start: string; end: string;
  by_day_model: { day: string; model: string; tok_out: number; tok_in: number; tok_cr: number; tok_cw: number; cost_usd: number; msgs: number }[];
  by_class: { cls: string; tok_out: number; cost_usd: number; msgs: number }[];
  by_project: { project: string; cls: string; tok_out: number; cost_usd: number }[];
  tools: { tool: string; sessions: number }[];
  cache: { cache_read: number; uncached: number; cache_write: number };
  sessions: Session[];
};
export type GitHub = {
  start: string; end: string;
  commits: { day: string; project: string | null; commits: number; insertions: number; deletions: number }[];
  prs: Ship[];
  ci: { day: string; passed: number; failed: number; runs: number }[];
  branches: { project: string; branch?: string; commits: number; first_day: string; last_day: string }[];
  gates: { day: string; status: string; n: number }[];
};
export type Project = { project: string; tok_out: number; agent_usd: number; aws_usd: number; commits: number; prs: number; pages: number; eval_runs: number; deploys: number; last_deploy: string | null; last_active: string };
export type ProjectDetail = { project: string; daily: { day: string; tok_out: number; cost_usd: number; commits: number; pages: number }[]; split: { cls: string; tok_out: number }[]; shiplog: Ship[] };
export type Health = { ok: boolean; version: string; demo: boolean; rollups_at: string | null };

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
  return (await r.json()) as T;
}

export const api = {
  health: () => get<Health>('/api/health'),
  trends: (grain: 'day' | 'week', window: number) => get<Trends>(`/api/trends?grain=${grain}&window=${window}`),
  overview: (week?: string) => get<Overview>(`/api/overview${week ? `?week=${week}` : ''}`),
  agents: (days: number) => get<Agents>(`/api/agents?days=${days}`),
  github: (days: number) => get<GitHub>(`/api/github?days=${days}`),
  projects: (days: number) => get<Project[]>(`/api/projects?days=${days}`),
  project: (name: string, days: number) => get<ProjectDetail>(`/api/projects/${encodeURIComponent(name)}?days=${days}`),
  shiplog: (limit: number) => get<Ship[]>(`/api/shiplog?limit=${limit}`),
  weekly: (week?: string) => get<{ week_start: string; narrative: string | null }>(`/api/weekly${week ? `?week=${week}` : ''}`),
};
