// Client for the AI Employee registry (backend/app/agents/registry_api.py) and WS6's passport/ledger routes.
// Everything shown comes from these calls: there is no offline or seeded data.
// Calls go through the console's same-origin proxy (app/api/backend), which adds the signed-in user's session, so
// the backend answers as that person and shows only their workspace. API_URL is still where that proxy points.
export const BASE = "/api/backend";
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
  /** "agent": it made its own key and Agaxes holds only the public half. "agaxes" (or missing): Agaxes holds it. */
  key_custody?: "agent" | "agaxes";
  workspace_id?: string | null;
  /** User ids of the people (recruiters) who work with it. They see only the agents assigned to them. */
  assignees?: string[];
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
  /** Who caused the entry, from their session or the admin token, covered by the hash. Missing in open mode. */
  actor?: { via: string; email?: string; role?: string; user_id?: string; [k: string]: unknown } | null;
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
  const res = await fetch(`${BASE}${path}`, {
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
  /** The full ledger as the exact text the server sent, so the browser can re-hash it byte for byte. */
  ledgerText: async () => {
    const res = await fetch(`${BASE}/ledger`);
    if (!res.ok) throw new ApiError(`Backend returned ${res.status}`, res.status);
    return res.text();
  },
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
  health: () => req<Health>("/health"),
  /** Who is signed in and what they may see (the Next auth route reads the session cookie). */
  me: async () => {
    const res = await fetch("/api/auth/me", { cache: "no-store" });
    if (!res.ok) throw new ApiError(`Not signed in (${res.status})`, res.status);
    return (await res.json()) as Me;
  },
  companies: () => req<{ companies: Company[]; unassigned_agents: AgentStub[] }>("/platform/companies"),
  moveAgent: (id: string, workspace_id: string | null) => post<Agent>(`/platform/agents/${id}/workspace`, { workspace_id }, "PUT"),
  setAssignees: (id: string, user_ids: string[]) => post<Agent>(`/agents/${id}/assignees`, { user_ids }, "PUT"),
  workspace: () => req<Workspace>("/workspace"),
  members: () => req<{ members: Member[] }>("/workspace/members").then((r) => r.members),
  setRole: (id: string, role: WorkspaceRole) => post<Member>(`/workspace/members/${id}`, { role }, "PUT"),
  enrollments: () => req<Enrollment[]>("/agents/enrollments"),
  enroll: (b: { name: string; role: string; sponsor: Sponsor; scopes?: Scope[]; days?: number; job?: string; ttl_minutes?: number }) =>
    post<{ enrollment: Enrollment; token: string; command: string; note?: string }>("/agents/enrollments", b),
  revokeEnrollment: (id: string) => post<Enrollment>(`/agents/enrollments/${id}/revoke`),
  /** Signed audit export as a file download. JSONL is the evidence (signed manifest + entries); CSV is for reading. */
  exportLedger: async (format: "jsonl" | "csv", agentId?: string) => {
    const token = getAdminToken();
    const q = new URLSearchParams({ format, ...(agentId ? { agent_id: agentId } : {}) });
    const res = await fetch(`${BASE}/ledger/export?${q}`, { headers: token ? { "x-admin-token": token } : {} });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new ApiError(body?.detail ?? `Backend returned ${res.status}`, res.status);
    }
    const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? `agaxes-ledger.${format}`;
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return name;
  },
};

export interface Access {
  level: "platform" | "company" | "own_work";
  role: "operator" | "owner" | "admin" | "member" | "viewer";
  views: string[];
  summary: string;
}
export interface Me {
  user: { id: string; email: string; full_name: string; job_role: string | null; workspace_role: string; company_id: string };
  company: { id: string; name: string; domain: string } | null;
  access?: Access;
}
export interface AgentStub { agent_id: string; name: string; status: AgentStatus }
export interface Company {
  id: string;
  name: string;
  domain: string;
  verified_via?: string;
  created_at?: string;
  members: Member[];
  agents: AgentStub[];
}

export type AuthMode = "open" | "writes_protected" | "login_required";
export interface Health { ok: boolean; auth_mode?: AuthMode; llm_mode?: string; crustdata_mode?: string }
export type WorkspaceRole = "viewer" | "member" | "admin" | "owner";
export interface Workspace {
  auth_mode: AuthMode;
  via: "session" | "admin_token" | "open" | string;
  role: WorkspaceRole | "operator";
  company?: { id?: string; name?: string; domain?: string } | null;
  roles: { role: WorkspaceRole | "operator"; can: string }[];
}
export interface Member { id: string; email: string; full_name?: string | null; job_role?: string | null; workspace_role: WorkspaceRole; created_at?: string; last_login_at?: string | null }
export interface Enrollment {
  enrollment_id: string;
  name: string;
  role: string;
  sponsor: Sponsor;
  scopes: Scope[] | null;
  created_by: string;
  created_at: string;
  expires_at: string;
  used_at: string | null;
  revoked_at: string | null;
  agent_id: string | null;
  status: "pending" | "used" | "expired" | "revoked";
}

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
    schedule?: { candidate: string; company: string; slots: string[]; interviewer: string; minutes: number; invite: string; drafted_by: string }[];
  };
  approvals?: Approval[];
}

export interface Approval {
  approval_id: string;
  task_id: string;
  agent_id: string;
  agent_name: string;
  action: "send" | "sign_offer";
  to: Recipient;
  body: string;
  scope: Scope;
  status: "pending" | "sending" | "sent" | "signed" | "rejected" | "blocked_at_send" | "expired";
  preview: { decision: "allow" | "block"; checks: Check[]; ledger_entry?: string | null; note?: string };
  created_at: string;
  decided_at?: string | null;
  decided_by?: string | null;
  note?: string | null;
  result?: { sent?: boolean; signed?: boolean; decision?: string; checks?: Check[]; error?: string; ledger_entry?: string; approval_entry?: string;
    verify_url?: string | null; email?: { emailed: boolean; why?: string; delivered_to?: string } | null } | null;
  /** Company rules (Rules view): how many different people must approve, who has, and the rules that apply. */
  approvals_needed?: number;
  approvals?: { by: string; at: string; edited?: boolean }[];
  rules?: RuleHit[];
}

// ---- company rules (backend/app/rules) ----------------------------------------------------------------------------
export type RuleType = "offer_approvers" | "quiet_hours" | "blocked_companies" | "daily_cap";
export interface RuleHit { rule_id: string; version: number; name: string; sentence: string; type: RuleType; effect: "block" | "hold" | "approvers"; detail: string }
export interface RuleField { name: string; label: string; type: "money" | "number" | "time" | "select" | "text" | "list"; placeholder?: string; min?: number; max?: number; options?: string[]; option_labels?: Record<string, string> }
export interface RuleTemplate { type: RuleType; label: string; description: string; applies_to: string; fields: RuleField[]; example: Record<string, unknown>; example_sentence: string }
export interface RuleVersion { version: number; params: Record<string, unknown>; agents: string[]; enabled: boolean; name: string | null; sentence: string; at: string; by: string; change: string; note?: string | null }
export interface Rule {
  rule_id: string; workspace_id: string | null; type: RuleType; type_label: string; applies_to?: string; params: Record<string, unknown>;
  agents: string[]; agent_names: string[]; name: string | null; sentence: string; enabled: boolean; version: number;
  created_at: string; created_by: string; updated_at: string; updated_by: string; editable: boolean; enforced_count?: number;
  history?: RuleVersion[]; recent?: RuleEnforcement[];
}
export interface RuleEnforcement { ts: string; hash: string; seq: number; rule_id: string; version: number; name: string; sentence: string; effect: string; detail: string; action: string; outcome: string; agent_id?: string | null; agent_name?: string | null; to?: { name?: string; company?: string } }
export interface RulesView { rules: Rule[]; templates: RuleTemplate[]; recent: RuleEnforcement[]; can_edit: boolean }
export const rulesApi = {
  list: () => req<RulesView>("/rules"),
  get: (id: string) => req<Rule>(`/rules/${id}`),
  preview: (b: { type: RuleType; params: Record<string, unknown>; agents?: string[] }) =>
    post<{ ok: boolean; sentence?: string; error?: string }>("/rules/preview", b),
  create: (b: { type: RuleType; params: Record<string, unknown>; agents?: string[]; name?: string; enabled?: boolean }) => post<Rule>("/rules", b),
  update: (id: string, b: { params?: Record<string, unknown>; agents?: string[]; name?: string; enabled?: boolean; note?: string }) =>
    post<Rule>(`/rules/${id}`, b, "PUT"),
  remove: (id: string) => post<Rule>(`/rules/${id}`, {}, "DELETE"),
};

export interface FlowCheck { agent: string; scope: string; decision: "allow" | "deny"; why: string; ledger_entry?: string | null }
export interface FlowStage { key: string; label: string; scope: Scope; status: string; task_id: string | null; agent: string | null; checks: FlowCheck[] }
export interface Flow {
  flow_id: string; status: "running" | "done" | "stopped"; created_at: string; finished_at: string | null; by: string;
  input: { brief: string; role: string; compensation: string; start_date: string; interviewer: string; slots: string };
  stage: number; stages: FlowStage[]; hired: string[]; error: string | null; packet: string;
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
  runtime: { alive: boolean; started_at: string | null; running: number; max_concurrent: number; modes: { crustdata: string; llm: string };
    provider?: { out_of_credits: boolean; since: string | null; endpoint: string | null; message: string | null } };
  totals: { agents: number; working: number; queued: number; done_today: number; failed_today: number; pending_approvals: number; sent_today: number; blocked_today: number };
  agents: LiveAgent[];
  tasks: Task[];
  approvals: { pending: Approval[]; decided: Approval[] };
  schedules: Schedule[];
  flows?: Flow[];
  payroll: { enabled: boolean; every_minutes: number; last_run_at?: string | null; next_run_at?: string | null; running?: boolean;
    last_result?: { at: string; by: string; checked: number; suspended: string[]; error?: string; ledger_entry?: string } | null };
  ledger: { chain_ok: boolean; first_bad_seq: number | null };
}

export const receiptUrl = (hash: string) => `${BASE}/runtime/receipts/${hash}`;

export interface Template { key: string; name: string; role: string; scopes: Scope[]; job: string; hired: boolean; jobs: string[] }

export const runtime = {
  templates: () => req<Template[]>("/runtime/templates"),
  hire: (key: string) => post<{ agent: Agent; decision: "allow" | "block"; failed: Check[] }>("/runtime/hire", { key }),
  state: () => req<RuntimeState>("/runtime/state"),
  kinds: () => req<TaskKind[]>("/runtime/kinds"),
  task: (id: string) => req<Task>(`/runtime/tasks/${id}`),
  assign: (b: { agent_id: string; kind: string; input: Record<string, string>; by?: string }) => post<Task>("/runtime/tasks", b),
  cancel: (id: string) => post<Task>(`/runtime/tasks/${id}/cancel`, { by: "employer" }),
  retry: (id: string) => post<Task>(`/runtime/tasks/${id}/retry`, { by: "employer" }),
  approve: (id: string, body?: string) => post<Approval>(`/runtime/approvals/${id}/approve`, { by: "employer", body }),
  reject: (id: string, note?: string) => post<Approval>(`/runtime/approvals/${id}/reject`, { by: "employer", note }),
  pause: (id: string, reason?: string) => post<Policy>(`/runtime/agents/${id}/pause`, { by: "employer", reason }),
  resume: (id: string) => post<Policy>(`/runtime/agents/${id}/resume`, { by: "employer" }),
  suspend: (id: string, reason: string) => post<Agent>(`/runtime/agents/${id}/suspend`, { by: "employer", reason }),
  policy: (id: string, b: { require_approval?: boolean; budget?: Partial<Budget> }) => post<Policy>(`/runtime/agents/${id}/policy`, b, "PUT"),
  schedule: (b: { agent_id: string; kind: string; input: Record<string, string>; every_minutes: number }) => post<Schedule>("/runtime/schedules", b),
  toggleSchedule: (id: string) => post<Schedule>(`/runtime/schedules/${id}/toggle`),
  deleteSchedule: (id: string) => post<{ deleted: string }>(`/runtime/schedules/${id}`, undefined, "DELETE"),
  setPayroll: (b: { enabled?: boolean; every_minutes?: number }) => post<RuntimeState["payroll"]>("/runtime/payroll", b, "PUT"),
  startFlow: (b: { brief: string; compensation?: string; start_date?: string }) => post<Flow>("/runtime/flows", b),
  runPayroll: () => post<NonNullable<RuntimeState["payroll"]["last_result"]>>("/runtime/payroll/run"),
};

// ---- connecting an agent (backend/app/agents/connect_api.py) -------------------------------------------------------

export type Risk = "low" | "medium" | "high" | "critical";
export type AgentTypeKey = "template" | "claude_code" | "mcp" | "http";
export interface CatalogScope { key: Scope; label: string; risk: Risk; allows: string; never: string; who_can_grant: string; needs_review: boolean }
export interface CatalogTool { key: string; label: string; kind: "data" | "action"; needs: Scope[]; detail: string }
export interface CatalogTemplate { key: string; name: string; role: string; scopes: Scope[]; tools: string[]; job: string; jobs: string[] }
export interface CatalogType { key: AgentTypeKey; label: string; runtime: "in-house" | "own"; detail: string }
export interface Catalog {
  agent_types: CatalogType[];
  templates: CatalogTemplate[];
  scopes: CatalogScope[];
  tools: CatalogTool[];
  roles: Role[];
  budget_defaults: Budget;
  budget_limits: Budget;
}
export interface OrgPerson { user_id: string; name: string; email: string; job_role?: string | null; workspace_role: WorkspaceRole; can_own: boolean; why_not?: string | null }
export interface SponsorMatch {
  name: string | null;
  profile_url: string;
  title: string | null;
  company: string | null;
  domain?: string | null;
  works_there: boolean;
  grants: Partial<Record<Scope, boolean>>;
  found?: boolean;
  error?: string;
}
export type ConnectStatus = "pending_review" | "approved" | "rejected" | "awaiting_agent" | "enrolled" | "connected" | "failed" | "cancelled";
export interface ConnectRequest {
  request_id: string;
  agent_type: AgentTypeKey;
  template: string | null;
  runtime: "in-house" | "own";
  name: string;
  job: string | null;
  role: string;
  scopes: Scope[];
  tools: string[];
  budget: Partial<Budget>;
  require_approval: boolean;
  days: number;
  sponsor: Sponsor;
  owner: { user_id: string; name: string; email: string; workspace_role: WorkspaceRole } | null;
  risk: Risk;
  review: { required: boolean; scopes: Scope[]; decision: "approve" | "reject" | null; by: string | null; at: string | null; note: string | null; sole_admin: boolean };
  status: ConnectStatus;
  requested_by: string;
  requested_by_id: string | null;
  created_at: string;
  enrollment_id: string | null;
  enrollment_status?: string | null;
  expires_at?: string;
  agent_id: string | null;
  agent_status?: AgentStatus;
  first_seen_at?: string | null;
  test: { at: string; via: string; ledger_entry: string } | null;
  verdict: Verdict | null;
  ledger: string[];
}
export interface IssueResult {
  request: ConnectRequest;
  agent?: Agent;
  verdict?: Verdict;
  token?: string;
  command?: string;
  mcp_command?: string;
  mcp_config?: string;
}

export const connectApi = {
  catalog: () => req<Catalog>("/connect/catalog"),
  people: () => req<{ members: OrgPerson[]; me: string | null; note?: string }>("/connect/people"),
  findSponsor: (b: { name: string; company: string; scopes?: Scope[] }) =>
    post<{ matches: SponsorMatch[]; error?: string | null; note?: string | null }>("/connect/sponsor/find", b),
  checkSponsor: (b: { profile_url: string; company: string; scopes?: Scope[] }) => post<SponsorMatch>("/connect/sponsor/check", b),
  create: (b: Record<string, unknown>) => post<ConnectRequest>("/connect/requests", b),
  list: () => req<ConnectRequest[]>("/connect/requests"),
  get: (id: string) => req<ConnectRequest>(`/connect/requests/${id}`),
  approve: (id: string, note = "") => post<ConnectRequest>(`/connect/requests/${id}/approve`, { note }),
  reject: (id: string, note = "") => post<ConnectRequest>(`/connect/requests/${id}/reject`, { note }),
  issue: (id: string) => post<IssueResult>(`/connect/requests/${id}/issue`),
  test: (id: string) => post<{ request: ConnectRequest; connected: boolean; waiting_for?: string; error?: string; first_seen_at?: string }>(`/connect/requests/${id}/test`),
  cancel: (id: string) => post<ConnectRequest>(`/connect/requests/${id}/cancel`),
};

// ---- emergency stop (backend/app/runtime/freeze.py) --------------------------------------------------

export type FreezeScope = "agent" | "sponsor" | "all";
export type FreezeOutcome = "restored" | "still_suspended" | "was_suspended_before" | "held_elsewhere" | "gone" | string | null;
export interface Person { name?: string | null; company?: string | null; profile_url?: string | null; email?: string | null; events?: number; last?: string | null }
export interface BlastAgent {
  agent_id: string;
  name: string;
  status?: AgentStatus;
  sponsor?: Sponsor;
  messages_sent: { ts: string | null; to?: Person | null; what: string; how?: string; hash?: string | null }[];
  people: Person[];
  data: { crustdata_calls: number; llm_calls: number; records: number; reads: { ts: string; what: string; kind?: string; status?: string; crustdata?: number; sources?: number }[] };
  approvals: { approval_id: string; action: string; status: string; to?: Person | null; created_at?: string; decided_at?: string | null; decided_by?: string | null }[];
  guard: { checked: number; blocked: number };
  rules_blocked: number;
  spend: { crustdata_calls: number; llm_calls: number; sends: number; offers_signed: number; offer_ctc_lpa: number };
  tasks: { total: number; [status: string]: number };
  ledger: { entries: number; kinds: [string, number][]; first_seq: number | null; last_seq: number | null };
}
export interface Blast {
  since: string;
  until: string;
  hours: number;
  totals: {
    agents: number; messages_sent: number; people: number; crustdata_calls: number; llm_calls: number; records: number;
    approvals: number; pending_approvals: number; tasks: number; running: number; guard_blocked: number; rules_blocked: number;
    offers_signed: number; ledger_entries: number;
  };
  agents: BlastAgent[];
}
export interface FreezeAgent { agent_id: string; name: string; prior_status: AgentStatus; sponsor: Sponsor; outcome: FreezeOutcome; still_reason?: string | null; held_by?: string }
export interface Freeze {
  freeze_id: string;
  scope: FreezeScope;
  target: string | null;
  label: string;
  reason: string;
  by: string;
  at: string;
  status: "active" | "lifted";
  agents: FreezeAgent[];
  stopped_tasks: { task_id: string; agent_id: string; title: string; kind: string; was: "running" | "queued" }[];
  pulled_approvals: { approval_id: string; agent_id: string; to?: Person | null; action: string }[];
  schedules_off: string[];
  blast: Blast;
  ledger_entry: string;
  restored_at: string | null;
  restored_by: string | null;
  restore_entry: string | null;
  bring_back?: boolean;
  requeued_tasks?: string[];
  returned_approvals?: string[];
}
export interface SponsorGroup { key: string; name: string; title?: string | null; company?: string; profile_url?: string; agents: { agent_id: string; name: string; status: AgentStatus }[] }
export interface FreezePreview {
  scope: FreezeScope;
  target: string | null;
  label: string;
  agents: { agent_id: string; name: string; status: AgentStatus; sponsor: Sponsor }[];
  will: { suspend: string[]; already_suspended: string[]; running_tasks: number; queued_tasks: number; pending_approvals: number; schedules: number };
  blast: Blast;
}

export const estop = {
  overview: () => req<{ active: Freeze[]; history: Freeze[]; sponsors: SponsorGroup[] }>("/runtime/freeze"),
  preview: (scope: FreezeScope, target?: string | null) => post<FreezePreview>("/runtime/freeze/preview", { scope, target: target ?? null }),
  freeze: (scope: FreezeScope, target: string | null, reason: string) => post<Freeze>("/runtime/freeze", { scope, target, reason }),
  restore: (id: string, bring_back: boolean) => post<Freeze>(`/runtime/freeze/${id}/restore`, { bring_back }),
  blast: (agentIds: string[], hours = 24) =>
    req<Blast>(`/runtime/freeze/blast?${new URLSearchParams([...agentIds.map((a) => ["agent_id", a]), ["hours", String(hours)]])}`),
};
