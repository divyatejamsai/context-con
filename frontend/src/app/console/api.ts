// Client for the AI Employee registry (backend/app/agents/registry_api.py) and WS6's passport/ledger routes.
// Everything shown comes from these calls: there is no offline or seeded data.
import { API_URL } from "@/lib/stream";
import type { Source } from "@/lib/types";

export type Scope = "outreach.hiring" | "outreach.sales" | "data.read" | "contract.sign" | "payment.send";
export type AgentStatus = "active" | "suspended" | "offboarded";
export type ReviewDecision = "keep" | "restrict" | "offboard";

export interface Sponsor {
  name: string;
  profile_url: string;
  company: string;
  company_domain?: string | null;
  title?: string | null;
}

export interface Recipient {
  name: string;
  profile_url: string;
  company: string;
}

export interface Passport {
  agent_id: string;
  agent_name: string;
  role: string;
  sponsor: Sponsor;
  scopes: Scope[];
  issued_at: string;
  expires_at: string;
  public_key: string;
  issuer_key_id?: string;
  issuer_signature?: string;
}

export interface Check {
  id: string;
  name: string;
  status: "pass" | "fail" | "unverifiable";
  detail: string;
  source?: Source | null;
}

export interface Verdict {
  subject: string;
  decision: "allow" | "block";
  checks: Check[];
  ledger_entry?: string | null;
}

export interface Scorecard {
  messages_checked: number;
  allowed: number;
  blocked: number;
  block_reasons: [string, number][];
  sponsor_checks: number;
  sponsor_checks_failed: number;
  ledger_entries: number;
  last_activity: string | null;
  work_filed?: number;
  work_by_kind?: [string, number][];
  recent_work?: { seq: number; ts: string; kind: string; summary: string | null; sources: number }[];
}

export interface Review {
  id: string;
  at: string;
  reviewer: string;
  decision: ReviewDecision;
  notes: string;
  scopes?: Scope[] | null;
  scorecard: Scorecard;
  ledger_entry?: string;
}

export interface Agent {
  agent_id: string;
  employee_no: number;
  name: string;
  role: string;
  job?: string | null;
  runtime?: "in-house" | "external" | string;
  status: AgentStatus;
  reason: string | null;
  suspended_by: string | null;
  onboarded_at: string;
  offboarded_at?: string;
  last_checked: string | null;
  last_verdict: Verdict | null;
  passport: Passport;
  reviews: Review[];
  ledger_entries: string[];
  scorecard?: Scorecard;
}

export interface Role {
  key: string;
  title: string;
  summary: string;
  default_scopes: Scope[];
  ceiling: Scope[];
}

export interface Scenario {
  id: string;
  story: string;
  sponsor: Sponsor;
  scopes: Scope[];
  expect: "allow" | "block";
  failing_check?: string;
}

export interface LedgerEntry {
  seq: number;
  ts: string;
  kind: string;
  payload: Record<string, unknown>;
  sources: Source[];
  prev_hash: string;
  hash: string;
}

export interface LedgerView {
  chain_ok: boolean;
  first_bad_seq: number | null;
  entries: LedgerEntry[];
}

export const SCOPE_INFO: Record<Scope, { label: string; detail: string }> = {
  "outreach.hiring": { label: "Hiring outreach", detail: "Contact candidates about open roles" },
  "outreach.sales": { label: "Sales outreach", detail: "Contact prospects on the company's behalf" },
  "data.read": { label: "Read data", detail: "Look up people and companies" },
  "contract.sign": { label: "Sign contracts", detail: "Commit the company to terms" },
  "payment.send": { label: "Send payments", detail: "Move the company's money" },
};

export class ApiError extends Error {
  constructor(message: string, public status: number, public verdict?: Verdict) {
    super(message);
  }
}

// Admin token for changes (backend COUNTERSIGN_ADMIN_TOKEN). Kept in this browser only; reads never need it.
const TOKEN_KEY = "countersign.admin-token";
export function getAdminToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}
export function setAdminToken(t: string) {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {}
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAdminToken();
  const res = await fetch(`${API_URL}/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(token ? { "x-admin-token": token } : {}), ...(init?.headers ?? {}) },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(body?.detail ?? `Backend returned ${res.status}`, res.status, body?.verdict);
  return body as T;
}

const post = <T,>(path: string, body?: unknown, method = "POST") =>
  req<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  agents: () => req<Agent[]>("/agents"),
  agent: (id: string) => req<Agent>(`/agents/${id}`),
  roles: () => req<{ roles: Role[]; scopes: Scope[] }>("/agents/roles"),
  scenarios: () => req<{ scenarios: Scenario[] }>("/passport/scenarios").then((r) => r.scenarios),
  ledger: (agentId?: string) => req<LedgerView>(`/ledger${agentId ? `?agent_id=${encodeURIComponent(agentId)}` : ""}`),
  onboard: (b: { name: string; role: string; sponsor: Sponsor; scopes?: Scope[]; days?: number; job?: string; runtime?: string }) =>
    post<{ agent: Agent; verdict: Verdict }>("/agents", b),
  payroll: () => post<Verdict[]>("/agents/recheck"),
  recheck: (id: string) => post<{ agent: Agent; verdict: Verdict }>(`/agents/${id}/recheck`),
  suspend: (id: string, reason: string) => post<Agent>(`/agents/${id}/suspend`, { reason }),
  reinstate: (id: string) => post<{ agent: Agent; verdict: Verdict }>(`/agents/${id}/reinstate`),
  offboard: (id: string, reason: string) => post<Agent>(`/agents/${id}/offboard`, { reason }),
  scopes: (id: string, scopes: Scope[]) => post<{ agent: Agent; verdict: Verdict | null }>(`/agents/${id}/scopes`, { scopes }, "PUT"),
  send: (id: string, b: { to: Recipient; body: string; scope: Scope; signed_body?: string }) =>
    post<{ verdict: Verdict; sent: boolean }>(`/agents/${id}/send`, b),
  verify: (passport: Passport, scope?: Scope) => post<Verdict>("/passport/verify", { passport, scope: scope ?? null }),
  review: (id: string, b: { reviewer: string; decision: ReviewDecision; notes: string; scopes?: Scope[] }) =>
    post<Agent>(`/agents/${id}/reviews`, b),
};

// ---- Agent runtime (backend/app/runtime, docs/RUNTIME.md): tasks, approvals, budgets, schedules -------------

export type TaskStatus = "queued" | "running" | "done" | "failed" | "cancelled" | "refused";
export type Activity = "working" | "idle" | "paused" | "waiting_on_you" | "suspended" | "offboarded";

export interface TaskKind {
  kind: string;
  label: string;
  scope: Scope;
  agent_hint?: string | null;
  description: string;
  fields: { name: string; label: string; type: "text" | "textarea"; required: boolean; placeholder?: string }[];
}

export interface SendRecord {
  to: Recipient;
  scope: Scope;
  body: string;
  decision: "allow" | "block";
  state: "blocked" | "pending_approval" | "sent" | "rejected" | "blocked_at_send" | "expired";
  approval_id?: string | null;
  guard_entry?: string | null;
  checks: Check[];
}

export interface Task {
  task_id: string;
  agent_id: string;
  agent_name: string;
  kind: string;
  title: string;
  status: TaskStatus;
  waiting_on?: string | null;
  assigned_by: string;
  schedule_id?: string | null;
  ref?: { kind: string; id: string } | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  seconds?: number | null;
  attempts: number;
  progress: { done: number; total: number; label: string };
  usage: { crustdata: number; llm: number; sends: number };
  result?: string | null;
  error?: string | null;
  ledger: string[];
  last_step?: string | null;
  counts?: { sends: number; findings: number; shortlist: number; artifacts: number };
  steps?: { ts: string; kind: string; text: string }[];
  input?: Record<string, string>;
  output?: {
    clock_in?: { decision: "allow" | "block"; headline: string; ledger_entry?: string; failed: Check[] };
    sends?: SendRecord[];
    shortlist?: { name: string; title?: string; company?: string; location?: string; score?: number; profile_url?: string; reasons?: string[]; guard?: string }[];
    findings?: { candidate: string; profile_url?: string; verified: number; total: number; contradicted: { claim: string; evidence: string; source?: Source | null }[] }[];
    artifacts?: { kind: string; title: string; path?: string; content?: string }[];
    filed?: { kind: string; summary: string; ledger_entry: string }[];
  };
  approvals?: Approval[];
}

export interface Approval {
  approval_id: string;
  task_id: string;
  agent_id: string;
  agent_name: string;
  action: "send";
  to: Recipient;
  body: string;
  scope: Scope;
  status: "pending" | "sending" | "sent" | "rejected" | "blocked_at_send" | "expired";
  preview: { decision: "allow" | "block"; checks: Check[]; ledger_entry?: string | null };
  created_at: string;
  decided_at?: string | null;
  decided_by?: string | null;
  note?: string | null;
  result?: { sent: boolean; decision?: string; checks?: Check[]; error?: string; ledger_entry?: string; approval_entry?: string } | null;
}

export interface Budget {
  tasks_per_day: number;
  sends_per_day: number;
  crustdata_calls_per_day: number;
  llm_calls_per_day: number;
}

export interface Policy {
  paused: boolean;
  paused_reason?: string | null;
  require_approval: boolean;
  budget: Budget;
}

export interface ReportCard {
  tasks_total: number;
  done: number;
  failed: number;
  refused: number;
  cancelled: number;
  success_rate: number | null;
  avg_seconds: number | null;
  drafts: number;
  guard_blocked: number;
  sent: number;
  pending_approval: number;
  rejected: number;
  blocked_at_send: number;
  findings: number;
  false_claims: number;
  approval_rate: number | null;
  filed: number;
  crustdata_calls: number;
  llm_calls: number;
  last_active: string | null;
}

export interface LiveAgent {
  agent_id: string;
  name: string;
  role: string;
  job?: string | null;
  runtime?: string;
  employee_no?: number;
  status: AgentStatus;
  reason?: string | null;
  sponsor: Sponsor;
  scopes: Scope[];
  activity: Activity;
  policy: Policy;
  usage_today: { tasks: number; sends: number; crustdata: number; llm: number };
  kinds: string[];
  current: Task | null;
  queued: number;
  metrics: ReportCard;
}

export interface Schedule {
  schedule_id: string;
  agent_id: string;
  agent_name: string;
  kind: string;
  title: string;
  input: Record<string, string>;
  every_minutes: number;
  enabled: boolean;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_task_id?: string | null;
  last_skip?: string | null;
  runs: number;
}

export interface RuntimeState {
  version: number;
  runtime: { alive: boolean; started_at: string | null; running: number; max_concurrent: number; modes: { crustdata: string; llm: string } };
  totals: { agents: number; working: number; queued: number; done_today: number; failed_today: number; pending_approvals: number; sent_today: number; blocked_today: number };
  agents: LiveAgent[];
  tasks: Task[];
  approvals: { pending: Approval[]; decided: Approval[] };
  schedules: Schedule[];
  payroll: { enabled: boolean; every_minutes: number; last_run_at?: string | null; next_run_at?: string | null; running?: boolean;
    last_result?: { at: string; by: string; checked: number; suspended: string[]; error?: string; ledger_entry?: string } | null };
  ledger: { chain_ok: boolean; first_bad_seq: number | null };
}

export const receiptUrl = (hash: string) => `${API_URL}/api/runtime/receipts/${hash}`;

export const runtime = {
  state: () => req<RuntimeState>("/runtime/state"),
  kinds: () => req<TaskKind[]>("/runtime/kinds"),
  task: (id: string) => req<Task>(`/runtime/tasks/${id}`),
  assign: (b: { agent_id: string; kind: string; input: Record<string, string>; by?: string }) => post<Task>("/runtime/tasks", b),
  cancel: (id: string) => post<Task>(`/runtime/tasks/${id}/cancel`, { by: "employer" }),
  retry: (id: string) => post<Task>(`/runtime/tasks/${id}/retry`, { by: "employer" }),
  approve: (id: string) => post<Approval>(`/runtime/approvals/${id}/approve`, { by: "employer" }),
  reject: (id: string, note?: string) => post<Approval>(`/runtime/approvals/${id}/reject`, { by: "employer", note }),
  pause: (id: string, reason?: string) => post<Policy>(`/runtime/agents/${id}/pause`, { by: "employer", reason }),
  resume: (id: string) => post<Policy>(`/runtime/agents/${id}/resume`, { by: "employer" }),
  suspend: (id: string, reason: string) => post<Agent>(`/runtime/agents/${id}/suspend`, { by: "employer", reason }),
  policy: (id: string, b: { require_approval?: boolean; budget?: Partial<Budget> }) => post<Policy>(`/runtime/agents/${id}/policy`, b, "PUT"),
  schedule: (b: { agent_id: string; kind: string; input: Record<string, string>; every_minutes: number }) => post<Schedule>("/runtime/schedules", b),
  toggleSchedule: (id: string) => post<Schedule>(`/runtime/schedules/${id}/toggle`),
  deleteSchedule: (id: string) => post<{ deleted: string }>(`/runtime/schedules/${id}`, undefined, "DELETE"),
  setPayroll: (b: { enabled?: boolean; every_minutes?: number }) => post<RuntimeState["payroll"]>("/runtime/payroll", b, "PUT"),
  runPayroll: () => post<NonNullable<RuntimeState["payroll"]["last_result"]>>("/runtime/payroll/run"),
};
