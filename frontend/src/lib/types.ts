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

// Accept older/alternate step names from fixtures.
export const STEP_ALIASES: Record<string, string> = { parse_brief: "parse" };
export const canonicalStep = (s?: string) => (s ? STEP_ALIASES[s] ?? s : s);
