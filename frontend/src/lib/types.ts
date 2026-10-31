// Mirrors the SSE contract in CONTEXT.md section 6 and backend/app/schemas.py.
// Every field the backend might omit is optional here so the UI never crashes on partial data.

export type ClaimStatus = "verified" | "contradicted" | "unverifiable";

export interface Source {
  endpoint: string;
  field?: string | null;
  url?: string | null;
}

export interface Claim {
  id: string;
  claim: string;
  status: ClaimStatus;
  evidence?: string;
  source?: Source | null;
}

export interface Reason {
  text: string;
  claim_ids?: string[];
}

export interface Candidate {
  id: string;
  name: string;
  title?: string | null;
  company?: string | null;
  location?: string | null;
  profile_url?: string | null;
  score?: number;
  reasons?: Reason[];
  claims?: Claim[];
  flags?: string[];
  outreach_draft?: string | null;
  guard?: Guard | null; // Send Guard verdict on the outreach draft (agent runs only)
  outreach_subject?: string | null;
  contact?: Contact | null; // email Crustdata has on record (agent runs, shortlisted candidates)
  outreach?: { status: string; detail: string; message?: OutboundMessage | null } | null; // set when the run auto-sent
}

// Email address from Crustdata Person Enrich (contact field). Never guessed.
export interface Contact {
  profile_url: string;
  email?: string | null;
  kind?: "business" | "personal" | string | null;
  status?: string | null; // Crustdata's status, e.g. "deliverable"
  last_updated?: string | null;
  options?: { email: string; kind: string; status?: string | null }[];
  source?: Source | null;
  note?: string;
  error?: string | null;
}

export interface MessageEvent {
  ts: string;
  status: string;
  detail?: string;
}

export interface Reply {
  message_id: string;
  from: string;
  subject?: string;
  date?: string;
  text: string;
}

// A real email sent (or refused) through Send Guard. backend/app/outbound/messages.py
export interface OutboundMessage {
  id: string;
  created_at: string;
  status: "sent" | "delivered" | "opened" | "clicked" | "replied" | "bounced" | "complained" | "blocked" | "failed" | "delivery_delayed" | string;
  detail?: string;
  to: { name?: string; profile_url?: string; company?: string };
  subject: string;
  body: string;
  intended_to?: string;
  delivered_to?: string;
  mode?: "test" | "live";
  provider?: string;
  guard?: Guard;
  contact?: Contact;
  events: MessageEvent[];
  replies: Reply[];
  ledger_entry?: string;
}

export interface OutboundConfig {
  provider: string;
  mode: "test" | "live" | string;
  ready: boolean;
  reason: string;
  test_to?: string | null;
  from?: string | null;
  reply_to?: string | null;
  replies: boolean;
}

export interface SendResult {
  ok: boolean;
  status: string;
  detail: string;
  message?: OutboundMessage | null;
  verdict?: Guard | null;
  contact?: Contact | null;
}

// Countersign checks: the passport check before a run, and Send Guard on each draft.
export interface GuardCheck {
  id?: string;
  name: string;
  status: "pass" | "fail" | "unverifiable";
  detail?: string;
  source?: Source | null;
}

export interface Guard {
  decision: "allow" | "block";
  checks?: GuardCheck[];
  ledger_entry?: string | null;
  error?: string;
}

export interface PassportCheck extends Guard {
  agent_id?: string;
  message?: string;
}

export interface Criteria {
  role?: string;
  title_variants?: string[];
  seniority?: string | null;
  skills?: string[];
  locations?: string[];
  company_preferences?: string[];
  must_haves?: string[];
  nice_to_haves?: string[];
  schools?: string[];
  degrees?: string[];
  education_note?: string | null;
}

export interface Summary {
  searched?: number;
  enriched?: number;
  shortlisted?: number;
  [k: string]: number | undefined;
}

export type RunEvent =
  | { type: "step"; step: string; message: string; data?: { criteria?: Criteria; order?: string[]; shortlist?: string[]; near_miss?: string[]; [k: string]: unknown } | null; ts?: string }
  | { type: "candidate"; candidate: Candidate; ts?: string }
  | { type: "criteria"; criteria: Criteria; ts?: string }
  | { type: "error"; step?: string; message: string; ts?: string }
  | { type: "done"; summary?: Summary; ts?: string };

export const PIPELINE_STEPS = ["parse", "search", "enrich", "verify", "rank", "outreach"] as const;
// Agent runs (/api/agents/{id}/run) wrap the pipeline in a passport check and Send Guard.
export const AGENT_STEPS = ["passport", ...PIPELINE_STEPS, "guard"] as const;
export const AUTOSEND_STEPS = [...AGENT_STEPS, "send"] as const;

// Accept older/alternate step names from fixtures.
export const STEP_ALIASES: Record<string, string> = { parse_brief: "parse" };
export const canonicalStep = (s?: string) => (s ? STEP_ALIASES[s] ?? s : s);
