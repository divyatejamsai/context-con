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
  /** The full ledger as the exact text the server sent, so the browser can re-hash it byte for byte. */
  ledgerText: async () => {
    const res = await fetch(`${API_URL}/api/ledger`);
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
};
